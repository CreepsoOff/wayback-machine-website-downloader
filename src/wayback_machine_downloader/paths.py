from __future__ import annotations

import hashlib
import mimetypes
import os
import pathlib
import re
import urllib.parse
from collections import defaultdict

from .models import Capture
from .selection import timestamp_value


def safe_segment(segment: str) -> str:
    decoded = urllib.parse.unquote(segment).replace("\x00", "").replace("/", "_").replace("\\", "_")
    if decoded in {"", ".", ".."}:
        return "_"
    return re.sub(r"[\x00-\x1f:]", "_", decoded)


def base_path(capture: Capture, primary_host: str) -> pathlib.PurePosixPath:
    parts = urllib.parse.urlsplit(capture.original)
    segments: list[str] = []
    if parts.hostname and parts.hostname.lower() != primary_host.lower():
        segments.extend(("_external", safe_segment(parts.hostname.lower())))
    segments.extend(safe_segment(part) for part in parts.path.split("/") if part)
    if not segments or parts.path.endswith("/"):
        segments.append("index.html")
    elif capture.mimetype.startswith("text/html") and not pathlib.PurePosixPath(segments[-1]).suffix:
        segments.append("index.html")
    elif not pathlib.PurePosixPath(segments[-1]).suffix:
        extension = mimetypes.guess_extension(capture.mimetype.split(";", 1)[0]) or ""
        segments[-1] += extension
    path = pathlib.PurePosixPath(*segments)
    if parts.query:
        marker = hashlib.sha256(parts.query.encode()).hexdigest()[:10]
        path = path.with_name(f"{path.stem}__q_{marker}{path.suffix}")
    return path


class PathMap:
    def __init__(self, captures: list[Capture], primary_host: str, *, all_timestamps: bool = False) -> None:
        self.paths: dict[str, pathlib.PurePosixPath] = {}
        self.by_url: dict[str, list[Capture]] = defaultdict(list)
        owners: dict[pathlib.PurePosixPath, str] = {}
        for capture in captures:
            path = base_path(capture, primary_host)
            if all_timestamps:
                path = pathlib.PurePosixPath("snapshots", capture.timestamp, path)
            if path in owners and owners[path] != capture.id:
                marker = hashlib.sha256(capture.id.encode()).hexdigest()[:10]
                path = path.with_name(f"{path.stem}__u_{marker}{path.suffix}")
            owners[path] = capture.id
            self.paths[capture.id] = path
            self.by_url[capture.original].append(capture)

    def path_for(self, capture: Capture) -> pathlib.PurePosixPath:
        return self.paths[capture.id]

    def reference(self, value: str, *, source: Capture) -> str | None:
        absolute = urllib.parse.urljoin(source.original, value)
        target_url, fragment = urllib.parse.urldefrag(absolute)
        candidates = self.by_url.get(target_url)
        if not candidates:
            parts = urllib.parse.urlsplit(target_url)
            alternate_scheme = "http" if parts.scheme == "https" else "https"
            alternate = urllib.parse.urlunsplit((alternate_scheme, parts.netloc, parts.path, parts.query, ""))
            candidates = self.by_url.get(alternate)
        if not candidates:
            return None
        source_time = timestamp_value(source.timestamp)
        target = min(candidates, key=lambda item: abs((timestamp_value(item.timestamp) - source_time).total_seconds()))
        relative = os.path.relpath(str(self.path_for(target)), start=str(self.path_for(source).parent)).replace(os.sep, "/")
        return relative + (("#" + fragment) if fragment else "")

    def to_dict(self) -> dict[str, str]:
        return dict(sorted((key, path.as_posix()) for key, path in self.paths.items()))
