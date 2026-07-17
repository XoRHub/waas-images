"""Contract tests for ci/publish_dockerhub_readme.py — the pure parts
(short-description byte cap, whitespace collapse); no Docker Hub API
calls. stdlib unittest only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish_dockerhub_readme as pdr  # noqa: E402


VARIANT = {
    "name": "demo",
    "layer": "apps",
    "os": "ubuntu-noble",
    "version": "1.0.0",
    "description": "Demo app.",
    "smoke": {"vnc": True},
}


class FullReadme(unittest.TestCase):
    def test_template_has_each_placeholder(self):
        text = pdr.TEMPLATE.read_text()
        self.assertEqual(text.count("{about}"), 1)
        self.assertIn("{image}", text)

    def test_splices_section_and_image_ref(self):
        out = pdr.full_readme(VARIANT, "docker.io/xorhub/demo:1.0.0")
        self.assertIn("# Demo app.", out)          # per-image section
        self.assertIn("**VNC**", out)              # render() content
        self.assertIn("docker.io/xorhub/demo:1.0.0", out)
        self.assertNotIn("{about}", out)
        self.assertNotIn("{image}", out)

    def test_stays_under_hub_cap(self):
        out = pdr.full_readme(VARIANT, "docker.io/xorhub/demo:1.0.0")
        self.assertLessEqual(len(out), pdr.FULL_DESCRIPTION_MAX)


class TemplateReadmeParity(unittest.TestCase):
    """GHCR package pages render the repo README, Docker Hub renders the
    template — the shared boilerplate must be byte-identical or the two
    registries drift apart (the iso contract stated in both files)."""

    GENERIC_REF = "docker.io/xorhub/<image>:<version>"

    def test_every_template_command_block_is_in_readme(self):
        import re

        readme = (pdr.TEMPLATE.parent.parent / "README.md").read_text()
        template = pdr.TEMPLATE.read_text().replace("{image}", self.GENERIC_REF)
        blocks = re.findall(r"```shell\n(.*?)```", template, flags=re.S)
        self.assertTrue(blocks, "template lost its ```shell blocks")
        for block in blocks:
            self.assertIn(block, readme)


class ShortDescription(unittest.TestCase):
    def test_short_text_passes_through(self):
        self.assertEqual(pdr.short_description("XFCE desktop"), "XFCE desktop")

    def test_never_exceeds_hub_byte_cap(self):
        out = pdr.short_description("x" * 500)
        self.assertLessEqual(len(out.encode()), pdr.SHORT_DESCRIPTION_MAX_BYTES)
        self.assertTrue(out.endswith("…"))

    def test_cap_is_bytes_not_chars(self):
        # 100 chars of 3-byte em-dashes = 300 bytes: the char-based cap
        # that shipped first let this through and Hub 400'd on it.
        out = pdr.short_description("—" * 100)
        self.assertLessEqual(len(out.encode()), pdr.SHORT_DESCRIPTION_MAX_BYTES)

    def test_truncation_never_splits_a_multibyte_char(self):
        # Byte 97 lands mid-em-dash for many alignments; the result must
        # still be valid UTF-8 with no replacement/partial artifacts.
        for pad in range(4):
            out = pdr.short_description("x" * pad + "—" * 60)
            out.encode()  # round-trips iff no mangled code point
            self.assertLessEqual(len(out.encode()), pdr.SHORT_DESCRIPTION_MAX_BYTES)

    def test_exactly_at_cap_untruncated(self):
        text = "x" * pdr.SHORT_DESCRIPTION_MAX_BYTES
        self.assertEqual(pdr.short_description(text), text)

    def test_manifest_newlines_collapsed(self):
        # Manifest descriptions use YAML folded blocks — any residual
        # newline/indent whitespace must not reach Hub's one-line field.
        self.assertEqual(pdr.short_description("a\n  b\n"), "a b")


if __name__ == "__main__":
    unittest.main()
