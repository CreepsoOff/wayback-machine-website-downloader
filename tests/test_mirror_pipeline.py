from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wayback_machine_downloader.config import MirrorConfig
from wayback_machine_downloader.mirror import Mirror
from wayback_machine_downloader.models import Capture, DownloadedCapture
from wayback_machine_downloader.paths import PathMap


def capture(url: str, *, status: str = "200", mimetype: str = "text/html", source: str = "scope", depth: int = 0) -> Capture:
    return Capture("com,example)/", "20250101120000", url, mimetype, status, "-", "1", source, depth)


class FakeCDX:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def exact_url(self, url: str, **kwargs):
        self.calls.append(url)
        return [capture(url, mimetype="text/css", source="external", depth=kwargs["depth"])]


class MirrorPipelineTests(unittest.TestCase):
    def test_external_budget_limits_exact_url_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            mirror = Mirror(MirrorConfig(
                url="https://example.com",
                output=directory,
                external_hosts=["cdn.example"],
                external_depth=1,
                external_budget=1,
            ), progress=lambda message: None)
            page = capture("https://example.com/")
            cache_path = mirror._cache_path(page)
            cache_path.write_text('<link href="https://cdn.example/a.css"><link href="https://cdn.example/b.css">')
            download = DownloadedCapture(page, cache_path.relative_to(mirror.cache).as_posix(), {}, 200, 1, 1, None)
            fake = FakeCDX()
            mirror.cdx = fake  # type: ignore[assignment]

            def downloads(items):
                return [DownloadedCapture(item, "unused", {}, 200, 1, 1, None) for item in items]

            mirror.download_many = downloads  # type: ignore[method-assign]
            captures, _, missing = mirror.discover_external([page], [download])
            self.assertEqual(fake.calls, ["https://cdn.example/a.css"])
            self.assertEqual(len(captures), 2)
            self.assertEqual(missing[0]["reason"], "external-budget-exhausted")

    def test_redirect_materializes_as_local_redirect_page(self):
        with tempfile.TemporaryDirectory() as directory:
            mirror = Mirror(MirrorConfig(url="https://example.com", output=directory), progress=lambda message: None)
            redirect = capture("https://example.com/old", status="301")
            target = capture("https://example.com/new/")
            redirect_cache = mirror._cache_path(redirect)
            target_cache = mirror._cache_path(target)
            redirect_cache.write_bytes(b"")
            target_cache.write_text("<h1>New</h1>")
            downloads = [
                DownloadedCapture(redirect, redirect_cache.relative_to(mirror.cache).as_posix(), {"location": "https://example.com/new/"}, 301, 0, 0, None),
                DownloadedCapture(target, target_cache.relative_to(mirror.cache).as_posix(), {}, 200, 1, 1, None),
            ]
            paths = PathMap([redirect, target], "example.com")
            mirror.materialize([redirect, target], downloads, paths)
            redirect_file = pathlib.Path(directory).joinpath(*paths.path_for(redirect).parts)
            self.assertIn("new/index.html", redirect_file.read_text())


if __name__ == "__main__":
    unittest.main()
