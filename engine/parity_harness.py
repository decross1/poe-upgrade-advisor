#!/usr/bin/env python3
"""Offline poe.ninja PlayerStat parity harness for ADR-0005."""

from __future__ import annotations

import argparse
import base64
import copy
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import NamedTuple
import xml.etree.ElementTree as ET
import zlib


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "engine" / "corpus" / "seed" / "ninja"
CLI = ROOT / "engine" / "pobcalc"
DEFAULT_REPORT = ROOT / "engine" / "reports" / "ninja-parity.json"
VERSION_SKEW_EVIDENCE = (
    "poe.ninja values reproduce exactly at upstream 961363511; pinned "
    "e0cc037d8 includes cost-efficiency ordering change 592c24073"
)
OVER_CLASSIFICATIONS = {
    (case_id, stat): {
        "kind": "PoB-version-skew",
        "evidence": VERSION_SKEW_EVIDENCE,
    }
    for case_id in (
        "11-guardian-dominating-blow",
        "15-guardian-absolution",
    )
    for stat in ("ManaCost", "ManaPerSecondCost")
}


class HarnessError(RuntimeError):
    """A corpus invariant or engine request failed."""


class CorpusCase(NamedTuple):
    case_id: str
    raw_path: Path
    raw: dict
    xml: bytes
    expected_stats: dict[str, str]
    identity: dict[str, object]
    config_sha256: str


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _decode_export(encoded: str) -> bytes:
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        return zlib.decompress(base64.urlsafe_b64decode(padded))
    except (ValueError, zlib.error) as exc:
        raise HarnessError(f"invalid pathOfBuildingExport: {exc}") from exc


def _active_config_sha256(root: ET.Element) -> str:
    config = root.find("Config")
    if config is None:
        raise HarnessError("export has no Config section")
    active_id = config.attrib.get("activeConfigSet", "1")
    active = next(
        (
            node
            for node in config.findall("ConfigSet")
            if node.attrib.get("id") == active_id
        ),
        None,
    )
    if active is None:
        raise HarnessError(f"active ConfigSet {active_id!r} is missing")
    return _sha256(ET.tostring(active, encoding="utf-8"))


def _export_data(xml: bytes) -> tuple[dict[str, object], dict[str, str], str]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise HarnessError(f"invalid export XML: {exc}") from exc
    if root.tag != "PathOfBuilding":
        raise HarnessError(f"unexpected export root: {root.tag}")
    build = root.find("Build")
    if build is None:
        raise HarnessError("export has no Build section")
    try:
        identity: dict[str, object] = {
            "base_class": build.attrib["className"],
            "ascendancy": build.attrib["ascendClassName"],
            "level": int(build.attrib["level"]),
        }
    except (KeyError, ValueError) as exc:
        raise HarnessError(f"invalid export identity: {exc}") from exc
    stats: dict[str, str] = {}
    for node in build.findall("PlayerStat"):
        name = node.attrib.get("stat")
        value = node.attrib.get("value")
        if not name or value is None:
            raise HarnessError("malformed PlayerStat in export")
        if name in stats:
            if stats[name] != value:
                raise HarnessError(f"conflicting duplicate PlayerStat in export: {name}")
            continue
        try:
            Decimal(value)
        except Exception as exc:
            raise HarnessError(f"non-numeric PlayerStat {name}: {value}") from exc
        stats[name] = value
    if not stats:
        raise HarnessError("export has no PlayerStat values")
    return identity, stats, _active_config_sha256(root)


def _validate_identity(
    raw: dict, export_identity: dict[str, object], case_id: str
) -> None:
    expected = {
        "base_class": raw.get("baseClass"),
        "ascendancy": raw.get("ascendancyClassName"),
        "level": raw.get("level"),
    }
    if expected != export_identity:
        raise HarnessError(
            f"{case_id}: JSON/export identity mismatch: "
            f"json={expected!r} export={export_identity!r}"
        )


