"""Polite HTTP client for aikstockdata.com's static public data files."""

from __future__ import annotations

import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://aikstockdata.com/data/public"
USER_AGENT = "qc-krx/0.1 (+https://github.com/pinjoy99/qc-krx)"


class NotModified(Exception):
    """Raised when a conditional request returns 304."""


class Client:
    """Thread-safe client with retries, a global request rate limit and ETag support."""

    def __init__(self, base_url: str = BASE_URL, min_interval: float = 0.1, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.timeout = timeout
        self._lock = threading.Lock()
        self._next_at = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        retry = Retry(
            total=5,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            self._next_at = max(now, self._next_at) + self.min_interval
        if wait > 0:
            time.sleep(wait)

    def get(self, path: str, etag: str | None = None) -> requests.Response:
        """GET ``path`` (relative to the public data root). Raises NotModified on 304."""
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        headers = {"If-None-Match": etag} if etag else {}
        self._throttle()
        resp = self.session.get(url, headers=headers, timeout=self.timeout)
        if resp.status_code == 304:
            raise NotModified(url)
        resp.raise_for_status()
        return resp

    def get_json(self, path: str) -> dict:
        return self.get(path).json()

    def get_text(self, path: str) -> str:
        resp = self.get(path)
        # The CSVs are UTF-8 with a BOM; decode explicitly rather than trusting headers.
        return resp.content.decode("utf-8-sig")
