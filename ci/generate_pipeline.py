#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyyaml==6.0.2",
# ]
# ///
"""Generate the CI build matrix from images.yaml + discovered manifests.

Discovery: every {base,desktop,apps}/*/manifest.yaml becomes, per
variant, one NATIVE build job per architecture plus one merge job
assembling the arch tags into the manifest list. Jobs are placed in
stages by dependency depth (a variant whose `from` names another
variant builds one stage later), and each arch chain is independent:
`ARG BASE_IMAGE` points at the parent's SAME-ARCH tag pushed earlier
in the same pipeline.

Emits github-matrices.json — per-layer-depth build/merge matrices
consumed by the committed .github/workflows/build.yml (fromJSON); the
workflow skeleton is static, only these matrices vary.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recipe_compiler  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LAYER_DIRS = ("base", "desktop", "apps")
# Stable GitHub URL prefix for the per-image READMEs ci/generate_image_
# readme.py commits under docs/images/ — the source for the
# org.opencontainers.image.documentation label/annotation.
DOCS_BASE_URL = "https://github.com/XoRHub/waas-images/blob/main/docs/images"
# GitLab runner tag per build platform. An arch without a native runner
# fleet must not appear in a manifest.
RUNNER_TAGS = {"linux/amd64": "amd", "linux/arm64": "arm"}


def load_manifests() -> list[dict]:
    manifests = []
    for layer in LAYER_DIRS:
        for mf in sorted(ROOT.glob(f"{layer}/*/manifest.yaml")):
            m = yaml.safe_load(mf.read_text())
            m["context"] = str(mf.parent.relative_to(ROOT))
            # recipe: manifests get their Dockerfile.generated materialised
            # here (and the recipe+Dockerfile ambiguity is refused); None
            # means "hand-written Dockerfile", the default.
            m["dockerfile"] = recipe_compiler.compile_recipe(m, mf.parent, ROOT)
            manifests.append(m)
    if not manifests:
        sys.exit("no manifests found — nothing to build")
    return manifests


def flatten_variants(manifests: list[dict], cfg: dict) -> dict[str, dict]:
    """One entry per publishable image, keyed by variant name."""
    defaults = cfg.get("defaults", {})
    variants: dict[str, dict] = {}
    for m in manifests:
        for v in m.get("variants", []):
            name = v["name"]
            if name in variants:
                sys.exit(f"duplicate variant name {name!r}")
            # os: resolves per variant (variant > manifest > defaults) so
            # one parameterized Dockerfile publishes ubuntu-* and
            # debian-* images from the same manifest.
            os_key = v.get("os", m.get("os", defaults.get("os")))
            if os_key not in cfg.get("os", {}):
                sys.exit(f"{name}: unknown os {os_key!r} (not in images.yaml)")
            os_args = cfg["os"][os_key].get("buildArgs", {})
            build_args = {
                **defaults.get("buildArgs", {}),
                **os_args,
                **m.get("buildArgs", {}),
                **v.get("buildArgs", {}),
            }
            # Reduced-hardening variants: INSTALL_SUDO=1 must be
            # impossible to ship under an innocuous name or profile. The
            # -dev tag suffix and the relaxed smoke are tied together
            # here, not left to authoring discipline.
            profile = v.get("profile", "standard")
            if profile not in ("standard", "dev"):
                sys.exit(f"{name}: profile must be standard|dev, got {profile!r}")
            if str(build_args.get("INSTALL_SUDO", "0")) == "1":
                if not name.endswith("-dev"):
                    sys.exit(f"{name}: INSTALL_SUDO=1 requires the -dev name suffix")
                if profile != "dev":
                    sys.exit(f"{name}: INSTALL_SUDO=1 requires profile: dev")
            if profile == "dev":
                # Baked marker consumed by waas-entrypoint's boot warning.
                build_args.setdefault("WAAS_PROFILE", "dev")
            variants[name] = {
                "name": name,
                "context": m["context"],
                "dockerfile": m["dockerfile"],
                "os": os_key,
                "layer": m.get("layer", m["context"].split("/", 1)[0]),
                "description": " ".join(str(m.get("description", "")).split()),
                "profile": profile,
                "version": str(m["version"]),
                # Catalog-only key (ci/generate_catalog.py): dashboard-icons
                # slug, never baked into the image. Root + per-variant
                # override, like smoke:/buildArgs:.
                "icon": v.get("icon", m.get("icon", "")),
                "from": v.get("from", m.get("from")),
                "archs": v.get("archs", m.get("archs", defaults.get("archs", []))),
                "build_args": build_args,
                "smoke": v.get("smoke", {}),
            }
    return variants


def stage_of(variants: dict[str, dict], name: str) -> int:
    """Dependency depth: 0 for roots, parent+1 otherwise."""
    v = variants[name]
    parent = v.get("from")
    if not parent:
        return 0
    if parent not in variants:
        sys.exit(f"{name}: unknown parent image {parent!r}")
    return stage_of(variants, parent) + 1


def validate_archs(variants: dict[str, dict]) -> None:
    """Every arch must have a runner mapping; a child cannot build an
    arch its parent does not publish (BASE_IMAGE is per-arch)."""
    for name, v in variants.items():
        for arch in v["archs"]:
            if arch not in RUNNER_TAGS:
                sys.exit(f"{name}: no runner tag mapped for arch {arch!r}")
        if v["from"]:
            missing = set(v["archs"]) - set(variants[v["from"]]["archs"])
            if missing:
                sys.exit(f"{name}: parent {v['from']!r} does not build {sorted(missing)}")


def build_vars(v: dict, variants: dict[str, dict]) -> dict:
    """The IMG_*/SMOKE_* contract consumed by ci/build_image.sh — one
    source of truth for both emitters."""
    out = {
        "IMG_NAME": v["name"],
        "IMG_CONTEXT": v["context"],
        "IMG_VERSION": v["version"],
        # OCI label sources (build_image.sh --label / merge_image.sh
        # index annotations): classification metadata for the future
        # catalog tooling.
        "IMG_OS": v["os"],
        "IMG_LAYER": v["layer"],
        "IMG_DESCRIPTION": v["description"],
        "IMG_PROFILE": v["profile"],
        "IMG_BUILD_ARGS": " ".join(
            f"{k}={val}" for k, val in sorted(v["build_args"].items())
        ),
        # Parent ref minus the -g<sha>-<arch> suffix, which only the
        # build job knows (build_image.sh appends it).
        "IMG_FROM_REF": (
            f"{v['from']}:{variants[v['from']]['version']}" if v["from"] else ""
        ),
        # org.opencontainers.image.documentation source: the generated
        # per-image README (ci/generate_image_readme.py), always at this
        # stable path once committed — never guessed, always this repo.
        "IMG_DOCUMENTATION": f"{DOCS_BASE_URL}/{v['name']}.md",
        "SMOKE_PROFILE": v["profile"],
        "SMOKE_VNC": "1" if v["smoke"].get("vnc") else "0",
        "SMOKE_RDP": "1" if v["smoke"].get("rdp") else "0",
        "SMOKE_SSH": "1" if v["smoke"].get("ssh") else "0",
        "SMOKE_AUDIO": "1" if v["smoke"].get("audio") else "0",
        "SMOKE_ENV": " ".join(
            f"{k}={val}" for k, val in sorted(v["smoke"].get("env", {}).items())
        ),
    }
    if v["dockerfile"]:
        out["IMG_DOCKERFILE"] = v["dockerfile"]
    return out


def merge_vars(v: dict, variants: dict[str, dict]) -> dict:
    """The IMG_* contract consumed by ci/merge_image.sh (same OCI
    metadata as the build jobs: the manifest-list index does not inherit
    per-arch config labels, so the merge re-asserts them)."""
    return {
        "IMG_NAME": v["name"],
        "IMG_VERSION": v["version"],
        "IMG_ARCHS": ",".join(v["archs"]),
        "IMG_OS": v["os"],
        "IMG_LAYER": v["layer"],
        "IMG_DESCRIPTION": v["description"],
        "IMG_PROFILE": v["profile"],
        "IMG_FROM_REF": (
            f"{v['from']}:{variants[v['from']]['version']}" if v["from"] else ""
        ),
        "IMG_DOCUMENTATION": f"{DOCS_BASE_URL}/{v['name']}.md",
    }


# GitHub-hosted runner labels per build platform. ubuntu-24.04-arm =
# GitHub's hosted arm64 fleet (free for public repos; check billing
# before enabling on a private one — WAAS_IMAGES_BUILD_STRATEGY=qemu
# routes everything to the amd64 fleet as the fallback, same variable
# as GitLab).
GH_RUNNERS = {"linux/amd64": "ubuntu-24.04", "linux/arm64": "ubuntu-24.04-arm"}
# The committed workflow has exactly layer-0/1/2 + merge-0/1/2 jobs.
GH_MAX_DEPTH = 2


def emit_github(variants: dict[str, dict], strategy: str) -> str:
    """Per-layer-depth build/merge matrices consumed by the committed
    .github/workflows/build.yml via fromJSON. The workflow skeleton is
    static; only these matrices vary."""
    depths = {name: stage_of(variants, name) for name in variants}
    deepest = max(depths.values())
    if deepest > GH_MAX_DEPTH:
        sys.exit(
            f"layer depth {deepest} exceeds the {GH_MAX_DEPTH} wired into "
            ".github/workflows/build.yml — add a layer-N/merge-N job pair "
            "there (a ~10-line diff) and bump GH_MAX_DEPTH"
        )

    matrices: dict[str, list] = {}
    for d in range(GH_MAX_DEPTH + 1):
        matrices[f"layer{d}"] = []
        matrices[f"merge{d}"] = []
    for name, v in sorted(variants.items(), key=lambda kv: (depths[kv[0]], kv[0])):
        d = depths[name]
        common = build_vars(v, variants)
        for arch in v["archs"]:
            runner = GH_RUNNERS["linux/amd64"] if strategy == "qemu" \
                else GH_RUNNERS[arch]
            matrices[f"layer{d}"].append(
                {**common, "IMG_ARCH": arch, "runner": runner})
        matrices[f"merge{d}"].append(merge_vars(v, variants))
    return json.dumps(matrices)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    # Operational fallback: set the CI variable WAAS_IMAGES_BUILD_STRATEGY
    # to "qemu" (e.g. arm fleet down) to route every build job to the amd
    # fleet under emulation. Same jobs, same gates, just slower.
    strategy = os.environ.get("WAAS_IMAGES_BUILD_STRATEGY", "native")
    if strategy not in ("native", "qemu"):
        sys.exit(f"WAAS_IMAGES_BUILD_STRATEGY must be native|qemu, got {strategy!r}")
    cfg = yaml.safe_load((ROOT / "images.yaml").read_text())
    variants = flatten_variants(load_manifests(), cfg)
    validate_archs(variants)
    out = ROOT / "github-matrices.json"
    out.write_text(emit_github(variants, strategy))
    print(f"generated {out.name} with {len(variants)} image(s), strategy={strategy}")


if __name__ == "__main__":
    main()
