"""Persistent adapter from the local API to the real Path of Building worker."""

from __future__ import annotations

import atexit
import base64
import hashlib
import json
import selectors
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from engine.preset_config import compile_config

MAX_BUILD_BYTES = 10_000_000
IMPORT_BUDGET_SECONDS = 2.0
WORKER_START_SECONDS = 30.0
TREE_PLAN_BUDGET_SECONDS = 30.0


class CalculatorError(RuntimeError):
    """Base class for calculation failures safe to translate at the API edge."""


class BuildImportError(CalculatorError):
    pass


class ItemParseError(CalculatorError):
    pass


class WorkerUnavailable(CalculatorError):
    pass


@dataclass(frozen=True)
class ImportedBuild:
    build_id: str
    facts: Mapping[str, Any]


@dataclass(frozen=True)
class EngineDiff:
    payload: Mapping[str, Any]
    compute_ms: float


@dataclass(frozen=True)
class EngineTreePlan:
    suggestions: tuple[Mapping[str, Any], ...]
    compute_ms: float


class Calculator(Protocol):
    def import_build(self, pob_code: str) -> ImportedBuild: ...

    def configure_build(
        self, canonical_config: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    def diff(
        self, item_text: str, canonical_config: Mapping[str, Any]
    ) -> EngineDiff: ...

    def tree_suggestions(
        self, points: int, canonical_config: Mapping[str, Any]
    ) -> EngineTreePlan: ...

    def close(self) -> None: ...


class JsonRpcWorker:
    """One long-lived ``pobcalc serve`` process, serialized by request."""

    def __init__(self, command: list[str], cwd: Path) -> None:
        self.command = command
        self.cwd = cwd
        self._lock = threading.Lock()
        self._sequence = 0
        self._process: subprocess.Popen[bytes] | None = None
        self._start()
        self.call("ping", {}, WORKER_START_SECONDS)

    def _start(self) -> None:
        try:
            self._process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as error:
            raise WorkerUnavailable(f"unable to start pobcalc: {error}") from error

    def call(
        self, method: str, params: Mapping[str, Any], timeout: float
    ) -> Mapping[str, Any]:
        with self._lock:
            process = self._process
            if (
                process is None
                or process.poll() is not None
                or process.stdin is None
                or process.stdout is None
            ):
                raise WorkerUnavailable(self._failure_detail("pobcalc is not running"))

            self._sequence += 1
            request_id = f"server-{self._sequence}"
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
            encoded = (
                json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
                + b"\n"
            )
            try:
                process.stdin.write(encoded)
                process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                raise WorkerUnavailable(
                    self._failure_detail("pobcalc request pipe closed")
                ) from error

            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                if not selector.select(timeout):
                    raise WorkerUnavailable(
                        f"pobcalc {method} exceeded {timeout * 1000:.0f}ms budget"
                    )
                raw = process.stdout.readline()
            finally:
                selector.close()
            if not raw:
                raise WorkerUnavailable(
                    self._failure_detail("pobcalc closed its response pipe")
                )

            try:
                response = json.loads(raw)
            except json.JSONDecodeError as error:
                raise WorkerUnavailable("pobcalc emitted invalid JSON") from error
            if response.get("id") != request_id:
                raise WorkerUnavailable("pobcalc response id did not match request")
            if "error" in response:
                message = str(response["error"].get("message", "calculation failed"))
                raise CalculatorError(message)
            result = response.get("result")
            if not isinstance(result, Mapping):
                raise WorkerUnavailable("pobcalc result was not an object")
            return result

    def _failure_detail(self, prefix: str) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return prefix
        detail = b""
        if process.poll() is not None:
            detail = process.stderr.read()
        if detail:
            return f"{prefix}: {detail.decode(errors='replace').strip()}"
        return prefix

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is None or process.poll() is not None:
                return
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


class PobCalculator:
    """Real calculator with one imported-build session and a warm PoB worker."""

    def __init__(
        self,
        root: Path | str,
        worker: JsonRpcWorker | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.translation = yaml.safe_load(
            (self.root / "assumptions" / "pob_translation.yaml").read_text(
                encoding="utf-8"
            )
        )
        if self.translation.get("translation_version") != 1:
            raise WorkerUnavailable("only pob_translation.yaml v1 is supported")
        self._temporary = tempfile.TemporaryDirectory(prefix="poe-advisor-session-")
        session_root = Path(self._temporary.name)
        self._build_path = session_root / "build.xml"
        self._item_path = session_root / "candidate.item.txt"
        self._active: ImportedBuild | None = None
        self._original_xml: bytes | None = None
        self._materialized_config_key: str | None = None
        self._lock = threading.RLock()
        self.worker = worker or JsonRpcWorker(
            [str(self.root / "engine" / "pobcalc"), "serve"], self.root
        )
        atexit.register(self.close)

    def import_build(self, pob_code: str) -> ImportedBuild:
        xml = decode_pob_code(pob_code)
        facts = extract_build_facts(xml)
        digest = hashlib.sha256(xml).hexdigest()
        imported = ImportedBuild(build_id=f"b-{digest[:12]}", facts=facts)
        with self._lock:
            self._active = imported
            self._original_xml = xml
            self._materialized_config_key = None
        return imported

    def configure_build(
        self, canonical_config: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        with self._lock:
            self._require_active()
            config, config_key = self._compile_config(canonical_config)
            self._materialize_build(config, config_key)
            started = time.perf_counter()
            try:
                result = self.worker.call(
                    "load",
                    {
                        "build": str(self._build_path),
                        "config": config,
                        "config_key": config_key,
                    },
                    IMPORT_BUDGET_SECONDS,
                )
            except CalculatorError as error:
                raise BuildImportError(str(error)) from error
            elapsed = time.perf_counter() - started
            if elapsed >= IMPORT_BUDGET_SECONDS:
                raise BuildImportError("Path of Building import exceeded 2000ms budget")
            identity = result.get("identity")
            if (
                not isinstance(identity, Mapping)
                or not isinstance(identity.get("base_class"), str)
                or not isinstance(identity.get("level"), (int, float))
            ):
                raise BuildImportError(
                    "Path of Building returned invalid build identity"
                )
            return identity

    def diff(
        self, item_text: str, canonical_config: Mapping[str, Any]
    ) -> EngineDiff:
        with self._lock:
            self._require_active()
            config, config_key = self._compile_config(canonical_config)
            self._materialize_build(config, config_key)
            self._item_path.write_text(item_text, encoding="utf-8")
            started = time.perf_counter()
            try:
                payload = self.worker.call(
                    "diff",
                    {
                        "build": str(self._build_path),
                        "item": str(self._item_path),
                        "config": config,
                        "config_key": config_key,
                    },
                    IMPORT_BUDGET_SECONDS,
                )
            except WorkerUnavailable:
                raise
            except CalculatorError as error:
                raise ItemParseError(str(error)) from error
            compute_ms = (time.perf_counter() - started) * 1000
            _validate_engine_diff(payload)
            return EngineDiff(payload=payload, compute_ms=compute_ms)

    def tree_suggestions(
        self, points: int, canonical_config: Mapping[str, Any]
    ) -> EngineTreePlan:
        if (
            not isinstance(points, int)
            or isinstance(points, bool)
            or not 1 <= points <= 10
        ):
            raise CalculatorError("tree plan points must be an integer from 1 to 10")
        with self._lock:
            self._require_active()
            config, config_key = self._compile_config(canonical_config)
            self._materialize_build(config, config_key)
            started = time.perf_counter()
            payload = self.worker.call(
                "tree_suggestions",
                {
                    "build": str(self._build_path),
                    "config": config,
                    "config_key": config_key,
                    "points": points,
                },
                TREE_PLAN_BUDGET_SECONDS,
            )
            compute_ms = (time.perf_counter() - started) * 1000
            suggestions = _validate_tree_suggestions(payload)
            if sum(item["path_cost"] for item in suggestions) > points:
                raise CalculatorError(
                    "Path of Building tree plan exceeded the requested point budget"
                )
            return EngineTreePlan(
                suggestions=tuple(suggestions),
                compute_ms=compute_ms,
            )

    def _compile_config(
        self, canonical_config: Mapping[str, Any]
    ) -> tuple[dict[str, object], str]:
        try:
            config = compile_config(
                dict(canonical_config), self.translation, "assumptions evaluator"
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CalculatorError(f"invalid evaluator ConfigSet: {error}") from error
        encoded = json.dumps(config, sort_keys=True, separators=(",", ":"))
        return config, hashlib.sha256(encoded.encode()).hexdigest()

    def _materialize_build(
        self, config: Mapping[str, object], config_key: str
    ) -> None:
        if self._materialized_config_key == config_key:
            return
        if self._original_xml is None:
            raise BuildImportError("no active build XML")
        self._build_path.write_bytes(
            materialize_config_set(self._original_xml, config)
        )
        self._materialized_config_key = config_key

    def _require_active(self) -> ImportedBuild:
        if self._active is None:
            raise BuildImportError("no active build")
        return self._active

    def close(self) -> None:
        self.worker.close()
        self._temporary.cleanup()


def decode_pob_code(value: str) -> bytes:
    """Accept raw PoB XML or the usual zlib/base64 Path of Building code."""
    if not isinstance(value, str) or not value.strip():
        raise BuildImportError("empty Path of Building code")
    raw = value.strip().encode()
    if len(raw) > MAX_BUILD_BYTES:
        raise BuildImportError("Path of Building code is too large")
    if raw.startswith((b"<?xml", b"<PathOfBuilding")):
        xml = raw
    else:
        try:
            padded = raw + b"=" * (-len(raw) % 4)
            compressed = base64.urlsafe_b64decode(padded)
            try:
                xml = zlib.decompress(compressed)
            except zlib.error:
                xml = zlib.decompress(compressed, -zlib.MAX_WBITS)
        except (ValueError, zlib.error) as error:
            raise BuildImportError("unparseable Path of Building code") from error
    if len(xml) > MAX_BUILD_BYTES:
        raise BuildImportError("decoded Path of Building XML is too large")
    return xml.strip()


def extract_build_facts(xml: bytes) -> dict[str, Any]:
    """Extract conservative, calculator-neutral facts from a PoB export."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise BuildImportError("unparseable Path of Building XML") from error
    if root.tag != "PathOfBuilding":
        raise BuildImportError("XML is not a Path of Building export")
    build = root.find("Build")
    if build is None:
        raise BuildImportError("Path of Building export has no Build section")

    try:
        main_group = int(
            build.attrib.get(
                "mainSocketGroup", build.attrib.get("mainSkillIndex", "1")
            )
        )
    except ValueError:
        main_group = 1

    active_skills: list[dict[str, Any]] = []
    has_trigger = False
    has_power_generation = False
    skills = root.find("Skills")
    skill_groups: list[ET.Element] = []
    if skills is not None:
        active_set_id = skills.attrib.get("activeSkillSet", "1")
        active_set = next(
            (
                node
                for node in skills.findall("SkillSet")
                if node.attrib.get("id") == active_set_id
            ),
            None,
        )
        skill_groups = (
            active_set.findall("Skill")
            if active_set is not None
            else skills.findall("Skill")
        )
    for group_index, group in enumerate(skill_groups, start=1):
        if group.attrib.get("enabled", "true").lower() == "false":
            continue
        enabled_gems = [
            gem
            for gem in group.findall("Gem")
            if gem.attrib.get("enabled", "true").lower() != "false"
        ]
        active_gems = [
            gem
            for gem in enabled_gems
            if "SupportGem" not in gem.attrib.get("gemId", "")
            and not gem.attrib.get("skillId", "").startswith("Support")
        ]
        support_names = [
            gem.attrib.get("nameSpec", "") for gem in enabled_gems if gem not in active_gems
        ]
        lowered_supports = " ".join(support_names).lower()
        has_trigger = has_trigger or any(
            marker in lowered_supports
            for marker in ("cast on ", "cast when ", "trigger")
        )
        has_power_generation = has_power_generation or (
            "power charge on critical" in lowered_supports
        )
        try:
            selected = int(group.attrib.get("mainActiveSkill", "1"))
        except ValueError:
            selected = 1
        for active_index, gem in enumerate(active_gems, start=1):
            name = gem.attrib.get("nameSpec") or gem.attrib.get("skillId") or "Unknown"
            active_skills.append(
                {
                    "name": name,
                    "links": len(enabled_gems),
                    "dps": (
                        1
                        if group_index == main_group and active_index == selected
                        else 0
                    ),
                    "tags": _conservative_skill_tags(name),
                }
            )

    return {
        "active_skills": active_skills,
        "allocated_keystone": None,
        "has_charge_generation": "power" if has_power_generation else None,
        "has_trigger_setup": has_trigger,
    }


def materialize_config_set(
    xml: bytes, config: Mapping[str, object]
) -> bytes:
    """Write translated evaluator values into the export before PoB imports it.

    PoB calculates once during import. Materializing the active ConfigSet lets
    the worker reuse that calculation instead of recalculating after import.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise BuildImportError("unparseable Path of Building XML") from error
    config_root = root.find("Config")
    if config_root is None:
        config_root = ET.SubElement(root, "Config")
    active_id = config_root.attrib.get("activeConfigSet", "1")
    config_set = next(
        (
            node
            for node in config_root.findall("ConfigSet")
            if node.attrib.get("id") == active_id
        ),
        None,
    )
    target = config_set if config_set is not None else config_root

    for key, value in sorted(config.items()):
        if key == "flasks_active":
            if not isinstance(value, bool):
                raise CalculatorError("flasks_active must be boolean")
            for slot in root.findall(".//Slot"):
                if slot.attrib.get("name", "").startswith("Flask "):
                    slot.attrib["active"] = "true" if value is True else "false"
            continue
        matching = [
            node
            for node in target.findall("Input")
            if node.attrib.get("name") == key
        ]
        node = matching[0] if matching else ET.SubElement(target, "Input")
        for duplicate in matching[1:]:
            target.remove(duplicate)
        node.attrib.clear()
        node.attrib["name"] = key
        if isinstance(value, bool):
            node.attrib["boolean"] = "true" if value else "false"
        elif isinstance(value, (int, float)):
            node.attrib["number"] = str(value)
        elif isinstance(value, str):
            node.attrib["string"] = value
        else:
            raise CalculatorError(
                f"unsupported ConfigSet value for {key}: {type(value).__name__}"
            )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _conservative_skill_tags(name: str) -> list[str]:
    lowered = name.lower()
    tags = []
    if any(marker in lowered for marker in ("chill", "cold snap", "vortex")):
        tags.append("chill")
    if "shock" in lowered:
        tags.append("shock")
    return tags


def _validate_engine_diff(payload: Mapping[str, Any]) -> None:
    for section in ("baseline", "candidate", "deltas"):
        metrics = payload.get(section)
        if not isinstance(metrics, Mapping):
            raise ItemParseError(f"Path of Building omitted {section} metrics")
        for key in ("total_dps", "ehp"):
            if not isinstance(metrics.get(key), (int, float)):
                raise ItemParseError(
                    f"Path of Building returned non-numeric {section}.{key}"
                )
    if not isinstance(payload.get("slot"), str):
        raise ItemParseError("Path of Building omitted the comparison slot")


def _validate_tree_suggestions(
    payload: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    suggestions = payload.get("suggestions")
    if not isinstance(suggestions, list):
        raise CalculatorError("Path of Building omitted tree suggestions")
    validated: list[Mapping[str, Any]] = []
    expected_step = 1
    for suggestion in suggestions:
        if not isinstance(suggestion, Mapping):
            raise CalculatorError("Path of Building returned an invalid suggestion")
        if suggestion.get("step") != expected_step:
            raise CalculatorError(
                "Path of Building returned non-sequential suggestion steps"
            )
        if not isinstance(suggestion.get("node_id"), int) or isinstance(
            suggestion.get("node_id"), bool
        ):
            raise CalculatorError("Path of Building returned an invalid node id")
        if not isinstance(suggestion.get("node_name"), str):
            raise CalculatorError("Path of Building returned an invalid node name")
        for field in (
            "offense_delta_pct",
            "defense_delta_pct",
            "combined_score",
        ):
            if not isinstance(suggestion.get(field), (int, float)) or isinstance(
                suggestion.get(field), bool
            ):
                raise CalculatorError(
                    f"Path of Building returned a non-numeric {field}"
                )
        path_cost = suggestion.get("path_cost")
        path_node_ids = suggestion.get("path_node_ids")
        if (
            not isinstance(path_cost, int)
            or isinstance(path_cost, bool)
            or path_cost < 1
            or not isinstance(path_node_ids, list)
            or len(path_node_ids) != path_cost
            or any(
                not isinstance(node_id, int) or isinstance(node_id, bool)
                for node_id in path_node_ids
            )
            or path_node_ids[-1] != suggestion["node_id"]
        ):
            raise CalculatorError("Path of Building returned an invalid node path")
        validated.append(dict(suggestion))
        expected_step += 1
    return validated
