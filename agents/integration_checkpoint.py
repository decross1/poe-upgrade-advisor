"""Durable red-main timeline for merge pause, repair, reserve, and HALT."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.degradation import DegradationController, DegradationSignals, RunReportData


@dataclass(frozen=True)
class CheckpointVerdict:
    main_red: bool
    red_hours: float
    merges_paused: bool
    repair_task_filed: bool
    revert_requested: bool
    reserve_unlocked: bool
    halted: bool


class IntegrationCheckpoint:
    """Apply each red-main escalation once and preserve its evidence."""

    def __init__(self, mailroom: str | Path, *, now=time.time) -> None:
        self.mailroom = Path(mailroom)
        self._now = now
        self.state_path = self.mailroom / "governor/integration_checkpoint.json"

    def _read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_json_once(self, path: Path, value: dict[str, Any]) -> bool:
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2, sort_keys=True)
                stream.write("\n")
            return True
        except FileExistsError:
            return False

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    def observe(
        self,
        *,
        main_red: bool,
        last_merged_pr: int | None = None,
        report_data: RunReportData | None = None,
    ) -> CheckpointVerdict:
        now = float(self._now())
        state = self._read_state()
        pause = self.mailroom / "PAUSE_MERGES"
        if not main_red:
            if pause.exists():
                pause.unlink()
            self._write_state({"status": "green", "recovered_at": now})
            return CheckpointVerdict(False, 0.0, False, False, False, False, False)

        red_since = float(state.get("red_since", now)) if state.get("status") == "red" else now
        red_hours = max(0.0, (now - red_since) / 3600)
        pause.parent.mkdir(parents=True, exist_ok=True)
        pause.touch(exist_ok=True)

        repair_path = self.mailroom / "priority/000-main-repair.json"
        self._write_json_once(repair_path, {
            "schema_version": "1.0",
            "task_id": "ORG-MAIN-REPAIR",
            "priority": 0,
            "reason": "main is red; repair before normal queue",
            "created_at": now,
            "last_merged_pr": last_merged_pr,
        })

        revert_path = self.mailroom / "integration_actions/revert-last-merge.json"
        revert_requested = revert_path.exists()
        if red_hours >= 6 and last_merged_pr is not None:
            self._write_json_once(revert_path, {
                "schema_version": "1.0",
                "action": "revert_last_merged_pr",
                "pr": last_merged_pr,
                "requested_at": now,
                "red_since": red_since,
            })
            revert_requested = True

        reserve_path = self.mailroom / "governor/reserve-unlocked.json"
        reserve_unlocked = reserve_path.exists()
        if red_hours >= 12:
            self._write_json_once(reserve_path, {
                "schema_version": "1.0",
                "reason": "main red for at least 12 hours",
                "unlocked_at": now,
                "red_since": red_since,
            })
            reserve_unlocked = True

        halted = (self.mailroom / "HALT").exists()
        if red_hours >= 24:
            controller = DegradationController(self.mailroom, now=self._now)
            controller.step(
                DegradationSignals(unrecoverable_main=True),
                report_data=report_data or RunReportData(),
            )
            halted = True

        self._write_state({
            "status": "red",
            "red_since": red_since,
            "last_checked": now,
            "last_merged_pr": last_merged_pr,
            "red_hours": red_hours,
        })
        return CheckpointVerdict(
            True,
            red_hours,
            True,
            repair_path.exists(),
            revert_requested,
            reserve_unlocked,
            halted,
        )
