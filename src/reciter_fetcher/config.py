from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FetcherConfig:
    root: Path
    qf_client_id: str | None
    qf_client_secret: str | None


def load_environment(root: Path) -> FetcherConfig:
    dotenv = root / ".env"
    if dotenv.exists():
        for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"").strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

    return FetcherConfig(
        root=root,
        qf_client_id=os.environ.get("QF_CLIENT_ID"),
        qf_client_secret=os.environ.get("QF_CLIENT_SECRET"),
    )