def load_cases(corpus: Path = CORPUS) -> tuple[dict, list[CorpusCase]]:
    manifest = json.loads((corpus / "manifest.json").read_bytes())
    cases = []
    for entry in manifest["entries"]:
        case_id = entry["id"]
        raw_path = corpus / entry["files"]["raw_response"]
        raw_bytes = raw_path.read_bytes()
        if _sha256(raw_bytes) != entry["fetch"]["sha256"]:
            raise HarnessError(f"{case_id}: raw response hash mismatch")
        raw = json.loads(raw_bytes)
        encoded = raw.get("pathOfBuildingExport")
        if not isinstance(encoded, str):
            raise HarnessError(f"{case_id}: pathOfBuildingExport is missing")
        if _sha256(encoded.encode()) != entry["export"]["encoded_sha256"]:
            raise HarnessError(f"{case_id}: encoded export hash mismatch")
        xml = _decode_export(encoded)
        if _sha256(xml) != entry["parse"]["decoded_sha256"]:
            raise HarnessError(f"{case_id}: decoded export hash mismatch")
        identity, stats, config_sha256 = _export_data(xml)
        _validate_identity(raw, identity, case_id)
        cases.append(
            CorpusCase(
                case_id,
                raw_path,
                raw,
                xml,
                stats,
                identity,
                config_sha256,
            )
        )
    if len(cases) != manifest["selection"]["count"]:
        raise HarnessError("manifest selection count does not match entries")
    return manifest, cases


def _printed_half_ulp(value: str) -> Decimal:
    decimal_value = Decimal(value)
    return Decimal(5).scaleb(decimal_value.as_tuple().exponent - 1)


def compare_stats(
    expected: dict[str, str], actual: dict[str, object]
) -> tuple[list[dict], dict[str, int], list[str]]:
    cells = []
    counts = {"exact": 0, "<=0.1%": 0, "<=1%": 0, "OVER": 0}
    for name in sorted(expected):
        expected_text = expected[name]
        expected_value = Decimal(expected_text)
        actual_raw = actual.get(name)
        if actual_raw == "Infinity":
            actual_value = Decimal("Infinity")
        elif actual_raw == "-Infinity":
            actual_value = Decimal("-Infinity")
        elif isinstance(actual_raw, (int, float)) and math.isfinite(actual_raw):
            actual_value = Decimal(str(actual_raw))
        else:
            actual_value = None
        expected_report = (
            float(expected_value)
            if expected_value.is_finite()
            else "Infinity"
            if expected_value > 0
            else "-Infinity"
        )
        actual_report = (
            float(actual_value)
            if actual_value is not None and actual_value.is_finite()
            else str(actual_value)
            if actual_value is not None
            else None
        )
        if (
            not expected_value.is_finite()
            and actual_value is not None
            and actual_value == expected_value
        ):
            cell = {
                "stat": name,
                "expected": expected_report,
                "actual": actual_report,
                "absolute_delta": 0.0,
                "relative_delta": 0.0,
                "band": "exact",
            }
        elif actual_value is None or not actual_value.is_finite():
            cell = {
                "stat": name,
                "expected": expected_report,
                "actual": actual_report,
                "absolute_delta": None,
                "relative_delta": None,
                "band": "OVER",
            }
        else:
            delta = abs(actual_value - expected_value)
            if delta <= _printed_half_ulp(expected_text):
                band = "exact"
                relative = Decimal(0)
            elif expected_value == 0:
                band = "OVER"
                relative = None
            else:
                relative = delta / abs(expected_value)
                if relative <= Decimal("0.001"):
                    band = "<=0.1%"
                elif relative <= Decimal("0.01"):
                    band = "<=1%"
                else:
                    band = "OVER"
            cell = {
                "stat": name,
                "expected": expected_report,
                "actual": actual_report,
                "absolute_delta": float(delta),
                "relative_delta": None if relative is None else float(relative),
                "band": band,
            }
        counts[cell["band"]] += 1
        cells.append(cell)
    extras = sorted(set(actual) - set(expected))
    return cells, counts, extras


