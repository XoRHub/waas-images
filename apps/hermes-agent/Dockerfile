# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# waas hermes-agent — Nous Research's Hermes Agent with its web
# dashboard as the kiosk session: Firefox on http://127.0.0.1:9119
# (the dashboard's Chat tab embeds the full TUI via xterm.js, so one
# surface covers chat AND status/keys/cron/logs). The dashboard server
# is supervised via the entrypoint.d hook, loopback-only — the
# password-gated VNC display stays the sole way in. Operators can flip
# back to the bare TUI (WAAS_APP="xterm -fa monospace -fs 12 -e
# hermes") or disable the server (WAAS_HERMES_DASHBOARD=0) per
# workspace, no rebuild.
#
# Upstream's installer in its root FHS mode: code in
# /usr/local/lib/hermes-agent, launcher /usr/local/bin/hermes,
# uv-managed Python under /usr/local/share — per-user state stays in
# ~/.hermes, which self-bootstraps on first run (verified: fresh uid
# 1000 home) and lands on the /home/waas_user volume at runtime, so
# keys/sessions/memories/skills survive pod restarts. Node 22 is
# preinstalled system-wide BEFORE the installer runs: it accepts any
# node >= 22.12 and otherwise drops a Hermes-managed copy into the
# build user's home — which the runtime home mount would shadow.
ARG BASE_IMAGE
# hadolint ignore=DL3006
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER 0

ARG TARGETARCH
# renovate: datasource=node-version depName=node
ARG NODE_VERSION=22.23.1
# renovate: datasource=github-tags depName=NousResearch/hermes-agent
ARG HERMES_VERSION=v2026.7.7.2

# git/ripgrep/ffmpeg: upstream's documented runtime deps (agent tools);
# xz-utils stays — node tarball now, an archive tool for the agent
# later. /root/.hermes is install-time state for the WRONG user (the
# app recreates it per user on first run) — remove it, and every
# credential-shaped leftover with it.
# DL3003: a WORKDIR would leak the code tree as every later step's cwd
# for one cd; DL3016: the web workspace's deps come from upstream's own
# committed lockfile, there is nothing for us to pin here.
# hadolint ignore=DL3008,DL3003,DL3016
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl git ripgrep ffmpeg xz-utils && \
    case "${TARGETARCH}" in \
        amd64) NODE_ARCH=x64 ;; \
        arm64) NODE_ARCH=arm64 ;; \
        *) echo "unsupported TARGETARCH ${TARGETARCH}" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
        | tar -xJ -C /usr/local --strip-components=1 --no-same-owner && \
    node --version && \
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh \
        | bash -s -- --branch "${HERMES_VERSION}" --skip-setup --non-interactive --skip-browser && \
    /usr/local/bin/hermes --version && \
    # Prebuild the dashboard's web UI: `hermes dashboard` otherwise
    # npm-builds it lazily on first launch, which can never work at
    # runtime (root-owned tree, read-only rootfs). node_modules is
    # build scaffolding only — the Python server serves the built
    # assets without it (verified: 200 after full prune).
    cd /usr/local/lib/hermes-agent && \
    npm install --workspace web && \
    npm run build -w web && \
    rm -rf node_modules web/node_modules /root/.npm /root/.hermes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/* /home/waas_user/.gnupg /tmp/*

# Firefox for the dashboard kiosk — the exact packages.mozilla.org
# pattern proven on apps/firefox (fingerprint-pinned repo + apt pin),
# with the same hardened enterprise policies (rootfs/etc/firefox);
# HTTPS-Only mode exempts 127.0.0.1, so the local dashboard loads.
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
    dpkg -s firefox curl git ripgrep ffmpeg >/dev/null && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/* /home/waas_user/.gnupg

# Kiosk wrapper, dashboard entrypoint hook, firefox policies.
COPY rootfs/ /

# ---- dev variant (hermes-agent-dev) -----------------------------------
# INSTALL_SUDO=1 is only ever set by the *-dev manifest variant (the
# generator refuses it on a name without the -dev suffix) and yields a
# DISTINCT tag with a documented reduced profile (HARDENING.md § Reduced
# profile) — the pod contract change lives in the platform repo. Lets
# the agent `sudo apt install` in-session; those installs land in the
# container layer and are lost on pod restart, only /home/waas_user
# (and so ~/.hermes) survives.
ARG INSTALL_SUDO=0
# hadolint ignore=DL3008
RUN if [ "${INSTALL_SUDO}" = "1" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends sudo && \
        printf '#1000 ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/waas-dev && \
        chmod 0440 /etc/sudoers.d/waas-dev && \
        apt-get clean && \
        rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/*; \
    fi

# Re-assert suid stripping (new packages may bring some back). Separate
# RUN: a trailing "|| true" on the apt chain would mask install failures.
# The dev variant excludes exactly /usr/bin/sudo — the smoke test
# asserts the resulting set (empty vs exactly sudo) per profile.
RUN if [ "${INSTALL_SUDO}" = "1" ]; then \
        find / -xdev -perm /6000 -type f ! -path /usr/bin/sudo -exec chmod a-s {} + 2>/dev/null || true; \
    else \
        find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true; \
    fi

# Baked profile marker: waas-entrypoint logs a loud warning when it
# boots a dev-profile image. Injected by the generator from the
# variant's profile: key.
ARG WAAS_PROFILE=standard
ENV WAAS_PROFILE=${WAAS_PROFILE}

# Session contract with the base entrypoint: WAAS_APP puts waas-session
# in single-app kiosk mode; word-split by the session script, so no
# quoted arguments. The wrapper waits for the supervised dashboard then
# execs Firefox on it, falling back to the xterm TUI if it never comes
# up. First run lands on hermes' own onboarding (model/provider/keys),
# stored under ~/.hermes.
ENV WAAS_APP="waas-hermes-kiosk"
ENV WAAS_HERMES_DASHBOARD=1

USER 1000:1000
