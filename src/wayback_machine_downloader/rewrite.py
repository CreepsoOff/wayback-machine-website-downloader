from __future__ import annotations

import html
import re

from .models import Capture
from .paths import PathMap

ATTR_RE = re.compile(r"(?P<prefix>\b(?:href|src|poster|action|data-src|data-href)\s*=\s*)(?P<quote>['\"]?)(?P<url>[^'\"\s>]+)(?P=quote)", re.I)
SRCSET_RE = re.compile(r"(?P<prefix>\bsrcset\s*=\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.I | re.S)
CSS_URL_RE = re.compile(r"(?P<prefix>url\(\s*)(?P<quote>['\"]?)(?P<url>[^)'\"]+)(?P=quote)(?P<suffix>\s*\))", re.I)


def rewrite_text(text: str, capture: Capture, paths: PathMap) -> str:
    def replacement(value: str) -> str:
        return paths.reference(html.unescape(value.strip()), source=capture) or value

    def attr(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{match.group('quote')}{replacement(match.group('url'))}{match.group('quote')}"

    def srcset(match: re.Match[str]) -> str:
        entries: list[str] = []
        for item in match.group("value").split(","):
            pieces = item.strip().split(None, 1)
            if pieces:
                pieces[0] = replacement(pieces[0])
            entries.append(" ".join(pieces))
        return f"{match.group('prefix')}{match.group('quote')}{', '.join(entries)}{match.group('quote')}"

    def css(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{match.group('quote')}{replacement(match.group('url'))}{match.group('quote')}{match.group('suffix')}"

    if capture.mimetype.startswith("text/html"):
        text = ATTR_RE.sub(attr, text)
        text = SRCSET_RE.sub(srcset, text)
        text = CSS_URL_RE.sub(css, text)
    elif capture.mimetype.startswith("text/css"):
        text = CSS_URL_RE.sub(css, text)
    return text
