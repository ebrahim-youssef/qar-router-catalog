from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class HttpError(RuntimeError):
    message: str
    status: int | None = None

    def __str__(self) -> str:
        return self.message


class HttpClient:
    def __init__(self, *, timeout: int = 30, attempts: int = 3) -> None:
        self.timeout = timeout
        self.attempts = attempts

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        body = self._request(Request(url, headers=headers or {}))
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise HttpError(f"Invalid JSON from {url}: {error}") from error

    def post_form(self, url: str, form: dict[str, str], headers: dict[str, str]) -> Any:
        body = urlencode(form).encode("utf-8")
        request_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            **headers,
        }
        response = self._request(Request(url, data=body, headers=request_headers, method="POST"))
        try:
            return json.loads(response)
        except json.JSONDecodeError as error:
            raise HttpError(f"Invalid JSON from {url}: {error}") from error

    def probe_url(self, url: str) -> None:
        self._request(Request(url, method="HEAD"))

    def _request(self, request: Request) -> bytes:
        for attempt in range(self.attempts):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except HTTPError as error:
                if error.code not in TRANSIENT_STATUS_CODES or attempt == self.attempts - 1:
                    raise HttpError(
                        f"HTTP {error.code} for {request.full_url}",
                        status=error.code,
                    ) from error
            except (URLError, OSError) as error:
                if attempt == self.attempts - 1:
                    raise HttpError(f"Request failed for {request.full_url}: {error}") from error

            time.sleep(2**attempt)

        raise AssertionError("retry loop exhausted")

