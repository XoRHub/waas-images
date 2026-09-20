# Hardening checklist

Applies to **every** image built from this repo. Each item says where it
is enforced, so the list is verifiable, not aspirational.

## Enforced at build time (Dockerfile)

- [x] **Non-root user** with fixed, build-arg-configurable UID/GID
      (default `1000:1000`, user `waas_user`, home `/home/waas_user`).
      Ubuntu 24.04's default `ubuntu` user is removed.
      → `base/ubuntu/Dockerfile`, `USER` directive; verify:
      `docker run --rm --entrypoint id <img>` → `uid=1000`.
      (Every `verify:` below uses `--entrypoint`: the images carry no
      `CMD`, and `waas-entrypoint` ignores its arguments and refuses to
      boot without a password, so a trailing command never runs.)
- [x] **No setuid/setgid binaries**: all `+s` bits stripped after every
      apt layer (base and derived images re-assert after installs), and
      **asserted by the CI smoke test** (`ci/smoke_test.sh` fails on any
      suid file; `-dev` images must show exactly `/usr/bin/sudo`).
      → verify:
      `docker run --rm --entrypoint find <img> / -xdev -perm /6000 -type f`
      → empty (a couple of `Permission denied` on stderr for root-only
      directories is the non-root user at work, not a finding).
- [x] **No secrets in the image**: password arrives at runtime via env,
      hashed to a 0600 file in tmpfs, then scrubbed from the environment.
      CI runs `trivy --scanners vuln,secret` as a gate.
      → `waas-entrypoint`; verify: `docker history`, trivy job.
- [x] **Minimal packages**: `--no-install-recommends` everywhere,
      `apt-get clean`, apt lists / caches / logs removed, xterm purged
      from the XFCE layer.
- [x] **No remote-desktop or shell surface beyond VNC, on every image
      from 3.0.0**: no Dockerfile in this repo installs `xrdp` or
      `sshd`, no build arg can add them, and the entrypoint has no code
      path that would start them — the platform reaches a Linux
      workspace over VNC and nothing else (waas#117: `rdp` is for
      Windows VMs, `ssh` was dropped), so a second session listener
      would be attack surface with no consumer. Structurally absent,
      not disabled: there is no runtime toggle to get it wrong
      (`WAAS_VNC_ENABLED=0`, which used to mean "RDP only", is refused
      at boot rather than silently ignored). Ports 3389/2222 are not
      even `EXPOSE`d. The listeners that remain are not sessions:
      PulseAudio on 4713 (its own item below) and, on `hermes-agent`
      only, the loopback-bound dashboard. Tags below 3.0.0 — including
      the `2.x` refs `catalog-waas-images.yaml` still carries until the
      3.0.0 build is published — were built from the old `-full`
      parents and DO ship both binaries, xrdp on by default.
      → `base/ubuntu/Dockerfile`, `base/fedora/Dockerfile`; verify:
      `docker run --rm --entrypoint sh <img> -c 'command -v xrdp; command -v sshd'`
      — both report not found on any 3.0.0+ tag (the same command
      against `ubuntu-desktop-noble:2.1.1` prints both paths, which is
      how you know it discriminates).
- [x] **App-dedicated images carry no desktop either**: the kiosk
      session (`WAAS_APP`) removes the desktop behind the app — no
      panel, no terminal, no WM keybindings.
      → `waas-session` + `/etc/waas/openbox-app.rc.xml` (base rootfs).
- [x] **Pinned supply chain**: base image pinned by Renovate digest pin;
      Mozilla APT repo verified against its published key fingerprint and
      priority-pinned; CI tool images version-pinned.

## Enforced at runtime (image design + smoke test)

- [x] **Read-only rootfs compatible**: only `/home/waas_user` and `/tmp`
      are written (`/run` left the contract with xrdp, its only
      writer). CI smoke-runs every image with `--read-only --cap-drop
      ALL --security-opt no-new-privileges` and a tmpfs on exactly
      those two paths — a regression fails the pipeline.
      → `ci/smoke_test.sh`.
- [x] **Zero capabilities required**: all ports > 1024, no PAM, no
      chown at startup (fsGroup handles the PVC). `--cap-drop ALL` in CI.
- [x] **X display protected** by a MIT-MAGIC-COOKIE (no `Xvnc -ac`).
- [x] **VNC auth always on** (`-SecurityTypes VncAuth`, `-rfbauth`);
      empty password refuses to start. There is no credential-less mode
      to opt into: the only session listener is Xvnc, and it always
      asks.
