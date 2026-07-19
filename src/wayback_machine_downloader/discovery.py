from __future__ import annotations

import html.parser
import re
import urllib.parse
from collections.abc import Iterable
from typing import Protocol

from .models import Capture


class DiscoveryProvider(Protocol):
    """Extension point reserved for the optional V2 browser extra."""

    def discover(self, body: str, capture: Capture) -> set[str]: ...


class HTMLDiscoveryParser(html.parser.HTMLParser):
    ATTRIBUTES = {"href", "src", "poster", "action", "data-src", "data-href"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            if name.lower() in self.ATTRIBUTES:
                self.urls.add(value)
            elif name.lower() == "srcset":
                for item in value.split(","):
                    candidate = item.strip().split(None, 1)[0]
                    if candidate:
                        self.urls.add(candidate)


CSS_URL_RE = re.compile(r"(?:url\(\s*|@import\s+)(?:['\"])?([^)'\"\s;]+)", re.I)
JS_CALL_RE = re.compile(
    r"(?:fetch|import|require|axios\.(?:get|post|put|delete)|new\s+URL)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.I,
)
JS_LITERAL_RE = re.compile(
    r"['\"]((?:https?:)?//[^'\"\s]+|(?:\.{0,2}/)[^'\"\s]+\.(?:js|mjs|css|json|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|map)(?:\?[^'\"\s]*)?)['\"]",
    re.I,
)


def valid_discovery(value: str, base_url: str) -> str | None:
    value = value.strip()
    if not value or value.startswith(("#", "data:", "mailto:", "tel:", "javascript:", "blob:")):
        return None
    absolute = urllib.parse.urljoin(base_url, value)
    parts = urllib.parse.urlsplit(absolute)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return urllib.parse.urldefrag(absolute)[0]


def discover_urls(body: str, capture: Capture, *, javascript: bool = True, providers: Iterable[DiscoveryProvider] = ()) -> set[str]:
    candidates: set[str] = set()
    if capture.mimetype.startswith("text/html"):
        parser = HTMLDiscoveryParser()
        parser.feed(body)
        candidates.update(parser.urls)
        candidates.update(CSS_URL_RE.findall(body))
    elif capture.mimetype.startswith("text/css"):
        candidates.update(CSS_URL_RE.findall(body))
    if javascript and ("javascript" in capture.mimetype or capture.original.lower().endswith((".js", ".mjs"))):
        candidates.update(JS_CALL_RE.findall(body))
        candidates.update(JS_LITERAL_RE.findall(body))
    for provider in providers:
        candidates.update(provider.discover(body, capture))
    return {url for value in candidates if (url := valid_discovery(value, capture.original))}


def is_allowed_external(url: str, primary_host: str, allowed_hosts: set[str]) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host != primary_host.lower() and host in allowed_hosts
