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

import fnmatch
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
    assert len(pr) == 15                       # the full ratified set
    assert pr["pushed"]["passed"] is False              # 3
    assert pr["branch_pattern"]["passed"] is False      # 4 (no branch)
    assert pr["commit_exists"]["passed"] is False       # 5
    assert pr["remote_agreement"]["passed"] is False    # 8
    # A4-precedent unknown semantics: packetless inputs record, not fail.
    assert pr["scope"]["passed"] is None                # 11
    assert pr["budgets"]["passed"] is None              # 14
    # A refused completion's bundle is persisted evidence.
    bundles = list((mailroom / "runs").glob("*/completion-proof.json"))
    assert len(bundles) == 1
    assert json.loads(bundles[0].read_text())["acked"] is False
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
    assert pr["commit_exists"]["passed"] is True         # 5
    assert pr["pushed"]["passed"] is True                # 3
    assert pr["branch_pattern"]["passed"] is True        # 4: ratified default
    assert pr["descends_from_base"]["passed"] is True    # 6
    assert pr["tree_clean_after_sweep"]["passed"] is True  # 7
    assert pr["remote_agreement"]["passed"] is True      # 8
    assert pr["accounting_before_ack"]["passed"] is True  # 15
    bundles = list((mailroom / "runs").glob("*/completion-proof.json"))
    assert len(bundles) == 1
    assert json.loads(bundles[0].read_text())["acked"] is True

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


def test_command_policy_never_constrains_agent_tools(mailroom, worktree):
    """T-A2, the load-bearing scope sentence: the packet policy bans
    `git push` for CHECK commands — and the agent itself must push to
    complete. truthful_agent runs a real `git push` inside its invocation
    while the packet declares (benign) checks under the same policy that
    bans pushing. Completion must still verify and ack: the policy governs
    what the DISPATCHER executes, never the agent's own tools."""
    d = worktree / "tasks" / "packets"
    d.mkdir(parents=True)
    (d / "TASK-7.json").write_text(json.dumps({
        "schema_version": "1.0", "task_id": "TASK-7",
        "owner_role": "backend", "tier": "green",
        "objective": "agent pushes; packet checks cannot",
        "files_in_scope": ["agent-work.txt"],
        "files_out_of_scope": [],
        "required_checks": ["git status --porcelain"],  # ratified entry 11
        "acceptance_criteria": [
            {"id": "AC-1", "text": "agent tools are unconstrained"}],
        "budgets": {"max_attempts": 2, "max_files_modified": 2,
                    "max_diff_lines": 100, "max_wall_clock_seconds": 60},
    }))
    # Packets are COMMITTED repo content (and tasks/packets/* is PROTECTED
    # per Lane B's B2) — an untracked packet would read as an agent
    # modification in the anti-loop changed-file set once that lands.
    _git("add", "tasks/packets/TASK-7.json", cwd=worktree)
    _git("commit", "-q", "-m", "packet: TASK-7", cwd=worktree)
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("truthful_agent.py"))

    assert out.ack == ACK          # the agent's push went through
    ev = finish_event(mailroom)
    assert proofs_by_id(ev)["remote_agreement"]["passed"] is True
    assert [c["rc"] for c in ev["required_checks"]] == [0]


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


def _run(res, worktree, mailroom, params, **kw) -> dict:
    proofs = verify_completion(res, worktree=worktree, mailroom=mailroom,
                               run_id="run-unit0001", params=params, **kw)
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
    pr = _run(res, worktree, mailroom, {"proofs": [{"id": "pushed"}]})
    assert pr["pushed"].passed is False
    assert "pushed=false" in pr["pushed"].detail


def test_remote_tip_must_match_claim(mailroom, worktree):
    """A stale/forged SHA against a real branch: remote moved past the
    claim (or never was the claim) → refuse, naming both SHAs."""
    res = _true_completion(worktree)
    (worktree / "w2.txt").write_text("w2\n")
    _git("add", "w2.txt", cwd=worktree)
    _git("commit", "-q", "-m", "w2", cwd=worktree)
    _git("push", "-q", "origin", "task/TASK-9", cwd=worktree)  # remote moves
    pr = _run(res, worktree, mailroom,  # still claims the OLD sha
              {"proofs": [{"id": "remote_agreement"}]})
    assert pr["remote_agreement"].passed is False
    assert "not the claimed" in pr["remote_agreement"].detail


