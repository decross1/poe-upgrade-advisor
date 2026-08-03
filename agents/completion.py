"""Dispatcher-verified completion (CC-2) — ratified proofs #1–#15.

A self-reported "completed" is a CLAIM, not a verdict. The dispatcher
verifies all fifteen ratified proofs (pm ANSWER 2026-08-02T20:50Z, from the
v1.0 reconstruction) before any ack applies. Numbering anchors #3/#4/#8 are
fixed by v1.1 and must not be renumbered.

Severity: a proof failure normally invalidates the ATTEMPT (message
retained; the cap or anti-loop retires it). Proofs #12/#13 — protected
path, banned/test-weakening signature — and a known-spend ceiling breach in
#14 are CIRCUIT BREAKS: the dispatcher terminates via the dead-letter path
(dispatcher-authored status per A7), never ack-as-success.

Unknown-value semantics follow A4: a proof whose contract input is absent
(no packet, unknown spend, unset pattern) is recorded NOT EVALUABLE
(`passed: None`) — never inferred to pass, never silently failed. Only a
positively failing proof refuses.

The active proof list and parameters are data
(`agents/completion_proofs.yaml`); checkers are registered here by id.
Proof #15 (accounting-before-ack) is an ORDERING property the dispatcher
itself satisfies at ack time — verify_completion() emits its placeholder
and dispatch.py replaces it with the real outcome in the persisted bundle.
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

PARAMS_PATH = Path(__file__).resolve().parent / "completion_proofs.yaml"

#: A6: the ls-remote observation persisted as evidence-at-time-T in the run
#: record; TOCTOU accepted and made diagnosable, no re-check loop.
LS_REMOTE_RECORD = "ls-remote.json"
#: The assembled proof bundle (all verdicts + evidence pointers).
PROOF_BUNDLE = "completion-proof.json"

_GIT_TIMEOUT = 60


@dataclass
class Proof:
    """One proof's outcome. `passed` is tri-state (True/False/None =
    not-evaluable). `severity` is "fail" (invalid attempt, retain) or
    "break" (immediate circuit break)."""

    number: int
    proof_id: str
    passed: bool | None
    detail: str
    severity: str = "fail"


def load_params(path: Path | None = None) -> dict:
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


def _diff_paths(ctx: dict) -> list[str] | None:
    """Changed paths base..commit, cached in ctx. None = unobtainable."""
    if "diff_paths" not in ctx:
        base, sha = ctx.get("base_sha"), ctx["res"].get("commit_sha")
        if not base or not sha:
            ctx["diff_paths"] = None
        else:
            rc, out = _git(ctx["worktree"], "diff", "--name-only",
                           f"{base}..{sha}")
            ctx["diff_paths"] = ([ln.strip() for ln in out.splitlines()
                                  if ln.strip()] if rc == 0 else None)
    return ctx["diff_paths"]


def _diff_text(ctx: dict) -> str | None:
    if "diff_text" not in ctx:
        base, sha = ctx.get("base_sha"), ctx["res"].get("commit_sha")
        if not base or not sha:
            ctx["diff_text"] = None
        else:
            rc, out = _git(ctx["worktree"], "diff", f"{base}..{sha}")
            ctx["diff_text"] = out if rc == 0 else None
    return ctx["diff_text"]


# ------------------------------------------------------------------ proofs

def p1_result_valid(res, ctx):
    # Reaching verification at all means load_result() accepted the file
    # against the A7-amended schema; recorded so the bundle is complete.
    return Proof(1, "result_valid", True,
                 "result file parsed and schema-valid (A7-amended enum)")


def p2_completed_fields(res, ctx):
    missing = [f for f in ("commit_sha", "pushed", "acceptance_criteria")
               if f not in res]
    if res.get("status") != "completed":
        return Proof(2, "completed_fields", False,
                     f"status is {res.get('status')!r}, not completed")
    if missing:
        return Proof(2, "completed_fields", False,
                     f"completed-conditional fields missing: {missing}")
    return Proof(2, "completed_fields", True,
                 "status completed with conditional fields present")


def p3_pushed(res, ctx):
    if res.get("pushed") is not True:
        return Proof(3, "pushed", False,
                     "completed result claims pushed=false — commits not "
                     "pushed are lost with the worktree; the dispatcher "
                     "never pushes (remote confirmation is #8)")
    return Proof(3, "pushed", True, "pushed=true claimed (verified by #8)")


def p4_branch_pattern(res, ctx):
    packet = ctx.get("packet") or {}
    pattern = (packet.get("branch_pattern")
               or (ctx.get("params") or {}).get("branch_pattern"))
    if not pattern:
        return Proof(4, "branch_pattern", None,
                     "no packet or repo-wide pattern configured")
    branch = res.get("branch")
    if not branch:
        return Proof(4, "branch_pattern", False,
                     "no branch named in a completed result")
    if not re.fullmatch(pattern, branch):
        return Proof(4, "branch_pattern", False,
                     f"branch {branch!r} does not match {pattern!r}")
    return Proof(4, "branch_pattern", True, f"branch {branch!r} conforms")


def p5_commit_exists(res, ctx):
    sha = res.get("commit_sha")
    if not sha:
        return Proof(5, "commit_exists", False,
                     "no commit_sha in a completed result")
    rc, out = _git(ctx["worktree"], "rev-parse", "--verify", "--quiet",
                   f"{sha}^{{commit}}")
    if rc != 0:
        return Proof(5, "commit_exists", False,
                     f"commit {sha} does not resolve in the repository")
    return Proof(5, "commit_exists", True, f"commit {sha} exists")


def p6_descends_from_base(res, ctx):
    base = ctx.get("base_sha")
    sha = res.get("commit_sha")
    if not base:
        return Proof(6, "descends_from_base", False,
                     "no worktree base SHA was recorded at invocation — "
                     "ancestry unverifiable")
    if not sha:
        return Proof(6, "descends_from_base", False, "no commit_sha")
    rc, _ = _git(ctx["worktree"], "merge-base", "--is-ancestor", base, sha)
    if rc != 0:
        return Proof(6, "descends_from_base", False,
                     f"{sha[:12]} does not descend from base {base[:12]} "
                     "(orphan branch or history rewrite)")
    return Proof(6, "descends_from_base", True,
                 f"{sha[:12]} descends from {base[:12]}")


def p7_tree_clean_after_sweep(res, ctx):
    rc, out = _git(ctx["worktree"], "status", "--porcelain")
    if rc != 0:
        return Proof(7, "tree_clean_after_sweep", False,
                     f"git status failed (rc={rc}) — cleanliness unprovable")
    if out.strip():
        dirty = [ln for ln in out.splitlines() if ln.strip()][:5]
        return Proof(7, "tree_clean_after_sweep", False,
                     f"tree dirty after the result sweep: {dirty}")
    return Proof(7, "tree_clean_after_sweep", True,
                 "worktree clean after sweep")


def p8_remote_agreement(res, ctx):
    branch = res.get("branch")
    if not branch:
        ctx["ls_remote"] = {"branch": None, "sha": None, "raw": "",
                            "observed_at": time.time(),
                            "claimed_commit_sha": res.get("commit_sha"),
                            "ls_remote_rc": None}
        _persist_ls_remote(ctx)
        return Proof(8, "remote_agreement", False,
                     "no branch named — remote agreement unverifiable")
    rc, out = _git(ctx["worktree"], "ls-remote", "origin",
                   f"refs/heads/{branch}")
    observed = out.split("\t", 1)[0].strip() if rc == 0 and out.strip() else None
    ctx["ls_remote"] = {"branch": branch, "sha": observed, "raw": out[:2000],
                        "observed_at": time.time(),
                        "claimed_commit_sha": res.get("commit_sha"),
                        "ls_remote_rc": rc}
    persisted = _persist_ls_remote(ctx)
    if rc != 0:
        return Proof(8, "remote_agreement", False,
                     f"ls-remote failed (rc={rc}): {out.strip()[:200]}")
    if not observed:
        return Proof(8, "remote_agreement", False,
                     f"branch {branch} does not exist on origin")
    claimed = res.get("commit_sha") or ""
    if not observed.startswith(claimed):
        return Proof(8, "remote_agreement", False,
                     f"origin/{branch} is at {observed[:12]}, not the "
                     f"claimed {claimed[:12]}")
    if not persisted:
        return Proof(8, "remote_agreement", False,
                     "remote agrees but the evidence record could not be "
                     "persisted — evidence-at-time-T is part of this proof")
    return Proof(8, "remote_agreement", True,
                 f"origin/{branch} at {observed[:12]} matches; raw "
                 f"observation persisted")


def _persist_ls_remote(ctx) -> bool:
    dest = Path(ctx["mailroom"]) / "runs" / ctx["run_id"]
    try:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / LS_REMOTE_RECORD).write_text(
            json.dumps(ctx["ls_remote"], indent=2))
        return True
    except OSError as e:
        print(f"WARNING: ls-remote evidence not persisted: {e}",
              file=sys.stderr)
        return False


def p9_required_checks(res, ctx):
    results = ctx.get("check_results")
    if results is None:
        return Proof(9, "required_checks_pass", None,
                     "no check results supplied to verification")
    bad = [r for r in results if not r.ok]
    if bad:
        return Proof(9, "required_checks_pass", False,
                     "dispatcher-run required checks failed: "
                     + "; ".join(f"{r.cmd!r}" for r in bad))
    return Proof(9, "required_checks_pass", True,
                 f"{len(results)} dispatcher-run check(s), all rc=0 "
                 "(agent tests[] array not consulted)")


#: Intents where the agent is JUDGING someone else's work rather than doing
#: the packet's work. The distinction is not cosmetic: a packet's
#: acceptance_criteria and files_in_scope describe the BUILDER's obligations,
#: so applying them to a reviewer asks the reviewer to satisfy criteria it was
#: never given and to produce its verdict inside a scope that no build packet
#: will ever list. See REVIEW_ROUTING_NOTE below for the measured cost.
REVIEW_INTENTS = frozenset({
    "REVIEW_REQUEST", "REVIEW_VERDICT",
    "ARBITRATION_REQUEST", "ARBITRATION_RULING",
})

#: Where a reviewer's written verdict may land. A review's deliverable is
#: evidence, and it needs somewhere to live that is neither the builder's
#: scope nor the control plane.
REVIEW_EVIDENCE_GLOBS = ("docs/agent-org/*",)

REVIEW_ROUTING_NOTE = """2026-08-03 orchestrator ruling (L-26).

