from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from reciter_fetcher.storage import atomic_write_json


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    counts: dict[str, int] | None
    error: str | None


@dataclass(frozen=True)
class RunSummary:
    statuses: list[ProviderStatus]

    @property
    def exit_code(self) -> int:
        return 1 if any(status.error for status in self.statuses) else 0


def run_providers(*, root: Path, providers: Iterable[Any], http: Any, config: Any) -> RunSummary:
    provider_list = list(providers)
    statuses: list[ProviderStatus] = []
    with ThreadPoolExecutor(max_workers=len(provider_list) or 1) as executor:
        future_to_provider = {
            executor.submit(provider.fetch_validate_verify, http, config): provider
            for provider in provider_list
        }
        for future in as_completed(future_to_provider):
            provider = future_to_provider[future]
            try:
                result = future.result()
                directory = getattr(provider, "output_directory", provider.name)
                for filename, payload in result.outputs.items():
                    atomic_write_json(root / "data" / "raw" / directory / filename, payload)
                statuses.append(ProviderStatus(provider.name, result.counts, None))
            except Exception as error:
                statuses.append(ProviderStatus(provider.name, None, str(error)))
    return RunSummary(sorted(statuses, key=lambda status: status.name))