def test_unpushed_branch_refuses(mailroom, worktree):
    res = _true_completion(worktree)
    res["branch"] = "task/TASK-9-never-pushed"
    _git("branch", "-q", "task/TASK-9-never-pushed", cwd=worktree)
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "remote_agreement"}]})
    assert pr["remote_agreement"].passed is False
    assert "does not exist on origin" in pr["remote_agreement"].detail


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
    proofs = [Proof(4, "branch_pattern", None, "pattern unset"),
              Proof(5, "commit_exists", True, "ok")]
    assert refusal(proofs) is None
    assert refusal([Proof(5, "commit_exists", False, "no")]) is not None


# ----------------------------------------------- ratified proofs #6-#15

def test_history_rewrite_fails_ancestry(mailroom, worktree):
    """#6: a claimed commit that does not descend from the recorded base
    (rewrite/orphan) refuses, even though the commit exists and is pushed."""
    res = _true_completion(worktree)
    tip = res["commit_sha"]
    parent = _git("rev-parse", f"{tip}~1", cwd=worktree).strip()
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "descends_from_base"}]}, base_sha=tip)
    # base == tip, claimed == tip: fine
    assert pr["descends_from_base"].passed is True
    res2 = dict(res, commit_sha=parent)  # claims an ancestor of the base
    pr2 = _run(res2, worktree, mailroom,
               {"proofs": [{"id": "descends_from_base"}]}, base_sha=tip)
    assert pr2["descends_from_base"].passed is False


def test_dirty_tree_fails_p7(mailroom, worktree):
    res = _true_completion(worktree)
    (worktree / "residue.txt").write_text("left behind\n")
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "tree_clean_after_sweep"}]})
    assert pr["tree_clean_after_sweep"].passed is False
    assert "residue.txt" in pr["tree_clean_after_sweep"].detail


def test_ac_set_equality_and_evidence(mailroom, worktree):
    """#10: exact id-set — none missing, none invented; all passed with
    evidence. No packet → not evaluable, never inferred."""
    res = _true_completion(worktree)
    packet = {"acceptance_criteria": [{"id": "AC-1", "text": "x"},
                                      {"id": "AC-2", "text": "y"}]}
    res["acceptance_criteria"] = [
        {"id": "AC-1", "status": "passed", "evidence": "t"}]
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "acceptance_criteria"}]}, packet=packet)
    assert pr["acceptance_criteria"].passed is False
    assert "missing ['AC-2']" in pr["acceptance_criteria"].detail
    res["acceptance_criteria"] = [
        {"id": "AC-1", "status": "passed", "evidence": "t"},
        {"id": "AC-2", "status": "passed", "evidence": None}]
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "acceptance_criteria"}]}, packet=packet)
    assert pr["acceptance_criteria"].passed is False  # evidence null
    assert _run(res, worktree, mailroom,
                {"proofs": [{"id": "acceptance_criteria"}]}
                )["acceptance_criteria"].passed is None  # no packet


def test_out_of_scope_path_fails_p11(mailroom, worktree):
    res = _true_completion(worktree)  # touched w.txt
    packet = {"files_in_scope": ["README.md"], "files_out_of_scope": []}
    pr = _run(res, worktree, mailroom, {"proofs": [{"id": "scope"}]},
              packet=packet, base_sha=_git("rev-parse", "origin/main",
                                           cwd=worktree).strip())
    assert pr["scope"].passed is False
    assert "w.txt" in pr["scope"].detail


def test_protected_path_circuit_breaks_end_to_end(mailroom, worktree,
                                                  monkeypatch):
    """#12 e2e: the agent commits a change to a PROTECTED path (agents/*),
    pushes it, and reports completed truthfully — the dispatcher circuit-
    breaks: dead-letter, ack_dead_letter, CIRCUIT_BROKEN, bundle marked."""
    monkeypatch.setenv("TRUTHFUL_TOUCH", "agents/governor/policy.yaml")
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("truthful_agent.py"))

    assert out.decision == "circuit_broken"
    assert out.ack == "ack_dead_letter"
    assert "completion proof circuit break" in out.reason
    assert "#12" in out.reason
    dl = list((mailroom / "dead_letter").glob("*/*.json"))
    assert len(dl) == 1
    assert json.loads(dl[0].read_text())["status"] == "dead_lettered"
    bundles = list((mailroom / "runs").glob("*/completion-proof.json"))
    assert len(bundles) == 1
    assert json.loads(bundles[0].read_text())["circuit_break"] is True


