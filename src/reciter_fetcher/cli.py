from __future__ import annotations

import argparse
from pathlib import Path

from reciter_fetcher.config import load_environment
from reciter_fetcher.http import HttpClient
from reciter_fetcher.providers import PROVIDERS
from reciter_fetcher.runner import run_providers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Quran reciter catalogs")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), action="append", help="provider to refresh")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    provider_names = args.provider or list(PROVIDERS)
    providers = [PROVIDERS[name]() for name in provider_names]
    summary = run_providers(root=root, providers=providers, http=HttpClient(), config=load_environment(root))
    for status in summary.statuses:
        if status.error:
            print(f"{status.name}: FAILED - {status.error}")
        else:
            counts = ", ".join(f"{name}={count}" for name, count in status.counts.items())
            print(f"{status.name}: OK - {counts}")
    return summary.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
