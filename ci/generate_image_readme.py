#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyyaml==6.0.2",
# ]
# ///
"""Render per-image documentation — one section per published image,
listing exactly which protocols it supports — into the GitHub Actions
job summary ($GITHUB_STEP_SUMMARY) of the CI run that built it.

Deliberately NOT committed: with the number of images only growing,
keeping one hand-synced doc file per image (or even one generator
output per image checked into the repo) is exactly the maintenance
burden this avoids — regenerated fresh every run from the current
manifests, so it can never drift, and there is nothing to keep in sync
between renames/removals and stale committed files. The durable,
versioned usage contract (WAAS_* env vars, ports, protocols) lives in
README.md instead, which is what org.opencontainers.image.documentation
points at (see ci/generate_pipeline.py).

Protocol coverage is driven by each variant's existing
smoke.rdp/smoke.ssh flags (the same signal CI already trusts to know
what to smoke-test) rather than a second, separately-maintained
capability field. VNC is always documented: every image in this repo
runs TigerVNC's Xvnc as the display server unconditionally (see
base/ubuntu/Dockerfile), regardless of what a given variant's smoke.vnc
happens to assert for its own CI check (e.g. the base -rdp variants
smoke-test RDP-only mode with smoke.vnc: false, even though Xvnc is
still there).

Reuses generate_pipeline.py's discovery (load_manifests +
flatten_variants) so the summary can never drift from the build matrix.
Outside CI (no $GITHUB_STEP_SUMMARY set, e.g. local `make image-docs`),
prints to stdout instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_pipeline as gp  # noqa: E402

PROJECT_URL = "https://github.com/XoRHub/waas-images"
WAAS_URL = "https://github.com/XoRHub/waas"


def render(v: dict, *, heading: str = "#") -> str:
    title = v["description"] or v["name"]
    lines = [
        f"{heading} {title}",
        "",
        f"Image `{v['name']}` — layer `{v['layer']}`, OS `{v['os']}`, "
        f"version `{v['version']}`.",
        "",
    ]
    if v["description"] and v["description"] != title:
        lines += [v["description"], ""]
    lines += [
        f"Built by [waas-images]({PROJECT_URL}), deployed by the "
        f"[WaaS platform]({WAAS_URL}).",
        "",
        f"{heading}# Protocols",
        "",
        "- **VNC** — port `5901`. Required env: `VNC_PW` (session "
        "password; refuses to start without it). Optional: "
        "`VNC_RESOLUTION` (default `1920x1080`), `VNC_COL_DEPTH` "
        "(default `24`).",
    ]
    smoke = v["smoke"]
    if smoke.get("rdp"):
        lines.append(
            "- **RDP** — port `3389`. Set `WAAS_RDP_ENABLED=1` to "
            "enable. `RDP_AUTH_ENABLED` (default `true`) requires the "
            "session password on connect; the runtime-only opt-out "
            "logs a loud warning (see README)."
        )
    if smoke.get("ssh"):
        lines.append(
            "- **SSH** — port `2222`. Set `WAAS_SSH_ENABLED=1` (check "
            "this image's own default — some default it off, some "
            "default it on) and provide `WAAS_SSH_AUTHORIZED_KEYS` (or "
            "`WAAS_SSH_AUTHORIZED_KEYS_FILE`) from a Secret — "
            "publickey authentication only, no password fallback."
        )
    lines.append("")
    return "\n".join(lines)


def published_variants(variants: dict[str, dict]) -> dict[str, dict]:
    """core-*: internal build parents only, never picked by an end user
    — no doc section makes sense for them (mirrors the same skip in
    ci/generate_catalog.py)."""
    return {n: v for n, v in variants.items() if not n.startswith("core-")}


def render_summary(published: dict[str, dict]) -> str:
    lines = [
        "# waas-images — image documentation",
        "",
        "Generated fresh for this run by `ci/generate_image_readme.py` "
        "— not committed. See [README.md]"
        f"({PROJECT_URL}/blob/main/README.md) for the durable usage "
        "contract (WAAS_* env vars, ports, protocols common to every "
        "image).",
        "",
    ]
    for _name, v in sorted(published.items()):
        lines.append(render(v, heading="##"))
    return "\n".join(lines)


def main() -> None:
    cfg = yaml.safe_load((gp.ROOT / "images.yaml").read_text())
    variants = gp.flatten_variants(gp.load_manifests(), cfg)
    published = published_variants(variants)
    summary = render_summary(published)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(summary)
        print(f"appended {len(published)} image doc section(s) to GITHUB_STEP_SUMMARY")
    else:
        print(summary)


if __name__ == "__main__":
    main()
