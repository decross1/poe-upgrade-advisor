"""CC-1/A2/A3: command policy, dispatcher-run checks, provisioning.

The policy is token-wise on shlex-parsed argv — the string tricks that
defeat prefix matching (respacing, quoting, lookalike names, shell
composition) are the point of these tests. The dispatch end-to-end half
proves the two load-bearing orderings: a failing REQUIRED check beats a
"completed" self-report, and provisioning sits BELOW the attempt-cap
increment (a provisioning failure is a counted attempt and the model is
never invoked).

Every test runs against a tmp-path mailroom (POB_LEDGER_DIR, autouse).
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import agents.dispatch as dispatch_mod
from agents.checks import (
    CommandPolicyError,
    check_policy,
    checks_ok,
    failed_checks_reason,
    load_command_policy,
    parse_command,
    provisioning_commands,
    run_commands,
    run_provisioning,
)
from agents.dispatch import dispatch
from agents.governor import budget_governor
from tests.test_dispatch import (
    ACK,
    RETAIN,
    acked,
    counter_lines,
    fake,
    make_worktree,
    tele_lines,
    write_message,
)

# ------------------------------------------------------------------ fixtures

@pytest.fixture(autouse=True)
def always_allow_run_budget(monkeypatch: pytest.MonkeyPatch):
    from agents.interfaces.run_budget import AlwaysAllow
    monkeypatch.setenv("RUN_BUDGET", "0")
    monkeypatch.setattr(dispatch_mod, "load_run_budget_port",
                        lambda *a, **k: AlwaysAllow(warn=lambda m: None))


@pytest.fixture(autouse=True)
def completion_proofs_pass(monkeypatch: pytest.MonkeyPatch):
    """This module tests CC-1 checks + provisioning; CC-2 proof coverage is
    tests/test_completion.py."""
    monkeypatch.setattr(dispatch_mod, "verify_completion",
                        lambda res, **kw: [])


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
def worktree(tmp_path: Path) -> Path:
    return make_worktree(tmp_path)


def with_packet(worktree: Path, task_id: str = "TASK-7", **fields) -> dict:
    """Write a minimal schema-valid packet into the worktree."""
    packet = {
        "schema_version": "1.0", "task_id": task_id,
        "owner_role": "backend", "tier": "green",
        "objective": "checks under test",
        "files_in_scope": ["README.md"],
        "files_out_of_scope": [],
        "required_checks": [],
        "acceptance_criteria": [{"id": "AC-1", "text": "checks gate the ack decision"}],
        "budgets": {"max_attempts": 2, "max_files_modified": 2,
                    "max_diff_lines": 100, "max_wall_clock_seconds": 60},
    }
    packet.update(fields)
    d = worktree / "tasks" / "packets"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task_id}.json").write_text(json.dumps(packet))
    return packet


def fake_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
             rc: int = 0) -> Path:
    """A `npm` on PATH that logs its argv and exits `rc`. Creates
    node_modules/ under --prefix on success, like the real `npm ci`."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "npm.log"
    script = bindir / "npm"
    script.write_text(f"""#!/bin/sh
echo "$@" >> {log}
if [ "{rc}" != "0" ]; then exit {rc}; fi
prev=""
for a in "$@"; do
  if [ "$prev" = "--prefix" ]; then mkdir -p "$a/node_modules"; fi
  prev="$a"
done
exit 0
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return log


# ------------------------------------------------------------------ policy

@pytest.mark.parametrize("cmd", [
    "npm install",
    "npm  install",                    # respaced
    "npm 'install'",                   # quoted
    "npm ci --prefix web",
    "git push origin main",
    "git push --force",
    "gh pr merge 95",
    "gh api repos/x/y",
])
def test_contract_bans_are_token_wise(cmd):
    with pytest.raises(CommandPolicyError):
        check_policy(parse_command(cmd))


@pytest.mark.parametrize("cmd", [
    "npm-install-helper --version",    # lookalike name: NOT npm install
    "npminstall",                      # NOT the banned pair
    "ghq get repo",                    # token boundary: NOT the gh ban
    "git status",
    "git log --oneline",
    "python3 -m pytest tests -q",
    "npm --prefix web run test",       # npm RUN is not npm install/ci
])
def test_non_banned_commands_pass_bans_only_policy(cmd):
    assert check_policy(parse_command(cmd)) == "bans_only"


@pytest.mark.parametrize("cmd", [
    "true && git push origin main",
    "npm test || true",
    "echo hi; gh pr merge",
    "python3 -m pytest | tee out.txt",
    "echo x > /tmp/x",
    "cat < /etc/passwd",
    "echo `whoami`",
    "echo $(rm -rf .)",
])
def test_shell_composition_is_rejected_not_prefix_matched(cmd):
    with pytest.raises(CommandPolicyError):
        parse_command(cmd)


def test_ratified_allowlist_mechanism_rejects_unlisted():
    pol = {"banned": [["git", "push"]],
           "allowlist": [["python3"], ["npm", "--prefix"]]}
    assert check_policy(parse_command("python3 -m pytest"), pol) == "allowlist"
    assert check_policy(parse_command("npm --prefix web run t"), pol) == "allowlist"
    with pytest.raises(CommandPolicyError):
        check_policy(parse_command("ruff check ."), pol)
    with pytest.raises(CommandPolicyError):  # bans beat the allowlist
        check_policy(parse_command("git push"), {
            "banned": [["git", "push"]], "allowlist": [["git"]]})


def test_committed_policy_file_is_bans_only_pending_answer():
    pol = load_command_policy()
    assert pol["allowlist"] is None
    assert [b for b in pol["banned"]] == [
        ["npm", "install"], ["npm", "ci"], ["git", "push"], ["gh"]]


# ------------------------------------------------------------------ runner

def test_runner_branches_on_rc_and_runs_every_check(tmp_path):
    results = run_commands(["true", "false", "true"], tmp_path)
    assert [r.rc for r in results] == [0, 1, 0]
    assert [r.ok for r in results] == [True, False, True]
    assert checks_ok(results) is False
    assert "rc=1" in failed_checks_reason(results)
    assert all(r.duration_seconds >= 0 for r in results)


def test_runner_records_policy_rejection_as_failure(tmp_path):
    results = run_commands(["git push origin x"], tmp_path)
    assert results[0].rc is None
    assert results[0].ok is False
    assert results[0].policy.startswith("rejected:")
    assert "required check failed" in failed_checks_reason(results)


def test_runner_timeout_is_a_failure(tmp_path):
    results = run_commands(["sleep 5"], tmp_path, timeout=1)
    assert results[0].timed_out is True
    assert results[0].ok is False


# ------------------------------------------------------------- provisioning

def test_provisioning_derived_from_npm_prefix_commands():
    packet = {"required_checks": ["npm --prefix web run test",
                                  "python3 -m pytest -q"],
              "deterministic_prepass": ["npm --prefix overlay run lint"]}
    cmds = provisioning_commands(packet)
    assert cmds == [
        ["npm", "ci", "--prefix", "web", "--prefer-offline"],
        ["npm", "ci", "--prefix", "overlay", "--prefer-offline"]]
    assert provisioning_commands({"required_checks": ["python3 -V"]}) == []
    assert provisioning_commands(None) == []


def test_provisioning_runs_with_shared_cache(tmp_path, monkeypatch):
    log = fake_npm(tmp_path, monkeypatch)
    monkeypatch.setenv("NPM_CACHE_DIR", str(tmp_path / "cache"))
    packet = {"required_checks": ["npm --prefix web run test"]}
    recs = run_provisioning(packet, tmp_path, tmp_path / "mailroom")
    assert len(recs) == 1
    assert recs[0]["rc"] == 0
    assert recs[0]["duration_seconds"] >= 0
    assert "ci --prefix web --prefer-offline" in log.read_text()
    assert (tmp_path / "web" / "node_modules").is_dir()


# ------------------------------------------------------------------ e2e

def test_failing_required_check_beats_completed_self_report(
        mailroom, worktree, counter):
    """CC-1's authority inversion, end to end: the agent reports completed
    (and the proofs are pinned green); the dispatcher's own check run says
    otherwise; the message is retained and per-check rc is in telemetry."""
    with_packet(worktree, required_checks=["true", "false"])
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.invoked is True
    assert out.result_status == "completed"
    assert out.ack == RETAIN
    assert msg["message_id"] not in acked(mailroom, "backend")
    fin = [ln for ln in tele_lines(mailroom) if ln.get("event") == "finish"][0]
    assert fin["result_error"].startswith("required check failed")
    rcs = {c["cmd"]: c["rc"] for c in fin["required_checks"]}
    assert rcs == {"true": 0, "false": 1}


def test_passing_checks_ack_with_per_check_telemetry(
        mailroom, worktree, counter):
    with_packet(worktree, required_checks=["true", "python3 -c 0"])
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))
    assert out.ack == ACK
    fin = [ln for ln in tele_lines(mailroom) if ln.get("event") == "finish"][0]
    assert all(c["rc"] == 0 for c in fin["required_checks"])
    assert all(c["policy"] == "bans_only" for c in fin["required_checks"])


def test_provisioning_failure_is_metered_and_never_invokes_model(
        mailroom, worktree, counter, tmp_path, monkeypatch):
    """A2 ordering, the probe target: provisioning sits BELOW the
    attempt-cap increment. rc!=0 → the attempt is COUNTED, the model is
    NEVER invoked, the message is retained with the failure telemetered —
    not an un-metered doom loop."""
    fake_npm(tmp_path, monkeypatch, rc=1)
    with_packet(worktree, required_checks=["npm --prefix web run test"])
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.invoked is False
    assert out.ack == RETAIN
    assert out.attempts == 1          # counted: below the increment
    assert counter_lines(counter) == []   # model never ran
    fin = [ln for ln in tele_lines(mailroom) if ln.get("event") == "finish"][0]
    assert fin["result_error"].startswith("dependency provisioning failed")
    assert fin["provisioning"][0]["rc"] == 1


def test_provisioned_fresh_worktree_runs_npm_checks(
        mailroom, worktree, counter, tmp_path, monkeypatch):
    """T-A1: an npm required check executes in a fresh worktree with NO
    pre-existing node_modules, because the dispatcher provisioned it first.
    The check itself proves node_modules existed when it ran."""
    fake_npm(tmp_path, monkeypatch)   # `npm ci` creates node_modules; `npm run` exits 0
    assert not (worktree / "web" / "node_modules").exists()
    with_packet(worktree, required_checks=[
        "npm --prefix web run test",
        "test -d web/node_modules",   # the proof, as a check
    ])
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.invoked is True
    assert out.ack == ACK
    fin = [ln for ln in tele_lines(mailroom) if ln.get("event") == "finish"][0]
    assert fin["provisioning"][0]["rc"] == 0
    assert all(c["rc"] == 0 for c in fin["required_checks"])


def test_no_packet_means_no_checks_no_provisioning(
        mailroom, worktree, counter):
    """Most ledger messages have no packet: dispatch semantics unchanged."""
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))
    assert out.ack == ACK
    fin = [ln for ln in tele_lines(mailroom) if ln.get("event") == "finish"][0]
    assert fin.get("required_checks") is None
    assert fin.get("provisioning") is None
