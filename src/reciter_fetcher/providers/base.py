from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderResult:
    outputs: dict[str, Any]
    counts: dict[str, int]


class Provider(Protocol):
    name: str
    output_directory: str

    def fetch_validate_verify(self, http: Any, config: Any) -> ProviderResult: ...

