# Terminal-first development environment: git/tmux/build tooling plus a hardened non-root OpenSSH server (publickey only, port 2222) for guacd's native ssh protocol. VNC stays available for graphical needs.

Image `dev-ssh` — layer `apps`, OS `ubuntu-24.04`, version `1.0.2`.

Built by [waas-images](https://github.com/XoRHub/waas-images), deployed by the [WaaS platform](https://github.com/XoRHub/waas).

## Protocols

- **VNC** — port `5901`. Required env: `VNC_PW` (session password; refuses to start without it). Optional: `VNC_RESOLUTION` (default `1920x1080`), `VNC_COL_DEPTH` (default `24`).
- **SSH** — port `2222`. Set `WAAS_SSH_ENABLED=1` (check this image's own default — some default it off, some default it on) and provide `WAAS_SSH_AUTHORIZED_KEYS` (or `WAAS_SSH_AUTHORIZED_KEYS_FILE`) from a Secret — publickey authentication only, no password fallback.
