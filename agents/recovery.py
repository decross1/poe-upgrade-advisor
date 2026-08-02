#!/usr/bin/env python3
"""Recovery v1 — worktree checkpoints and loss-proof bundles (W1-4).

Why: one ~45-minute invocation on 2026-07-26 lost everything it had done to a
timeout kill — unpushed work in a throwaway worktree, deleted with it. And 14
dirty `.fan` worktrees are sitting on disk right now holding uncommitted work
nobody bundled (frontend-c4c78ba2 alone: 21 files, staged deletions included).

Invariant: **a dirty worktree is never deleted without a verified bundle.**

Bundle layout, under `<mailroom>/recovery/<task-id>/<run-id>/`:
    metadata.json          task, run, role, trigger, timestamps, exit code,
                           base SHA + origin/main SHA (what `apply` targets)
    working.patch          git diff
    staged.patch           git diff --cached
    untracked-files.txt    git ls-files --others --exclude-standard
    untracked.tar          content of those files (names alone cannot be
                           restored; the staged-deletion specimen proves
                           patches alone are not enough either)
    branch.txt             current branch / detached HEAD sha
    commits.txt            git log origin/main..HEAD --oneline
    result.json            the result file if one exists, even if invalid
    stderr-tail.txt        last 200 lines, secret-scrubbed

Checkpointing: `working.patch`/`staged.patch` are rewritten in place every
300 s during a long invocation, so a hard kill loses at most 5 minutes.

Secret scrubbing: anything matching a token/key/password pattern is replaced
with [REDACTED] before it is written. stderr in particular carries environment
noise.

CLI:
    python3 agents/recovery.py list
    python3 agents/recovery.py show <task-id>
    python3 agents/recovery.py apply <task-id> <run-id> [--worktree <path>]

`apply` must work against a fresh, clean checkout — that is the only version
of "recoverable" that means anything.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

STDERR_TAIL_LINES = 200
CHECKPOINT_INTERVAL = 300

#: Secret patterns scrubbed from every text artifact in a bundle.
_SECRET_PATTERNS = (
    re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,})"),                # GitHub tokens
    re.compile(r"\b(sk-[A-Za-z0-9-]{20,})"),                    # API keys
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),                      # AWS
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})"),            # Slack
    re.compile(r"(?i)((?:password|passwd|secret|token|api_key|apikey|auth)"
               r"\s*[=:]\s*)(\"[^\"]{4,}\"|'[^']{4,}'|[^\s\"']{4,})"),
    re.compile(r"(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
               r"\.[A-Za-z0-9_-]{5,})"),                        # JWTs
)


def scrub(text: str) -> str:
    for rx in _SECRET_PATTERNS:
        if rx.groups >= 2:
            text = rx.sub(lambda m: m.group(1) + "[REDACTED]", text)
        else:
            text = rx.sub("[REDACTED]", text)
    return text


def _git(worktree: Path, *args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(worktree), *args],
                           capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def is_git_worktree(worktree: Path) -> bool:
    rc, out = _git(worktree, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out.strip() == "true"


def is_dirty(worktree: Path) -> bool:
    rc, out = _git(worktree, "status", "--porcelain")
    return rc == 0 and bool(out.strip())


def unpushed_commits(worktree: Path) -> str:
    rc, out = _git(worktree, "log", "origin/main..HEAD", "--oneline")
    return out.strip() if rc == 0 else ""


def bundle_dir(mailroom: Path, task_id: str, run_id: str) -> Path:
    return mailroom / "recovery" / task_id / run_id


def write_checkpoint(worktree: Path, mailroom: Path, *, task_id: str,
                     run_id: str) -> Path | None:
    """The 300-second heartbeat: current patches, rewritten in place."""
    if not is_git_worktree(worktree):
        return None
    d = bundle_dir(mailroom, task_id, run_id)
    try:
        d.mkdir(parents=True, exist_ok=True)
        _, working = _git(worktree, "diff")
        _, staged = _git(worktree, "diff", "--cached")
        (d / "working.patch").write_text(scrub(working))
        (d / "staged.patch").write_text(scrub(staged))
        (d / "checkpoint.at").write_text(str(time.time()))
    except OSError:
        return None
    return d


def write_bundle(worktree: Path, mailroom: Path, *, task_id: str, run_id: str,
                 role: str = "", trigger: str = "manual",
                 exit_code: int | None = None,
                 stderr_tail: str = "") -> Path | None:
    """Full loss-proof bundle. Returns the bundle dir, or None if worktree
    is not a git tree (nothing recoverable) or the mailroom is unwritable."""
    if not is_git_worktree(worktree):
        return None
    d = bundle_dir(mailroom, task_id, run_id)
    try:
        d.mkdir(parents=True, exist_ok=True)
        # --submodule=short: a submodule pointer change emits no plain-diff
        # hunk and no untracked entry — without this a pointer-only dirty
        # tree bundles NOTHING and verifies clean (found on the real
        # frontend-a49a07be specimen, engine/vendor/PathOfBuilding).
        _, working = _git(worktree, "diff", "--submodule=short")
        _, staged = _git(worktree, "diff", "--cached", "--submodule=short")
        _, untracked = _git(worktree, "ls-files", "--others",
                            "--exclude-standard")
        _, status_out = _git(worktree, "status", "--porcelain")
        _, branch = _git(worktree, "rev-parse", "--abbrev-ref", "HEAD")
        _, head = _git(worktree, "rev-parse", "HEAD")
        _, base = _git(worktree, "rev-parse", "origin/main")

        (d / "working.patch").write_text(scrub(working))
        (d / "staged.patch").write_text(scrub(staged))
        (d / "untracked-files.txt").write_text(untracked)
        (d / "branch.txt").write_text(
            f"{branch.strip()}\n{head.strip()}\n")
        (d / "commits.txt").write_text(unpushed_commits(worktree) + "\n")
        (d / "stderr-tail.txt").write_text(
            scrub("\n".join(stderr_tail.splitlines()[-STDERR_TAIL_LINES:])))

        names = [n for n in untracked.splitlines() if n.strip()]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name in names:
                fp = worktree / name
                if fp.is_file():
                    data = fp.read_bytes()
                    try:
                        data = scrub(data.decode()).encode()
                    except UnicodeDecodeError:
                        pass  # binary: keep as-is
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
        (d / "untracked.tar").write_bytes(buf.getvalue())

        result_fp = worktree / ".agent-result.json"
        if result_fp.exists():
            (d / "result.json").write_text(scrub(result_fp.read_text()))

        test_summary = worktree / ".last-test-summary.txt"
        if test_summary.exists():
            (d / "last-test-summary.txt").write_text(
                scrub(test_summary.read_text()))

        (d / "metadata.json").write_text(json.dumps({
            "schema_version": "1.0",
            "task_id": task_id, "run_id": run_id, "role": role,
            "trigger": trigger, "exit_code": exit_code,
            "created_at": time.time(),
            "worktree": str(worktree),
            "head_sha": head.strip(), "origin_main_sha": base.strip(),
            "branch": branch.strip(),
            "dirty": is_dirty(worktree),
            "unpushed_commit_count": len(unpushed_commits(worktree)
                                         .splitlines()),
            "untracked_count": len(names),
            "dirty_entry_count": len(status_out.splitlines()),
            "captured_bytes": len(working) + len(staged)
            + sum((worktree / n).stat().st_size for n in names
                  if (worktree / n).is_file()),
        }, indent=2))
    except OSError as e:
        print(f"RECOVERY-DEGRADED: bundle write failed: {e}", file=sys.stderr)
        return None
    return d


def verify_bundle(d: Path) -> bool:
    """A bundle is verified when its required artifacts exist and parse."""
    try:
        meta = json.loads((d / "metadata.json").read_text())
        # untracked.tar is required: it is the ONLY copy of untracked
        # content — a bundle without it "verifies" a loss.
        if not (all((d / n).exists() for n in
                    ("working.patch", "staged.patch", "untracked-files.txt",
                     "untracked.tar", "branch.txt", "commits.txt"))
                and meta.get("schema_version") == "1.0"):
            return False
        # A dirty tree whose bundle captured NOTHING is a contradiction,
        # not a verified recovery — "artifacts exist and parse" must never
        # be mistaken for "the work was captured". captured_bytes absent
        # (pre-field bundles) falls back to on-disk artifact sizes.
        captured = meta.get("captured_bytes")
        if captured is None:
            captured = ((d / "working.patch").stat().st_size
                        + (d / "staged.patch").stat().st_size
                        + (d / "untracked.tar").stat().st_size)
        if meta.get("dirty") and captured == 0 \
                and not meta.get("unpushed_commit_count"):
            return False
        return True
    except (OSError, json.JSONDecodeError, KeyError):
        return False


def inspect_worktree(worktree: Path, mailroom: Path, *, task_id: str,
                     run_id: str, role: str = "",
                     exit_code: int | None = None,
                     stderr_tail: str = "") -> Path | None:
    """Dispatch step 12: bundle whenever the tree holds unsaved work.

    Dirty tree or unpushed commits after an invocation means work exists
    only here; the supervisor may remove the worktree only when a verified
    bundle exists (or the tree is clean).

    If an abnormal-stop bundle (timeout/sigterm/halt) already exists for
    this run, it is kept as-is: the tree has not changed since the child
    died, and re-bundling would overwrite the trigger provenance — the
    on-disk record of WHY the run stopped.
    """
    if not is_git_worktree(worktree):
        return None
    d = bundle_dir(mailroom, task_id, run_id)
    if (d / "metadata.json").exists():
        return d
    if not is_dirty(worktree) and not unpushed_commits(worktree):
        return None
    return write_bundle(worktree, mailroom, task_id=task_id, run_id=run_id,
                        role=role, trigger="post-invocation",
                        exit_code=exit_code, stderr_tail=stderr_tail)


# ------------------------------------------------------------------ CLI
def cmd_list(mailroom: Path) -> None:
    root = mailroom / "recovery"
    if not root.is_dir():
        print("no recovery bundles")
        return
    for task in sorted(p for p in root.iterdir() if p.is_dir()):
        for run in sorted(p for p in task.iterdir() if p.is_dir()):
            ok = "verified" if verify_bundle(run) else "INCOMPLETE"
            print(f"{task.name}  {run.name}  {ok}")


def cmd_show(mailroom: Path, task_id: str) -> None:
    root = mailroom / "recovery" / task_id
    if not root.is_dir():
        sys.exit(f"no bundles for {task_id}")
    for run in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = {}
        try:
            meta = json.loads((run / "metadata.json").read_text())
        except (OSError, json.JSONDecodeError):
            pass
        print(json.dumps({"run_id": run.name, **meta}, indent=2))


def cmd_apply(mailroom: Path, task_id: str, run_id: str,
              worktree: Path) -> None:
    """Apply a bundle to a fresh, clean checkout."""
    d = bundle_dir(mailroom, task_id, run_id)
    if not verify_bundle(d):
        sys.exit(f"bundle {task_id}/{run_id} missing or unverified")
    if is_dirty(worktree):
        sys.exit(f"refusing to apply onto a dirty tree at {worktree}")
    for patch, staged in (("staged.patch", True), ("working.patch", False)):
        body = (d / patch).read_text()
        if not body.strip():
            continue
        args = ["apply", "--index"] if staged else ["apply"]
        p = subprocess.run(["git", "-C", str(worktree), *args, "-"],
                           input=body, capture_output=True, text=True)
        if p.returncode != 0:
            sys.exit(f"git apply {patch} failed:\n{p.stderr}")
    tar_fp = d / "untracked.tar"
    if tar_fp.exists() and tar_fp.stat().st_size:
        with tarfile.open(tar_fp) as tar:
            tar.extractall(worktree, filter="data")
    print(f"applied {task_id}/{run_id} onto {worktree}")


def main(argv: list[str] | None = None) -> int:
    from agents.postmaster import ledger as ledger_mod
    ap = argparse.ArgumentParser(description="worktree recovery bundles")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("show")
    s.add_argument("task_id")
    a = sub.add_parser("apply")
    a.add_argument("task_id")
    a.add_argument("run_id")
    a.add_argument("--worktree", type=Path, default=Path.cwd())
    b = sub.add_parser("bundle")
    b.add_argument("--worktree", type=Path, required=True)
    b.add_argument("--task-id", required=True)
    b.add_argument("--run-id", required=True)
    b.add_argument("--role", default="")
    b.add_argument("--trigger", default="manual")
    ns = ap.parse_args(argv)
    mailroom = ledger_mod.ledger_root()
    if ns.cmd == "list":
        cmd_list(mailroom)
    elif ns.cmd == "show":
        cmd_show(mailroom, ns.task_id)
    elif ns.cmd == "apply":
        cmd_apply(mailroom, ns.task_id, ns.run_id, ns.worktree.resolve())
    elif ns.cmd == "bundle":
        d = write_bundle(ns.worktree.resolve(), mailroom, task_id=ns.task_id,
                         run_id=ns.run_id, role=ns.role, trigger=ns.trigger)
        print(str(d) if d else "no bundle written")
    return 0


if __name__ == "__main__":
    _here = Path(__file__).resolve().parents[1]
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    sys.exit(main())
