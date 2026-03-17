from __future__ import annotations

import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "core"))

from pipeline.kb_step import _find_existing_store  # noqa: E402


class TestKBStep(unittest.TestCase):
    def test_find_existing_store_reuses_by_name(self):
        stores = [
            {
                "id": "vs-old",
                "name": "lighting_kb",
                "status": "completed",
                "created_at": 100,
                "file_counts": {"total": 10},
                "metadata": {"kb_key": "lighting_kb", "kb_fingerprint": "old"},
            }
        ]

        existing = _find_existing_store(stores, vector_store_name="lighting_kb")

        self.assertIsNotNone(existing)
        self.assertEqual(existing["id"], "vs-old")

    def test_find_existing_store_prefers_populated_store_over_newer_empty_store(self):
        stores = [
            {
                "id": "vs-empty",
                "name": "lighting_kb",
                "status": "completed",
                "created_at": 200,
                "file_counts": {"total": 0},
            },
            {
                "id": "vs-full",
                "name": "lighting_kb",
                "status": "completed",
                "created_at": 100,
                "file_counts": {"total": 829},
            },
        ]

        existing = _find_existing_store(stores, vector_store_name="lighting_kb")

        self.assertIsNotNone(existing)
        self.assertEqual(existing["id"], "vs-full")

    def test_find_existing_store_ignores_other_names(self):
        stores = [
            {
                "id": "vs-other",
                "name": "other_kb",
                "status": "completed",
                "created_at": 100,
                "file_counts": {"total": 12},
            }
        ]

        existing = _find_existing_store(stores, vector_store_name="lighting_kb")

        self.assertIsNone(existing)


if __name__ == "__main__":
    unittest.main()
