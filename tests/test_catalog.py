from __future__ import annotations

import unittest

from reciter_fetcher.catalog import build_catalog, semantic_catalog, serialize_catalog
from reciter_fetcher.curated import CuratedEntry, CuratedReciter


def reciter(
    *,
    slug: str = "example",
    name_en: str = "Example Reciter",
    name_ar: str = "قارئ المثال",
    qfs: list[dict] | None = None,
    qfa: list[dict] | None = None,
    mp3: list[dict] | None = None,
    ea: list[tuple[int, dict]] | None = None,
) -> CuratedReciter:
    sections = {
        "QFS": [CuratedEntry("QFS", payload["id"], payload) for payload in qfs or []],
        "QFA": [CuratedEntry("QFA", payload["id"], payload) for payload in qfa or []],
        "MP3": [CuratedEntry("MP3", payload["id"], payload) for payload in mp3 or []],
        "EA": [CuratedEntry("EA", identifier, payload) for identifier, payload in ea or []],
    }
    return CuratedReciter(slug, f"{slug}.md", name_en, name_ar, sections)


QFS_7 = {
    "id": 7,
    "name": "Surah Name",
    "style": {"name": "Murattal", "translated_name": {"name": "Murattal"}},
    "qirat": {"name": "Hafs", "language_name": "english"},
    "translated_name": {"name": "Translated Surah Name", "language_name": "english"},
}


