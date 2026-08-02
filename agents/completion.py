"""Dispatcher-verified completion (CC-2).

A self-reported "completed" is a CLAIM, not a verdict. Before this module
existed, the fabricated payload `{"status": "completed", "pushed": false,
"commit_sha": "0000000", "acceptance_criteria": []}` was schema-valid and
ackable: it drove a governor success row and a spend row on the agent's
word alone. The dispatcher now verifies completion proofs before any ack
applies; a failing proof beats the self-report and the message is retained.

The proof LIST is data-driven: `agents/completion_proofs.yaml` names the
active proofs and carries the contract parameters (e.g. the allowed task
branch pattern), so pm-ratified values from plan v1.0 drop in without code
change. Checker implementations are registered here by proof id. Proofs
#5–#15 of the plan await the base contract (pm ANSWER pending) and are NOT
invented here — absence is reported, never filled.

Unknown-value semantics follow the contract's A4 precedent: a proof whose
contract parameter is unset is recorded as NOT EVALUABLE (`passed: None`)
in telemetry — never inferred to pass, never silently converted to a
failure. Only a proof that positively FAILS refuses the completion.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import re

import yaml

PARAMS_PATH = Path(__file__).resolve().parent / "completion_proofs.yaml"

#: A6: the ls-remote observation persisted as evidence-at-time-T in the run
#: record. A later discrepancy (e.g. a force-push after the check) is then
#: diagnosable rather than silent; there is deliberately no re-check loop.
LS_REMOTE_RECORD = "ls-remote.json"

_GIT_TIMEOUT = 60


@dataclass
class Proof:
    """One completion proof's outcome. `passed` is tri-state: True, False,
    or None for not-evaluable (contract parameter unset / not applicable)."""

    proof_id: str
    passed: bool | None
    detail: str


def load_params(path: Path | None = None) -> dict:
    """Contract parameters for the proofs. Missing file → empty params:
    every parameterised proof then reports not-evaluable, loudly."""
    p = path or PARAMS_PATH
    try:
        data = yaml.safe_load(p.read_text())
    except OSError:
        return {}
    return data if isinstance(data, dict) else {}


def _git(worktree: Path, *args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(worktree), *args],
                           capture_output=True, text=True,
                           timeout=_GIT_TIMEOUT)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


# ------------------------------------------------------------------ proofs

def proof_commit_exists(res: dict, ctx: dict) -> Proof:
    """#1 — the claimed commit object exists in the worktree's repository."""
    sha = res.get("commit_sha")
    if not sha:
        return Proof("commit_exists", False, "no commit_sha in a completed result")
    rc, out = _git(ctx["worktree"], "cat-file", "-e", f"{sha}^{{commit}}")
    if rc != 0:
        return Proof("commit_exists", False,
                     f"commit {sha} does not exist in the repository "
                     f"(cat-file rc={rc})")
    return Proof("commit_exists", True, f"commit {sha} exists")


def proof_pushed_remote_agreement(res: dict, ctx: dict) -> Proof:
    """#2 — `pushed` must be true and the remote must agree: the claimed
    branch exists on origin and the claimed commit is at its tip. The
    ls-remote observation is stashed in ctx for proof #4 to persist."""
    if res.get("pushed") is not True:
        return Proof("pushed_remote_agreement", False,
                     "completed result claims pushed=false — commits not "
                     "pushed are lost with the worktree")
    branch = res.get("branch")
    if not branch:
        return Proof("pushed_remote_agreement", False,
                     "no branch named in a completed result — push claim "
                     "is unverifiable")
    rc, out = _git(ctx["worktree"], "ls-remote", "origin",
                   f"refs/heads/{branch}")
    observed = out.split("\t", 1)[0].strip() if rc == 0 and out.strip() else None
    ctx["ls_remote"] = {"branch": branch, "sha": observed,
                        "observed_at": time.time(),
                        "claimed_commit_sha": res.get("commit_sha"),
                        "ls_remote_rc": rc}
    if rc != 0:
        return Proof("pushed_remote_agreement", False,
                     f"ls-remote failed (rc={rc}): {out.strip()[:200]}")
    if not observed:
        return Proof("pushed_remote_agreement", False,
                     f"branch {branch} does not exist on origin")
    claimed = res.get("commit_sha") or ""
    if not observed.startswith(claimed):
        return Proof("pushed_remote_agreement", False,
                     f"remote {branch} is at {observed[:12]}, not the "
                     f"claimed {claimed[:12]}")
    return Proof("pushed_remote_agreement", True,
                 f"origin/{branch} at {observed[:12]} matches the claim")


