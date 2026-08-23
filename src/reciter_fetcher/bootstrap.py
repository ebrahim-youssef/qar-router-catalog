from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from reciter_fetcher.catalog import build_catalog, semantic_catalog
from reciter_fetcher.curated import (
    CuratedEntry,
    CuratedReciter,
    MISSING_NAME,
    NAME_NOT_FIRST,
    SECTION_HEADER_PATTERN,
    load_curated_reciters,
    remove_trailing_json_commas,
)
from reciter_fetcher.storage import atomic_write_text


_HEADER = SECTION_HEADER_PATTERN


@dataclass(frozen=True)
class CatalogComparison:
    lost: list[dict[str, Any]]
    changed: list[dict[str, Any]]
    added: list[dict[str, Any]]
    allowed_removed: list[dict[str, Any]]


@dataclass(frozen=True)
class MigrationEdit:
    file: str
    section: str
    entry_id: int | None
    field: str
    old_value: Any
    new_value: Any
    source_path: str


@dataclass(frozen=True)
class MigrationConflict:
    file: str
    section: str
    entry_id: int | None
    field: str
    catalog_value: Any
    markdown_value: Any
    catalog_path: str


@dataclass(frozen=True)
class MigrationPlan:
    backfills: list[MigrationEdit]
    conflicts: list[MigrationConflict]
    comparison: CatalogComparison


class MigrationError(ValueError):
    pass


def _stable(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))


def _binding_item(key: tuple[Any, ...], value: dict[str, Any], *, value_key: str = "value") -> dict[str, Any]:
    slug, riwaya, style, provider, identity = key
    return {
        "kind": "binding",
        "slug": slug,
        "riwaya": riwaya,
        "style": style,
        "provider": provider,
        "identity": identity,
        value_key: value,
    }


def _dead_legacy_bindings(legacy: dict[str, Any]) -> list[dict[str, Any]]:
    removed: list[dict[str, Any]] = []
    for slug, reciter_node in legacy.items():
        if not isinstance(reciter_node, dict):
            continue
        for style, style_node in reciter_node.get("styles", {}).items():
            for riwaya, riwaya_node in style_node.get("riwayat", {}).items():
                bindings = riwaya_node.get("providers", {}).get("everyAyah", [])
                for binding in bindings:
                    if isinstance(binding, dict) and binding.get("dead") is True:
                        key = (slug, riwaya, style, "everyAyah", binding.get("everyAyahId"))
                        removed.append(_binding_item(key, binding))
    return _stable(removed)


def compare_catalogs(legacy: dict[str, Any], candidate: dict[str, Any]) -> CatalogComparison:
    old = semantic_catalog(legacy, legacy=True)
    new = semantic_catalog(candidate)
    lost: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []

    old_names = old["names"]
    new_names = new["names"]
    for slug in old_names.keys() - new_names.keys():
        lost.append({"kind": "name", "slug": slug, "value": old_names[slug]})
    for slug in new_names.keys() - old_names.keys():
        added.append({"kind": "name", "slug": slug, "value": new_names[slug]})
    for slug in old_names.keys() & new_names.keys():
        if old_names[slug] != new_names[slug]:
            changed.append(
                {
                    "kind": "name",
                    "slug": slug,
                    "legacy": old_names[slug],
                    "candidate": new_names[slug],
                }
            )

    old_bindings = old["bindings"]
    new_bindings = new["bindings"]
    for key in old_bindings.keys() - new_bindings.keys():
        lost.append(_binding_item(key, old_bindings[key]))
    for key in new_bindings.keys() - old_bindings.keys():
        added.append(_binding_item(key, new_bindings[key]))
    for key in old_bindings.keys() & new_bindings.keys():
        if old_bindings[key] != new_bindings[key]:
            item = _binding_item(key, old_bindings[key], value_key="legacy")
            item["candidate"] = new_bindings[key]
            changed.append(item)

    return CatalogComparison(
        lost=_stable(lost),
        changed=_stable(changed),
        added=_stable(added),
        allowed_removed=_dead_legacy_bindings(legacy),
    )