def test_test_weakening_signature_breaks_p13(mailroom, worktree):
    _git("checkout", "-q", "-b", "task/TASK-13", cwd=worktree)
    (worktree / "tests_new.py").write_text(
        "@pytest.mark.skip\ndef test_x():\n    pass\n")
    _git("add", "tests_new.py", cwd=worktree)
    _git("commit", "-q", "-m", "weaken", cwd=worktree)
    sha = _git("rev-parse", "HEAD", cwd=worktree).strip()
    base = _git("rev-parse", "origin/main", cwd=worktree).strip()
    res = {"schema_version": "1.0", "run_id": "run-unit0001",
           "task_id": "TASK-13", "status": "completed", "summary": "w",
           "commit_sha": sha, "pushed": True, "branch": "task/TASK-13",
           "acceptance_criteria": []}
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "banned_patterns"}]}, base_sha=base)
    assert pr["banned_patterns"].passed is False
    assert pr["banned_patterns"].severity == "break"
    assert "TEST_SIG" in pr["banned_patterns"].detail


def test_budgets_p14_lines_ceiling_and_unknown_spend(mailroom, worktree):
    res = _true_completion(worktree)
    base = _git("rev-parse", "origin/main", cwd=worktree).strip()
    packet = {"budgets": {"max_diff_lines": 0}}
    pr = _run(res, worktree, mailroom, {"proofs": [{"id": "budgets"}]},
              packet=packet, base_sha=base)
    assert pr["budgets"].passed is False
    assert pr["budgets"].severity == "fail"
    # known spend over ceiling: circuit break (T-A3)
    packet = {"budgets": {"cost_ceiling_usd": 1.0}}
    pr = _run(res, worktree, mailroom, {"proofs": [{"id": "budgets"}]},
              packet=packet, usage={"cash_usd": 2.5})
    assert pr["budgets"].passed is False
    assert pr["budgets"].severity == "break"
    # unknown spend: ceiling not_evaluable, never blocks (A4)
    pr = _run(res, worktree, mailroom, {"proofs": [{"id": "budgets"}]},
              packet=packet, usage={"cash_usd": None})
    assert pr["budgets"].passed is True
    assert "not_evaluable" in pr["budgets"].detail


def test_spend_write_failure_refuses_ack_p15(mailroom, worktree,
                                             monkeypatch):
    """#15 e2e: all fourteen proofs pass but the spend row cannot be
    written — the ack is REFUSED (retain), never 'acked but unremembered'."""
    from agents.interfaces.budget import BudgetLedgerUnavailable

    def boom(self, **kw):
        raise BudgetLedgerUnavailable("disk full")
    monkeypatch.setattr(dispatch_mod.SqliteBudgetLedger, "record_spend",
                        boom)
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("truthful_agent.py"))

    assert out.ack == RETAIN
    assert "#15 accounting_before_ack" in out.reason
    assert msg["message_id"] not in acked(mailroom, "backend")
    ev = finish_event(mailroom)
    assert proofs_by_id(ev)["accounting_before_ack"]["passed"] is False


# --- L-4: pm may author packets; nothing else moves (2026-08-03) ----------


def _pm_ctx(paths, role):
    """Minimal ctx for p12: a stubbed diff and a role."""
    return {"role": role, "_paths_override": list(paths)}


def test_p12_pm_may_author_packets(monkeypatch):
    """Orchestrator ruling L-4. CC-4 protects tasks/packets/* so a TASK agent
    cannot rewrite the constraints it is judged against — kept. But authoring
    packets IS pm's planning job (SPEC.md: only pm applies `protected-change`),
    and the unqualified break dead-lettered the mission message live."""
    from agents import completion as C

    monkeypatch.setattr(C, "_diff_paths",
                        lambda ctx: ctx.get("_paths_override"))
    ok = C.p12_protected({}, _pm_ctx(["tasks/packets/TASK-999-S2.json"], "pm"))
    assert ok.passed and "role-authorized" in ok.detail


