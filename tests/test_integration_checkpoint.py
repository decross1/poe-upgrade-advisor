from __future__ import annotations

import json

from agents.degradation import RunReportData
from agents.integration_checkpoint import IntegrationCheckpoint


def test_red_main_timeline_is_idempotent_and_escalates_at_each_boundary(tmp_path):
    mailroom = tmp_path / "mailroom"
    clock = {"now": 1000.0}
    checkpoint = IntegrationCheckpoint(mailroom, now=lambda: clock["now"])

    first = checkpoint.observe(main_red=True, last_merged_pr=77)
    assert first.merges_paused and first.repair_task_filed
    assert not first.revert_requested and not first.reserve_unlocked and not first.halted
    assert (mailroom / "PAUSE_MERGES").is_file()
    repair = json.loads((mailroom / "priority/000-main-repair.json").read_text())
    assert repair["priority"] == 0 and repair["task_id"] == "ORG-MAIN-REPAIR"

    clock["now"] += 6 * 3600
    six = checkpoint.observe(main_red=True, last_merged_pr=77)
    assert six.revert_requested and not six.reserve_unlocked
    revert = json.loads((mailroom / "integration_actions/revert-last-merge.json").read_text())
    assert revert["pr"] == 77

    clock["now"] += 6 * 3600
    twelve = checkpoint.observe(main_red=True, last_merged_pr=77)
    assert twelve.reserve_unlocked and not twelve.halted

    clock["now"] += 12 * 3600
    day = checkpoint.observe(
        main_red=True,
        last_merged_pr=77,
        report_data=RunReportData(tasks_landed=["TASK-BEFORE-RED"]),
    )
    assert day.halted
    assert (mailroom / "HALT").is_file()
    assert "TASK-BEFORE-RED" in (mailroom / "RUN-REPORT.md").read_text()


def test_green_recovery_removes_pause_and_resets_red_clock(tmp_path):
    mailroom = tmp_path / "mailroom"
    clock = {"now": 100.0}
    checkpoint = IntegrationCheckpoint(mailroom, now=lambda: clock["now"])
    checkpoint.observe(main_red=True, last_merged_pr=1)
    clock["now"] += 100
    green = checkpoint.observe(main_red=False)
    assert not green.main_red and not green.merges_paused
    assert not (mailroom / "PAUSE_MERGES").exists()
    assert json.loads((mailroom / "governor/integration_checkpoint.json").read_text())[
        "status"
    ] == "green"


def test_revert_waits_for_known_last_merge(tmp_path):
    mailroom = tmp_path / "mailroom"
    clock = {"now": 1.0}
    checkpoint = IntegrationCheckpoint(mailroom, now=lambda: clock["now"])
    checkpoint.observe(main_red=True)
    clock["now"] += 7 * 3600
    verdict = checkpoint.observe(main_red=True)
    assert not verdict.revert_requested
    assert not (mailroom / "integration_actions/revert-last-merge.json").exists()
