from __future__ import annotations

from typing import Any

from reciter_fetcher.http import HttpError
from reciter_fetcher.providers.base import ProviderResult


class Mp3QuranProvider:
    name = "mp3quran"
    output_directory = "mp3quran"
    catalog_url = "https://www.mp3quran.net/api/v3/reciters?language=eng"

    def fetch_validate_verify(self, http: Any, config: Any) -> ProviderResult:
        payload = http.get_json(self.catalog_url)
        if not isinstance(payload, dict) or not isinstance(payload.get("reciters"), list):
            raise HttpError("MP3Quran response is missing reciters")

        reciters = payload["reciters"]
        identifiers: set[int] = set()
        moshaf_count = 0
        first_probe_url: str | None = None
        for reciter in reciters:
            if not isinstance(reciter, dict) or not isinstance(reciter.get("id"), int):
                raise HttpError("MP3Quran reciter has no integer id")
            if reciter["id"] in identifiers:
                raise HttpError(f"MP3Quran duplicate reciter id: {reciter['id']}")
            identifiers.add(reciter["id"])
            moshaf_list = reciter.get("moshaf")
            if not isinstance(moshaf_list, list):
                raise HttpError(f"MP3Quran reciter {reciter['id']} has no moshaf list")
            for moshaf in moshaf_list:
                if not isinstance(moshaf, dict):
                    raise HttpError("MP3Quran moshaf is not an object")
                server = moshaf.get("server")
                surah_total = moshaf.get("surah_total")
                surah_list = moshaf.get("surah_list")
                if not isinstance(server, str) or not isinstance(surah_total, int) or not isinstance(surah_list, str):
                    raise HttpError("MP3Quran moshaf is missing audio metadata")
                surahs = [item for item in surah_list.split(",") if item]
                if len(surahs) != surah_total:
                    raise HttpError("MP3Quran moshaf surah_total does not match surah_list")
                moshaf_count += 1
                if first_probe_url is None and surahs:
                    first_probe_url = f"{server.rstrip('/')}/{int(surahs[0]):03d}.mp3"

        if not reciters or first_probe_url is None:
            raise HttpError("MP3Quran catalog has no probeable recitation")
        http.probe_url(first_probe_url)
        return ProviderResult(
            outputs={"reciters.json": payload},
            counts={"reciters": len(reciters), "moshaf": moshaf_count},
        )

