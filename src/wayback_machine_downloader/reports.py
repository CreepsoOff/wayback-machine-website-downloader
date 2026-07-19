from __future__ import annotations

import html
import json
import pathlib
from typing import Any

from .models import Capture, DownloadedCapture
from .paths import PathMap


def write_json(path: pathlib.Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_sitemap(path: pathlib.Path, captures: list[Capture], paths: PathMap) -> None:
    items = []
    for capture in captures:
        if capture.mimetype.startswith("text/html"):
            items.append(
                "  <url><loc>"
                + html.escape(capture.original)
                + "</loc><lastmod>"
                + f"{capture.timestamp[:4]}-{capture.timestamp[4:6]}-{capture.timestamp[6:8]}"
                + "</lastmod></url>"
            )
    document = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n" + "\n".join(items) + "\n</urlset>\n"
    path.write_text(document, encoding="utf-8")


def report_data(
    *,
    captures: list[Capture],
    downloads: list[DownloadedCapture],
    missing_strategy: list[str],
    missing_resources: list[dict[str, object]],
    warc_records: int,
) -> dict[str, object]:
    failures = [item.to_dict() for item in downloads if item.error]
    integrity_failures = [item.to_dict() for item in downloads if item.digest_verified is False]
    return {
        "expected": len(captures),
        "downloaded": sum(not item.error for item in downloads),
        "failed": len(failures),
        "digest_verified": sum(item.digest_verified is True for item in downloads),
        "digest_unavailable": sum(item.digest_verified is None for item in downloads),
        "digest_failed": len(integrity_failures),
        "external_captures": sum(item.source == "external" for item in captures),
        "missing_for_snapshot_strategy": missing_strategy,
        "missing_resources": len(missing_resources),
        "warc_records": warc_records,
        "failures": failures,
        "integrity_failures": integrity_failures,
    }
