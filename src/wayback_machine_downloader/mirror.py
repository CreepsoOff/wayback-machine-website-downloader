from __future__ import annotations

import concurrent.futures
import hashlib
import json
import pathlib
import re
import sys
import urllib.parse
from collections.abc import Callable

from .cdx import CDXClient, build_scope
from .config import MirrorConfig
from .discovery import discover_urls, is_allowed_external
from .http import HTTPClient, verify_cdx_digest
from .models import Capture, DownloadedCapture
from .paths import PathMap
from .reports import report_data, write_json, write_sitemap
from .rewrite import rewrite_text
from .selection import select_captures
from .state import StateStore
from .warc import export_warc


def validate_original_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("URL must be an original HTTPS site URL, for example https://example.com")
    if parts.hostname.lower() == "web.archive.org":
        raise ValueError("pass the original site URL, not a web.archive.org replay URL")
    return value


def decode_text(body: bytes, headers: dict[str, str]) -> tuple[str, str]:
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    for encoding in ([match.group(1).strip("'\"")] if match else []) + ["utf-8", "windows-1252"]:
        try:
            return body.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            pass
    return body.decode("utf-8", errors="replace"), "utf-8"


class Mirror:
    def __init__(self, config: MirrorConfig, *, progress: Callable[[str], None] | None = None) -> None:
        self.config = config.normalized()
        self.config.url = validate_original_url(self.config.url)
        self.output = pathlib.Path(self.config.output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.cache = self.output / ".wayback-cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.state = StateStore(self.output / ".wayback-state.json")
        self.http = HTTPClient(delay=self.config.delay)
        self.progress = progress or (lambda message: print(message, file=sys.stderr))
        self.cdx = CDXClient(self.http, self.state, page_size=self.config.page_size, progress=self.progress)
        self.primary_host = urllib.parse.urlsplit(self.config.url).hostname or ""

    def inventory(self) -> tuple[list[Capture], list[str]]:
        scope = self.config.scope or build_scope(self.config.url, self.config.scope_type)[0]
        records = self.cdx.query(
            scope,
            from_timestamp=self.config.from_timestamp,
            to_timestamp=self.config.to_timestamp,
            statuses=self.config.statuses,
            mime_types=self.config.mime_types,
            exclude_mime_types=self.config.exclude_mime_types,
        )
        return select_captures(
            records,
            strategy=self.config.strategy,
            target=self.config.timestamp,
            all_timestamps=self.config.all_timestamps,
        )

    def _cache_path(self, capture: Capture) -> pathlib.Path:
        return self.cache / (hashlib.sha256(capture.id.encode()).hexdigest() + ".body")

    def download(self, capture: Capture) -> DownloadedCapture:
        cache_path = self._cache_path(capture)
        relative_cache = cache_path.relative_to(self.cache).as_posix()
        saved = self.state.download(capture.id)
        if saved and saved.get("complete") and cache_path.exists():
            return DownloadedCapture.from_dict(saved["download"])
        try:
            result = self.http.get(capture.replay_url, follow_redirects=False)
            cache_path.write_bytes(result.body)
            verified = verify_cdx_digest(result.raw_body, result.body, capture.digest) if self.config.verify_digests else None
            download = DownloadedCapture(
                capture,
                relative_cache,
                result.headers,
                result.status,
                len(result.raw_body),
                len(result.body),
                verified,
            )
            self.state.save_download(capture.id, {"complete": True, "download": download.to_dict()})
            return download
        except Exception as exc:
            download = DownloadedCapture(capture, relative_cache, {}, 0, 0, 0, None, str(exc))
            self.state.save_download(capture.id, {"complete": False, "download": download.to_dict()})
            return download

    def download_many(self, captures: list[Capture]) -> list[DownloadedCapture]:
        downloads: list[DownloadedCapture] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.workers) as executor:
            futures = {executor.submit(self.download, capture): capture for capture in captures}
            for number, future in enumerate(concurrent.futures.as_completed(futures), 1):
                item = future.result()
                downloads.append(item)
                result = "FAILED" if item.error else "cached"
                self.progress(f"[{number}/{len(captures)}] {result} {item.capture.original}")
        return sorted(downloads, key=lambda item: item.capture.id)

    def discover_external(
        self,
        captures: list[Capture],
        downloads: list[DownloadedCapture],
    ) -> tuple[list[Capture], list[DownloadedCapture], list[dict[str, object]]]:
        allowed = set(self.config.external_hosts)
        known_urls: set[str] = set()

        def mark_known(url: str) -> None:
            known_urls.add(url)
            parts = urllib.parse.urlsplit(url)
            if (parts.hostname or "").lower() == self.primary_host.lower() and parts.scheme in {"http", "https"}:
                alternate = "http" if parts.scheme == "https" else "https"
                known_urls.add(urllib.parse.urlunsplit((alternate, parts.netloc, parts.path, parts.query, "")))

        for capture in captures:
            mark_known(capture.original)
        missing: list[dict[str, object]] = []
        frontier = [item for item in downloads if not item.error]
        external_count = 0
        scan_depth = max(1, self.config.external_depth)
        for depth in range(1, scan_depth + 1):
            discovered_by: dict[str, str] = {}
            for item in frontier:
                if not (item.capture.mimetype.startswith(("text/", "application/javascript")) or "json" in item.capture.mimetype):
                    continue
                body = (self.cache / item.cache_path).read_bytes()
                text, _ = decode_text(body, item.response_headers)
                for url in discover_urls(text, item.capture, javascript=self.config.discover_javascript):
                    if url not in known_urls:
                        discovered_by.setdefault(url, item.capture.original)
            new_captures: list[Capture] = []
            for url, referrer in sorted(discovered_by.items()):
                host = (urllib.parse.urlsplit(url).hostname or "").lower()
                if host == self.primary_host.lower():
                    missing.append({"url": url, "reason": "not-in-selected-inventory", "discovered_from": referrer, "depth": depth})
                    mark_known(url)
                    continue
                if not is_allowed_external(url, self.primary_host, allowed):
                    missing.append({"url": url, "reason": "external-host-not-allowed", "discovered_from": referrer, "depth": depth})
                    mark_known(url)
                    continue
                if depth > self.config.external_depth:
                    missing.append({"url": url, "reason": "external-depth-disabled", "discovered_from": referrer, "depth": depth})
                    mark_known(url)
                    continue
                if external_count >= self.config.external_budget:
                    missing.append({"url": url, "reason": "external-budget-exhausted", "discovered_from": referrer, "depth": depth})
                    continue
                external_count += 1
                records = self.cdx.exact_url(
                    url,
                    from_timestamp=self.config.from_timestamp,
                    to_timestamp=self.config.to_timestamp,
                    statuses=self.config.statuses,
                    mime_types=self.config.mime_types,
                    exclude_mime_types=self.config.exclude_mime_types,
                    depth=depth,
                )
                selected, _ = select_captures(records, strategy=self.config.strategy, target=self.config.timestamp, all_timestamps=self.config.all_timestamps)
                if not selected:
                    missing.append({"url": url, "reason": "not-in-wayback", "discovered_from": referrer, "depth": depth})
                    mark_known(url)
                    continue
                new_captures.extend(selected)
                mark_known(url)
            if not new_captures:
                break
            new_downloads = self.download_many(new_captures)
            captures.extend(new_captures)
            downloads.extend(new_downloads)
            frontier = [item for item in new_downloads if not item.error]
        return captures, downloads, missing

    def materialize(self, captures: list[Capture], downloads: list[DownloadedCapture], paths: PathMap) -> None:
        by_id = {item.capture.id: item for item in downloads}
        for capture in captures:
            item = by_id.get(capture.id)
            if not item or item.error:
                continue
            body = (self.cache / item.cache_path).read_bytes()
            destination = self.output.joinpath(*paths.path_for(capture).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if capture.is_redirect:
                location = item.response_headers.get("location", "")
                local = paths.reference(location, source=capture) if location else None
                target = local or location or "#"
                body = f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={target}"><a href="{target}">Redirect</a>\n'.encode()
            elif capture.mimetype.startswith(("text/html", "text/css")):
                text, encoding = decode_text(body, item.response_headers)
                body = rewrite_text(text, capture, paths).encode(encoding, errors="xmlcharrefreplace")
            temporary = destination.with_name(destination.name + ".part")
            temporary.write_bytes(body)
            temporary.replace(destination)

    def run(self) -> int:
        captures, missing_strategy = self.inventory()
        if self.config.inventory_only:
            write_json(self.output / "wayback-inventory.json", {
                "config": self.config.to_public_dict(),
                "capture_records": len(captures),
                "captures": [capture.to_dict() for capture in captures],
                "missing_for_snapshot_strategy": missing_strategy,
            })
            self.progress(f"Inventory complete: {len(captures)} captures")
            return 0

        downloads = self.download_many(captures)
        captures, downloads, missing_resources = self.discover_external(captures, downloads)
        captures = sorted({capture.id: capture for capture in captures}.values(), key=lambda item: item.id)
        paths = PathMap(captures, self.primary_host, all_timestamps=self.config.all_timestamps)
        self.materialize(captures, downloads, paths)
        warc_records = export_warc(self.output / "archive.warc", downloads, self.cache) if self.config.export_warc else 0

        write_json(self.output / "wayback-inventory.json", {
            "config": self.config.to_public_dict(),
            "capture_records": len(captures),
            "captures": [capture.to_dict() for capture in captures],
            "missing_for_snapshot_strategy": missing_strategy,
        })
        write_json(self.output / "url-map.json", paths.to_dict())
        write_json(self.output / "missing-resources.json", missing_resources)
        write_sitemap(self.output / "sitemap.xml", captures, paths)
        report = report_data(
            captures=captures,
            downloads=downloads,
            missing_strategy=missing_strategy,
            missing_resources=missing_resources,
            warc_records=warc_records,
        )
        write_json(self.output / "wayback-report.json", report)
        self.progress(f"Done: {report['downloaded']}/{report['expected']} captures; {report['failed']} failed; {report['digest_failed']} digest mismatches")
        return 1 if report["failed"] or report["digest_failed"] else 0