def test_p12_packet_authorship_is_pm_only(monkeypatch):
    """The carve-out is role-scoped: a task agent authoring a packet is the
    exact attack CC-4 exists to stop, and still circuit-breaks."""
    from agents import completion as C

    monkeypatch.setattr(C, "_diff_paths",
                        lambda ctx: ctx.get("_paths_override"))
    for role in ("backend", "frontend", None):
        broke = C.p12_protected(
            {}, _pm_ctx(["tasks/packets/TASK-999-S2.json"], role))
        assert not broke.passed, f"{role} must not author packets"
        assert broke.severity == "break"


def test_p12_pm_carveout_is_packets_only(monkeypatch):
    """Every other protected glob still breaks FOR PM — the carve-out must not
    become a general pm exemption."""
    from agents import completion as C

    monkeypatch.setattr(C, "_diff_paths",
                        lambda ctx: ctx.get("_paths_override"))
    for path in ("agents/dispatch.py", "AGENTS.md", "PRODUCT_DOCTRINE.md",
                 ".github/workflows/ci.yml", "contracts/x.yaml",
                 "scripts/check_invariants.py"):
        broke = C.p12_protected({}, _pm_ctx([path], "pm"))
        assert not broke.passed and broke.severity == "break", path

    # mixed: a packet PLUS a protected file is not laundered by the carve-out
    mixed = C.p12_protected(
        {}, _pm_ctx(["tasks/packets/TASK-1.json", "agents/dispatch.py"], "pm"))
    assert not mixed.passed and mixed.severity == "break"


# --- L-26: review intents are judged on the reviewer's obligations --------
#
# Proofs #10/#11 read the packet named by the message's task_id. For a
# TASK_ASSIGN that is correct. For a REVIEW_REQUEST the reviewer is handed the
# BUILDER's packet — so it is asked for an AC id-set it never agreed to, and
# told its verdict document is out of a scope no build packet will ever list.
# Measured 2026-08-03 across all three roles in one morning (pm TASK-210-S3,
# frontend TASK-210-S3, backend TASK-210-S2): every agent independently named
# review criteria and wrote to docs/agent-org/, and every one was refused.
# Review work was unpassable by construction, so review->merge never closed.


def test_review_intent_does_not_inherit_the_builders_acs(mailroom, worktree):
    """A reviewer cannot emit the builder's AC id-set — there is no id-set
    that satisfies this, which is why no prompt fixed it."""
    res = _true_completion(worktree)
    res["acceptance_criteria"] = [
        {"id": "AC-REVIEW-EXECUTION", "status": "passed", "evidence": "ran"},
    ]
    packet = {"acceptance_criteria": [{"id": "AC-1"}, {"id": "AC-2"}]}
    params = {"proofs": [{"id": "acceptance_criteria"}]}

    # As a build intent this is exactly the observed failure.
    built = _run(res, worktree, mailroom, params, packet=packet,
                 intent="TASK_ASSIGN")
    assert built["acceptance_criteria"].passed is False
    assert "invented" in built["acceptance_criteria"].detail

    # As a review intent it is not evaluable — the same verdict this proof
    # already returns when there is no packet at all.
    for intent in ("REVIEW_REQUEST", "REVIEW_VERDICT",
                   "ARBITRATION_REQUEST", "ARBITRATION_RULING"):
        pr = _run(res, worktree, mailroom, params, packet=packet,
                  intent=intent)
        assert pr["acceptance_criteria"].passed is None, intent
        assert "L-26" in pr["acceptance_criteria"].detail


