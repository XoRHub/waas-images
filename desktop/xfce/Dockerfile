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

# Re-assert suid stripping (new packages may bring some back). Separate
# RUN: a trailing "|| true" on the apt chain would mask install failures.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

# Session contract with the base entrypoint: WAAS_STARTUP replaces the
# openbox fallback. dbus-launch is prepended by waas-session.
ENV WAAS_STARTUP=startxfce4

USER 1000:1000
