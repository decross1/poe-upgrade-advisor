import json
import math
import os
import pathlib
import time
import unittest

from server.app import BASE_PATH, ApiApplication
from server.assumptions import AssumptionsEvaluator
from server.calculator import PobCalculator

ROOT = pathlib.Path(__file__).resolve().parents[2]


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


@unittest.skipUnless(
    runtime_is_available(), "run engine/runtime/build.sh for integration test"
)
class RealServerAdapterTest(unittest.TestCase):
    def setUp(self):
        self.calculator = PobCalculator(ROOT)
        self.app = ApiApplication(
            self.calculator,
            AssumptionsEvaluator(ROOT / "assumptions"),
        )

    def tearDown(self):
        self.calculator.close()

    def test_contract_card_comes_from_real_warm_engine(self):
        build_xml = (
            ROOT
            / "engine"
            / "vendor"
            / "PathOfBuilding"
            / "spec"
            / "TestBuilds"
            / "3.13"
            / "OccVortex.xml"
        ).read_text()
        started = time.perf_counter()
        status, build = self.app.dispatch(
            "POST", f"{BASE_PATH}/build", {"pob_code": build_xml}
        )
        import_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(status, 200)
        self.assertEqual(build["character_class"], "Witch")
        self.assertEqual(build["ascendancy"], "Occultist")
        self.assertEqual(build["level"], 99)
        self.assertEqual(build["main_skill"]["name"], "Vortex")
        self.assertLess(import_ms, 2000)

        item_text = (
            ROOT / "engine" / "tests" / "fixtures" / "item.txt"
        ).read_text()
        cards = []
        samples = []
        for _ in range(20):
            started = time.perf_counter()
            status, card = self.app.dispatch(
                "POST", f"{BASE_PATH}/diff", {"item_text": item_text}
            )
            samples.append((time.perf_counter() - started) * 1000)
            self.assertEqual(status, 200)
            cards.append(card)

        p95_ms = sorted(samples)[math.ceil(len(samples) * 0.95) - 1]
        self.assertLess(p95_ms, 150)
        self.assertTrue(all(card == cards[0] for card in cards))

        schema = json.loads(
            (ROOT / "contracts" / "verdict.schema.json").read_text()
        )
        allowed = set(schema["properties"])
        required = set(schema["required"])
        self.assertLessEqual(set(cards[0]), allowed)
        self.assertLessEqual(required, set(cards[0]))
        self.assertIn(
            cards[0]["verdict"],
            {"UPGRADE", "SIDEGRADE", "DOWNGRADE", "CANT_EVALUATE"},
        )
        self.assertLessEqual(len(cards[0]["sentence"]), 140)
        self.assertLessEqual(len(cards[0]["assumptions"]), 6)

    def test_evaluator_config_is_translated_before_worker_call(self):
        config, _ = self.calculator._compile_config(
            {
                "enemyIsBoss": "NONE",
                "enemyLevel": 84,
                "multiplierEnemyCount": "pack",
                "conditionNearEnemy": True,
                "flasks_active": False,
            }
        )
        self.assertEqual(
            config,
            {
                "enemyIsBoss": "None",
                "enemyLevel": 84,
                "multiplierNearbyEnemies": 8,
                "flasks_active": False,
            },
        )

        build_xml = (
            ROOT
            / "engine"
            / "vendor"
            / "PathOfBuilding"
            / "spec"
            / "TestBuilds"
            / "3.13"
            / "OccVortex.xml"
        ).read_text()
        imported = self.calculator.import_build(build_xml)
        evaluator = AssumptionsEvaluator(ROOT / "assumptions")
        enabled = evaluator.evaluate(imported.facts, "mapping")
        disabled = evaluator.evaluate(
            imported.facts,
            "mapping",
            [{"assumption_id": "config.flasks_up", "value": False}],
        )
        item_text = (
            ROOT / "engine" / "tests" / "fixtures" / "item.txt"
        ).read_text()
        enabled_diff = self.calculator.diff(item_text, enabled.pob_config)
        disabled_diff = self.calculator.diff(item_text, disabled.pob_config)
        self.assertNotEqual(
            enabled_diff.payload["baseline"],
            disabled_diff.payload["baseline"],
        )


if __name__ == "__main__":
    unittest.main()
