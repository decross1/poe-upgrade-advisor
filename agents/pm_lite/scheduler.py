#!/usr/bin/env python3
"""pm-lite: deterministic org event scheduler and state reducer.

This module deliberately has no model invocation adapter. It observes durable
state, emits deterministic decisions, assigns dependency-ready packets, and
escalates only the four judgement classes reserved for the PM/arbiter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agents.accounting import AnalyticsTelemetry
from agents.degradation import arbiter_after_circuit_break
from agents.interfaces.packet import PacketError, load_packet, packet_path
from agents.interfaces.policy import load_policy
from agents.postmaster import ledger as ledger_mod

JUDGEMENT_INTENTS = {"ARBITRATION_REQUEST"}
JUDGEMENT_EVENT_KINDS = {"untrusted_intake", "arbitration_request", "dead_letter", "adr_rfc"}
ROUTINE_EVENT_KINDS = {
    "issue_transition",
    "label_transition",
    "pr_readiness",
    "review_age",
    "ci_completion",
    "merge_eligibility",
    "ttl_expiry",
    "blocker_change",
    "budget",
    "health",
    "task_completed",
}
STALL_INVOCATIONS = 3
STALL_WINDOW_SECONDS = 12 * 3600
MERGE_ALARM_SECONDS = 4 * 3600
DEFAULT_TTL_SECONDS = 24 * 3600


@dataclass(frozen=True)
class SchedulerAction:
    kind: str
    key: str
    detail: str
    target_role: str | None = None
    task_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PollReport:
    actions: tuple[SchedulerAction, ...]
    model_invocations: int = 0


def _utc_stamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


class PmLiteScheduler:
    """One deterministic poll cycle over ledger, GitHub and durable state."""

    def __init__(
        self,
        repo: str | Path,
        mailroom: str | Path,
        *,
        now: Callable[[], float] = time.time,
        preflight_fn: Callable[..., Any] | None = None,
        gh: Callable[..., str | None] | None = None,
        merge_runner: Callable[[int], Any] | None = None,
        commit_probe: Callable[[str, float], bool] | None = None,
        config: dict[str, Any] | None = None,
        telemetry: Any | None = None,
    ) -> None:
        self.repo = Path(repo)
        self.mailroom = Path(mailroom)
        self._now = now
        self._preflight_fn = preflight_fn
        self._gh = gh or self._run_gh
        self._merge_runner = merge_runner or self._run_merge_robot
        self._commit_probe = commit_probe or self._has_recent_commit
        self.config = config if config is not None else self._load_live_config()
        self.telemetry = telemetry or AnalyticsTelemetry(
            self.mailroom / "telemetry/invocations.jsonl"
        )
        self.state_dir = self.mailroom / "pm_lite"
        self.state_path = self.state_dir / "state.json"
        self.actions_path = self.state_dir / "actions.jsonl"
        self._state = self._load_state()
        self._actions: list[SchedulerAction] = []

    def _load_live_config(self) -> dict[str, Any]:
        override = os.environ.get("POSTMASTER_CONFIG")
        candidates = [Path(override)] if override else []
        for base in (self.repo, *self.repo.parents):
            candidates.append(base / "agents/postmaster/config.yaml")
        for path in candidates:
            if not path.is_file():
                continue
            try:
                value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                return {}
            return value if isinstance(value, dict) else {}
        return {}

    def _load_state(self) -> dict[str, Any]:
        default = {
            "processed_events": [],
            "emitted_actions": [],
            "escalated": [],
            "assigned": [],
            "completed": [],
            "ready_since": {},
            "dead_letters_seen": [],
        }
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        if not isinstance(loaded, dict):
            return default
        return {**default, **loaded}

    def _save_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary, self.state_path)

    def _action(
        self,
        kind: str,
        key: str,
        detail: str,
        *,
        target_role: str | None = None,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
        once: bool = True,
    ) -> None:
        identity = f"{kind}:{key}"
        emitted = set(self._state["emitted_actions"])
        if once and identity in emitted:
            return
        action = SchedulerAction(
            kind, key, detail, target_role, task_id, payload or {}
        )
        self._actions.append(action)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": _utc_stamp(self._now()),
            "body": f"[DECISION] {kind}: {detail}",
            **asdict(action),
        }
        with self.actions_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        if once:
            self._state["emitted_actions"].append(identity)

    def _suppress(self, reason: str, **fields: Any) -> None:
        self.telemetry.suppressed(
            role="pm",
            task_id=fields.pop("task_id", "ORG"),
            decision="suppressed_no_model",
            suppressed_reason=f"pm_lite:{reason}",
            **fields,
        )

    def _all_messages_with_age(self) -> list[tuple[dict[str, Any], float]]:
        messages: list[tuple[dict[str, Any], float]] = []
        for path in sorted((self.mailroom / "messages").glob("*.json")):
            try:
                message = json.loads(path.read_text(encoding="utf-8"))
                ledger_mod.VALIDATOR.validate(message)
                messages.append((message, path.stat().st_mtime))
            except Exception as exc:  # noqa: BLE001 - poison entries become decisions
                self._action(
                    "ledger_invalid",
                    path.name,
                    f"unreadable or invalid ledger entry: {type(exc).__name__}: {exc}",
                )
        return messages

    def _circuit_broken_roles(self) -> set[str]:
        path = self.mailroom / "governor/governor_ledger.sqlite3"
        if not path.is_file():
            return set()
        try:
            threshold = int(
                load_policy(self.repo / "agents/governor")[
                    "circuit_breaker_consecutive_failures"
                ]
            )
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            rows = db.execute(
                "SELECT role, task_id, success FROM ledger ORDER BY ts DESC"
            ).fetchall()
        except (OSError, sqlite3.Error, KeyError, TypeError, ValueError):
            return set()
        finally:
            if "db" in locals():
                db.close()
        streaks: dict[tuple[str, str], int] = {}
        closed: set[tuple[str, str]] = set()
        for role, task_id, success in rows:
            key = (str(role), str(task_id))
            if key in closed:
                continue
            if success:
                closed.add(key)
                continue
            streaks[key] = streaks.get(key, 0) + 1
        return {role for (role, _), count in streaks.items() if count >= threshold}

    def _arbiter(self) -> str | None:
        return arbiter_after_circuit_break(
            self.config, circuit_broken=self._circuit_broken_roles()
        )

    def _judgement_message(
        self,
        *,
        trigger: str,
        key: str,
        detail: str,
        target: str,
        task_id: str | None,
        source: dict[str, Any] | None = None,
    ) -> bool:
        if source is not None and source["to_role"] == target:
            return True
        if source is not None:
            hop = int(source.get("hop_count", 0)) + 1
            maximum = int(source.get("max_hops", 6))
            if hop >= maximum:
                self._action(
                    "judgement_route_refused_hop_cap",
                    key,
                    f"cannot route judgement to {target}: hop {hop}/{maximum}",
                    target_role=target,
                    task_id=task_id,
                )
                return False
            message = {
                **source,
                "message_id": str(uuid.uuid4()),
                "idempotency_key": f"pm-lite:judgement:{trigger}:{key}:{target}",
                "from_role": "pm",
                "to_role": target,
                "hop_count": hop,
            }
        else:
            message = {
                "schema_version": "1.0",
                "message_id": str(uuid.uuid4()),
                "idempotency_key": f"pm-lite:judgement:{trigger}:{key}:{target}",
                "task_id": task_id or "ORG",
                "from_role": "pm",
                "to_role": target,
                "intent": "SYNC",
                "hop_count": 0,
                "max_hops": 6,
                "refs": {},
                "body_markdown": f"[DECISION] Judgement required — {trigger}: {detail}",
            }
        try:
            self._write_message(message, prefix="judgement")
        except Exception as exc:  # noqa: BLE001 - invalid routing fails closed
            self._action(
                "judgement_transport_blocked",
                key,
                f"ledger rejected judgement route: {exc}",
                target_role=target,
                task_id=task_id,
            )
            return False
        return True

    def _escalate(
        self,
        trigger: str,
        key: str,
        detail: str,
        *,
        task_id: str | None = None,
        source: dict[str, Any] | None = None,
    ) -> str | None:
        identity = f"{trigger}:{key}"
        if identity in set(self._state["escalated"]):
            return self._arbiter()
        target = self._arbiter()
        if target is None:
            self._action(
                "judgement_unroutable",
                identity,
                f"{trigger} requires judgement but no arbiter is available: {detail}",
                task_id=task_id,
            )
            return None
        if target != "pm":
            self._action(
                "arbiter_promoted",
                target,
                f"PM circuit-broken; promoted {target} from live arbiter_fallback",
                target_role=target,
            )
        self._action(
            "judgement",
            identity,
            f"{trigger}: {detail}",
            target_role=target,
            task_id=task_id,
        )
        routed = self._judgement_message(
            trigger=trigger,
            key=key,
            detail=detail,
            target=target,
            task_id=task_id,
            source=source,
        )
        if not routed:
            return None
        self._state["escalated"].append(identity)
        return target

    def _ack_pm_message(self, message_id: str) -> None:
        path = self.mailroom / "cursors/pm.acked"
        path.parent.mkdir(parents=True, exist_ok=True)
        if message_id in ledger_mod.acked_ids(self.mailroom, "pm"):
            return
        with path.open("a", encoding="utf-8") as stream:
            stream.write(message_id + "\n")

    def _process_ledger(self) -> None:
        acked = ledger_mod.acked_ids(self.mailroom, "pm")
        ttl = int(self.config.get("task_ttl_seconds", DEFAULT_TTL_SECONDS))
        now = self._now()
        for message, created_at in self._all_messages_with_age():
            if message["to_role"] != "pm" or message["message_id"] in acked:
                continue
            if str(message["idempotency_key"]).startswith("pm-lite:judgement:"):
                continue
            key = message["message_id"]
            if message.get("untrusted") or message["intent"] == "INTAKE_TICKET":
                target = self._escalate(
                    "untrusted_intake",
                    key,
                    message["body_markdown"].splitlines()[0][:200],
                    task_id=message["task_id"],
                    source=message,
                )
                if target is not None and target != "pm":
                    self._ack_pm_message(key)
                    self._suppress(
                        "judgement_reassigned",
                        task_id=message["task_id"],
                        message_id=key,
                    )
            elif message["intent"] in JUDGEMENT_INTENTS:
                target = self._escalate(
                    "arbitration_request",
                    key,
                    message["body_markdown"].splitlines()[0][:200],
                    task_id=message["task_id"],
                    source=message,
                )
                if target is not None and target != "pm":
                    self._ack_pm_message(key)
                    self._suppress(
                        "judgement_reassigned",
                        task_id=message["task_id"],
                        message_id=key,
                    )
            elif (message.get("refs") or {}).get("adr"):
                target = self._escalate(
                    "adr_rfc",
                    key,
                    message["body_markdown"].splitlines()[0][:200],
                    task_id=message["task_id"],
                    source=message,
                )
                if target is not None and target != "pm":
                    self._ack_pm_message(key)
                    self._suppress(
                        "judgement_reassigned",
                        task_id=message["task_id"],
                        message_id=key,
                    )
            else:
                self._action(
                    "ledger_observed",
                    key,
                    f"{message['intent']} for {message['task_id']} is mechanically queued",
                    task_id=message["task_id"],
                )
                self._ack_pm_message(key)
                self._suppress(
                    "routine_message",
                    task_id=message["task_id"],
                    message_id=key,
                )
            if now - created_at >= ttl and message["task_id"] != "ORG":
                self._park_task(
                    message["task_id"],
                    message.get("to_role", "pm"),
                    f"TTL expired after {ttl}s",
                    key=f"ttl:{key}",
                )

    def _load_preflight(self) -> Callable[..., Any] | None:
        if self._preflight_fn is not None:
            return self._preflight_fn
        try:
            from agents.preflight import preflight
        except ImportError:
            return None
        return preflight

    def _message_by_id(self) -> dict[str, dict[str, Any]]:
        return {
            message["message_id"]: message
            for message, _ in self._all_messages_with_age()
            if "message_id" in message
        }

    def _requeue_changed_blockers(self) -> None:
        preflight = self._load_preflight()
        records = sorted((self.mailroom / "blocked").glob("*/*.json"))
        if records and preflight is None:
            self._action(
                "blocked_check_unavailable",
                "agents.preflight",
                "blocked records exist but Lane A preflight is not integrated",
            )
            return
        messages = self._message_by_id()
        for path in records:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                original = messages[record["message_id"]]
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                self._action(
                    "blocked_record_invalid",
                    str(path),
                    f"cannot recheck blocked record: {exc}",
                )
                continue
            packet = None
            candidate = packet_path(self.repo, record["task_id"])
            if candidate.is_file():
                try:
                    packet = load_packet(candidate)
                except PacketError as exc:
                    self._action(
                        "blocked_packet_invalid",
                        record["task_id"],
                        str(exc),
                        task_id=record["task_id"],
                    )
                    continue
            verdict = preflight(
                original,
                packet=packet,
                blocked_dir=self.mailroom / "blocked",
                role=record["role"],
            )
            if verdict.fingerprint == record.get("fingerprint"):
                self._suppress(
                    "unchanged_blocker",
                    task_id=record["task_id"],
                    message_id=record["message_id"],
                )
                continue
            clone = dict(original)
            clone["message_id"] = str(uuid.uuid4())
            clone["idempotency_key"] = (
                f"pm-lite:requeue:{original['message_id']}:{verdict.fingerprint}"
            )
            clone["hop_count"] = int(original.get("hop_count", 0)) + 1
            if clone["hop_count"] >= int(original.get("max_hops", 6)):
                self._action(
                    "blocker_requeue_refused_hop_cap",
                    record["task_id"],
                    f"requeue would reach hop {clone['hop_count']}/"
                    f"{original.get('max_hops', 6)}",
                    target_role=record["role"],
                    task_id=record["task_id"],
                )
                continue
            self._write_message(clone, prefix="requeue")
            self._action(
                "blocker_requeued",
                record["task_id"],
                f"fingerprint changed {record.get('fingerprint')} -> {verdict.fingerprint}",
                target_role=record["role"],
                task_id=record["task_id"],
                payload={"message_id": clone["message_id"]},
            )

    def _write_message(self, message: dict[str, Any], *, prefix: str) -> Path:
        ledger_mod.VALIDATOR.validate(message)
        directory = self.mailroom / "messages"
        directory.mkdir(parents=True, exist_ok=True)
        for existing in directory.glob("*.json"):
            try:
                prior = json.loads(existing.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if prior.get("idempotency_key") == message["idempotency_key"]:
                return existing
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = directory / (
            f"{stamp}-pm-to-{message['to_role']}-{prefix}-"
            f"{message['message_id'][:8]}.json"
        )
        with path.open("x", encoding="utf-8") as stream:
            json.dump(message, stream, indent=2)
        return path

    def _dead_letters(self) -> None:
        for path in sorted((self.mailroom / "dead_letter").glob("*/*.json")):
            key = str(path.relative_to(self.mailroom / "dead_letter"))
            if key in set(self._state["dead_letters_seen"]):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._action("dead_letter_invalid", key, str(exc))
                continue
            target = self._escalate(
                "dead_letter",
                key,
                record.get("reason", "re-triage required"),
                task_id=record.get("task_id"),
            )
            if target is not None:
                self._state["dead_letters_seen"].append(key)

    def _park_task(self, task_id: str, role: str, reason: str, *, key: str) -> None:
        path = self.state_dir / "parked" / f"{task_id}.json"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "task_id": task_id,
                        "role": role,
                        "reason": reason,
                        "parked_at": _utc_stamp(self._now()),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        self._action("task_parked", key, reason, task_id=task_id)

    def _has_recent_commit(self, task_id: str, since: float) -> bool:
        run = subprocess.run(
            [
                "git",
                "log",
                "--all",
                "--format=%H",
                f"--since=@{int(since)}",
                f"--grep={task_id}",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
        )
        return run.returncode == 0 and bool(run.stdout.strip())

    def _detect_stalls(self) -> None:
        path = self.mailroom / "governor/governor_ledger.sqlite3"
        if not path.is_file():
            return
        since = self._now() - STALL_WINDOW_SECONDS
        try:
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            rows = db.execute(
                "SELECT role, task_id, COUNT(*) FROM ledger "
                "WHERE ts>=? AND task_id!='ORG' GROUP BY role, task_id "
                "HAVING COUNT(*)>=?",
                (since, STALL_INVOCATIONS),
            ).fetchall()
        except sqlite3.Error as exc:
            self._action("stall_check_failed", str(path), str(exc))
            return
        finally:
            if "db" in locals():
                db.close()
        for role, task_id, count in rows:
            if self._commit_probe(str(task_id), since):
                continue
            key = f"stall:{role}:{task_id}"
            self._park_task(
                str(task_id),
                str(role),
                f"{count} invocations in 12h with zero commits",
                key=key,
            )
            dead = self.mailroom / "dead_letter" / str(task_id) / "pm-lite-stall.json"
            if not dead.exists():
                dead.parent.mkdir(parents=True, exist_ok=True)
                dead.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "task_id": task_id,
                            "role": role,
                            "reason": f"{count} invocations in 12h with zero commits",
                            "attempts": count,
                            "dead_lettered_by": "pm-lite",
                            "created_at": self._now(),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

    def _load_backlog(self) -> list[dict[str, Any]]:
        path = self.state_dir / "backlog.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def _assign_next(self) -> None:
        completed = set(self._state["completed"])
        assigned = set(self._state["assigned"])
        indexed = list(enumerate(self._load_backlog()))
        indexed.sort(key=lambda item: (int(item[1].get("priority", 100)), item[0]))
        for _, entry in indexed:
            task_id = entry.get("task_id")
            if not isinstance(task_id, str) or task_id in assigned or task_id in completed:
                continue
            if not set(entry.get("depends_on") or []) <= completed:
                continue
            try:
                packet = load_packet(packet_path(self.repo, task_id))
            except PacketError as exc:
                self._action("packet_not_assignable", str(task_id), str(exc), task_id=task_id)
                continue
            message = {
                "schema_version": "1.0",
                "message_id": str(uuid.uuid4()),
                "idempotency_key": f"{task_id}:TASK_ASSIGN:pm-lite",
                "task_id": task_id,
                "from_role": "pm",
                "to_role": packet["owner_role"],
                "intent": "TASK_ASSIGN",
                "hop_count": 0,
                "max_hops": 6,
                "refs": {"issue": packet["issue"]} if packet.get("issue") else {},
                "body_markdown": f"[DECISION] Assign dependency-ready packet {task_id}.",
            }
            try:
                self._write_message(message, prefix="TASK_ASSIGN")
            except Exception as exc:  # noqa: BLE001 - schema mismatch fails closed
                self._action(
                    "packet_transport_blocked",
                    task_id,
                    f"ledger rejected packet identity: {exc}",
                    task_id=task_id,
                )
                continue
            self._state["assigned"].append(task_id)
            self._action(
                "packet_assigned",
                task_id,
                f"assigned next dependency-ready packet to {packet['owner_role']}",
                target_role=packet["owner_role"],
                task_id=task_id,
                payload={"message_id": message["message_id"]},
            )
            return

    def _gh_json(self, *args: str) -> Any:
        raw = self._gh(*args)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _run_gh(self, *args: str) -> str | None:
        try:
            run = subprocess.run(
                ["gh", *args],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return run.stdout if run.returncode == 0 else None

    def _ready_prs(self) -> list[dict[str, Any]]:
        value = self._gh_json(
            "pr",
            "list",
            "--state",
            "open",
            "--label",
            "ready-to-merge",
            "--json",
            "number,title",
        )
        return value if isinstance(value, list) else []

    def _local_merge_pause(self) -> str | None:
        path = self.mailroom / "PAUSE_MERGES"
        try:
            if not path.is_file():
                return None
            path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"PAUSE_MERGES unreadable: {exc}"
        return f"PAUSE_MERGES active at {path}"

    def _run_merge_robot(self, pr_number: int) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PR_NUMBER": str(pr_number),
        }
        return subprocess.run(
            ["python3", "agents/merge_robot/merge_robot.py"],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _merge_ready(self, ready_prs: Iterable[dict[str, Any]]) -> None:
        now = self._now()
        active: set[str] = set()
        for pr in ready_prs:
            number = str(pr["number"])
            active.add(number)
            first = float(self._state["ready_since"].setdefault(number, now))
            if now - first > MERGE_ALARM_SECONDS:
                self._action(
                    "merge_ready_alarm",
                    number,
                    f"PR #{number} merge-ready for over 4h",
                    payload={"pr": int(number)},
                )
        self._state["ready_since"] = {
            key: value
            for key, value in self._state["ready_since"].items()
            if key in active
        }
        if not active:
            return
        paused = self._local_merge_pause()
        if paused is not None:
            self._action("merge_suppressed", "local-pause", paused, once=False)
            return
        for number in sorted(active, key=int):
            result = self._merge_runner(int(number))
            return_code = getattr(result, "returncode", 0)
            self._action(
                "merge_robot_run",
                number,
                f"merge robot checked PR #{number}; rc={return_code}",
                payload={"pr": int(number), "returncode": return_code},
                once=False,
            )

    def _process_events(self, events: Iterable[dict[str, Any]]) -> None:
        processed = set(self._state["processed_events"])
        for event in events:
            canonical = json.dumps(event, sort_keys=True, default=str)
            event_id = str(event.get("event_id") or hashlib.sha256(canonical.encode()).hexdigest()[:16])
            if event_id in processed:
                continue
            kind = str(event.get("kind") or "")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            task_id = payload.get("task_id")
            if kind in JUDGEMENT_EVENT_KINDS:
                target = self._escalate(
                    kind,
                    event_id,
                    str(payload.get("detail", kind)),
                    task_id=task_id,
                )
                if target is None:
                    continue
            elif kind == "task_completed" and isinstance(task_id, str):
                if task_id not in self._state["completed"]:
                    self._state["completed"].append(task_id)
                self._action(kind, event_id, f"{task_id} completed", task_id=task_id)
            elif kind in ROUTINE_EVENT_KINDS:
                self._action(
                    "event_reduced",
                    event_id,
                    f"{kind} reduced deterministically",
                    task_id=task_id,
                    payload=payload,
                )
            else:
                self._action("event_unknown", event_id, f"unsupported event kind: {kind}")
            self._state["processed_events"].append(event_id)
            processed.add(event_id)

    def _spooled_events(self) -> list[dict[str, Any]]:
        events = []
        for path in sorted((self.state_dir / "events").glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._action("event_invalid", path.name, str(exc))
                continue
            if isinstance(value, dict):
                value.setdefault("event_id", path.stem)
                events.append(value)
            else:
                self._action("event_invalid", path.name, "event must be an object")
        return events

    def poll(
        self,
        *,
        events: Iterable[dict[str, Any]] = (),
        ready_prs: Iterable[dict[str, Any]] | None = None,
    ) -> PollReport:
        """Run one full cycle. The return value always reports zero model calls."""
        self._actions = []
        if (self.mailroom / "HALT").is_file():
            self._suppress("halt")
            return PollReport((), model_invocations=0)
        self._process_events([*self._spooled_events(), *events])
        self._process_ledger()
        self._requeue_changed_blockers()
        self._dead_letters()
        self._detect_stalls()
        self._assign_next()
        self._merge_ready(self._ready_prs() if ready_prs is None else ready_prs)
        if not self._actions:
            self._suppress("empty_queue")
        self._save_state()
        return PollReport(tuple(self._actions), model_invocations=0)


def _find_mailroom(repo: Path) -> Path:
    for directory in (repo, *repo.parents):
        candidate = directory / "mailroom"
        if candidate.is_dir():
            return candidate
    return repo / "mailroom"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--mailroom", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    mailroom = (args.mailroom or _find_mailroom(repo)).resolve()
    report = PmLiteScheduler(repo, mailroom).poll()
    print(json.dumps({
        "model_invocations": report.model_invocations,
        "actions": [asdict(action) for action in report.actions],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
