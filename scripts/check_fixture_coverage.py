#!/usr/bin/env python3
"""Doctrine I8 (CI job: assumptions-fixtures): every rule file must be
referenced by >=1 fixture; every fixture must parse and name expectations."""
import sys
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
    for exp in doc["expected"]:
        covered.add(exp.get("rule_id"))

uncovered = rule_ids - covered
if uncovered:
    errors.append(f"I8 violated: rules with no fixture: {sorted(uncovered)}")

if errors:
    print("\n".join(errors)); sys.exit(1)
print(f"fixture coverage: OK ({len(rule_ids)} rules, all covered)")
