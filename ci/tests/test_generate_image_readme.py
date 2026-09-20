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
    "description": "XFCE desktop over VNC, derived from the apt core image.",
    "version": "1.0.0",
    "icon": "ubuntu-linux",
    "variants": [
        {
            "name": "ubuntu-desktop-noble",
            "smoke": {"vnc": True, "audio": True},
        },
        # An internal build parent, and one CI does not even probe over
        # VNC — the protocol section must not depend on smoke.vnc.
        {
            "name": "core-ubuntu-noble",
            "smoke": {"audio": True},
        },
    ],
}


class RenderFormat(unittest.TestCase):
    def setUp(self):
        variants = gp.flatten_variants([BASE_MANIFEST], CFG)
        self.desktop = variants["ubuntu-desktop-noble"]
        self.unprobed = variants["core-ubuntu-noble"]

    def test_title_falls_back_to_description(self):
        self.assertTrue(gir.render(self.desktop).startswith(f"# {self.desktop['description']}"))

    def test_vnc_always_documented(self):
        for v in (self.desktop, self.unprobed):
            self.assertIn("**VNC**", gir.render(v))
            self.assertIn("WAAS_DESKTOP_PASSWORD", gir.render(v))

    def test_vnc_is_the_only_protocol(self):
        # xrdp/sshd left the images (waas#117): no render may advertise
        # another protocol, whatever the manifest's smoke: block says.
        for v in (self.desktop, self.unprobed):
            out = gir.render(v)
            self.assertNotIn("**RDP**", out)
            self.assertNotIn("**SSH**", out)
            self.assertNotIn("WAAS_RDP_", out)
            self.assertNotIn("WAAS_SSH_", out)

    def test_links_project_and_waas(self):
        out = gir.render(self.desktop)
        self.assertIn(gir.PROJECT_URL, out)
        self.assertIn(gir.WAAS_URL, out)

    def test_heading_level_is_configurable(self):
        out = gir.render(self.desktop, heading="##")
        self.assertTrue(out.startswith(f"## {self.desktop['description']}"))
        self.assertIn("### Protocols", out)


class PublishedVariants(unittest.TestCase):
    def test_core_prefixed_variants_excluded(self):
        variants = gp.flatten_variants([BASE_MANIFEST], CFG)
        published = gir.published_variants(variants)
        self.assertIn("ubuntu-desktop-noble", published)
        self.assertNotIn("core-ubuntu-noble", published)


class RenderSummary(unittest.TestCase):
    def test_includes_every_published_variant(self):
        variants = gp.flatten_variants([BASE_MANIFEST], CFG)
        published = gir.published_variants(variants)
        summary = gir.render_summary(published)
        self.assertIn("ubuntu-desktop-noble", summary)
        self.assertNotIn("core-ubuntu-noble", summary)

    def test_links_readme_not_a_generated_file(self):
        summary = gir.render_summary({})
        self.assertIn("README.md", summary)


if __name__ == "__main__":
    unittest.main()
