"""Frontend reviewer driver for PR #63 round 2 (head 7cddc04).

Executes the live server against the real pinned engine and checks the
behaviors the +126/-37 commit touches, plus the standing frontend covenant
checks (I2 card shape, I3 one-tap reversible assumptions, I5 degradation,
I6 latency gates). Prints a PASS/FAIL line per check; exits nonzero on any
failure.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:47791/api/v0"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} {detail}")
    if not ok:
        failures.append(name)


def post(path: str, body: dict) -> tuple[int, bytes]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def get(path: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(BASE + path) as resp:
        return resp.status, resp.read()


def main() -> int:
    from engine.parity_harness import load_cases

    _, cases = load_cases()
    build_xml = next(
        case.xml for case in cases if case.case_id == "12-elementalist-ci-cold-snap"
    ).decode()
    item_text = (ROOT / "engine" / "tests" / "fixtures" / "item.txt").read_text()

    schema = json.loads(
        (ROOT / "contracts" / "verdict.schema.json").read_text()
    )
    import jsonschema

    # --- /build: real import, latency gate, identity -----------------------
    started = time.perf_counter()
    status, raw = post("/build", {"pob_code": build_xml})
    import_ms = (time.perf_counter() - started) * 1000
    build = json.loads(raw)
    check("build.status", status == 200, f"status={status}")
    check(
        "build.import_latency",
        import_ms < 2000,
        f"{import_ms:.3f} ms (gate <2000)",
    )
    check(
        "build.identity",
        build.get("character_class") == "Witch"
        and build.get("ascendancy") == "Elementalist"
        and build.get("level") == 97
        and "Cold Snap" in build.get("main_skill", {}).get("name", ""),
        f"identity={build.get('character_class')}/{build.get('ascendancy')}/"
        f"{build.get('level')}/{build.get('main_skill', {}).get('name')}",
    )

    status, raw2 = get("/build")
    check(
        "build.warm_identity",
        status == 200 and json.loads(raw2) == build,
        "GET /build byte-stable identity",
    )

    # --- /diff determinism + latency, 100 independent samples --------------
    latencies = []
    cards = []
    for _ in range(100):
        started = time.perf_counter()
        status, raw = post("/diff", {"item_text": item_text})
        latencies.append((time.perf_counter() - started) * 1000)
        assert status == 200, f"diff status {status}: {raw!r}"
        cards.append(raw)
    p95 = sorted(latencies)[94]
    median = statistics.median(latencies)
    check(
        "diff.latency",
        p95 < 150,
        f"100-sample p95={p95:.3f} ms median={median:.3f} ms (gate <150)",
    )
    check(
        "diff.determinism",
        len(set(cards)) == 1,
        "byte-identical cards across 100 runs",
    )
    card = json.loads(cards[0])
    check("diff.verdict_word", card["verdict"] in {
        "UPGRADE", "SIDEGRADE", "DOWNGRADE", "CANT_EVALUATE"}, card["verdict"])

    jsonschema.validate(card, schema)
    check("diff.schema_valid", True, "card validates against verdict.schema.json")
    check(
        "i2.card_minimal",
        len(card["sentence"]) <= 140 and len(card["assumptions"]) <= 6,
        f"sentence={len(card['sentence'])} chars, "
        f"assumptions={len(card['assumptions'])}",
    )

    # --- materialization cache: A/B/A config switching ---------------------
    # Exercises _materialize_build re-materialization across config keys.
    status, raw_map = post("/diff", {"item_text": item_text, "preset": "mapping"})
    status, raw_boss = post("/diff", {"item_text": item_text, "preset": "bossing"})
    status, raw_map2 = post("/diff", {"item_text": item_text, "preset": "mapping"})
    check(
        "materialize.presets_differ",
        raw_map != raw_boss,
        "mapping vs bossing cards differ (config reaches engine)",
    )
    check(
        "materialize.cache_switch_stable",
        raw_map == raw_map2 and raw_map == cards[0],
        "A/B/A preset switching returns byte-identical mapping card",
    )

    # --- I3: one-tap reversible assumption override against real engine ----
    # The commit replaced the backend's own flask-override engine test with a
    # preset-difference test; this reviewer check covers the override path.
    flask_ids = [
        a["id"] for a in card["assumptions"] if a["id"] == "config.flasks_up"
    ]
    check("i3.flask_chip_present", bool(flask_ids), f"chip={flask_ids}")
    base_value = next(
        a["value"] for a in card["assumptions"] if a["id"] == "config.flasks_up"
    )
    status, raw_override = post(
        "/diff",
        {
            "item_text": item_text,
            "overrides": [
                {"assumption_id": "config.flasks_up", "value": not base_value}
            ],
        },
    )
    override_card = json.loads(raw_override)
    override_value = next(
        a["value"]
        for a in override_card["assumptions"]
        if a["id"] == "config.flasks_up"
    )
    check(
        "i3.override_applied",
        status == 200 and override_value == (not base_value),
        f"chip flips {base_value} -> {override_value}",
    )
    check(
        "i3.override_changes_card",
        override_card["diff_id"] != card["diff_id"]
        or override_card["verdict"] != card["verdict"]
        or override_card["offense_delta_pct"] != card["offense_delta_pct"]
        or override_card["defense_delta_pct"] != card["defense_delta_pct"],
        f"baseline=({card['verdict']},{card['offense_delta_pct']},"
        f"{card['defense_delta_pct']}) override=({override_card['verdict']},"
        f"{override_card['offense_delta_pct']},"
        f"{override_card['defense_delta_pct']})",
    )
    # Reversibility: flipping back restores the original card byte-for-byte.
    status, raw_back = post("/diff", {"item_text": item_text})
    check(
        "i3.override_reversible",
        raw_back == cards[0],
        "post-override default diff is byte-identical to baseline",
    )

    # --- I5: low-confidence degradation on a real trigger build ------------
    # Also exercises the commit's active-SkillSet fact extraction on a second
    # real export (CoC = cast-on-crit trigger setup).
    from server.assumptions import AssumptionsEvaluator
    from server.calculator import extract_build_facts

    coc_xml = next(
        case.xml for case in cases if case.case_id == "06-inquisitor-coc-ice-spear"
    )
    trigger_facts = extract_build_facts(coc_xml)
    check(
        "i5.trigger_detected",
        trigger_facts["has_trigger_setup"] is True,
        "extract_build_facts flags CoC trigger setup",
    )
    evaluator = AssumptionsEvaluator(ROOT / "assumptions")
    evaluation = evaluator.evaluate(trigger_facts, "mapping")
    check(
        "i5.trigger_degrades",
        evaluation.cant_evaluate and evaluation.confidence <= 0.5,
        f"cant_evaluate={evaluation.cant_evaluate} "
        f"confidence={evaluation.confidence}",
    )

    # --- error paths unchanged ----------------------------------------------
    status, _ = post("/build", {"account": "x", "character": "y"})
    check("errors.account_only_422", status == 422, f"status={status}")
    status, _ = post("/diff", {"item_text": ""})
    check("errors.empty_item_422", status == 422, f"status={status}")
    status, _ = post("/diff", {"item_text": item_text, "preset": "nope"})
    check("errors.bad_preset_422", status == 422, f"status={status}")

    if failures:
        print(f"REVIEWER CHECKS FAILED: {failures}")
        return 1
    print("ALL REVIEWER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    proc = subprocess.Popen(
        [sys.executable, "-m", "server"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(BASE + "/build", timeout=1)
                break
            except urllib.error.HTTPError:
                break  # server is up (404: no active build yet)
            except Exception:
                time.sleep(0.5)
        else:
            print("FAIL: server did not start")
            sys.exit(1)
        sys.exit(main())
    finally:
        proc.terminate()
        proc.wait(timeout=10)
