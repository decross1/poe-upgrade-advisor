"""Dispatcher-executed packet commands: policy, checks, provisioning (CC-1).

At 228bea2 `grep -c required_checks agents/dispatch.py` was 0 — the packet
schema promised "shell commands the dispatcher runs itself. Authoritative"
and nothing implemented it. This module is that implementation, plus the
two amendments that make it operable:

**Scope (A3 — one sentence, load-bearing):** this policy governs
packet-declared `required_checks` and `deterministic_prepass` ONLY —
commands the DISPATCHER executes. It does not constrain the agent's own
tool use inside its invocation (the agent MUST be able to push; the agent
is bounded by scope guards, protected paths, budgets and the banned-pattern
scan instead).

**Provisioning (A2):** `npm ci` is banned in packets, yet npm-based checks
cannot run in a fresh worktree without node_modules. Dependency
provisioning is therefore a dispatcher-owned privileged prepass — derived
from the packet's commands, never expressible in them — run before the
model is invoked, timed and telemetered, and never charged against the
packet's wall-clock cap.

Command policy is DATA (`agents/command_policy.yaml`): the four bans are
contract today; the positive allowlist is null until pm's ANSWER ratifies
plan v1.0's contents, and that bans-only state is stamped on every record.
Commands are shlex-parsed and compared token-wise — `npm  install` is
banned however it is spaced, `npm-install-helper` is not, and shell
composition (`&&`, `|`, `;`, redirects, substitution) is rejected outright
rather than prefix-matched (the checks run WITHOUT a shell).
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

POLICY_PATH = Path(__file__).resolve().parent / "command_policy.yaml"

#: Per-check wall cap. Dispatcher work, not packet work: deliberately NOT
#: budgets["max_wall_clock_seconds"].
CHECK_TIMEOUT = int(os.environ.get("CHECK_TIMEOUT", "600"))
PROVISION_TIMEOUT = int(os.environ.get("PROVISION_TIMEOUT", "900"))

#: Tokens that mean "this string needs a shell". Their presence anywhere in
#: the parse is a rejection — composition cannot be policy-checked
#: token-wise, so it does not run.
_SHELL_OPERATORS = {"&&", "||", ";", "|", ">", ">>", "<", "<<", "&"}


class CommandPolicyError(ValueError):
    """A packet command the dispatcher refuses to execute."""


def load_command_policy(path: Path | None = None) -> dict:
    p = path or POLICY_PATH
    try:
        data = yaml.safe_load(p.read_text())
    except OSError:
        # No policy file is not "no policy": the contract bans are baked in.
        return {"banned": _CONTRACT_BANS, "allowlist": None}
    if not isinstance(data, dict):
        return {"banned": _CONTRACT_BANS, "allowlist": None}
    data.setdefault("banned", _CONTRACT_BANS)
    return data


#: v1.1 §CC-1: the only ratified policy contents today.
_CONTRACT_BANS = [["npm", "install"], ["npm", "ci"], ["git", "push"], ["gh"]]


def parse_command(cmd: str) -> list[str]:
    """shlex-parse one packet command into argv, or raise.

    Anything a plain argv cannot express — operators, redirects,
    substitution — is rejected: `parsed or rejected, not prefix-matched`.
    """
    if not cmd or not cmd.strip():
        raise CommandPolicyError("empty command")
    if "$(" in cmd or "`" in cmd:
        raise CommandPolicyError(f"command substitution rejected: {cmd!r}")
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError as e:
        raise CommandPolicyError(f"unparseable command {cmd!r}: {e}") from e
    for t in tokens:
        if t in _SHELL_OPERATORS or (set(t) <= set("&|;<>") and t):
            raise CommandPolicyError(
                f"shell composition rejected ({t!r}): {cmd!r}")
    if not tokens:
        raise CommandPolicyError(f"no tokens in command {cmd!r}")
    return tokens


# --------------------------------------------------- entry validators
# Each validator answers for ONE allowlist entry: "accept", "no-match"
# (entry does not apply — try the next), or raises CommandPolicyError when
# the command clearly targets this entry but violates its constraints
# (extra args, disallowed flag, wrong context) — a constraint violation
# must surface as ITS reason, not as a generic not-in-allowlist.

_SAFE_PATH = lambda p: not p.startswith("/") and ".." not in Path(p).parts  # noqa: E731


def _v_exact(argv, entry, context):
    return "accept" if argv == [str(a) for a in entry["argv"]] else "no-match"


def _v_pytest(argv, entry, context):
    if argv[:1] == ["pytest"]:
        rest = argv[1:]
    elif argv[:3] == ["python3", "-m", "pytest"]:
        rest = argv[3:]
    else:
        return "no-match"
    prefixes = tuple(entry.get("target_prefixes")
                     or ["tests", "packaging", "engine/tests"])
    for a in rest:
        if a in ("-q", "--cov", "--cov-report=json"):
            continue
        if a.startswith("-"):
            raise CommandPolicyError(f"pytest flag not allowlisted: {a!r}")
        base = a.split("::", 1)[0]
        if not any(base == p or base.startswith(p + "/") for p in prefixes):
            raise CommandPolicyError(
                f"pytest target outside allowed trees: {a!r}")
    return "accept"


def _v_packets_validate(argv, entry, context):
    if argv == ["python3", "agents/packets/validate.py", "--all"]:
        return "accept"
    if argv[:3] == ["python3", "-m", "agents.packets.validate"]:
        rest = argv[3:]
        if rest in ([], ["--all"]):
            return "accept"
        if len(rest) == 1 and rest[0].startswith("tasks/packets/"):
            return "accept"
        raise CommandPolicyError(
            f"packets.validate arg not allowed: {rest!r}")
    return "no-match"


def _v_unittest_engine(argv, entry, context):
    head = ["python3", "-m", "unittest", "discover", "-s", "engine/tests"]
    if argv[: len(head)] != head:
        return "no-match"
    rest = argv[len(head):]
    # Verbosity only. `-v` was allowed and `-q` was not, which is an arbitrary
    # gap rather than a control: neither changes WHICH tests run or whether a
    # failure is reported — unittest exits non-zero either way, and the
    # dispatcher reads the exit code. Observed live 2026-08-03: TASK-102-S2
    # (the parity-corpus mission task) declared `-q` and was refused 87 times
    # at the pre-invoke gate.
    if rest in ([], ["-v"], ["-q"]):
        return "accept"
    raise CommandPolicyError(f"unittest args not allowed: {rest!r}")


def _v_ruff(argv, entry, context):
    if argv[:2] != ["ruff", "check"]:
        return "no-match"
    rest = list(argv[2:])
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--select", "--exclude"):
            if i + 1 >= len(rest):
                raise CommandPolicyError(f"ruff {a} missing its value")
            if a == "--exclude" and not _SAFE_PATH(rest[i + 1]):
                raise CommandPolicyError(
                    f"ruff --exclude path escapes worktree: {rest[i+1]!r}")
            i += 2
            continue
        if a == "--fix":
            # writes the tree: prepass-only (packet schema names it there)
            if context != "prepass":
                raise CommandPolicyError(
                    "ruff --fix is prepass-only, not a required check")
            i += 1
            continue
        if a.startswith("-"):
            raise CommandPolicyError(f"ruff flag not allowlisted: {a!r}")
        if not _SAFE_PATH(a):
            raise CommandPolicyError(f"ruff path escapes worktree: {a!r}")
        i += 1
    return "accept"


def _v_npm_run(argv, entry, context):
    if argv[:2] != ["npm", "--prefix"] or len(argv) < 3:
        return "no-match"
    if len(argv) != 5 or argv[3] != "run":
        raise CommandPolicyError(
            f"npm form must be exactly `npm --prefix <ws> run <script>`, "
            f"no extra args or -- passthrough: {argv!r}")
    ws, script = argv[2], argv[4]
    if ws not in entry.get("prefixes", []):
        return "no-match"
    if script not in entry.get("scripts", []):
        return "no-match"
    return "accept"


_GIT_RO = {"status", "diff", "log", "rev-parse", "ls-files", "merge-base"}
_GIT_ESCAPES = ("-c", "-C", "--git-dir", "--work-tree", "--exec-path",
                "--ext-diff", "--textconv")


def _v_git_readonly(argv, entry, context):
    if argv[:1] != ["git"]:
        return "no-match"
    if len(argv) < 2 or argv[1].startswith("-"):
        raise CommandPolicyError(
            "git global options before the subcommand are rejected "
            "(external-command escape hatches)")
    if argv[1] not in _GIT_RO:
        return "no-match"  # git push/fetch/... already hit the bans
    for a in argv[2:]:
        if a in _GIT_ESCAPES or any(
                a.startswith(e + "=") for e in _GIT_ESCAPES if e.startswith("--")):
            raise CommandPolicyError(f"git escape-hatch option rejected: {a!r}")
    return "accept"


_VALIDATORS = {
    "exact": _v_exact,
    "pytest": _v_pytest,
    "packets_validate": _v_packets_validate,
    "unittest_engine": _v_unittest_engine,
    "ruff": _v_ruff,
    "npm_run": _v_npm_run,
    "git_readonly": _v_git_readonly,
}


def check_policy(argv: list[str], policy: dict | None = None,
                 context: str = "checks") -> str:
    """Enforce the command policy on parsed argv, in `context`
    ("checks" | "prepass").

    Bans reject first (fast, defense in depth). Then the ratified allowlist:
    the command must be accepted by some entry whose `contexts` admits this
    context. Returns the mode stamped on the record — "allowlist", or
    "bans_only" when a policy carries no allowlist (the pre-ratification
    state, still used by permissive test policies). Raises
    CommandPolicyError otherwise, preferring an entry's own constraint
    reason over the generic not-in-allowlist.
    """
    pol = policy if policy is not None else load_command_policy()
    for ban in pol.get("banned") or []:
        ban = [str(b) for b in ban]
        if argv[: len(ban)] == ban:
            raise CommandPolicyError(
                f"banned command: {' '.join(ban)!r} (contract ban)")
    allow = pol.get("allowlist")
    if allow is None:
        return "bans_only"
    constraint_error: CommandPolicyError | None = None
    for entry in allow:
        if isinstance(entry, list):  # legacy argv-prefix form
            e = [str(x) for x in entry]
            if argv[: len(e)] == e:
                return "allowlist"
            continue
        validator = _VALIDATORS.get(entry.get("kind"))
        if validator is None:
            continue  # unknown kind in data: cannot accept, never rejects
        try:
            verdict = validator(argv, entry, context)
        except CommandPolicyError as e:
            constraint_error = constraint_error or e
            continue
        if verdict == "accept":
            if context not in (entry.get("contexts")
                               or ["checks", "prepass"]):
                constraint_error = constraint_error or CommandPolicyError(
                    f"entry {entry.get('entry')} is "
                    f"{'/'.join(entry.get('contexts') or [])}-only, not "
                    f"allowed in {context}")
                continue
            return "allowlist"
    if constraint_error is not None:
        raise constraint_error
    raise CommandPolicyError(
        f"command not in ratified allowlist: {argv[0]!r}")


def validate_packet_commands(packet: dict | None,
                             policy: dict | None = None) -> list[str]:
    """Pre-invoke validation: every packet command must parse and pass
    policy in its own context. Returns violation strings (empty = clean).
    A packet carrying a non-listed command fails BEFORE any model spend."""
    if not packet:
        return []
    violations: list[str] = []
    for field, context in (("required_checks", "checks"),
                           ("deterministic_prepass", "prepass")):
        for cmd in packet.get(field) or []:
            try:
                check_policy(parse_command(cmd), policy, context=context)
            except CommandPolicyError as e:
                violations.append(f"{field}: {cmd!r}: {e}")
    return violations


@dataclass
class CheckResult:
    cmd: str
    rc: int | None          # None: never ran (policy) or timed out
    duration_seconds: float
    timed_out: bool
    policy: str             # bans_only | allowlist | rejected:<reason>
    ok: bool


def run_commands(cmds: list[str], worktree: Path, *,
                 timeout: int = CHECK_TIMEOUT,
                 policy: dict | None = None,
                 context: str = "checks") -> list[CheckResult]:
    """Run packet commands the dispatcher owns, argv-exec, no shell.

    EVERY command runs even after a failure — the record should name
    everything wrong, not the first thing. The caller branches on rc; this
    runner never swallows one (the defect class CC-1 exists to kill).
    """
    results: list[CheckResult] = []
    for cmd in cmds or []:
        started = time.monotonic()
        try:
            argv = parse_command(cmd)
            mode = check_policy(argv, policy, context=context)
        except CommandPolicyError as e:
            results.append(CheckResult(cmd=cmd, rc=None, duration_seconds=0.0,
                                       timed_out=False,
                                       policy=f"rejected:{e}", ok=False))
            continue
        try:
            pr = subprocess.run(argv, cwd=worktree, capture_output=True,
                                text=True, timeout=timeout)
            results.append(CheckResult(
                cmd=cmd, rc=pr.returncode,
                duration_seconds=round(time.monotonic() - started, 3),
                timed_out=False, policy=mode, ok=pr.returncode == 0))
        except subprocess.TimeoutExpired:
            results.append(CheckResult(
                cmd=cmd, rc=None,
                duration_seconds=round(time.monotonic() - started, 3),
                timed_out=True, policy=mode, ok=False))
        except OSError as e:
            results.append(CheckResult(
                cmd=cmd, rc=None,
                duration_seconds=round(time.monotonic() - started, 3),
                timed_out=False, policy=f"{mode}:oserror:{e}", ok=False))
    return results


def checks_ok(results: list[CheckResult]) -> bool:
    return all(r.ok for r in results)


def checks_telemetry(results: list[CheckResult]) -> list[dict]:
    return [asdict(r) for r in results]


def failed_checks_reason(results: list[CheckResult]) -> str | None:
    bad = [r for r in results if not r.ok]
    if not bad:
        return None
    parts = []
    for r in bad:
        why = ("timeout" if r.timed_out
               else r.policy if r.policy.startswith("rejected")
               else f"rc={r.rc}")
        parts.append(f"{r.cmd!r} ({why})")
    return "required check failed: " + "; ".join(parts)


# ------------------------------------------------------------- provisioning

def provisioning_commands(packet: dict | None) -> list[list[str]]:
    """Derive the dispatcher-owned provisioning for a packet.

    Not expressible in the packet: derived from what its commands NEED. Any
    `npm --prefix <ws> ...` in required_checks/deterministic_prepass means
    workspace <ws> needs node_modules, which a fresh worktree does not have
    and the packet is (correctly) banned from installing.
    """
    if not packet:
        return []
    prefixes: list[str] = []
    for field in ("required_checks", "deterministic_prepass"):
        for cmd in packet.get(field) or []:
            try:
                argv = parse_command(cmd)
            except CommandPolicyError:
                continue  # the check runner will reject and record it
            if argv and argv[0] == "npm" and "--prefix" in argv:
                i = argv.index("--prefix")
                if i + 1 < len(argv) and argv[i + 1] not in prefixes:
                    prefixes.append(argv[i + 1])
    return [["npm", "ci", "--prefix", ws, "--prefer-offline"]
            for ws in prefixes]


def run_provisioning(packet: dict | None, worktree: Path, mailroom: Path,
                     *, timeout: int = PROVISION_TIMEOUT) -> list[dict]:
    """Run the provisioning prepass. Dispatcher-privileged: bypasses the
    packet command policy by construction (it is not a packet command), runs
    against the committed lockfile with a shared cache, and is timed and
    telemetered. Returns one record per command; rc != 0 means the caller
    must NOT invoke the model (the checks cannot execute)."""
    records: list[dict] = []
    cache = os.environ.get("NPM_CACHE_DIR") or str(
        Path(mailroom) / "cache" / "npm")
    for argv in provisioning_commands(packet):
        started = time.monotonic()
        env = dict(os.environ, npm_config_cache=cache)
        try:
            pr = subprocess.run(argv, cwd=worktree, env=env,
                                capture_output=True, text=True,
                                timeout=timeout)
            records.append({"cmd": " ".join(argv), "rc": pr.returncode,
                            "duration_seconds":
                                round(time.monotonic() - started, 3),
                            "stderr_tail": (pr.stderr or "")[-400:]})
        except (subprocess.TimeoutExpired, OSError) as e:
            records.append({"cmd": " ".join(argv), "rc": None,
                            "duration_seconds":
                                round(time.monotonic() - started, 3),
                            "stderr_tail": str(e)[-400:]})
    return records


def provisioning_ok(records: list[dict]) -> bool:
    return all(r.get("rc") == 0 for r in records)
