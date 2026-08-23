from __future__ import annotations

import argparse
import json
from pathlib import Path

from reciter_fetcher.audit import audit, format_report, report_to_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit curated reciter data against raw provider catalogs")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--strict", action="store_true", help="also verify snippets deep-equal raw entries")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON report with stable issue codes")
    args = parser.parse_args(argv)

    report = audit(args.root.resolve(), strict=args.strict)
    if args.json:
        print(json.dumps(report_to_json(report), ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
