#!/usr/bin/env python3
"""Compare a frozen PoB corpus spot-check across platform runtimes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from engine.parity_harness import CorpusCase, load_cases
from engine.timeless_cache import CacheError, prepare

ROOT = Path(__file__).resolve().parents[1]
POB_SOURCE = ROOT / "engine" / "vendor" / "PathOfBuilding" / "src"
SPOT_CHECK_CASE_IDS = (
    "05-ascendant-ci-support",
    "06-inquisitor-coc-ice-spear",
    "13-ascendant-icicle-mine",
)


class RuntimeParityError(RuntimeError):
    """A platform runtime cannot produce the parity spot-check."""


def _runtime_layout(runtime_root: Path) -> tuple[Path, str]:
    if sys.platform == "win32":
        return (
            runtime_root / "bin" / "luajit.exe",
            str(runtime_root / "lib" / "lua" / "5.1" / "?.dll") + ";;",
        )
    return (
        runtime_root / "bin" / "luajit",
        str(runtime_root / "lib" / "lua" / "5.1" / "?.so") + ";;",
    )


def _selected_cases() -> tuple[CorpusCase, ...]:
    _, cases = load_cases()
    by_id = {case.case_id: case for case in cases}
    missing = sorted(set(SPOT_CHECK_CASE_IDS) - set(by_id))
    if missing:
        raise RuntimeParityError(
            f"frozen parity corpus is missing selected cases: {', '.join(missing)}"
        )
    return tuple(by_id[case_id] for case_id in SPOT_CHECK_CASE_IDS)


def _preset_config() -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / "engine" / "preset_config.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeParityError(
            f"preset configuration failed with {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def _run_case(
    case: CorpusCase,
    build_path: Path,
    lua_binary: Path,
    lua_cpath: str,
    preset_config: str,
    data_root: Path,
) -> str:
    environment = os.environ.copy()
    runtime_lua = ROOT / "engine" / "vendor" / "PathOfBuilding" / "runtime" / "lua"
    environment["LUA_PATH"] = (
        f"{runtime_lua / '?.lua'};{runtime_lua / '?' / 'init.lua'};;"
    )
    environment["LUA_CPATH"] = lua_cpath
    environment["POBCALC_DATA_ROOT"] = str(data_root)
    result = subprocess.run(
        [
            str(lua_binary),
            str(ROOT / "engine" / "pobcalc.lua"),
            "--stats",
            str(build_path),
            "",
            preset_config,
        ],
        cwd=POB_SOURCE,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeParityError(
            f"{case.case_id}: runtime exited with {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    output = result.stdout.rstrip("\r\n")
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeParityError(
            f"{case.case_id}: runtime emitted invalid JSON: {exc}"
        ) from exc
    if parsed.get("identity") != case.identity:
        raise RuntimeParityError(
            f"{case.case_id}: runtime identity mismatch: "
            f"expected {case.identity!r}, got {parsed.get('identity')!r}"
        )
    if not isinstance(parsed.get("player_stats"), dict):
        raise RuntimeParityError(f"{case.case_id}: runtime omitted player_stats")
    return output


def run_spot_check(runtime_root: Path) -> dict[str, object]:
    runtime_root = runtime_root.resolve()
    lua_binary, lua_cpath = _runtime_layout(runtime_root)
    if not lua_binary.is_file():
        raise RuntimeParityError(f"runtime binary is missing: {lua_binary}")
    if not (POB_SOURCE / "HeadlessWrapper.lua").is_file():
        raise RuntimeParityError(
            "Path of Building is missing; initialize engine/vendor/PathOfBuilding"
        )
    module_pattern = Path(lua_cpath.removesuffix(";;").replace("?", "lua-utf8"))
    if not module_pattern.is_file():
        raise RuntimeParityError(f"lua-utf8 module is missing: {module_pattern}")

    try:
        data_root = prepare(
            POB_SOURCE / "Data" / "TimelessJewelData",
            runtime_root,
        )
    except CacheError as exc:
        raise RuntimeParityError(str(exc)) from exc

    preset_config = _preset_config()
    results = []
    with tempfile.TemporaryDirectory(prefix="pob-runtime-parity-") as temporary:
        temporary_root = Path(temporary)
        for case in _selected_cases():
            build_path = temporary_root / f"{case.case_id}.xml"
            build_path.write_bytes(case.xml)
            results.append(
                {
                    "id": case.case_id,
                    "result_json": _run_case(
                        case,
                        build_path,
                        lua_binary,
                        lua_cpath,
                        preset_config,
                        data_root,
                    ),
                }
            )
    return {
        "schema_version": 1,
        "case_ids": list(SPOT_CHECK_CASE_IDS),
        "results": results,
    }


def _encoded_report(report: dict[str, object]) -> bytes:
    return (
        json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        type=Path,
        default=Path(
            os.environ.get("POBCALC_RUNTIME", ROOT / "engine" / ".runtime")
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = _encoded_report(run_spot_check(args.runtime))
    except RuntimeParityError as exc:
        parser.exit(69, f"runtime parity: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(report)
    digest = hashlib.sha256(report).hexdigest()
    print(
        f"runtime parity: {len(SPOT_CHECK_CASE_IDS)} builds exact report "
        f"sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
