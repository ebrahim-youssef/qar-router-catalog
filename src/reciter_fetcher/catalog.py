from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from reciter_fetcher.curated import CuratedEntry, CuratedReciter


MP3_RIWAYAH_BY_ID = {
    1: "hafs",
    2: "warsh_an_nafi",
    3: "khalaf_an_hamzah",
    4: "albazzi_an_ibnkatheer",
    5: "qalun_an_nafi",
    6: "qunbul_an_ibnkatheer",
    7: "alsusi_an_abiamr",
    8: "qalun_an_nafi_tariq_abinasheet",
    9: "ruways_and_rawh_an_yaqoub_alhadrami",
    10: "warsh_an_nafi_tariq_abibakr_alasbahani",
    11: "albazzi_and_qunbul_an_ibnkatheer",
    12: "aldouri_an_alkisai",
    13: "aldouri_an_abiamr",
    15: "shubah_an_asim",
    16: "ibndhakwan_an_ibnamer",
    18: "warsh_an_nafi_tariq_alazraq",
    19: "hisham_an_ibnamer",
    20: "ibnjammaz_an_abijaafar",
    21: "hafs",
    22: "hafs",
}

MP3_MURATTAL_TYPES = {
    11,
    14,
    21,
    31,
    41,
    51,
    61,
    71,
    81,
    91,
    101,
    111,
    120,
    121,
    131,
    151,
    161,
    181,
    191,
    201,
}

QFS_RIWAYAH_BY_NAME = {"Hafs": "hafs"}
QFS_STYLE_BY_NAME = {
    "Murattal": "murattal",
    "Mujawwad": "mujawwad",
    "Muallim": "muallim",
    "Kids Repeat": "kids_repeat",
    "Kids repeat": "kids_repeat",
}
QFA_STYLE_BY_NAME = {
    "Murattal": "murattal",
    "Mujawwad": "mujawwad",
    "Muallim": "muallim",
}

MP3_BINDING_FIELDS = {
    "reciterId",
    "reciterName",
    "letter",
    "date",
    "moshafId",
    "moshafName",
    "rewayaId",
    "moshafType",
    "server",
    "surahTotal",
    "surahList",
}

_SLUG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_SECTION_PROVIDER = {
    "QFA": "quranFoundationAyah",
    "QFS": "quranFoundationSurah",
    "MP3": "mp3Quran",
    "EA": "everyAyah",
}


@dataclass(frozen=True)
class CatalogIssue:
    code: str
    file: str
    section: str
    entry_id: int | None
    message: str


def _issue(
    code: str,
    reciter: CuratedReciter,
    section: str,
    entry_id: int | None,
    message: str,
) -> CatalogIssue:
    return CatalogIssue(code, reciter.file, section, entry_id, message)


def _curated_slug(
    value: Any,
    *,
    reciter: CuratedReciter,
    section: str,
    entry_id: int,
    field: str,
) -> tuple[str | None, CatalogIssue | None]:
    code = "unknown_riwayah" if field == "riwaya" else "unknown_style"
    if value is None or value == "":
        return None, _issue(
            "missing_classification",
            reciter,
            section,
            entry_id,
            f"missing curated {field}",
        )
    if not isinstance(value, str) or _SLUG.fullmatch(value) is None:
        return None, _issue(code, reciter, section, entry_id, f"unsupported {field} {value!r}")
    return value, None


def _qfs_record(
    reciter: CuratedReciter, entry: CuratedEntry
) -> tuple[tuple[str, str, dict[str, Any]] | None, list[CatalogIssue]]:
    payload = entry.payload
    qirat = payload.get("qirat")
    style_data = payload.get("style")
    if not isinstance(qirat, dict) or not isinstance(style_data, dict):
        return None, [
            _issue(
                "missing_classification",
                reciter,
                "QFS",
                entry.identifier,
                "QFS entry requires structured qirat and style fields",
            )
        ]
    qirat_name = qirat.get("name")
    style_name = style_data.get("name")
    issues: list[CatalogIssue] = []
    riwayah = QFS_RIWAYAH_BY_NAME.get(qirat_name) if type(qirat_name) is str else None
    style = QFS_STYLE_BY_NAME.get(style_name) if type(style_name) is str else None
    if riwayah is None:
        issues.append(
            _issue(
                "unknown_riwayah",
                reciter,
                "QFS",
                entry.identifier,
                f"unsupported QFS qirat.name {qirat_name!r}",
            )
        )
    if style is None:
        issues.append(
            _issue(
                "unknown_style",
                reciter,
                "QFS",
                entry.identifier,
                f"unsupported QFS style.name {style_name!r}",
            )
        )
    if issues:
        return None, issues
    binding = {"id": payload["id"]}
    if "name" in payload:
        binding["name"] = payload["name"]
    binding["style"] = style_name
    binding["qirat"] = qirat_name
    if "translated_name" in payload:
        translated_name = payload["translated_name"]
        binding["translatedName"] = (
            translated_name.get("name") if isinstance(translated_name, dict) else translated_name
        )
    return (riwayah, style, binding), []  # type: ignore[return-value]


