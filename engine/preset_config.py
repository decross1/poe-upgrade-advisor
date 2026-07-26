#!/usr/bin/env python3
"""Compile canonical scenario presets into PoB configuration values."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


def compile_config(
    canonical_config: dict[str, object],
    translation: dict[str, object],
    source: str = "configuration",
) -> dict[str, object]:
    """Translate one evaluator ConfigSet into Path of Building input values."""
    enum_values: dict[object, object] = {}
    ambiguous: set[object] = set()
    for mapping in translation.get("enums", {}).values():
        for canonical, pob_value in mapping.items():
            if canonical in enum_values and enum_values[canonical] != pob_value:
                ambiguous.add(canonical)
            enum_values[canonical] = pob_value

    pob_config: dict[str, object] = {}
    for canonical_key, canonical_value in canonical_config.items():
        key_rule = translation.get("keys", {}).get(canonical_key)
        if key_rule:
            pob_key = key_rule["pob_key"]
            value_map = key_rule.get("map", {})
            if canonical_value not in value_map:
                raise ValueError(
                    f"{source}: missing mapping for "
                    f"{canonical_key}={canonical_value!r}"
                )
            pob_value = value_map[canonical_value]
        else:
            pob_key = canonical_key
            if canonical_value in ambiguous:
                raise ValueError(
                    f"{source}: ambiguous enum mapping for {canonical_value!r}"
                )
            pob_value = enum_values.get(canonical_value, canonical_value)

        if pob_key in pob_config:
            previous = pob_config[pob_key]
            if not isinstance(previous, (int, float)) or not isinstance(
                pob_value, (int, float)
            ):
                raise ValueError(f"{source}: non-numeric conflict for {pob_key}")
            pob_config[pob_key] = max(previous, pob_value)
        else:
            pob_config[pob_key] = pob_value
    return pob_config


def compile_presets(root: Path) -> dict[str, dict[str, object]]:
    translation = yaml.safe_load(
        (root / "assumptions" / "pob_translation.yaml").read_text()
    )

    compiled: dict[str, dict[str, object]] = {}
    for path in sorted((root / "assumptions" / "presets").glob("*.yaml")):
        preset = yaml.safe_load(path.read_text())
        compiled[path.stem] = compile_config(
            preset["pob_config"], translation, path.name
        )
    return compiled


if __name__ == "__main__":
    repository_root = Path(__file__).resolve().parent.parent
    try:
        translation = yaml.safe_load(
            (repository_root / "assumptions" / "pob_translation.yaml").read_text()
        )
        json.dump(
            {
                "translation_version": translation["translation_version"],
                "presets": compile_presets(repository_root),
            },
            sys.stdout,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"pobcalc: invalid preset translation: {error}", file=sys.stderr)
        raise SystemExit(65)
