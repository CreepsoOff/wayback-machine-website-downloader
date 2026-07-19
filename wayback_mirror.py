#!/usr/bin/env python3
"""CDX-first Wayback Machine website downloader (standard library only)."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import gzip
import hashlib
import html
import json
import mimetypes
import os
import pathlib
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Iterable

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
REPLAY_ROOT = "https://web.archive.org/web"
USER_AGENT = "wayback-site-mirror/1.0 (+offline preservation; polite CDX client)"
FIELDS = ("timestamp", "original", "mimetype", "statuscode", "digest", "length")
REQUEST_INTERVAL = 0.75
_request_lock = threading.Lock()
_next_request_time = 0.0


@dataclasses.dataclass(frozen=True)
class Capture:
    timestamp: str
    original: str
    mimetype: str
    statuscode: str
    digest: str
    length: str

    @property
    def replay_url(self) -> str:
        return f"{REPLAY_ROOT}/{self.timestamp}id_/{self.original}"


def request_bytes(url: str, *, attempts: int = 5, timeout: int = 60) -> tuple[bytes, dict[str, str]]:
    global _next_request_time
    last_error: Exception | None = None
    for attempt in range(attempts):
        with _request_lock:
            delay = max(0.0, _next_request_time - time.monotonic())
            if delay:
                time.sleep(delay)
            _next_request_time = time.monotonic() + REQUEST_INTERVAL
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
                headers = {k.lower(): v for k, v in response.headers.items()}
                if headers.get("content-encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
                return body, headers
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 == attempts:
                break
            retry_after = getattr(exc, "headers", {}).get("Retry-After") if getattr(exc, "headers", None) else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(20.0, (2**attempt) + random.random())
            time.sleep(delay)
    raise RuntimeError(f"request failed after {attempts} attempts: {url}: {last_error}")


def cdx_pages(scope: str, *, page_size: int, from_ts: str | None, to_ts: str | None) -> Iterable[list[Capture]]:
    """Yield every CDX page, using resume keys until the server says there are no more."""
    resume_key: str | None = None
    seen_keys: set[str] = set()
    while True:
        params: list[tuple[str, str]] = [
            ("url", scope),
            ("output", "json"),
            ("fl", ",".join(FIELDS)),
            ("filter", "statuscode:200"),
            ("limit", str(page_size)),
            ("showResumeKey", "true"),
        ]
        if from_ts:
            params.append(("from", from_ts))
        if to_ts:
            params.append(("to", to_ts))
        if resume_key:
            params.append(("resumeKey", resume_key))
        url = CDX_ENDPOINT + "?" + urllib.parse.urlencode(params)
        raw, _ = request_bytes(url)
        payload = json.loads(raw)
        if not payload:
            return
        header = payload[0]
        if header != list(FIELDS):
            raise RuntimeError(f"unexpected CDX fields: {header!r}")
        rows: list[Capture] = []
        next_key: str | None = None
        for row in payload[1:]:
            if len(row) == len(FIELDS):
                rows.append(Capture(*row))
            elif len(row) == 1 and row[0]:
                next_key = row[0]
        yield rows
        if not next_key:
            return
        if next_key in seen_keys:
            raise RuntimeError(f"CDX returned a repeated resume key: {next_key}")
        seen_keys.add(next_key)
        resume_key = next_key


def parse_original_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("URL must be an original HTTPS site URL, for example https://example.com")
    if parts.hostname.lower() == "web.archive.org":
        raise ValueError("pass the original site URL, not a web.archive.org replay URL")
    return value


def timestamp_distance(left: str, right: str) -> int:
    left_date = dt.datetime.strptime(left, "%Y%m%d%H%M%S")
    right_date = dt.datetime.strptime(right, "%Y%m%d%H%M%S")
    return int(abs((left_date - right_date).total_seconds()))


def select_captures(captures: Iterable[Capture], target_ts: str) -> list[Capture]:
    grouped: dict[str, list[Capture]] = defaultdict(list)
    for capture in captures:
        clean = urllib.parse.urldefrag(capture.original)[0]
        grouped[clean].append(dataclasses.replace(capture, original=clean))
    if target_ts == "latest":
        selected = (max(group, key=lambda item: item.timestamp) for group in grouped.values())
    else:
        selected = (min(group, key=lambda item: (timestamp_distance(item.timestamp, target_ts), item.timestamp)) for group in grouped.values())
    return sorted(selected, key=lambda item: item.original)


def safe_segment(segment: str) -> str:
    decoded = urllib.parse.unquote(segment)
    decoded = decoded.replace("\x00", "").replace("/", "_").replace("\\", "_")
    if decoded in {"", ".", ".."}:
        return "_"
    return re.sub(r"[\x00-\x1f:]", "_", decoded)


def base_local_path(capture: Capture) -> pathlib.PurePosixPath:
    parts = urllib.parse.urlsplit(capture.original)
    segments = [safe_segment(part) for part in parts.path.split("/") if part]
    if not segments or parts.path.endswith("/"):
        segments.append("index.html")
    elif capture.mimetype.startswith("text/html") and not pathlib.PurePosixPath(segments[-1]).suffix:
        segments.append("index.html")
    elif not pathlib.PurePosixPath(segments[-1]).suffix:
        guessed = mimetypes.guess_extension(capture.mimetype.split(";", 1)[0]) or ""
        segments[-1] += guessed
    path = pathlib.PurePosixPath(*segments)
    if parts.query:
        marker = hashlib.sha256(parts.query.encode()).hexdigest()[:10]
        path = path.with_name(f"{path.stem}__q_{marker}{path.suffix}")
    return path


def assign_paths(captures: list[Capture]) -> dict[str, pathlib.PurePosixPath]:
    result: dict[str, pathlib.PurePosixPath] = {}
    owners: dict[pathlib.PurePosixPath, str] = {}
    for capture in captures:
        path = base_local_path(capture)
        if path in owners and owners[path] != capture.original:
            marker = hashlib.sha256(capture.original.encode()).hexdigest()[:10]
            path = path.with_name(f"{path.stem}__u_{marker}{path.suffix}")
        owners[path] = capture.original
        result[capture.original] = path
    return result


def local_reference(value: str, *, source_url: str, source_path: pathlib.PurePosixPath, paths: dict[str, pathlib.PurePosixPath]) -> str:
    stripped = html.unescape(value.strip())
    if not stripped or stripped.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
        return value
    absolute = urllib.parse.urljoin(source_url, stripped)
    target, fragment = urllib.parse.urldefrag(absolute)
    destination = paths.get(target)
    if destination is None:
        return value
    relative = os.path.relpath(str(destination), start=str(source_path.parent)).replace(os.sep, "/")
    return relative + (("#" + fragment) if fragment else "")


ATTR_RE = re.compile(r"(?P<prefix>\b(?:href|src|poster|action)\s*=\s*)(?P<quote>['\"]?)(?P<url>[^'\"\s>]+)(?P=quote)", re.I)
SRCSET_RE = re.compile(r"(?P<prefix>\bsrcset\s*=\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.I | re.S)
CSS_URL_RE = re.compile(r"(?P<prefix>url\(\s*)(?P<quote>['\"]?)(?P<url>[^)'\"]+)(?P=quote)(?P<suffix>\s*\))", re.I)


def rewrite_text(text: str, *, capture: Capture, path: pathlib.PurePosixPath, paths: dict[str, pathlib.PurePosixPath]) -> str:
    def attr(match: re.Match[str]) -> str:
        new = local_reference(match.group("url"), source_url=capture.original, source_path=path, paths=paths)
        return f"{match.group('prefix')}{match.group('quote')}{new}{match.group('quote')}"

    def srcset(match: re.Match[str]) -> str:
        entries = []
        for item in match.group("value").split(","):
            bits = item.strip().split(None, 1)
            if bits:
                bits[0] = local_reference(bits[0], source_url=capture.original, source_path=path, paths=paths)
            entries.append(" ".join(bits))
        return f"{match.group('prefix')}{match.group('quote')}{', '.join(entries)}{match.group('quote')}"

    def css(match: re.Match[str]) -> str:
        new = local_reference(match.group("url").strip(), source_url=capture.original, source_path=path, paths=paths)
        return f"{match.group('prefix')}{match.group('quote')}{new}{match.group('quote')}{match.group('suffix')}"

    if capture.mimetype.startswith("text/html"):
        text = ATTR_RE.sub(attr, text)
        text = SRCSET_RE.sub(srcset, text)
        text = CSS_URL_RE.sub(css, text)
    elif capture.mimetype.startswith("text/css"):
        text = CSS_URL_RE.sub(css, text)
    return text


def decode_text(body: bytes, headers: dict[str, str]) -> tuple[str, str]:
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    candidates = [match.group(1).strip("'\"") if match else "", "utf-8", "windows-1252"]
    for encoding in candidates:
        if not encoding:
            continue
        try:
            return body.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            pass
    return body.decode("utf-8", errors="replace"), "utf-8"


def write_capture(capture: Capture, *, output: pathlib.Path, path: pathlib.PurePosixPath, paths: dict[str, pathlib.PurePosixPath]) -> dict[str, object]:
    destination = output.joinpath(*path.parts)
    if destination.is_file() and destination.stat().st_size > 0:
        return {"url": capture.original, "timestamp": capture.timestamp, "replay_url": capture.replay_url, "path": path.as_posix(), "bytes": destination.stat().st_size, "mimetype": capture.mimetype, "digest": capture.digest, "resumed": True}
    body, headers = request_bytes(capture.replay_url)
    if capture.mimetype.startswith(("text/html", "text/css")):
        text, encoding = decode_text(body, headers)
        body = rewrite_text(text, capture=capture, path=path, paths=paths).encode(encoding, errors="xmlcharrefreplace")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".part-{threading.get_ident()}")
    temporary.write_bytes(body)
    temporary.replace(destination)
    return {"url": capture.original, "timestamp": capture.timestamp, "replay_url": capture.replay_url, "path": path.as_posix(), "bytes": len(body), "mimetype": capture.mimetype, "digest": capture.digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mirror every successful archived URL under a Wayback site scope.")
    parser.add_argument("url", help="original HTTPS site URL, for example https://example.com")
    parser.add_argument("-o", "--output", type=pathlib.Path, default=pathlib.Path("wayback-mirror"))
    parser.add_argument("--timestamp", help="14-digit point-in-time target; defaults to the latest capture of each URL")
    parser.add_argument("--from", dest="from_ts", help="optional inclusive CDX timestamp lower bound")
    parser.add_argument("--to", dest="to_ts", help="optional inclusive CDX timestamp upper bound")
    parser.add_argument("--scope", help="CDX scope override, e.g. example.com/* or *.example.com/")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.75, help="minimum seconds between archive requests")
    parser.add_argument("--page-size", type=int, default=5000)
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args(argv)
    global REQUEST_INTERVAL
    REQUEST_INTERVAL = max(0.0, args.delay)

    try:
        original = parse_original_url(args.url)
    except ValueError as exc:
        parser.error(str(exc))
    target_ts = args.timestamp or "latest"
    if target_ts != "latest" and not re.fullmatch(r"\d{14}", target_ts):
        parser.error("target timestamp must have 14 digits")
    host = urllib.parse.urlsplit(original).hostname
    assert host
    scope = args.scope or f"{host}/*"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    all_captures: list[Capture] = []
    for page_number, page in enumerate(cdx_pages(scope, page_size=args.page_size, from_ts=args.from_ts, to_ts=args.to_ts), 1):
        all_captures.extend(page)
        print(f"CDX page {page_number}: {len(page)} captures ({len(all_captures)} total)", file=sys.stderr)
    selected = select_captures(all_captures, target_ts)
    paths = assign_paths(selected)
    inventory = {
        "scope": scope,
        "target_timestamp": target_ts,
        "capture_records": len(all_captures),
        "distinct_urls": len(selected),
        "captures": [dataclasses.asdict(capture) | {"local_path": paths[capture.original].as_posix(), "replay_url": capture.replay_url} for capture in selected],
    }
    (output / "wayback-inventory.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.inventory_only:
        print(f"Inventory complete: {len(selected)} URLs -> {output / 'wayback-inventory.json'}")
        return 0

    successes: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(write_capture, capture, output=output, path=paths[capture.original], paths=paths): capture for capture in selected}
        for number, future in enumerate(concurrent.futures.as_completed(futures), 1):
            capture = futures[future]
            try:
                successes.append(future.result())
                print(f"[{number}/{len(selected)}] saved {capture.original}", file=sys.stderr)
            except Exception as exc:
                failures.append({"url": capture.original, "timestamp": capture.timestamp, "replay_url": capture.replay_url, "error": str(exc)})
                print(f"[{number}/{len(selected)}] FAILED {capture.original}: {exc}", file=sys.stderr)

    report = {"expected": len(selected), "downloaded": len(successes), "failed": len(failures), "files": sorted(successes, key=lambda item: str(item["url"])), "failures": failures}
    (output / "wayback-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Done: {len(successes)}/{len(selected)} URLs downloaded; {len(failures)} failed. Report: {output / 'wayback-report.json'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
