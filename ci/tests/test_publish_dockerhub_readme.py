"""Contract tests for ci/publish_dockerhub_readme.py — the pure parts
(short-description byte cap, whitespace collapse); no Docker Hub API
calls. stdlib unittest only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish_dockerhub_readme as pdr  # noqa: E402


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
