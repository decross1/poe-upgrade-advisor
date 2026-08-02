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


def check_policy(argv: list[str], policy: dict | None = None) -> str:
    """Enforce the command policy on parsed argv.

    Returns the policy mode stamped on the record: "bans_only" while the
    positive allowlist awaits ratification, "allowlist" once it is data.
    Raises CommandPolicyError on a banned or non-allowlisted command.
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
    for entry in allow:
        entry = [str(e) for e in entry]
        if argv[: len(entry)] == entry:
            return "allowlist"
    raise CommandPolicyError(
        f"command not in ratified allowlist: {argv[0]!r}")


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
                 policy: dict | None = None) -> list[CheckResult]:
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
            mode = check_policy(argv, policy)
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
