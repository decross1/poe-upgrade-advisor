"""CC-2: dispatcher-verified completion, against REAL git repositories.

This is the suite where the completion proofs run for real — no pin. The
worktrees are `git clone`s of a tmp origin (test_recovery's builders), so
`origin/main`, ls-remote, and pushes all resolve exactly as they do in a
fan worktree. The central case is the PLAN's fabricated payload
`{"status": "completed", "pushed": false, "commit_sha": "0000000", ...}`:
schema-valid, and before CC-2 it was acked and recorded as a governor
success on the agent's word alone. It must be REFUSED end-to-end here.

Every test runs against a tmp-path mailroom (POB_LEDGER_DIR, autouse);
nothing touches the real mailroom.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import agents.dispatch as dispatch_mod
from agents.completion import Proof, refusal, verify_completion
from agents.dispatch import dispatch
from agents.governor import budget_governor
from tests.test_dispatch import (
    ACK,
    RETAIN,
    acked,
    fake,
    governor_rows,
    tele_lines,
    write_message,
)
from tests.test_recovery import _git, clone_worktree, make_origin

# ------------------------------------------------------------------ fixtures
# Thin copies of the dispatch-suite autouse fixtures (fixtures do not cross
# module boundaries). Deliberately ABSENT: the completion_proofs_pass pin.


@pytest.fixture(autouse=True)
def always_allow_run_budget(monkeypatch: pytest.MonkeyPatch):
    from agents.interfaces.run_budget import AlwaysAllow
    monkeypatch.setenv("RUN_BUDGET", "0")
    monkeypatch.setattr(dispatch_mod, "load_run_budget_port",
                        lambda *a, **k: AlwaysAllow(warn=lambda m: None))


@pytest.fixture(autouse=True)
def mailroom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "mailroom"
    monkeypatch.setenv("POB_LEDGER_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def counter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fp = tmp_path / "invocations.count"
    monkeypatch.setenv("COUNTER_FILE", str(fp))
    return fp


@pytest.fixture(autouse=True)
def no_preflight(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PREFLIGHT", "0")


@pytest.fixture(autouse=True)
def no_gh(monkeypatch: pytest.MonkeyPatch):
    class _FakeSubprocess:
        def run(self, argv, **kwargs):
            return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(budget_governor, "subprocess", _FakeSubprocess())


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    return make_origin(tmp_path)


@pytest.fixture
def worktree(origin: Path, tmp_path: Path) -> Path:
    return clone_worktree(origin, tmp_path / "wt")


def finish_event(mailroom: Path) -> dict:
    events = [ln for ln in tele_lines(mailroom) if ln.get("event") == "finish"]
    assert len(events) == 1
    return events[0]


def proofs_by_id(event: dict) -> dict:
    return {p["proof_id"]: p for p in (event.get("completion_proofs") or [])}


# ------------------------------------------------------------------ e2e

def test_fabricated_completion_refused_end_to_end(mailroom, worktree):
    """THE CC-2 case. Before: ack + governor success + spend row on the
    agent's word. After: retained, success=False, refusal named proof by
    proof in telemetry, and the fabricated artifact preserved as evidence
    in the run record."""
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("fabricating_agent.py"))

    assert out.invoked is True
    assert out.result_status == "completed"
    assert out.ack == RETAIN
    assert msg["message_id"] not in acked(mailroom, "backend")
    assert governor_rows(mailroom) == [("backend", "TASK-7", 0)]

    ev = finish_event(mailroom)
    assert ev["result_error"].startswith("completion refused")
    pr = proofs_by_id(ev)
    assert pr["commit_exists"]["passed"] is False
    assert pr["pushed_remote_agreement"]["passed"] is False
    # A4-precedent unknown semantics: pattern unset is recorded, not failed.
    assert pr["branch_pattern"]["passed"] is None
    # The fabricated claim itself is preserved evidence (A1 sweep).
    swept = list((mailroom / "runs").glob("*/agent-result.json"))
    assert len(swept) == 1
    assert json.loads(swept[0].read_text())["commit_sha"] == "0000000"


def test_genuine_completion_acks_and_persists_ls_remote(mailroom, worktree):
    """Verification that refuses honest work is as broken as verification
    that acks fabricated work: a real commit on a real pushed branch must
    ack, record a governor success, and leave the A6 ls-remote evidence in
    the run record."""
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("truthful_agent.py"))

    assert out.result_status == "completed"
    assert out.ack == ACK
    assert msg["message_id"] in acked(mailroom, "backend")
    assert governor_rows(mailroom) == [("backend", "TASK-7", 1)]

    ev = finish_event(mailroom)
    pr = proofs_by_id(ev)
    assert pr["commit_exists"]["passed"] is True
    assert pr["pushed_remote_agreement"]["passed"] is True
    assert pr["branch_pattern"]["passed"] is None  # pm ANSWER pending
    assert pr["ls_remote_recorded"]["passed"] is True

    records = list((mailroom / "runs").glob("*/ls-remote.json"))
    assert len(records) == 1
    obs = json.loads(records[0].read_text())
    sha = _git("rev-parse", "task/TASK-7-S1", cwd=worktree)
    assert obs["branch"] == "task/TASK-7-S1"
    assert obs["sha"] == sha.strip()
    assert obs["claimed_commit_sha"] == sha.strip()
    assert obs["observed_at"] > 0


def test_rollback_lever_documented(mailroom, worktree, monkeypatch):
    """COMPLETION_PROOFS=0 is the operator rollback lever (ANTI_LOOP
    idiom), default ON. Off restores the legacy self-report ack — this
    test exists so the lever's effect is pinned and visible, not
    discovered."""
    monkeypatch.setenv("COMPLETION_PROOFS", "0")
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("fabricating_agent.py"))
    assert out.ack == ACK  # legacy behavior, operator's explicit choice


# ------------------------------------------------------------------ units

def _true_completion(worktree: Path) -> dict:
    """Build a genuinely-committed, genuinely-pushed result dict."""
    _git("checkout", "-q", "-b", "task/TASK-9", cwd=worktree)
    (worktree / "w.txt").write_text("w\n")
    _git("add", "w.txt", cwd=worktree)
    _git("commit", "-q", "-m", "w", cwd=worktree)
    sha = _git("rev-parse", "HEAD", cwd=worktree).strip()
    _git("push", "-q", "origin", "task/TASK-9", cwd=worktree)
    return {"schema_version": "1.0", "run_id": "run-unit0001",
            "task_id": "TASK-9", "status": "completed", "summary": "w",
            "commit_sha": sha, "pushed": True, "branch": "task/TASK-9",
            "acceptance_criteria": []}


def _run(res, worktree, mailroom, params) -> dict:
    proofs = verify_completion(res, worktree=worktree, mailroom=mailroom,
                               run_id="run-unit0001", params=params)
    return {p.proof_id: p for p in proofs}


def test_commit_must_exist(mailroom, worktree):
    res = _true_completion(worktree)
    res["commit_sha"] = "a" * 40  # not an object in this repo
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "commit_exists"}]})
    assert pr["commit_exists"].passed is False


def test_pushed_false_refuses_even_with_real_commit(mailroom, worktree):
    res = _true_completion(worktree)
    res["pushed"] = False
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "pushed_remote_agreement"}]})
    assert pr["pushed_remote_agreement"].passed is False
    assert "pushed=false" in pr["pushed_remote_agreement"].detail


def test_remote_tip_must_match_claim(mailroom, worktree):
    """A stale/forged SHA against a real branch: remote moved past the
    claim (or never was the claim) → refuse, naming both SHAs."""
    res = _true_completion(worktree)
    (worktree / "w2.txt").write_text("w2\n")
    _git("add", "w2.txt", cwd=worktree)
    _git("commit", "-q", "-m", "w2", cwd=worktree)
    _git("push", "-q", "origin", "task/TASK-9", cwd=worktree)  # remote moves
    pr = _run(res, worktree, mailroom,  # still claims the OLD sha
              {"proofs": [{"id": "pushed_remote_agreement"}]})
    assert pr["pushed_remote_agreement"].passed is False
    assert "not the claimed" in pr["pushed_remote_agreement"].detail


def test_unpushed_branch_refuses(mailroom, worktree):
    res = _true_completion(worktree)
    res["branch"] = "task/TASK-9-never-pushed"
    _git("branch", "-q", "task/TASK-9-never-pushed", cwd=worktree)
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "pushed_remote_agreement"}]})
    assert pr["pushed_remote_agreement"].passed is False
    assert "does not exist on origin" in pr["pushed_remote_agreement"].detail


def test_branch_pattern_enforced_when_ratified(mailroom, worktree):
    res = _true_completion(worktree)
    pattern = r"(task|canary|repair)/TASK-[0-9]+(-S[0-9]+)?"
    ok = _run(res, worktree, mailroom,
              {"branch_pattern": pattern,
               "proofs": [{"id": "branch_pattern"}]})
    assert ok["branch_pattern"].passed is True
    res["branch"] = "definitely/not-a-task-branch"
    bad = _run(res, worktree, mailroom,
               {"branch_pattern": pattern,
                "proofs": [{"id": "branch_pattern"}]})
    assert bad["branch_pattern"].passed is False


def test_unknown_ratified_proof_id_refuses(mailroom, worktree):
    """A yaml proof id with no registered checker is a contract/code
    mismatch — refuse rather than silently skip a ratified proof."""
    res = _true_completion(worktree)
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "proof_seven_from_v1_0"}]})
    assert pr["proof_seven_from_v1_0"].passed is False
    assert refusal(list(pr.values())) is not None


def test_not_evaluable_alone_does_not_refuse():
    proofs = [Proof("branch_pattern", None, "pattern unset"),
              Proof("commit_exists", True, "ok")]
    assert refusal(proofs) is None
    assert refusal([Proof("commit_exists", False, "no")]) is not None
