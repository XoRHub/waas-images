#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyyaml==6.0.2",
# ]
# ///
"""Emit catalog-waas-images.yaml — the WaaS picker catalog of the images
THIS repo builds (format contract: README § Image catalogs and
docs/studies/prompt-feature13-catalog-publishing.md).

Reuses generate_pipeline.py's discovery (load_manifests +
flatten_variants) so the catalog can never drift from the build matrix.
Runs AFTER build+push on the default branch — the immutable <version>
tags it references must already exist — unlike generate_pipeline.py
which runs before. `image:version` needs no digest: <version> tags are
immutable by CI construction (README § Build matrix & tagging).

Every entry also carries `profile`/`recommended` — waas's deployment
recommendation fields (wire format: shared/catalog.Entry, vendored
schema: ci/schema/v1.schema.json). Both are derived locally from data
already in this repo (variant `profile:`, `smoke:`, HARDENING.md's
platform-side doctrine) rather than hand-written in any manifest.yaml,
so they cannot drift from the doctrine they mirror. See
RECOMMENDATION_STANDARD/RECOMMENDATION_DEV below.

Every entry is normally "{registry}/{variant name}:{variant version}"
against --registry (default $CI_PUBLIC_REGISTRY_IMAGE, docker.io — the
registry ci/merge_image.sh mirrors the finished <version> manifest list
to; see build.yml). Build/merge itself happens on GHCR
(CI_REGISTRY_IMAGE, CI-internal), and the per-arch "-g<sha>-<arch>"
build/hand-off tags ci/build_image.sh pushes there never enter this
list: they are not manifest variants, just intermediate artifacts this
generator has no reference to.

build.yml's catalog job runs regardless of individual layer/merge
failures (a bad image must not block the other 14) — so for each
variant this generator checks the registry for the ref it's about to
emit. If that exact <version> was never actually published (this run's
build for it failed), it falls back to whatever catalog-waas-images.yaml
already committed on main last has for that app name — the last
version that DID publish successfully — rather than emit a 404. A
variant that has never once published successfully is omitted, not
guessed at.
"""
from __future__ import annotations

import argparse
import copy
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Callable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_pipeline as gp  # noqa: E402

API_VERSION = "waas.xorhub.io/catalog/v1"

# variant["profile"] ("standard"/"dev", set by flatten_variants) -> wire
# Entry.profile ("hardened"/"normal"). Total mapping: flatten_variants
# already rejects any other value, so every catalogued entry gets one.
PROFILE_WIRE_NAME = {"standard": "hardened", "dev": "normal"}

# Mirrors HARDENING.md § "To apply on the platform side" (the pod
# securityContext/volumes recommended for every image built here).
# Keep these two constants and that section in sync by hand — cross-
# reference the line numbers there if you touch either.
RECOMMENDATION_STANDARD = {
    "podSecurityContext": {
        "runAsNonRoot": True,
        "runAsUser": 1000,
        "fsGroup": 1000,
        "seccompProfile": {"type": "RuntimeDefault"},
    },
    "securityContext": {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "readOnlyRootFilesystem": True,
    },
    "volumes": [
        {"name": "tmp", "mountPath": "/tmp"},
        {"name": "run", "mountPath": "/run"},
    ],
}

# Mirrors HARDENING.md § "Reduced profile: `-dev` images" — identical to
# RECOMMENDATION_STANDARD except the four exceptions documented there:
# readOnlyRootFilesystem/allowPrivilegeEscalation flip, and ALL is no
# longer dropped (runtime-default capabilities are kept so the -dev
# image's setuid sudo can regain them within the bounding set — the
# fourth exception, "no setuid binary", has no PodSecurityContext/
# SecurityContext field to express and is a fact of the image, not a
# deployment recommendation).
RECOMMENDATION_DEV = {
    "podSecurityContext": copy.deepcopy(RECOMMENDATION_STANDARD["podSecurityContext"]),
    "securityContext": {
        "allowPrivilegeEscalation": True,
        "readOnlyRootFilesystem": False,
    },
    "volumes": copy.deepcopy(RECOMMENDATION_STANDARD["volumes"]),
}

# smoke.<protocol> (variant["smoke"], the same signal build_vars() reads
# — absent and explicitly False are equivalent everywhere it's read) ->
# the EnvHint(s) to surface for that protocol. Names as actually present
# in this repo today (grep RDP_AUTH_ENABLED README.md HARDENING.md
# base/*/Dockerfile before touching this table — 43-prompt-waas-images-
# env-naming.md would rename RDP_AUTH_ENABLED if it ever lands).
_ENV_HINTS_BY_PROTOCOL = {
    "rdp": [
        {
            "name": "WAAS_RDP_ENABLED",
            "description": "Enable xrdp — boolean '0'/'1'. Requires the "
                            "image to have been built with INSTALL_RDP=1 "
                            "(OS-only images only); no relevant runtime "
                            "default to advertise here.",
            "protocols": ["rdp"],
        },
        {
            "name": "RDP_AUTH_ENABLED",
            "description": "Require the RDP client to present the session "
                            "password. Baked true; an explicit runtime "
                            "false opts out and logs a warning — never a "
                            "build-time toggle.",
            "protocols": ["rdp"],
            "default": "true",
        },
    ],
    "ssh": [
        {
            "name": "WAAS_SSH_ENABLED",
            "description": "Enable sshd (publickey only) — boolean '0'/'1'.",
            "protocols": ["ssh"],
            "default": "0",
            "requires": ["WAAS_SSH_AUTHORIZED_KEYS_FILE"],
        },
        {
            "name": "WAAS_SSH_AUTHORIZED_KEYS_FILE",
            "description": "Path to the authorized public key — mount "
                            "from a Secret (valueFrom.secretKeyRef), never "
                            "a literal value. Required as soon as "
                            "WAAS_SSH_ENABLED=1: the entrypoint refuses to "
                            "start otherwise (fail-closed by design).",
            "protocols": ["ssh"],
        },
    ],
    "vnc": [
        {
            "name": "WAAS_AUDIO_ENABLED",
            "description": "Enable the unprivileged PulseAudio daemon "
                            "(native protocol on TCP 4713, consumed by "
                            "guacd's VNC client) — boolean '0'/'1'.",
            "protocols": ["vnc"],
            "default": "1",
        },
    ],
}


