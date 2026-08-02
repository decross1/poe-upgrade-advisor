#!/usr/bin/env python3
"""Query invocation analytics and calibrate subscription allowance usage."""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.accounting import (
    AccountingBudgetLedger,
    AnalyticsTelemetry,
    read_invocations,
    weighted_seconds,
)


def find_mailroom(root: Path = ROOT) -> Path:
    for ancestor in (root, *root.parents):
        candidate = ancestor / "mailroom"
        if candidate.is_dir():
            return candidate
    return root.parent / "mailroom"


def parse_since(value: str, *, now: float | None = None) -> float:
    suffixes = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
    if len(value) < 2 or value[-1] not in suffixes:
        raise argparse.ArgumentTypeError("--since must look like 30m, 24h, or 7d")
    try:
        amount = float(value[:-1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--since must look like 30m, 24h, or 7d") from exc
    if amount < 0:
        raise argparse.ArgumentTypeError("--since cannot be negative")
    return (time.time() if now is None else now) - amount * suffixes[value[-1]]


def _started(record: dict[str, Any]) -> float:
    value = record.get("started_at")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _contains_module(value: Any, module: str) -> bool:
    needle = module.replace(".", "/")
    if isinstance(value, list):
        return any(module in str(item) or needle in str(item) for item in value)
    return value is not None and (module in str(value) or needle in str(value))


def filter_records(
    records: list[dict[str, Any]],
    *,
    since_ts: float | None = None,
    task: str | None = None,
    model: str | None = None,
    module: str | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        if since_ts is not None and _started(record) < since_ts:
            continue
        if task is not None and record.get("task_id") != task:
            continue
        if model is not None and model not in {record.get("model"), record.get("model_tier")}:
            continue
        if module is not None:
            touched = (record.get("files_inspected"), record.get("files_modified"))
            if not any(_contains_module(value, module) for value in touched):
                continue
        selected.append(record)
    return selected


def _nullable_sum(
    records: list[dict[str, Any]], field: str
) -> tuple[float | int | None, int, int]:
    values = [record.get(field) for record in records if record.get(field) is not None]
    return (sum(values) if values else None, len(values), len(records))


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    invoked = [r for r in records if not r.get("suppressed") and r.get("result_status") != "suppressed"]
    aggregates = {
        field: _nullable_sum(invoked, field)
        for field in (
            "cash_cost_usd",
            "allowance_pct_estimated",
            "input_tokens",
            "output_tokens",
        )
    }
    measurements = {}
    for field, (total, known, rows) in aggregates.items():
        measurements[field] = total
        measurements[f"{field}_known_rows"] = known
        measurements[f"{field}_rows"] = rows
    return {
        "records": len(records),
        "invocations": len(invoked),
        "suppressed": len(records) - len(invoked),
        "accepted": sum(r.get("accepted") is True for r in invoked),
        "crashed": sum(r.get("result_status") == "crashed" for r in invoked),
        "incomplete": sum(r.get("incomplete") is True for r in invoked),
        **measurements,
    }


def wasted_runs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record for record in records
        if not record.get("suppressed")
        and record.get("result_status") != "suppressed"
        and (record.get("rolled_back") is True or record.get("accepted") is False)
    ]


def accepted_cost(records: list[dict[str, Any]], group_by: str) -> dict[str, Any]:
    accepted = [record for record in records if record.get("accepted") is True]
    incomplete = [
        record.get("run_id") for record in accepted
        if record.get("cash_cost_usd") is None and record.get("allowance_pct_estimated") is None
    ]
    if incomplete:
        raise ValueError(
            "accepted-cost unavailable: accepted runs lack both cash cost and "
            f"allowance estimate: {', '.join(str(x) for x in incomplete)}"
        )
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "accepted_runs": 0,
            "cash_cost_usd": None,
            "allowance_pct_estimated": None,
        }
    )
    for record in accepted:
        key = str(record.get(group_by) or "<unknown>")
        group = groups[key]
        group["accepted_runs"] += 1
        if record.get("cash_cost_usd") is not None:
            group["cash_cost_usd"] = (
                (group["cash_cost_usd"] or 0.0) + float(record["cash_cost_usd"])
            )
        if record.get("allowance_pct_estimated") is not None:
            group["allowance_pct_estimated"] = (
                (group["allowance_pct_estimated"] or 0.0)
                + float(record["allowance_pct_estimated"])
            )
    return {
        "label": "ESTIMATE — accepted-run cost from measured cash and/or calibrated allowance",
        "group_by": group_by,
        "groups": dict(groups),
    }


