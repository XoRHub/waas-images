# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
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

# Bake an unprivileged, publickey-only sshd into this image (1) or ship
# without one at all (0, default) — same opt-in-but-off-by-default
# contract as desktop/xfce/Dockerfile; see rootfs/etc/waas/entrypoint.d/
# 50-sshd.sh.
ARG INSTALL_SSH=0

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
    && if [ "${INSTALL_SSH}" = "1" ]; then \
        dnf install -y --setopt=install_weak_deps=False openssh-server && \
        # openssh-server's postinst bakes host keys; drop them so the
        # image carries none — 50-sshd.sh (re)generates them at boot (or
        # takes a mounted WAAS_SSH_HOST_KEY_FILE), and baked keys trip
        # trivy's secret scanner (HIGH: AsymmetricPrivateKey) for no
        # benefit (same rationale as apps/dev-ssh/Dockerfile).
        rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub && \
        # sshd refuses to start without its privilege-separation directory.
        mkdir -p /run/sshd; \
    fi && \
    dnf remove -y xterm && \
    dnf clean all && \
    rm -rf /var/cache/* /var/log/*

# Re-assert suid stripping (new packages may bring some back). Separate
# RUN: a trailing "|| true" on the dnf chain would mask install failures.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

COPY rootfs/ /

# The SSH entrypoint hook only makes sense when sshd is actually
# installed — delete it otherwise so the capability is structurally
# absent (not just disabled) on any variant built with INSTALL_SSH unset.
RUN if [ "${INSTALL_SSH}" != "1" ]; then rm -f /etc/waas/entrypoint.d/50-sshd.sh; fi

# Session contract with the base entrypoint: WAAS_STARTUP replaces the
# openbox fallback. dbus-launch is prepended by waas-session.
ENV WAAS_STARTUP=startxfce4 \
    WAAS_SSH_ENABLED=0 \
    WAAS_SSH_PORT=2222

# Runtime contract: port 2222 = SSH (guacd protocol "ssh"), reachable
# only on variants built with INSTALL_SSH=1 AND booted with
# WAAS_SSH_ENABLED=1 — off by default even when installed, since there
# is no auto-generated fallback credential the way VNC_PW has one.
EXPOSE 2222

USER 1000:1000
