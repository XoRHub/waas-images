#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyyaml==6.0.2",
# ]
# ///
"""Generate docs/images/<variant>.md — one generated README per
published image (README § "Per-image README"), pointing at this
project and at WaaS (the platform that deploys these images) and
documenting exactly which protocols that image supports.

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
flatten_variants) so the docs can never drift from the build matrix.
Output is committed (not gitignored): it must live at a stable GitHub
URL to be linkable from the org.opencontainers.image.documentation
label/annotation (see ci/build_image.sh, ci/merge_image.sh).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_pipeline as gp  # noqa: E402

PROJECT_URL = "https://github.com/XoRHub/waas-images"
WAAS_URL = "https://github.com/XoRHub/waas"


def render(v: dict) -> str:
    title = v.get("display_name") or v["description"] or v["name"]
    lines = [
        f"# {title}",
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
        "## Protocols",
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(gp.ROOT / "docs" / "images"))
    args = parser.parse_args()

    cfg = yaml.safe_load((gp.ROOT / "images.yaml").read_text())
    variants = gp.flatten_variants(gp.load_manifests(), cfg)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, v in sorted(variants.items()):
        (out_dir / f"{name}.md").write_text(render(v))
    print(f"generated {len(variants)} file(s) under {out_dir}/")


if __name__ == "__main__":
    main()
