import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jsonschema
import pytest

from server.app import ApiApplication, BASE_PATH, BuildStore, create_server
from server.assumptions import AssumptionsEvaluator
from server.calculator import FixtureCalculator

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def evaluator() -> AssumptionsEvaluator:
    return AssumptionsEvaluator(ROOT / "assumptions")


@pytest.fixture
def app(evaluator: AssumptionsEvaluator) -> ApiApplication:
    return ApiApplication(
        FixtureCalculator(ROOT / "contracts/fixtures"), evaluator, BuildStore()
    )


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


def test_trigger_penalty_degrades_to_cant_evaluate(
    evaluator: AssumptionsEvaluator,
) -> None:
    result = evaluator.evaluate(
        {
            "active_skills": [{"name": "Cremation", "links": 6, "dps": 10}],
            "has_trigger_setup": True,
        },
        "mapping",
    )
    assert result.confidence == 0.5
    assert result.cant_evaluate
    assert len(result.reasons) == 2


def test_build_endpoints_and_validation(app: ApiApplication) -> None:
    assert app.dispatch("GET", f"{BASE_PATH}/build") == (404, None)
    status, build = app.dispatch(
        "POST",
        f"{BASE_PATH}/build",
        {"pob_code": "@skill:Vortex;@tag:chill", "character_class": "Witch", "level": 91},
    )
    assert status == 200
    assert build["main_skill"]["name"] == "Vortex"
    assert build["character_class"] == "Witch"
    assert app.dispatch("GET", f"{BASE_PATH}/build") == (200, build)
    assert app.dispatch("POST", f"{BASE_PATH}/build", {}) == (422, None)
    assert app.dispatch(
        "POST",
        f"{BASE_PATH}/build",
        {"pob_code": "code", "account": "a", "character": "c"},
    ) == (422, None)
    assert app.dispatch(
        "POST", f"{BASE_PATH}/build", {"pob_code": "code", "level": "not-a-level"}
    ) == (422, None)


def test_all_golden_responses_are_reproduced_and_schema_valid(
    app: ApiApplication,
) -> None:
    app.dispatch("POST", f"{BASE_PATH}/build", {"pob_code": "@skill:Arc"})
    schema = json.loads((ROOT / "contracts/verdict.schema.json").read_text())
    verdicts = set()
    fixture_paths = sorted((ROOT / "contracts/fixtures").glob("*.json"))
    assert len(fixture_paths) == 7
    for path in fixture_paths:
        expected = json.loads(path.read_text())
        status, actual = app.dispatch(
            "POST", f"{BASE_PATH}/diff", {"item_text": f"@fixture:{path.stem}"}
        )
        assert status == 200
        assert actual == expected
        jsonschema.validate(actual, schema)
        verdicts.add(actual["verdict"])
    assert verdicts == {"UPGRADE", "SIDEGRADE", "DOWNGRADE", "CANT_EVALUATE"}


def test_diff_errors_and_deterministic_override(app: ApiApplication) -> None:
    assert app.dispatch(
        "POST", f"{BASE_PATH}/diff", {"item_text": "item"}
    ) == (404, None)
    app.dispatch("POST", f"{BASE_PATH}/build", {"pob_code": "@skill:Arc"})
    for body in (
        {},
        {"item_text": ""},
        {"item_text": "@fixture:missing"},
        {"item_text": "item", "overrides": [{"assumption_id": "missing-value"}]},
    ):
        assert app.dispatch("POST", f"{BASE_PATH}/diff", body) == (422, None)
    request = {
        "item_text": "@fixture:upgrade_mapping",
        "overrides": [{"assumption_id": "config.flasks_up", "value": False}],
    }
    first = app.dispatch("POST", f"{BASE_PATH}/diff", request)[1]
    second = app.dispatch("POST", f"{BASE_PATH}/diff", request)[1]
    assert first == second
    assert first["diff_id"].startswith("d-8f2c41a7#ovr-")
    assert next(
        item for item in first["assumptions"] if item["id"] == "config.flasks_up"
    )["value"] is False


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

    try:
        assert post("/diff", {"item_text": "item"}) == (404, b"")
        status, raw = post("/build", {"pob_code": "@skill:Arc"})
        assert status == 200
        assert json.loads(raw)["main_skill"]["name"] == "Arc"
        status, raw = post("/diff", {"item_text": "@fixture:sidegrade_bossing"})
        assert status == 200
        assert json.loads(raw)["verdict"] == "SIDEGRADE"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
