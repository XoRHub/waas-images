# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# waas ubuntu-xfce — lightweight full desktop on top of the base image.
#
# BASE_IMAGE is injected by CI as the exact ref built earlier in the same
# pipeline — registry/ubuntu-base-rdp:<version>-<sha> (ubuntu-xfce),
# registry/debian-base-rdp:<version>-<sha> (debian-xfce), or
# registry/ubuntu-base-vnc:<version>-<sha> (ubuntu-desktop, the VNC-only
# apps/* parent) — so a layer change propagates through the whole tree
# in one pipeline run.
ARG BASE_IMAGE
# hadolint ignore=DL3006
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER 0

# Bake an unprivileged, publickey-only sshd into this image (1) or ship
# without one at all (0, default). Decoupled from WAAS_SSH_ENABLED below:
# unlike RDP, there is no auto-generated fallback credential for SSH, so
# even a variant built with INSTALL_SSH=1 must default to SSH disabled
# at runtime (see rootfs/etc/waas/entrypoint.d/50-sshd.sh).
ARG INSTALL_SSH=0

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
    && if [ "${INSTALL_SSH}" = "1" ]; then \
        apt-get install -y --no-install-recommends openssh-server && \
        # openssh-server's postinst bakes host keys; drop them so the
        # image carries none — 50-sshd.sh (re)generates them at boot (or
        # takes a mounted WAAS_SSH_HOST_KEY_FILE), and baked keys trip
        # trivy's secret scanner (HIGH: AsymmetricPrivateKey) for no
        # benefit (same rationale as apps/dev-ssh/Dockerfile).
        rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub && \
        # sshd refuses to start without its privilege-separation directory.
        mkdir -p /run/sshd; \
    fi && \
    apt-get purge -y --auto-remove xterm && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/*

# Re-assert suid stripping (new packages may bring some back, e.g.
# openssh-server ships ssh-keysign setuid).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

COPY rootfs/ /

# The SSH entrypoint hook only makes sense when sshd is actually
# installed — delete it otherwise so the capability is structurally
# absent (not just disabled) on any variant built with INSTALL_SSH
# unset, e.g. the VNC-only ubuntu-desktop apps parent.
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
