#!/usr/bin/env python3
"""Doctrine invariant checker (CI job: doctrine-invariants).
Mechanically enforces the [CI] invariants in PRODUCT_DOCTRINE.md.
Extend this file ONLY via protected-change tasks."""
import json, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
errors = []

# I4 — at most 3 scenario presets
presets = list((ROOT / "assumptions" / "presets").glob("*.yaml"))
if len(presets) > 3:
    errors.append(f"I4 violated: {len(presets)} presets (max 3): {[p.name for p in presets]}")
allowed = {"mapping", "bossing", "balanced"}
for p in presets:
    if p.stem not in allowed:
        errors.append(f"I4 violated: preset '{p.stem}' not in {sorted(allowed)}")

# I2 — verdict schema stays tight
vs = json.loads((ROOT / "contracts" / "verdict.schema.json").read_text())
props = vs["properties"]
if vs.get("additionalProperties") is not False:
    errors.append("I2 violated: verdict schema must set additionalProperties=false")
if props["sentence"].get("maxLength", 10**9) > 140:
    errors.append("I2 violated: sentence maxLength > 140")
if props["assumptions"].get("maxItems", 10**9) > 6:
    errors.append("I2 violated: assumptions maxItems > 6")
if set(props["verdict"]["enum"]) != {"UPGRADE", "SIDEGRADE", "DOWNGRADE", "CANT_EVALUATE"}:
    errors.append("I2 violated: verdict enum changed")

# I1 — overlay contains no settings surface (heuristic; strengthen in TASK-203)
overlay_src = ROOT / "overlay" / "src"
if overlay_src.exists():
    banned = ["settings", "preferences", "configpanel", "optionsmenu"]
    for f in overlay_src.rglob("*"):
        if f.is_file() and f.suffix in {".ts", ".tsx", ".js", ".jsx", ".rs", ".vue", ".svelte"}:
            low = f.name.lower()
            if any(b in low for b in banned):
                errors.append(f"I1 violated: settings-like file in overlay: {f.relative_to(ROOT)}")

# I5 — confidence threshold must exist as data
conf = ROOT / "assumptions" / "rules" / "confidence.yaml"
if not conf.exists():
    errors.append("I5 violated: assumptions/rules/confidence.yaml missing")
else:
    c = yaml.safe_load(conf.read_text())
    if not (0 < c.get("cant_evaluate_below", 0) < 1):
        errors.append("I5 violated: cant_evaluate_below must be in (0,1)")

if errors:
    print("\n".join(errors)); sys.exit(1)
print("doctrine invariants: OK")
