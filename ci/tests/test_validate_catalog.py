"""Contract tests for ci/validate_catalog.py against the vendored
schema (ci/schema/v1.schema.json — see ci/schema/README.md). stdlib
unittest only, same convention as test_generate_catalog.py."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validate_catalog as vc  # noqa: E402

SCHEMA = json.loads(vc.SCHEMA_PATH.read_text())


def minimal() -> dict:
    return {
        "apiVersion": "waas.xorhub.io/catalog/v1",
        "images": [{"image": "ghcr.io/xorhub/waas-images/ubuntu-xfce:1.1.0"}],
    }


class ValidateCatalog(unittest.TestCase):
    def test_minimal_valid(self):
        self.assertEqual(vc.validate(minimal(), SCHEMA), [])

    def test_full_entry_valid(self):
        data = minimal()
        data["images"][0].update(
            os="linux", app="ubuntu-xfce", version="1.1.0",
            icon="ubuntu-linux", displayName="XFCE desktop")
        self.assertEqual(vc.validate(data, SCHEMA), [])

    def test_full_recommended_entry_valid(self):
        # waas docs/image-catalog.md's canonical example (~lines 151-187
        # at 2026-07-16) — the exact shape ci/generate_catalog.py must
        # be able to emit.
        data = minimal()
        data["images"][0].update(
            os="linux", app="ubuntu-xfce", version="1.1.0",
            profile="hardened",
            recommended={
                "podSecurityContext": {"runAsUser": 1000, "runAsNonRoot": True},
                "securityContext": {
                    "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]},
                },
                "volumes": [
                    {"name": "tmp", "mountPath": "/tmp"},
                    {"name": "run", "mountPath": "/run", "readOnly": True},
                ],
                "env": [
                    {
                        "name": "WAAS_SSH_ENABLED",
                        "description": "Enable sshd (publickey only) — boolean '0'/'1'",
                        "protocols": ["ssh"],
                        "default": "0",
                        "requires": ["WAAS_SSH_AUTHORIZED_KEYS_FILE"],
                    },
                    {
                        "name": "WAAS_SSH_AUTHORIZED_KEYS_FILE",
                        "description": "Path to the authorized public key.",
                        "protocols": ["ssh"],
                    },
                ],
            },
        )
        self.assertEqual(vc.validate(data, SCHEMA), [])

    def test_profile_out_of_enum(self):
        data = minimal()
        data["images"][0]["profile"] = "bogus"
        self.assertTrue(vc.validate(data, SCHEMA))

    def test_recommended_unknown_key(self):
        data = minimal()
        data["images"][0]["recommended"] = {"bogus": True}
        self.assertTrue(vc.validate(data, SCHEMA))

    def test_missing_api_version(self):
        data = minimal()
        del data["apiVersion"]
        self.assertTrue(vc.validate(data, SCHEMA))

    def test_wrong_api_version(self):
        data = minimal()
        data["apiVersion"] = "waas.xorhub.io/catalog/v2"
        self.assertTrue(vc.validate(data, SCHEMA))

    def test_missing_image(self):
        data = minimal()
        del data["images"][0]["image"]
        self.assertTrue(vc.validate(data, SCHEMA))

    def test_os_out_of_enum(self):
        data = minimal()
        data["images"][0]["os"] = "macos"
        self.assertTrue(vc.validate(data, SCHEMA))

    def test_unknown_entry_key(self):
        data = minimal()
        data["images"][0]["img"] = "typo"
        self.assertTrue(vc.validate(data, SCHEMA))

    def test_unknown_root_key(self):
        data = minimal()
        data["catalog"] = []
        self.assertTrue(vc.validate(data, SCHEMA))

    def test_reports_every_violation(self):
        data = minimal()
        data["images"].append({"os": "macos"})  # missing image + bad os
        data["images"][0]["img"] = "typo"
        self.assertGreaterEqual(len(vc.validate(data, SCHEMA)), 3)


if __name__ == "__main__":
    unittest.main()
