"""Format-contract tests for ci/generate_catalog.py against fabricated
manifests (README § Image catalogs / docs/studies/
prompt-feature13-catalog-publishing.md). stdlib unittest only."""
import sys
import tempfile
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
            # Build matrix defaults (CFG): linux/amd64 -> amd64.
            "architectures": ["amd64"],
            # No smoke: on this fixture's variant, so no env hints — but
            # profile/recommended are still always present (total mapping).
            "profile": "hardened",
            "recommended": gc.RECOMMENDATION_STANDARD,
        })

    def test_architectures_follow_variant_archs(self):
        # A multi-arch variant emits both, buildx platform prefix
        # stripped; the arch list is per variant, not per manifest.
        manifests = [dict(
            MANIFESTS[1],
            variants=[{"name": "ubuntu-firefox",
                       "archs": ["linux/amd64", "linux/arm64"]}],
        )]
        variants = gp.flatten_variants(manifests, CFG)
        out = gc.catalog(variants, "reg")
        self.assertEqual(
            out["images"][0]["architectures"], ["amd64", "arm64"])

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

    def test_core_prefixed_variants_never_published(self):
        # core-*: internal build parents only (base + the apps/* desktop
        # parent) — must never appear in the catalog, even though
        # flatten_variants happily returns them like any other variant.
        manifests = MANIFESTS + [{
            "name": "ubuntu-core",
            "layer": "base",
            "context": "base/ubuntu",
            "dockerfile": None,
            "description": "internal parent",
            "version": "1.0.0",
            "variants": [{"name": "core-ubuntu-noble"}],
        }]
        variants = gp.flatten_variants(manifests, CFG)
        out = gc.catalog(variants, "reg")
        by_app = {e["app"]: e for e in out["images"]}
        self.assertNotIn("core-ubuntu-noble", by_app)


RECOMMENDED_MANIFESTS = [
    {
        "name": "ubuntu-desktop-full",
        "layer": "base",
        "context": "base/ubuntu",
        "dockerfile": None,
        "description": "OS-only desktop, VNC + RDP + SSH.",
        "version": "1.0.0",
        "variants": [
            {"name": "ubuntu-desktop-full",
             "smoke": {"vnc": True, "rdp": True, "ssh": True}},
        ],
    },
    {
        "name": "chrome",
        "layer": "apps",
        "context": "apps/chrome",
        "dockerfile": None,
        "description": "Chrome desktop, VNC only.",
        "version": "1.0.0",
        # Mirrors apps/chrome/manifest.yaml: only vnc: true declared,
        # no explicit rdp:/ssh: false.
        "variants": [{"name": "chrome", "smoke": {"vnc": True}}],
    },
    {
        "name": "devtools",
        "layer": "apps",
        "context": "apps/devtools",
        "dockerfile": None,
        "description": "Dev desktop.",
        "version": "1.0.0",
        "variants": [
            {"name": "devtools", "smoke": {"vnc": True}},
            {"name": "devtools-dev", "profile": "dev", "smoke": {"vnc": True}},
        ],
    },
]


class CatalogRecommended(unittest.TestCase):
    """profile/recommended derivation (variant profile: + HARDENING.md-
    mirroring constants + smoke:-derived env hints)."""

    def setUp(self):
        variants = gp.flatten_variants(RECOMMENDED_MANIFESTS, CFG)
        self.out = gc.catalog(variants, "reg")
        self.by_app = {e["app"]: e for e in self.out["images"]}

    def test_standard_profile_maps_to_hardened(self):
        entry = self.by_app["chrome"]
        self.assertEqual(entry["profile"], "hardened")
        sec = entry["recommended"]["securityContext"]
        self.assertTrue(sec["readOnlyRootFilesystem"])
        self.assertFalse(sec["allowPrivilegeEscalation"])
        self.assertEqual(sec["capabilities"], {"drop": ["ALL"]})
        self.assertEqual(entry["recommended"]["volumes"], [
            {"name": "tmp", "mountPath": "/tmp"},
            {"name": "run", "mountPath": "/run"},
        ])

    def test_dev_profile_maps_to_normal_with_exceptions(self):
        entry = self.by_app["devtools-dev"]
        self.assertEqual(entry["profile"], "normal")
        sec = entry["recommended"]["securityContext"]
        self.assertFalse(sec["readOnlyRootFilesystem"])
        self.assertTrue(sec["allowPrivilegeEscalation"])
        # Runtime-default capabilities kept — never an explicit empty drop.
        self.assertNotIn("capabilities", sec)
        # podSecurityContext (non-root UID/GID, seccomp) holds unchanged.
        self.assertEqual(
            entry["recommended"]["podSecurityContext"],
            self.by_app["devtools"]["recommended"]["podSecurityContext"])

    def test_env_hints_follow_smoke(self):
        self.assertEqual(
            [h["name"] for h in self.by_app["ubuntu-desktop-full"]["recommended"]["env"]],
            ["WAAS_RDP_ENABLED", "WAAS_RDP_AUTH_ENABLED", "WAAS_SSH_ENABLED",
             "WAAS_SSH_AUTHORIZED_KEYS_FILE", "WAAS_AUDIO_ENABLED"])
        self.assertEqual(
            [h["name"] for h in self.by_app["chrome"]["recommended"]["env"]],
            ["WAAS_AUDIO_ENABLED"])

    def test_no_smoke_protocols_omits_env_key(self):
        # MANIFESTS' ubuntu-xfce/debian-xfce carry no smoke: at all.
        variants = gp.flatten_variants(MANIFESTS, CFG)
        out = gc.catalog(variants, "reg")
        by_app = {e["app"]: e for e in out["images"]}
        self.assertNotIn("env", by_app["ubuntu-xfce"]["recommended"])


