"""Localhost-only implementation of the v0 build and diff API."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

from .assumptions import AssumptionsEvaluator
from .calculator import Calculator, FixtureNotFound

HOST = "127.0.0.1"
PORT = 47791
BASE_PATH = "/api/v0"
VALID_PRESETS = {"mapping", "bossing", "balanced"}


@dataclass
class BuildStore:
    active: dict[str, Any] | None = None


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
        if path == f"{BASE_PATH}/build" and method == "GET":
            return (200, self.store.active) if self.store.active else (404, None)
        if path == f"{BASE_PATH}/build" and method == "POST":
            return self._import_build(body)
        if path == f"{BASE_PATH}/diff" and method == "POST":
            return self._diff(body)
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

        source = pob_code or f"{account}/{character}"
        facts = self._fixture_build_facts(pob_code or "")
        result = self.evaluator.evaluate(facts, "mapping")
        try:
            level = int(body.get("level", 1))
        except (TypeError, ValueError):
            return 422, None
        self.store.active = {
            "build_id": f"b-{hashlib.sha256(source.encode()).hexdigest()[:8]}",
            "character_class": str(body.get("character_class", "Unknown")),
            "level": level,
            "main_skill": {
                "name": result.main_skill,
                "inferred": result.main_skill_inferred,
                "confidence": result.confidence,
            },
            "preset_default": "mapping",
        }
        if body.get("ascendancy"):
            self.store.active["ascendancy"] = str(body["ascendancy"])
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
        if self.store.active is None or "@error:404" in item_text:
            return 404, None
        if "@error:422" in item_text:
            return 422, None
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
        try:
            return 200, self.calculator.diff(item_text, preset, overrides)
        except FixtureNotFound:
            return 422, None

    @staticmethod
    def _fixture_build_facts(pob_code: str) -> dict[str, Any]:
        """Parse explicit fake metadata without pretending to parse a real PoB."""
        skill_match = re.search(r"@skill:([^;\n]+)", pob_code)
        skill = skill_match.group(1).strip() if skill_match else "Unknown"
        return {
            "active_skills": [
                {
                    "name": skill,
                    "links": 6 if skill != "Unknown" else 0,
                    "dps": 1,
                    "tags": [
                        tag
                        for tag in ("chill", "shock")
                        if f"@tag:{tag}" in pob_code
                    ],
                }
            ],
            "allocated_keystone": (
                "Elemental Overload" if "@keystone:eo" in pob_code else None
            ),
            "has_charge_generation": (
                "power" if "@charges:power" in pob_code else None
            ),
            "has_trigger_setup": "@trigger" in pob_code,
        }


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
                self.command, urlsplit(self.path).path, body
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
