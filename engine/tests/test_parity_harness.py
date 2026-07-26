import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "parity_harness", ROOT / "engine" / "parity_harness.py"
)
HARNESS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(HARNESS)


def runtime_is_available():
    runtime_root = Path(
        os.environ.get("POBCALC_RUNTIME", ROOT / "engine" / ".runtime")
    )
    return bool(
        (
            os.environ.get("POBCALC_LUA")
            and os.environ.get("POBCALC_LUA_CPATH")
        )
        or (
            (runtime_root / "bin" / "luajit").is_file()
            and (runtime_root / "lib" / "lua" / "5.1" / "lua-utf8.so").is_file()
        )
    )


class ParityHarnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.cases = HARNESS.load_cases()

    def test_loads_all_frozen_cases_and_player_stats(self):
        self.assertEqual(len(self.cases), 15)
        self.assertTrue(all(len(case.expected_stats) > 80 for case in self.cases))

    def test_corrupted_stat_self_test_fails_comparison(self):
        result = HARNESS.run_self_test(self.cases[0])
        self.assertEqual(
            result, {"corrupted_stat": "passed", "identity_mismatch": "passed"}
        )

    def test_corrupted_stat_is_the_cell_that_fails(self):
        case = self.cases[0]
        stat = sorted(case.expected_stats)[0]
        expected = str(float(case.expected_stats[stat]) + 1_000_000)
        cells, counts, _ = HARNESS.compare_stats(
            {stat: expected}, {stat: float(case.expected_stats[stat])}
        )
        self.assertEqual(len(cells), 1)
        self.assertEqual(counts["OVER"], 1)

    def test_json_export_identity_mismatch_aborts(self):
        case = self.cases[0]
        raw = copy.deepcopy(case.raw)
        raw["ascendancyClassName"] = "NotTheExportedAscendancy"
        with self.assertRaisesRegex(HARNESS.HarnessError, "identity mismatch"):
            HARNESS._validate_identity(raw, case.identity, case.case_id)

    def test_comparison_bands_and_extra_values(self):
        cells, counts, extras = HARNESS.compare_stats(
            {
                "Exact": "100.000",
                "Close": "100.000",
                "Pass": "100.000",
                "Fail": "100.000",
            },
            {
                "Exact": 100,
                "Close": 100.09,
                "Pass": 100.9,
                "Fail": 102,
                "Extra": 1,
            },
        )
        self.assertEqual(
            [cell["band"] for cell in cells],
            ["<=0.1%", "exact", "OVER", "<=1%"],
        )
        self.assertEqual(
            counts, {"exact": 1, "<=0.1%": 1, "<=1%": 1, "OVER": 1}
        )
        self.assertEqual(extras, ["Extra"])

    def test_stats_cli_recalculates_frozen_player_stats(self):
        if not runtime_is_available():
            self.skipTest("run engine/runtime/build.sh for integration test")
        case = self.cases[0]
        with tempfile.TemporaryDirectory(prefix="pob-stats-test-") as temporary:
            build = Path(temporary) / "build.xml"
            build.write_bytes(case.xml)
            result = subprocess.run(
                [
                    ROOT / "engine" / "pobcalc",
                    "stats",
                    "--build",
                    build,
                    "--json",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
        actual = json.loads(result.stdout)
        self.assertEqual(actual["identity"], case.identity)
        _, counts, _ = HARNESS.compare_stats(
            case.expected_stats, actual["player_stats"]
        )
        self.assertEqual(counts["OVER"], 0)


if __name__ == "__main__":
    unittest.main()
