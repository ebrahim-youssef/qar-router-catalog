from __future__ import annotations

from typing import Any

from reciter_fetcher.http import HttpError
from reciter_fetcher.providers.base import ProviderResult


class EveryAyahProvider:
    name = "everyayah"
    output_directory = "everyayah"
    catalog_url = "https://everyayah.com/data/recitations.js"

    def fetch_validate_verify(self, http: Any, config: Any) -> ProviderResult:
        payload = http.get_json(self.catalog_url)
        if not isinstance(payload, dict):
            raise HttpError("EveryAyah response is not an object")
        ayah_count = payload.get("ayahCount")
        if not isinstance(ayah_count, list) or len(ayah_count) != 114:
            raise HttpError("EveryAyah response has invalid ayahCount metadata")

        recitations = [(key, value) for key, value in payload.items() if key != "ayahCount"]
        if not recitations:
            raise HttpError("EveryAyah response has no recitations")
        for identifier, recitation in recitations:
            if not isinstance(recitation, dict) or not all(
                isinstance(recitation.get(field), str) for field in ("subfolder", "name", "bitrate")
            ):
                raise HttpError(f"EveryAyah recitation {identifier} has invalid metadata")

        first_subfolder = recitations[0][1]["subfolder"]
        http.probe_url(f"https://everyayah.com/data/{first_subfolder}/001001.mp3")
        return ProviderResult(
            outputs={"recitations.json": payload},
            counts={"recitations": len(recitations)},
        )

