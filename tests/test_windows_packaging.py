"""Static contracts for TASK-209 lane C (issue #75): Windows packaging.

The PowerShell scripts are AUTHORED BLIND on this Linux dev box (same
precedent as packaging/run.bat, see packaging/test_launch.py): syntax and
cmd/pwsh semantics are verified here only statically. Real execution is the
`windows-package-cleanroom` job in .github/workflows/ci.yml — extract in a
fresh dir, run.bat, POST /build with a golden code, real build summary.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PS1 = ROOT / "scripts" / "package_mvp_windows.ps1"
CLEANROOM_PS1 = ROOT / "scripts" / "cleanroom_windows_check.ps1"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# Lane A's pinned runtime artifact (engine/tests/test_windows_runtime_build.py
# pins the same name against ci.yml — the two must never drift).
LANE_A_ARTIFACT = (
    "pobcalc-runtime-windows-x64-"
    "luajit-a471ab78c7b670b4f92dae111fc3c96fb824c768-"
    "luautf8-08b0fc930f5a52eff36348ed1ea39aadfc697fa6"
)


def test_windows_package_script_is_windows_only():
    script = PACKAGE_PS1.read_text(encoding="utf-8")
    # run.bat is THE entrypoint: staged at the zip root.
    assert 'packaging/run.bat' in script
    # No unix entrypoints are staged into the Windows zip (issue #75).
    assert "run.command" not in script
    assert "run.sh" not in script
    # Output is a zip named for Windows x86-64. ZipFile.CreateFromDirectory
    # (not Compress-Archive) so engine/.runtime dot-entries always ship.
    assert "CreateFromDirectory" in script
    assert "-windows-x64.zip" in script


def test_windows_package_script_wires_lane_a_runtime_layout():
    script = PACKAGE_PS1.read_text(encoding="utf-8")
    # The engine runtime dir expects exactly lane A's build-windows.ps1 layout.
    for required in ("luajit.exe", "lua51.dll", "lua-utf8.dll", "manifest"):
        assert required in script, f"runtime requirement lost: {required}"
    # Until lane A's artifact is wired: an explicit stub, so the launcher
    # fails honestly (I5) instead of mysteriously.
    assert "RUNTIME-STUB.txt" in script
    assert "-RuntimeDir" in script


def test_windows_package_script_stages_real_engine():
    """Same real-engine guarantee as the Linux tarball (I5): real PoB verdicts
    or an honest dead stop, never a fixture fallback."""
    script = PACKAGE_PS1.read_text(encoding="utf-8")
    for artifact in ("pobcalc", "pobcalc.lua", "preset_config.py", "timeless_cache.py"):
        assert artifact in script, f"engine piece lost: {artifact}"
    # TreeData GUI sprites excluded; headless lua libs still ship.
    for ext in (".png", ".jpg", ".webp"):
        assert f'"{ext}"' in script, f"TreeData sprite exclusion lost: {ext}"
    assert "runtime/lua" in script
    assert "TreeData" in script


def test_windows_cleanroom_asserts_real_build_summary():
    script = CLEANROOM_PS1.read_text(encoding="utf-8")
    # Extract in a fresh dir, launch through run.bat like a tester.
    assert "Expand-Archive" in script
    assert '"run.bat"' in script
    # POST /build with a golden corpus code, assert the real engine's summary.
    assert "/api/v0/build" in script
    assert "pob_code" in script
    assert "Vaal Cold Snap" in script
    # Golden input is host-side only (the app sees a plain HTTP body).
    assert "engine/corpus/seed/ninja/12-elementalist-ci-cold-snap.json" in script
    # Provenance: fixture path provably absent from the artifact.
    assert "contracts" in script


def test_windows_cleanroom_stub_mode_asserts_honest_failure():
    script = CLEANROOM_PS1.read_text(encoding="utf-8")
    # Pre-lane-A mode is a hard assertion of the honest failure, not a skip.
    assert "ExpectStubRuntime" in script
    assert "RUNTIME-STUB.txt" in script
    assert "engine could not start" in script


def test_run_bat_python_resolution_order():
    bat = (ROOT / "packaging" / "run.bat").read_bytes()
    assert bat, "run.bat missing"
    # cmd.exe misparses LF-only batch files that use labels/goto.
    assert b"\n" not in bat.replace(b"\r\n", b""), "run.bat must be CRLF-only"
    text = bat.decode("ascii")
    # py launcher first, python3 fallback, plain python last (TASK-209).
    assert text.index('set "PY=py -3"') < text.index('set "PY=python3"') < text.index('set "PY=python"')


def test_macos_packaging_is_gone():
    package_sh = (ROOT / "scripts" / "package_mvp.sh").read_text(encoding="utf-8")
    assert "run.command" not in package_sh
    cleanroom_sh = (ROOT / "scripts" / "cleanroom_real_engine_check.sh").read_text(
        encoding="utf-8"
    )
    # The Linux clean-room actively asserts run.command's absence.
    assert '[ ! -e "$APP/run.command" ]' in cleanroom_sh


def test_ci_has_windows_package_cleanroom_job():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "windows-package-cleanroom:" in workflow
    assert "runs-on: windows-latest" in workflow
    # Downloads lane A's pinned runtime artifact (by exact pinned name),
    # from main-branch runs only — real-mode assertions activate when lane A
    # LANDS (merged), not when a draft PR happens to publish an artifact.
    assert LANE_A_ARTIFACT in workflow
    assert 'head_branch -eq "main"' in workflow
    # ...builds the zip, clean-room checks it, and uploads the zip artifact.
    assert "./scripts/package_mvp_windows.ps1" in workflow
    assert "./scripts/cleanroom_windows_check.ps1" in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_worker_startup_io_failure_surfaces_as_worker_unavailable(tmp_path):
    """A startup I/O failure must surface as WorkerUnavailable — never a raw
    OSError and never a hang: launch.py keys the honest "engine could not
    start" dead stop (I5) off WorkerUnavailable, and a raw OSError escaping
    startup was misreported as a port-bind failure (real windows-latest run
    30210831928, WinError 10038).

    Rewritten against the reader-thread/queue worker (#83, which superseded
    the selector path this test used to simulate): a child that exits
    immediately gives the reader thread EOF, it enqueues b"", and the
    startup ping in JsonRpcWorker.__init__ raises WorkerUnavailable via the
    pipe-closed path. No selectors reference remains in the worker.
    """
    import sys

    import pytest

    import server.calculator as calculator

    with pytest.raises(calculator.WorkerUnavailable):
        calculator.JsonRpcWorker([sys.executable, "-c", "pass"], tmp_path)