def record_allowance(
    *,
    ledger: AccountingBudgetLedger,
    telemetry: AnalyticsTelemetry,
    records: list[dict[str, Any]],
    role: str,
    pct: float,
    ts: float | None = None,
) -> dict[str, Any]:
    now = time.time() if ts is None else ts
    prior = ledger.latest_allowance(role)
    prior_ts = float(prior["ts"]) if prior is not None else 0.0
    weighted = weighted_seconds(records, role=role, since_ts=prior_ts)
    result = ledger.record_allowance(
        role=role,
        pct=pct,
        source="manual_daily_reading",
        weighted_seconds=weighted,
        ts=now,
    )
    factor = result["pct_per_weighted_second"]
    backfilled = 0
    if factor is not None:
        for record in records:
            if record.get("role") != role or _started(record) <= prior_ts:
                continue
            if record.get("suppressed") or record.get("result_status") == "suppressed":
                continue
            duration = record.get("duration_seconds")
            weight = record.get("invocation_weight")
            if duration is None or weight is None:
                continue
            estimate = float(duration) * float(weight) * float(factor)
            telemetry.backfill_allowance(
                str(record["run_id"]), pct=estimate, source="manual_daily_reading"
            )
            backfilled += 1
    result["backfilled_invocations"] = backfilled
    return result


def preview_allowance(
    *,
    ledger: AccountingBudgetLedger,
    records: list[dict[str, Any]],
    role: str,
    pct: float,
    ts: float | None = None,
) -> dict[str, Any]:
    """Compute a calibration without mutating allowance or telemetry stores."""
    if not math.isfinite(pct) or not 0 <= pct <= 100:
        raise ValueError("allowance percentage must be between 0 and 100")
    now = time.time() if ts is None else ts
    prior = ledger.latest_allowance(role)
    prior_ts = float(prior["ts"]) if prior is not None else 0.0
    prior_pct = float(prior["pct"]) if prior is not None else None
    weighted = weighted_seconds(records, role=role, since_ts=prior_ts)
    delta = None if prior_pct is None else (
        pct - prior_pct if pct >= prior_pct else pct
    )
    factor = (
        delta / weighted
        if delta is not None and weighted > 0
        else None
    )
    backfilled = sum(
        1
        for record in records
        if record.get("role") == role
        and _started(record) > prior_ts
        and not record.get("suppressed")
        and record.get("result_status") != "suppressed"
        and record.get("duration_seconds") is not None
        and record.get("invocation_weight") is not None
    ) if factor is not None else 0
    return {
        "dry_run": True,
        "role": role,
        "source": "manual_daily_reading",
        "ts": now,
        "prior_ts": prior_ts if prior is not None else None,
        "prior_pct": prior_pct,
        "pct": pct,
        "allowance_delta_pct": delta,
        "cycle_reset": prior_pct is not None and pct < prior_pct,
        "weighted_seconds": weighted,
        "pct_per_weighted_second": factor,
        "backfilled_invocations": backfilled,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailroom", type=Path)
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    summary = sub.add_parser("summary")
    summary.add_argument("--since", default="7d")
    task = sub.add_parser("task")
    task.add_argument("task_id")
    model = sub.add_parser("model")
    model.add_argument("tier")
    module = sub.add_parser("module")
    module.add_argument("name")
    sub.add_parser("wasted-runs")
    cost = sub.add_parser("accepted-cost")
    cost.add_argument("--group-by", choices=("task_class", "role", "model_tier"), required=True)
    allowance = sub.add_parser("record-allowance")
    allowance.add_argument("--role", required=True)
    allowance.add_argument("--pct", required=True, type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mailroom is None:
        if args.dry_run:
            print("--dry-run requires an explicit --mailroom", file=sys.stderr)
            return 2
        mailroom = find_mailroom()
    else:
        mailroom = args.mailroom
    telemetry_path = args.telemetry or mailroom / "telemetry/invocations.jsonl"
    ledger_path = args.ledger or mailroom / "governor/budget_ledger.sqlite3"
    records, errors = read_invocations(telemetry_path)
    if errors:
        print(f"TELEMETRY-DEGRADED: {len(errors)} unreadable event(s)", file=sys.stderr)
    try:
        if args.command == "summary":
            output = summarize(filter_records(records, since_ts=parse_since(args.since)))
        elif args.command == "task":
            output = filter_records(records, task=args.task_id)
        elif args.command == "model":
            output = filter_records(records, model=args.tier)
        elif args.command == "module":
            output = filter_records(records, module=args.name)
        elif args.command == "wasted-runs":
            output = wasted_runs(records)
        elif args.command == "accepted-cost":
            output = accepted_cost(records, args.group_by)
        elif args.dry_run:
            ledger = AccountingBudgetLedger(ledger_path, read_only=True)
            output = preview_allowance(
                ledger=ledger,
                records=records,
                role=args.role,
                pct=args.pct,
            )
        else:
            ledger = AccountingBudgetLedger(ledger_path)
            output = record_allowance(
                ledger=ledger,
                telemetry=AnalyticsTelemetry(telemetry_path),
                records=records,
                role=args.role,
                pct=args.pct,
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