class CatalogBuilderTests(unittest.TestCase):
    def test_qfa_and_qfs_with_same_id_remain_separate_bindings(self) -> None:
        source = reciter(
            qfs=[QFS_7],
            qfa=[
                {
                    "id": 7,
                    "reciter_name": "Ayah Name",
                    "style": None,
                    "riwaya": "hafs",
                    "catalog_style": "murattal",
                }
            ],
        )

        catalog, issues = build_catalog([source])

        self.assertEqual([], issues)
        providers = catalog["example"]["riwayat"]["hafs"]["styles"]["murattal"]["providers"]
        self.assertEqual(
            [{"id": 7, "reciterName": "Ayah Name", "style": None}],
            providers["quranFoundationAyah"],
        )
        self.assertEqual(7, providers["quranFoundationSurah"][0]["id"])

    def test_qfs_uses_structured_qirat_and_style_and_preserves_fields(self) -> None:
        catalog, issues = build_catalog([reciter(qfs=[QFS_7])])

        self.assertEqual([], issues)
        binding = catalog["example"]["riwayat"]["hafs"]["styles"]["murattal"]["providers"][
            "quranFoundationSurah"
        ][0]
        self.assertEqual(
            {
                "id": 7,
                "name": "Surah Name",
                "style": "Murattal",
                "qirat": "Hafs",
                "translatedName": "Translated Surah Name",
            },
            binding,
        )

    def test_qfs_accepts_verified_current_mujawwad_and_kids_repeat_spellings(self) -> None:
        source = reciter(
            qfs=[
                {
                    **QFS_7,
                    "id": 1,
                    "style": {"name": "Mujawwad"},
                },
                {
                    **QFS_7,
                    "id": 168,
                    "style": {"name": "Kids repeat"},
                },
            ]
        )

        catalog, issues = build_catalog([source])

        self.assertEqual([], issues)
        styles = catalog["example"]["riwayat"]["hafs"]["styles"]
        self.assertEqual(["kids_repeat", "mujawwad"], list(styles))
        self.assertEqual(168, styles["kids_repeat"]["providers"]["quranFoundationSurah"][0]["id"])
        self.assertEqual(1, styles["mujawwad"]["providers"]["quranFoundationSurah"][0]["id"])

    def test_qfa_non_null_style_uses_only_accepted_mapping(self) -> None:
        catalog, issues = build_catalog(
            [
                reciter(
                    qfa=[
                        {"id": 3, "reciter_name": "Teacher", "style": "Muallim", "riwaya": "hafs"},
                        {"id": 2, "reciter_name": "Reciter", "style": "Mujawwad", "riwaya": "hafs"},
                    ]
                )
            ]
        )

        self.assertEqual([], issues)
        styles = catalog["example"]["riwayat"]["hafs"]["styles"]
        self.assertEqual(["muallim", "mujawwad"], list(styles))
        self.assertNotIn("riwaya", styles["mujawwad"]["providers"]["quranFoundationAyah"][0])

    def test_qfa_accepts_verified_current_murattal_spelling(self) -> None:
        source = reciter(
            qfa=[
                {
                    "id": 2,
                    "reciter_name": "AbdulBaset AbdulSamad",
                    "style": "Murattal",
                    "riwaya": "hafs",
                }
            ]
        )

        catalog, issues = build_catalog([source])

        self.assertEqual([], issues)
        binding = catalog["example"]["riwayat"]["hafs"]["styles"]["murattal"]["providers"][
            "quranFoundationAyah"
        ][0]
        self.assertEqual(
            {"id": 2, "reciterName": "AbdulBaset AbdulSamad", "style": "Murattal"},
            binding,
        )

    def test_dead_everyayah_entry_is_not_generated(self) -> None:
        catalog, issues = build_catalog(
            [reciter(ea=[(27, {"subfolder": "Dead_64kbps", "name": "Dead", "bitrate": "64kbps", "style": "murattal", "riwaya": "hafs", "dead": True})])]
        )

        self.assertEqual({}, catalog)
        self.assertEqual([], issues)

    def test_everyayah_translation_uses_explicit_none_riwayah(self) -> None:
        catalog, issues = build_catalog(
            [reciter(ea=[(78, {"subfolder": "translations/example", "name": "Translation", "bitrate": "32kbps", "style": "translation"})])]
        )

        self.assertEqual([], issues)
        binding = catalog["example"]["riwayat"]["none"]["styles"]["translation"]["providers"]["everyAyah"][0]
        self.assertEqual(
            {"everyAyahId": "78", "subfolder": "translations/example", "name": "Translation", "bitrate": "32kbps"},
            binding,
        )

    def test_unknown_mp3_rewaya_id_is_reported_not_guessed(self) -> None:
        source = reciter(
            mp3=[
                {
                    "id": 10,
                    "name": "MP3 Name",
                    "moshaf": [{"id": 100, "name": "Unknown", "rewaya_id": 999, "moshaf_type": 11}],
                }
            ]
        )

        catalog, issues = build_catalog([source])

        self.assertEqual({}, catalog)
        self.assertEqual(["unknown_riwayah"], [issue.code for issue in issues])
        self.assertEqual(("example.md", "MP3", 100), (issues[0].file, issues[0].section, issues[0].entry_id))

    def test_unknown_mp3_moshaf_type_is_reported_not_guessed(self) -> None:
        source = reciter(
            mp3=[
                {
                    "id": 10,
                    "name": "MP3 Name",
                    "moshaf": [{"id": 100, "name": "Unknown", "rewaya_id": 1, "moshaf_type": 999}],
                }
            ]
        )

        catalog, issues = build_catalog([source])

        self.assertEqual({}, catalog)
        self.assertEqual(["unknown_style"], [issue.code for issue in issues])

    def test_mp3_classification_requires_exact_hashable_integers(self) -> None:
        cases = (
            ("rewaya_id", True, "unknown_riwayah"),
            ("rewaya_id", [], "unknown_riwayah"),
            ("moshaf_type", 11.0, "unknown_style"),
            ("moshaf_type", [], "unknown_style"),
        )
        for field, value, expected_code in cases:
            with self.subTest(field=field, value=value):
                moshaf = {"id": 100, "name": "Invalid classification", "rewaya_id": 1, "moshaf_type": 11}
                moshaf[field] = value
                source = reciter(mp3=[{"id": 10, "name": "MP3 Name", "moshaf": [moshaf]}])

                catalog, issues = build_catalog([source])

                self.assertEqual({}, catalog)
                self.assertEqual([expected_code], [issue.code for issue in issues])
                self.assertEqual(100, issues[0].entry_id)

    def test_unhashable_quran_foundation_classifications_are_structured_issues(self) -> None:
        cases = (
            (
                reciter(qfs=[{**QFS_7, "qirat": {"name": []}}]),
                "unknown_riwayah",
            ),
            (
                reciter(qfs=[{**QFS_7, "style": {"name": {}}}]),
                "unknown_style",
            ),
            (
                reciter(qfa=[{"id": 7, "reciter_name": "QFA", "style": [], "riwaya": "hafs"}]),
                "unknown_style",
            ),
        )
        for source, expected_code in cases:
            with self.subTest(section=next(section for section, entries in source.sections.items() if entries)):
                catalog, issues = build_catalog([source])

                self.assertEqual({}, catalog)
                self.assertEqual([expected_code], [issue.code for issue in issues])

    def test_mp3_moshaf_id_requires_an_exact_integer(self) -> None:
        for moshaf_id in (None, True, 100.0, "100"):
            with self.subTest(moshaf_id=moshaf_id):
                moshaf = {"name": "Invalid identity", "rewaya_id": 1, "moshaf_type": 11}
                if moshaf_id is not None:
                    moshaf["id"] = moshaf_id
                source = reciter(mp3=[{"id": 10, "name": "MP3 Name", "moshaf": [moshaf]}])

                catalog, issues = build_catalog([source])

                self.assertEqual({}, catalog)
                self.assertEqual(["missing_id"], [issue.code for issue in issues])
                self.assertEqual(("example.md", "MP3", 10), (issues[0].file, issues[0].section, issues[0].entry_id))

    def test_mp3_multi_moshaf_is_split_and_converted_to_camel_case(self) -> None:
        source = reciter(
            mp3=[
                {
                    "id": 10,
                    "name": "MP3 Name",
                    "letter": "M",
                    "date": "2026-01-01",
                    "moshaf": [
                        {"id": 102, "name": "Teacher", "rewaya_id": 1, "moshaf_type": 213, "server": "https://teacher", "surah_total": 2, "surah_list": "1,2"},
                        {"id": 101, "name": "Recitation", "rewaya_id": 2, "moshaf_type": 222, "server": "https://recitation", "surah_total": 1, "surah_list": "1"},
                    ],
                }
            ]
        )

        catalog, issues = build_catalog([source])

        self.assertEqual([], issues)
        binding = catalog["example"]["riwayat"]["warsh_an_nafi"]["styles"]["mujawwad"]["providers"]["mp3Quran"][0]
        self.assertEqual(
            {
                "reciterId": 10,
                "reciterName": "MP3 Name",
                "letter": "M",
                "date": "2026-01-01",
                "moshafId": 101,
                "moshafName": "Recitation",
                "rewayaId": 2,
                "moshafType": 222,
                "server": "https://recitation",
                "surahTotal": 1,
                "surahList": "1",
            },
            binding,
        )
        self.assertIn("muallim", catalog["example"]["riwayat"]["hafs"]["styles"])

    def test_provider_arrays_and_all_tree_keys_are_deterministic(self) -> None:
        source_z = reciter(
            slug="z_reciter",
            qfs=[{**QFS_7, "id": 9}, {**QFS_7, "id": 2}],
            ea=[
                (10, {"subfolder": "Ten", "name": "Ten", "bitrate": "64", "style": "murattal", "riwaya": "hafs"}),
                (2, {"subfolder": "Two", "name": "Two", "bitrate": "64", "style": "murattal", "riwaya": "hafs"}),
            ],
        )
        source_a = reciter(
            slug="a_reciter",
            mp3=[
                {
                    "id": 4,
                    "name": "A",
                    "moshaf": [
                        {"id": 20, "name": "Twenty", "rewaya_id": 1, "moshaf_type": 11},
                        {"id": 3, "name": "Three", "rewaya_id": 1, "moshaf_type": 11},
                    ],
                }
            ],
        )

        catalog, issues = build_catalog([source_z, source_a])

        self.assertEqual([], issues)
        self.assertEqual(["a_reciter", "z_reciter"], list(catalog))
        providers = catalog["z_reciter"]["riwayat"]["hafs"]["styles"]["murattal"]["providers"]
        self.assertEqual(["everyAyah", "quranFoundationSurah"], list(providers))
        self.assertEqual(["2", "10"], [binding["everyAyahId"] for binding in providers["everyAyah"]])
        self.assertEqual([2, 9], [binding["id"] for binding in providers["quranFoundationSurah"]])
        mp3 = catalog["a_reciter"]["riwayat"]["hafs"]["styles"]["murattal"]["providers"]["mp3Quran"]
        self.assertEqual([3, 20], [binding["moshafId"] for binding in mp3])

    def test_unknown_qfs_structured_terms_are_reported(self) -> None:
        source = reciter(
            qfs=[
                {**QFS_7, "id": 1, "qirat": {"name": "Unmapped"}},
                {**QFS_7, "id": 2, "style": {"name": "Unmapped"}},
            ]
        )

        catalog, issues = build_catalog([source])

        self.assertEqual({}, catalog)
        self.assertEqual(["unknown_riwayah", "unknown_style"], [issue.code for issue in issues])

    def test_missing_curated_classification_is_reported(self) -> None:
        sources = [
            reciter(slug="qfa", qfa=[{"id": 1, "reciter_name": "QFA", "style": None}]),
            reciter(slug="ea", ea=[(1, {"subfolder": "EA", "name": "EA", "style": "murattal"})]),
        ]

        catalog, issues = build_catalog(sources)

        self.assertEqual({}, catalog)
        self.assertEqual(["missing_classification", "missing_classification"], [issue.code for issue in issues])

    def test_streaming_name_does_not_invent_representation(self) -> None:
        streaming = {**QFS_7, "id": 173, "name": "Mishari Rashid al-`Afasy Streaming"}

        catalog, issues = build_catalog([reciter(qfs=[streaming])])

        self.assertEqual([], issues)
        binding = catalog["example"]["riwayat"]["hafs"]["styles"]["murattal"]["providers"][
            "quranFoundationSurah"
        ][0]
        self.assertNotIn("representation", binding)

    def test_serialization_is_stable_and_preserves_arabic(self) -> None:
        catalog, issues = build_catalog([reciter(ea=[(1, {"subfolder": "A", "name": "عربي", "bitrate": "64", "style": "murattal", "riwaya": "hafs"})])])

        self.assertEqual([], issues)
        serialized = serialize_catalog(catalog)
        self.assertIn('"ar": "قارئ المثال"', serialized)
        self.assertIn('"name": "عربي"', serialized)
        self.assertNotIn("\\u", serialized)
        self.assertTrue(serialized.endswith("\n"))
        self.assertEqual(serialized, serialize_catalog(catalog))


