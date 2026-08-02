#!/usr/bin/env python3
"""Validate one task packet or every authored packet."""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.interfaces.packet import (
    PacketError,
    load_packet,
    parent_of,
    validate_packet,
)
from agents.merge_robot.patterns import PROTECTED

MAX_PACKET_BYTES = 64 * 1024
MAX_ITEMS = {
    "files_in_scope": 25,
    "files_out_of_scope": 25,
    "required_checks": 12,
    "acceptance_criteria": 12,
    "preconditions": 12,
    "constraints": 20,
    "forbidden_actions": 20,
}
PROTECTED_REVIEW = "evidence-bearing-non-author-approval"


def _glob_probe(pattern: str) -> str:
    prefix = pattern.split("*", 1)[0].split("?", 1)[0].rstrip("/")
    return f"{prefix}/__packet_probe__" if prefix else "__packet_probe__"


def scope_touches_protected(pattern: str) -> bool:
    probe = _glob_probe(pattern)
    return any(
        fnmatch.fnmatch(probe, protected)
        or fnmatch.fnmatch(pattern, protected)
        or fnmatch.fnmatch(_glob_probe(protected), pattern)
        for protected in PROTECTED
    )


def validate_semantics(packet: dict[str, Any]) -> dict[str, Any]:
    """Reject boundedness, identity, and routing ambiguity the schema cannot express."""
    validate_packet(packet)
    task_id = packet["task_id"]
    derived_parent = parent_of(task_id)
    declared_parent = packet.get("parent_task_id")
    if declared_parent != derived_parent:
        raise PacketError(
            f"ambiguous stage identity: {task_id} derives parent {derived_parent!r}, "
            f"but parent_task_id is {declared_parent!r}"
        )
    for field, limit in MAX_ITEMS.items():
        values = packet.get(field) or []
        if len(values) > limit:
            raise PacketError(f"packet oversized: {field} has {len(values)} items, max {limit}")
    for field in ("files_in_scope", "files_out_of_scope", "required_checks"):
        values = packet.get(field) or []
        if len(values) != len(set(values)):
            raise PacketError(f"packet ambiguous: duplicate value in {field}")
        if any(not str(value).strip() or "\x00" in str(value) or "\n" in str(value) for value in values):
            raise PacketError(f"packet ambiguous: invalid value in {field}")
    overlap = set(packet["files_in_scope"]) & set(packet.get("files_out_of_scope") or [])
    if overlap:
        raise PacketError(f"packet ambiguous: scope both allows and forbids {sorted(overlap)}")
    criteria_ids = [criterion["id"] for criterion in packet["acceptance_criteria"]]
    if len(criteria_ids) != len(set(criteria_ids)):
        raise PacketError("packet ambiguous: acceptance criterion ids must be unique")

    protected = any(scope_touches_protected(pattern) for pattern in packet["files_in_scope"])
    if protected:
        routing = packet.get("routing") or {}
        review = set(routing.get("review_only_if") or [])
        if packet["tier"] != "red" or routing.get("reasoning_effort") != "high" \
                or PROTECTED_REVIEW not in review:
            raise PacketError(
                "protected-path scope requires tier=red, reasoning_effort=high, "
                f"and review_only_if containing {PROTECTED_REVIEW!r}"
            )
    return packet


def validate_path(path: str | Path) -> dict[str, Any]:
    packet_path = Path(path)
    try:
        size = packet_path.stat().st_size
    except OSError as exc:
        raise PacketError(f"cannot stat packet {packet_path}: {exc}") from exc
    if size > MAX_PACKET_BYTES:
        raise PacketError(f"packet oversized: {size} bytes, max {MAX_PACKET_BYTES}")
    return validate_semantics(load_packet(packet_path))


def validate_all(root: str | Path = ROOT) -> list[Path]:
    directory = Path(root) / "tasks/packets"
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise PacketError(f"no packets found in {directory}")
    for path in paths:
        validate_path(path)
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", nargs="?", help="optional 'validate' or packet path")
    parser.add_argument("second", nargs="?", help="packet path after 'validate'")
    parser.add_argument("--all", action="store_true", help="validate tasks/packets/*.json")
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.second if args.first == "validate" else args.first
    try:
        if args.all:
            if path:
                raise PacketError("choose a packet path or --all, not both")
            paths = validate_all(args.root)
            print(json.dumps({"valid": len(paths), "paths": [str(p) for p in paths]}))
        else:
            if not path:
                raise PacketError("provide validate <path> or --all")
            packet = validate_path(path)
            print(json.dumps({"valid": 1, "task_id": packet["task_id"]}))
    except PacketError as exc:
        print(f"packet validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
