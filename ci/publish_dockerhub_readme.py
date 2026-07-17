#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyyaml==6.0.2",
# ]
# ///
"""Push per-image overviews to Docker Hub (the public mirror).

GHCR pages show the linked GitHub repo's README automatically (via
org.opencontainers.image.source), but Docker Hub shows nothing unless
the repository's `full_description` is set through its HTTP API — the
registry (push/pull) protocol has no way to carry it. This script fills
that gap: for every published image (core-* skipped, same rule as the
catalog), render the exact same per-image section generate_image_readme
puts in the CI job summary and PATCH it to
https://hub.docker.com/v2/repositories/<namespace>/<image>/, plus the
short `description` (Hub caps it at 100 chars) from the manifest.

Reuses generate_image_readme.render() so the Hub overview, the job
summary and the build matrix can never drift apart. Best-effort by
design, like the mirror itself: a repo that doesn't exist yet on Hub
(image never mirrored) or a transient API error warns and moves on —
the exit code only goes non-zero if every single push failed (login
failure included), so one flaky repo can't fail the catalog job.

Env (same names the merge jobs already use):
  CI_PUBLIC_REGISTRY_USER      Docker Hub username (JWT login)
  CI_PUBLIC_REGISTRY_PASSWORD  Docker Hub password or PAT
  CI_PUBLIC_REGISTRY_IMAGE     docker.io/<namespace> — namespace source
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_image_readme as gir  # noqa: E402
import generate_pipeline as gp  # noqa: E402

HUB_API = "https://hub.docker.com/v2"
# Hub rejects `description` over 100 chars (400) instead of truncating.
SHORT_DESCRIPTION_MAX = 100


def api(path: str, payload: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(
        f"{HUB_API}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST" if token is None else "PATCH",
    )
    if token:
        req.add_header("Authorization", f"JWT {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def short_description(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= SHORT_DESCRIPTION_MAX:
        return text
    return text[: SHORT_DESCRIPTION_MAX - 1] + "…"


def main() -> None:
    user = os.environ["CI_PUBLIC_REGISTRY_USER"]
    password = os.environ["CI_PUBLIC_REGISTRY_PASSWORD"]
    namespace = os.environ["CI_PUBLIC_REGISTRY_IMAGE"].rsplit("/", 1)[-1]

    cfg = yaml.safe_load((gp.ROOT / "images.yaml").read_text())
    variants = gp.flatten_variants(gp.load_manifests(), cfg)
    published = gir.published_variants(variants)

    try:
        token = api("/users/login", {"username": user, "password": password})["token"]
    except (urllib.error.URLError, KeyError) as exc:
        print(f"ERROR: Docker Hub login failed: {exc}", file=sys.stderr)
        sys.exit(1)

    pushed = 0
    for name, v in sorted(published.items()):
        payload = {
            "full_description": gir.render(v),
            "description": short_description(v["description"] or name),
        }
        try:
            api(f"/repositories/{namespace}/{name}/", payload, token=token)
        except urllib.error.HTTPError as exc:
            # 404: never mirrored to Hub yet — expected for brand-new
            # images until their first merge job runs. Anything else is
            # still only worth a warning (see docstring).
            print(f"WARNING: {namespace}/{name}: HTTP {exc.code} — skipped", file=sys.stderr)
        except urllib.error.URLError as exc:
            print(f"WARNING: {namespace}/{name}: {exc} — skipped", file=sys.stderr)
        else:
            pushed += 1
            print(f"pushed overview for {namespace}/{name}")

    print(f"pushed {pushed}/{len(published)} Docker Hub overview(s)")
    if published and pushed == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
