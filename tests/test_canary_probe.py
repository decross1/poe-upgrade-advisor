"""The canary's single required check must fail closed on every defect it guards.

scripts/check_canary_probe.py is the TASK-999-S1 required check (base
contract §16, ratified disposition R4). These tests pin its three
conditions and its read-only behaviour.
"""

import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "check_canary_probe.py"

spec = importlib.util.spec_from_file_location("check_canary_probe", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _probe(tmp_path, text):
    p = tmp_path / "canary-probe.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_missing_file_fails(tmp_path):
    assert mod.check(tmp_path / "absent.md") == 1


def test_empty_file_fails(tmp_path):
    assert mod.check(_probe(tmp_path, "")) == 1


def test_wrong_first_line_fails(tmp_path):
    assert mod.check(_probe(tmp_path, "# Wrong title\nbody\n")) == 1


def test_over_thirty_lines_fails(tmp_path):
    text = "# Canary probe\n" + "line\n" * 30  # 31 lines total
    assert mod.check(_probe(tmp_path, text)) == 1


def test_valid_probe_passes(tmp_path):
    assert mod.check(_probe(tmp_path, "# Canary probe\n\nself-describing body\n")) == 0


def test_exactly_thirty_lines_passes(tmp_path):
    text = "# Canary probe\n" + "line\n" * 29  # 30 lines total
    assert mod.check(_probe(tmp_path, text)) == 0


def test_check_writes_nothing(tmp_path):
    probe = _probe(tmp_path, "# Canary probe\nbody\n")
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    mod.check(probe)
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    assert before == after
