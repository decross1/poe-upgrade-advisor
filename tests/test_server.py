import base64
import json
import threading
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jsonschema
import pytest
import yaml

from server.app import BASE_PATH, ApiApplication, BuildStore, create_server
from server.assumptions import AssumptionsEvaluator
from server.calculator import (
    EngineDiff,
    EngineTreePlan,
    ImportedBuild,
    ItemParseError,
    decode_pob_code,
    extract_build_facts,
)

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_XML = b"""<?xml version="1.0"?>
<PathOfBuilding>
  <Build level="91" className="Witch" ascendClassName="Occultist"
         mainSocketGroup="1"/>
  <Skills>
    <Skill enabled="true" mainActiveSkill="1">
      <Gem enabled="true" gemId="Metadata/Items/Gems/SkillGemArc"
           skillId="Arc" nameSpec="Arc"/>
      <Gem enabled="true" gemId="Metadata/Items/Gems/SupportGemAddedLightningDamage"
           skillId="SupportAddedLightningDamage" nameSpec="Added Lightning Damage"/>
    </Skill>
  </Skills>
</PathOfBuilding>
"""


class StubCalculator:
    def __init__(self, facts: Mapping[str, Any] | None = None) -> None:
        self.facts = facts or {
            "active_skills": [
                {"name": "Arc", "links": 6, "dps": 100, "tags": []}
            ],
            "allocated_keystone": None,
            "has_charge_generation": None,
            "has_trigger_setup": False,
        }
        self.configurations: list[dict[str, Any]] = []

    def import_build(self, pob_code: str) -> ImportedBuild:
        return ImportedBuild("b-stub", self.facts)

    def configure_build(
        self, canonical_config: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.configurations.append(dict(canonical_config))
        return {"base_class": "Witch", "ascendancy": "Occultist", "level": 91}

    def diff(
        self, item_text: str, canonical_config: Mapping[str, Any]
    ) -> EngineDiff:
        self.configurations.append(dict(canonical_config))
        if item_text in {"", "unparseable"}:
            raise ItemParseError("test item is unparseable")
        candidates = {
            "upgrade": (110, 110),
            "bigger-upgrade": (130, 120),
            "sidegrade": (101, 99),
            "downgrade": (90, 90),
            "zero-baseline": (1, 100),
        }
        try:
            candidate_dps, candidate_ehp = candidates[item_text]
        except KeyError as error:
            raise ItemParseError("test item is unparseable") from error
        baseline_dps = 0 if item_text == "zero-baseline" else 100
        return EngineDiff(
            {
                "baseline": {"total_dps": baseline_dps, "ehp": 100},
                "candidate": {
                    "total_dps": candidate_dps,
                    "ehp": candidate_ehp,
                },
                "deltas": {
                    "total_dps": candidate_dps - baseline_dps,
                    "ehp": candidate_ehp - 100,
                },
                "slot": "Weapon 1",
                "breakdown_ref": "pob://calcs/Weapon 1",
            },
            4.3,
        )

    def tree_suggestions(
        self, points: int, canonical_config: Mapping[str, Any]
    ) -> EngineTreePlan:
        self.configurations.append(dict(canonical_config))
        bossing = canonical_config.get("enemyIsBoss") == "PINNACLE"
        node_id = 54321 if bossing else 26725
        offense = 2.4 if bossing else 1.8
        return EngineTreePlan(
            suggestions=(
                {
                    "step": 1,
                    "node_id": node_id,
                    "node_name": (
                        "Bossing Power" if bossing else "Mapping Power"
                    ),
                    "offense_delta_pct": offense,
                    "defense_delta_pct": 0.0,
                    "combined_score": round(0.8 * offense, 3),
                    "path_cost": 1,
                    "path_node_ids": [node_id],
                },
            ),
            compute_ms=12.4,
        )

    def close(self) -> None:
        return


@pytest.fixture
def evaluator() -> AssumptionsEvaluator:
    return AssumptionsEvaluator(ROOT / "assumptions")


@pytest.fixture
def calculator() -> StubCalculator:
    return StubCalculator()


@pytest.fixture
def app(
    evaluator: AssumptionsEvaluator, calculator: StubCalculator
) -> ApiApplication:
    return ApiApplication(calculator, evaluator, BuildStore())


def import_stub_build(app: ApiApplication) -> dict[str, Any]:
    status, build = app.dispatch(
        "POST", f"{BASE_PATH}/build", {"pob_code": "stub"}
    )
    assert status == 200
    assert build is not None
    return build


def test_evaluator_loads_data_matches_rules_and_honors_overrides(
    evaluator: AssumptionsEvaluator,
) -> None:
    result = evaluator.evaluate(
        {
            "active_skills": [
                {"name": "Arc", "links": 6, "dps": 100, "tags": ["shock"]}
            ],
            "allocated_keystone": "Elemental Overload",
            "has_charge_generation": "power",
        },
        "mapping",
        [{"assumption_id": "config.flasks_up", "value": False}],
    )
    assert result.main_skill == "Arc"
    assert result.pob_config["enemyLevel"] == 84
    assert result.pob_config["flasks_active"] is False
    assert {item["id"] for item in result.assumptions} >= {
        "main_skill.most_linked_highest_dps",
        "config.elemental_overload",
        "config.shock_from_setup",
        "config.flasks_up",
        "config.power_charges_from_generation",
    }
    assert result.confidence == 0.7
    assert not result.cant_evaluate


def test_trigger_penalty_is_one_tap_reversible(
    evaluator: AssumptionsEvaluator,
) -> None:
    facts = {
        "active_skills": [{"name": "Cremation", "links": 6, "dps": 10}],
        "has_trigger_setup": True,
    }
    result = evaluator.evaluate(facts, "mapping")
    assert result.confidence == 0.5
    assert result.cant_evaluate
    assert len(result.reasons) == 2

    trusted = evaluator.evaluate(
        facts,
        "mapping",
        [{"assumption_id": "main_skill.trigger_ambiguity", "value": False}],
    )
    assert trusted.confidence == 0.8
    assert not trusted.cant_evaluate
    assert trusted.reasons == ()


def test_build_endpoints_use_engine_identity_and_hold_session(
    app: ApiApplication,
) -> None:
    assert app.dispatch("GET", f"{BASE_PATH}/build") == (404, None)
    build = import_stub_build(app)
    assert build == {
        "build_id": "b-stub",
        "character_class": "Witch",
        "ascendancy": "Occultist",
        "level": 91,
        "main_skill": {"name": "Arc", "inferred": True, "confidence": 0.8},
        "preset_default": "mapping",
    }
    assert app.dispatch("GET", f"{BASE_PATH}/build") == (200, build)
    assert app.dispatch("POST", f"{BASE_PATH}/build", {}) == (422, None)
    assert app.dispatch(
        "POST",
        f"{BASE_PATH}/build",
        {"pob_code": "code", "account": "a", "character": "c"},
    ) == (422, None)
    assert app.dispatch(
        "POST", f"{BASE_PATH}/build", {"account": "a", "character": "c"}
    ) == (422, None)


@pytest.mark.parametrize(
    ("item_text", "expected"),
    [
        ("upgrade", "UPGRADE"),
        ("sidegrade", "SIDEGRADE"),
        ("downgrade", "DOWNGRADE"),
        ("zero-baseline", "CANT_EVALUATE"),
    ],
)
def test_real_serializer_reaches_every_verdict_and_matches_golden_shape(
    app: ApiApplication, item_text: str, expected: str
) -> None:
    import_stub_build(app)
    status, card = app.dispatch(
        "POST", f"{BASE_PATH}/diff", {"item_text": item_text}
    )
    assert status == 200
    assert card is not None
    assert card["verdict"] == expected
    schema = json.loads((ROOT / "contracts/verdict.schema.json").read_text())
    jsonschema.validate(card, schema)

    golden = [
        json.loads(path.read_text())
        for path in sorted((ROOT / "contracts/fixtures").glob("*.json"))
    ]
    assert expected in {fixture["verdict"] for fixture in golden}
    allowed_fields = set().union(*(fixture.keys() for fixture in golden))
    assert set(card) <= allowed_fields


def test_diff_validation_determinism_and_evaluator_config(
    app: ApiApplication, calculator: StubCalculator
) -> None:
    assert app.dispatch(
        "POST", f"{BASE_PATH}/diff", {"item_text": "upgrade"}
    ) == (404, None)
    import_stub_build(app)
    for body in (
        {},
        {"item_text": ""},
        {"item_text": "upgrade", "preset": "invalid"},
        {"item_text": "upgrade", "overrides": [{"assumption_id": "missing-value"}]},
        {
            "item_text": "upgrade",
            "overrides": [{"assumption_id": "not-a-rule", "value": False}],
        },
        {
            "item_text": "upgrade",
            "overrides": [
                {"assumption_id": "config.flasks_up", "value": "not-boolean"}
            ],
        },
    ):
        assert app.dispatch("POST", f"{BASE_PATH}/diff", body) == (422, None)
    request = {
        "item_text": "upgrade",
        "overrides": [{"assumption_id": "config.flasks_up", "value": False}],
    }
    first = app.dispatch("POST", f"{BASE_PATH}/diff", request)[1]
    second = app.dispatch("POST", f"{BASE_PATH}/diff", request)[1]
    assert first == second
    assert first is not None
    assert first["diff_id"].startswith("d-")
    assert next(
        item for item in first["assumptions"] if item["id"] == "config.flasks_up"
    )["value"] is False
    assert calculator.configurations[-1]["flasks_active"] is False


def test_scan_ranks_verdicts_by_combined_delta_and_keeps_ties_stable(
    app: ApiApplication,
) -> None:
    import_stub_build(app)
    status, response = app.dispatch(
        "POST",
        f"{BASE_PATH}/scan",
        {
            "items": [
                "downgrade",
                "upgrade",
                "sidegrade",
                "bigger-upgrade",
                "upgrade",
                "zero-baseline",
            ],
            "preset": "bossing",
        },
    )
    assert status == 200
    assert response is not None
    assert [result["index"] for result in response["results"]] == [
        3,
        1,
        4,
        2,
        0,
        5,
    ]
    assert all(
        result["verdict"]["preset"] == "bossing"
        for result in response["results"]
    )
    schema = json.loads((ROOT / "contracts/verdict.schema.json").read_text())
    for result in response["results"]:
        jsonschema.validate(result["verdict"], schema)


def test_scan_validation_and_empty_stash(app: ApiApplication) -> None:
    assert app.dispatch(
        "POST", f"{BASE_PATH}/scan", {"items": ["upgrade"]}
    ) == (404, None)
    import_stub_build(app)
    for body in (
        None,
        {},
        {"items": "upgrade"},
        {"items": [1]},
        {"items": ["upgrade"] * 2_001},
        {"items": ["upgrade"], "preset": "invalid"},
    ):
        assert app.dispatch("POST", f"{BASE_PATH}/scan", body) == (422, None)
    status, response = app.dispatch(
        "POST",
        f"{BASE_PATH}/scan",
        {"items": ["upgrade", "", "unparseable"]},
    )
    assert status == 200
    assert response is not None
    assert [result["index"] for result in response["results"]] == [0, 1, 2]
    assert [
        result["verdict"]["verdict"] for result in response["results"]
    ] == ["UPGRADE", "CANT_EVALUATE", "CANT_EVALUATE"]
    assert app.dispatch(
        "POST", f"{BASE_PATH}/scan", {"items": []}
    ) == (200, {"results": []})


def test_tree_suggestions_validation_determinism_and_contract(
    app: ApiApplication, calculator: StubCalculator
) -> None:
    endpoint = f"{BASE_PATH}/tree/suggestions"
    assert app.dispatch("GET", endpoint) == (404, None)
    for query in (
        "?points=",
        "?points=0",
        "?points=11",
        "?points=1.0",
        "?points=01",
        "?points=1&points=2",
        "?preset=invalid",
        "?preset=mapping&preset=bossing",
    ):
        assert app.dispatch("GET", endpoint + query) == (422, None)

    import_stub_build(app)
    first = app.dispatch("GET", endpoint)
    second = app.dispatch("GET", endpoint + "?points=5&preset=mapping")
    assert first == second
    status, mapping = first
    assert status == 200
    assert mapping is not None
    assert mapping["preset"] == "mapping"
    assert mapping["suggestions"][0]["node_id"] == 26725
    assert mapping["compute_ms"] == 12
    assert mapping["plan_id"].startswith("p-")

    status, bossing = app.dispatch(
        "GET", endpoint + "?points=3&preset=bossing"
    )
    assert status == 200
    assert bossing is not None
    assert bossing["preset"] == "bossing"
    assert bossing["suggestions"][0]["node_id"] == 54321
    assert calculator.configurations[-1]["enemyIsBoss"] == "PINNACLE"

    contract = yaml.safe_load(
        (ROOT / "contracts/openapi.yaml").read_text()
    )
    schema = {
        "$ref": "#/components/schemas/TreePlan",
        "components": contract["components"],
    }
    jsonschema.validate(mapping, schema)
    jsonschema.validate(bossing, schema)
    for fixture_path in sorted(
        (ROOT / "contracts/fixtures/tree_suggestions").glob("*.json")
    ):
        jsonschema.validate(
            json.loads(fixture_path.read_text()),
            schema,
        )


def test_pob_code_decode_and_conservative_fact_extraction() -> None:
    encoded = base64.urlsafe_b64encode(zlib.compress(SIMPLE_XML)).rstrip(b"=")
    assert decode_pob_code(encoded.decode()) == SIMPLE_XML
    facts = extract_build_facts(SIMPLE_XML)
    assert facts["active_skills"] == [
        {"name": "Arc", "links": 2, "dps": 1, "tags": []}
    ]
    assert not facts["has_trigger_setup"]


def test_http_round_trip_uses_bare_contract_errors(app: ApiApplication) -> None:
    server = create_server(app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}{BASE_PATH}"

    def post(path: str, body: dict) -> tuple[int, bytes]:
        request = Request(
            base + path,
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def get(path: str) -> tuple[int, bytes]:
        try:
            with urlopen(base + path) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    try:
        assert post("/diff", {"item_text": "upgrade"}) == (404, b"")
        assert get("/tree/suggestions") == (404, b"")
        status, raw = post("/build", {"pob_code": "stub"})
        assert status == 200
        assert json.loads(raw)["main_skill"]["name"] == "Arc"
        status, raw = post("/diff", {"item_text": "sidegrade"})
        assert status == 200
        assert json.loads(raw)["verdict"] == "SIDEGRADE"
        status, raw = post(
            "/scan", {"items": ["downgrade", "upgrade", "sidegrade"]}
        )
        assert status == 200
        assert [
            result["index"] for result in json.loads(raw)["results"]
        ] == [1, 2, 0]
        status, raw = get("/tree/suggestions?points=3&preset=bossing")
        assert status == 200
        assert json.loads(raw)["preset"] == "bossing"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
