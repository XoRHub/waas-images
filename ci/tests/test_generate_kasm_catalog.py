"""Tests for ci/generate_kasm_catalog.py with Docker Hub mocked:
release-tag selection amid kasm's noisy tags, pagination, and the
knownVersion fallback on network failure. stdlib unittest only."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate_kasm_catalog as gkc  # noqa: E402

MAPPING = {
    "images": [
        {"name": "terminal", "app": "terminal", "icon": "terminal",
         "displayName": "Kasm Terminal", "knownVersion": "1.19.0",
         "architectures": ["amd64"]},
    ]
}


def hub_page(tags, next_url=None):
    body = json.dumps({
        "results": [{"name": t} for t in tags],
        "next": next_url,
    }).encode()
    return io.BytesIO(body)


class LatestReleaseTag(unittest.TestCase):
    def test_ignores_non_release_tags(self):
        # Hub's -last_updated ordering surfaces edge/rolling/arch tags
        # first (observed live) — only plain X.Y.Z may win.
        page = hub_page(["0.0.7-edge", "develop-edge", "x86_64-1.19.0",
                         "1.19.0-rolling-daily", "1.16.1", "1.19.0", "1.9.0"])
        with mock.patch.object(gkc.urllib.request, "urlopen",
                               return_value=page):
            self.assertEqual(gkc.latest_release_tag("terminal"), "1.19.0")

    def test_numeric_not_lexicographic_ordering(self):
        page = hub_page(["1.9.0", "1.10.0"])
        with mock.patch.object(gkc.urllib.request, "urlopen",
                               return_value=page):
            self.assertEqual(gkc.latest_release_tag("terminal"), "1.10.0")

    def test_follows_pagination(self):
        pages = [hub_page(["develop"], next_url="page2"),
                 hub_page(["1.19.0"])]
        with mock.patch.object(gkc.urllib.request, "urlopen",
                               side_effect=pages):
            self.assertEqual(gkc.latest_release_tag("terminal"), "1.19.0")

    def test_no_release_tag_returns_none(self):
        with mock.patch.object(gkc.urllib.request, "urlopen",
                               return_value=hub_page(["develop"])):
            self.assertIsNone(gkc.latest_release_tag("terminal"))


class Catalog(unittest.TestCase):
    def test_success(self):
        with mock.patch.object(gkc, "latest_release_tag",
                               return_value="1.20.0"):
            out = gkc.catalog(MAPPING)
        self.assertEqual(out["apiVersion"], "waas.xorhub.io/catalog/v1")
        self.assertEqual(out["images"], [{
            "image": "docker.io/kasmweb/terminal:1.20.0",
            "os": "linux",
            "app": "terminal",
            "version": "1.20.0",
            "icon": "terminal",
            "displayName": "Kasm Terminal",
            "architectures": ["amd64"],
        }])

    def test_missing_architectures_omitted(self):
        mapping = {"images": [
            {"name": "chrome", "app": "chrome", "knownVersion": "1.19.0"},
        ]}
        with mock.patch.object(gkc, "latest_release_tag",
                               return_value="1.20.0"):
            out = gkc.catalog(mapping)
        self.assertNotIn("architectures", out["images"][0])

    def test_network_failure_falls_back_to_known_version(self):
        with mock.patch.object(gkc.urllib.request, "urlopen",
                               side_effect=URLError("unreachable")):
            out = gkc.catalog(MAPPING)
        self.assertEqual(out["images"][0]["image"],
                         "docker.io/kasmweb/terminal:1.19.0")
        self.assertEqual(out["images"][0]["version"], "1.19.0")

    def test_no_release_tag_falls_back_to_known_version(self):
        with mock.patch.object(gkc, "latest_release_tag", return_value=None):
            out = gkc.catalog(MAPPING)
        self.assertEqual(out["images"][0]["version"], "1.19.0")


if __name__ == "__main__":
    unittest.main()
