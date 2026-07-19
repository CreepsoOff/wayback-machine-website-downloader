from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections.abc import Callable

from .http import HTTPClient
from .models import Capture
from .state import StateStore

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
FIELDS = ("urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length")


def build_scope(original_url: str, scope_type: str) -> tuple[str, str | None]:
    parts = urllib.parse.urlsplit(original_url)
    assert parts.hostname
    if scope_type == "domain":
        return f"*.{parts.hostname}/", None
    if scope_type == "prefix":
        path = parts.path or "/"
        if not path.endswith("/"):
            path += "/"
        return f"{parts.hostname}{path}*", None
    if scope_type == "host":
        return f"{parts.hostname}/*", None
    raise ValueError("scope type must be host, domain, or prefix")


def status_regex(statuses: list[str]) -> str | None:
    if not statuses or "any" in statuses:
        return None
    pieces: list[str] = []
    for status in statuses:
        if re.fullmatch(r"[1-5]xx", status):
            pieces.append(re.escape(status[0]) + r"\d\d")
        elif re.fullmatch(r"\d{3}", status):
            pieces.append(re.escape(status))
        else:
            raise ValueError(f"invalid status filter: {status}")
    return "(?:" + "|".join(pieces) + ")"


def mime_regex(value: str) -> str:
    return re.escape(value).replace(r"\*", ".*")


class CDXClient:
    def __init__(self, http: HTTPClient, state: StateStore, *, page_size: int = 5000, progress: Callable[[str], None] | None = None) -> None:
        self.http = http
        self.state = state
        self.page_size = page_size
        self.progress = progress or (lambda message: None)

    def query(
        self,
        scope: str,
        *,
        from_timestamp: str | None = None,
        to_timestamp: str | None = None,
        statuses: list[str] | None = None,
        mime_types: list[str] | None = None,
        exclude_mime_types: list[str] | None = None,
        source: str = "scope",
        depth: int = 0,
        resume: bool = True,
    ) -> list[Capture]:
        parameters: list[tuple[str, str]] = [
            ("url", scope),
            ("output", "json"),
            ("fl", ",".join(FIELDS)),
            ("limit", str(self.page_size)),
            ("showResumeKey", "true"),
            ("resolveRevisits", "true"),
        ]
        if from_timestamp:
            parameters.append(("from", from_timestamp))
        if to_timestamp:
            parameters.append(("to", to_timestamp))
        regex = status_regex(statuses or [])
        if regex:
            parameters.append(("filter", f"statuscode:{regex}"))
        if mime_types:
            parameters.append(("filter", "mimetype:(?:" + "|".join(mime_regex(value) for value in mime_types) + ")"))
        for value in exclude_mime_types or []:
            parameters.append(("filter", f"!mimetype:{mime_regex(value)}"))

        fingerprint = hashlib.sha256(urllib.parse.urlencode(sorted(parameters)).encode()).hexdigest()
        saved = self.state.query(fingerprint) if resume else {"captures": [], "resume_key": None, "complete": False}
        captures = [Capture.from_dict(item) for item in saved.get("captures", [])]
        if saved.get("complete"):
            self.progress(f"CDX cache: {len(captures)} capture records")
            return captures

        resume_key = saved.get("resume_key")
        seen_keys: set[str] = set()
        page_number = 0
        while True:
            query = list(parameters)
            if resume_key:
                query.append(("resumeKey", str(resume_key)))
            url = CDX_ENDPOINT + "?" + urllib.parse.urlencode(query)
            result = self.http.get(url)
            payload = json.loads(result.body)
            if not payload:
                self.state.save_query(fingerprint, captures=[item.to_dict() for item in captures], resume_key=None, complete=True)
                return captures
            if payload[0] != list(FIELDS):
                raise RuntimeError(f"unexpected CDX fields: {payload[0]!r}")
            page: list[Capture] = []
            next_key: str | None = None
            for row in payload[1:]:
                if len(row) == len(FIELDS):
                    page.append(Capture(*row, source=source, depth=depth))
                elif len(row) == 1 and row[0]:
                    next_key = row[0]
            captures.extend(page)
            page_number += 1
            self.progress(f"CDX page {page_number}: {len(page)} records ({len(captures)} total)")
            if next_key and next_key in seen_keys:
                raise RuntimeError("CDX returned a repeated continuation token")
            if next_key:
                seen_keys.add(next_key)
            self.state.save_query(
                fingerprint,
                captures=[item.to_dict() for item in captures],
                resume_key=next_key,
                complete=next_key is None,
            )
            if not next_key:
                return captures
            resume_key = next_key

    def exact_url(self, url: str, **kwargs) -> list[Capture]:  # type: ignore[no-untyped-def]
        return self.query(url, source="external", **kwargs)
