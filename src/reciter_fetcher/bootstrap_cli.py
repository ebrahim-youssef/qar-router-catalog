from __future__ import annotations

import argparse
import json
from pathlib import Path

from reciter_fetcher.bootstrap import (
    MigrationError,
    MigrationPlan,
    apply_migration,
    build_migration,
    compare_catalogs,
    report_json,
)
from reciter_fetcher.catalog import build_catalog, serialize_catalog
from reciter_fetcher.curated import load_curated_reciters
from reciter_fetcher.storage import atomic_write_text


def _format_plan(plan: MigrationPlan) -> str:
    lines: list[str] = []
    for edit in plan.backfills:
        lines.append(
            f"BACKFILL {edit.file} {edit.section} {edit.entry_id if edit.entry_id is not None else '-'} "
            f"{edit.field}: {edit.old_value!r} -> {edit.new_value!r} from {edit.source_path}"
        )
    for conflict in plan.conflicts:
        slug = Path(conflict.file).stem
        lines.append(
            f"CONFLICT {slug} {conflict.file} {conflict.section} "
            f"{conflict.entry_id if conflict.entry_id is not None else '-'} {conflict.field}: "
            f"legacy={conflict.catalog_value!r} markdown={conflict.markdown_value!r} "
            f"catalogPath={conflict.catalog_path}"
        )
    for item in [*plan.comparison.lost, *plan.comparison.changed]:
        lines.append(f"LEGACY_LOSS {json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)}")
    for item in plan.comparison.added:
        lines.append(f"ADDITION {json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)}")
    return "\n".join(lines)


def _print_plan(plan: MigrationPlan, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report_json(plan), ensure_ascii=False, indent=2))
    else:
        text = _format_plan(plan)
        if text:
            print(text)


def _blocked(plan: MigrationPlan) -> bool:
    return bool(plan.conflicts or plan.comparison.lost or plan.comparison.changed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report or apply guarded catalog-to-Markdown backfills")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--apply", action="store_true", help="apply only reported unambiguous backfills")
    parser.add_argument("--json", action="store_true", help="emit a stable JSON report")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        plan = build_migration(root)
    except MigrationError as error:
        if args.json:
            print(json.dumps({"error": str(error)}, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR {error}")
        return 1

    _print_plan(plan, as_json=args.json)
    if not args.apply:
        return 1 if _blocked(plan) else 0

    try:
        apply_migration(root, plan)
        legacy_path = root / "data" / "curated" / "catalog.json"
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        reciters, parse_issues = load_curated_reciters(root)
        candidate, catalog_issues = build_catalog(reciters)
        if parse_issues or catalog_issues:
            return 1
        comparison = compare_catalogs(legacy, candidate)
        if plan.conflicts or comparison.lost or comparison.changed:
            return 1
        atomic_write_text(legacy_path, serialize_catalog(candidate))
    except (MigrationError, OSError, json.JSONDecodeError) as error:
        if not args.json:
            print(f"ERROR {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
