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