def classify_over_cells(case_id: str, cells: list[dict]) -> dict[str, int]:
    counts = {
        "our-bug": 0,
        "PoB-version-skew": 0,
        "documented-limitation": 0,
        "unclassified": 0,
    }
    for cell in cells:
        if cell["band"] != "OVER":
            continue
        classification = OVER_CLASSIFICATIONS.get((case_id, cell["stat"]))
        if classification is None:
            counts["unclassified"] += 1
        else:
            cell["classification"] = classification
            counts[classification["kind"]] += 1
    return counts


def run_self_test(case: CorpusCase) -> dict[str, str]:
    corrupted = dict(case.expected_stats)
    stat = sorted(corrupted)[0]
    corrupted[stat] = str(Decimal(corrupted[stat]) + Decimal("1000000"))
    _, counts, _ = compare_stats(
        {stat: corrupted[stat]}, {stat: float(case.expected_stats[stat])}
    )
    if counts["OVER"] == 0:
        raise HarnessError("corrupted-stat canary did not fail")

    mismatched = copy.deepcopy(case.raw)
    mismatched["level"] = int(mismatched["level"]) + 1
    try:
        _validate_identity(mismatched, case.identity, case.case_id)
    except HarnessError:
        pass
    else:
        raise HarnessError("JSON/export identity canary did not abort")
    return {"corrupted_stat": "passed", "identity_mismatch": "passed"}


class Worker:
    def __init__(self, locale: str = "C"):
        environment = os.environ.copy()
        environment["LC_ALL"] = locale
        self.process = subprocess.Popen(
            [sys.executable, CLI, "serve"],
            cwd=ROOT,
            env=environment,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.request_id = 0

    def stats(self, build: Path) -> tuple[dict, str]:
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "stats",
            "params": {"build": str(build)},
        }
        if self.process.stdin is None or self.process.stdout is None:
            raise HarnessError("engine worker pipes are unavailable")
        self.process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise HarnessError(f"engine worker exited early: {stderr}")
        response = json.loads(line)
        if "error" in response:
            raise HarnessError(f"engine request failed: {response['error']}")
        return response["result"], line

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        if self.process.returncode:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise HarnessError(
                f"engine worker exited with {self.process.returncode}: {stderr}"
            )
        if self.process.stdout:
            self.process.stdout.close()
        if self.process.stderr:
            self.process.stderr.close()

    def __enter__(self) -> Worker:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def _available_locales() -> list[str]:
    result = subprocess.run(
        ["locale", "-a"], check=True, text=True, capture_output=True
    )
    locales = result.stdout.splitlines()
    choices = []
    for preferred in ("C", "C.utf8", "C.UTF-8"):
        if preferred in locales and preferred not in choices:
            choices.append(preferred)
    if len(choices) < 2:
        choices.extend(locale for locale in locales if locale not in choices)
    if len(choices) < 2:
        raise HarnessError("two installed locales are required for determinism gate")
    return choices[:2]


def _assert_engine_identity(case: CorpusCase, actual: dict) -> None:
    if actual != case.identity:
        raise HarnessError(
            f"{case.case_id}: export/engine identity mismatch: "
            f"export={case.identity!r} engine={actual!r}"
        )


