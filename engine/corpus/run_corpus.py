#!/usr/bin/env python3
"""Validate and execute independently captured PoB differential cases."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
BUILDS = ROOT / "builds"
REQUIRED_ARCHETYPES = {"mine", "trigger", "minion", "ci", "low-life"}


def load_cases():
    cases = []
    for directory in sorted(BUILDS.iterdir()):
        if not directory.is_dir():
            continue
        metadata_file = directory / "metadata.json"
        build_file = directory / "build.xml"
        if not metadata_file.is_file() or not build_file.is_file():
            raise ValueError(f"{directory.name}: build.xml and metadata.json are required")
        metadata = json.loads(metadata_file.read_text())
        if metadata.get("id") != directory.name:
            raise ValueError(f"{directory.name}: metadata id must match directory")
        ET.parse(build_file)
        cases.append((directory, metadata))
    if len(cases) != 25:
        raise ValueError(f"expected 25 builds, found {len(cases)}")
    present = {tag for _, case in cases for tag in case.get("archetypes", [])}
    missing = REQUIRED_ARCHETYPES - present
    if missing:
        raise ValueError(f"missing adversarial archetypes: {sorted(missing)}")
    return cases


def canonical_json(path):
    return json.dumps(json.loads(path.read_text()), sort_keys=True, separators=(",", ":"))


def run_case(directory, metadata, pobcalc):
    item = directory / metadata["candidate_item"]
    expected = directory / metadata["oracle"]["file"]
    if not item.is_file() or not expected.is_file():
        raise ValueError(f"{metadata['id']}: captured case files are missing")
    command = [
        pobcalc,
        "diff",
        "--build",
        str(directory / "build.xml"),
        "--item",
        str(item),
        "--preset",
        metadata["preset"],
        "--json",
    ]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    actual = json.dumps(json.loads(result.stdout), sort_keys=True, separators=(",", ":"))
    if actual != canonical_json(expected):
        raise AssertionError(f"{metadata['id']}: output differs from desktop oracle")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args()
    try:
        cases = load_cases()
        pending = [case["id"] for _, case in cases if case["oracle"]["status"] == "pending"]
        if pending and not args.allow_pending:
            raise ValueError(f"{len(pending)} cases await independent desktop oracle capture")
        pobcalc = os.environ.get("POBCALC", str(ROOT.parent / "pobcalc"))
        for directory, metadata in cases:
            if metadata["oracle"]["status"] == "captured":
                run_case(directory, metadata, pobcalc)
        print(f"validated {len(cases)} builds; captured={len(cases)-len(pending)} pending={len(pending)}")
        return 0
    except (ValueError, ET.ParseError, subprocess.CalledProcessError, AssertionError) as error:
        print(f"corpus failure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