- [x] **Audio via an unprivileged PulseAudio** (plain user mode: no
      root, no setuid, no rtkit — same privilege profile as everything
      else): a null sink plus the native protocol on TCP 4713, which
      guacd's VNC client consumes (`enable-audio`/`audio-servername`).
      Module loading is frozen after startup
      (`--disallow-module-loading`), so neither an in-session client nor
      a network peer can extend the daemon. TCP auth is anonymous BY
      DESIGN: the guacd-only NetworkPolicy is the boundary for 4713
      exactly as it is for the cleartext VNC port (see § Threat
      model). `WAAS_AUDIO_ENABLED=0` disables the daemon entirely.
      → `waas-entrypoint`, `etc/waas/pulse/default.pa.tpl`; verify: CI
      smoke test runs `pactl info` against tcp:4713.

## To apply on the platform side (documented contract)

- [ ] Pod `securityContext` (recommended for the operator's pod spec):
      `runAsNonRoot`, `runAsUser/fsGroup: 1000`,
      `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`,
      `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true` +
      emptyDir on `/tmp`. Meets PodSecurity **restricted**.
      AppArmor: `runtime/default` is sufficient; no custom profile needed.
- [ ] `examples/networkpolicy-workspaces.yaml`: only guacd reaches
      5901/4713; no east-west between workspaces. Mandatory if
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
outside `/home/waas_user|/tmp`, and `no-new-privileges` kills setuid
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
loud boot warning; the catalog entry must keep its `allowedGroups` gate
(platform-side, documented contract — same list as the standard
`devtools`).

Machine mirror: `ci/generate_catalog.py`'s `RECOMMENDATION_DEV` derives
the published catalog's `recommended` block (`profile: normal`) from
the three exceptions above — not a guarantee against drift, but keep
both in sync when editing either.

### Durable tooling without the reduced profile

The "lost on pod restart" caveat above is unchanged and still exact: apt
state lives in the container layer and dies with the pod. Nothing here
makes `sudo apt install` persist, and no image-side mechanism can — an
overlay would need `mount(2)`, i.e. `CAP_SYS_ADMIN`, which § Known gaps
declines to grant.

What *is* solved is the underlying need. The desktop layer
(`desktop/xfce`, `desktop/xfce-fedora`) ships **mise**, so every image
built on it inherits it: the three OS desktops and, being built FROM
`ubuntu-desktop-noble`, `apps/devtools`. `apps/hermes-agent` carries
its own copy — it is a kiosk on `core-ubuntu-noble`, outside the XFCE
lineage. mise installs toolchains under `~/.local/share/mise`, on the
home PVC, so they survive restarts by construction. It writes nothing
outside `$HOME` and `/tmp` and needs no privileges, so it ships on the
**hardened** variants too, not only on `-dev` (verified: installs a new
tool fine under `--read-only`). A user who only needs a language runtime
or a CLI tool therefore does not need the reduced profile at all —
prefer the hardened tag.

The gap it does not close: **system libraries**. Anything requiring a
`.so`, a codec or an apt package's maintainer scripts still means `sudo
apt install` on a `-dev` image, and still dies with the pod.

Two consequences worth stating: what a user installs via mise lives on
the PVC, so it is outside the trivy gate and the SBOM by construction
(same as anything `/etc/waas/init.d/` pulls in); and mise's shims sit
first on `PATH`, so a user-installed `python3` shadows the image's.

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
runs on the pod network. VNC between guacd and the workspace is
**cleartext**, accepted because: (1) both endpoints live in the same
cluster namespace, (2) the NetworkPolicy above restricts the path to
guacd exactly, (3) guacd's VNC client support for X509/VeNCrypt is
unreliable, so forcing TLS there would break the only protocol. If the
pod network itself is in scope (multi-tenant nodes, no CNI encryption),
enable WireGuard/IPsec at the CNI layer (Cilium/Calico) rather than
per-protocol TLS — it also covers guacd→wwt. (The xrdp bridge used to
offer a negotiated-TLS alternative on 3389; it is gone with RDP, and the
CNI answer above was already the recommended one.)

## Known, accepted gaps (documented, not hidden)

- `/etc/machine-id` is identical across containers of one image (baked
  for read-only dbus); not used as identity by anything shipped.
- Clipboard is text-only over VNC (RFB cut-text via vncconfig); files
  and images are not bridged. Browser-window resizes are not pushed to
  the server by guacd's VNC client (`waas-resize` inside the session is
  the workaround, see README).
- Firefox's *internal* process sandbox degrades in the container
  (`CanCreateUserNamespace: EPERM`): unprivileged user namespaces are
  blocked by the seccomp/caps profile. Deliberate: the pod (non-root,
  no caps, read-only, seccomp, NetworkPolicy) is the sandbox boundary
  here; granting CAP_SYS_ADMIN to restore Firefox's inner sandbox would
  weaken the outer one.
