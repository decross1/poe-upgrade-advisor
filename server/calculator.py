"""Narrow calculation boundary; TASK-202b replaces only the implementation."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


class Calculator(Protocol):
    def diff(
        self,
        item_text: str,
        preset: str | None,
        overrides: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]: ...


class FixtureNotFound(ValueError):
    pass


class FixtureCalculator:
    """Deterministic fake backed by the contract response oracle."""

    marker = re.compile(r"@fixture:([A-Za-z0-9_-]+)")

    def __init__(self, fixtures_dir: Path | str) -> None:
        self.fixtures = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(Path(fixtures_dir).glob("*.json"))
        }

    def diff(
        self,
        item_text: str,
        preset: str | None,
        overrides: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        match = self.marker.search(item_text)
        name = match.group(1) if match else "upgrade_mapping"
        if name not in self.fixtures:
            raise FixtureNotFound(name)
        card = deepcopy(self.fixtures[name])
        if preset is not None:
            card["preset"] = preset
        if overrides:
            for override in overrides:
                target = next(
                    (
                        assumption
                        for assumption in card["assumptions"]
                        if assumption["id"] == override.get("assumption_id")
                    ),
                    None,
                )
                if target is not None and "value" in override:
                    target["value"] = override["value"]
            encoded = json.dumps(
                list(overrides), sort_keys=True, separators=(",", ":")
            ).encode()
            card["diff_id"] = (
                f"{card['diff_id']}#ovr-{hashlib.sha256(encoded).hexdigest()[:12]}"
            )
        return card
