# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# waas desktop (XFCE) — lightweight full desktop on top of a core image.
#
# BASE_IMAGE is injected by CI as the exact ref built earlier in the same
# pipeline — registry/core-ubuntu-noble-full:<version>-<sha>
# (ubuntu-desktop-noble), registry/core-debian-13-full:<version>-<sha>
# (debian-desktop-13), or registry/core-ubuntu-noble:<version>-<sha>
# (core-ubuntu-noble-xfce, the VNC-only devtools parent) — so a layer
# change propagates through the whole tree in one pipeline run. RDP/SSH
# capability is entirely inherited from whichever core parent this is
# built FROM; this Dockerfile only ever installs the desktop environment.
ARG BASE_IMAGE
# hadolint ignore=DL3006
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER 0

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        xfce4-session \
        xfce4-panel \
        xfce4-settings \
        xfdesktop4 \
        xfwm4 \
        xfce4-terminal \
        thunar \
        adwaita-icon-theme \
    && apt-get purge -y --auto-remove xterm && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/*

# ---- desktop baseline -------------------------------------------------
# A desktop with only a terminal and a file manager is not a usable
# workspace: before this, ubuntu-desktop-noble / debian-desktop-13 shipped
# XFCE and nothing else — no browser, no editor, no git, and no ssh client
# at all (`git push` over SSH was impossible on EVERY image in this repo,
# devtools included). This layer is where that belongs: it reaches the two
# OS desktops AND core-ubuntu-noble-xfce, so apps/devtools inherits it
# instead of carrying its own copy. The kiosk apps built straight on
# core-ubuntu-noble (firefox, chrome, libreoffice, hermes-agent) are
# deliberately untouched — they have no shell to use any of it.
#
# openssh-client, not openssh-server: this is the client half, for `git
# push` and outbound ssh. Whether sshd LISTENS is still entirely the core
# parent's INSTALL_SSH decision.
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        curl \
        vim \
        less \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/*

# Firefox — same packages.mozilla.org pattern proven on apps/firefox and
# apps/hermes-agent (fingerprint-pinned repo + apt pin). The Mozilla deb
# ships its own .desktop; we add no --no-sandbox override, matching
# apps/firefox — the degraded inner sandbox is the documented, accepted
# posture (HARDENING.md § Known gaps).
# renovate: datasource=custom.mozilla-apt depName=firefox
ARG FIREFOX_VERSION=*
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends gpg && \
    install -d -m 0755 /etc/apt/keyrings && \
    curl -fsSL -4 --max-time 20 https://packages.mozilla.org/apt/repo-signing-key.gpg \
        | gpg --dearmor -o /etc/apt/keyrings/packages.mozilla.org.gpg && \
    gpg --show-keys --with-colons /etc/apt/keyrings/packages.mozilla.org.gpg \
        | grep -q "^fpr:.*35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3" && \
    echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.gpg] https://packages.mozilla.org/apt mozilla main" \
        > /etc/apt/sources.list.d/mozilla.list && \
    printf 'Package: firefox*\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' \
        > /etc/apt/preferences.d/mozilla && \
    apt-get update && \
    if [ "${FIREFOX_VERSION}" = "*" ]; then \
        apt-get install -y --no-install-recommends firefox; \
    else \
        apt-get install -y --no-install-recommends "firefox=${FIREFOX_VERSION}"; \
    fi && \
    apt-get purge -y --auto-remove gpg && \
    dpkg -s firefox git openssh-client curl vim less >/dev/null && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/* /home/waas_user/.gnupg

# Enterprise policies: hardened defaults, applied system-wide and
# non-overridable by the user (Mozilla debs read /etc/firefox/policies).
COPY policies.json /etc/firefox/policies/policies.json

# mise — user-level toolchain manager, and the answer to the one thing
# this platform cannot otherwise offer: only /home/waas_user is a PVC, so
# anything apt installs dies with the pod. mise installs under
# ~/.local/share/mise, i.e. ON the home volume, so toolchains survive
# restarts. It needs no privileges and writes nothing outside $HOME and
# /tmp, so it works on the hardened profile too (verified: installs fine
# under --read-only) — a user needing a language runtime therefore does
# not need a -dev tag at all.
#
# Verification pins the SIGNING KEY fingerprint, not a per-arch digest: a
# literal SHA256 would need one ARG per arch and renovate cannot recompute
# either, so a version bump would break the build every time.
# renovate: datasource=github-releases depName=jdx/mise
ARG MISE_VERSION=v2026.7.7
ARG TARGETARCH
# gpgv is a SEPARATE package from gpg (a standalone verifier binary; the
# gpg package does not ship it), and the SHASUMS256.asc check below execs
# it directly. ubuntu-noble carries it in the base image already — apt
# there hard-depends on gpgv for archive verification — but Debian 13
# does not: trixie's apt verifies archives with sequoia's sqv and dropped
# the hard gpgv dependency, so the debian-desktop-13 leg had no gpgv at
# all and died with "gpgv: command not found" (exit 127). Hence gpgv is
# named explicitly below — but installed AND purged conditionally: on
# ubuntu-noble the base's own gpgv must survive this layer (purging it
# would tear out apt's dependency and the resolver refuses), so only a
# copy this layer added is ours to remove.
#
# DL3003: a WORKDIR would leak /tmp as every later step's cwd for one cd;
# DL3008: gpg (and gpgv where we added it) is build scaffolding, purged
# at the end of this same layer;
# SC2086: ${GPGV_PKG} is deliberately unquoted — when empty it must
# expand to no argument at all, a quoted "" would reach apt-get as a
# package named "".
# hadolint ignore=DL3003,DL3008,SC2086
RUN apt-get update && \
    if dpkg -s gpgv >/dev/null 2>&1; then GPGV_PKG=""; else GPGV_PKG="gpgv"; fi && \
    apt-get install -y --no-install-recommends gpg ${GPGV_PKG} && \
    case "${TARGETARCH}" in \
        amd64) MISE_ARCH=x64 ;; \
        arm64) MISE_ARCH=arm64 ;; \
        *) echo "unsupported TARGETARCH ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    MISE_TARBALL="mise-${MISE_VERSION}-linux-${MISE_ARCH}.tar.gz" && \
    cd /tmp && \
    # Saved under its exact release filename on purpose: SHASUMS256.asc
    # lists paths as "./mise-<ver>-linux-<arch>.tar.gz", so `sha256sum -c`
    # resolves them relative to cwd. Rename it and the check fails with a
    # confusing "FAILED open or read".
    curl -fsSL -4 --max-time 60 \
        "https://github.com/jdx/mise/releases/download/${MISE_VERSION}/${MISE_TARBALL}" \
        -o "${MISE_TARBALL}" && \
    curl -fsSL -4 --max-time 20 \
        "https://github.com/jdx/mise/releases/download/${MISE_VERSION}/SHASUMS256.asc" \
        -o SHASUMS256.asc && \
    curl -fsSL -4 --max-time 20 https://mise.jdx.dev/gpg-key.pub \
        | gpg --dearmor -o /tmp/mise-release-key.gpg && \
    gpg --show-keys --with-colons /tmp/mise-release-key.gpg \
        | grep -q "^fpr:.*24853EC9F655CE80B48E6C3A8B81C9D17413A06D" && \
    gpgv --keyring /tmp/mise-release-key.gpg SHASUMS256.asc && \
    # Checksums come out of the clearsigned body only AFTER gpgv accepted
    # it, so the digest we compare against is itself signed.
    grep "  ./${MISE_TARBALL}\$" SHASUMS256.asc | sed 's|\./||' | sha256sum -c - && \
    tar -xzf "${MISE_TARBALL}" -C /usr/local/bin --strip-components=2 mise/bin/mise && \
    rm -f "${MISE_TARBALL}" SHASUMS256.asc /tmp/mise-release-key.gpg && \
    test "$(mise --version | cut -d' ' -f1)" = "${MISE_VERSION#v}" && \
    apt-get purge -y --auto-remove gpg ${GPGV_PKG} && \
    apt-get clean && \
    # The base exports HOME=/home/waas_user, and derived images RUN as
    # root — so root's `mise --version` above just seeded ~/.cache/mise
    # and ~/.local/share/mise ROOT-OWNED inside the user's home. Same trap
    # gpg falls into (hence the .gnupg removal alongside). Harmless under
    # a k8s PVC, which shadows the dir, but a docker named volume COPIES
    # image content in and the user then cannot write their own cache.
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/* \
        /home/waas_user/.gnupg /home/waas_user/.cache /home/waas_user/.local

# Both mise wiring mechanisms, because they cover different contexts and
# upstream recommends the pair (dev-tools/shims.html):
#   shims on PATH — the only thing that works in NON-interactive contexts
#     (XFCE menu launches, scripts, anything not an interactive bash).
#     Verified: a `bash -c` reads neither /etc/bash.bashrc nor ~/.bashrc.
#   `mise activate` — richer (mise's [env] vars, cd/enter/leave hooks) but
#     driven by the prompt hook, so interactive shells only. This is what
#     xfce4-terminal gets.
# No precedence problem: activate strips the shims dir from PATH itself.
# A missing shims dir on a fresh PVC is inert (execvp skips it), and
# pre-creating it would be pointless — the PVC shadows that path anyway.
ENV PATH=/home/waas_user/.local/share/mise/shims:/home/waas_user/.local/bin:$PATH
# Pinned explicitly rather than left to XDG defaults: the PATH above
# hardcodes the shims location, so the data dir must not be free to move.
# startxfce4/dbus can inject XDG_* into the session, and an XDG_CACHE_HOME
# landing on a tmpfs would silently stop the cache from persisting.
ENV MISE_DATA_DIR=/home/waas_user/.local/share/mise \
    MISE_CACHE_DIR=/home/waas_user/.cache/mise

# Interactive activation goes in /etc/bash.bashrc, NOT /etc/skel/.bashrc:
# waas-entrypoint only seeds skel when ~/.profile is absent, so an
# existing PVC would never see a skel change. /etc/bash.bashrc lives in
# the image layer and therefore covers old and new volumes alike.
#
# SC2016 is the intent, not a bug: the single quotes keep $(mise activate
# bash) LITERAL so it lands unexpanded and runs per shell. Expanding here
# would bake this build's activation script in and rot on the next bump.
# hadolint ignore=SC2016
RUN printf '\n# mise (waas): user toolchains live on the home PVC — see the Dockerfile.\neval "$(mise activate bash)"\n' \
        >> /etc/bash.bashrc

# Re-assert suid stripping (new packages may bring some back). Separate
# RUN: a trailing "|| true" on the apt chain would mask install failures.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

# Session contract with the base entrypoint: WAAS_STARTUP replaces the
# openbox fallback. dbus-launch is prepended by waas-session.
ENV WAAS_STARTUP=startxfce4

USER 1000:1000
