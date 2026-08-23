from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from reciter_fetcher.catalog_cli import main as catalog_main
from reciter_fetcher.storage import atomic_write_text


EXPECTED_CATALOG = {
    "example": {
        "name": {"ar": "قارئ المثال", "en": "Example Reciter"},
        "riwayat": {
            "hafs": {
                "styles": {
                    "murattal": {
                        "providers": {
                            "quranFoundationAyah": [
                                {"id": 7, "reciterName": "Example Reciter", "style": None}
                            ]
                        }
                    }
                }
            }
        },
    }
}


def markdown(*, classified: bool = True) -> str:
    curated = ',\n  "riwaya": "hafs",\n  "catalog_style": "murattal"' if classified else ""
    return f'''#name
en:Example Reciter
ar:قارئ المثال

# QFS

# QFA
{{
  "id": 7,
  "reciter_name": "Example Reciter",
  "style": null{curated}
}}

# MP3

# EA
'''


class CatalogCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.reciters = self.root / "data" / "curated" / "reciters"
        self.reciters.mkdir(parents=True)
        self.markdown_path = self.reciters / "example.md"
        self.catalog_path = self.root / "data" / "curated" / "catalog.json"
        self.markdown_path.write_text(markdown(), encoding="utf-8")

    def test_generate_writes_catalog_atomically_from_markdown(self) -> None:
        result = catalog_main(["--root", str(self.root)])

        self.assertEqual(0, result)
        self.assertEqual(EXPECTED_CATALOG, json.loads(self.catalog_path.read_text(encoding="utf-8")))
        self.assertIn("قارئ المثال", self.catalog_path.read_text(encoding="utf-8"))

    def test_check_succeeds_only_for_exact_deterministic_bytes_without_writing(self) -> None:
        self.assertEqual(0, catalog_main(["--root", str(self.root)]))
        before = self.catalog_path.read_bytes()

        self.assertEqual(0, catalog_main(["--root", str(self.root), "--check"]))
        self.assertEqual(before, self.catalog_path.read_bytes())

        self.catalog_path.write_text("{}\n", encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            result = catalog_main(["--root", str(self.root), "--check"])
        self.assertEqual(1, result)
        self.assertEqual(b"{}\n", self.catalog_path.read_bytes())

    def test_generation_error_preserves_previous_catalog_and_prints_every_issue(self) -> None:
        self.catalog_path.write_text('{"protected": true}\n', encoding="utf-8")
        self.markdown_path.write_text(markdown(classified=False), encoding="utf-8")
        second = self.reciters / "z_missing_name.md"
        second.write_text(markdown().replace("#name\nen:Example Reciter\nar:قارئ المثال\n\n", ""), encoding="utf-8")
        before = self.catalog_path.read_bytes()
        output = io.StringIO()

        with redirect_stdout(output):
            result = catalog_main(["--root", str(self.root)])

        self.assertEqual(1, result)
        self.assertEqual(before, self.catalog_path.read_bytes())
        lines = output.getvalue().splitlines()
        self.assertEqual(sorted(lines), lines)
        self.assertTrue(any("example.md QFA 7" in line and "missing_classification" in line for line in lines))
        self.assertTrue(any("z_missing_name.md NAME" in line and "missing_name" in line for line in lines))

    def test_missing_reciter_source_directory_preserves_previous_catalog(self) -> None:
        missing_root = self.root / "missing-source"
        catalog_path = missing_root / "data" / "curated" / "catalog.json"
        catalog_path.parent.mkdir(parents=True)
        catalog_path.write_text('{"protected": true}\n', encoding="utf-8")
        before = catalog_path.read_bytes()
        output = io.StringIO()

        with redirect_stdout(output):
            result = catalog_main(["--root", str(missing_root)])

        self.assertEqual(1, result)
        self.assertEqual(before, catalog_path.read_bytes())
        self.assertIn("data/curated/reciters", output.getvalue())
        self.assertIn("missing", output.getvalue())

    def test_atomic_write_text_cleans_temporary_file_when_replace_fails(self) -> None:
        target = self.root / "nested" / "output.txt"
        target.parent.mkdir()
        target.write_text("protected", encoding="utf-8")

        with patch("reciter_fetcher.storage.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                atomic_write_text(target, "replacement")

        self.assertEqual("protected", target.read_text(encoding="utf-8"))
        self.assertEqual([target], list(target.parent.iterdir()))


if __name__ == "__main__":
    unittest.main()
