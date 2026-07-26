"""Localhost-only implementation of the v0 build and diff API."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .assumptions import AssumptionsEvaluator, Evaluation
from .calculator import (
    BuildImportError,
    Calculator,
    ItemParseError,
    WorkerUnavailable,
)

HOST = "127.0.0.1"
PORT = 47791
BASE_PATH = "/api/v0"
VALID_PRESETS = {"mapping", "bossing", "balanced"}
VERDICT_RANK = {
    "UPGRADE": 3,
    "SIDEGRADE": 2,
    "DOWNGRADE": 1,
    "CANT_EVALUATE": 0,
}


@dataclass
class BuildStore:
    active: dict[str, Any] | None = None
    facts: Mapping[str, Any] | None = None


class ApiApplication:
    def __init__(
        self,
        calculator: Calculator,
        evaluator: AssumptionsEvaluator,
        store: BuildStore | None = None,
    ) -> None:
        self.calculator = calculator
        self.evaluator = evaluator
        self.store = store or BuildStore()

    def dispatch(
        self, method: str, path: str, body: Any = None
    ) -> tuple[int, dict[str, Any] | None]:
        target = urlsplit(path)
        route = target.path
        if route == f"{BASE_PATH}/build" and method == "GET":
            return (200, self.store.active) if self.store.active else (404, None)
        if route == f"{BASE_PATH}/build" and method == "POST":
            return self._import_build(body)
        if route == f"{BASE_PATH}/diff" and method == "POST":
            return self._diff(body)
        if route == f"{BASE_PATH}/scan" and method == "POST":
            return self._scan(body)
        if route == f"{BASE_PATH}/tree/suggestions" and method == "GET":
            return self._tree_suggestions(
                parse_qs(target.query, keep_blank_values=True)
            )
        return 404, None

    def _import_build(self, body: Any) -> tuple[int, dict[str, Any] | None]:
        if not isinstance(body, Mapping):
            return 422, None
        pob_code = body.get("pob_code")
        account = body.get("account")
        character = body.get("character")
        has_code = isinstance(pob_code, str) and bool(pob_code.strip())
        has_character = (
            isinstance(account, str)
            and bool(account.strip())
            and isinstance(character, str)
            and bool(character.strip())
        )
        if has_code == has_character:
            return 422, None

        if not has_code:
            # A public account/character does not contain the complete PoB
            # ConfigSet required for deterministic evaluation.
            return 422, None

        try:
            imported = self.calculator.import_build(pob_code)
            result = self.evaluator.evaluate(imported.facts, "mapping")
            identity = self.calculator.configure_build(result.pob_config)
        except BuildImportError:
            return 422, None

        self.store.facts = imported.facts
        self.store.active = {
            "build_id": imported.build_id,
            "character_class": identity["base_class"],
            "level": int(identity["level"]),
            "main_skill": {
                "name": result.main_skill,
                "inferred": result.main_skill_inferred,
                "confidence": result.confidence,
            },
            "preset_default": "mapping",
        }
        ascendancy = identity.get("ascendancy")
        if isinstance(ascendancy, str) and ascendancy and ascendancy != "None":
            self.store.active["ascendancy"] = ascendancy
        return 200, self.store.active

    def _diff(self, body: Any) -> tuple[int, dict[str, Any] | None]:
        if not isinstance(body, Mapping):
            return 422, None
        item_text = body.get("item_text")
        if (
            not isinstance(item_text, str)
            or not item_text.strip()
            or len(item_text) > 20_000
        ):
            return 422, None
        if self.store.active is None or self.store.facts is None:
            return 404, None
        preset = body.get("preset")
        if preset is not None and preset not in VALID_PRESETS:
            return 422, None
        overrides = body.get("overrides", [])
        if not isinstance(overrides, list) or any(
            not isinstance(item, Mapping)
            or not isinstance(item.get("assumption_id"), str)
            or "value" not in item
            for item in overrides
        ):
            return 422, None
        selected_preset = preset or self.store.active["preset_default"]
        base_evaluation = self.evaluator.evaluate(
            self.store.facts, selected_preset
        )
        known_values = {
            assumption["id"]: assumption["value"]
            for assumption in base_evaluation.assumptions
        }
        if any(
            override["assumption_id"] not in known_values
            or not self._same_value_type(
                known_values[override["assumption_id"]], override["value"]
            )
            for override in overrides
        ):
            return 422, None
        evaluation = self.evaluator.evaluate(
            self.store.facts, selected_preset, overrides
        )
        return self._evaluate_item(
            item_text, selected_preset, evaluation, overrides
        )

    def _scan(self, body: Any) -> tuple[int, dict[str, Any] | None]:
        if not isinstance(body, Mapping):
            return 422, None
        items = body.get("items")
        if (
            not isinstance(items, list)
            or len(items) > 2_000
            or any(not isinstance(item, str) for item in items)
        ):
            return 422, None
        if self.store.active is None or self.store.facts is None:
            return 404, None
        preset = body.get("preset")
        if preset is not None and preset not in VALID_PRESETS:
            return 422, None
        selected_preset = preset or self.store.active["preset_default"]
        evaluation = self.evaluator.evaluate(
            self.store.facts, selected_preset
        )
        results = []
        for index, item_text in enumerate(items):
            status, verdict = self._evaluate_item(
                item_text,
                selected_preset,
                evaluation,
                [],
                item_parse_is_uncertain=True,
            )
            if status != 200 or verdict is None:
                return status, None
            results.append({"index": index, "verdict": verdict})
        results.sort(key=self._scan_rank)
        return 200, {"results": results}

    def _tree_suggestions(
        self, query: Mapping[str, list[str]]
    ) -> tuple[int, dict[str, Any] | None]:
        point_values = query.get("points", ["5"])
        preset_values = query.get("preset", [])
        if len(point_values) != 1 or len(preset_values) > 1:
            return 422, None
        try:
            points = int(point_values[0])
        except (TypeError, ValueError):
            return 422, None
        if str(points) != point_values[0] or not 1 <= points <= 10:
            return 422, None
        preset = preset_values[0] if preset_values else None
        if preset is not None and preset not in VALID_PRESETS:
            return 422, None
        if self.store.active is None or self.store.facts is None:
            return 404, None

        selected_preset = preset or self.store.active["preset_default"]
        evaluation = self.evaluator.evaluate(
            self.store.facts, selected_preset
        )
        plan = self.calculator.tree_suggestions(
            points, evaluation.pob_config
        )
        suggestions = [dict(item) for item in plan.suggestions]
        response = {
            "plan_id": self._plan_id(
                selected_preset, points, suggestions
            ),
            "preset": selected_preset,
            "suggestions": suggestions,
            "compute_ms": max(0, round(plan.compute_ms)),
        }
        return 200, response

    def _evaluate_item(
        self,
        item_text: str,
        selected_preset: str,
        evaluation: Evaluation,
        overrides: list[Mapping[str, Any]],
        item_parse_is_uncertain: bool = False,
    ) -> tuple[int, dict[str, Any] | None]:
        if evaluation.cant_evaluate:
            return 200, self._cant_evaluate_card(
                selected_preset,
                evaluation.confidence,
                evaluation.assumptions,
                evaluation.reasons,
                overrides,
            )
        try:
            calculation = self.calculator.diff(item_text, evaluation.pob_config)
        except ItemParseError:
            if item_parse_is_uncertain:
                return 200, self._cant_evaluate_card(
                    selected_preset,
                    0,
                    evaluation.assumptions,
                    ("engine.item_unparseable: Path of Building rejected the item",),
                    overrides,
                )
            return 422, None
        except WorkerUnavailable:
            return 200, self._cant_evaluate_card(
                selected_preset,
                0,
                evaluation.assumptions,
                ("engine.worker_unavailable: Path of Building did not respond",),
                overrides,
            )
        return 200, self._verdict_card(
            calculation.payload,
            selected_preset,
            evaluation.confidence,
            evaluation.assumptions,
            overrides,
        )

    @staticmethod
    def _scan_rank(result: Mapping[str, Any]) -> tuple[float, float, int]:
        card = result["verdict"]
        combined_delta = (
            card["offense_delta_pct"] + card["defense_delta_pct"]
        )
        return (
            -VERDICT_RANK[card["verdict"]],
            -combined_delta,
            result["index"],
        )

    def _verdict_card(
        self,
        payload: Mapping[str, Any],
        preset: str,
        confidence: float,
        assumptions: tuple[Mapping[str, Any], ...],
        overrides: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        baseline = payload["baseline"]
        candidate = payload["candidate"]
        offense = self._percent_delta(
            baseline["total_dps"], candidate["total_dps"]
        )
        defense = self._percent_delta(baseline["ehp"], candidate["ehp"])
        if offense is None or defense is None:
            return self._cant_evaluate_card(
                preset,
                confidence,
                assumptions,
                (
                    (
                        "engine.zero_baseline: a percentage delta cannot be "
                        "computed from a zero baseline"
                    ),
                ),
                overrides,
            )
        offense = round(offense, 1)
        defense = round(defense, 1)
        if (
            offense >= 0
            and defense >= 0
            and (offense > 0 or defense > 0)
        ):
            verdict = "UPGRADE"
        elif (
            offense <= 0
            and defense <= 0
            and (offense < 0 or defense < 0)
        ):
            verdict = "DOWNGRADE"
        else:
            verdict = "SIDEGRADE"
        card = {
            "diff_id": self._diff_id(preset, overrides, payload),
            "verdict": verdict,
            "offense_delta_pct": offense,
            "defense_delta_pct": defense,
            "sentence": self._sentence(verdict, offense, defense),
            "assumptions": self._ordered_assumptions(assumptions),
            "confidence": confidence,
            "preset": preset,
        }
        return card

    def _cant_evaluate_card(
        self,
        preset: str,
        confidence: float,
        assumptions: tuple[Mapping[str, Any], ...],
        reasons: tuple[str, ...],
        overrides: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        card = {
            "diff_id": self._diff_id(preset, overrides, {"reasons": reasons}),
            "verdict": "CANT_EVALUATE",
            "offense_delta_pct": 0,
            "defense_delta_pct": 0,
            "sentence": (
                "Confidence is too low for an honest verdict; open details "
                "to review the assumptions."
            ),
            "assumptions": self._ordered_assumptions(assumptions),
            "confidence": confidence,
            "preset": preset,
        }
        if reasons:
            card["cant_evaluate_reasons"] = list(reasons)
        return card

    def _diff_id(
        self,
        preset: str,
        overrides: list[Mapping[str, Any]],
        calculation: Mapping[str, Any],
    ) -> str:
        assert self.store.active is not None
        encoded = json.dumps(
            {
                "build_id": self.store.active["build_id"],
                "preset": preset,
                "overrides": overrides,
                "calculation": calculation,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"d-{hashlib.sha256(encoded).hexdigest()[:12]}"

    def _plan_id(
        self,
        preset: str,
        points: int,
        suggestions: list[Mapping[str, Any]],
    ) -> str:
        assert self.store.active is not None
        encoded = json.dumps(
            {
                "build_id": self.store.active["build_id"],
                "translation_version": 1,
                "preset": preset,
                "points": points,
                "suggestions": suggestions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"p-{hashlib.sha256(encoded).hexdigest()[:12]}"

    @staticmethod
    def _ordered_assumptions(
        assumptions: tuple[Mapping[str, Any], ...],
    ) -> list[dict[str, Any]]:
        return [
            dict(assumption)
            for assumption in sorted(
                assumptions,
                key=lambda item: not bool(item.get("impactful")),
            )[:6]
        ]

    @staticmethod
    def _percent_delta(baseline: float, candidate: float) -> float | None:
        if baseline == 0:
            return 0.0 if candidate == 0 else None
        return (candidate - baseline) / abs(baseline) * 100

    @staticmethod
    def _same_value_type(expected: Any, actual: Any) -> bool:
        if isinstance(expected, bool):
            return isinstance(actual, bool)
        if isinstance(expected, str):
            return isinstance(actual, str) and bool(actual)
        return type(actual) is type(expected)

    @staticmethod
    def _sentence(verdict: str, offense: float, defense: float) -> str:
        offense_text = f"{offense:+.1f}%"
        defense_text = f"{defense:+.1f}%"
        if verdict == "SIDEGRADE":
            ending = "the candidate is a sidegrade."
        elif verdict == "UPGRADE":
            ending = "the combined change is an upgrade."
        else:
            ending = "the combined change is a downgrade."
        return (
            f"Offense changes {offense_text} and defense {defense_text}; {ending}"
        )


def create_server(
    app: ApiApplication, host: str = HOST, port: int = PORT
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle(None)

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length)) if length else None
            except (ValueError, json.JSONDecodeError):
                self.send_response(422)
                self.end_headers()
                return
            self._handle(body)

        def _handle(self, body: Any) -> None:
            status, response = app.dispatch(
                self.command, self.path, body
            )
            self.send_response(status)
            if response is not None:
                encoded = json.dumps(
                    response, separators=(",", ":"), sort_keys=True
                ).encode()
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            else:
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)
