"""Tests for ci/generate_kasm_catalog.py with Docker Hub mocked:
release-tag selection amid kasm's noisy tags, pagination, the
knownVersion fallback on network failure, per-tag architecture lookup,
and profile/recommended derivation via an injected hardening probe
(never a real subprocess/Docker call here). stdlib unittest only."""
import copy
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate_catalog as gc  # noqa: E402
import generate_kasm_catalog as gkc  # noqa: E402

MAPPING = {
    "images": [
        {"name": "terminal", "app": "terminal", "icon": "terminal",
         "displayName": "Kasm Terminal", "knownVersion": "1.19.0"},
    ]
}


def hub_page(tags, next_url=None):
    body = json.dumps({
        "results": [{"name": t} for t in tags],
        "next": next_url,
    }).encode()
    return io.BytesIO(body)


def hub_tag_detail(architectures):
    body = json.dumps({
        "images": [{"architecture": a} for a in architectures],
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


class HubArchitectures(unittest.TestCase):
    def test_returns_sorted_enum_architectures(self):
        with mock.patch.object(
            gkc.urllib.request, "urlopen",
            return_value=hub_tag_detail(["arm64", "amd64"]),
        ):
            self.assertEqual(
                gkc.hub_architectures("terminal", "1.19.0"), ["amd64", "arm64"])

    def test_filters_non_enum_architectures(self):
        with mock.patch.object(
            gkc.urllib.request, "urlopen",
            return_value=hub_tag_detail(["amd64", "riscv64"]),
        ):
            self.assertEqual(
                gkc.hub_architectures("terminal", "1.19.0"), ["amd64"])

    def test_network_failure_returns_none(self):
        with mock.patch.object(gkc.urllib.request, "urlopen",
                               side_effect=URLError("unreachable")):
            self.assertIsNone(gkc.hub_architectures("terminal", "1.19.0"))

    def test_no_images_returns_none(self):
        with mock.patch.object(
            gkc.urllib.request, "urlopen", return_value=hub_tag_detail([]),
        ):
            self.assertIsNone(gkc.hub_architectures("terminal", "1.19.0"))


class Catalog(unittest.TestCase):
    def _catalog(self, mapping=MAPPING, **kwargs):
        with mock.patch.object(gkc, "latest_release_tag",
                               return_value="1.20.0"), \
             mock.patch.object(gkc, "hub_architectures",
                               return_value=["amd64"]):
            return gkc.catalog(mapping, **kwargs)

    def test_success(self):
        out = self._catalog()
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
                               return_value="1.20.0"), \
             mock.patch.object(gkc, "hub_architectures", return_value=None):
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

    def test_no_profile_when_probe_returns_none(self):
        # Default probe (no --probe-hardening) is a no-op lambda -> None.
        out = self._catalog()
        self.assertNotIn("profile", out["images"][0])
        self.assertNotIn("recommended", out["images"][0])

    def test_hardened_probe_reuses_generate_catalog_standard(self):
        out = self._catalog(probe=lambda ref: "hardened")
        entry = out["images"][0]
        self.assertEqual(entry["profile"], "hardened")
        self.assertEqual(entry["recommended"], gc.RECOMMENDATION_STANDARD)
        # Deep-copied, not the same object this module could accidentally
        # mutate on a later entry.
        self.assertIsNot(entry["recommended"], gc.RECOMMENDATION_STANDARD)

    def test_normal_probe_has_no_security_context_or_volumes_claim(self):
        out = self._catalog(probe=lambda ref: "normal")
        entry = out["images"][0]
        self.assertEqual(entry["profile"], "normal")
        self.assertEqual(entry["recommended"], gkc.KASM_RECOMMENDATION_NORMAL)
        self.assertNotIn("securityContext", entry["recommended"])
        self.assertNotIn("volumes", entry["recommended"])

    def test_previous_same_version_skips_probe(self):
        previous = {"terminal": {
            "image": "docker.io/kasmweb/terminal:1.20.0",
            "profile": "hardened",
            "recommended": copy.deepcopy(gc.RECOMMENDATION_STANDARD),
        }}
        probe = mock.Mock(side_effect=AssertionError("must not be called"))
        out = self._catalog(probe=probe, previous=previous)
        probe.assert_not_called()
        entry = out["images"][0]
        self.assertEqual(entry["profile"], "hardened")
        self.assertEqual(entry["recommended"], gc.RECOMMENDATION_STANDARD)

    def test_previous_different_version_reprobes(self):
        previous = {"terminal": {
            "image": "docker.io/kasmweb/terminal:1.19.0",  # stale version
            "profile": "hardened",
            "recommended": gc.RECOMMENDATION_STANDARD,
        }}
        probe = mock.Mock(return_value="normal")
        out = self._catalog(probe=probe, previous=previous)
        probe.assert_called_once_with("docker.io/kasmweb/terminal:1.20.0")
        self.assertEqual(out["images"][0]["profile"], "normal")


if __name__ == "__main__":
    unittest.main()
