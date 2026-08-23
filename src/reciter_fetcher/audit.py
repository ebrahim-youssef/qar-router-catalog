from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import catalog, curated

RAW_ROOT = "data/raw"
CURATED_ROOT = "data/curated/reciters"


@dataclass(frozen=True)
class SectionSpec:
    tag: str
    raw_file: str
    path: tuple[str, ...] = ()
    dict_keyed: bool = False
    curated_keys: tuple[str, ...] = ()


AUDIT_SECTIONS: dict[str, SectionSpec] = {
    "QFS": SectionSpec(tag="QFS", raw_file="quran_foundation/chapter-reciters.json", path=("reciters",)),
    "QFA": SectionSpec(
        tag="QFA",
        raw_file="quran_foundation/ayah-recitations.json",
        path=("recitations",),
        curated_keys=("riwaya", "catalog_style"),
    ),
    "MP3": SectionSpec(tag="MP3", raw_file="mp3quran/reciters.json", path=("reciters",)),
    "EA": SectionSpec(tag="EA", raw_file="everyayah/recitations.json", dict_keyed=True, curated_keys=("style", "riwaya", "dead")),
}

@dataclass(frozen=True)
class ProviderAudit:
    tag: str
    raw_count: int
    missing: list[int]
    stale: list[int]
    duplicates: list[tuple[int, list[str]]]

    @property
    def covered_count(self) -> int:
        return self.raw_count - len(self.missing)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.stale and not self.duplicates


@dataclass(frozen=True)
class FileIssue:
    file: str
    issue: str
    code: str = "legacy_issue"
    section: str | None = None
    entry_id: int | None = None


@dataclass(frozen=True)
class StrictMismatch:
    file: str
    tag: str
    reciter_id: int
    detail: str


@dataclass
class AuditReport:
    providers: list[ProviderAudit] = field(default_factory=list)
    file_issues: list[FileIssue] = field(default_factory=list)
    strict_mismatches: list[StrictMismatch] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(provider.ok for provider in self.providers) and not self.file_issues and not self.strict_mismatches


def canonical_id(value: Any) -> int | None:
    return curated.canonical_id(value)


def load_raw_entries(root: Path, spec: SectionSpec) -> tuple[dict[int, Any], str | None]:
    path = root / RAW_ROOT / spec.raw_file
    if not path.exists():
        return {}, f"raw file not found: {spec.raw_file}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {}, f"cannot read raw file {spec.raw_file}: {error}"
    entries: dict[int, Any] = {}
    if spec.dict_keyed:
        iterator = payload.items() if isinstance(payload, dict) else []
        for key, value in iterator:
            identifier = canonical_id(key)
            if identifier is not None and isinstance(value, dict):
                entries[identifier] = value
        return entries, None
    node: Any = payload
    for part in spec.path:
        if not isinstance(node, dict) or part not in node:
            return {}, f"raw file {spec.raw_file} is missing key {'.'.join(spec.path)}"
        node = node[part]
    if not isinstance(node, list):
        return {}, f"raw file {spec.raw_file} entry list is invalid"
    for item in node:
        if isinstance(item, dict):
            identifier = canonical_id(item.get("id"))
            if identifier is not None:
                entries[identifier] = item
    return entries, None


def extract_entries(text: str) -> list[tuple[int | None, dict[str, Any]] | FileIssue]:
    return [
        (item.identifier, item.payload)
        if isinstance(item, curated._ScannedEntry)
        else FileIssue(file="", issue=item.message, code=item.code, section=item.section, entry_id=item.entry_id)
        for item in curated._scan_section_items(text, section="GENERIC", file_name="", validate_content=False)
    ]


def split_sections(text: str) -> dict[str, str]:
    return curated.split_sections(text)


def parse_name_header(sections: dict[str, str]) -> FileIssue | None:
    name_en, name_ar = curated.parse_name_header(sections)
    if name_en is None or name_ar is None:
        return FileIssue(
            file="",
            issue="missing #name header with en:/ar: lines",
            code=curated.MISSING_NAME,
            section="NAME",
        )
    return None


@dataclass
class CuratedFile:
    relative_path: str
    sections: dict[str, str]


def load_curated_files(root: Path) -> list[CuratedFile]:
    directory = root / CURATED_ROOT
    files: list[CuratedFile] = []
    if not directory.is_dir():
        return files
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        files.append(CuratedFile(relative_path=path.name, sections=split_sections(text)))
    return files


