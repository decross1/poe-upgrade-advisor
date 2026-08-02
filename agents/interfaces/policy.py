"""Policy loading across the lane split.

Execution policy is deliberately kept in TWO files so the two lanes never edit
the same YAML:

- `agents/governor/policy.yaml`      — Lane A. Per-task execution: attempt
  caps, backoff, circuit breakers, per-tier execution classes.
- `agents/governor/run_policy.yaml`  — Lane B. Aggregate: per-day caps, the
  `run:` budget block with reserve and burn-down, and the degradation ladder.

`load_policy()` merges them. A key defined in both is a lane-boundary
violation and raises, rather than silently letting one lane's value win.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TASK_POLICY_FILENAME = "policy.yaml"
RUN_POLICY_FILENAME = "run_policy.yaml"

#: Top-level keys each lane owns. Enforced by `load_policy`.
LANE_A_KEYS = frozenset({
    "per_task_max_invocations", "backoff", "circuit_breaker_consecutive_failures",
    "execution_classes", "circuit_breakers", "recovery", "progress",
})
LANE_B_KEYS = frozenset({
    "per_day_max", "daily_reset_hour_utc", "daily", "run", "degradation", "roles",
})


class PolicyError(ValueError):
    """Policy is missing, unparseable, or violates the lane key split."""


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise PolicyError(f"{path} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise PolicyError(f"{path} must contain a mapping, got {type(data).__name__}")
    return data


def load_policy(governor_dir: str | Path) -> dict:
    """Merge task policy and run policy, refusing overlapping keys."""
    d = Path(governor_dir)
    task = _read(d / TASK_POLICY_FILENAME)
    run = _read(d / RUN_POLICY_FILENAME)
    if not task:
        raise PolicyError(f"no task policy at {d / TASK_POLICY_FILENAME}")
    overlap = set(task) & set(run)
    if overlap:
        raise PolicyError(
            f"lane boundary violated: {sorted(overlap)} defined in both "
            f"{TASK_POLICY_FILENAME} and {RUN_POLICY_FILENAME}"
        )
    return {**task, **run}


def resolve_budgets(policy: dict, packet: dict | None = None, tier: str | None = None) -> dict:
    """Tier defaults overlaid with packet overrides.

    A packet may only **tighten** a budget. An override that loosens a tier
    default is ignored and does not raise — a task cannot buy itself more room
    than its class allows, and self-escalation of authority is forbidden
    (restart program, design principle 5).
    """
    tier = tier or (packet or {}).get("tier") or "green"
    classes = policy.get("execution_classes") or {}
    base = dict(classes.get(tier) or {})
    overrides = dict(((packet or {}).get("budgets") or {}))
    for k, v in overrides.items():
        if v is None:
            continue
        cur = base.get(k)
        if cur is None or not isinstance(cur, (int, float)) or not isinstance(v, (int, float)):
            base[k] = v
        else:
            base[k] = min(cur, v)
    return base