def test_review_intent_may_write_its_verdict_but_nothing_else(mailroom,
                                                              worktree):
    """#11 admits the review-evidence dir for a review intent — and ONLY it.
    A reviewer that edits product code is still out of scope."""
    _git("checkout", "-q", "-b", "role/review-l26", cwd=worktree)
    verdict = worktree / "docs/agent-org/task-210-s3-review.md"
    verdict.parent.mkdir(parents=True, exist_ok=True)
    verdict.write_text("# verdict\n\nlooks right\n")
    _git("add", "-A", cwd=worktree)
    _git("commit", "-q", "-m", "review verdict", cwd=worktree)
    sha = _git("rev-parse", "HEAD", cwd=worktree).strip()
    base = _git("rev-parse", "origin/main", cwd=worktree).strip()

    res = {"schema_version": "1.0", "run_id": "run-unit0001",
           "task_id": "TASK-210-S3", "status": "completed", "summary": "r",
           "commit_sha": sha, "pushed": True, "checks": [],
           "acceptance_criteria": []}
    packet = {"files_in_scope": ["overlay/**"],
              "files_out_of_scope": ["docs/agent-org/**"]}
    params = {"proofs": [{"id": "scope"}]}

    # The builder's packet denies it; as a build intent that still holds.
    built = _run(res, worktree, mailroom, params, packet=packet,
                 base_sha=base, intent="TASK_ASSIGN")
    assert built["scope"].passed is False

    reviewed = _run(res, worktree, mailroom, params, packet=packet,
                    base_sha=base, intent="REVIEW_REQUEST")
    assert reviewed["scope"].passed is True, reviewed["scope"].detail


def test_review_intent_is_not_a_general_scope_escape(mailroom, worktree):
    """The carve-out is the evidence dir, not a blanket pass: a reviewer that
    touches out-of-scope PRODUCT code is still refused."""
    _git("checkout", "-q", "-b", "role/review-l26-escape", cwd=worktree)
    (worktree / "sneaky.py").write_text("x = 1\n")
    _git("add", "-A", cwd=worktree)
    _git("commit", "-q", "-m", "not a verdict", cwd=worktree)
    sha = _git("rev-parse", "HEAD", cwd=worktree).strip()
    base = _git("rev-parse", "origin/main", cwd=worktree).strip()

    res = {"schema_version": "1.0", "run_id": "run-unit0001",
           "task_id": "TASK-210-S3", "status": "completed", "summary": "r",
           "commit_sha": sha, "pushed": True, "checks": [],
           "acceptance_criteria": []}
    pr = _run(res, worktree, mailroom, {"proofs": [{"id": "scope"}]},
              packet={"files_in_scope": ["overlay/**"],
                      "files_out_of_scope": []},
              base_sha=base, intent="REVIEW_REQUEST")
    assert pr["scope"].passed is False
    assert "sneaky.py" in pr["scope"].detail


def test_protected_paths_still_break_on_a_review_intent(mailroom, worktree):
    """#12 is untouched by L-26: docs/agent-org/* is not protected, and the
    protected floor still circuit-breaks for a reviewer."""
    from agents import completion as C
    from agents.merge_robot.patterns import PROTECTED

    # A reviewer committing to the control plane still circuit-breaks: the
    # L-26 carve-out lives in #11 and #12 never consults it.
    broke = C.p12_protected({}, {"res": {}, "intent": "REVIEW_REQUEST",
                                 "role": "backend", "worktree": worktree,
                                 "diff_paths": ["agents/dispatch.py"],
                                 "packet": None, "base_sha": None})
    assert broke.number == 12
    assert broke.passed is False
    assert broke.severity == "break"
    assert "agents/dispatch.py" in broke.detail

    # And the evidence dir the carve-out admits is not protected in the first
    # place, so admitting it cannot be smuggling a protected path through.
    assert not any(g.startswith("docs/agent-org") for g in PROTECTED)
    for glob in C.REVIEW_EVIDENCE_GLOBS:
        assert not any(fnmatch.fnmatch(glob.replace("*", "x"), g)
                       for g in PROTECTED)


def test_dispatcher_threads_the_message_intent_into_the_proofs():
    """The fix is inert unless dispatch passes the intent through."""
    import inspect

    from agents import dispatch

    src = inspect.getsource(dispatch.dispatch)
    assert 'intent=msg.get("intent")' in src


# --- L-32: coordination intents are not judged as builds -------------------
#
# L-26 fixed reviews and stopped one intent short. Counted from the ledger,
# STATUS is the org's MOST COMMON message (112) against 51 TASK_ASSIGN — so
# the majority of the org's traffic was being judged against a builder's
# packet it never agreed to. Observed on the P0 path: pm triaging backend's
# TASK-212-S1 STATUS was refused for "missing ['AC-1'..'AC-6'], invented
# [...]" while filing the very task that unblocks red main.


