from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wayback_machine_downloader.cdx import build_scope, status_regex
from wayback_machine_downloader.config import load_config
from wayback_machine_downloader.discovery import discover_urls, is_allowed_external
from wayback_machine_downloader.http import verify_cdx_digest
from wayback_machine_downloader.mirror import validate_original_url
from wayback_machine_downloader.models import Capture, SnapshotStrategy
from wayback_machine_downloader.paths import PathMap
from wayback_machine_downloader.rewrite import rewrite_text
from wayback_machine_downloader.selection import select_captures


def capture(url: str, timestamp: str = "20250101120000", mimetype: str = "text/html", status: str = "200", source: str = "scope") -> Capture:
    return Capture("com,example)/", timestamp, url, mimetype, status, "DIGEST", "10", source)


class ValidationTests(unittest.TestCase):
    def test_accepts_original_https_url(self):
        self.assertEqual(validate_original_url("https://example.com/a"), "https://example.com/a")

    def test_rejects_replay_and_http_urls(self):
        with self.assertRaisesRegex(ValueError, "original site"):
            validate_original_url("https://web.archive.org/web/2025/https://example.com")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_original_url("http://example.com")

    def test_scopes(self):
        self.assertEqual(build_scope("https://example.com/docs/", "host")[0], "example.com/*")
        self.assertEqual(build_scope("https://example.com/docs/", "domain")[0], "*.example.com/")
        self.assertEqual(build_scope("https://example.com/docs/", "prefix")[0], "example.com/docs/*")

    def test_status_regex(self):
        self.assertEqual(status_regex(["200", "3xx"]), r"(?:200|3\d\d)")
        self.assertIsNone(status_regex(["any"]))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            capture("https://example.com/a", "20240101000000"),
            capture("https://example.com/a", "20250101000000"),
            capture("https://example.com/a", "20260101000000"),
        ]

    def selected(self, strategy: SnapshotStrategy, target: str | None = "20250701000000") -> str:
        chosen, _ = select_captures(self.items, strategy=strategy, target=target)
        return chosen[0].timestamp

    def test_strategies(self):
        self.assertEqual(self.selected(SnapshotStrategy.LATEST, None), "20260101000000")
        self.assertEqual(self.selected(SnapshotStrategy.NEAREST), "20250101000000")
        self.assertEqual(self.selected(SnapshotStrategy.BEFORE), "20250101000000")
        self.assertEqual(self.selected(SnapshotStrategy.AFTER), "20260101000000")

    def test_missing_direction_is_reported(self):
        chosen, missing = select_captures(self.items, strategy=SnapshotStrategy.BEFORE, target="20200101000000")
        self.assertEqual(chosen, [])
        self.assertEqual(missing, ["https://example.com/a"])

    def test_all_timestamps(self):
        chosen, _ = select_captures(self.items, strategy=SnapshotStrategy.LATEST, target=None, all_timestamps=True)
        self.assertEqual(len(chosen), 3)


class DiscoveryAndRewriteTests(unittest.TestCase):
    def test_html_css_and_javascript_discovery(self):
        html_item = capture("https://example.com/")
        urls = discover_urls('<script src="/app.js"></script><img srcset="/a.png 1x, https://cdn.example/b.png 2x">', html_item)
        self.assertIn("https://example.com/app.js", urls)
        self.assertIn("https://cdn.example/b.png", urls)
        js_item = capture("https://example.com/app.js", mimetype="application/javascript")
        urls = discover_urls('fetch("/api/data.json"); import("./chunk.js")', js_item)
        self.assertIn("https://example.com/api/data.json", urls)
        self.assertIn("https://example.com/chunk.js", urls)

    def test_external_allowlist(self):
        self.assertTrue(is_allowed_external("https://cdn.example/a", "example.com", {"cdn.example"}))
        self.assertFalse(is_allowed_external("https://other.example/a", "example.com", {"cdn.example"}))

    def test_external_paths_and_rewriting(self):
        page = capture("https://example.com/")
        asset = capture("https://cdn.example/app.css", mimetype="text/css", source="external")
        paths = PathMap([page, asset], "example.com")
        self.assertEqual(paths.path_for(asset).as_posix(), "_external/cdn.example/app.css")
        rewritten = rewrite_text('<link href="https://cdn.example/app.css">', page, paths)
        self.assertIn('_external/cdn.example/app.css', rewritten)

    def test_rewriting_falls_back_between_http_and_https_captures(self):
        page = capture("https://example.com/")
        asset = capture("http://example.com/legacy.css", mimetype="text/css")
        paths = PathMap([page, asset], "example.com")
        rewritten = rewrite_text('<link href="https://example.com/legacy.css">', page, paths)
        self.assertIn('href="legacy.css"', rewritten)


class IntegrityAndConfigTests(unittest.TestCase):
    def test_digest_verification(self):
        body = b"archived payload"
        digest = base64.b32encode(hashlib.sha1(body).digest()).decode().rstrip("=")
        self.assertTrue(verify_cdx_digest(body, body, digest))
        self.assertFalse(verify_cdx_digest(b"different", b"different", digest))
        self.assertIsNone(verify_cdx_digest(body, body, "-"))

    def test_json_and_toml_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            json_path = root / "config.json"
            json_path.write_text(json.dumps({"url": "https://example.com"}))
            self.assertEqual(load_config(json_path)["url"], "https://example.com")
            toml_path = root / "config.toml"
            toml_path.write_text('[wayback]\nurl = "https://example.com"\n')
            self.assertEqual(load_config(toml_path)["url"], "https://example.com")


if __name__ == "__main__":
    unittest.main()