def env_hints(smoke: dict) -> list[dict]:
    """recommended.env for one variant, derived from its smoke: block —
    the only per-image protocol signal that reaches every catalogued
    variant (build_args/INSTALL_RDP/INSTALL_SSH don't: they're never
    redeclared on desktop/*/apps/* manifests, so build_args is empty on
    every variant this generator actually publishes)."""
    hints: list[dict] = []
    for protocol in ("rdp", "ssh", "vnc"):
        if smoke.get(protocol):
            hints.extend(copy.deepcopy(_ENV_HINTS_BY_PROTOCOL[protocol]))
    return hints


def recommended_for(v: dict) -> dict:
    """entry["recommended"] for one variant: the fixed standard/dev
    Recommendation block for its profile, plus env hints for whichever
    protocols its smoke: block declares."""
    base = RECOMMENDATION_DEV if v["profile"] == "dev" else RECOMMENDATION_STANDARD
    recommended = copy.deepcopy(base)
    hints = env_hints(v["smoke"])
    if hints:
        recommended["env"] = hints
    return recommended


def load_previous(path: Path) -> dict[str, dict]:
    """Best-effort read of the catalog this generator last wrote,
    keyed by app name — the fallback source when today's build for an
    image failed. Anything wrong with the file (missing, unparsable)
    just means no fallback is available, not a hard error: this
    generator must never itself be the reason the catalog job fails."""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return {}
    return {img["app"]: img for img in data.get("images", []) if "app" in img}


def registry_has(ref: str) -> bool:
    """True if `ref` (image:tag) actually exists on its registry."""
    return subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def catalog(
    variants: dict[str, dict],
    registry: str,
    *,
    exists: Callable[[str], bool] = lambda ref: True,
    previous: dict[str, dict] | None = None,
) -> dict:
    previous = previous or {}
    images = []
    for name, v in sorted(variants.items()):
        # core-*: internal build parents only (base + the apps/* desktop
        # parent) — never picked by an end user, never published here.
        if name.startswith("core-"):
            continue
        # <registry>/<variant>:<version> — the exact ref the merge
        # job's mirror step pushed (ci/merge_image.sh:
        # ${CI_PUBLIC_REGISTRY_IMAGE}/${IMG_NAME}) — IF that publish
        # actually succeeded; see module docstring for the fallback.
        ref = f"{registry}/{name}:{v['version']}"
        version = v["version"]
        if not exists(ref):
            fallback = previous.get(name)
            if fallback is None:
                print(f"WARNING: {name}:{version} not found on {registry} and "
                      "no previously published catalog entry to fall back to "
                      "— omitted from the catalog", file=sys.stderr)
                continue
            print(f"WARNING: {name}:{version} not found on {registry} — "
                  f"falling back to previously published {fallback['image']}",
                  file=sys.stderr)
            ref = fallback["image"]
            version = fallback["version"]
        entry = {
            "image": ref,
            # Workspace OS family, NOT the build distro (v["os"] is
            # ubuntu-noble/debian-13/fedora-43 — a different notion).
            "os": "linux",
            "app": name,
            "version": version,
        }
        if v["icon"]:
            entry["icon"] = v["icon"]
        if v["description"]:
            entry["displayName"] = textwrap.shorten(
                v["description"], width=80, placeholder="…")
        # Recalculated from the current manifest/HARDENING.md-derived
        # constants every run, exactly like icon/displayName above —
        # never copied from previous[name]. A failed build's fallback
        # entry can therefore reference an old image:version alongside
        # a profile/recommended computed from the CURRENT manifest;
        # that's the same staleness already accepted for icon/
        # displayName, not a new risk.
        entry["profile"] = PROFILE_WIRE_NAME[v["profile"]]
        entry["recommended"] = recommended_for(v)
        images.append(entry)
    return {"apiVersion": API_VERSION, "images": images}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", default=os.environ.get("CI_PUBLIC_REGISTRY_IMAGE"),
        help="public registry prefix the <version> manifest lists were "
             "mirrored to (default: $CI_PUBLIC_REGISTRY_IMAGE, same "
             "source as ci/merge_image.sh's mirror step)")
    parser.add_argument("--output", default="catalog-waas-images.yaml")
    args = parser.parse_args()
    if not args.registry:
        sys.exit("--registry or CI_PUBLIC_REGISTRY_IMAGE is required")

    cfg = yaml.safe_load((gp.ROOT / "images.yaml").read_text())
    variants = gp.flatten_variants(gp.load_manifests(), cfg)

    out_path = Path(args.output)
    previous = load_previous(out_path)
    out = catalog(variants, args.registry, exists=registry_has, previous=previous)

    out_path.write_text(
        yaml.safe_dump(out, sort_keys=False, width=120, allow_unicode=True))
    print(f"generated {args.output} with {len(out['images'])} image(s)")


if __name__ == "__main__":
    main()
