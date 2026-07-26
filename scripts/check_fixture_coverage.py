#!/usr/bin/env python3
"""Validate Doctrine I8 fixture coverage and build provenance."""

import base64
import binascii
import json
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
rules_dir = ROOT / "assumptions" / "rules"
fix_dir = ROOT / "assumptions" / "fixtures"
errors = []

rule_ids = set()
for rf in rules_dir.glob("*.yaml"):
    doc = yaml.safe_load(rf.read_text()) or {}
    for r in doc.get("rules", []):
        if "id" not in r:
            errors.append(f"rule without id in {rf.name}")
        else:
            rule_ids.add(r["id"])

covered = set()
for ff in fix_dir.glob("*.yaml"):
    doc = yaml.safe_load(ff.read_text()) or {}
    if "build" not in doc or "expected" not in doc:
        errors.append(f"fixture {ff.name} missing build/expected")
        continue
    build = doc["build"]
    if not isinstance(build, str) or not build:
        errors.append(f"fixture {ff.name} has an invalid build")
        continue
    try:
        if "/" in build:
            build_path = (ROOT / build).resolve()
            build_path.relative_to(ROOT)
            raw_build = build_path.read_bytes()
            if build_path.suffix == ".json":
                response = json.loads(raw_build)
                encoded = response["pathOfBuildingExport"].encode()
                compressed = base64.urlsafe_b64decode(
                    encoded + b"=" * (-len(encoded) % 4)
                )
                raw_build = zlib.decompress(compressed)
        else:
            encoded = build.encode()
            compressed = base64.urlsafe_b64decode(
                encoded + b"=" * (-len(encoded) % 4)
            )
            try:
                raw_build = zlib.decompress(compressed)
            except zlib.error:
                raw_build = zlib.decompress(compressed, -zlib.MAX_WBITS)
        root = ET.fromstring(raw_build)
        if root.tag != "PathOfBuilding":
            raise ValueError("root element is not PathOfBuilding")
    except (
        KeyError,
        ValueError,
        OSError,
        UnicodeError,
        ET.ParseError,
        binascii.Error,
        zlib.error,
    ) as error:
        errors.append(f"fixture {ff.name} build is not a loadable PoB export: {error}")
        continue
    for exp in doc["expected"]:
        covered.add(exp.get("rule_id"))

uncovered = rule_ids - covered
if uncovered:
    errors.append(f"I8 violated: rules with no fixture: {sorted(uncovered)}")

if errors:
    print("\n".join(errors)); sys.exit(1)
print(f"fixture coverage: OK ({len(rule_ids)} rules, all covered)")
