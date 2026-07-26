#!/usr/bin/env python3
"""Prepare immutable PoB timeless-jewel lookup tables for the headless host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zlib


JEWEL_ARCHIVES = {
    "BrutalRestraint": ("BrutalRestraint.zip",),
    "ElegantHubris": ("ElegantHubris.zip",),
    "GloriousVanity": tuple(f"GloriousVanity.zip.part{part}" for part in range(5)),
    "HeroicTragedy": ("HeroicTragedy.zip",),
    "LethalPride": ("LethalPride.zip",),
    "MilitantFaith": ("MilitantFaith.zip",),
}


class CacheError(RuntimeError):
    """The pinned timeless-jewel data cannot be prepared safely."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(source: Path, cache: Path) -> Path:
    source = source.resolve()
    data_root = cache.resolve() / "timeless-data"
    output_root = data_root / "Data" / "TimelessJewelData"
    marker_path = data_root / "manifest.json"

    archive_payloads: dict[str, bytes] = {}
    inputs: dict[str, str] = {}
    for jewel, archive_names in JEWEL_ARCHIVES.items():
        parts = []
        for archive_name in archive_names:
            archive_path = source / archive_name
            try:
                archive = archive_path.read_bytes()
            except OSError as exc:
                raise CacheError(f"cannot read pinned archive {archive_path}: {exc}") from exc
            inputs[archive_name] = _sha256(archive)
            parts.append(archive)
        archive_payloads[jewel] = b"".join(parts)

    existing = None
    try:
        existing = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if (
        isinstance(existing, dict)
        and existing.get("schema_version") == 1
        and existing.get("inputs") == inputs
        and all(
            (output_root / f"{jewel}.bin").is_file()
            and (output_root / f"{jewel}.bin").stat().st_size
            == existing.get("outputs", {}).get(f"{jewel}.bin", {}).get("bytes")
            for jewel in JEWEL_ARCHIVES
        )
    ):
        return data_root

    outputs = {}
    for jewel, compressed in archive_payloads.items():
        try:
            expanded = zlib.decompress(compressed)
        except zlib.error as exc:
            raise CacheError(f"invalid pinned archive for {jewel}: {exc}") from exc
        output_name = f"{jewel}.bin"
        _atomic_write(output_root / output_name, expanded)
        outputs[output_name] = {
            "bytes": len(expanded),
            "sha256": _sha256(expanded),
        }

    marker = {
        "schema_version": 1,
        "inputs": inputs,
        "outputs": outputs,
    }
    _atomic_write(
        marker_path,
        (json.dumps(marker, sort_keys=True, indent=2) + "\n").encode(),
    )
    return data_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(prepare(args.source, args.cache))
    except CacheError as exc:
        parser.exit(69, f"timeless cache: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
