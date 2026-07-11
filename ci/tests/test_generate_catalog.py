"""Format-contract tests for ci/generate_catalog.py against fabricated
manifests (README § Image catalogs / docs/studies/
prompt-feature13-catalog-publishing.md). stdlib unittest only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate_catalog as gc  # noqa: E402
import generate_pipeline as gp  # noqa: E402

CFG = {
    "os": {"ubuntu-24.04": {}, "debian-13": {}},
    "defaults": {"os": "ubuntu-24.04", "archs": ["linux/amd64"]},
}

MANIFESTS = [
    {
        "name": "ubuntu-xfce",
        "layer": "desktop",
        "context": "desktop/xfce",
        "dockerfile": None,
        "description": "XFCE desktop, VNC + RDP, derived from the apt base-rdp image.",
        "version": "1.1.0",
        "icon": "ubuntu-linux",
        "variants": [
            {"name": "ubuntu-xfce"},
            # Per-variant icon override, the smoke:/buildArgs: convention.
            {"name": "debian-xfce", "os": "debian-13", "icon": "debian-linux"},
        ],
    },
    {
        "name": "ubuntu-firefox",
        "layer": "apps",
        "context": "apps/firefox",
        "dockerfile": None,
        "description": "",  # no displayName emitted
        "version": "1.0.3",
        # no icon: key at all — field must be absent, not empty
        "variants": [{"name": "ubuntu-firefox"}],
    },
]


class CatalogFormat(unittest.TestCase):
    def setUp(self):
        variants = gp.flatten_variants(MANIFESTS, CFG)
        self.out = gc.catalog(variants, "registry.gitlab.com/acme/waas-images")
        self.by_app = {e["app"]: e for e in self.out["images"]}

    def test_api_version(self):
        self.assertEqual(self.out["apiVersion"], "waas.xorhub.io/catalog/v1")

    def test_one_entry_per_variant(self):
        self.assertEqual(
            sorted(self.by_app), ["debian-xfce", "ubuntu-firefox", "ubuntu-xfce"])

    def test_full_entry(self):
        self.assertEqual(self.by_app["ubuntu-xfce"], {
            "image": "registry.gitlab.com/acme/waas-images/ubuntu-xfce:1.1.0",
            "os": "linux",
            "app": "ubuntu-xfce",
            "version": "1.1.0",
            "icon": "ubuntu-linux",
            "displayName": "XFCE desktop, VNC + RDP, derived from the apt base-rdp image.",
        })

    def test_variant_icon_override(self):
        self.assertEqual(self.by_app["debian-xfce"]["icon"], "debian-linux")

    def test_missing_icon_and_description_omitted(self):
        entry = self.by_app["ubuntu-firefox"]
        self.assertNotIn("icon", entry)
        self.assertNotIn("displayName", entry)
        self.assertEqual(
            entry["image"],
            "registry.gitlab.com/acme/waas-images/ubuntu-firefox:1.0.3")

    def test_image_ref_has_no_digest(self):
        for entry in self.out["images"]:
            self.assertNotIn("@", entry["image"])

    def test_display_name_truncated(self):
        manifests = [dict(MANIFESTS[0], description="word " * 40)]
        variants = gp.flatten_variants(manifests, CFG)
        out = gc.catalog(variants, "reg")
        for entry in out["images"]:
            self.assertLessEqual(len(entry["displayName"]), 80)
            self.assertTrue(entry["displayName"].endswith("…"))


if __name__ == "__main__":
    unittest.main()
