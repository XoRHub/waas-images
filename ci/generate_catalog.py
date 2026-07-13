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
