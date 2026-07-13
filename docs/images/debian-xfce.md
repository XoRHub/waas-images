# XFCE desktop, VNC + RDP, derived from the apt base-rdp image.

Image `debian-xfce` — layer `desktop`, OS `debian-13`, version `1.2.0`.

Built by [waas-images](https://github.com/XoRHub/waas-images), deployed by the [WaaS platform](https://github.com/XoRHub/waas).

## Protocols

- **VNC** — port `5901`. Required env: `VNC_PW` (session password; refuses to start without it). Optional: `VNC_RESOLUTION` (default `1920x1080`), `VNC_COL_DEPTH` (default `24`).
- **RDP** — port `3389`. Set `WAAS_RDP_ENABLED=1` to enable. `RDP_AUTH_ENABLED` (default `true`) requires the session password on connect; the runtime-only opt-out logs a loud warning (see README).
- **SSH** — port `2222`. Set `WAAS_SSH_ENABLED=1` (check this image's own default — some default it off, some default it on) and provide `WAAS_SSH_AUTHORIZED_KEYS` (or `WAAS_SSH_AUTHORIZED_KEYS_FILE`) from a Secret — publickey authentication only, no password fallback.