Proofs #10 and #11 read the packet named by the MESSAGE's task_id. For a
TASK_ASSIGN that is right — the agent is building the thing the packet
describes. For a REVIEW_REQUEST it is a category error: the reviewer is
handed the BUILDER's packet and judged against the builder's obligations.

The failure was structural, not occasional, and it was measured in one
morning across all three roles:

  pm       TASK-210-S3  #10 invented ['REVIEW-PROCESS','REVIEW-PROVENANCE']
                        #11 out of scope ['docs/agent-org/task-210-s3-review-...md']
  frontend TASK-210-S3  #10 invented ['verdict-acknowledged','pm-evidence-confirmed', ...]
                        #11 out of scope ['docs/agent-org/task-210-s3-verdict-ack-...md']
  backend  TASK-210-S2  #10 invented ['AC-REVIEW-EXECUTION','AC-BLAST-RADIUS', ...]

Every agent independently did the sensible thing — name the criteria a
REVIEW is judged on, and write the verdict to docs/agent-org/ — and every
one was refused for it. No prompt fixes this: there is no id-set a reviewer
can emit that equals the builder's, and no path inside a build packet's
scope where a verdict belongs. Review work was unpassable by construction,
which is why review->merge, the loop the mission runs on, never closed.

The correction is to evaluate the right obligations, NOT to lower the bar:
  #10 is not evaluable for a review intent (the builder's ACs are not the
      reviewer's) — the same `None` verdict this proof already returns when
      there is no packet at all.
  #11 additionally admits docs/agent-org/* for a review intent. Build
      scope for builders is untouched.

