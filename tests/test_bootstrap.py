from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from reciter_fetcher.catalog import build_catalog
from reciter_fetcher.bootstrap import compare_catalogs
from reciter_fetcher.bootstrap_cli import main as bootstrap_main
from reciter_fetcher.curated import load_curated_reciters


def qfa_markdown(
    *,
    slug_name: str | None = "Example Reciter",
    arabic_name: str | None = "قارئ المثال",
    riwaya: str | None = None,
    catalog_style: str | None = None,
    trailing_comma: bool = False,
) -> str:
    if slug_name is None and arabic_name is None:
        name_block = ""
    else:
        name_lines = ["#name"]
        if slug_name is not None:
            name_lines.append(f"en:{slug_name}")
        if arabic_name is not None:
            name_lines.append(f"ar:{arabic_name}")
        name_block = "\n".join(name_lines) + "\n\n"
    curated = ""
    if riwaya is not None:
        curated += f',\n  "riwaya": {json.dumps(riwaya, ensure_ascii=False)}'
    if catalog_style is not None:
        curated += f',\n  "catalog_style": {json.dumps(catalog_style, ensure_ascii=False)}'
    raw_separator = "," if trailing_comma and not curated else ""
    return f'''{name_block}# QFS

# QFA
{{
  "id": 7,
  "reciter_name": "Example Reciter",
  "style": null{raw_separator}{curated}
}}

# MP3

# EA
'''


def legacy_catalog(
    *,
    slug: str = "example",
    name_en: object = "Example Reciter",
    name_ar: object = "قارئ المثال",
    riwaya: str = "hafs",
    style: str = "murattal",
    binding: dict | None = None,
) -> dict:
    return {
        slug: {
            "name": {"ar": name_ar, "en": name_en},
            "styles": {
                style: {
                    "riwayat": {
                        riwaya: {
                            "providers": {
                                "quranFoundationAyah": [
                                    binding
                                    or {"id": 7, "reciterName": "Example Reciter", "style": None}
                                ]
                            }
                        }
                    }
                }
            },
        }
    }


def current_catalog(*, binding: dict | None = None) -> dict:
    return {
        "example": {
            "name": {"ar": "قارئ المثال", "en": "Example Reciter"},
            "riwayat": {
                "hafs": {
                    "styles": {
                        "murattal": {
                            "providers": {
                                "quranFoundationAyah": [
                                    binding
                                    or {"id": 7, "reciterName": "Example Reciter", "style": None}
                                ]
                            }
                        }
                    }
                }
            },
        }
    }


class CatalogComparisonTests(unittest.TestCase):
    def test_hierarchy_reordering_is_semantically_equal(self) -> None:
        comparison = compare_catalogs(legacy_catalog(), current_catalog())

        self.assertEqual([], comparison.lost)
        self.assertEqual([], comparison.changed)
        self.assertEqual([], comparison.added)
        self.assertEqual([], comparison.allowed_removed)

    def test_missing_changed_added_and_dead_entries_are_classified_deterministically(self) -> None:
        legacy = legacy_catalog(binding={"id": 7, "reciterName": "Legacy", "style": None})
        legacy["lost"] = legacy_catalog(slug="lost")["lost"]
        legacy["example"]["styles"]["murattal"]["riwayat"]["hafs"]["providers"]["everyAyah"] = [
            {"everyAyahId": "12", "name": "Dead", "dead": True}
        ]
        candidate = current_catalog(binding={"id": 7, "reciterName": "Candidate", "style": None})
        candidate["added"] = current_catalog()["example"]

        comparison = compare_catalogs(legacy, candidate)

        self.assertTrue(any(item["slug"] == "lost" for item in comparison.lost))
        self.assertEqual("example", comparison.changed[0]["slug"])
        self.assertTrue(any(item["slug"] == "added" for item in comparison.added))
        self.assertEqual("12", comparison.allowed_removed[0]["identity"])


