#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyyaml==6.0.2",
# ]
# ///
"""Emit catalog-kasmweb.yaml — the WaaS picker catalog of the upstream
docker.io/kasmweb/* images (same format contract as
catalog-waas-images.yaml, README § Image catalogs).

kasm/catalog-mapping.yaml stays hand-curated for which image/app
name/icon/displayName/description to publish (description optional and
never regenerated away — see catalog()); this script resolves the
newest published X.Y.Z
release tag per image from the public Docker Hub API (no auth needed),
and derives BOTH `architectures` (Hub's per-tag manifest-list
architecture data — no longer hand-curated: that data drifted stale,
see hub_architectures()) and `profile`/`recommended` (via
probe_hardening(), only when --probe-hardening is passed — it actually
pulls+runs the resolved image under this repo's hardened Docker flags,
the same technique ci/smoke_test.sh uses on this repo's own images,
since kasmweb images carry no local manifest/HARDENING.md doctrine to
derive a profile from statically). Best effort by design throughout:
any Hub/Docker failure falls back to omitting the field (or, for
version resolution, the mapping's knownVersion) rather than failing,
because this catalog must never block anything in this repo.

Two CLI modes, both usable from CI or by hand (same script, same
--probe-hardening flag either way):

  - No positional arg (the CI/scheduled path, `catalog-kasmweb.yml`):
    regenerate the WHOLE catalog from every image in the mapping.
  - `generate_kasm_catalog.py <name>` (e.g. `vs-code` — never a full
    ref: the registry, docker.io/kasmweb/, is always the same):
    resolve/probe just THAT one image and upsert it into the existing
    catalog-kasmweb.yaml in place, leaving every other entry untouched.
    If `<name>` isn't in kasm/catalog-mapping.yaml yet, a minimal entry
    (name/app/knownVersion) is appended to it as plain text — never a
    yaml.safe_load/dump round-trip of the whole file, which would
    silently strip its hand-written header comments — so the image is
    tracked by future full regens too; icon/displayName are left for a
    human to fill in by hand afterward.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_catalog as gc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API_VERSION = "waas.xorhub.io/catalog/v1"
# Plain X.Y.Z releases only: kasmweb also pushes develop*/-rolling/
# arch-prefixed tags, and Hub's last-updated ordering surfaces those
# first — "most recently pushed" is NOT "newest release".
RELEASE_TAG = re.compile(r"^\d+\.\d+\.\d+$")
PAGE_URL = ("https://hub.docker.com/v2/repositories/kasmweb/{name}/tags"
            "?page_size=100&page={page}")
TAG_URL = "https://hub.docker.com/v2/repositories/kasmweb/{name}/tags/{version}"
MAX_PAGES = 5  # ~500 tags, comfortable headroom over kasm's tag volume
TIMEOUT = 15
PROBE_TIMEOUT = 180  # ci/probe_kasm_hardening.sh pulls full desktop images

# recommended.podSecurityContext-only block for a kasmweb image whose
# UID-1000 baseline was confirmed live but whose readOnlyRootFilesystem/
# cap-drop ALL tolerance was NOT (profile: "normal"). Deliberately not
# generate_catalog.RECOMMENDATION_DEV: that constant's shape encodes
# THIS repo's specific sudo/bounding-set exceptions for -dev images, a
# different claim than "hardening simply wasn't verified" here.
KASM_RECOMMENDATION_NORMAL = {
    "podSecurityContext": {
        "runAsNonRoot": True,
        "runAsUser": 1000,
        "fsGroup": 1000,
        "seccompProfile": {"type": "RuntimeDefault"},
    },
}


def latest_release_tag(name: str) -> str | None:
    releases: list[tuple[int, ...]] = []
    for page in range(1, MAX_PAGES + 1):
        url = PAGE_URL.format(name=name, page=page)
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            data = json.load(resp)
        releases += [
            tuple(int(x) for x in t["name"].split("."))
            for t in data.get("results", [])
            if RELEASE_TAG.match(t["name"])
        ]
        if not data.get("next"):
            break
    if not releases:
        return None
    return ".".join(str(x) for x in max(releases))


ARCH_ENUM = ("amd64", "arm64")  # ci/schema/v1.schema.json Entry.architectures enum


def hub_architectures(name: str, version: str) -> list[str] | None:
    """Docker Hub's single-tag endpoint images[].architecture list for
    name:version — replaces the old hand-curated kasm/catalog-mapping.yaml
    `architectures:` field, which was found to have drifted stale
    (kasmweb's plain X.Y.Z tags are NOT amd64-only, contrary to that
    field's own comment — verified live: 1.19.0 is a multi-arch
    amd64+arm64 manifest list for both terminal and firefox). None on
    any failure (network, 404, malformed JSON) or when nothing in the
    schema's amd64/arm64 enum is present — same best-effort contract as
    latest_release_tag()."""
    url = TAG_URL.format(name=name, version=version)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    archs = sorted({
        img["architecture"] for img in data.get("images", [])
        if img.get("architecture") in ARCH_ENUM
    })
    return archs or None


def probe_hardening(ref: str) -> str | None:
    """Best-effort: shell out to ci/probe_kasm_hardening.sh, which
    actually pulls+runs `ref` under increasingly strict Docker flags to
    empirically determine whether it tolerates readOnlyRootFilesystem/
    cap-drop ALL — kasmweb images carry no local manifest/HARDENING.md
    doctrine to derive a profile from statically, unlike this repo's own
    images (generate_catalog.py's RECOMMENDATION_STANDARD/
    RECOMMENDATION_DEV). Returns "hardened"/"normal"/None (probe
    inconclusive, timed out, or errored — never raises, matches this
    generator's must-never-block contract)."""
    try:
        result = subprocess.run(
            ["sh", str(ROOT / "ci/probe_kasm_hardening.sh"), ref],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — best effort, never fatal
        print(f"{ref}: hardening probe failed: {exc}", file=sys.stderr)
        return None
    outcome = result.stdout.strip()
    return outcome if outcome in ("hardened", "normal") else None


def recommended_for(profile: str) -> dict:
    """entry["recommended"] for one probed kasmweb image: the fixed
    hardened/normal block for whichever verdict probe_hardening()
    returned — the kasmweb equivalent of generate_catalog.py's
    recommended_for(), minus the env hints (this catalog has no
    smoke:-equivalent protocol signal to derive them from)."""
    if profile == "hardened":
        return copy.deepcopy(gc.RECOMMENDATION_STANDARD)
    return copy.deepcopy(KASM_RECOMMENDATION_NORMAL)


def catalog(
    mapping: dict,
    *,
    probe: Callable[[str], str | None] = lambda ref: None,
    previous: dict[str, dict] | None = None,
) -> dict:
    previous = previous or {}
    images = []
    for img in mapping["images"]:
        name = img["name"]
        try:
            version = latest_release_tag(name)
            if version is None:
                print(f"kasmweb/{name}: no X.Y.Z release tag on Docker Hub",
                      file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 — best effort, never fatal
            print(f"kasmweb/{name}: Docker Hub lookup failed: {exc}",
                  file=sys.stderr)
            version = None
        if version is None:
            version = str(img["knownVersion"])
            print(f"kasmweb/{name}: falling back to knownVersion {version}",
                  file=sys.stderr)
        ref = f"docker.io/kasmweb/{name}:{version}"
        entry = {
            "image": ref,
            "os": "linux",
            "app": img["app"],
            "version": version,
        }
        if img.get("icon"):
            entry["icon"] = img["icon"]
        if img.get("displayName"):
            entry["displayName"] = img["displayName"]
        # Hand-curated in the mapping like icon/displayName, but never
        # regenerated away: when the mapping omits it, a description the
        # previous catalog already carried is preserved rather than
        # dropped — a value that once existed is never silently erased.
        # Absent from both -> field omitted entirely.
        fallback = previous.get(img["app"])
        description = img.get("description") or (fallback or {}).get("description")
        if description:
            entry["description"] = description
        # Derived from Docker Hub's per-tag manifest-list data for the
        # resolved version, never hand-curated (see hub_architectures()
        # docstring for why the old hand-curated field was removed).
        # Best effort: any Hub failure here just omits the key, same
        # "unknown -> waas falls back to spec.architectures" contract as
        # catalog-waas-images.yaml.
        try:
            archs = hub_architectures(name, version)
        except Exception as exc:  # noqa: BLE001 — best effort, never fatal
            print(f"kasmweb/{name}: architecture lookup failed: {exc}",
                  file=sys.stderr)
            archs = None
        if archs:
            entry["architectures"] = archs
        # profile/recommended: reuse the previously-published verdict
        # for the SAME image:version — ci/probe_kasm_hardening.sh
        # pulls+runs a full desktop image, so a version that hasn't
        # changed must not be re-probed every run. Otherwise call
        # probe(ref) (a no-op returning None unless --probe-hardening
        # was passed — see main()).
        if fallback and fallback.get("image") == ref and fallback.get("profile"):
            entry["profile"] = fallback["profile"]
            if fallback.get("recommended"):
                entry["recommended"] = copy.deepcopy(fallback["recommended"])
        else:
            outcome = probe(ref)
            if outcome:
                entry["profile"] = outcome
                entry["recommended"] = recommended_for(outcome)
        images.append(entry)
    return {"apiVersion": API_VERSION, "images": images}


def append_mapping_entry(mapping_path: Path, name: str, version: str) -> None:
    """Append a minimal new image block to the hand-curated mapping
    file as plain text, never via yaml.safe_load/safe_dump — round-
    tripping the whole file through the YAML library would silently
    strip every one of its header comments (icon-slug verification
    instructions, the architectures/profile/recommended note, etc.).
    icon/displayName are intentionally left out for a human to add by
    hand afterward; knownVersion is the version resolved live right
    now, so the entry has an offline fallback from the moment it's
    added."""
    block = (
        f"\n  - name: {name}            # docker.io/kasmweb/{name}\n"
        f"    app: {name}\n"
        f"    knownVersion: \"{version}\"\n"
    )
    with mapping_path.open("a") as f:
        f.write(block)


def resolve_mapping_entry(mapping: dict, mapping_path: Path, name: str) -> dict:
    """The single-image CLI mode's counterpart to iterating
    mapping["images"] in catalog(): find `name`'s existing mapping
    entry (unchanged), or resolve its current release live and append
    a minimal one via append_mapping_entry() if this is a genuinely new
    image. Exits with an error if `name` isn't already mapped AND has
    no resolvable X.Y.Z release on Docker Hub — unlike catalog()'s
    per-run best-effort posture, a manual single-image add with no
    usable version at all has nothing sensible to write and should
    fail loudly, not silently omit the image."""
    for img in mapping["images"]:
        if img["name"] == name:
            return img
    version = latest_release_tag(name)
    if version is None:
        sys.exit(f"kasmweb/{name}: no X.Y.Z release tag found on Docker Hub — "
                  "not a known kasmweb image name, or Hub is unreachable")
    append_mapping_entry(mapping_path, name, version)
    print(f"kasmweb/{name}: new image, appended to {mapping_path} with "
          f"knownVersion {version} (edit icon/displayName there by hand "
          "if wanted)", file=sys.stderr)
    return {"name": name, "app": name, "knownVersion": version}


def upsert_entry(out_path: Path, entry: dict) -> dict:
    """Merge `entry` into the catalog already at out_path (same app ->
    replace in place, preserving every other entry's position; new app
    -> append) instead of main()'s full-regen rebuild-from-scratch —
    the single-image CLI mode must never clobber every other
    already-published entry just to refresh or add one."""
    if out_path.exists():
        try:
            data = yaml.safe_load(out_path.read_text()) or {}
        except yaml.YAMLError:
            data = {}
    else:
        data = {}
    data.setdefault("apiVersion", API_VERSION)
    images = data.setdefault("images", [])
    for i, existing in enumerate(images):
        if existing.get("app") == entry["app"]:
            images[i] = entry
            break
    else:
        images.append(entry)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image", nargs="?",
        help="short kasmweb image name (e.g. 'vs-code') to resolve/probe "
             "and upsert in isolation instead of regenerating the whole "
             "catalog — the registry (docker.io/kasmweb/) is always the "
             "same, never pass a full ref; added to --mapping automatically "
             "if it isn't there yet")
    parser.add_argument("--mapping", default=str(ROOT / "kasm/catalog-mapping.yaml"))
    parser.add_argument("--output", default="catalog-kasmweb.yaml")
    parser.add_argument(
        "--probe-hardening", action="store_true",
        help="actually pull+run each resolved image via "
             "ci/probe_kasm_hardening.sh to derive profile/recommended — "
             "slow, requires Docker; off by default so `make catalogs` "
             "stays fast and offline-friendly")
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    mapping = yaml.safe_load(mapping_path.read_text())
    out_path = Path(args.output)
    probe = probe_hardening if args.probe_hardening else (lambda ref: None)
    previous = gc.load_previous(out_path)

    if args.image:
        img = resolve_mapping_entry(mapping, mapping_path, args.image)
        entry = catalog({"images": [img]}, probe=probe, previous=previous)["images"][0]
        out_data = upsert_entry(out_path, entry)
        out_path.write_text(
            yaml.safe_dump(out_data, sort_keys=False, width=120, allow_unicode=True))
        profile_note = f" (profile: {entry['profile']})" if entry.get("profile") else ""
        print(f"updated {args.output}: {entry['app']} -> {entry['image']}{profile_note}")
        return

    out = catalog(mapping, probe=probe, previous=previous)
    out_path.write_text(
        yaml.safe_dump(out, sort_keys=False, width=120, allow_unicode=True))
    print(f"generated {args.output} with {len(out['images'])} image(s)")


if __name__ == "__main__":
    main()
