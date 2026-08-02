#!/usr/bin/env python3
"""Normalize a legacy issue only after explicit human/PM confirmation."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.interfaces.packet import PacketError, parent_of
from agents.packets.validate import validate_semantics


class ConfirmationRequired(PacketError):
    """A preview exists, but it is not executable until explicitly confirmed."""


TIER_BUDGETS = {
    "green": {"max_attempts": 2, "max_files_modified": 4, "max_diff_lines": 250,
              "max_wall_clock_seconds": 900},
    "yellow": {"max_attempts": 2, "max_files_modified": 6, "max_diff_lines": 400,
               "max_wall_clock_seconds": 1200},
    "red": {"max_attempts": 3, "max_files_modified": 8, "max_diff_lines": 600,
            "max_wall_clock_seconds": 1800},
}


def _task_id(issue: dict[str, Any]) -> str:
    match = re.search(r"\bTASK-[0-9]+(?:-S[0-9]+)?\b", str(issue.get("title") or ""))
    if not match:
        raise PacketError("legacy issue title has no well-formed TASK id")
    return match.group(0)


def packet_preview(issue: dict[str, Any]) -> dict[str, Any]:
    """Return a deliberately non-executable skeleton for human completion."""
    task_id = _task_id(issue)
    title = str(issue.get("title") or task_id)
    objective = title.split(":", 1)[-1].strip()
    if len(objective) < 10:
        objective = f"Complete the explicitly reviewed work for {task_id}"
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "parent_task_id": parent_of(task_id),
        "issue": issue.get("number"),
        "owner_role": None,
        "tier": None,
        "objective": objective,
        "files_in_scope": [],
        "files_out_of_scope": [],
        "required_checks": [],
        "acceptance_criteria": [],
        "budgets": {},
    }


def normalize_issue(
    issue: dict[str, Any],
    *,
    confirmed_by: str | None,
    owner_role: str,
    tier: str,
    files_in_scope: list[str],
    files_out_of_scope: list[str],
    required_checks: list[str],
    acceptance: list[str],
    routing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if confirmed_by not in {"human", "pm"}:
        raise ConfirmationRequired("legacy normalization requires --confirm human|pm")
    packet = packet_preview(issue)
    packet.update({
        "owner_role": owner_role,
        "tier": tier,
        "files_in_scope": files_in_scope,
        "files_out_of_scope": files_out_of_scope,
        "required_checks": required_checks,
        "acceptance_criteria": [
            {"id": f"AC-{index}", "text": text} for index, text in enumerate(acceptance, 1)
        ],
        "budgets": dict(TIER_BUDGETS[tier]),
    })
    if routing:
        packet["routing"] = routing
    return validate_semantics(packet)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue_json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm", choices=("human", "pm"))
    parser.add_argument("--owner-role", choices=("pm", "backend", "frontend"))
    parser.add_argument("--tier", choices=("green", "yellow", "red"))
    parser.add_argument("--files-in-scope", action="append", default=[])
    parser.add_argument("--files-out-of-scope", action="append", default=[])
    parser.add_argument("--required-check", action="append", default=[])
    parser.add_argument("--acceptance", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        issue = json.loads(args.issue_json.read_text(encoding="utf-8"))
        if not args.confirm:
            print(json.dumps(packet_preview(issue), indent=2, sort_keys=True))
            print("normalization preview only: explicit --confirm human|pm required", file=sys.stderr)
            return 2
        if not args.owner_role or not args.tier:
            raise PacketError("--owner-role and --tier are required when confirming")
        packet = normalize_issue(
            issue,
            confirmed_by=args.confirm,
            owner_role=args.owner_role,
            tier=args.tier,
            files_in_scope=args.files_in_scope,
            files_out_of_scope=args.files_out_of_scope,
            required_checks=args.required_check,
            acceptance=args.acceptance,
        )
        rendered = json.dumps(packet, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (OSError, json.JSONDecodeError, PacketError, KeyError) as exc:
        print(f"normalization failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