def audit(root: Path, *, strict: bool = False) -> AuditReport:
    report = AuditReport()
    curated_files, curated_issues = curated.load_curated_reciters(root)

    coverage: dict[str, dict[int, list[str]]] = {tag: {} for tag in AUDIT_SECTIONS}
    snippets: dict[str, dict[tuple[str, int], dict[str, Any]]] = {tag: {} for tag in AUDIT_SECTIONS}

    for issue in curated_issues:
        prefix = f"[{issue.section}] " if issue.section and issue.section != "NAME" else ""
        report.file_issues.append(
            FileIssue(
                file=issue.file,
                issue=prefix + issue.message,
                code=issue.code,
                section=issue.section,
                entry_id=issue.entry_id,
            )
        )

    _, classification_issues = catalog.build_catalog(curated_files)
    for issue in sorted(
        classification_issues,
        key=lambda item: (item.file, item.section, item.entry_id is None, item.entry_id or 0, item.code, item.message),
    ):
        report.file_issues.append(
            FileIssue(
                file=issue.file,
                issue=f"[{issue.section}] {issue.message}",
                code=issue.code,
                section=issue.section,
                entry_id=issue.entry_id,
            )
        )

    for reciter in curated_files:
        for tag, entries in reciter.sections.items():
            for entry in entries:
                coverage[tag].setdefault(entry.identifier, []).append(reciter.file)
                snippets[tag][(reciter.file, entry.identifier)] = entry.payload

    for tag, spec in AUDIT_SECTIONS.items():
        raw_entries, error = load_raw_entries(root, spec)
        if error is not None:
            report.file_issues.append(
                FileIssue(
                    file=spec.raw_file,
                    issue=error,
                    code="raw_file_error",
                    section=tag,
                )
            )
            report.providers.append(ProviderAudit(tag=tag, raw_count=0, missing=[], stale=[], duplicates=[]))
            continue
        covered = set(coverage[tag])
        raw_ids = set(raw_entries)
        duplicates: list[tuple[int, list[str]]] = [
            (identifier, paths) for identifier, paths in sorted(coverage[tag].items()) if len(paths) > 1
        ]
        report.providers.append(
            ProviderAudit(
                tag=tag,
                raw_count=len(raw_ids),
                missing=sorted(raw_ids - covered),
                stale=sorted(covered - raw_ids),
                duplicates=duplicates,
            )
        )
        if strict:
            for (file_name, identifier), parsed in sorted(snippets[tag].items()):
                expected = raw_entries.get(identifier)
                curated_view = {key: value for key, value in parsed.items() if key not in spec.curated_keys}
                if expected is not None and curated_view != expected:
                    report.strict_mismatches.append(
                        StrictMismatch(file=file_name, tag=tag, reciter_id=identifier, detail="snippet differs from raw entry")
                    )

    return report


def format_report(report: AuditReport) -> str:
    lines: list[str] = []
    for provider in report.providers:
        status = "OK" if provider.ok else "FAIL"
        lines.append(
            f"{provider.tag}: {status} raw={provider.raw_count} covered={provider.covered_count}"
            f" missing={len(provider.missing)} stale={len(provider.stale)} duplicates={len(provider.duplicates)}"
        )
        if provider.missing:
            lines.append(f"  missing ids: {_format_ids(provider.missing)}")
        if provider.stale:
            lines.append(f"  stale ids: {_format_ids(provider.stale)}")
        for identifier, paths in provider.duplicates:
            lines.append(f"  duplicate id {identifier}: {', '.join(paths)}")
    for issue in report.file_issues:
        lines.append(f"FILE: {issue.file} - {issue.issue}")
    for mismatch in report.strict_mismatches:
        lines.append(f"MISMATCH [{mismatch.tag}] {mismatch.file} id={mismatch.reciter_id}: {mismatch.detail}")
    total_problems = sum(not provider.ok for provider in report.providers) + len(report.file_issues) + len(report.strict_mismatches)
    if total_problems == 0:
        lines.append("AUDIT PASSED: every raw entry is curated")
    else:
        lines.append(f"AUDIT FAILED: {total_problems} problem group(s)")
    return "\n".join(lines)


def _format_ids(ids: list[int]) -> str:
    rendered = [str(identifier) for identifier in ids[:50]]
    suffix = f" ... (+{len(ids) - 50} more)" if len(ids) > 50 else ""
    return ", ".join(rendered) + suffix


def report_to_json(report: AuditReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "providers": [
            {
                "tag": provider.tag,
                "raw_count": provider.raw_count,
                "covered_count": provider.covered_count,
                "missing": provider.missing,
                "stale": provider.stale,
                "duplicates": [{"id": identifier, "files": paths} for identifier, paths in provider.duplicates],
                "ok": provider.ok,
            }
            for provider in report.providers
        ],
        "file_issues": [
            {
                "file": issue.file,
                "issue": issue.issue,
                "code": issue.code,
                "section": issue.section,
                "entry_id": issue.entry_id,
            }
            for issue in report.file_issues
        ],
        "strict_mismatches": [
            {"file": mismatch.file, "tag": mismatch.tag, "id": mismatch.reciter_id, "detail": mismatch.detail}
            for mismatch in report.strict_mismatches
        ],
    }
