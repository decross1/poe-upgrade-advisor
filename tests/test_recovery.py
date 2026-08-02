"""Tests for agents/recovery.py and dispatch's supervised invocation (W1-4).

Why this module exists, measured: one ~45-minute invocation on 2026-07-26
lost everything it had done to a timeout kill — unpushed work in a throwaway
worktree, deleted with it. And 14 dirty `.fan` worktrees sit on disk today
holding uncommitted work nobody bundled; frontend-c4c78ba2 alone holds 21
files including STAGED DELETIONS, which is why `git diff` alone cannot be
the bundle (a staged deletion never appears in plain `git diff`, and
untracked files appear in neither patch).

Every test runs against a tmp-path mailroom (POB_LEDGER_DIR, autouse) and
REAL git repositories built entirely under tmp_path: an `origin` repo plus
`git clone`s of it, so `origin/main` resolves exactly as it does in a fan
worktree. Nothing here ever touches the real mailroom or the real
worktrees/.fan specimens. Preflight is disabled (its suite stubs `gh`; ours
must never reach it) and budget_governor's subprocess is a recorder.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import agents.dispatch as dispatch_mod
import agents.recovery as recovery_mod
from agents.dispatch import dispatch
from agents.governor import budget_governor
from agents.recovery import (
    bundle_dir,
    cmd_apply,
    inspect_worktree,
    is_dirty,
    unpushed_commits,
    verify_bundle,
    write_bundle,
    write_checkpoint,
)
from tests.test_dispatch import INVOKE, RETAIN, acked, fake, tele_lines, write_message

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCH_PY = REPO_ROOT / "agents" / "dispatch.py"
RECOVERY_PY = REPO_ROOT / "agents" / "recovery.py"

#: Same policy make_worktree (tests/test_dispatch.py) writes, but committed
#: into the tmp ORIGIN repo so every clone carries it as a TRACKED file — an
#: untracked policy.yaml would make a "clean clone" impossible to build.
POLICY = {
    "per_task_max_invocations": 12,
    "per_day_max": {"pm": 100, "backend": 100, "frontend": 100},
    "backoff": {"base_minutes": 0, "max_minutes": 0},
    "circuit_breaker_consecutive_failures": 3,
    "daily_reset_hour_utc": 4,
    "execution_classes": {
        "green": {"max_attempts": 2, "max_wall_clock_seconds": 60},
        "org": {"max_attempts": 2, "max_wall_clock_seconds": 60},
    },
}

GHP_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
SK_KEY = "sk-" + "abcdefghijklmnop12345678"


# ------------------------------------------------------------------ fixtures
@pytest.fixture(autouse=True)
def mailroom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp mailroom via POB_LEDGER_DIR, set BEFORE any dispatch/recovery call.

    Autouse: no test in this module can ever touch the real mailroom — and
    because subprocess tests inherit os.environ, their children cannot
    either.
    """
    root = tmp_path / "mailroom"
    monkeypatch.setenv("POB_LEDGER_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def counter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Counter file the fake agents append to; one line per invocation."""
    fp = tmp_path / "invocations.count"
    monkeypatch.setenv("COUNTER_FILE", str(fp))
    return fp


@pytest.fixture(autouse=True)
def no_preflight(monkeypatch: pytest.MonkeyPatch):
    """These tests target recovery, not preflight — and preflight would hit
    the real `gh` CLI. PREFLIGHT=0 is the W1-3 rollback flag."""
    monkeypatch.setenv("PREFLIGHT", "0")


@pytest.fixture(autouse=True)
def no_gh(monkeypatch: pytest.MonkeyPatch):
    """Replace budget_governor's subprocess so _dead_letter never runs gh."""
    class _FakeSubprocess:
        def __init__(self) -> None:
            self.calls: list[tuple[list[str], dict]] = []

        def run(self, argv, **kwargs):
            self.calls.append((list(argv), dict(kwargs)))
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    rec = _FakeSubprocess()
    monkeypatch.setattr(budget_governor, "subprocess", rec)
    return rec


# ------------------------------------------------------------------ helpers
def _git(*args: str, cwd: Path) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, f"git {' '.join(args)} failed:\n{p.stderr}"
    return p.stdout


def make_origin(base: Path) -> Path:
    """A real 'origin' repo in tmp: main branch, a few tracked files, and
    the governor policy committed (see POLICY note above)."""
    origin = base / "origin"
    origin.mkdir()
    _git("init", "-q", "-b", "main", cwd=origin)
    _git("config", "user.email", "recovery-test@example.com", cwd=origin)
    _git("config", "user.name", "Recovery Test", cwd=origin)
    (origin / "tracked.txt").write_text("line one\n")
    (origin / "keep.txt").write_text("keep: original\n")
    (origin / "doomed.txt").write_text("delete me\n")
    gov = origin / "agents" / "governor"
    gov.mkdir(parents=True)
    (gov / "policy.yaml").write_text(yaml.safe_dump(POLICY))
    _git("add", "-A", cwd=origin)
    _git("commit", "-q", "-m", "init", cwd=origin)
    return origin


def clone_worktree(origin: Path, dest: Path) -> Path:
    """`git clone` of the tmp origin, so origin/main resolves in the clone."""
    _git("clone", "-q", str(origin), str(dest), cwd=origin.parent)
    _git("config", "user.email", "recovery-test@example.com", cwd=dest)
    _git("config", "user.name", "Recovery Test", cwd=dest)
    return dest


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    return make_origin(tmp_path)


@pytest.fixture
def worktree(origin: Path, tmp_path: Path) -> Path:
    return clone_worktree(origin, tmp_path / "wt")


def cap_budgets(monkeypatch: pytest.MonkeyPatch, wall_seconds: int) -> None:
    """Wall cap comes from execution_classes.max_wall_clock_seconds; shrink
    it without also shrinking the policy the governor reads."""
    monkeypatch.setattr(
        dispatch_mod, "resolve_budgets",
        lambda policy, packet, tier: {"max_attempts": 2,
                                      "max_wall_clock_seconds": wall_seconds})


def single_bundle(mailroom: Path, task_id: str) -> Path:
    runs = sorted((mailroom / "recovery" / task_id).iterdir())
    assert len(runs) == 1, f"expected exactly one bundle run, got {runs}"
    return runs[0]


def meta_of(run_dir: Path) -> dict:
    return json.loads((run_dir / "metadata.json").read_text())


def spawn_dispatch(worktree: Path, message_id: str,
                   fake_name: str) -> subprocess.Popen:
    """Run dispatch as a REAL child process (signal tests need a real pid).

    Inherits os.environ, which the autouse fixtures already point at the
    tmp mailroom (POB_LEDGER_DIR) with PREFLIGHT=0.
    """
    return subprocess.Popen(
        [sys.executable, str(DISPATCH_PY), "--role", "backend",
         "--message-id", message_id, "--worktree", str(worktree),
         "--fake-agent", fake(fake_name)],
        cwd=REPO_ROOT, env=os.environ.copy(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_for(predicate, timeout: float = 15.0, interval: float = 0.05) -> bool:
    """Bounded sub-second polling — the only waiting these tests do."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _reap(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)


# ------------------------------------------------------------------ test 6 *
def test_forced_timeout_preserves_bundle_and_dirty_worktree(
        mailroom, worktree, counter, monkeypatch):
    """Test 6 * (W1-4) — a forced timeout preserves a recoverable patch and
    the dirty worktree is NOT deleted.

    The starred test because it is the incident: one ~45-minute invocation
    on 2026-07-26 lost everything it had done to a timeout kill. And the
    disk today shows the scale of what an unbundled kill leaves behind — 14
    dirty .fan worktrees, frontend-c4c78ba2 alone holding 21 files
    including STAGED DELETIONS (which is exactly why 'git diff' alone
    cannot be the bundle: staged deletions live only in `diff --cached`,
    untracked files in neither patch).
    """
    cap_budgets(monkeypatch, 1)
    msg = write_message(mailroom)
    mid = msg["message_id"]

    out = dispatch("backend", mid, worktree,
                   fake_agent=fake("dirty_sleeper_agent.py"))

    # Outcome: the timed-out path — killed (no rc), retained, never acked.
    assert out.decision == INVOKE
    assert out.invoked is True
    assert out.exit_code == -1
    assert out.ack == RETAIN
    assert "timeout" in out.reason
    assert mid not in acked(mailroom, "backend")
    assert counter.read_text().splitlines() == ["invoked"]

    # The bundle: written before the child was terminated, verified.
    run = single_bundle(mailroom, "TASK-7")
    starts = [r for r in tele_lines(mailroom) if r["event"] == "start"]
    assert len(starts) == 1 and run.name == starts[0]["run_id"]
    assert verify_bundle(run) is True
    meta = meta_of(run)
    # Fixed in the W1-4 close commit: step 12 keeps an existing abnormal-
    # stop bundle intact, so the kill provenance survives on disk.
    assert meta["trigger"] == "timeout"
    assert meta["dirty"] is True
    assert meta["untracked_count"] >= 1
    assert "agent edit: unsaved work" in (run / "working.patch").read_text()

    # The dirty worktree is NOT deleted, and is still recoverably dirty.
    assert worktree.is_dir()
    assert is_dirty(worktree) is True

    finishes = [r for r in tele_lines(mailroom) if r["event"] == "finish"]
    assert len(finishes) == 1
    assert finishes[0]["timed_out"] is True
    assert finishes[0]["exit_code"] is None


# ------------------------------------------------------------------ SIGTERM
def test_sigterm_preserves_bundle_and_retains_message(mailroom, worktree):
    """SIGTERM (the supervisor's `timeout` sends one) bundles before dying.

    Runs dispatch as a real child process, waits for the fake agent's
    dirty-marker (tree already dirtied by then), then delivers SIGTERM.
    """
    msg = write_message(mailroom)
    mid = msg["message_id"]

    proc = spawn_dispatch(worktree, mid, "dirty_sleeper_agent.py")
    try:
        assert wait_for(lambda: (worktree / ".dirty-marker").exists()), \
            "fake agent never dirtied the tree"
        os.kill(proc.pid, signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=15)
    finally:
        _reap(proc)

    assert proc.returncode == 0, stderr  # structured Outcome, not a crash

    run = single_bundle(mailroom, "TASK-7")
    assert verify_bundle(run) is True
    meta = meta_of(run)
    # Fixed in the W1-4 close commit: provenance survives step 12.
    assert meta["trigger"] == "sigterm"
    assert meta["dirty"] is True
    assert "agent edit: unsaved work" in (run / "working.patch").read_text()
    assert mid not in acked(mailroom, "backend")  # retained
    assert is_dirty(worktree) is True

    finishes = [r for r in tele_lines(mailroom) if r["event"] == "finish"]
    assert len(finishes) == 1
    assert finishes[0]["exit_code"] is None


# -------------------------------------------------------------------- apply
def test_bundle_applies_cleanly_to_fresh_checkout(mailroom, origin, tmp_path):
    """`apply` against a fresh clean clone is the only version of
    "recoverable" that means anything (W1-4 spec).

    The dirty tree carries all four shapes of unsaved work at once —
    unstaged edit, staged edit, STAGED DELETION (the frontend-c4c78ba2
    specimen shape that plain `git diff` cannot see), and an untracked
    file — and every one must survive the round trip.
    """
    wt = clone_worktree(origin, tmp_path / "dirty-wt")
    (wt / "tracked.txt").write_text("line one\nunstaged edit\n")     # (a)
    (wt / "keep.txt").write_text("keep: staged edit\n")              # (b)
    _git("add", "keep.txt", cwd=wt)
    _git("rm", "-q", "doomed.txt", cwd=wt)                           # (c)
    payload = "untracked payload éÿ — no secrets\n".encode()
    (wt / "notes").mkdir()                                           # (d)
    (wt / "notes" / "scratch.txt").write_bytes(payload)

    d = write_bundle(wt, mailroom, task_id="TASK-77", run_id="run-apply",
                     role="backend", trigger="manual")
    assert d is not None
    assert verify_bundle(d) is True

    fresh = clone_worktree(origin, tmp_path / "fresh-wt")
    cmd_apply(mailroom, "TASK-77", "run-apply", fresh)

    assert (fresh / "tracked.txt").read_text() == "line one\nunstaged edit\n"
    assert (fresh / "keep.txt").read_text() == "keep: staged edit\n"
    assert not (fresh / "doomed.txt").exists()
    status = _git("status", "--porcelain", cwd=fresh)
    assert "D  doomed.txt" in status          # deletion applied AND staged
    cached = _git("diff", "--cached", "--name-only", cwd=fresh)
    assert "keep.txt" in cached and "doomed.txt" in cached
    # untracked content restored byte-identical
    assert (fresh / "notes" / "scratch.txt").read_bytes() == payload


# ------------------------------------------------------------- clean tree
def test_clean_pushed_worktree_yields_no_bundle_and_loop_guard_holds(
        mailroom, worktree):
    """A clean clone at origin/main has nothing to lose: no bundle. And the
    supervisor may remove a worktree only under the clean-AND-no-unpushed
    guard — asserted statically against scripts/agent_loop.sh, because
    `worktree remove` succeeds on a clean tree with local commits, silently
    orphaning them in the shared object store."""
    assert is_dirty(worktree) is False
    assert unpushed_commits(worktree) == ""
    d = inspect_worktree(worktree, mailroom, task_id="TASK-7",
                         run_id="run-clean", role="backend")
    assert d is None
    assert not (mailroom / "recovery").exists()

    loop = (REPO_ROOT / "scripts" / "agent_loop.sh").read_text()
    guard = re.search(
        r'if \[ -z "\$\(git -C "\$wt" status --porcelain[^\n]*\] && \\\n'
        r'\s*\[ -z "\$\(git -C "\$wt" log --oneline origin/main\.\.HEAD'
        r'[^\n]*\]; then\n'
        r'\s*git -C "\$DIR" worktree remove "\$wt"',
        loop)
    assert guard, ("fan_worker removal guard must require BOTH a clean tree "
                   "AND no unpushed commits immediately before remove")
    # The remove INVOCATION appears exactly once — only inside that guard
    # (comments may mention "worktree remove"; the command form may not).
    assert loop.count('git -C "$DIR" worktree remove') == 1
    assert "RECOVERY_REQUIRED" in loop
    assert "INVOKE_TIMEOUT=${INVOKE_TIMEOUT:-900}" in loop


# ------------------------------------------------------------------ secrets
def test_secrets_are_scrubbed_from_every_text_artifact(mailroom, worktree):
    """password=..., ghp_ and sk- literals must never reach a bundle: the
    mailroom outlives the worktree and is exactly the kind of place a leaked
    credential would sit unnoticed. Binary untracked content is kept intact
    (un-scrubbed) — corrupting it would defeat recovery."""
    (worktree / "tracked.txt").write_text(
        f"line one\npassword=hunter2secret\ntoken={GHP_TOKEN}\n")
    (worktree / "secret-note.txt").write_text(
        f"api_key: {SK_KEY}\nplain scratch line\n")
    binary = bytes(range(256)) * 4  # not valid UTF-8: takes the binary path
    (worktree / "blob.bin").write_bytes(binary)

    d = write_bundle(
        worktree, mailroom, task_id="TASK-88", run_id="run-scrub",
        role="backend", trigger="manual",
        stderr_tail=f"auth failed for {SK_KEY}\npassword=hunter2secret\n")
    assert d is not None

    working = (d / "working.patch").read_text()
    stderr = (d / "stderr-tail.txt").read_text()
    with tarfile.open(d / "untracked.tar") as tar:
        note = tar.extractfile("secret-note.txt").read().decode()
        blob = tar.extractfile("blob.bin").read()

    assert "[REDACTED]" in working
    assert "[REDACTED]" in stderr
    assert "[REDACTED]" in note
    assert blob == binary  # binary survives un-scrubbed but intact

    text_artifacts = {p.name: p.read_text() for p in d.iterdir()
                      if p.name != "untracked.tar"}
    text_artifacts["untracked.tar:secret-note.txt"] = note
    for name, text in text_artifacts.items():
        for secret in ("hunter2secret", GHP_TOKEN, SK_KEY):
            assert secret not in text, f"secret literal leaked into {name}"


# --------------------------------------------------------------------- HALT
def test_halt_mid_invocation_stops_worker_at_next_tick(mailroom, worktree):
    """The operator's kill switch stops in-flight work at the next 0.1 s
    poll tick — not after INVOKE_TIMEOUT more seconds. HALT must NOT exist
    at dispatch start (step 1 would suppress the run before invoking)."""
    msg = write_message(mailroom)
    mid = msg["message_id"]
    assert not (mailroom / "HALT").exists()

    started = time.monotonic()
    proc = spawn_dispatch(worktree, mid, "dirty_sleeper_agent.py")
    try:
        assert wait_for(lambda: (worktree / ".dirty-marker").exists()), \
            "fake agent never dirtied the tree"
        (mailroom / "HALT").touch()
        stdout, stderr = proc.communicate(timeout=15)
    finally:
        _reap(proc)
    elapsed = time.monotonic() - started

    assert proc.returncode == 0, stderr
    # Well before the 60 s wall cap and the agent's 30 s sleep.
    assert elapsed < 10

    run = single_bundle(mailroom, "TASK-7")
    assert verify_bundle(run) is True
    meta = meta_of(run)
    # Fixed in the W1-4 close commit: provenance survives step 12.
    assert meta["trigger"] == "halt"
    assert meta["dirty"] is True
    assert mid not in acked(mailroom, "backend")  # retained

    finishes = [r for r in tele_lines(mailroom) if r["event"] == "finish"]
    assert len(finishes) == 1
    assert finishes[0]["halted"] is True
    assert finishes[0]["exit_code"] is None


# -------------------------------------------------------------- checkpoints
def test_checkpoints_written_during_long_invocation(mailroom, worktree,
                                                    monkeypatch, tmp_path):
    """The 300 s heartbeat, shrunk to 0.3 s: patches must be rewritten
    DURING the run, so a hard kill (SIGKILL — no handler ever runs) loses
    at most one interval. Exercised via _run_capped directly, which also
    proves the un-clobbered trigger="timeout" bundle write."""
    assert recovery_mod.CHECKPOINT_INTERVAL == 300  # the production default
    monkeypatch.setattr(recovery_mod, "CHECKPOINT_INTERVAL", 0.3)

    ctx = tmp_path / "ctx.json"
    ctx.write_text("{}")
    t0 = time.time()
    rc, stdout_tail, stderr_tail, stop_reason = dispatch_mod._run_capped(
        [fake("dirty_sleeper_agent.py"), str(ctx)], worktree, mailroom,
        wall_cap=2, task_id="TASK-9", run_id="run-ckpt", role="backend")

    assert rc is None
    assert stop_reason == "timeout"

    d = bundle_dir(mailroom, "TASK-9", "run-ckpt")
    # checkpoint.at is written ONLY by write_checkpoint: proof the mid-run
    # heartbeat ran, not just the final stop bundle.
    assert (d / "checkpoint.at").exists()
    at = float((d / "checkpoint.at").read_text())
    assert t0 < at < t0 + 2.5
    assert "agent edit: unsaved work" in (d / "working.patch").read_text()
    # The timeout stop then wrote the FULL bundle — and with no dispatch
    # step 12 on this direct path, the true trigger survives on disk.
    assert verify_bundle(d) is True
    assert meta_of(d)["trigger"] == "timeout"


def test_write_checkpoint_direct_and_non_git_trees(mailroom, worktree,
                                                   tmp_path):
    """write_checkpoint on a real tree writes patches + checkpoint.at; on a
    non-git path both checkpoint and bundle refuse with None (nothing
    recoverable) instead of raising."""
    (worktree / "tracked.txt").write_text("line one\ncheckpointed edit\n")
    d = write_checkpoint(worktree, mailroom, task_id="TASK-3", run_id="r1")
    assert d == bundle_dir(mailroom, "TASK-3", "r1")
    assert "checkpointed edit" in (d / "working.patch").read_text()
    assert (d / "staged.patch").exists()
    assert (d / "checkpoint.at").exists()

    not_git = tmp_path / "not-a-repo"
    not_git.mkdir()
    assert write_checkpoint(not_git, mailroom, task_id="T", run_id="r") is None
    assert write_bundle(not_git, mailroom, task_id="T", run_id="r") is None


# --------------------------------------------------------- unpushed commits
def test_unpushed_commit_with_clean_tree_still_bundles(mailroom, worktree):
    """A clean tree with a local commit is still unsaved work — `worktree
    remove` would orphan the commit in the shared object store. Step 12
    must bundle on unpushed commits, not only on dirtiness."""
    (worktree / "tracked.txt").write_text("line one\ncommitted line\n")
    _git("commit", "-q", "-am", "TASK-7: local commit never pushed",
         cwd=worktree)
    assert is_dirty(worktree) is False
    assert unpushed_commits(worktree) != ""

    d = inspect_worktree(worktree, mailroom, task_id="TASK-7",
                         run_id="run-unpushed", role="backend")
    assert d is not None
    assert verify_bundle(d) is True
    assert "local commit never pushed" in (d / "commits.txt").read_text()
    meta = meta_of(d)
    assert meta["unpushed_commit_count"] >= 1
    assert meta["dirty"] is False
    assert meta["trigger"] == "post-invocation"
    assert meta["head_sha"] != meta["origin_main_sha"]


# ------------------------------------------------------------ verify_bundle
def test_verify_bundle_complete_true_missing_artifact_false(mailroom,
                                                            worktree):
    """verify_bundle gates the never-delete-dirty invariant: complete =>
    True; any required artifact missing or metadata unparseable => False."""
    (worktree / "tracked.txt").write_text("line one\nverify edit\n")
    d = write_bundle(worktree, mailroom, task_id="TASK-5", run_id="r1")
    assert verify_bundle(d) is True

    (d / "commits.txt").unlink()
    assert verify_bundle(d) is False

    d2 = write_bundle(worktree, mailroom, task_id="TASK-5", run_id="r2")
    assert verify_bundle(d2) is True
    (d2 / "metadata.json").write_text("{ not json")
    assert verify_bundle(d2) is False
    # NOTE (reported as an observation, not asserted): verify_bundle does
    # not require untracked.tar, although untracked content is exactly what
    # patches cannot restore.


# --------------------------------------------------- step 12 on normal exit
def test_normal_exit_dirty_tree_bundles_post_invocation(mailroom, worktree):
    """rc=0 with no result and a dirty tree is the dangerous-normal case:
    the work exists only in the throwaway worktree. Step 12 must bundle it
    with trigger=post-invocation before any supervisor considers removal."""
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("dirty_completing_agent.py"))

    assert out.invoked is True
    assert out.exit_code == 0
    assert out.ack == RETAIN  # rc==0 carries zero bits; no result, no ack

    run = single_bundle(mailroom, "TASK-7")
    assert verify_bundle(run) is True
    meta = meta_of(run)
    assert meta["trigger"] == "post-invocation"
    assert meta["dirty"] is True
    assert meta["exit_code"] == 0
    assert "quick dirty edit" in (run / "working.patch").read_text()
    untracked = (run / "untracked-files.txt").read_text().splitlines()
    assert "untracked-note.txt" in untracked


# ---------------------------------------------------------------------- CLI
def test_cli_list_and_show_smoke(mailroom, worktree):
    """list/show over a tmp mailroom with one bundle, via the real CLI in a
    subprocess (POB_LEDGER_DIR inherited from the autouse fixture)."""
    (worktree / "tracked.txt").write_text("line one\ncli edit\n")
    d = write_bundle(worktree, mailroom, task_id="TASK-42", run_id="run-cli",
                     role="backend", trigger="manual")
    assert d is not None

    p = subprocess.run(
        [sys.executable, str(RECOVERY_PY), "list"],
        cwd=REPO_ROOT, env=os.environ.copy(),
        capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    assert "TASK-42" in p.stdout
    assert "run-cli" in p.stdout
    assert "verified" in p.stdout

    p = subprocess.run(
        [sys.executable, str(RECOVERY_PY), "show", "TASK-42"],
        cwd=REPO_ROOT, env=os.environ.copy(),
        capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    shown = json.loads(p.stdout)
    assert shown["run_id"] == "run-cli"
    assert shown["task_id"] == "TASK-42"
    assert shown["schema_version"] == "1.0"
    assert shown["trigger"] == "manual"


# ------------------------------------------- W1-4 close-commit regressions
def test_list_cli_skips_stray_files(tmp_path, monkeypatch):
    """A stray file under recovery/ must not crash the list CLI."""
    mailroom = tmp_path / "mailroom"
    monkeypatch.setenv("POB_LEDGER_DIR", str(mailroom))
    (mailroom / "recovery" / "TASK-1" / "run-1").mkdir(parents=True)
    (mailroom / "recovery" / "STRAY.txt").write_text("not a task dir")
    (mailroom / "recovery" / "TASK-1" / "also-stray.log").write_text("x")
    import agents.recovery as recovery_mod
    recovery_mod.cmd_list(mailroom)  # must not raise


def test_verify_bundle_requires_untracked_tar(tmp_path):
    """A bundle missing the only copy of untracked content must not verify."""
    import agents.recovery as recovery_mod
    clone = clone_worktree(make_origin(tmp_path), tmp_path / "clone-x")
    (clone / "new-untracked.txt").write_text("only copy lives here")
    mailroom = tmp_path / "mailroom"
    d = recovery_mod.write_bundle(clone, mailroom, task_id="TASK-2",
                                  run_id="r1", role="backend",
                                  trigger="manual")
    assert recovery_mod.verify_bundle(d) is True
    (d / "untracked.tar").unlink()
    assert recovery_mod.verify_bundle(d) is False


def test_metadata_records_worktree_path(tmp_path):
    """Readiness (Lane B W1-6) correlates bundle -> left-in-place tree."""
    import agents.recovery as recovery_mod
    clone = clone_worktree(make_origin(tmp_path), tmp_path / "clone-x")
    (clone / "dirty.txt").write_text("x")
    d = recovery_mod.write_bundle(clone, tmp_path / "mailroom",
                                  task_id="TASK-3", run_id="r1",
                                  role="backend", trigger="manual")
    assert meta_of(d)["worktree"] == str(clone)


def test_inspect_worktree_preserves_existing_abnormal_bundle(tmp_path):
    """The no-reclobber rule directly: an existing bundle for the run keeps
    its trigger; inspect_worktree returns it untouched."""
    import agents.recovery as recovery_mod
    clone = clone_worktree(make_origin(tmp_path), tmp_path / "clone-x")
    (clone / "dirty.txt").write_text("x")
    mailroom = tmp_path / "mailroom"
    d1 = recovery_mod.write_bundle(clone, mailroom, task_id="TASK-4",
                                   run_id="r1", role="backend",
                                   trigger="sigterm")
    d2 = recovery_mod.inspect_worktree(clone, mailroom, task_id="TASK-4",
                                       run_id="r1", role="backend")
    assert d1 == d2
    assert meta_of(d1)["trigger"] == "sigterm"
