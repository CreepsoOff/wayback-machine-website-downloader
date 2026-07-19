from __future__ import annotations

import datetime as dt
import pathlib
import uuid

from .models import DownloadedCapture


def _record(headers: list[tuple[str, str]], payload: bytes) -> bytes:
    lines = ["WARC/1.1", *[f"{key}: {value}" for key, value in headers], f"Content-Length: {len(payload)}", "", ""]
    return "\r\n".join(lines).encode("utf-8") + payload + b"\r\n\r\n"


def export_warc(path: pathlib.Path, downloads: list[DownloadedCapture], cache_root: pathlib.Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("wb") as stream:
        info = b"software: wayback-machine-website-downloader/1.5.0\nformat: WARC File Format 1.1\n"
        stream.write(_record([
            ("WARC-Type", "warcinfo"),
            ("WARC-Date", dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")),
            ("WARC-Record-ID", f"<urn:uuid:{uuid.uuid4()}>") ,
            ("Content-Type", "application/warc-fields"),
        ], info))
        for download in downloads:
            cache_path = cache_root / download.cache_path
            if download.error or not cache_path.exists():
                continue
            payload = cache_path.read_bytes()
            capture_date = dt.datetime.strptime(download.capture.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
            stream.write(_record([
                ("WARC-Type", "resource"),
                ("WARC-Target-URI", download.capture.original),
                ("WARC-Date", capture_date.isoformat().replace("+00:00", "Z")),
                ("WARC-Record-ID", f"<urn:uuid:{uuid.uuid4()}>") ,
                ("WARC-Refers-To-Target-URI", download.capture.replay_url),
                ("Content-Type", download.capture.mimetype or "application/octet-stream"),
            ], payload))
            count += 1
    return count
