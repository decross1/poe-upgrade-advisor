"""Task packet contract.

v1 carries only fields the dispatcher mechanically enforces. Packets are
authored by pm and live in `tasks/packets/<task-id>.json`.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

PACKET_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "task_packet.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(PACKET_SCHEMA_PATH.read_text()))

#: Where authored packets live, relative to the repo root.
PACKET_DIR = Path("tasks") / "packets"


class PacketError(ValueError):
    """Packet is absent, unparseable, or does not satisfy the schema."""


def validate_packet(obj: Any) -> dict:
    """Return `obj` if it is a valid TaskPacket, else raise `PacketError`."""
    if not isinstance(obj, dict):
        raise PacketError(f"packet must be a JSON object, got {type(obj).__name__}")
    errors = sorted(_VALIDATOR.iter_errors(obj), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        loc = "/".join(str(p) for p in first.absolute_path) or "<root>"
        raise PacketError(f"packet invalid at {loc}: {first.message}")
    return obj


def load_packet(path: str | Path) -> dict:
    """Read and validate a packet file."""
    p = Path(path)
    if not p.exists():
        raise PacketError(f"no packet at {p}")
    try:
        obj = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise PacketError(f"packet {p} is not valid JSON: {e}") from e
    except OSError as e:
        raise PacketError(f"cannot read packet {p}: {e}") from e
    return validate_packet(obj)


def packet_path(repo_root: str | Path, task_id: str) -> Path:
    """Canonical on-disk location of a packet."""
    return Path(repo_root) / PACKET_DIR / f"{task_id}.json"


def parent_of(task_id: str) -> str | None:
    """`TASK-210-S1` -> `TASK-210`; `TASK-210` -> None.

    Stage identity is derived, not declared, so a stage can never disagree with
    its own ID. Merge automation uses this to close a stage without closing the
    parent.
    """
    head, sep, tail = task_id.rpartition("-")
    if sep and tail.startswith("S") and tail[1:].isdigit():
        return head
    return None


def out_of_scope(changed_files: list[str], packet: dict) -> list[str]:
    """Files the packet forbids touching, given an actual changed-file list.

    A file is out of scope when it matches `files_out_of_scope` OR when it
    matches nothing in `files_in_scope`. Deny wins: an explicit out-of-scope
    glob is a violation even if an in-scope glob also matches, so a broad
    in-scope entry can never launder a forbidden path.
    """
    deny = packet.get("files_out_of_scope", []) or []
    allow = packet.get("files_in_scope", []) or []
    violations = []
    for f in changed_files:
        if any(fnmatch.fnmatch(f, g) for g in deny):
            violations.append(f)
        elif not any(fnmatch.fnmatch(f, g) for g in allow):
            violations.append(f)
    return violations
