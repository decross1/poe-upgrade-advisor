import pathlib
import re
import unittest

from engine.runtime_parity import SPOT_CHECK_CASE_IDS

ROOT = pathlib.Path(__file__).resolve().parents[2]
LINUX_BUILD = ROOT / "engine" / "runtime" / "build.sh"
WINDOWS_BUILD = ROOT / "engine" / "runtime" / "build-windows.ps1"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
NINJA_MANIFEST = ROOT / "engine" / "corpus" / "seed" / "ninja" / "manifest.json"


def revision(source, variable):
    match = re.search(
        rf'(?m)^{re.escape(variable)}\s*=\s*"?([0-9a-f]{{40}})"?$',
        source,
    )
    if not match:
        raise AssertionError(f"missing revision variable {variable}")
    return match.group(1)


class WindowsRuntimeBuildTest(unittest.TestCase):
    def test_windows_and_linux_source_revisions_match(self):
        linux = LINUX_BUILD.read_text()
        windows = WINDOWS_BUILD.read_text()

        linux_revisions = {
            "luajit": revision(linux, "readonly LUAJIT_REVISION"),
            "lua-utf8": revision(linux, "readonly LUAUTF8_REVISION"),
        }
        windows_revisions = {
            "luajit": revision(windows, "$LuaJitRevision"),
            "lua-utf8": revision(windows, "$LuaUtf8Revision"),
        }
        self.assertEqual(windows_revisions, linux_revisions)

    def test_windows_build_smoke_tests_the_staged_native_module(self):
        source = WINDOWS_BUILD.read_text()

        for artifact in ("luajit.exe", "lua51.dll", "lua-utf8.dll", "manifest"):
            self.assertIn(artifact, source)
        self.assertIn('"/DLUA_BUILD_AS_DLL"', source)
        self.assertIn('"-e", "require(\'lua-utf8\')"', source)

    def test_ci_builds_on_windows_and_publishes_runtime(self):
        workflow = CI_WORKFLOW.read_text()

        self.assertIn("windows-runtime-build:", workflow)
        self.assertIn("runs-on: windows-latest", workflow)
        self.assertIn("./engine/runtime/build-windows.ps1", workflow)
        self.assertIn(
            "copy /Y packaging\\run.bat run.bat",
            workflow,
        )
        self.assertIn(
            "call run.bat --runtime-check-only",
            workflow,
        )
        self.assertIn(
            "name: pobcalc-runtime-windows-x64-"
            "luajit-a471ab78c7b670b4f92dae111fc3c96fb824c768-"
            "luautf8-08b0fc930f5a52eff36348ed1ea39aadfc697fa6",
            workflow,
        )
        self.assertIn("path: engine/.runtime", workflow)
        self.assertIn("include-hidden-files: true", workflow)

    def test_parity_subset_has_three_builds_and_ci_or_low_life(self):
        import json

        manifest = json.loads(NINJA_MANIFEST.read_text())
        ci_or_low_life = set(
            manifest["selection"]["required_mechanics"]["ci_or_low_life"]
        )

        self.assertGreaterEqual(len(SPOT_CHECK_CASE_IDS), 3)
        self.assertEqual(len(SPOT_CHECK_CASE_IDS), len(set(SPOT_CHECK_CASE_IDS)))
        self.assertTrue(ci_or_low_life.intersection(SPOT_CHECK_CASE_IDS))

    def test_ci_requires_byte_identical_linux_and_windows_reports(self):
        workflow = CI_WORKFLOW.read_text()

        self.assertIn("name: runtime-parity-linux", workflow)
        self.assertIn("name: runtime-parity-windows", workflow)
        self.assertIn("runtime-parity-cross-platform:", workflow)
        self.assertIn(
            "needs: [engine-integration, windows-runtime-build]",
            workflow,
        )
        self.assertIn(
            "runtime-parity/linux/runtime-parity-spot-check.json",
            workflow,
        )
        self.assertIn(
            "runtime-parity/windows/runtime-parity-spot-check.json",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
