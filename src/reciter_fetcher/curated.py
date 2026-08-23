from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MISSING_NAME = "missing_name"
MISSING_SECTION = "missing_section"
INVALID_JSON = "invalid_json"
UNBALANCED_JSON = "unbalanced_json"
INVALID_PREAMBLE = "invalid_preamble"
UNKNOWN_SECTION = "unknown_section"
NAME_NOT_FIRST = "name_not_first"
MISSING_ID = "missing_id"
DUPLICATE_ID = "duplicate_id"
DUPLICATE_SECTION = "duplicate_section"

REQUIRED_SECTIONS = ("QFS", "QFA", "MP3", "EA")
SECTION_HEADER_PATTERN = re.compile(r"^\s*#+\s*(.*?)\s*$", re.MULTILINE)


def section_heading(line: str) -> str | None:
    """Return the parser's normalized section name for a Markdown heading line."""
    match = SECTION_HEADER_PATTERN.fullmatch(line)
    return match.group(1).strip().upper() if match is not None else None


def remove_trailing_json_commas(text: str) -> str:
    """Remove trailing JSON commas without changing comma-like text in strings."""
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        character = text[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                output.extend(text[index + 1:lookahead])
                index = lookahead
                continue
        output.append(character)
        index += 1
    return "".join(output)


@dataclass(frozen=True)
class CuratedIssue:
    code: str
    file: str
    section: str | None
    entry_id: int | None
    message: str


@dataclass(frozen=True)
class CuratedEntry:
    section: str
    identifier: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class CuratedReciter:
    slug: str
    file: str
    name_en: str | None
    name_ar: str | None
    sections: dict[str, list[CuratedEntry]]


@dataclass(frozen=True)
class _ScannedEntry:
    identifier: int | None
    payload: dict[str, Any]


def canonical_id(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _read_string(text: str, start: int) -> int:
    index = start + 1
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 2
            continue
        if character == '"':
            return index + 1
        index += 1
    raise ValueError("unterminated string")


def _read_block(text: str, start: int) -> tuple[int, int]:
    depth = 0
    index = start
    while index < len(text):
        character = text[index]
        if character == '"':
            index = _read_string(text, index)
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
        index += 1
    raise ValueError("unbalanced braces")


def _split_section_blocks(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        heading = section_heading(line)
        if heading is not None:
            if current is not None:
                sections.setdefault(current, []).append("\n".join(buffer))
            current = heading
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections.setdefault(current, []).append("\n".join(buffer))
    return sections


def split_sections(text: str) -> dict[str, str]:
    """Return the last block for each header for legacy audit callers."""
    return {section: blocks[-1] for section, blocks in _split_section_blocks(text).items()}


def parse_name_header(sections: dict[str, str]) -> tuple[str | None, str | None]:
    name_block = sections.get("NAME", "")
    en_match = re.search(r"^en:\s*(.+)$", name_block, re.MULTILINE)
    ar_match = re.search(r"^ar:\s*(.+)$", name_block, re.MULTILINE)
    name_en = en_match.group(1).strip() if en_match else None
    name_ar = ar_match.group(1).strip() if ar_match else None
    return name_en or None, name_ar or None


def _preceding_key(text: str, object_start: int) -> int | None:
    index = object_start - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    if index < 0 or text[index] != ":":
        return None
    index -= 1
    while index >= 0 and text[index].isspace():
        index -= 1
    if index < 0 or text[index] != '"':
        return None
    closing_quote = index
    index -= 1
    while index >= 0 and text[index].isdigit():
        index -= 1
    if index < 0 or text[index] != '"' or index + 1 == closing_quote:
        return None
    return canonical_id(text[index + 1:closing_quote])


def _scan_section_items(
    content: str,
    *,
    section: str,
    file_name: str,
    validate_content: bool = True,
) -> list[_ScannedEntry | CuratedIssue]:
    items: list[_ScannedEntry | CuratedIssue] = []
    index = 0

    while index < len(content):
        character = content[index]
        if character == "{":
            try:
                block_start, block_end = _read_block(content, index)
            except ValueError as error:
                items.append(CuratedIssue(UNBALANCED_JSON, file_name, section, None, str(error)))
                break
            snippet = content[block_start:block_end]
            try:
                parsed = json.loads(remove_trailing_json_commas(snippet))
            except json.JSONDecodeError as error:
                items.append(
                    CuratedIssue(INVALID_JSON, file_name, section, None, f"invalid JSON snippet: {error}")
                )
                index = block_end
                continue

            identifier = _preceding_key(content, index) if section in {"EA", "GENERIC"} else None
            if section not in {"EA", "GENERIC"} and isinstance(parsed, dict):
                identifier = canonical_id(parsed.get("id"))
            elif section == "GENERIC" and identifier is None and isinstance(parsed, dict):
                identifier = canonical_id(parsed.get("id"))
            if not isinstance(parsed, dict):
                items.append(CuratedIssue(INVALID_JSON, file_name, section, None, "JSON snippet is not an object"))
            else:
                items.append(_ScannedEntry(identifier=identifier, payload=parsed))
            index = block_end
            continue
        if character.isspace() or character == ",":
            index += 1
            continue
        if character == '"':
            try:
                string_end = _read_string(content, index)
            except ValueError as error:
                items.append(CuratedIssue(UNBALANCED_JSON, file_name, section, None, str(error)))
                break
            if not validate_content:
                index = string_end
                continue
            if section == "EA" and content[index + 1:string_end - 1].isdigit():
                next_index = string_end
                while next_index < len(content) and content[next_index].isspace():
                    next_index += 1
                if next_index < len(content) and content[next_index] == ":":
                    next_index += 1
                    while next_index < len(content) and content[next_index].isspace():
                        next_index += 1
                    if next_index < len(content) and content[next_index] == "{":
                        index = next_index
                        continue
            items.append(CuratedIssue(INVALID_JSON, file_name, section, None, "unexpected section content"))
            break
        if validate_content:
            items.append(CuratedIssue(INVALID_JSON, file_name, section, None, "unexpected section content"))
            break
        index += 1
    return items


def _parse_section_entries(
    content: str,
    *,
    section: str,
    file_name: str,
) -> tuple[list[CuratedEntry], list[CuratedIssue]]:
    items = _scan_section_items(content, section=section, file_name=file_name)
    entries: list[CuratedEntry] = []
    issues: list[CuratedIssue] = []
    seen_ids: set[int] = set()
    for item in items:
        if isinstance(item, CuratedIssue):
            issues.append(item)
        elif item.identifier is None:
            issues.append(CuratedIssue(MISSING_ID, file_name, section, None, "snippet has no id"))
        else:
            if item.identifier in seen_ids:
                issues.append(
                    CuratedIssue(DUPLICATE_ID, file_name, section, item.identifier, f"duplicate id {item.identifier}")
                )
            seen_ids.add(item.identifier)
            entries.append(CuratedEntry(section=section, identifier=item.identifier, payload=item.payload))
    return entries, issues


def parse_curated_text(text: str, *, file_name: str) -> tuple[CuratedReciter, list[CuratedIssue]]:
    section_blocks = _split_section_blocks(text)
    raw_sections = {section: blocks[0] for section, blocks in section_blocks.items()}
    name_en, name_ar = parse_name_header(raw_sections)
    issues: list[CuratedIssue] = []
    headings: list[str] = []
    preamble: list[str] = []
    saw_heading = False
    for line in text.splitlines():
        stripped = line.strip()
        heading = section_heading(line)
        if heading is not None:
            saw_heading = True
            headings.append(heading)
        elif not saw_heading and stripped:
            preamble.append(stripped)
    if preamble:
        issues.append(
            CuratedIssue(
                INVALID_PREAMBLE,
                file_name,
                None,
                None,
                "non-whitespace content appears before the first section header",
            )
        )
    if headings and headings[0] != "NAME":
        issues.append(
            CuratedIssue(NAME_NOT_FIRST, file_name, headings[0] or None, None, "#name must be the first section header")
        )
    allowed_sections = {"NAME", *REQUIRED_SECTIONS}
    for heading in headings:
        if heading not in allowed_sections:
            issues.append(
                CuratedIssue(
                    UNKNOWN_SECTION,
                    file_name,
                    heading or None,
                    None,
                    f"unsupported section header #{heading or '<empty>'}; register the provider before adding data",
                )
            )
    for section, blocks in section_blocks.items():
        if len(blocks) > 1:
            issues.append(CuratedIssue(DUPLICATE_SECTION, file_name, section, None, "duplicate section header"))
    if name_en is None or name_ar is None:
        issues.append(
            CuratedIssue(MISSING_NAME, file_name, "NAME", None, "missing #name header with en:/ar: lines")
        )

    sections: dict[str, list[CuratedEntry]] = {}
    for section in REQUIRED_SECTIONS:
        contents = section_blocks.get(section)
        if contents is None:
            issues.append(CuratedIssue(MISSING_SECTION, file_name, section, None, "missing section header"))
            continue
        entries: list[CuratedEntry] = []
        entry_issues: list[CuratedIssue] = []
        for content in contents:
            parsed_entries, parsed_issues = _parse_section_entries(content, section=section, file_name=file_name)
            entries.extend(parsed_entries)
            entry_issues.extend(parsed_issues)
        sections[section] = entries
        issues.extend(entry_issues)

    return (
        CuratedReciter(
            slug=Path(file_name).stem,
            file=file_name,
            name_en=name_en,
            name_ar=name_ar,
            sections=sections,
        ),
        issues,
    )


def load_curated_reciters(root: Path) -> tuple[list[CuratedReciter], list[CuratedIssue]]:
    directory = root / "data" / "curated" / "reciters"
    if not directory.is_dir():
        return [], []

    reciters: list[CuratedReciter] = []
    issues: list[CuratedIssue] = []
    for path in sorted(directory.glob("*.md")):
        reciter, parsed_issues = parse_curated_text(path.read_text(encoding="utf-8"), file_name=path.name)
        reciters.append(reciter)
        issues.extend(parsed_issues)
    return reciters, issues