def test_only_task_assign_carries_the_packets_acceptance_criteria(mailroom,
                                                                  worktree):
    res = _true_completion(worktree)
    res["acceptance_criteria"] = [
        {"id": "triage-outcome", "status": "passed", "evidence": "filed"},
    ]
    packet = {"acceptance_criteria": [{"id": "AC-1"}, {"id": "AC-2"}]}
    params = {"proofs": [{"id": "acceptance_criteria"}]}

    # The build intent still binds — this is the whole point of the proof.
    built = _run(res, worktree, mailroom, params, packet=packet,
                 intent="TASK_ASSIGN")
    assert built["acceptance_criteria"].passed is False

    # Every coordination intent the ledger actually carries does not.
    for intent in ("STATUS", "SYNC", "ANSWER", "QUESTION", "INTAKE_TICKET",
                   "BOOTSTRAP", "REVIEW_REQUEST", "REVIEW_VERDICT",
                   "ARBITRATION_REQUEST", "ARBITRATION_RULING"):
        pr = _run(res, worktree, mailroom, params, packet=packet,
                  intent=intent)
        assert pr["acceptance_criteria"].passed is None, intent


def test_an_unknown_intent_keeps_todays_behaviour(mailroom, worktree):
    """Enumerated, not inverted (`!= TASK_ASSIGN`), so an intent nobody
    anticipated cannot silently skip a proof."""
    res = _true_completion(worktree)
    res["acceptance_criteria"] = [
        {"id": "invented", "status": "passed", "evidence": "x"}]
    pr = _run(res, worktree, mailroom,
              {"proofs": [{"id": "acceptance_criteria"}]},
              packet={"acceptance_criteria": [{"id": "AC-1"}]},
              intent="SOME_FUTURE_INTENT")
    assert pr["acceptance_criteria"].passed is False


def test_a_triage_may_write_the_backlog_but_not_product_code(mailroom,
                                                             worktree):
    """pm's triage deliverable is a backlog entry; no build packet lists one.
    The carve-out is those paths only — product code stays out of scope."""
    from agents import completion as C
    assert "tasks/BACKLOG.md" in C.REVIEW_EVIDENCE_GLOBS

    _git("checkout", "-q", "-b", "role/triage-l32", cwd=worktree)
    backlog = worktree / "tasks/BACKLOG.md"
    backlog.parent.mkdir(parents=True, exist_ok=True)
    backlog.write_text("# backlog\n\n- filed TASK-213\n")
    _git("add", "-A", cwd=worktree)
    _git("commit", "-q", "-m", "triage", cwd=worktree)
    sha = _git("rev-parse", "HEAD", cwd=worktree).strip()
    base = _git("rev-parse", "origin/main", cwd=worktree).strip()

    res = {"schema_version": "1.0", "run_id": "run-unit0001",
           "task_id": "TASK-212-S1", "status": "completed", "summary": "t",
           "commit_sha": sha, "pushed": True, "checks": [],
           "acceptance_criteria": []}
    packet = {"files_in_scope": ["engine/**"],
              "files_out_of_scope": ["tasks/**"]}
    params = {"proofs": [{"id": "scope"}]}

    assert _run(res, worktree, mailroom, params, packet=packet,
                base_sha=base, intent="TASK_ASSIGN")["scope"].passed is False
    assert _run(res, worktree, mailroom, params, packet=packet,
                base_sha=base, intent="STATUS")["scope"].passed is True


def test_l32_still_breaks_a_coordinator_on_protected_paths(mailroom, worktree):
    """#12 is untouched: neither admitted path is PROTECTED, and a
    coordinator committing to the control plane still circuit-breaks."""
    from agents import completion as C
    from agents.merge_robot.patterns import PROTECTED

    for glob in C.REVIEW_EVIDENCE_GLOBS:
        probe = glob.replace("*", "x")
        assert not any(fnmatch.fnmatch(probe, g) for g in PROTECTED), glob

    broke = C.p12_protected({}, {"res": {}, "intent": "STATUS",
                                 "role": "backend", "worktree": worktree,
                                 "diff_paths": ["agents/dispatch.py"],
                                 "packet": None, "base_sha": None})
    assert broke.passed is False and broke.severity == "break"
