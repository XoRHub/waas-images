#!/usr/bin/env python3
"""Emit catalog-waas-images.yaml — the WaaS picker catalog of the images
THIS repo builds (format contract: README § Image catalogs and
docs/studies/prompt-feature13-catalog-publishing.md).

Reuses generate_pipeline.py's discovery (load_manifests +
flatten_variants) so the catalog can never drift from the build matrix.
Runs AFTER build+push on the default branch — the immutable <version>
tags it references must already exist — unlike generate_pipeline.py
which runs before. `image:version` needs no digest: <version> tags are
immutable by CI construction (README § Build matrix & tagging).
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_pipeline as gp  # noqa: E402

API_VERSION = "waas.xorhub.io/catalog/v1"


def catalog(variants: dict[str, dict], registry: str) -> dict:
    images = []
    for name, v in sorted(variants.items()):
        entry = {
            # <registry>/<variant>:<version> — the exact ref the merge
            # job pushed (ci/merge_image.sh: ${CI_REGISTRY_IMAGE}/${IMG_NAME}).
            "image": f"{registry}/{name}:{v['version']}",
            # Workspace OS family, NOT the build distro (v["os"] is
            # ubuntu-24.04/debian-13/fedora-43 — a different notion).
            "os": "linux",
            "app": name,
            "version": v["version"],
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
        "--registry", default=os.environ.get("CI_REGISTRY_IMAGE"),
        help="registry prefix the images were pushed under "
             "(default: $CI_REGISTRY_IMAGE, same source as ci/build_image.sh)")
    parser.add_argument("--output", default="catalog-waas-images.yaml")
    args = parser.parse_args()
    if not args.registry:
        sys.exit("--registry or CI_REGISTRY_IMAGE is required")

    cfg = yaml.safe_load((gp.ROOT / "images.yaml").read_text())
    variants = gp.flatten_variants(gp.load_manifests(), cfg)
    out = catalog(variants, args.registry)
    Path(args.output).write_text(
        yaml.safe_dump(out, sort_keys=False, width=120, allow_unicode=True))
    print(f"generated {args.output} with {len(out['images'])} image(s)")


if __name__ == "__main__":
    main()
