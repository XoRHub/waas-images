# Headless apt-based graphical session (TigerVNC Xvnc + openbox fallback), VNC and optional xrdp bridge, PulseAudio for guacd's VNC audio stream, non-root, read-only-rootfs friendly.

Image `ubuntu-base-vnc` — layer `base`, OS `ubuntu-24.04`, version `1.4.0`.

Built by [waas-images](https://github.com/XoRHub/waas-images), deployed by the [WaaS platform](https://github.com/XoRHub/waas).

## Protocols

- **VNC** — port `5901`. Required env: `VNC_PW` (session password; refuses to start without it). Optional: `VNC_RESOLUTION` (default `1920x1080`), `VNC_COL_DEPTH` (default `24`).
