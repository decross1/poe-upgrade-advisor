"""Structured result contract.

`exit_code == 0` is not success. This file is. A missing or schema-invalid
result is an *invalid attempt*: the dispatcher increments the attempt ledger
and does NOT acknowledge the message.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

RESULT_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "result.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(RESULT_SCHEMA_PATH.read_text()))

#: Filename an executor writes inside its worktree. The dispatcher reads
#: exactly this path and nothing else — no parsing of model prose.
RESULT_FILENAME = ".agent-result.json"


class ResultError(ValueError):
    """Result file is absent, unparseable, or does not satisfy the schema."""


def validate_result(obj: Any) -> dict:
    """Return `obj` if it is a valid AgentResult, else raise `ResultError`."""
    if not isinstance(obj, dict):
        raise ResultError(f"result must be a JSON object, got {type(obj).__name__}")
    errors = sorted(_VALIDATOR.iter_errors(obj), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        loc = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise ResultError(f"result invalid at {loc}: {first.message}")
    return obj


def load_result(path: str | Path) -> dict:
    """Read and validate a result file.

    Raises `ResultError` for every failure mode — absent, empty, unparseable,
    or schema-invalid — so callers have exactly one thing to catch.
    """
    p = Path(path)
    if not p.exists():
        raise ResultError(f"no result file at {p}")
    try:
        raw = p.read_text()
    except OSError as e:
        raise ResultError(f"cannot read result file {p}: {e}") from e
    if not raw.strip():
        raise ResultError(f"result file {p} is empty")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ResultError(f"result file {p} is not valid JSON: {e}") from e
    return validate_result(obj)


def is_ackable(result: dict) -> bool:
    """True when a *valid* result authorises retiring the ledger message.

    `needs_retry` is deliberately excluded: it remains actionable, and only the
    dispatcher-side attempt cap may retire it.
    """
    return result.get("status") in {"completed", "blocked", "terminated", "dead_lettered"}