def _qfa_record(
    reciter: CuratedReciter, entry: CuratedEntry
) -> tuple[tuple[str, str, dict[str, Any]] | None, list[CatalogIssue]]:
    payload = entry.payload
    missing_fields = ["riwaya"] if payload.get("riwaya") in (None, "") else []
    if payload.get("style") is None and payload.get("catalog_style") in (None, ""):
        missing_fields.append("catalog_style")
    if missing_fields:
        return None, [
            _issue(
                "missing_classification",
                reciter,
                "QFA",
                entry.identifier,
                f"missing curated classification fields: {', '.join(missing_fields)}",
            )
        ]
    riwayah, riwayah_issue = _curated_slug(
        payload.get("riwaya"),
        reciter=reciter,
        section="QFA",
        entry_id=entry.identifier,
        field="riwaya",
    )
    raw_style = payload.get("style")
    if raw_style is None:
        style, style_issue = _curated_slug(
            payload.get("catalog_style"),
            reciter=reciter,
            section="QFA",
            entry_id=entry.identifier,
            field="style",
        )
    else:
        style = QFA_STYLE_BY_NAME.get(raw_style) if type(raw_style) is str else None
        style_issue = None
        if style is None:
            style_issue = _issue(
                "unknown_style",
                reciter,
                "QFA",
                entry.identifier,
                f"unsupported QFA style {raw_style!r}",
            )
    issues = [issue for issue in (riwayah_issue, style_issue) if issue is not None]
    if issues:
        return None, issues
    binding = {
        key: payload[source_key]
        for source_key, key in (("id", "id"), ("reciter_name", "reciterName"), ("style", "style"))
        if source_key in payload
    }
    return (riwayah, style, binding), []  # type: ignore[return-value]


def _mp3_style(moshaf_type: Any) -> str | None:
    if type(moshaf_type) is not int:
        return None
    if moshaf_type == 213:
        return "muallim"
    if moshaf_type == 222:
        return "mujawwad"
    if moshaf_type in MP3_MURATTAL_TYPES:
        return "murattal"
    return None


def _mp3_records(
    reciter: CuratedReciter, entry: CuratedEntry
) -> tuple[list[tuple[str, str, dict[str, Any]]], list[CatalogIssue]]:
    payload = entry.payload
    records: list[tuple[str, str, dict[str, Any]]] = []
    issues: list[CatalogIssue] = []
    moshafs = payload.get("moshaf")
    if not isinstance(moshafs, list):
        return [], [
            _issue(
                "missing_classification",
                reciter,
                "MP3",
                entry.identifier,
                "MP3 entry requires a moshaf array",
            )
        ]
    for moshaf in moshafs:
        if not isinstance(moshaf, dict):
            issues.append(
                _issue("missing_classification", reciter, "MP3", entry.identifier, "MP3 moshaf is not an object")
            )
            continue
        moshaf_id = moshaf.get("id")
        if type(moshaf_id) is not int:
            issues.append(
                _issue(
                    "missing_id",
                    reciter,
                    "MP3",
                    entry.identifier,
                    f"MP3 moshaf id must be an integer, got {moshaf_id!r}",
                )
            )
            continue
        issue_id = moshaf_id
        rewaya_id = moshaf.get("rewaya_id")
        riwayah = MP3_RIWAYAH_BY_ID.get(rewaya_id) if type(rewaya_id) is int else None
        style = _mp3_style(moshaf.get("moshaf_type"))
        if riwayah is None:
            issues.append(
                _issue(
                    "unknown_riwayah",
                    reciter,
                    "MP3",
                    issue_id,
                    f"unsupported MP3 rewaya_id {moshaf.get('rewaya_id')!r}",
                )
            )
        if style is None:
            issues.append(
                _issue(
                    "unknown_style",
                    reciter,
                    "MP3",
                    issue_id,
                    f"unsupported MP3 moshaf_type {moshaf.get('moshaf_type')!r}",
                )
            )
        if riwayah is None or style is None:
            continue
        candidates = {
            "reciterId": payload.get("id"),
            "reciterName": payload.get("name"),
            "letter": payload.get("letter"),
            "date": payload.get("date"),
            "moshafId": moshaf.get("id"),
            "moshafName": moshaf.get("name"),
            "rewayaId": moshaf.get("rewaya_id"),
            "moshafType": moshaf.get("moshaf_type"),
            "server": moshaf.get("server"),
            "surahTotal": moshaf.get("surah_total"),
            "surahList": moshaf.get("surah_list"),
        }
        binding = {key: value for key, value in candidates.items() if key in MP3_BINDING_FIELDS and value is not None}
        records.append((riwayah, style, binding))
    return records, issues


