from __future__ import annotations

import base64
import dataclasses
import gzip
import hashlib
import random
import threading
import time
import urllib.error
import urllib.request

USER_AGENT = "wayback-machine-website-downloader/1.5 (+https://github.com/CreepsoOff/wayback-machine-website-downloader)"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


@dataclasses.dataclass(frozen=True, slots=True)
class HTTPResult:
    raw_body: bytes
    body: bytes
    headers: dict[str, str]
    status: int
    final_url: str


class HTTPClient:
    def __init__(self, *, delay: float = 0.75, attempts: int = 5, timeout: int = 60) -> None:
        self.delay = delay
        self.attempts = attempts
        self.timeout = timeout
        self._lock = threading.Lock()
        self._next_request = 0.0
        self._no_redirect_opener = urllib.request.build_opener(NoRedirect)

    def _pace(self) -> None:
        with self._lock:
            remaining = self._next_request - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            self._next_request = time.monotonic() + self.delay

    def get(self, url: str, *, follow_redirects: bool = True) -> HTTPResult:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            self._pace()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            try:
                opener = urllib.request.urlopen if follow_redirects else self._no_redirect_opener.open
                with opener(request, timeout=self.timeout) as response:
                    return self._result(response.read(), response.headers.items(), response.status, response.geturl())
            except urllib.error.HTTPError as exc:
                if not follow_redirects and 300 <= exc.code < 400:
                    return self._result(exc.read(), exc.headers.items(), exc.code, url)
                last_error = exc
                if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                    break
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else min(30.0, 2**attempt + random.random())
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                time.sleep(min(30.0, 2**attempt + random.random()))
        raise RuntimeError(f"request failed after {self.attempts} attempts: {url}: {last_error}")

    @staticmethod
    def _result(raw: bytes, headers_source, status: int, final_url: str) -> HTTPResult:  # type: ignore[no-untyped-def]
        headers = {key.lower(): value for key, value in headers_source}
        body = raw
        if headers.get("content-encoding", "").lower() == "gzip":
            try:
                body = gzip.decompress(raw)
            except gzip.BadGzipFile:
                pass
        return HTTPResult(raw, body, headers, status, final_url)


def verify_cdx_digest(raw_body: bytes, decoded_body: bytes, digest: str) -> bool | None:
    if not digest or digest == "-":
        return None
    expected = digest.upper().rstrip("=")
    for body in (raw_body, decoded_body):
        actual = base64.b32encode(hashlib.sha1(body).digest()).decode("ascii").rstrip("=")
        if actual == expected:
            return True
    return False