class SemanticCatalogTests(unittest.TestCase):
    def test_projects_new_and_legacy_hierarchies_to_same_records(self) -> None:
        binding = {"id": 7, "reciterName": "Name", "style": None}
        current = {
            "example": {
                "name": {"en": "Example", "ar": "مثال"},
                "riwayat": {"hafs": {"styles": {"murattal": {"providers": {"quranFoundationAyah": [binding]}}}}},
            }
        }
        legacy = {
            "example": {
                "name": {"ar": "مثال", "en": "Example"},
                "styles": {"murattal": {"riwayat": {"hafs": {"providers": {"quranFoundationAyah": [binding]}}}}},
            }
        }

        self.assertEqual(semantic_catalog(current), semantic_catalog(legacy, legacy=True))

    def test_projection_keeps_missing_binding_fields_visible(self) -> None:
        complete = {
            "example": {
                "riwayat": {"hafs": {"styles": {"murattal": {"providers": {"quranFoundationAyah": [{"id": 7, "reciterName": "Name", "style": None}]}}}}}
            }
        }
        missing = {
            "example": {
                "styles": {"murattal": {"riwayat": {"hafs": {"providers": {"quranFoundationAyah": [{"id": 7, "reciterName": "Name"}]}}}}}
            }
        }

        self.assertNotEqual(semantic_catalog(complete), semantic_catalog(missing, legacy=True))

    def test_legacy_projection_omits_only_dead_everyayah_binding(self) -> None:
        legacy = {
            "example": {
                "styles": {
                    "murattal": {
                        "riwayat": {
                            "hafs": {
                                "providers": {
                                    "everyAyah": [
                                        {"everyAyahId": 1, "name": "Live"},
                                        {"everyAyahId": 2, "name": "Dead", "dead": True},
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }

        projected = semantic_catalog(legacy, legacy=True)

        self.assertEqual(1, len(projected["bindings"]))
        self.assertEqual({"everyAyahId": 1, "name": "Live"}, next(iter(projected["bindings"].values())))


if __name__ == "__main__":
    unittest.main()
