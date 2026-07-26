import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
LINUX_BUILD = ROOT / "engine" / "runtime" / "build.sh"
WINDOWS_BUILD = ROOT / "engine" / "runtime" / "build-windows.ps1"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


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
        self.assertIn("name: pobcalc-runtime-windows-x64", workflow)
        self.assertIn("path: engine/.runtime", workflow)


if __name__ == "__main__":
    unittest.main()
