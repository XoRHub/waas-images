# Hardening checklist

Applies to **every** image built from this repo. Each item says where it
is enforced, so the list is verifiable, not aspirational.

## Enforced at build time (Dockerfile)

- [x] **Non-root user** with fixed, build-arg-configurable UID/GID
      (default `1000:1000`, user `waas_user`, home `/home/waas_user`).
      Ubuntu 24.04's default `ubuntu` user is removed.
      → `base/ubuntu/Dockerfile`, `USER` directive; verify:
      `docker run --rm <img> id` → `uid=1000`.
- [x] **No setuid/setgid binaries**: all `+s` bits stripped after every
      apt layer (base and derived images re-assert after installs), and
      **asserted by the CI smoke test** (`ci/smoke_test.sh` fails on any
      suid file; `-dev` images must show exactly `/usr/bin/sudo`).
      → verify: `docker run --rm <img> find / -xdev -perm /6000 -type f`
      → empty.
- [x] **No secrets in the image**: password arrives at runtime via env,
      hashed to a 0600 file in tmpfs, then scrubbed from the environment.
      CI runs `trivy --scanners vuln,secret` as a gate.
      → `waas-entrypoint`; verify: `docker history`, trivy job.
- [x] **Minimal packages**: `--no-install-recommends` everywhere,
      `apt-get clean`, apt lists / caches / logs removed, xterm purged
      from the XFCE layer.
- [x] **App-dedicated images carry no remote-desktop surface beyond
      VNC**: every `apps/*` image is built on the VNC-only
      `core-ubuntu-noble-xfce` parent, itself built on the VNC-only
      `core-ubuntu-noble` core (never the `-full` core, no `xrdp`, no
      `sshd`) — a single-app desktop can only ever activate VNC, not
      merely by runtime toggle but because the binaries themselves are
      absent.
      → `desktop/xfce/manifest.yaml`'s `core-ubuntu-noble-xfce` variant;
      verify:
      `docker run --rm <apps-image> sh -c 'command -v xrdp; command -v sshd'`
      — both report not found.
- [x] **Pinned supply chain**: base image pinned by Renovate digest pin;
      Mozilla APT repo verified against its published key fingerprint and
      priority-pinned; CI tool images version-pinned.

## Enforced at runtime (image design + smoke test)

- [x] **Read-only rootfs compatible**: only `/home/waas_user`, `/tmp`, `/run`
      are written. CI smoke-runs every image with `--read-only
      --cap-drop ALL --security-opt no-new-privileges` — a regression
      fails the pipeline.
      → `ci/smoke_test.sh`.
- [x] **Zero capabilities required**: all ports > 1024, no PAM, no
      chown at startup (fsGroup handles the PVC). `--cap-drop ALL` in CI.
- [x] **X display protected** by a MIT-MAGIC-COOKIE (no `Xvnc -ac`).
- [x] **VNC auth always on** (`-SecurityTypes VncAuth`, `-rfbauth`);
      empty password refuses to start. xrdp: `crypt_level=high`,
      `security_layer=negotiate` with TLS cert (provided or ephemeral).
- [x] **RDP auth on by default** (`RDP_AUTH_ENABLED=true` baked as ENV,
      no build-time opt-out): the RDP client must present the session
      password (`password=ask` bridge). Credential-less RDP requires an
      explicit `RDP_AUTH_ENABLED=false` at runtime and logs a warning —
      no image can leave the build with an open RDP.
- [x] **Audio via an unprivileged PulseAudio** (plain user mode: no
      root, no setuid, no rtkit — same privilege profile as everything
      else): a null sink plus the native protocol on TCP 4713, which
      guacd's VNC client consumes (`enable-audio`/`audio-servername`).
      Module loading is frozen after startup
      (`--disallow-module-loading`), so neither an in-session client nor
      a network peer can extend the daemon. TCP auth is anonymous BY
      DESIGN: the guacd-only NetworkPolicy is the boundary for 4713
      exactly as it is for the cleartext VNC/RDP ports (see § Threat
      model). `WAAS_AUDIO_ENABLED=0` disables the daemon entirely.
      → `waas-entrypoint`, `etc/waas/pulse/default.pa.tpl`; verify: CI
      smoke test runs `pactl info` against tcp:4713.
