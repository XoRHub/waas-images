# XFCE desktop with Google Chrome (dl.google.com APT repo, fingerprint pinned), auto-started via XDG autostart; the pod is the sandbox boundary (inner Chrome sandbox disabled, Firefox-gap precedent).

Image `ubuntu-chrome` — layer `apps`, OS `ubuntu-24.04`, version `1.0.1`.

Built by [waas-images](https://github.com/XoRHub/waas-images), deployed by the [WaaS platform](https://github.com/XoRHub/waas).

## Protocols

- **VNC** — port `5901`. Required env: `VNC_PW` (session password; refuses to start without it). Optional: `VNC_RESOLUTION` (default `1920x1080`), `VNC_COL_DEPTH` (default `24`).
