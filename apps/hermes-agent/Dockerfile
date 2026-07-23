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
# The npm bundled in the node tarball (10.9.8) ships two HIGH CVEs in its
# OWN vendored deps — picomatch 4.0.3 (CVE-2026-33671) and sigstore 3.1.0
# (CVE-2026-48815) — which gated the Trivy scan red. Neither is hermes
# code and neither is reachable from anything we run, but the scan is a
# hard gate, so upgrade npm rather than suppress: npm 12 drops picomatch
# entirely and vendors sigstore 5.0.0 (fix landed in 4.1.1).
# renovate: datasource=npm depName=npm
ARG NPM_VERSION=12.0.1
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
    npm install -g "npm@${NPM_VERSION}" && \
    npm --version && \
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh \
        | bash -s -- --branch "${HERMES_VERSION}" --skip-setup --non-interactive --skip-browser && \
    /usr/local/bin/hermes --version && \
    # Prebuild BOTH front-ends: each otherwise npm-installs and builds
    # itself lazily on first launch, which can never work at runtime
    # (root-owned tree, read-only rootfs).
    #   web    — the dashboard UI, served by the Python server.
    #   ui-tui — the terminal chat UI behind the kiosk's fallback path.
    # One install for both: npm workspaces hoist to the root
    # node_modules, and a second `npm install --workspace ...` would
    # re-resolve that shared tree.
    # node_modules is build scaffolding only, for both: the Python
    # server serves web's built assets without it (verified: 200 after
    # full prune), and ui-tui/scripts/build.mjs esbuilds a deliberately
    # self-contained dist/entry.js ("No runtime node_modules needed").
    cd /usr/local/lib/hermes-agent && \
    npm install --workspace web --workspace ui-tui && \
    npm run build -w web && \
    npm run build -w ui-tui && \
    test -f hermes_cli/web_dist/index.html && \
    test -f ui-tui/dist/entry.js && \
    rm -rf node_modules web/node_modules ui-tui/node_modules \
        /root/.npm /root/.hermes && \
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

# mise — user-level toolchain manager. The point is persistence: only
# /home/waas_user is a PVC, so anything `sudo apt install` puts in the
# container layer dies with the pod. mise installs tools under
# ~/.local/share/mise, i.e. ON the home volume, so they survive restarts.
# It needs no privileges and writes nothing outside $HOME + /tmp, which is
# why it ships on the hardened variant too (read-only rootfs and all), not
# just on -dev.
#
# Verification chain mirrors the Mozilla block above: pin the SIGNING KEY
# fingerprint, not a per-arch digest. A literal SHA256 would need one ARG
# per arch and renovate cannot recompute either, so a version bump would
# break the build every single time.
# renovate: datasource=github-releases depName=jdx/mise
ARG MISE_VERSION=v2026.7.12
# DL3003: a WORKDIR would leak /tmp as every later step's cwd for one cd;
# DL3008: gpg is build scaffolding, purged at the end of this same layer.
# hadolint ignore=DL3003,DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends gpg && \
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
    apt-get purge -y --auto-remove gpg && \
    apt-get clean && \
    # The base exports HOME=/home/waas_user, and this image RUNs as root —
    # so root's `mise --version` above just seeded ~/.cache/mise and
    # ~/.local/share/mise ROOT-OWNED inside the user's home. Same trap gpg
    # falls into (hence the .gnupg removal alongside). Harmless under a
    # k8s PVC, which shadows the dir, but a docker named volume COPIES
    # image content in and the user then cannot write their own cache.
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/* \
        /home/waas_user/.gnupg /home/waas_user/.cache /home/waas_user/.local

# Both mise wiring mechanisms, because they cover different contexts and
# upstream recommends the pair (dev-tools/shims.html):
#   shims on PATH — the only thing that works in NON-interactive contexts
#     (the agent's subprocesses, XFCE menu launches, WAAS_APP, scripts).
#     Verified: a `bash -c` reads neither /etc/bash.bashrc nor ~/.bashrc.
#   `mise activate` — richer (mise's [env] vars, cd/enter/leave hooks) but
#     driven by the prompt hook, so interactive shells only.
# No precedence problem: activate strips the shims dir from PATH itself.
# A missing shims dir on a fresh PVC is inert (execvp skips it), so there
# is nothing to pre-create — and pre-creating would be pointless anyway,
# the PVC shadows whatever the image puts at that path.
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
# SC2016 is the intent, not a bug: the single quotes keep $(mise activate
# bash) LITERAL so it lands unexpanded in /etc/bash.bashrc and runs per
# shell. Expanding it here would bake this build's activation script into
# the image and silently rot on the next mise bump.
# hadolint ignore=SC2016
RUN printf '\n# mise (waas): user toolchains live on the home PVC — see the Dockerfile.\neval "$(mise activate bash)"\n' \
        >> /etc/bash.bashrc

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

# Point hermes at the two bundles built above. Both vars are what
# upstream's own Docker image sets (their Dockerfile + immutable-install
# tests assert them), for the same reason we need them: an install tree
# that is root-owned and read-only at runtime.
#
# TUI — prebuilding alone is NOT enough. _make_tui_argv()
# (hermes_cli/main.py) re-runs `npm run build` on EVERY launch outside
# Termux (should_build is unconditionally True), writing ui-tui/dist/
# entry.js. HERMES_TUI_DIR is checked at the top of that function and
# returns `node --expose-gc <dir>/dist/entry.js` directly, skipping both
# the npm install and the rebuild. Must NOT be combined with
# `hermes --dev` (upstream rejects the pair).
#
# WEB — without it, `hermes dashboard` falls into
# `_build_web_ui(PROJECT_ROOT/"web", fatal=True)`. That happens to no-op
# today only because _web_ui_build_needed() judges our prebuilt dist
# fresh; setting the var makes it unconditional instead of resting on a
# staleness heuristic. vite's outDir is ../hermes_cli/web_dist, so this
# is where `npm run build -w web` already writes.
#
# Both silently fall back to running npm against the read-only tree if
# the artifacts are not actually at these paths — hence the two `test -f`
# guards in the build above.
ENV HERMES_TUI_DIR=/usr/local/lib/hermes-agent/ui-tui
ENV HERMES_WEB_DIST=/usr/local/lib/hermes-agent/hermes_cli/web_dist

USER 1000:1000
