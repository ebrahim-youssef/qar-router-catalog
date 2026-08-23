from __future__ import annotations

import unittest
from pathlib import Path

from reciter_fetcher.catalog import build_catalog, serialize_catalog
from reciter_fetcher.curated import load_curated_reciters


ROOT = Path(__file__).resolve().parents[1]


class RepositoryCatalogTests(unittest.TestCase):
    def test_repository_markdown_builds_without_issues(self):
        reciters, parse_issues = load_curated_reciters(ROOT)
        catalog, catalog_issues = build_catalog(reciters)
        self.assertEqual([], parse_issues)
        self.assertEqual([], catalog_issues)
        self.assertEqual(261, len(catalog))

    def test_checked_in_catalog_is_deterministic_markdown_output(self):
        reciters, _ = load_curated_reciters(ROOT)
        catalog, _ = build_catalog(reciters)
        self.assertEqual(
            (ROOT / "data/curated/catalog.json").read_text(encoding="utf-8"),
            serialize_catalog(catalog),
        )
