# syntax=docker/dockerfile:1.7
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

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget gpg && \
    install -d -m 0755 /etc/apt/keyrings && \
    wget -qO- https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /etc/apt/keyrings/packages.microsoft.com.gpg && \
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
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/* /home/user/.gnupg

# Re-assert suid stripping (new packages may bring some back). Separate
# RUN: a trailing "|| true" on the apt chain would mask install failures.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

# The pod is the sandbox boundary (non-root, no caps, seccomp, read-only,
# NetworkPolicy): the default seccomp profile blocks the user namespaces
# VS Code's Chromium sandbox wants, exactly like Firefox (HARDENING.md
# § Known gaps). Ship a desktop entry that launches it accordingly.
RUN install -d -m 0755 /usr/share/applications && \
    printf '[Desktop Entry]\nType=Application\nName=Visual Studio Code\nComment=Code Editing. Redefined.\nExec=/usr/bin/code --no-sandbox %%F\nIcon=vscode\nCategories=Development;IDE;\nMimeType=text/plain;inode/directory;\n' \
        > /usr/share/applications/code.desktop

USER 1000:1000
