# syntax=docker/dockerfile:1.7
# waas fedora-xfce — lightweight full desktop on top of the fedora base.
#
# dnf sibling of desktop/xfce/Dockerfile (the build context is the image
# directory, so the two cannot share a file). Package deltas verified
# against Fedora 43: xfdesktop (not xfdesktop4), Thunar (capitalised).
#
# BASE_IMAGE is injected by CI as the exact ref built earlier in the same
# pipeline (registry/fedora-base-rdp:<version>-<sha>), so a layer change
# propagates through the whole tree in one pipeline run.
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

# Re-assert suid stripping (new packages may bring some back). Separate
# RUN: a trailing "|| true" on the dnf chain would mask install failures.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

# Session contract with the base entrypoint: WAAS_STARTUP replaces the
# openbox fallback. dbus-launch is prepended by waas-session.
ENV WAAS_STARTUP=startxfce4

USER 1000:1000