class CatalogFallback(unittest.TestCase):
    """A variant whose current <version> was never actually published
    (this run's build failed) must fall back to the last version that
    WAS, per catalog-waas-images.yaml, not emit a 404 — and must
    disappear entirely if there's nothing to fall back to."""

    def setUp(self):
        self.variants = gp.flatten_variants(MANIFESTS, CFG)

    def test_unpublished_falls_back_to_previous(self):
        previous = {
            "ubuntu-xfce": {
                "image": "registry.gitlab.com/acme/waas-images/ubuntu-xfce:1.0.4",
                "os": "linux", "app": "ubuntu-xfce", "version": "1.0.4",
            },
        }
        out = gc.catalog(
            self.variants, "registry.gitlab.com/acme/waas-images",
            exists=lambda ref: "ubuntu-xfce:1.1.0" not in ref,
            previous=previous,
        )
        by_app = {e["app"]: e for e in out["images"]}
        entry = by_app["ubuntu-xfce"]
        self.assertEqual(entry["image"],
                          "registry.gitlab.com/acme/waas-images/ubuntu-xfce:1.0.4")
        self.assertEqual(entry["version"], "1.0.4")
        # Metadata (icon/displayName) still reflects the CURRENT manifest,
        # only image/version are pinned to the fallback.
        self.assertEqual(entry["icon"], "ubuntu-linux")
        # The other two variants were unaffected.
        self.assertEqual(sorted(by_app), ["debian-xfce", "ubuntu-firefox", "ubuntu-xfce"])

    def test_unpublished_without_previous_is_omitted(self):
        out = gc.catalog(
            self.variants, "registry.gitlab.com/acme/waas-images",
            exists=lambda ref: "ubuntu-xfce:1.1.0" not in ref,
            previous={},
        )
        by_app = {e["app"]: e for e in out["images"]}
        self.assertNotIn("ubuntu-xfce", by_app)
        self.assertEqual(sorted(by_app), ["debian-xfce", "ubuntu-firefox"])

    def test_published_ignores_previous(self):
        # exists() says every ref is fine — the fallback path must
        # never trigger even if `previous` disagrees.
        previous = {
            "ubuntu-xfce": {
                "image": "registry.gitlab.com/acme/waas-images/ubuntu-xfce:0.0.1",
                "os": "linux", "app": "ubuntu-xfce", "version": "0.0.1",
            },
        }
        out = gc.catalog(
            self.variants, "registry.gitlab.com/acme/waas-images",
            exists=lambda ref: True, previous=previous,
        )
        by_app = {e["app"]: e for e in out["images"]}
        self.assertEqual(by_app["ubuntu-xfce"]["version"], "1.1.0")


class LoadPrevious(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(gc.load_previous(Path("/nonexistent/catalog.yaml")), {})

    def test_malformed_yaml_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("apiVersion: [unterminated")
            path = Path(f.name)
        try:
            self.assertEqual(gc.load_previous(path), {})
        finally:
            path.unlink()

    def test_valid_file_keyed_by_app(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(
                "apiVersion: waas.xorhub.io/catalog/v1\n"
                "images:\n"
                "- image: reg/ubuntu-xfce:1.0.4\n"
                "  app: ubuntu-xfce\n"
                "  version: \"1.0.4\"\n"
            )
            path = Path(f.name)
        try:
            self.assertEqual(
                gc.load_previous(path),
                {"ubuntu-xfce": {"image": "reg/ubuntu-xfce:1.0.4",
                                  "app": "ubuntu-xfce", "version": "1.0.4"}},
            )
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
