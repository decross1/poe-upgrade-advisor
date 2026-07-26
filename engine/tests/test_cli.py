import json
import os
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = ROOT / "engine" / "pobcalc"


class PobcalcCliTest(unittest.TestCase):
    def test_usage_rejects_incomplete_invocation(self):
        result = subprocess.run(
            [CLI, "diff", "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("usage:", result.stderr)

    def test_serve_rejects_extra_arguments(self):
        result = subprocess.run(
            [CLI, "serve", "unexpected"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("pobcalc serve", result.stderr)

    def test_output_is_byte_deterministic_when_runtime_is_available(self):
        lua = os.environ.get("POBCALC_LUA")
        cpath = os.environ.get("POBCALC_LUA_CPATH")
        if not lua or not cpath:
            self.skipTest("set POBCALC_LUA and POBCALC_LUA_CPATH for integration test")

        fixture = ROOT / "engine" / "tests" / "fixtures"
        command = [
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
