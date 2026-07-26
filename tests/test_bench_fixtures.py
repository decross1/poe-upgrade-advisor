"""Gate for the overlay bench fixtures (TASK-201).

Fixtures are the payload both stack variants render; they must stay valid
against the protected contract schema (contracts/verdict.schema.json) and must
cover every verdict state so the benchmark exercises the same DOM paths the
production overlay will (role priority 1: every state renders gracefully).
"""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "overlay" / "bench" / "fixtures"
SCHEMA = json.loads((ROOT / "contracts" / "verdict.schema.json").read_text())
ALL_VERDICTS = {"UPGRADE", "SIDEGRADE", "DOWNGRADE", "CANT_EVALUATE"}


def _fixtures() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("verdict_*.json"))


def test_fixtures_exist_and_cover_all_verdict_states() -> None:
    files = _fixtures()
    assert files, "no bench fixtures found"
    verdicts = {json.loads(f.read_text())["verdict"] for f in files}
    assert verdicts == ALL_VERDICTS


def test_fixtures_validate_against_contract_schema() -> None:
    validator = jsonschema.Draft202012Validator(SCHEMA)
    for f in _fixtures():
        validator.validate(json.loads(f.read_text()))


def test_sentence_respects_doctrine_i2_cap() -> None:
    for f in _fixtures():
        sentence = json.loads(f.read_text())["sentence"]
        assert len(sentence) <= 140, f"{f.name}: sentence over 140 chars"


def test_shared_card_ui_is_stack_agnostic() -> None:
    """card.js must not bind to one host stack (keeps the comparison fair)."""
    card_js = (ROOT / "overlay" / "bench" / "shared" / "card.js").read_text()
    assert "require(" not in card_js
    assert "__TAURI__" not in card_js
    assert "ipcRenderer" not in card_js
