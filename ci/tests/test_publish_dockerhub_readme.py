"""Contract tests for ci/publish_dockerhub_readme.py — the pure parts
(short-description cap, payload shape); no Docker Hub API calls.
stdlib unittest only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish_dockerhub_readme as pdr  # noqa: E402


class ShortDescription(unittest.TestCase):
    def test_short_text_passes_through(self):
        self.assertEqual(pdr.short_description("XFCE desktop"), "XFCE desktop")

    def test_never_exceeds_hub_cap(self):
        out = pdr.short_description("x" * 500)
        self.assertEqual(len(out), pdr.SHORT_DESCRIPTION_MAX)
        self.assertTrue(out.endswith("…"))

    def test_exactly_at_cap_untruncated(self):
        text = "x" * pdr.SHORT_DESCRIPTION_MAX
        self.assertEqual(pdr.short_description(text), text)

    def test_manifest_newlines_collapsed(self):
        # Manifest descriptions use YAML folded blocks — any residual
        # newline/indent whitespace must not reach Hub's one-line field.
        self.assertEqual(pdr.short_description("a\n  b\n"), "a b")


if __name__ == "__main__":
    unittest.main()
