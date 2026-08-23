from __future__ import annotations

import base64
from typing import Any

from reciter_fetcher.http import HttpError
from reciter_fetcher.providers.base import ProviderResult


class QuranFoundationProvider:
    name = "quran-foundation"
    output_directory = "quran_foundation"
    oauth_url = "https://oauth2.quran.foundation/oauth2/token"
    api_base = "https://apis.quran.foundation/content/api/v4"
    user_agent = "itqan-reciter-catalog/1.0"

    def fetch_validate_verify(self, http: Any, config: Any) -> ProviderResult:
        if not config or not config.qf_client_id or not config.qf_client_secret:
            raise HttpError("QF_CLIENT_ID and QF_CLIENT_SECRET are required for Quran Foundation")

        for refresh_attempt in range(2):
            token = self._get_token(http, config)
            headers = {
                "Accept": "application/json",
                "User-Agent": self.user_agent,
                "x-auth-token": token,
                "x-client-id": config.qf_client_id,
            }
            try:
                return self._fetch_validate_verify(http, headers)
            except HttpError as error:
                if error.status != 401 or refresh_attempt == 1:
                    raise

        raise AssertionError("Quran Foundation token refresh loop exhausted")

    def _get_token(self, http: Any, config: Any) -> str:
        basic = base64.b64encode(f"{config.qf_client_id}:{config.qf_client_secret}".encode()).decode()
        payload = http.post_form(
            self.oauth_url,
            {"grant_type": "client_credentials", "scope": "content"},
            {
                "Accept": "application/json",
                "Authorization": f"Basic {basic}",
                "User-Agent": self.user_agent,
            },
        )
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise HttpError("Quran Foundation did not return an access token")
        return token

    def _fetch_validate_verify(self, http: Any, headers: dict[str, str]) -> ProviderResult:
        qfs_url = f"{self.api_base}/resources/chapter_reciters?language=en"
        qfa_url = f"{self.api_base}/resources/recitations?language=en"
        qfs = http.get_json(qfs_url, headers)
        qfa = http.get_json(qfa_url, headers)
        if not isinstance(qfs, dict) or not isinstance(qfs.get("reciters"), list):
            raise HttpError("Quran Foundation chapter-reciter response is invalid")
        if not isinstance(qfa, dict) or not isinstance(qfa.get("recitations"), list):
            raise HttpError("Quran Foundation ayah-recitation response is invalid")
        self._unique_ids(qfs["reciters"], "Quran Foundation chapter-reciter")
        self._unique_ids(qfa["recitations"], "Quran Foundation ayah-recitation")
        if not qfs["reciters"] or not qfa["recitations"]:
            raise HttpError("Quran Foundation catalog is empty")

        chapter_reciter_id = qfs["reciters"][0]["id"]
        ayah_recitation_id = qfa["recitations"][0]["id"]
        chapter_audio = http.get_json(f"{self.api_base}/chapter_recitations/{chapter_reciter_id}", headers)
        ayah_audio = http.get_json(
            f"{self.api_base}/recitations/{ayah_recitation_id}/by_chapter/1?per_page=50",
            headers,
        )
        if not isinstance(chapter_audio, dict) or not isinstance(chapter_audio.get("audio_files"), list) or not chapter_audio["audio_files"]:
            raise HttpError("Quran Foundation chapter-reciter audio probe failed")
        if not isinstance(ayah_audio, dict) or not isinstance(ayah_audio.get("audio_files"), list) or not ayah_audio["audio_files"]:
            raise HttpError("Quran Foundation ayah-recitation audio probe failed")

        return ProviderResult(
            outputs={"chapter-reciters.json": qfs, "ayah-recitations.json": qfa},
            counts={"chapter_reciters": len(qfs["reciters"]), "ayah_recitations": len(qfa["recitations"])},
        )

    @staticmethod
    def _unique_ids(entries: list[Any], label: str) -> None:
        identifiers: set[int] = set()
        for entry in entries:
            identifier = entry.get("id") if isinstance(entry, dict) else None
            if not isinstance(identifier, int):
                raise HttpError(f"{label} entry has no integer id")
            if identifier in identifiers:
                raise HttpError(f"{label} has duplicate id: {identifier}")
            identifiers.add(identifier)

