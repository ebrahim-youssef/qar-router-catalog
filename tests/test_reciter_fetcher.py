from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reciter_fetcher.config import load_environment
from reciter_fetcher.http import HttpClient, HttpError
from reciter_fetcher.providers.everyayah import EveryAyahProvider
from reciter_fetcher.providers.mp3quran import Mp3QuranProvider
from reciter_fetcher.providers.quran_foundation import QuranFoundationProvider
from reciter_fetcher.providers import PROVIDERS
from reciter_fetcher.runner import run_providers
from reciter_fetcher.storage import atomic_write_json


class FakeHttp:
    def __init__(self, *, responses: dict[str, object], probes: set[str] | None = None):
        self.responses = responses
        self.probes = probes or set()
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> object:
        self.calls.append(("get_json", url, headers))
        return self.responses[url]

    def post_form(self, url: str, form: dict[str, str], headers: dict[str, str]) -> object:
        self.calls.append(("post_form", url, headers))
        return self.responses[url]

    def probe_url(self, url: str) -> None:
        self.calls.append(("probe_url", url, None))
        if url not in self.probes:
            raise HttpError(f"probe failed: {url}")


class ReciterFetcherTests(unittest.TestCase):
    def test_dotenv_does_not_override_exported_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text(
                "QF_CLIENT_ID=file-id\nQF_CLIENT_SECRET=file-secret\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"QF_CLIENT_ID": "environment-id"}, clear=True):
                config = load_environment(root)

        self.assertEqual("environment-id", config.qf_client_id)
        self.assertEqual("file-secret", config.qf_client_secret)

    def test_atomic_write_json_replaces_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nested" / "catalog.json"
            atomic_write_json(output, {"reciters": [1, 2]})

            self.assertEqual(
                '{\n  "reciters": [\n    1,\n    2\n  ]\n}\n',
                output.read_text(encoding="utf-8"),
            )

    def test_mp3quran_fetches_validates_and_probes_a_catalog(self) -> None:
        catalog_url = "https://www.mp3quran.net/api/v3/reciters?language=eng"
        probe_url = "https://audio.example/001.mp3"
        http = FakeHttp(
            responses={
                catalog_url: {
                    "reciters": [
                        {
                            "id": 7,
                            "name": "Example",
                            "moshaf": [
                                {
                                    "id": 10,
                                    "server": "https://audio.example/",
                                    "surah_total": 2,
                                    "surah_list": "1,2",
                                }
                            ],
                        }
                    ]
                }
            },
            probes={probe_url},
        )

        result = Mp3QuranProvider().fetch_validate_verify(http, None)

        self.assertEqual(1, result.counts["reciters"])
        self.assertEqual(1, result.counts["moshaf"])
        self.assertIn("reciters.json", result.outputs)
        self.assertIn(("probe_url", probe_url, None), http.calls)

    def test_mp3quran_rejects_duplicate_reciter_ids(self) -> None:
        catalog_url = "https://www.mp3quran.net/api/v3/reciters?language=eng"
        http = FakeHttp(
            responses={
                catalog_url: {
                    "reciters": [
                        {"id": 7, "moshaf": []},
                        {"id": 7, "moshaf": []},
                    ]
                }
            }
        )

        with self.assertRaisesRegex(HttpError, "duplicate reciter id"):
            Mp3QuranProvider().fetch_validate_verify(http, None)

    def test_everyayah_excludes_ayah_count_and_probes_audio(self) -> None:
        catalog_url = "https://everyayah.com/data/recitations.js"
        probe_url = "https://everyayah.com/data/example/001001.mp3"
        http = FakeHttp(
            responses={
                catalog_url: {
                    "1": {"subfolder": "example", "name": "Example", "bitrate": "64kbps"},
                    "ayahCount": [1] * 114,
                }
            },
            probes={probe_url},
        )

        result = EveryAyahProvider().fetch_validate_verify(http, None)

        self.assertEqual(1, result.counts["recitations"])
        self.assertIn(("probe_url", probe_url, None), http.calls)

    def test_quran_foundation_keeps_id_domains_separate_and_sends_user_agent(self) -> None:
        oauth_url = "https://oauth2.quran.foundation/oauth2/token"
        qfs_url = "https://apis.quran.foundation/content/api/v4/resources/chapter_reciters?language=en"
        qfa_url = "https://apis.quran.foundation/content/api/v4/resources/recitations?language=en"
        qfs_probe_url = "https://apis.quran.foundation/content/api/v4/chapter_recitations/11"
        qfa_probe_url = "https://apis.quran.foundation/content/api/v4/recitations/22/by_chapter/1?per_page=50"
        http = FakeHttp(
            responses={
                oauth_url: {"access_token": "token"},
                qfs_url: {"reciters": [{"id": 11, "name": "Surah"}]},
                qfa_url: {"recitations": [{"id": 22, "reciter_name": "Ayah"}]},
                qfs_probe_url: {"audio_files": [{"audio_url": "https://audio.example/001.mp3"}]},
                qfa_probe_url: {"audio_files": [{"url": "https://audio.example/001001.mp3"}]},
            }
        )
        config = type("Config", (), {"qf_client_id": "id", "qf_client_secret": "secret"})()

        result = QuranFoundationProvider().fetch_validate_verify(http, config)

        self.assertEqual(1, result.counts["chapter_reciters"])
        self.assertEqual(1, result.counts["ayah_recitations"])
        qfs_headers = next(headers for method, url, headers in http.calls if method == "get_json" and url == qfs_url)
        self.assertEqual("itqan-reciter-catalog/1.0", qfs_headers["User-Agent"])
        self.assertEqual("token", qfs_headers["x-auth-token"])

    def test_quran_foundation_refreshes_token_once_after_unauthorized_response(self) -> None:
        oauth_url = "https://oauth2.quran.foundation/oauth2/token"
        qfs_url = "https://apis.quran.foundation/content/api/v4/resources/chapter_reciters?language=en"
        qfa_url = "https://apis.quran.foundation/content/api/v4/resources/recitations?language=en"
        qfs_probe_url = "https://apis.quran.foundation/content/api/v4/chapter_recitations/11"
        qfa_probe_url = "https://apis.quran.foundation/content/api/v4/recitations/22/by_chapter/1?per_page=50"

        class RefreshingHttp(FakeHttp):
            def __init__(self):
                super().__init__(
                    responses={
                        oauth_url: {"access_token": "token"},
                        qfs_url: {"reciters": [{"id": 11}]},
                        qfa_url: {"recitations": [{"id": 22}]},
                        qfs_probe_url: {"audio_files": [{}]},
                        qfa_probe_url: {"audio_files": [{}]},
                    }
                )
                self.unauthorized_once = True

            def get_json(self, url, headers=None):
                if url == qfs_url and self.unauthorized_once:
                    self.unauthorized_once = False
                    raise HttpError("expired", status=401)
                return super().get_json(url, headers)

        http = RefreshingHttp()
        config = type("Config", (), {"qf_client_id": "id", "qf_client_secret": "secret"})()

        result = QuranFoundationProvider().fetch_validate_verify(http, config)

        self.assertEqual(1, result.counts["chapter_reciters"])
        self.assertEqual(2, sum(1 for method, url, _ in http.calls if method == "post_form" and url == oauth_url))

    def test_provider_registry_is_extensible_by_provider_key(self) -> None:
        self.assertEqual({"quran-foundation", "mp3quran", "everyayah"}, set(PROVIDERS))

    def test_runner_keeps_failed_provider_output_and_returns_failure(self) -> None:
        class SuccessfulProvider:
            name = "success"

            def fetch_validate_verify(self, http, config):
                from reciter_fetcher.providers.base import ProviderResult

                return ProviderResult(outputs={"catalog.json": {"ok": True}}, counts={"items": 1})

        class FailingProvider:
            name = "failure"

            def fetch_validate_verify(self, http, config):
                raise HttpError("unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing = root / "data" / "raw" / "failure" / "catalog.json"
            existing.parent.mkdir(parents=True)
            existing.write_text('{"old": true}\n', encoding="utf-8")

            summary = run_providers(
                root=root,
                providers=[SuccessfulProvider(), FailingProvider()],
                http=FakeHttp(responses={}),
                config=None,
            )

            self.assertEqual(1, summary.exit_code)
            self.assertEqual('{"old": true}\n', existing.read_text(encoding="utf-8"))
            self.assertEqual(
                {"ok": True},
                json.loads((root / "data" / "raw" / "success" / "catalog.json").read_text()),
            )

    def test_http_client_retries_transient_failures(self) -> None:
        responses = [OSError("network"), OSError("network"), b'{"ok": true}']

        with patch("reciter_fetcher.http.urlopen") as urlopen, patch("reciter_fetcher.http.time.sleep") as sleep:
            def side_effect(*args, **kwargs):
                response = responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return _Response(response)

            urlopen.side_effect = side_effect
            client = HttpClient()
            payload = client.get_json("https://example.test/catalog")

        self.assertEqual({"ok": True}, payload)
        self.assertEqual(3, urlopen.call_count)
        self.assertEqual(2, sleep.call_count)


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body


if __name__ == "__main__":
    unittest.main()
