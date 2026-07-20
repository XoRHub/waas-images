"""Tests for ci/generate_kasm_catalog.py with Docker Hub mocked:
release-tag selection amid kasm's noisy tags, pagination, the
knownVersion fallback on network failure, per-tag architecture lookup,
profile/recommended derivation via an injected hardening probe (never a
real subprocess/Docker call here), and the single-image CLI mode's
mapping-append/catalog-upsert helpers. stdlib unittest only."""
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

import yaml

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

    def test_description_from_mapping_emitted(self):
        mapping = {"images": [
            {"name": "terminal", "app": "terminal", "knownVersion": "1.19.0",
             "description": "Kasm terminal desktop."},
        ]}
        out = self._catalog(mapping)
        self.assertEqual(out["images"][0]["description"],
                         "Kasm terminal desktop.")

    def test_description_absent_from_mapping_omitted(self):
        # MAPPING's terminal entry carries no description.
        self.assertNotIn("description", self._catalog()["images"][0])

    def test_description_preserved_from_previous_when_mapping_omits_it(self):
        # Never regenerated away: a description the last catalog carried
        # survives even though the mapping (MAPPING) has none.
        previous = {"terminal": {
            "image": "docker.io/kasmweb/terminal:1.20.0",
            "description": "hand-written, must not be erased",
        }}
        out = self._catalog(previous=previous)
        self.assertEqual(out["images"][0]["description"],
                         "hand-written, must not be erased")

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


class AppendMappingEntry(unittest.TestCase):
    def test_appends_without_disturbing_existing_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.yaml"
            path.write_text("# a hand-written comment\nimages:\n"
                            "  - name: terminal\n    app: terminal\n"
                            "    knownVersion: \"1.19.0\"\n")
            gkc.append_mapping_entry(path, "vs-code", "1.20.0")
            text = path.read_text()
            self.assertIn("# a hand-written comment", text)
            self.assertIn("- name: terminal", text)
            self.assertIn("- name: vs-code", text)
            self.assertIn('knownVersion: "1.20.0"', text)
            # Still valid YAML with both images present, appended text
            # didn't break the existing structure.
            data = yaml.safe_load(text)
            self.assertEqual([i["name"] for i in data["images"]],
                             ["terminal", "vs-code"])


class ResolveMappingEntry(unittest.TestCase):
    def test_existing_image_returned_unchanged_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.yaml"
            path.write_text("images:\n  - name: terminal\n    app: terminal\n"
                            "    knownVersion: \"1.19.0\"\n")
            before = path.read_text()
            mapping = {"images": [
                {"name": "terminal", "app": "terminal", "knownVersion": "1.19.0"},
            ]}
            entry = gkc.resolve_mapping_entry(mapping, path, "terminal")
            self.assertEqual(entry["app"], "terminal")
            self.assertEqual(path.read_text(), before)  # untouched

    def test_new_image_resolved_live_and_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.yaml"
            path.write_text("images: []\n")
            mapping = {"images": []}
            with mock.patch.object(gkc, "latest_release_tag",
                                   return_value="1.20.0"):
                entry = gkc.resolve_mapping_entry(mapping, path, "vs-code")
            self.assertEqual(entry, {"name": "vs-code", "app": "vs-code",
                                     "knownVersion": "1.20.0"})
            self.assertIn("vs-code", path.read_text())

    def test_unresolvable_new_image_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.yaml"
            path.write_text("images: []\n")
            mapping = {"images": []}
            with mock.patch.object(gkc, "latest_release_tag",
                                   return_value=None):
                with self.assertRaises(SystemExit):
                    gkc.resolve_mapping_entry(mapping, path, "not-a-real-image")


class UpsertEntry(unittest.TestCase):
    def test_replaces_matching_app_preserves_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog-kasmweb.yaml"
            path.write_text(
                "apiVersion: waas.xorhub.io/catalog/v1\n"
                "images:\n"
                "- image: docker.io/kasmweb/terminal:1.19.0\n"
                "  app: terminal\n"
                "- image: docker.io/kasmweb/firefox:1.19.0\n"
                "  app: firefox\n")
            new_terminal = {"image": "docker.io/kasmweb/terminal:1.20.0",
                            "app": "terminal"}
            out = gkc.upsert_entry(path, new_terminal)
            apps = [i["app"] for i in out["images"]]
            self.assertEqual(apps, ["terminal", "firefox"])  # order preserved
            self.assertEqual(
                out["images"][0]["image"], "docker.io/kasmweb/terminal:1.20.0")
            self.assertEqual(
                out["images"][1]["image"], "docker.io/kasmweb/firefox:1.19.0")

    def test_appends_new_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog-kasmweb.yaml"
            path.write_text(
                "apiVersion: waas.xorhub.io/catalog/v1\n"
                "images:\n- image: docker.io/kasmweb/terminal:1.19.0\n"
                "  app: terminal\n")
            new_entry = {"image": "docker.io/kasmweb/vs-code:1.20.0",
                        "app": "vs-code"}
            out = gkc.upsert_entry(path, new_entry)
            self.assertEqual([i["app"] for i in out["images"]],
                             ["terminal", "vs-code"])

    def test_missing_file_starts_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "does-not-exist.yaml"
            entry = {"image": "docker.io/kasmweb/terminal:1.19.0", "app": "terminal"}
            out = gkc.upsert_entry(path, entry)
            self.assertEqual(out["apiVersion"], gkc.API_VERSION)
            self.assertEqual(out["images"], [entry])


if __name__ == "__main__":
    unittest.main()
