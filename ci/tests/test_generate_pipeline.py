"""Contract tests for ci/generate_pipeline.py's manifest flattening.
stdlib unittest only, same convention as test_generate_catalog.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import generate_pipeline as gp  # noqa: E402

CFG = {
    "os": {"ubuntu-24.04": {}, "debian-13": {}},
    "defaults": {"os": "ubuntu-24.04", "archs": ["linux/amd64"]},
}

MANIFEST = {
    "name": "ubuntu-firefox",
    "layer": "apps",
    "context": "apps/firefox",
    "dockerfile": None,
    "description": "Policy-managed Firefox, single-app kiosk.",
    "version": "1.0.3",
    "variants": [{"name": "ubuntu-firefox", "smoke": {"vnc": True}}],
}


def with_smoke(smoke: dict) -> list[dict]:
    return [dict(MANIFEST, variants=[{"name": "ubuntu-firefox", "smoke": smoke}])]


class FlattenVariantsSmoke(unittest.TestCase):
    """smoke: is a closed key set (generate_pipeline.SMOKE_KEYS): a key
    naming a probe nothing runs must fail generation, not be skipped."""

    def test_dropped_protocol_keys_are_refused(self):
        # xrdp/sshd left the images (waas#117) and ci/smoke_test.sh lost
        # their probes with them — a manifest still asking for one must
        # not pass as "smoke-tested".
        for key in ("rdp", "ssh"):
            with self.assertRaises(SystemExit):
                gp.flatten_variants(with_smoke({"vnc": True, key: True}), CFG)

    def test_known_keys_pass(self):
        variants = gp.flatten_variants(
            with_smoke({"vnc": True, "audio": True, "env": {"X": "1"}}), CFG)
        self.assertIn("ubuntu-firefox", variants)


if __name__ == "__main__":
    unittest.main()
