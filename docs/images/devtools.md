# XFCE work desktop with VS Code (Microsoft APT repo, fingerprint pinned) and a dev toolchain (git, build-essential, python3, jq, tmux, ...). No autostart: VS Code sits in the XFCE menu.

Image `devtools` — layer `apps`, OS `ubuntu-noble`, version `1.0.0`.

Built by [waas-images](https://github.com/XoRHub/waas-images), deployed by the [WaaS platform](https://github.com/XoRHub/waas).

## Protocols

- **VNC** — port `5901`. Required env: `VNC_PW` (session password; refuses to start without it). Optional: `VNC_RESOLUTION` (default `1920x1080`), `VNC_COL_DEPTH` (default `24`).
