# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# waas ubuntu-devtools — XFCE work desktop with VS Code and a dev toolchain.
#
# Fills the governance-catalog entry "Dev Tools (VS Code, toolchains)"
# (allowedGroups nymphe:dev). VS Code comes from the Microsoft APT repo
# (packages.microsoft.com/repos/code), pinned by its signing-key
# fingerprint and an apt preference — the exact pattern proven on
# apps/firefox. The toolchain mirrors apps/dev-ssh.
#
# Hand-written on purpose (not a recipe:): third-party repo + composed
# toolchain + the INSTALL_SUDO dev-variant hook exceed the apt-simple
# case. No autostart: this is a work desktop, VS Code sits in the XFCE
# menu.
ARG BASE_IMAGE
# hadolint ignore=DL3006
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER 0

# Vendored fallback: packages.microsoft.com (Azure Front Door) is
# unreachable from some runner fleets even with -4 (IPv4 route, not just
# the IPv6 one, ends up blackholed) — unlike packages.mozilla.org /
# dl.google.com, which -4 alone fixed. Rather than fail the build on a
# transient network path to one vendor, fetch live and fall back to a
# copy of the same key checked into the repo, verified below against
# the fingerprint either way. Refresh this file if Microsoft ever
# rotates the key (build breaks loudly on a fingerprint mismatch).
COPY microsoft-signing-key.asc /tmp/microsoft-signing-key.vendored.asc

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget gpg && \
    install -d -m 0755 /etc/apt/keyrings && \
    ( wget -4 --timeout=20 --tries=3 -qO- https://packages.microsoft.com/keys/microsoft.asc \
        > /tmp/microsoft-signing-key.fetched.asc || true ) && \
    if [ -s /tmp/microsoft-signing-key.fetched.asc ]; then \
        cp /tmp/microsoft-signing-key.fetched.asc /tmp/microsoft-signing-key.asc; \
    else \
        echo "WARN: live fetch of packages.microsoft.com signing key failed, falling back to vendored copy" >&2; \
        cp /tmp/microsoft-signing-key.vendored.asc /tmp/microsoft-signing-key.asc; \
    fi && \
    gpg --dearmor -o /etc/apt/keyrings/packages.microsoft.com.gpg /tmp/microsoft-signing-key.asc && \
    rm -f /tmp/microsoft-signing-key.fetched.asc /tmp/microsoft-signing-key.vendored.asc /tmp/microsoft-signing-key.asc && \
    # --with-colons: machine-readable output, fingerprint unspaced.
    # Fingerprint read from the live key on 2026-07-11.
    gpg --show-keys --with-colons /etc/apt/keyrings/packages.microsoft.com.gpg \
        | grep -q "^fpr:.*BC528686B50D79E339D3721CEB3E94ADBE1229CF" && \
    echo "deb [signed-by=/etc/apt/keyrings/packages.microsoft.com.gpg] https://packages.microsoft.com/repos/code stable main" \
        > /etc/apt/sources.list.d/vscode.list && \
    printf 'Package: code*\nPin: origin packages.microsoft.com\nPin-Priority: 1000\n' \
        > /etc/apt/preferences.d/vscode && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        code \
        git \
        build-essential \
        python3 \
        python3-venv \
        jq \
        curl \
        vim \
        less \
        tmux \
    && apt-mark auto wget gpg >/dev/null && \
    # autoremove, not purge: a blind purge would drag away any package
    # above that Depends: on wget/gpg; dpkg -s makes that a build failure.
    apt-get autoremove -y --purge && \
    dpkg -s code git build-essential python3 python3-venv jq curl vim less tmux >/dev/null && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/* /home/waas_user/.gnupg

# ---- dev variant (ubuntu-devtools-dev) --------------------------------
# INSTALL_SUDO=1 is only ever set by the *-dev manifest variant (the
# generator refuses it on a name without the -dev suffix) and yields a
# DISTINCT tag with a documented reduced profile (HARDENING.md § Reduced
# profile). sudo is useless without the matching pod profile
# (readOnlyRootFilesystem: false, allowPrivilegeEscalation: true) — that
# WorkspaceTemplate change lives in the platform repo. Anything
# installed in-session lands in the container layer: lost on pod
# restart, only /home/waas_user (PVC) survives.
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
# boots a dev-profile image (RDP_AUTH_ENABLED=false precedent). Injected
# by the generator from the variant's profile: key.
ARG WAAS_PROFILE=standard
ENV WAAS_PROFILE=${WAAS_PROFILE}

# The pod is the sandbox boundary (non-root, no caps, seccomp, read-only,
# NetworkPolicy): the default seccomp profile blocks the user namespaces
# VS Code's Chromium sandbox wants, exactly like Firefox (HARDENING.md
# § Known gaps). Ship a desktop entry that launches it accordingly.
RUN install -d -m 0755 /usr/share/applications && \
    printf '[Desktop Entry]\nType=Application\nName=Visual Studio Code\nComment=Code Editing. Redefined.\nExec=/usr/bin/code --no-sandbox %%F\nIcon=vscode\nCategories=Development;IDE;\nMimeType=text/plain;inode/directory;\n' \
        > /usr/share/applications/code.desktop

USER 1000:1000
