import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "timeless_cache", ROOT / "engine" / "timeless_cache.py"
)
CACHE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(CACHE)


class TimelessCacheTest(unittest.TestCase):
    def test_prepares_all_pinned_archives_without_touching_source(self):
        with tempfile.TemporaryDirectory(prefix="timeless-source-") as source_name:
            with tempfile.TemporaryDirectory(prefix="timeless-cache-") as cache_name:
                source = Path(source_name)
                expected = {}
                for jewel, archive_names in CACHE.JEWEL_ARCHIVES.items():
                    value = f"lookup:{jewel}".encode()
                    expected[jewel] = value
                    compressed = zlib.compress(value)
                    width = max(1, len(compressed) // len(archive_names))
                    offsets = [
                        index * width for index in range(len(archive_names))
                    ] + [len(compressed)]
                    for index, archive_name in enumerate(archive_names):
                        (source / archive_name).write_bytes(
                            compressed[offsets[index] : offsets[index + 1]]
                        )

                data_root = CACHE.prepare(source, Path(cache_name))
                manifest = json.loads(
                    (data_root / "manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(manifest["schema_version"], 1)
                for jewel, value in expected.items():
                    self.assertEqual(
                        (
                            data_root
                            / "Data"
                            / "TimelessJewelData"
                            / f"{jewel}.bin"
                        ).read_bytes(),
                        value,
                    )
                self.assertFalse(list(source.glob("*.bin")))
                self.assertEqual(CACHE.prepare(source, Path(cache_name)), data_root)


if __name__ == "__main__":
    unittest.main()
