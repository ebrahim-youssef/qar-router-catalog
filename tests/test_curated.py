from __future__ import annotations

import unittest

from reciter_fetcher.curated import parse_curated_text, remove_trailing_json_commas


FULL_MARKDOWN = '''#name
en:Example Reciter
ar:قارئ

# QFS
{"id": 7, "name": "Chapter"},
{"id": 173, "name": "Streaming"},

# QFA
{"id": 2, "reciter_name": "Ayah"},

# MP3
{"id": 102, "name": "MP3", "moshaf": [{"id": 1, "name": "Hafs"}]},

# EA
"28": {"subfolder": "Example_64", "name": "Example"},
'''


BROKEN_MARKDOWN = '''#name
en:Broken
ar:مكسور

# QFS
{"name": "No identifier"},
{"id": 2, "name": },

# QFA

# MP3

# EA
'''


class CuratedParserTests(unittest.TestCase):
    def test_rejects_non_whitespace_preamble(self) -> None:
        _, issues = parse_curated_text("orphan provider data\n" + FULL_MARKDOWN, file_name="preamble.md")

        self.assertIn("invalid_preamble", [issue.code for issue in issues])

    def test_rejects_unknown_heading_without_silently_ignoring_its_data(self) -> None:
        text = FULL_MARKDOWN + '\n# NEW_PROVIDER\n{"id": 999}\n'

        _, issues = parse_curated_text(text, file_name="unknown.md")

        unknown = [issue for issue in issues if issue.code == "unknown_section"]
        self.assertEqual(1, len(unknown))
        self.assertEqual("NEW_PROVIDER", unknown[0].section)
        self.assertIn("unsupported section header", unknown[0].message)

    def test_requires_name_as_first_meaningful_section(self) -> None:
        text = '# QFS\n{"id": 7}\n\n' + FULL_MARKDOWN

        _, issues = parse_curated_text(text, file_name="order.md")

        self.assertIn("name_not_first", [issue.code for issue in issues])

    def test_trailing_comma_cleanup_is_string_aware(self) -> None:
        snippet = '{"name": "valid,}", "items": ["also,]",],}'

        cleaned = remove_trailing_json_commas(snippet)

        self.assertEqual('{"name": "valid,}", "items": ["also,]"]}', cleaned)
    def test_parses_name_and_all_provider_sections(self) -> None:
        reciter, issues = parse_curated_text(FULL_MARKDOWN, file_name="example.md")

        self.assertEqual([], issues)
        self.assertEqual("example", reciter.slug)
        self.assertEqual("Example Reciter", reciter.name_en)
        self.assertEqual("قارئ", reciter.name_ar)
        self.assertEqual([7, 173], [entry.identifier for entry in reciter.sections["QFS"]])
        self.assertEqual([28], [entry.identifier for entry in reciter.sections["EA"]])

    def test_reports_missing_section_headers(self) -> None:
        _, issues = parse_curated_text("#name\nen:X\nar:س\n\n# QFS\n", file_name="x.md")

        self.assertEqual(
            ["missing_section", "missing_section", "missing_section"],
            [issue.code for issue in issues],
        )

    def test_reports_missing_identifier_and_malformed_json(self) -> None:
        _, issues = parse_curated_text(BROKEN_MARKDOWN, file_name="broken.md")

        self.assertEqual(["missing_id", "invalid_json"], [issue.code for issue in issues])

    def test_reports_duplicate_name_and_provider_headers(self) -> None:
        text = '''#name
en:First
ar:أول

#name
en:Second
ar:ثان

# QFS
{"id": 7}

# QFS
{"id": 173}

# QFA

# MP3

# EA
'''

        _, issues = parse_curated_text(text, file_name="duplicate.md")

        self.assertEqual(
            [("duplicate_section", "NAME"), ("duplicate_section", "QFS")],
            [(issue.code, issue.section) for issue in issues],
        )

    def test_reports_non_object_section_content(self) -> None:
        for content in ("not-json", "]"):
            with self.subTest(content=content):
                text = FULL_MARKDOWN.replace('{"id": 7, "name": "Chapter"},\n{"id": 173, "name": "Streaming"},', content)

                _, issues = parse_curated_text(text, file_name="invalid.md")

                self.assertIn(("invalid_json", "QFS"), [(issue.code, issue.section) for issue in issues])

    def test_parses_ea_key_with_long_whitespace_before_object(self) -> None:
        text = FULL_MARKDOWN.replace(
            '"28": {"subfolder": "Example_64", "name": "Example"},',
            '"28":' + (" " * 80) + '{"subfolder": "Example_64", "name": "Example"},',
        )

        reciter, issues = parse_curated_text(text, file_name="example.md")

        self.assertEqual([], issues)
        self.assertEqual([28], [entry.identifier for entry in reciter.sections["EA"]])


if __name__ == "__main__":
    unittest.main()
