# Ubuntu Desktop (VNC only)

Image `ubuntu-desktop` — layer `desktop`, OS `ubuntu-24.04`, version `1.2.0`.

XFCE desktop, VNC only — the parent for every apps/* image; no xrdp or sshd at all.

Built by [waas-images](https://github.com/XoRHub/waas-images), deployed by the [WaaS platform](https://github.com/XoRHub/waas).

## Protocols

- **VNC** — port `5901`. Required env: `VNC_PW` (session password; refuses to start without it). Optional: `VNC_RESOLUTION` (default `1920x1080`), `VNC_COL_DEPTH` (default `24`).
