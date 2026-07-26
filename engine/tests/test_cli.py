import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = ROOT / "engine" / "pobcalc"
LOADER = importlib.machinery.SourceFileLoader("pobcalc_invoker", str(CLI))
CLI_SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
INVOKER = importlib.util.module_from_spec(CLI_SPEC)
LOADER.exec_module(INVOKER)
SPEC = importlib.util.spec_from_file_location(
    "preset_config", ROOT / "engine" / "preset_config.py"
)
PRESET_CONFIG = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(PRESET_CONFIG)


def runtime_is_available():
    runtime_root = pathlib.Path(
        os.environ.get("POBCALC_RUNTIME", ROOT / "engine" / ".runtime")
    )
    configured = os.environ.get("POBCALC_LUA") and os.environ.get(
        "POBCALC_LUA_CPATH"
    )
    bundled = (
        (runtime_root / "bin" / "luajit").is_file()
        and (runtime_root / "lib" / "lua" / "5.1" / "lua-utf8.so").is_file()
    )
    return configured or bundled


class PobcalcCliTest(unittest.TestCase):
    def test_server_starts_invoker_with_active_python(self):
        from server.calculator import PobCalculator

        with mock.patch("server.calculator.JsonRpcWorker") as worker_class:
            calculator = PobCalculator(ROOT)
            self.addCleanup(calculator.close)
            worker_class.assert_called_once_with(
                [sys.executable, str(CLI), "serve"],
                ROOT,
            )

    def test_runtime_artifacts_are_selected_by_platform(self):
        self.assertEqual(
            INVOKER._runtime_artifacts("linux"), ("luajit", "lua-utf8.so")
        )
        self.assertEqual(
            INVOKER._runtime_artifacts("win32"),
            ("luajit.exe", "lua-utf8.dll"),
        )

    def test_windows_runtime_discovery_uses_exe_without_execute_bit(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = pathlib.Path(temporary)
            binary = runtime / "bin" / "luajit.exe"
            library = runtime / "lib" / "lua" / "5.1" / "lua-utf8.dll"
            binary.parent.mkdir(parents=True)
            library.parent.mkdir(parents=True)
            binary.touch(mode=0o600)
            library.touch()
            self.assertEqual(
                INVOKER._find_lua(runtime, {}, "win32"), str(binary)
            )
            self.assertEqual(
                INVOKER._lua_cpath(runtime, {}, "win32"),
                f"{library.parent / '?.dll'};;",
            )

    def test_compiles_versioned_pob_translation(self):
        presets = PRESET_CONFIG.compile_presets(ROOT)
        self.assertEqual(
            presets["bossing"],
            {
                "conditionKilledRecently": False,
                "enemyIsBoss": "Pinnacle",
                "enemyLevel": 85,
                "multiplierNearbyEnemies": 1,
            },
        )
        self.assertEqual(
            presets["mapping"],
            {
                "buffOnslaught": False,
                "conditionKilledRecently": True,
                "enemyIsBoss": "None",
                "enemyLevel": 84,
                "multiplierNearbyEnemies": 8,
            },
        )

    def test_usage_rejects_incomplete_invocation(self):
        result = subprocess.run(
            [sys.executable, CLI, "diff", "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("usage:", result.stderr)

    def test_serve_rejects_extra_arguments(self):
        result = subprocess.run(
            [sys.executable, CLI, "serve", "unexpected"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("pobcalc serve", result.stderr)

    def test_output_is_byte_deterministic_when_runtime_is_available(self):
        if not runtime_is_available():
            self.skipTest("run engine/runtime/build.sh for integration test")

        fixture = ROOT / "engine" / "tests" / "fixtures"
        command = [
            sys.executable,
            CLI,
            "diff",
            "--build",
            ROOT
            / "engine"
            / "vendor"
            / "PathOfBuilding"
            / "spec"
            / "TestBuilds"
            / "3.13"
            / "OccVortex.xml",
            "--item",
            fixture / "item.txt",
            "--preset",
            "bossing",
            "--json",
        ]
        first = subprocess.run(command, cwd=ROOT, check=True, capture_output=True).stdout
        second = subprocess.run(command, cwd=ROOT, check=True, capture_output=True).stdout
        self.assertEqual(first, second)
        payload = json.loads(first)
        self.assertEqual(
            list(payload),
            ["baseline", "candidate", "deltas", "slot", "breakdown_ref"],
        )

    def test_warm_worker_reuses_build_without_changing_result(self):
        if not runtime_is_available():
            self.skipTest("run engine/runtime/build.sh for integration test")

        fixture = ROOT / "engine" / "tests" / "fixtures"
        request = {
            "jsonrpc": "2.0",
            "id": "same-input",
            "method": "diff",
            "params": {
                "build": str(
                    ROOT
                    / "engine"
                    / "vendor"
                    / "PathOfBuilding"
                    / "spec"
                    / "TestBuilds"
                    / "3.13"
                    / "OccVortex.xml"
                ),
                "item": str(fixture / "item.txt"),
                "preset": "bossing",
            },
        }
        worker = subprocess.Popen(
            [sys.executable, CLI, "serve"],
            cwd=ROOT,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.assertIsNotNone(worker.stdin)
            self.assertIsNotNone(worker.stdout)
            responses = []
            for _ in range(2):
                worker.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                worker.stdin.flush()
                responses.append(json.loads(worker.stdout.readline()))
            self.assertEqual(responses[0]["result"], responses[1]["result"])
        finally:
            if worker.stdin:
                worker.stdin.close()
            worker.wait(timeout=10)
            if worker.stdout:
                worker.stdout.close()
            if worker.stderr:
                worker.stderr.close()