class BootstrapCliTests(unittest.TestCase):
    def test_rejects_already_migrated_catalog(self) -> None:
        catalog_path = self.root / "data" / "curated" / "catalog.json"
        catalog_path.write_text(
            json.dumps({"example": {"name": {"en": "Example", "ar": "مثال"}, "riwayat": {}}}),
            encoding="utf-8",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            result = bootstrap_main(["--root", str(self.root), "--json"])

        self.assertEqual(1, result)
        self.assertIn("already uses the generated riwayat -> styles schema", output.getvalue())

    def test_apply_preserves_comma_brace_inside_qfa_string(self) -> None:
        self.markdown_path.write_text(
            qfa_markdown().replace('"Example Reciter"', '"Example Reciter,}"'),
            encoding="utf-8",
        )
        self.write_legacy(
            legacy_catalog(binding={"id": 7, "reciterName": "Example Reciter,}", "style": None})
        )

        output = io.StringIO()
        with redirect_stdout(output):
            result = bootstrap_main(["--root", str(self.root), "--apply", "--json"])

        self.assertEqual(0, result)
        self.assertIn('"reciter_name": "Example Reciter,}"', self.markdown_path.read_text(encoding="utf-8"))
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.reciters = self.root / "data" / "curated" / "reciters"
        self.reciters.mkdir(parents=True)
        self.markdown_path = self.reciters / "example.md"
        self.catalog_path = self.root / "data" / "curated" / "catalog.json"

    def write_legacy(self, payload: dict | None = None) -> None:
        self.catalog_path.write_text(
            json.dumps(payload or legacy_catalog(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def run_json(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            result = bootstrap_main(["--root", str(self.root), *arguments, "--json"])
        return result, json.loads(output.getvalue())

    def test_bootstrap_report_never_changes_markdown_without_apply(self) -> None:
        self.write_legacy()
        self.markdown_path.write_text(qfa_markdown(), encoding="utf-8")
        before = self.markdown_path.read_bytes()
        result, report = self.run_json()

        self.assertEqual(0, result)
        self.assertEqual(before, self.markdown_path.read_bytes())
        self.assertEqual(["backfills", "conflicts", "legacyLosses", "additions"], list(report))
        self.assertEqual(["catalog_style", "riwaya"], sorted(edit["field"] for edit in report["backfills"]))
        self.assertEqual([], report["conflicts"])
        self.assertEqual([], report["legacyLosses"])

    def test_apply_backfills_qfa_classification_only_for_exact_slug_and_provider_id(self) -> None:
        self.write_legacy()
        self.markdown_path.write_text(qfa_markdown(), encoding="utf-8")

        result, _ = self.run_json("--apply")

        self.assertEqual(0, result)
        text = self.markdown_path.read_text(encoding="utf-8")
        self.assertIn('"riwaya": "hafs"', text)
        self.assertIn('"catalog_style": "murattal"', text)
        generated = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.assertIn("riwayat", generated["example"])
        self.assertNotIn("styles", generated["example"])

        other_root = self.root / "other"
        other_reciters = other_root / "data" / "curated" / "reciters"
        other_reciters.mkdir(parents=True)
        other_markdown = other_reciters / "different.md"
        other_markdown.write_text(qfa_markdown(), encoding="utf-8")
        other_catalog = other_root / "data" / "curated" / "catalog.json"
        other_catalog.write_text(json.dumps(legacy_catalog(), ensure_ascii=False), encoding="utf-8")
        before = other_markdown.read_bytes()

        output = io.StringIO()
        with redirect_stdout(output):
            other_result = bootstrap_main(["--root", str(other_root), "--apply", "--json"])
        self.assertEqual(1, other_result)
        self.assertEqual(before, other_markdown.read_bytes())
        self.assertEqual(legacy_catalog(), json.loads(other_catalog.read_text(encoding="utf-8")))

    def test_apply_reuses_existing_trailing_comma_when_backfilling_qfa_fields(self) -> None:
        self.write_legacy()
        self.markdown_path.write_text(qfa_markdown(trailing_comma=True), encoding="utf-8")

        result, _ = self.run_json("--apply")

        self.assertEqual(0, result)
        text = self.markdown_path.read_text(encoding="utf-8")
        self.assertNotIn(",,", text)
        reciters, parse_issues = load_curated_reciters(self.root)
        catalog, catalog_issues = build_catalog(reciters)
        self.assertEqual([], parse_issues)
        self.assertEqual([], catalog_issues)
        self.assertEqual(
            [{"id": 7, "reciterName": "Example Reciter", "style": None}],
            catalog["example"]["riwayat"]["hafs"]["styles"]["murattal"]["providers"][
                "quranFoundationAyah"
            ],
        )

    def test_report_fails_loudly_for_candidate_only_missing_classification(self) -> None:
        self.catalog_path.write_text("{}\n", encoding="utf-8")
        self.markdown_path.write_text(qfa_markdown(), encoding="utf-8")
        output = io.StringIO()

        with redirect_stdout(output):
            result = bootstrap_main(["--root", str(self.root)])

        self.assertEqual(1, result)
        self.assertIn("example.md QFA 7", output.getvalue())
        self.assertIn("missing_classification", output.getvalue())

    def test_apply_fails_loudly_for_candidate_only_missing_classification(self) -> None:
        self.catalog_path.write_text("{}\n", encoding="utf-8")
        self.markdown_path.write_text(qfa_markdown(), encoding="utf-8")
        before_markdown = self.markdown_path.read_bytes()
        before_catalog = self.catalog_path.read_bytes()
        output = io.StringIO()

        with redirect_stdout(output):
            result = bootstrap_main(["--root", str(self.root), "--apply"])

        self.assertEqual(1, result)
        self.assertIn("example.md QFA 7", output.getvalue())
        self.assertIn("missing_classification", output.getvalue())
        self.assertEqual(before_markdown, self.markdown_path.read_bytes())
        self.assertEqual(before_catalog, self.catalog_path.read_bytes())

    def test_apply_copies_only_explicit_legacy_names(self) -> None:
        self.write_legacy()
        self.markdown_path.write_text(qfa_markdown(slug_name=None, arabic_name=None), encoding="utf-8")

        result, _ = self.run_json("--apply")
        self.assertEqual(0, result)
        text = self.markdown_path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#name\nen:Example Reciter\nar:قارئ المثال\n\n"))

        missing_root = self.root / "missing"
        missing_reciters = missing_root / "data" / "curated" / "reciters"
        missing_reciters.mkdir(parents=True)
        missing_markdown = missing_reciters / "example.md"
        missing_markdown.write_text(qfa_markdown(slug_name=None, arabic_name=None), encoding="utf-8")
        missing_catalog = missing_root / "data" / "curated" / "catalog.json"
        missing_catalog.write_text(
            json.dumps(legacy_catalog(name_en=None, name_ar="قارئ المثال"), ensure_ascii=False),
            encoding="utf-8",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            missing_result = bootstrap_main(["--root", str(missing_root), "--apply", "--json"])
        self.assertEqual(1, missing_result)
        self.assertNotIn("en:", missing_markdown.read_text(encoding="utf-8"))

    def test_apply_rejects_incomplete_name_header_after_provider_and_preserves_file(self) -> None:
        self.write_legacy()
        markdown = qfa_markdown(arabic_name=None)
        name_block, provider_blocks = markdown.split("\n\n", 1)
        self.markdown_path.write_text(provider_blocks + "\n\n" + name_block + "\n", encoding="utf-8")
        before_markdown = self.markdown_path.read_bytes()
        before_catalog = self.catalog_path.read_bytes()
        output = io.StringIO()

        with redirect_stdout(output):
            result = bootstrap_main(["--root", str(self.root), "--apply", "--json"])

        self.assertEqual(1, result)
        self.assertIn("name_not_first", output.getvalue())
        self.assertEqual(before_markdown, self.markdown_path.read_bytes())
        self.assertEqual(before_catalog, self.catalog_path.read_bytes())

    def test_apply_rejects_late_incomplete_double_hash_name_and_preserves_files(self) -> None:
        self.write_legacy()
        markdown = qfa_markdown(arabic_name=None)
        name_block, provider_blocks = markdown.split("\n\n", 1)
        late_name = name_block.replace("#name", "##name")
        self.markdown_path.write_text(provider_blocks + "\n\n" + late_name + "\n", encoding="utf-8")
        before_markdown = self.markdown_path.read_bytes()
        before_catalog = self.catalog_path.read_bytes()
        output = io.StringIO()

        with redirect_stdout(output):
            result = bootstrap_main(["--root", str(self.root), "--apply", "--json"])

        self.assertEqual(1, result)
        self.assertIn("name_not_first", output.getvalue())
        self.assertEqual(before_markdown, self.markdown_path.read_bytes())
        self.assertEqual(before_catalog, self.catalog_path.read_bytes())

    def test_apply_leaves_conflicts_and_catalog_unchanged_and_returns_one(self) -> None:
        self.write_legacy()
        self.markdown_path.write_text(
            qfa_markdown(riwaya="warsh_an_nafi", catalog_style="murattal"),
            encoding="utf-8",
        )
        before_markdown = self.markdown_path.read_bytes()
        before_catalog = self.catalog_path.read_bytes()
        output = io.StringIO()

        with redirect_stdout(output):
            result = bootstrap_main(["--root", str(self.root), "--apply"])

        self.assertEqual(1, result)
        self.assertEqual(before_markdown, self.markdown_path.read_bytes())
        self.assertEqual(before_catalog, self.catalog_path.read_bytes())
        line = output.getvalue().strip()
        self.assertIn("example", line)
        self.assertIn("example.md", line)
        self.assertIn("QFA", line)
        self.assertIn("7", line)
        self.assertIn("riwaya", line)
        self.assertIn("hafs", line)
        self.assertIn("warsh_an_nafi", line)


if __name__ == "__main__":
    unittest.main()