def run_harness(report_path: Path = DEFAULT_REPORT) -> dict:
    manifest, cases = load_cases()
    self_test = run_self_test(cases[0])
    case_files: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="pob-parity-") as temporary:
        temp = Path(temporary)
        for case in cases:
            path = temp / f"{case.case_id}.xml"
            path.write_bytes(case.xml)
            case_files[case.case_id] = path

        locales = _available_locales()
        reference_lines = []
        for locale in locales:
            with Worker(locale) as worker:
                locale_lines = []
                for _ in range(10):
                    actual, line = worker.stats(case_files[cases[0].case_id])
                    _assert_engine_identity(cases[0], actual["identity"])
                    locale_lines.append(line.split('"result":', 1)[1])
                if len(set(locale_lines)) != 1:
                    raise HarnessError(
                        f"engine output is not byte deterministic under {locale}"
                    )
                reference_lines.append(locale_lines[0])
        if len(set(reference_lines)) != 1:
            raise HarnessError("engine output differs between locales")

        results = []
        total_counts = {"exact": 0, "<=0.1%": 0, "<=1%": 0, "OVER": 0}
        classification_counts = {
            "our-bug": 0,
            "PoB-version-skew": 0,
            "documented-limitation": 0,
            "unclassified": 0,
        }
        latencies_ms = []
        imported_builds = 0
        worker = Worker("C")
        try:
            worker.stats(case_files[cases[0].case_id])
            for case in cases:
                started = time.perf_counter_ns()
                try:
                    actual, _ = worker.stats(case_files[case.case_id])
                    engine_error = None
                except HarnessError as exc:
                    actual = None
                    engine_error = str(exc)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                latencies_ms.append(elapsed_ms)
                if actual is None:
                    import_status = "engine_error"
                    engine_identity = None
                    cells, counts, extras = compare_stats(case.expected_stats, {})
                elif actual["identity"] != case.identity:
                    import_status = "engine_identity_mismatch"
                    engine_identity = actual["identity"]
                    engine_error = (
                        f"expected {case.identity!r}, got {engine_identity!r}"
                    )
                    cells, counts, extras = compare_stats(case.expected_stats, {})
                else:
                    import_status = "imported"
                    imported_builds += 1
                    engine_identity = actual["identity"]
                    cells, counts, extras = compare_stats(
                        case.expected_stats, actual["player_stats"]
                    )
                for band in total_counts:
                    total_counts[band] += counts[band]
                case_classifications = classify_over_cells(case.case_id, cells)
                for classification in classification_counts:
                    classification_counts[classification] += case_classifications[
                        classification
                    ]
                results.append(
                    {
                        "id": case.case_id,
                        "config_set_sha256": case.config_sha256,
                        "import_status": import_status,
                        "engine_identity": engine_identity,
                        "engine_error": engine_error,
                        "warm_latency_ms": round(elapsed_ms, 6),
                        "band_counts": counts,
                        "extra_engine_stats": extras,
                        "stats": cells,
                    }
                )
                if import_status != "imported":
                    worker.close()
                    worker = Worker("C")
                    worker.stats(case_files[cases[0].case_id])
        finally:
            worker.close()

    ordered_latencies = sorted(latencies_ms)
    p95_index = math.ceil(0.95 * len(ordered_latencies)) - 1
    build_import_p95_ms = ordered_latencies[p95_index]
    classification_gate_pass = (
        classification_counts["our-bug"] == 0
        and classification_counts["documented-limitation"] == 0
        and classification_counts["unclassified"] == 0
    )
    build_import_p95_pass = build_import_p95_ms < 2000
    report = {
        "schema_version": 1,
        "task": "TASK-101",
        "adr": "ADR-0005",
        "oracle": {
            "provider": "poe.ninja frozen character exports",
            "snapshot_version": manifest["source"]["version"],
            "build_count": len(cases),
            "expected_vector": "pathOfBuildingExport/Build/PlayerStat",
            "config_policy": "embedded active ConfigSet loaded verbatim; no product preset",
            "non_finite_policy": "signed infinity is serialized as a JSON string and compared exactly",
        },
        "self_test": self_test,
        "determinism": {
            "runs_per_locale": 10,
            "locales": locales,
            "byte_identical": True,
        },
        "summary": {
            "compared_cells": sum(total_counts.values()),
            "band_counts": total_counts,
            "imported_builds": imported_builds,
            "failed_imports": len(cases) - imported_builds,
            "build_import_p95_ms": round(build_import_p95_ms, 6),
            "build_import_p95_limit_ms": 2000,
            "build_import_p95_pass": build_import_p95_pass,
            "over_band_pass": total_counts["OVER"] == 0,
            "over_cell_classifications": classification_counts,
            "classification_gate_pass": classification_gate_pass,
            "go_gate_pass": classification_gate_pass and build_import_p95_pass,
        },
        "builds": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--self-test-only",
        action="store_true",
        help="run corpus-integrity and canary checks without starting PoB",
    )
    args = parser.parse_args()
    try:
        if args.self_test_only:
            _, cases = load_cases()
            print(json.dumps(run_self_test(cases[0]), sort_keys=True))
            return 0
        report = run_harness(args.report)
    except HarnessError as exc:
        print(f"parity-harness: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["go_gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
