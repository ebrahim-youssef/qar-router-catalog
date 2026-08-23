from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reciter_fetcher.audit import audit, extract_entries, format_report, parse_name_header, report_to_json, split_sections


def write_raw(root: Path) -> None:
    (root / "data" / "raw" / "quran_foundation").mkdir(parents=True)
    (root / "data" / "raw" / "mp3quran").mkdir(parents=True)
    (root / "data" / "raw" / "everyayah").mkdir(parents=True)
    (root / "data" / "raw" / "quran_foundation" / "chapter-reciters.json").write_text(
        json.dumps(
            {
                "reciters": [
                    {
                        "id": 7,
                        "name": "Afasy",
                        "qirat": {"name": "Hafs"},
                        "style": {"name": "Murattal"},
                    },
                    {
                        "id": 173,
                        "name": "Afasy Streaming",
                        "qirat": {"name": "Hafs"},
                        "style": {"name": "Murattal"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "data" / "raw" / "quran_foundation" / "ayah-recitations.json").write_text(
        json.dumps({"recitations": [{"id": 2, "reciter_name": "AbdulBaset", "style": None}]}),
        encoding="utf-8",
    )
    (root / "data" / "raw" / "mp3quran" / "reciters.json").write_text(
        json.dumps(
            {
                "reciters": [
                    {
                        "id": 102,
                        "name": "Maher",
                        "moshaf": [{"id": 100, "rewaya_id": 1, "moshaf_type": 11}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "data" / "raw" / "everyayah" / "recitations.json").write_text(
        json.dumps({"ayahCount": [7], "28": {"subfolder": "Maher_64", "name": "Maher"}}),
        encoding="utf-8",
    )


def write_curated(root: Path, name: str, body: str) -> None:
    directory = root / "data" / "curated" / "reciters"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body, encoding="utf-8")


def full_file(qfs_body: str = "", qfa_body: str = "", mp3_body: str = "", ea_body: str = "") -> str:
    return f"#name\nen:Test Reciter\nar:قارئ\n\n# QFS\n{qfs_body}\n\n# QFA\n{qfa_body}\n\n# MP3\n{mp3_body}\n\n# EA\n{ea_body}\n"


class AuditTests(unittest.TestCase):
    def test_malformed_raw_json_is_a_structured_file_issue(self) -> None:
        raw_path = self.root / "data" / "raw" / "quran_foundation" / "chapter-reciters.json"
        raw_path.parent.mkdir(parents=True)
        raw_path.write_text("{broken", encoding="utf-8")

        report = audit(self.root, strict=True)

        issues = [issue for issue in report.file_issues if issue.code == "raw_file_error"]
        self.assertTrue(any(issue.section == "QFS" and issue.file.endswith("chapter-reciters.json") for issue in issues))

    def test_unreadable_raw_json_is_a_structured_file_issue(self) -> None:
        write_raw(self.root)
        raw_path = self.root / "data" / "raw" / "quran_foundation" / "chapter-reciters.json"
        read_text = Path.read_text

        def fail_selected_path(path: Path, *args: object, **kwargs: object) -> str:
            if path == raw_path:
                raise OSError("permission denied")
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=fail_selected_path):
            report = audit(self.root)

        issues = [issue for issue in report.file_issues if issue.code == "raw_file_error"]
        self.assertTrue(any(issue.section == "QFS" and "permission denied" in issue.issue for issue in issues))

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_full_coverage_passes(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "afasy.md", full_file(
            qfs_body=(
                '{"id": 7, "name": "Afasy", "qirat": {"name": "Hafs"}, "style": {"name": "Murattal"}},\n'
                '{"id": 173, "name": "Afasy Streaming", "qirat": {"name": "Hafs"}, "style": {"name": "Murattal"}},'
            ),
            qfa_body='{"id": 2, "reciter_name": "AbdulBaset", "style": null, "riwaya": "hafs", "catalog_style": "murattal"},',
            mp3_body='{"id": 102, "name": "Maher", "moshaf": [{"id": 100, "rewaya_id": 1, "moshaf_type": 11}]},',
            ea_body=' "28": {"subfolder": "Maher_64", "name": "Maher", "style": "murattal", "riwaya": "hafs"},',
        ))
        report = audit(self.root)
        self.assertTrue(report.ok, format_report(report))

    def test_missing_id_is_reported(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "afasy.md", full_file(
            qfs_body='{"id": 7, "name": "Afasy"},',
            mp3_body='{"id": 102, "name": "Maher"},',
            ea_body=' "28": {"subfolder": "Maher_64", "name": "Maher"},',
        ))
        report = audit(self.root)
        self.assertFalse(report.ok)
        qfs = next(provider for provider in report.providers if provider.tag == "QFS")
        self.assertEqual(qfs.missing, [173])

    def test_stale_id_is_reported(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "afasy.md", full_file(
            qfs_body='{"id": 999, "name": "Ghost"},',
            mp3_body='{"id": 102, "name": "Maher"},',
            ea_body=' "28": {"subfolder": "Maher_64", "name": "Maher"},',
            qfa_body="none",
        ))
        report = audit(self.root)
        qfs = next(provider for provider in report.providers if provider.tag == "QFS")
        self.assertEqual(qfs.stale, [999])
        self.assertEqual(qfs.missing, [7, 173])

    def test_duplicates_across_and_within_files(self) -> None:
        write_raw(self.root)
        snippet = '{"id": 102, "name": "Maher"},'
        write_curated(self.root, "maher.md", full_file(mp3_body=snippet, ea_body=' "28": {"subfolder": "x", "name": "y"},'))
        write_curated(self.root, "maher_copy.md", full_file(mp3_body=snippet))
        report = audit(self.root)
        mp3 = next(provider for provider in report.providers if provider.tag == "MP3")
        self.assertEqual(len(mp3.duplicates), 1)
        identifier, paths = mp3.duplicates[0]
        self.assertEqual(identifier, 102)
        self.assertEqual(sorted(paths), ["maher.md", "maher_copy.md"])

    def test_wrong_section_paste_is_detected(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "maher.md", full_file(
            qfs_body='{"id": 102, "name": "Maher"},',
            mp3_body="",
            ea_body=' "28": {"subfolder": "x", "name": "y"},',
        ))
        report = audit(self.root)
        qfs = next(provider for provider in report.providers if provider.tag == "QFS")
        mp3 = next(provider for provider in report.providers if provider.tag == "MP3")
        self.assertIn(102, qfs.stale)
        self.assertIn(102, mp3.missing)

    def test_strict_mismatch_is_reported(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "maher.md", full_file(
            mp3_body='{"id": 102, "name": "Edited By Hand"},',
            ea_body=' "28": {"subfolder": "x", "name": "y"},',
        ))
        report = audit(self.root, strict=True)
        self.assertFalse(report.ok)
        self.assertTrue(any(mismatch.file == "maher.md" and mismatch.reciter_id == 102 for mismatch in report.strict_mismatches))

    def test_strict_passes_when_snippet_matches(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "maher.md", full_file(
            mp3_body='{  "id": 102,  "name": "Maher", "moshaf": [{"id": 100, "rewaya_id": 1, "moshaf_type": 11}],},',
            ea_body=' "28": {"subfolder": "Maher_64", "name": "Maher"},',
        ))
        report = audit(self.root, strict=True)
        self.assertEqual(report.strict_mismatches, [])

    def test_strict_tolerates_curated_style_keys_on_ea(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "maher.md", full_file(
            ea_body=' "28": {"subfolder": "Maher_64", "name": "Maher", "style": "murattal", "riwaya": "hafs", "dead": true},',
        ))
        report = audit(self.root, strict=True)
        self.assertEqual(report.strict_mismatches, [])

    def test_strict_tolerates_curated_classification_keys_on_qfa(self) -> None:
        write_raw(self.root)
        write_curated(
            self.root,
            "qfa.md",
            full_file(
                qfa_body='{"id": 2, "reciter_name": "AbdulBaset", "style": null, "riwaya": "hafs", "catalog_style": "murattal"},'
            ),
        )

        report = audit(self.root, strict=True)

        self.assertFalse(any(mismatch.tag == "QFA" for mismatch in report.strict_mismatches))

    def test_strict_still_flags_other_ea_edits(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "maher.md", full_file(
            ea_body=' "28": {"subfolder": "Edited_64", "name": "Maher"},',
        ))
        report = audit(self.root, strict=True)
        self.assertTrue(any(mismatch.tag == "EA" for mismatch in report.strict_mismatches))

    def test_missing_name_header_is_flagged(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "broken.md", "# QFS\n\n# QFA\n\n# MP3\n\n# EA\n")
        report = audit(self.root)
        self.assertTrue(any(issue.issue.startswith("missing #name") for issue in report.file_issues))

    def test_parser_issues_keep_stable_codes_and_locations(self) -> None:
        write_raw(self.root)
        write_curated(
            self.root,
            "broken.md",
            "#name\nen:Broken\nar:مكسور\n\n# QFS\n{\"name\": \"No id\"}\n",
        )

        report = audit(self.root)
        issues = [(issue.code, issue.section, issue.entry_id) for issue in report.file_issues]

        self.assertIn(("missing_id", "QFS", None), issues)
        self.assertIn(("missing_section", "QFA", None), issues)
        self.assertIn(("missing_section", "MP3", None), issues)
        self.assertIn(("missing_section", "EA", None), issues)

    def test_qfa_requires_curated_riwayah_and_null_style_classification(self) -> None:
        write_raw(self.root)
        write_curated(
            self.root,
            "qfa.md",
            full_file(qfa_body='{"id": 2, "reciter_name": "AbdulBaset", "style": null},'),
        )

        report = audit(self.root)
        issues = [(issue.code, issue.section, issue.entry_id) for issue in report.file_issues]

        self.assertIn(("missing_classification", "QFA", 2), issues)

    def test_unknown_mp3_classifications_are_actionable_issues(self) -> None:
        write_raw(self.root)
        write_curated(
            self.root,
            "mp3.md",
            full_file(
                mp3_body='{"id": 102, "name": "Maher", "moshaf": [{"id": 100, "rewaya_id": 999, "moshaf_type": 999}]},'
            ),
        )

        report = audit(self.root)
        issues = [(issue.code, issue.section, issue.entry_id) for issue in report.file_issues]

        self.assertIn(("unknown_riwayah", "MP3", 100), issues)
        self.assertIn(("unknown_style", "MP3", 100), issues)

    def test_qfa_and_qfs_duplicate_checks_use_separate_id_domains(self) -> None:
        write_raw(self.root)
        (self.root / "data" / "raw" / "quran_foundation" / "ayah-recitations.json").write_text(
            json.dumps({"recitations": [{"id": 7, "reciter_name": "Ayah Afasy", "style": None}]}),
            encoding="utf-8",
        )
        write_curated(
            self.root,
            "afasy.md",
            full_file(
                qfs_body='{"id": 7, "name": "Afasy", "qirat": {"name": "Hafs"}, "style": {"name": "Murattal"}},',
                qfa_body='{"id": 7, "reciter_name": "Ayah Afasy", "style": null, "riwaya": "hafs", "catalog_style": "murattal"},',
            ),
        )

        report = audit(self.root)
        qfs = next(provider for provider in report.providers if provider.tag == "QFS")
        qfa = next(provider for provider in report.providers if provider.tag == "QFA")

        self.assertEqual([], qfs.duplicates)
        self.assertEqual([], qfa.duplicates)

    def test_json_report_emits_literal_stable_issue_codes(self) -> None:
        write_raw(self.root)
        write_curated(
            self.root,
            "broken.md",
            "#name\nen:Broken\nar:مكسور\n\n# QFS\n{\"name\": \"No id\"}\n",
        )

        payload = report_to_json(audit(self.root))
        issues = payload["file_issues"]

        self.assertIn("missing_id", [issue["code"] for issue in issues])
        self.assertIn("missing_section", [issue["code"] for issue in issues])
        self.assertTrue(all({"code", "section", "entry_id"} <= issue.keys() for issue in issues))

    def test_invalid_snippet_json_is_flagged(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "broken.md", full_file(mp3_body='{"id": 102, "name": }', ea_body=""))
        report = audit(self.root)
        self.assertTrue(any("invalid JSON" in issue.issue for issue in report.file_issues))

    def test_unbalanced_snippet_braces_are_flagged(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "broken.md", full_file(mp3_body='{"id": 102, broken', ea_body=""))
        report = audit(self.root)
        self.assertTrue(any("unbalanced braces" in issue.issue for issue in report.file_issues))

    def test_missing_raw_file_is_flagged(self) -> None:
        write_curated(self.root, "empty.md", full_file())
        report = audit(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("raw file not found" in issue.issue for issue in report.file_issues))

    def test_everyayah_meta_keys_are_skipped(self) -> None:
        write_raw(self.root)
        write_curated(self.root, "maher.md", full_file(ea_body=' "28": {"subfolder": "x", "name": "y"},'))
        report = audit(self.root)
        ea = next(provider for provider in report.providers if provider.tag == "EA")
        self.assertEqual(ea.stale, [])
        self.assertEqual(ea.raw_count, 1)

    def test_legacy_parser_helpers_remain_compatible(self) -> None:
        sections = split_sections("#name\nen:Test\nar:قارئ\n\n# QFS\n{\"id\": 7}\n")

        self.assertIsNone(parse_name_header(sections))
        self.assertEqual([(7, {"id": 7})], extract_entries(sections["QFS"]))
        self.assertEqual([(28, {"name": "EveryAyah"})], extract_entries('"28": {"name": "EveryAyah"}'))
        self.assertEqual([(None, {"name": "No identifier"})], extract_entries('{"name": "No identifier"}'))


if __name__ == "__main__":
    unittest.main()