Everything else still binds on reviews: #9 still re-runs the required
checks, #12 still circuit-breaks on PROTECTED paths (docs/agent-org/* is
not protected), and the review verdict itself still has to reach the ledger.
"""


def p10_acceptance_criteria(res, ctx):
    packet = ctx.get("packet")
    if not packet:
        return Proof(10, "acceptance_criteria", None,
                     "no packet — AC set-equality not evaluable")
    if ctx.get("intent") in REVIEW_INTENTS:
        # L-26: the packet's ACs are the BUILDER's obligations; a reviewer
        # never agreed to them and cannot emit their id-set. Not evaluable —
        # the reviewer's substantive gates are #9 and its ledger verdict.
        return Proof(10, "acceptance_criteria", None,
                     f"review intent {ctx['intent']} — the packet's ACs bind "
                     "the builder, not the reviewer; not evaluable (L-26)")
    want = {c["id"] for c in packet.get("acceptance_criteria") or []}
    got = {c.get("id") for c in res.get("acceptance_criteria") or []}
    if want != got:
        return Proof(10, "acceptance_criteria", False,
                     f"AC id-set mismatch: missing {sorted(want - got)}, "
                     f"invented {sorted(got - want)}")
    bad = [c.get("id") for c in res.get("acceptance_criteria") or []
           if c.get("status") != "passed" or not c.get("evidence")]
    if bad:
        return Proof(10, "acceptance_criteria", False,
                     f"ACs not passed-with-evidence: {bad}")
    return Proof(10, "acceptance_criteria", True,
                 f"{len(want)} ACs: exact id-set, all passed with evidence "
                 "(mechanical ACs re-verified by #9)")


def p11_scope(res, ctx):
    packet = ctx.get("packet")
    if not packet:
        return Proof(11, "scope", None, "no packet — scope not evaluable")
    paths = _diff_paths(ctx)
    if paths is None:
        return Proof(11, "scope", False,
                     "base..commit diff unobtainable — scope unprovable")
    from agents.interfaces.packet import out_of_scope  # noqa: PLC0415
    bad = out_of_scope(paths, packet)
    if bad and ctx.get("intent") in REVIEW_INTENTS:
        # L-26: a review's deliverable is a written verdict, and no build
        # packet lists a path for one. Admit the review-evidence dir — and
        # ONLY it — so the rest of the scope check still bites.
        bad = [p for p in bad
               if not any(fnmatch.fnmatch(p, g)
                          for g in REVIEW_EVIDENCE_GLOBS)]
    if bad:
        return Proof(11, "scope", False,
                     f"paths out of scope (deny wins): {bad[:5]}")
    return Proof(11, "scope", True,
                 f"{len(paths)} changed path(s), all in scope")


def p12_protected(res, ctx):
    paths = _diff_paths(ctx)
    if paths is None:
        # Unprovable is a retain-failure (#5 owns the fake-commit case);
        # the CIRCUIT BREAK is reserved for a positively observed violation.
        return Proof(12, "protected_paths", False,
                     "base..commit diff unobtainable — protection "
                     "unprovable")
    from agents.merge_robot.patterns import PROTECTED  # noqa: PLC0415
    hit = [p for p in paths
           if any(fnmatch.fnmatch(p, g) for g in PROTECTED)]

    # 2026-08-03 orchestrator ruling (L-4). CC-4 protected `tasks/packets/*`
    # so a TASK agent cannot rewrite the constraints it is being judged
    # against — a real control, kept. But this proof had no role awareness,
    # so it also circuit-broke **pm authoring a packet**, which is pm's core
    # planning job (SPEC.md: only the PM identity applies `protected-change`;
    # ADR-0003 gives pm the merge exception). Observed live: the mission
    # message dead-lettered for committing `tasks/packets/TASK-999-S2.json`,
    # making the autonomous planning loop impossible.
    #
    # The carve-out is deliberately the narrowest that restores the role:
    # pm, packets only. Every other protected glob — agents/*, .github/*,
    # contracts/*, PRODUCT_DOCTRINE.md, AGENTS.md, engine/corpus/*,
    # scripts/check_invariants.py — still circuit-breaks for pm too, and
    # ALL of them still circuit-break for every non-pm role. Merge-time
    # authorization is unchanged: the PR still needs `protected-change`,
    # which is where a human sees it.
    if hit and ctx.get("role") == "pm":
        packets_only = [p for p in hit if fnmatch.fnmatch(p, "tasks/packets/*")]
        if len(packets_only) == len(hit):
            return Proof(12, "protected_paths", True,
                         f"pm authored packet(s) {packets_only[:5]} — "
                         "role-authorized protected change (L-4); merge-time "
                         "`protected-change` label still required")

    if hit:
        return Proof(12, "protected_paths", False,
                     f"PROTECTED path in committed diff: {hit[:5]} — "
                     "circuit break", severity="break")
    return Proof(12, "protected_paths", True,
                 "no protected path in the committed diff")


def p13_banned_patterns(res, ctx):
    text = _diff_text(ctx)
    if text is None:
        return Proof(13, "banned_patterns", False,
                     "base..commit diff unobtainable — pattern scan "
                     "unprovable")
    from agents.merge_robot.patterns import BANNED, TEST_SIG  # noqa: PLC0415
    hits: list[str] = []
    for line in text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            for b in BANNED:
                if re.search(b, line[1:]):
                    hits.append(f"BANNED {b!r}")
        for sig in TEST_SIG:
            if re.search(sig, line):
                hits.append(f"TEST_SIG {sig!r}")
    if hits:
        return Proof(13, "banned_patterns", False,
                     f"signature(s) in diff: {sorted(set(hits))[:5]} — "
                     "circuit break", severity="break")
    return Proof(13, "banned_patterns", True,
                 "no banned or test-weakening signature in the diff")


def p14_budgets(res, ctx):
    packet = ctx.get("packet")
    budgets = (packet or {}).get("budgets") or {}
    if not budgets:
        return Proof(14, "budgets", None,
                     "no packet budgets — not evaluable")
    problems: list[str] = []
    severity = "fail"
    paths = _diff_paths(ctx)
    mf = budgets.get("max_files_modified")
    if mf is not None and paths is not None and len(paths) > mf:
        problems.append(f"files {len(paths)} > max {mf}")
    ml = budgets.get("max_diff_lines")
    if ml is not None:
        text = _diff_text(ctx)
        if text is not None:
            lines = sum(1 for ln in text.splitlines()
                        if (ln.startswith("+") and not ln.startswith("+++"))
                        or (ln.startswith("-") and not ln.startswith("---")))
            if lines > ml:
                problems.append(f"diff lines {lines} > max {ml}")
    ma = budgets.get("max_attempts")
    if ma is not None and ctx.get("attempts") is not None \
            and ctx["attempts"] > ma:
        problems.append(f"attempt {ctx['attempts']} > max {ma}")
    mw = budgets.get("max_wall_clock_seconds")
    if mw is not None and ctx.get("duration_seconds") is not None \
            and ctx["duration_seconds"] > mw:
        problems.append(f"duration {ctx['duration_seconds']:.0f}s > {mw}s")
    ceiling = budgets.get("cost_ceiling_usd")
    cash = (ctx.get("usage") or {}).get("cash_usd")
    ceiling_note = ""
    if ceiling is not None:
        if cash is None:
            ceiling_note = "; ceiling: not_evaluable (unknown spend, A4)"
        elif cash > ceiling:
            problems.append(f"cash {cash} > ceiling {ceiling}")
            severity = "break"  # T-A3: known spend over ceiling breaks
    if problems:
        return Proof(14, "budgets", False,
                     "; ".join(problems) + ceiling_note, severity=severity)
    return Proof(14, "budgets", True,
                 "within packet budgets" + ceiling_note)


CHECKERS = {
    "result_valid": p1_result_valid,
    "completed_fields": p2_completed_fields,
    "pushed": p3_pushed,
    "branch_pattern": p4_branch_pattern,
    "commit_exists": p5_commit_exists,
    "descends_from_base": p6_descends_from_base,
    "tree_clean_after_sweep": p7_tree_clean_after_sweep,
    "remote_agreement": p8_remote_agreement,
    "required_checks_pass": p9_required_checks,
    "acceptance_criteria": p10_acceptance_criteria,
    "scope": p11_scope,
    "protected_paths": p12_protected,
    "banned_patterns": p13_banned_patterns,
    "budgets": p14_budgets,
}


def verify_completion(res: dict, *, worktree: Path, mailroom: Path,
                      run_id: str, packet: dict | None = None,
                      params: dict | None = None,
                      base_sha: str | None = None,
                      check_results: list | None = None,
                      attempts: int | None = None,
                      duration_seconds: float | None = None,
                      usage: dict | None = None,
                      role: str | None = None,
                      intent: str | None = None) -> list[Proof]:
    """Run proofs #1–#14 in order (every one runs — the refusal should name
    everything wrong, not the first thing). #15 is appended by the
    dispatcher at ack time; its placeholder is emitted here so the bundle
    always carries fifteen verdicts."""
    p = params if params is not None else load_params()
    active = [e["id"] if isinstance(e, dict) else str(e)
              for e in (p.get("proofs") or [])]
    ctx: dict = {"worktree": Path(worktree), "mailroom": Path(mailroom),
                 "run_id": run_id, "packet": packet, "params": p,
                 "res": res, "base_sha": base_sha,
                 "check_results": check_results, "attempts": attempts,
                 "duration_seconds": duration_seconds, "usage": usage,
                 "role": role, "intent": intent}
    results: list[Proof] = []
    for proof_id in active:
        if proof_id == "accounting_before_ack":
            results.append(Proof(15, "accounting_before_ack", None,
                                 "evaluated by the dispatcher at ack time"))
            continue
        checker = CHECKERS.get(proof_id)
        if checker is None:
            results.append(Proof(0, proof_id, False,
                                 "no checker registered for this proof id"))
            continue
        try:
            results.append(checker(res, ctx))
        except Exception as e:  # noqa: BLE001 — a crashing proof must not ack
            results.append(Proof(0, proof_id, False,
                                 f"proof crashed: {type(e).__name__}: {e}"))
    return results


def refusal(proofs: list[Proof]) -> str | None:
    failed = [p for p in proofs if p.passed is False]
    if not failed:
        return None
    return "completion refused: " + "; ".join(
        f"#{p.number} {p.proof_id}: {p.detail}" for p in failed)


def breaks(proofs: list[Proof]) -> list[Proof]:
    """Proofs that failed with circuit-break severity (#12/#13, #14
    ceiling): terminate via the dead-letter path, never ack-as-success."""
    return [p for p in proofs if p.passed is False and p.severity == "break"]


def proofs_telemetry(proofs: list[Proof]) -> list[dict]:
    return [asdict(p) for p in proofs]


def persist_bundle(mailroom: Path, run_id: str, proofs: list[Proof],
                   extra: dict | None = None) -> Path | None:
    """The assembled completion proof — all verdicts + evidence pointers —
    persisted in mailroom/runs/<run_id>/ (proof #15's bundle half)."""
    dest = Path(mailroom) / "runs" / run_id
    try:
        dest.mkdir(parents=True, exist_ok=True)
        fp = dest / PROOF_BUNDLE
        fp.write_text(json.dumps({
            "schema_version": "1.0", "run_id": run_id,
            "assembled_at": time.time(),
            "proofs": proofs_telemetry(proofs),
            **(extra or {}),
        }, indent=2))
        return fp
    except OSError as e:
        print(f"WARNING: completion-proof bundle not persisted: {e}",
              file=sys.stderr)
        return None
