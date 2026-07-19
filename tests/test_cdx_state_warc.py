from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wayback_machine_downloader.cdx import CDXClient, FIELDS
from wayback_machine_downloader.http import HTTPResult
from wayback_machine_downloader.models import Capture, DownloadedCapture
from wayback_machine_downloader.state import StateStore
from wayback_machine_downloader.warc import export_warc


class FakeHTTP:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        body = json.dumps(self.payloads.pop(0)).encode()
        return HTTPResult(body, body, {}, 200, url)


class CDXStateTests(unittest.TestCase):
    def test_resume_key_pagination_and_persistent_cache(self):
        row1 = ["com,example)/", "20240101000000", "https://example.com/", "text/html", "200", "A", "1"]
        row2 = ["com,example)/a", "20240101000001", "https://example.com/a", "text/html", "200", "B", "1"]
        pages = [[list(FIELDS), row1, [], ["opaque-token"]], [list(FIELDS), row2]]
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(pathlib.Path(directory) / "state.json")
            http = FakeHTTP(pages)
            client = CDXClient(http, state, page_size=1)
            result = client.query("example.com/*", statuses=["200"])
            self.assertEqual(len(result), 2)
            self.assertIn("resumeKey=opaque-token", http.urls[1])
            cached_http = FakeHTTP([])
            cached = CDXClient(cached_http, StateStore(state.path), page_size=1).query("example.com/*", statuses=["200"])
            self.assertEqual(len(cached), 2)
            self.assertEqual(cached_http.urls, [])


class WARCExportTests(unittest.TestCase):
    def test_warc_resource_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "body").write_bytes(b"hello")
            capture = Capture("com,example)/", "20250101120000", "https://example.com/", "text/plain", "200", "-", "5")
            download = DownloadedCapture(capture, "body", {}, 200, 5, 5, None)
            count = export_warc(root / "archive.warc", [download], root)
            data = (root / "archive.warc").read_bytes()
            self.assertEqual(count, 1)
            self.assertIn(b"WARC/1.1", data)
            self.assertIn(b"WARC-Target-URI: https://example.com/", data)
            self.assertIn(b"hello", data)


if __name__ == "__main__":
    unittest.main()
