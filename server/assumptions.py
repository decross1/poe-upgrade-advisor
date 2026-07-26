"""Data-driven evaluator for the rules under ``assumptions/``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Evaluation:
    main_skill: str
    main_skill_inferred: bool
    confidence: float
    cant_evaluate: bool
    reasons: tuple[str, ...]
    pob_config: Mapping[str, Any]
    assumptions: tuple[Mapping[str, Any], ...]


class AssumptionsEvaluator:
    """Evaluate build facts against versioned YAML rules.

    Build facts are deliberately calculator-neutral. The future PoB adapter only
    needs to expose fields used by ``when`` predicates plus ``active_skills``.
    """

    def __init__(self, assumptions_dir: Path | str) -> None:
        self.root = Path(assumptions_dir)
        self.confidence_rules = self._load("rules/confidence.yaml")
        self.config_rules = self._load("rules/config_inference.yaml")["rules"]
        self.main_skill_rules = self._load("rules/main_skill.yaml")["rules"]
        self.presets = {
            path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted((self.root / "presets").glob("*.yaml"))
        }

    def evaluate(
        self,
        build: Mapping[str, Any],
        preset: str,
        overrides: Sequence[Mapping[str, Any]] = (),
    ) -> Evaluation:
        if preset not in {"mapping", "bossing", "balanced"}:
            raise ValueError(f"unknown preset: {preset}")

        override_values = {
            item["assumption_id"]: item["value"]
            for item in overrides
            if isinstance(item, Mapping)
            and isinstance(item.get("assumption_id"), str)
            and "value" in item
        }
        config = deepcopy(self.presets.get(preset, {}).get("pob_config", {}))
        assumptions: list[dict[str, Any]] = []
        weights: list[float] = []
        reasons: list[str] = []

        main_skill, inferred, main_rule, main_weight = self._main_skill(
            build, override_values
        )
        weights.append(main_weight)
        assumptions.append(
            self._assumption(
                main_rule,
                override_values.get(main_rule["id"], main_skill),
                main_rule["chip_label"].format(skill=main_skill),
            )
        )

        for rule in self.config_rules:
            if not self._matches(rule["when"], build):
                continue
            value = next(iter(rule["set"].values()))
            value = override_values.get(rule["id"], value)
            config.update(
                {
                    key: override_values.get(rule["id"], configured)
                    for key, configured in rule["set"].items()
                }
            )
            weights.append(float(rule["confidence_weight"]))
            assumptions.append(self._assumption(rule, value, rule["chip_label"]))

        for rule in self.main_skill_rules:
            if rule.get("effect") != "reduce_confidence" or not self._matches(
                rule["when"], build
            ):
                continue
            override_value = override_values.get(rule["id"], True)
            assumptions.insert(
                0,
                self._assumption(rule, override_value, rule["chip_label"]),
            )
            if override_value is False:
                continue
            penalty = float(rule["confidence_weight"])
            weights = [max(0.0, weight + penalty) for weight in weights]
            reasons.append(
                f"{rule['id']}: trigger setup reduces skill-detection confidence"
            )

        confidence = round(min(weights, default=0.0), 2)
        floor = float(self.confidence_rules["cant_evaluate_below"])
        cant_evaluate = confidence < floor
        if cant_evaluate:
            reasons.append(
                f"aggregate confidence {confidence:.2f} below "
                f"cant_evaluate_below threshold {floor:.2f}"
            )

        return Evaluation(
            main_skill=main_skill,
            main_skill_inferred=inferred,
            confidence=confidence,
            cant_evaluate=cant_evaluate,
            reasons=tuple(reasons),
            pob_config=config,
            assumptions=tuple(assumptions[:6]),
        )

    def _main_skill(
        self,
        build: Mapping[str, Any],
        override_values: Mapping[str, Any],
    ) -> tuple[str, bool, Mapping[str, Any], float]:
        override = override_values.get(
            "main_skill.most_linked_highest_dps",
            override_values.get("main_skill.user_override", build.get("user_override")),
        )
        if isinstance(override, str) and override:
            rule = self.main_skill_rules[0]
            return override, False, rule, float(rule["confidence_weight"])

        rule = next(
            rule
            for rule in self.main_skill_rules
            if rule.get("set", {}).get("main_skill", "").startswith("$argmax")
        )
        skills = build.get("active_skills", ())
        candidates = [skill for skill in skills if isinstance(skill, Mapping)]
        winner = max(
            candidates,
            key=lambda skill: (skill.get("links", 0), skill.get("dps", 0)),
            default={"name": "Unknown"},
        )
        name = str(winner.get("name", "Unknown"))
        weight = float(rule["confidence_weight"]) if name != "Unknown" else 0.0
        return name, True, rule, weight

    @staticmethod
    def _matches(predicate: Mapping[str, Any], build: Mapping[str, Any]) -> bool:
        for key, expected in predicate.items():
            if key == "always":
                if not expected:
                    return False
            elif key == "user_override_exists":
                if bool(build.get("user_override")) is not bool(expected):
                    return False
            elif key == "any_skill_tag":
                tags = {
                    tag
                    for skill in build.get("active_skills", ())
                    if isinstance(skill, Mapping)
                    for tag in skill.get("tags", ())
                }
                if expected not in tags:
                    return False
            elif build.get(key) != expected:
                return False
        return True

    @staticmethod
    def _assumption(
        rule: Mapping[str, Any], value: Any, label: str
    ) -> dict[str, Any]:
        return {
            "id": rule["id"],
            "label": label,
            "value": value,
            "impactful": True,
            "reversible": True,
            "source_rule": rule["id"],
        }

    def _load(self, relative: str) -> Mapping[str, Any]:
        return yaml.safe_load((self.root / relative).read_text(encoding="utf-8"))
