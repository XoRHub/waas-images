"""Format-contract tests for ci/generate_image_readme.py against
fabricated manifests. stdlib unittest only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate_image_readme as gir  # noqa: E402
import generate_pipeline as gp  # noqa: E402

CFG = {
    "os": {"ubuntu-24.04": {}},
    "defaults": {"os": "ubuntu-24.04", "archs": ["linux/amd64"]},
}

BASE_MANIFEST = {
    "name": "ubuntu-desktop",
    "layer": "desktop",
    "context": "desktop/xfce",
    "dockerfile": None,
    "description": "XFCE desktop, VNC + RDP + SSH, derived from the apt core-full image.",
    "version": "1.0.0",
    "icon": "ubuntu-linux",
    "variants": [
        {
            "name": "ubuntu-desktop-noble",
            "smoke": {"vnc": True, "rdp": True, "ssh": True, "audio": True},
        },
        {
            "name": "core-ubuntu-noble-xfce",
            "smoke": {"vnc": True, "rdp": False, "audio": True},
        },
    ],
}


class RenderFormat(unittest.TestCase):
    def setUp(self):
        variants = gp.flatten_variants([BASE_MANIFEST], CFG)
        self.full = variants["ubuntu-desktop-noble"]
        self.vnc_only = variants["core-ubuntu-noble-xfce"]

    def test_title_falls_back_to_description(self):
        self.assertTrue(gir.render(self.full).startswith(f"# {self.full['description']}"))

    def test_vnc_always_documented(self):
        for v in (self.full, self.vnc_only):
            self.assertIn("**VNC**", gir.render(v))
            self.assertIn("VNC_PW", gir.render(v))

    def test_rdp_only_when_smoke_rdp_true(self):
        self.assertIn("**RDP**", gir.render(self.full))
        self.assertNotIn("**RDP**", gir.render(self.vnc_only))

    def test_ssh_only_when_smoke_ssh_true(self):
        self.assertIn("**SSH**", gir.render(self.full))
        self.assertIn("WAAS_SSH_AUTHORIZED_KEYS", gir.render(self.full))
        self.assertNotIn("**SSH**", gir.render(self.vnc_only))
        self.assertNotIn("WAAS_SSH_AUTHORIZED_KEYS", gir.render(self.vnc_only))

    def test_links_project_and_waas(self):
        out = gir.render(self.full)
        self.assertIn(gir.PROJECT_URL, out)
        self.assertIn(gir.WAAS_URL, out)

    def test_heading_level_is_configurable(self):
        out = gir.render(self.full, heading="##")
        self.assertTrue(out.startswith(f"## {self.full['description']}"))
        self.assertIn("### Protocols", out)


class PublishedVariants(unittest.TestCase):
    def test_core_prefixed_variants_excluded(self):
        variants = gp.flatten_variants([BASE_MANIFEST], CFG)
        published = gir.published_variants(variants)
        self.assertIn("ubuntu-desktop-noble", published)
        self.assertNotIn("core-ubuntu-noble-xfce", published)


class RenderSummary(unittest.TestCase):
    def test_includes_every_published_variant(self):
        variants = gp.flatten_variants([BASE_MANIFEST], CFG)
        published = gir.published_variants(variants)
        summary = gir.render_summary(published)
        self.assertIn("ubuntu-desktop-noble", summary)
        self.assertNotIn("core-ubuntu-noble-xfce", summary)

    def test_links_readme_not_a_generated_file(self):
        summary = gir.render_summary({})
        self.assertIn("README.md", summary)


if __name__ == "__main__":
    unittest.main()
