# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# waas fedora desktop — lightweight full desktop on top of a fedora core
# image.
#
# dnf sibling of desktop/xfce/Dockerfile (the build context is the image
# directory, so the two cannot share a file). Package deltas verified
# against Fedora 43: xfdesktop (not xfdesktop4), Thunar (capitalised).
#
# BASE_IMAGE is injected by CI as the exact ref built earlier in the same
# pipeline (registry/core-fedora-43-full:<version>-<sha>), so a layer
# change propagates through the whole tree in one pipeline run. RDP/SSH
# capability is entirely inherited from that core parent; this Dockerfile
# only ever installs the desktop environment.
ARG BASE_IMAGE
# hadolint ignore=DL3006
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER 0

# hadolint ignore=DL3041
RUN dnf install -y --setopt=install_weak_deps=False \
        xfce4-session \
        xfce4-panel \
        xfce4-settings \
        xfdesktop \
        xfwm4 \
        xfce4-terminal \
        Thunar \
        adwaita-icon-theme \
    && dnf remove -y xterm && \
    dnf clean all && \
    rm -rf /var/cache/* /var/log/*

# ---- desktop baseline -------------------------------------------------
# dnf sibling of the same block in desktop/xfce/Dockerfile — see there for
# the rationale. Package name deltas verified against Fedora 43:
# openssh-clientS (plural), vim-enhanced (not vim).
#
# Firefox comes straight from the Fedora repos, NOT packages.mozilla.org:
# Fedora ships a real, current firefox RPM (152.0.6-1.fc43, the same
# upstream version as the Mozilla .deb the apt sibling pins), so the
# third-party-repo dance buys nothing here.
#
# That difference also means this image should NOT inherit the apt
# sibling's expat .trivyignore: CVE-2022-25235/25236 are false positives
# caused by Ubuntu's snap-transitional "firefox" stub and its epoch, a
# mechanism with no Fedora equivalent. Deliberately left unsuppressed —
# if the fedora scan ever flags them, that is new information worth
# reading rather than something to have pre-silenced.
# hadolint ignore=DL3041
RUN dnf install -y --setopt=install_weak_deps=False \
        firefox \
        git \
        openssh-clients \
        curl \
        vim-enhanced \
        less \
    && rpm -q firefox git openssh-clients curl vim-enhanced less >/dev/null && \
    dnf clean all && \
    # .viminfo: the base exports HOME=/home/waas_user and this RUN is
    # root, so the vim-enhanced transaction leaves a root-owned dotfile in
    # the user's home. Same class as the .gnupg/.cache cleanup below.
    rm -rf /var/cache/* /var/log/* /home/waas_user/.viminfo

# Enterprise policies: same hardened set as the apt sibling. /etc/firefox/
# policies is the documented system-wide location on Linux and works for
# distro-packaged Firefox too; verified that Fedora's RPM ships no
# distribution/policies.json, which would otherwise take precedence.
COPY policies.json /etc/firefox/policies/policies.json

# mise — see desktop/xfce/Dockerfile for the full rationale. The block is
# near-identical because mise is a signed tarball, not a package: only the
# gnupg2 install differs from the apt sibling.
#
# gnupg2-verify is what actually ships /usr/bin/gpgv here (verified:
# rpm -qf on Fedora 43) — gnupg2 hard-requires it and fedora:43's base
# image even preinstalls it, so the `gpgv` call below worked without it
# being named. Named anyway: the apt sibling broke exactly when a base
# image (debian:13-slim) stopped implying gpgv, and this line is what
# keeps that failure mode impossible rather than merely absent today.
# NOT added to the `dnf remove` below: it is base-image content on
# Fedora, not scaffolding this layer introduced.
# renovate: datasource=github-releases depName=jdx/mise
ARG MISE_VERSION=v2026.7.7
ARG TARGETARCH
# DL3003: a WORKDIR would leak /tmp as every later step's cwd for one cd.
# hadolint ignore=DL3003,DL3041
RUN dnf install -y --setopt=install_weak_deps=False gnupg2 gnupg2-verify && \
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
    dnf remove -y gnupg2 && \
    dnf clean all && \
    # The base exports HOME=/home/waas_user, and derived images RUN as
    # root — so root's `mise --version` above just seeded ~/.cache/mise
    # and ~/.local/share/mise ROOT-OWNED inside the user's home. Harmless
    # under a k8s PVC, which shadows the dir, but a docker named volume
    # COPIES image content in and the user then cannot write their cache.
    rm -rf /var/cache/* /var/log/* \
        /home/waas_user/.gnupg /home/waas_user/.cache /home/waas_user/.local

# Both mise wiring mechanisms — see desktop/xfce/Dockerfile. Shims cover
# non-interactive contexts (a `bash -c` reads no rc file at all), activate
# covers interactive shells with the richer feature set. activate strips
# the shims dir from PATH itself, so there is no precedence conflict.
ENV PATH=/home/waas_user/.local/share/mise/shims:/home/waas_user/.local/bin:$PATH
ENV MISE_DATA_DIR=/home/waas_user/.local/share/mise \
    MISE_CACHE_DIR=/home/waas_user/.cache/mise

# /etc/bashrc, NOT /etc/bash.bashrc — this is the one real divergence from
# the apt sibling. The Red Hat family's system-wide interactive bashrc is
# /etc/bashrc; /etc/bash.bashrc is Debian/Ubuntu's name and bash never
# reads it here. Appending to the wrong one fails silently: the file is
# created, the build succeeds, and activation simply never happens
# (caught exactly that way — ACTIVATE_FAIL on the first fedora build).
#
# Still not /etc/skel/.bashrc: waas-entrypoint only seeds skel when
# ~/.profile is absent, so an existing PVC would never see a skel change.
# SC2016 is the intent — the single quotes keep $(mise activate bash)
# literal so it runs per shell instead of being baked at build time.
# hadolint ignore=SC2016
RUN printf '\n# mise (waas): user toolchains live on the home PVC — see the Dockerfile.\neval "$(mise activate bash)"\n' \
        >> /etc/bashrc

# Re-assert suid stripping (new packages may bring some back). Separate
# RUN: a trailing "|| true" on the dnf chain would mask install failures.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

# Session contract with the base entrypoint: WAAS_STARTUP replaces the
# openbox fallback. dbus-launch is prepended by waas-session.
ENV WAAS_STARTUP=startxfce4

USER 1000:1000
