"""Structured result contract.

`exit_code == 0` is not success. This file is. A missing or schema-invalid
result is an *invalid attempt*: the dispatcher increments the attempt ledger
and does NOT acknowledge the message.
"""
from __future__ import annotations

import json
import shutil
import sys
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


#: Basename of the swept artifact inside `mailroom/runs/<run_id>/`. The dot
#: prefix exists only to keep the file out of the agent's way in the
#: worktree; in the run record it is a first-class artifact.
SWEPT_RESULT_FILENAME = "agent-result.json"


def runs_dir(mailroom: str | Path, run_id: str) -> Path:
    """The per-run record home, `mailroom/runs/<run_id>/`.

    The legacy postmaster writes `runs/<role>-last-run.log` flat in `runs/`;
    run_ids are uuid hex, so per-run DIRECTORIES cannot collide with those
    files.
    """
    return Path(mailroom) / "runs" / run_id


def sweep_result(worktree: str | Path, mailroom: str | Path,
                 run_id: str) -> Path | None:
    """Move the worktree result artifact into the durable run record (CC-3).

    The agent's write contract is unchanged — it writes RESULT_FILENAME in
    the worktree root. The DISPATCHER owns the artifact's lifecycle after
    reading it. Left in place it dirties the tree: the supervisor strands
    the worktree as RECOVERY_REQUIRED, step 12 bundles after every clean
    success, and the file enters the anti-loop changed-file set. The sweep
    runs immediately after the result read and BEFORE any cleanliness
    evaluation, moving the file — schema-valid or not, it is evidence — to
    `mailroom/runs/<run_id>/agent-result.json`.

    Returns the destination path, or None when there is nothing to sweep.
    A failed sweep is loud but not fatal: the file then stays in the tree
    and the existing recovery machinery preserves it exactly as before.
    """
    src = Path(worktree) / RESULT_FILENAME
    if not src.exists():
        return None
    dest_dir = runs_dir(mailroom, run_id)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / SWEPT_RESULT_FILENAME
        shutil.move(str(src), str(dest))
        return dest
    except OSError as e:
        print(f"WARNING: result sweep failed, artifact left in worktree "
              f"({src}): {e}", file=sys.stderr)
        return None


def is_ackable(result: dict) -> bool:
    """True when a *valid* result authorises retiring the ledger message.

    `needs_retry` is deliberately excluded: it remains actionable, and only the
    dispatcher-side attempt cap may retire it.
    """
    return result.get("status") in {"completed", "blocked", "terminated", "dead_lettered"}