def proof_branch_pattern(res: dict, ctx: dict) -> Proof:
    """#3 — the branch matches the ratified task-branch pattern. The
    pattern VALUE is contract data (pm ANSWER); unset → not evaluable."""
    pattern = (ctx.get("params") or {}).get("branch_pattern")
    if not pattern:
        return Proof("branch_pattern", None,
                     "branch_pattern unset — pm ANSWER pending (plan v1.0); "
                     "recorded not-evaluable, never inferred")
    branch = res.get("branch")
    if not branch:
        return Proof("branch_pattern", False,
                     "no branch named in a completed result")
    if not re.fullmatch(pattern, branch):
        return Proof("branch_pattern", False,
                     f"branch {branch!r} does not match ratified pattern "
                     f"{pattern!r}")
    return Proof("branch_pattern", True, f"branch {branch!r} matches pattern")


def proof_ls_remote_recorded(res: dict, ctx: dict) -> Proof:
    """#4 (A6) — the ls-remote observation from proof #2 is durably
    persisted in mailroom/runs/<run_id>/ as evidence-at-time-T."""
    obs = ctx.get("ls_remote")
    if obs is None:
        return Proof("ls_remote_recorded", False,
                     "no ls-remote observation was taken (proof #2 could "
                     "not run one)")
    dest = Path(ctx["mailroom"]) / "runs" / ctx["run_id"]
    try:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / LS_REMOTE_RECORD).write_text(json.dumps(obs, indent=2))
    except OSError as e:
        return Proof("ls_remote_recorded", False,
                     f"could not persist ls-remote evidence: {e}")
    return Proof("ls_remote_recorded", True,
                 f"observation persisted to runs/{ctx['run_id']}/"
                 f"{LS_REMOTE_RECORD}")


#: Checker registry, keyed by the proof id used in completion_proofs.yaml.
#: The yaml decides WHICH proofs are active and their parameters; new
#: pm-ratified proofs that parameterise an existing kind drop in as data.
CHECKERS = {
    "commit_exists": proof_commit_exists,
    "pushed_remote_agreement": proof_pushed_remote_agreement,
    "branch_pattern": proof_branch_pattern,
    "ls_remote_recorded": proof_ls_remote_recorded,
}


def verify_completion(res: dict, *, worktree: Path, mailroom: Path,
                      run_id: str, packet: dict | None = None,
                      params: dict | None = None) -> list[Proof]:
    """Run every active proof against a `completed` result, in order.

    Every proof runs — a failing early proof does not short-circuit the
    rest, because the refusal detail should name everything wrong with the
    claim, not the first thing.
    """
    p = params if params is not None else load_params()
    active = [e["id"] if isinstance(e, dict) else str(e)
              for e in (p.get("proofs") or [])]
    ctx: dict = {"worktree": Path(worktree), "mailroom": Path(mailroom),
                 "run_id": run_id, "packet": packet, "params": p}
    results: list[Proof] = []
    for proof_id in active:
        checker = CHECKERS.get(proof_id)
        if checker is None:
            # A yaml entry with no registered checker is a contract/code
            # mismatch — refuse rather than silently skip a ratified proof.
            results.append(Proof(proof_id, False,
                                 "no checker registered for this proof id"))
            continue
        try:
            results.append(checker(res, ctx))
        except Exception as e:  # noqa: BLE001 — a crashing proof must not ack
            results.append(Proof(proof_id, False,
                                 f"proof crashed: {type(e).__name__}: {e}"))
    return results


def refusal(proofs: list[Proof]) -> str | None:
    """The refusal line for telemetry/result_error, or None when no proof
    positively failed. Not-evaluable proofs are recorded, not refused."""
    failed = [p for p in proofs if p.passed is False]
    if not failed:
        return None
    return "completion refused: " + "; ".join(
        f"{p.proof_id}: {p.detail}" for p in failed)


def proofs_telemetry(proofs: list[Proof]) -> list[dict]:
    return [asdict(p) for p in proofs]