def _ea_record(
    reciter: CuratedReciter, entry: CuratedEntry
) -> tuple[tuple[str, str, dict[str, Any]] | None, list[CatalogIssue]]:
    payload = entry.payload
    if payload.get("dead") is True:
        return None, []
    style, style_issue = _curated_slug(
        payload.get("style"),
        reciter=reciter,
        section="EA",
        entry_id=entry.identifier,
        field="style",
    )
    if style == "translation":
        riwayah = "none"
        riwayah_issue = None
    else:
        riwayah, riwayah_issue = _curated_slug(
            payload.get("riwaya"),
            reciter=reciter,
            section="EA",
            entry_id=entry.identifier,
            field="riwaya",
        )
    issues = [issue for issue in (style_issue, riwayah_issue) if issue is not None]
    if issues:
        return None, issues
    binding = {"everyAyahId": str(entry.identifier)}
    binding.update(
        {
            key: payload[key]
            for key in ("subfolder", "name", "bitrate")
            if key in payload
        }
    )
    return (riwayah, style, binding), []  # type: ignore[return-value]


def _insert(
    catalog: dict[str, Any],
    reciter: CuratedReciter,
    riwayah: str,
    style: str,
    provider: str,
    binding: dict[str, Any],
) -> None:
    reciter_node = catalog.setdefault(
        reciter.slug,
        {"name": {"ar": reciter.name_ar, "en": reciter.name_en}, "riwayat": {}},
    )
    providers = (
        reciter_node["riwayat"]
        .setdefault(riwayah, {"styles": {}})["styles"]
        .setdefault(style, {"providers": {}})["providers"]
    )
    providers.setdefault(provider, []).append(binding)


def _identity(provider: str, binding: dict[str, Any]) -> Any:
    field = {
        "quranFoundationAyah": "id",
        "quranFoundationSurah": "id",
        "mp3Quran": "moshafId",
        "everyAyah": "everyAyahId",
    }[provider]
    return binding.get(field)


def _identity_sort_key(value: Any) -> tuple[int, Any]:
    if isinstance(value, (int, float)):
        return (0, value)
    if isinstance(value, str) and value.isdecimal():
        return (0, int(value))
    return (1, str(value))


def _sorted_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for slug in sorted(catalog):
        source_reciter = catalog[slug]
        reciter_node = {"name": source_reciter["name"], "riwayat": {}}
        for riwayah in sorted(source_reciter["riwayat"]):
            riwayah_node = {"styles": {}}
            source_styles = source_reciter["riwayat"][riwayah]["styles"]
            for style in sorted(source_styles):
                source_providers = source_styles[style]["providers"]
                providers = {
                    provider: sorted(
                        source_providers[provider],
                        key=lambda binding, provider=provider: (
                            _identity_sort_key(_identity(provider, binding)),
                            json.dumps(binding, sort_keys=True, ensure_ascii=False),
                        ),
                    )
                    for provider in sorted(source_providers)
                }
                riwayah_node["styles"][style] = {"providers": providers}
            reciter_node["riwayat"][riwayah] = riwayah_node
        result[slug] = reciter_node
    return result


def build_catalog(reciters: Iterable[CuratedReciter]) -> tuple[dict[str, Any], list[CatalogIssue]]:
    catalog: dict[str, Any] = {}
    issues: list[CatalogIssue] = []
    for reciter in sorted(reciters, key=lambda item: (item.slug, item.file)):
        for section in ("QFS", "QFA", "MP3", "EA"):
            provider = _SECTION_PROVIDER[section]
            for entry in sorted(reciter.sections.get(section, []), key=lambda item: item.identifier):
                if section == "QFS":
                    record, entry_issues = _qfs_record(reciter, entry)
                    records = [] if record is None else [record]
                elif section == "QFA":
                    record, entry_issues = _qfa_record(reciter, entry)
                    records = [] if record is None else [record]
                elif section == "MP3":
                    records, entry_issues = _mp3_records(reciter, entry)
                else:
                    record, entry_issues = _ea_record(reciter, entry)
                    records = [] if record is None else [record]
                issues.extend(entry_issues)
                for riwayah, style, binding in records:
                    _insert(catalog, reciter, riwayah, style, provider, binding)
    return _sorted_catalog(catalog), issues


def serialize_catalog(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"


def semantic_catalog(catalog: dict[str, Any], *, legacy: bool = False) -> dict[str, Any]:
    names: dict[str, Any] = {}
    bindings: dict[tuple[Any, ...], dict[str, Any]] = {}
    for slug, reciter_node in catalog.items():
        if "name" in reciter_node:
            names[slug] = reciter_node["name"]
        if legacy:
            recordings = (
                (riwayah, style, style_node)
                for style, style_node in reciter_node.get("styles", {}).items()
                for riwayah, riwayah_node in style_node.get("riwayat", {}).items()
                for style_node in (riwayah_node,)
            )
        else:
            recordings = (
                (riwayah, style, style_node)
                for riwayah, riwayah_node in reciter_node.get("riwayat", {}).items()
                for style, style_node in riwayah_node.get("styles", {}).items()
            )
        for riwayah, style, recording in recordings:
            for provider, provider_bindings in recording.get("providers", {}).items():
                for binding in provider_bindings:
                    if legacy and provider == "everyAyah" and binding.get("dead") is True:
                        continue
                    key = (slug, riwayah, style, provider, _identity(provider, binding))
                    bindings[key] = binding
    return {"names": names, "bindings": bindings}