- [x] **SSH, when built in, is publickey-only and off by default**
      (`INSTALL_SSH=1` bakes an unprivileged `sshd`; `WAAS_SSH_ENABLED`
      still defaults to `0` even then — there is no auto-generated
      fallback credential the way `VNC_PW` has one, so a desktop image
      must never assume an operator meant to expose it). Password
      authentication is impossible by construction: the unprivileged
      `sshd` cannot read `/etc/shadow`. The entrypoint refuses to start
      with `WAAS_SSH_ENABLED=1` and no authorized key, and refuses to
      even try if `sshd` isn't in the image at all (same guard pattern
      as RDP's `xrdp` check).
      → `base/ubuntu/Dockerfile`, `base/fedora/Dockerfile`,
      `rootfs/etc/waas/entrypoint.d/50-sshd.sh`; verify:
      `docker run --rm <img> command -v sshd` reports not found unless
      the image was built with `INSTALL_SSH=1`.

## To apply on the platform side (documented contract)

- [ ] Pod `securityContext` (recommended for the operator's pod spec):
      `runAsNonRoot`, `runAsUser/fsGroup: 1000`,
      `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`,
      `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true` +
      emptyDir on `/tmp` and `/run`. Meets PodSecurity **restricted**.
      AppArmor: `runtime/default` is sufficient; no custom profile needed.
- [ ] `examples/networkpolicy-workspaces.yaml`: only guacd reaches
      5901/3389/4713; no east-west between workspaces. Mandatory if
      audio stays enabled: 4713 accepts anonymous clients by design.
- [ ] Template credentials from Vault/ESO (see README § Secrets).

Machine mirror: `ci/generate_catalog.py`'s `RECOMMENDATION_STANDARD`
derives the published catalog's `recommended` block from this section —
not a guarantee against drift, but keep both in sync when editing
either.

## Reduced profile: `-dev` images

Some workspaces are development environments whose users legitimately
need `sudo apt install` in-session. That can never be a runtime flag —
sudo is a setuid binary (stripped from standard images), `apt` writes
outside `/home/waas_user|/tmp|/run`, and `no-new-privileges` kills setuid
transitions — so it is a **build-time variant with a distinct tag**
(`<name>-dev`, e.g. `devtools-dev`), a documented reduced
profile, not a regression of this checklist.

Items **lifted** on `-dev` images, and only these:

- Setuid: exactly `/usr/bin/sudo` (NOPASSWD for UID 1000). The smoke
  test asserts the set is exactly that — anything else fails CI.
- Read-only rootfs: the matching WorkspaceTemplate must set
  `readOnlyRootFilesystem: false` (in-session installs land in the
  container layer and are **lost on pod restart**; only `/home/waas_user`
  survives).
- `allowPrivilegeEscalation: true` (without it sudo stays dead).
- `capabilities.drop: [ALL]` → keep the **runtime default** capability
  set instead: a setuid binary regains capabilities only within the
  bounding set, so an ALL-dropped pod keeps sudo dead even with
  privilege escalation allowed (verified live: `sudo: unable to change
  to root gid`). Do not add capabilities beyond the runtime defaults.

Items that **hold**, smoke/scan-enforced like everywhere else: non-root
UID 1000, no capabilities added beyond runtime defaults, no secrets
baked, minimal packages (sudo aside), VncAuth always on, trivy gate,
cosign signature. The dev smoke exercises `sudo -n true` for real under
exactly this profile.

Guard rails: the pipeline generator refuses `INSTALL_SUDO=1` on a
variant whose name lacks the `-dev` suffix or whose `profile:` is not
`dev`; the image bakes `WAAS_PROFILE=dev` and the entrypoint logs a
loud boot warning (`RDP_AUTH_ENABLED=false` precedent); the catalog
entry must keep its `allowedGroups` gate (platform-side, documented
contract — same list as the standard `devtools`).

Machine mirror: `ci/generate_catalog.py`'s `RECOMMENDATION_DEV` derives
the published catalog's `recommended` block (`profile: normal`) from
the three exceptions above — not a guarantee against drift, but keep
both in sync when editing either.

## Runtime init hook (`/etc/waas/init.d/`)

`waas-entrypoint` sources `/etc/waas/init.d/*.sh` after the image's own
build-time `entrypoint.d/` hooks (separate directory on purpose: a
volume mounted over `entrypoint.d/` would shadow the image's hooks).
Mount a ConfigMap there to run per-workspace initialisation at boot
without rebuilding the image. No privilege change: scripts run as UID
1000 like everything else — only a `-dev` image gives them a sudo path
— and anything they install outside the home PVC is lost on pod
restart. Wiring the ConfigMap mount into the WorkspaceTemplate is a
platform-repo concern.

## Threat model for desktop traffic

The browser session is TLS-terminated at the ingress; wwt→guacd→workspace
runs on the pod network. VNC/RDP between guacd and the workspace is
**cleartext by default**, accepted because: (1) both endpoints live in
the same cluster namespace, (2) the NetworkPolicy above restricts the
path to guacd exactly, (3) guacd's VNC client support for X509/VeNCrypt
is unreliable, so forcing TLS there would break the primary protocol.
If the pod network itself is in scope (multi-tenant nodes, no CNI
encryption), enable WireGuard/IPsec at the CNI layer (Cilium/Calico)
rather than per-protocol TLS — it also covers guacd→wwt. For RDP, TLS
*is* enabled when guacd negotiates it (`security_layer=negotiate`); mount
a real cert via `WAAS_TLS_CERT`/`WAAS_TLS_KEY` to replace the ephemeral
self-signed one.

## Known, accepted gaps (documented, not hidden)

- `/etc/machine-id` is identical across containers of one image (baked
  for read-only dbus); not used as identity by anything shipped.
- RDP clipboard: **works, text-only, without chansrv** — xrdp's libvnc
  backend embeds its own cliprdr handler (`vnc/vnc_clip.c`) bridging
  the RDP clipboard to the RFB cut-text that Xvnc/vncconfig already
  serve. Verified live against guacd 1.5.5, both directions, on this
  image (2026-07); the wwt policy filter applies unchanged. Non-text
  formats (files, images) are not bridged.
- RDP audio: still not shipped — and the blocker is NOT sesman/PAM.
  Investigated on xrdp 0.9.24 / Ubuntu 24.04: chansrv runs fine
  without sesman (`chansrvport=DISPLAY(n)` in the xrdp.ini session
  section), as UID 1000, without PAM, and the xrdp package ships zero
  setuid/setgid binaries — none of that would regress this checklist.
  What is missing is the sound-server side: chansrv's audio needs an
  xrdp sink module inside the audio server, and Ubuntu 24.04 only
  packages `pipewire-module-xrdp` (PipeWire) — this image runs
  PulseAudio (see "Enforced at runtime"). Shipping RDP audio therefore
  means either migrating the image's audio stack to PipeWire
  (pipewire-pulse could keep serving guacd's VNC stream) or compiling
  `pulseaudio-module-xrdp` from source (supply-chain + maintenance
  cost). Deliberately deferred; revisit if the audio stack moves to
  PipeWire. VNC remains the recommended Linux protocol.
- Firefox's *internal* process sandbox degrades in the container
  (`CanCreateUserNamespace: EPERM`): unprivileged user namespaces are
  blocked by the seccomp/caps profile. Deliberate: the pod (non-root,
  no caps, read-only, seccomp, NetworkPolicy) is the sandbox boundary
  here; granting CAP_SYS_ADMIN to restore Firefox's inner sandbox would
  weaken the outer one.
