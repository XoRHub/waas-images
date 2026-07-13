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

kasm/catalog-mapping.yaml stays hand-curated (which image, app name,
icon); this script only resolves the newest published X.Y.Z release tag
per image from the public Docker Hub API (no auth needed). Best effort
by design: any Hub failure — network, rate-limit, no release tag found —
falls back to the mapping's knownVersion instead of failing, because
this catalog must never block anything in this repo. Publication only:
it never writes back to the mapping.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
API_VERSION = "waas.xorhub.io/catalog/v1"
# Plain X.Y.Z releases only: kasmweb also pushes develop*/-rolling/
# arch-prefixed tags, and Hub's last-updated ordering surfaces those
# first — "most recently pushed" is NOT "newest release".
RELEASE_TAG = re.compile(r"^\d+\.\d+\.\d+$")
PAGE_URL = ("https://hub.docker.com/v2/repositories/kasmweb/{name}/tags"
            "?page_size=100&page={page}")
MAX_PAGES = 5  # ~500 tags, comfortable headroom over kasm's tag volume
TIMEOUT = 15


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


def catalog(mapping: dict) -> dict:
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
        entry = {
            "image": f"docker.io/kasmweb/{name}:{version}",
            "os": "linux",
            "app": img["app"],
            "version": version,
        }
        if img.get("icon"):
            entry["icon"] = img["icon"]
        if img.get("displayName"):
            entry["displayName"] = img["displayName"]
        images.append(entry)
    return {"apiVersion": API_VERSION, "images": images}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", default=str(ROOT / "kasm/catalog-mapping.yaml"))
    parser.add_argument("--output", default="catalog-kasmweb.yaml")
    args = parser.parse_args()

    mapping = yaml.safe_load(Path(args.mapping).read_text())
    out = catalog(mapping)
    Path(args.output).write_text(
        yaml.safe_dump(out, sort_keys=False, width=120, allow_unicode=True))
    print(f"generated {args.output} with {len(out['images'])} image(s)")


if __name__ == "__main__":
    main()
