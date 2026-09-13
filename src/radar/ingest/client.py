"""Shared HTTP fetcher with polite crawling, retries, offline replay and provenance.

Two modes, chosen by ``settings.offline``:

* **live**  - real HTTP via httpx, rate-limited to one request/second/host, retried with
  exponential backoff. Every response is written to ``data/raw`` with its URL and timestamp
  (NFR-03 reproducibility), and optionally saved as a fixture for future offline runs.
* **offline** - no network. The same ``fetch`` call reads a recorded fixture instead, so the
  whole pipeline and the test-suite run deterministically without internet.

A "fixture" (a recorded response used to replay a source offline) is just the raw response body
plus its URL, status and retrieval time, stored as JSON under ``data/fixtures/<connector>/``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from radar.config import Settings
from radar.models import RawResponse, utcnow


def slugify(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80] or "x"


class Fetcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._last_request_at: dict[str, float] = {}
        self._client = None  # lazily created only when a live request is needed

    # -- fixtures -------------------------------------------------------------------------
    def fixture_path(self, connector: str, key: str) -> Path:
        return self.settings.fixtures_dir / connector / f"{slugify(key)}.json"

    def _load_fixture(self, connector: str, key: str) -> RawResponse | None:
        path = self.fixture_path(connector, key)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return RawResponse(connector=connector, key=key, from_fixture=True, **data)

    def _save_fixture(self, resp: RawResponse) -> None:
        path = self.fixture_path(resp.connector, resp.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "url": resp.url,
            "params": resp.params,
            "status_code": resp.status_code,
            "retrieved_at": resp.retrieved_at.isoformat(),
            "body": resp.body,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_raw(self, resp: RawResponse) -> None:
        path = self.settings.raw_dir / resp.connector / f"{slugify(resp.key)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "url": resp.url,
            "params": resp.params,
            "status_code": resp.status_code,
            "retrieved_at": resp.retrieved_at.isoformat(),
            "body": resp.body,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- rate limiting --------------------------------------------------------------------
    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        gap = self.settings.min_seconds_between_requests
        last = self._last_request_at.get(host)
        if last is not None:
            wait = gap - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request_at[host] = time.monotonic()

    # -- the one entry point --------------------------------------------------------------
    def fetch(
        self,
        connector: str,
        key: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> RawResponse:
        params = params or {}
        if self.settings.offline:
            fixture = self._load_fixture(connector, key)
            if fixture is not None:
                return fixture
            # Offline miss: return an empty 0 response so the pipeline degrades gracefully.
            return RawResponse(
                connector=connector,
                key=key,
                url=url,
                params=params,
                status_code=0,
                retrieved_at=utcnow(),
                body="",
                from_fixture=True,
            )
        return self._fetch_live(connector, key, url, params)

    def _fetch_live(
        self, connector: str, key: str, url: str, params: dict[str, str]
    ) -> RawResponse:
        import httpx  # imported lazily so offline runs need no network stack

        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": self.settings.user_agent},
                timeout=self.settings.request_timeout_seconds,
                follow_redirects=True,
            )
        last_exc: Exception | None = None
        for attempt in range(self.settings.max_retries):
            self._throttle(url)
            try:
                r = self._client.get(url, params=params)
                resp = RawResponse(
                    connector=connector,
                    key=key,
                    url=str(r.url),
                    params=params,
                    status_code=r.status_code,
                    retrieved_at=utcnow(),
                    body=r.text,
                )
                if r.status_code < 500:
                    self._save_raw(resp)
                    if self.settings.record_fixtures:
                        self._save_fixture(resp)
                    return resp
            except Exception as exc:  # network error -> back off and retry
                last_exc = exc
            time.sleep(2 ** attempt)
        if last_exc is not None:
            raise last_exc
        # exhausted retries on 5xx
        self._save_raw(resp)
        return resp

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
