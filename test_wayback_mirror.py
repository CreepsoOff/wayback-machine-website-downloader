import pathlib
import tempfile
import unittest

import wayback_mirror as wm


def capture(url, timestamp="20260417195810", mimetype="text/html"):
    return wm.Capture(timestamp, url, mimetype, "200", "DIGEST", "10")


class MirrorTests(unittest.TestCase):
    def test_parse_original_url(self):
        self.assertEqual(wm.parse_original_url("https://example.com/a/"), "https://example.com/a/")

    def test_rejects_wayback_replay_url(self):
        with self.assertRaisesRegex(ValueError, "original site URL"):
            wm.parse_original_url("https://web.archive.org/web/20260417195810/https://example.com/")

    def test_rejects_non_https_url(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            wm.parse_original_url("http://example.com/")

    def test_nearest_capture_per_exact_url(self):
        chosen = wm.select_captures([
            capture("https://e.test/a", "20260101000000"),
            capture("https://e.test/a", "20260417195821"),
            capture("https://e.test/b", "20260417195822"),
        ], "20260417195810")
        self.assertEqual([(x.original, x.timestamp) for x in chosen], [
            ("https://e.test/a", "20260417195821"),
            ("https://e.test/b", "20260417195822"),
        ])

    def test_latest_capture_per_exact_url(self):
        chosen = wm.select_captures([
            capture("https://example.com/a", "20260101000000"),
            capture("https://example.com/a", "20260417195821"),
        ], "latest")
        self.assertEqual(chosen[0].timestamp, "20260417195821")

    def test_paths_and_rewriting(self):
        items = [capture("https://e.test/"), capture("https://e.test/guide/"), capture("https://e.test/assets/app.css", mimetype="text/css")]
        paths = wm.assign_paths(items)
        self.assertEqual(str(paths[items[0].original]), "index.html")
        self.assertEqual(str(paths[items[1].original]), "guide/index.html")
        rewritten = wm.rewrite_text('<a href="/guide/">G</a><link href="/assets/app.css">', capture=items[0], path=paths[items[0].original], paths=paths)
        self.assertIn('href="guide/index.html"', rewritten)
        self.assertIn('href="assets/app.css"', rewritten)


if __name__ == "__main__":
    unittest.main()