def _explicit_name(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _legacy_qfa_bindings(node: dict[str, Any], entry_id: int) -> list[tuple[str, str, str]]:
    matches: list[tuple[str, str, str]] = []
    for style, style_node in node.get("styles", {}).items():
        if not isinstance(style_node, dict):
            continue
        for riwaya, riwaya_node in style_node.get("riwayat", {}).items():
            if not isinstance(riwaya_node, dict):
                continue
            bindings = riwaya_node.get("providers", {}).get("quranFoundationAyah", [])
            for index, binding in enumerate(bindings):
                if isinstance(binding, dict) and type(binding.get("id")) is int and binding["id"] == entry_id:
                    path = (
                        f"styles.{style}.riwayat.{riwaya}.providers."
                        f"quranFoundationAyah[{index}]"
                    )
                    matches.append((riwaya, style, path))
    return matches


def _name_plan(reciter: CuratedReciter, legacy_node: dict[str, Any]) -> tuple[list[MigrationEdit], list[MigrationConflict]]:
    edits: list[MigrationEdit] = []
    conflicts: list[MigrationConflict] = []
    legacy_name = legacy_node.get("name") if isinstance(legacy_node.get("name"), dict) else {}
    for language, markdown_value in (("en", reciter.name_en), ("ar", reciter.name_ar)):
        catalog_value = legacy_name.get(language)
        field = f"name.{language}"
        source_path = f"{reciter.slug}.name.{language}"
        if markdown_value is None:
            if _explicit_name(catalog_value):
                edits.append(MigrationEdit(reciter.file, "NAME", None, field, None, catalog_value, source_path))
            else:
                conflicts.append(
                    MigrationConflict(
                        reciter.file,
                        "NAME",
                        None,
                        field,
                        catalog_value,
                        None,
                        source_path,
                    )
                )
        elif _explicit_name(catalog_value) and markdown_value != catalog_value:
            conflicts.append(
                MigrationConflict(
                    reciter.file,
                    "NAME",
                    None,
                    field,
                    catalog_value,
                    markdown_value,
                    source_path,
                )
            )
    return edits, conflicts


def _qfa_plan(reciter: CuratedReciter, legacy_node: dict[str, Any]) -> tuple[list[MigrationEdit], list[MigrationConflict]]:
    edits: list[MigrationEdit] = []
    conflicts: list[MigrationConflict] = []
    for entry in reciter.sections.get("QFA", []):
        matches = _legacy_qfa_bindings(legacy_node, entry.identifier)
        if not matches:
            continue
        classifications = {(riwaya, style) for riwaya, style, _ in matches}
        if len(classifications) != 1:
            paths = sorted(path for _, _, path in matches)
            for field, markdown_value in (
                ("riwaya", entry.payload.get("riwaya")),
                ("catalog_style", entry.payload.get("catalog_style")),
            ):
                conflicts.append(
                    MigrationConflict(
                        reciter.file,
                        "QFA",
                        entry.identifier,
                        field,
                        sorted(classifications),
                        markdown_value,
                        ", ".join(paths),
                    )
                )
            continue

        riwaya, style = next(iter(classifications))
        source_path = matches[0][2]
        desired_fields = [("riwaya", riwaya)]
        if entry.payload.get("style") is None:
            desired_fields.append(("catalog_style", style))
        for field, catalog_value in desired_fields:
            markdown_value = entry.payload.get(field)
            if markdown_value in (None, ""):
                edits.append(
                    MigrationEdit(
                        reciter.file,
                        "QFA",
                        entry.identifier,
                        field,
                        markdown_value,
                        catalog_value,
                        source_path,
                    )
                )
            elif markdown_value != catalog_value:
                conflicts.append(
                    MigrationConflict(
                        reciter.file,
                        "QFA",
                        entry.identifier,
                        field,
                        catalog_value,
                        markdown_value,
                        source_path,
                    )
                )
    return edits, conflicts


def _prospective_reciters(
    reciters: list[CuratedReciter], edits: list[MigrationEdit]
) -> list[CuratedReciter]:
    by_file: dict[str, list[MigrationEdit]] = {}
    for edit in edits:
        by_file.setdefault(edit.file, []).append(edit)
    result: list[CuratedReciter] = []
    for reciter in reciters:
        reciter_edits = by_file.get(reciter.file, [])
        name_en = reciter.name_en
        name_ar = reciter.name_ar
        sections = {section: list(entries) for section, entries in reciter.sections.items()}
        for edit in reciter_edits:
            if edit.field == "name.en":
                name_en = edit.new_value
            elif edit.field == "name.ar":
                name_ar = edit.new_value
            elif edit.section == "QFA":
                updated: list[CuratedEntry] = []
                for entry in sections.get("QFA", []):
                    if entry.identifier == edit.entry_id:
                        payload = copy.deepcopy(entry.payload)
                        payload[edit.field] = edit.new_value
                        entry = replace(entry, payload=payload)
                    updated.append(entry)
                sections["QFA"] = updated
        result.append(replace(reciter, name_en=name_en, name_ar=name_ar, sections=sections))
    return result


def _load_legacy(root: Path) -> dict[str, Any]:
    path = root / "data" / "curated" / "catalog.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError(f"cannot read legacy catalog {path}: {error}") from error
    if not isinstance(payload, dict):
        raise MigrationError(f"legacy catalog {path} must contain a JSON object")
    migrated_slugs = sorted(
        slug for slug, node in payload.items() if isinstance(node, dict) and "riwayat" in node
    )
    if migrated_slugs:
        example = migrated_slugs[0]
        raise MigrationError(
            "catalog already uses the generated riwayat -> styles schema "
            f"(for example {example!r}); bootstrap accepts only the one-time legacy styles -> riwayat schema"
        )
    return payload


def build_migration(root: Path) -> MigrationPlan:
    legacy = _load_legacy(root)
    reciters, parse_issues = load_curated_reciters(root)
    missing_name_files = {issue.file for issue in parse_issues if issue.code == MISSING_NAME}
    files_with_name_headers: set[str] = set()
    for reciter in reciters:
        path = root / "data" / "curated" / "reciters" / reciter.file
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise MigrationError(f"cannot read curated file {path}: {error}") from error
        if any(match.group(1).upper() == "NAME" for match in _HEADER.finditer(text)):
            files_with_name_headers.add(reciter.file)
    unsafe = [
        issue
        for issue in parse_issues
        if issue.code != MISSING_NAME
        and not (
            issue.code == NAME_NOT_FIRST
            and issue.file in missing_name_files
            and issue.file not in files_with_name_headers
        )
    ]
    if unsafe:
        details = "; ".join(
            f"{issue.file} {issue.section or '-'} {issue.entry_id}: {issue.code}: {issue.message}"
            for issue in unsafe
        )
        raise MigrationError(details)

    edits: list[MigrationEdit] = []
    conflicts: list[MigrationConflict] = []
    for reciter in reciters:
        legacy_node = legacy.get(reciter.slug)
        if not isinstance(legacy_node, dict):
            continue
        name_edits, name_conflicts = _name_plan(reciter, legacy_node)
        qfa_edits, qfa_conflicts = _qfa_plan(reciter, legacy_node)
        edits.extend(name_edits)
        edits.extend(qfa_edits)
        conflicts.extend(name_conflicts)
        conflicts.extend(qfa_conflicts)

    edits = sorted(edits, key=lambda item: (item.file, item.section, item.entry_id or -1, item.field))
    conflicts = sorted(
        conflicts,
        key=lambda item: (item.file, item.section, item.entry_id or -1, item.field, item.catalog_path),
    )
    prospective = _prospective_reciters(reciters, edits)
    candidate, catalog_issues = build_catalog(prospective)
    if catalog_issues:
        details = "; ".join(
            f"{issue.file} {issue.section} {issue.entry_id}: {issue.code}: {issue.message}"
            for issue in sorted(
                catalog_issues,
                key=lambda item: (
                    item.file,
                    item.section,
                    item.entry_id if item.entry_id is not None else -1,
                    item.code,
                    item.message,
                ),
            )
        )
        raise MigrationError(details)
    return MigrationPlan(edits, conflicts, compare_catalogs(legacy, candidate))


def _object_end(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    raise MigrationError("unbalanced JSON while applying migration")


def _qfa_object(text: str, entry_id: int) -> tuple[int, int, dict[str, Any]]:
    headers = list(_HEADER.finditer(text))
    for position, header in enumerate(headers):
        if header.group(1).upper() != "QFA":
            continue
        start = header.end()
        end = headers[position + 1].start() if position + 1 < len(headers) else len(text)
        cursor = start
        while cursor < end:
            object_start = text.find("{", cursor, end)
            if object_start == -1:
                break
            object_end = _object_end(text, object_start)
            snippet = text[object_start:object_end]
            payload = json.loads(remove_trailing_json_commas(snippet))
            if isinstance(payload, dict) and type(payload.get("id")) is int and payload["id"] == entry_id:
                return object_start, object_end, payload
            cursor = object_end
    raise MigrationError(f"QFA provider id {entry_id} was not found while applying migration")


def _apply_json_field(text: str, edit: MigrationEdit) -> str:
    assert edit.entry_id is not None
    start, end, payload = _qfa_object(text, edit.entry_id)
    if payload.get(edit.field) != edit.old_value:
        raise MigrationError(f"stale migration edit for {edit.file} QFA {edit.entry_id} {edit.field}")
    snippet = text[start:end]
    encoded = json.dumps(edit.new_value, ensure_ascii=False)
    field_pattern = re.compile(
        rf'(?m)(^[ \t]*"{re.escape(edit.field)}"[ \t]*:[ \t]*)(null|"(?:\\.|[^"\\])*")'
    )
    if edit.field in payload:
        replacement, count = field_pattern.subn(rf"\g<1>{encoded}", snippet, count=1)
        if count != 1:
            raise MigrationError(f"cannot replace {edit.field} in {edit.file}")
    else:
        indent_match = re.search(r'(?m)^([ \t]+)"[^"\n]+"[ \t]*:', snippet)
        indent = indent_match.group(1) if indent_match else "  "
        close = len(snippet) - 1
        before_close = snippet[:close].rstrip()
        whitespace = snippet[len(before_close):close]
        comma = "" if before_close.endswith(("{", ",")) else ","
        replacement = f'{before_close}{comma}\n{indent}"{edit.field}": {encoded}{whitespace}}}'
    return text[:start] + replacement + text[end:]


def _apply_name_fields(text: str, edits: list[MigrationEdit]) -> str:
    values = {edit.field.removeprefix("name."): edit.new_value for edit in edits}
    headers = list(_HEADER.finditer(text))
    name_header = next((header for header in headers if header.group(1).upper() == "NAME"), None)
    if name_header is None:
        lines = ["#name"]
        for language in ("en", "ar"):
            if language in values:
                lines.append(f"{language}:{values[language]}")
        return "\n".join(lines) + "\n\n" + text

    next_header = next((header for header in headers if header.start() > name_header.start()), None)
    block_end = next_header.start() if next_header is not None else len(text)
    block = text[name_header.start():block_end]
    for language in ("en", "ar"):
        if language not in values:
            continue
        pattern = re.compile(rf"(?m)^{language}:[^\n]*(?:\n|$)")
        line = f"{language}:{values[language]}\n"
        if pattern.search(block):
            block = pattern.sub(line, block, count=1)
        elif language == "en":
            insertion = block.find("\n") + 1
            block = block[:insertion] + line + block[insertion:]
        else:
            en_line = re.search(r"(?m)^en:[^\n]*(?:\n|$)", block)
            insertion = en_line.end() if en_line else block.find("\n") + 1
            block = block[:insertion] + line + block[insertion:]
    return text[:name_header.start()] + block + text[block_end:]


def apply_migration(root: Path, plan: MigrationPlan) -> None:
    by_file: dict[str, list[MigrationEdit]] = {}
    for edit in plan.backfills:
        by_file.setdefault(edit.file, []).append(edit)
    for file_name in sorted(by_file):
        path = root / "data" / "curated" / "reciters" / file_name
        text = path.read_text(encoding="utf-8")
        edits = by_file[file_name]
        name_edits = [edit for edit in edits if edit.section == "NAME"]
        if name_edits:
            text = _apply_name_fields(text, name_edits)
        for edit in sorted(
            (item for item in edits if item.section == "QFA"),
            key=lambda item: (item.entry_id or -1, item.field),
        ):
            text = _apply_json_field(text, edit)
        atomic_write_text(path, text)


def report_json(plan: MigrationPlan) -> dict[str, Any]:
    return {
        "backfills": [asdict(edit) for edit in plan.backfills],
        "conflicts": [asdict(conflict) for conflict in plan.conflicts],
        "legacyLosses": [*plan.comparison.lost, *plan.comparison.changed],
        "additions": plan.comparison.added,
    }
