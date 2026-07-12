# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
# waas dev-ssh — terminal-first development environment: the base headless
# session (VNC available for graphical needs) plus a hardened, fully
# non-root OpenSSH server for guacd's native "ssh" protocol.
#
# sshd runs as UID 1000, like everything else in the image:
#   - listens on 2222 (unprivileged bind);
#   - host keys are generated at boot into the runtime dir (or provided
#     via WAAS_SSH_HOST_KEY from a Secret for a stable identity);
#   - public-key auth only. Password auth is impossible by construction:
#     an unprivileged sshd cannot read /etc/shadow — a stolen desktop
#     password therefore never grants shell access.
#   - authorized keys are injected at runtime (WAAS_SSH_AUTHORIZED_KEYS
#     env or a mounted Secret file) — never baked into the image.
ARG BASE_IMAGE
# hadolint ignore=DL3006
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
USER 0

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openssh-server \
        openssh-client \
        git \
        tmux \
        vim \
        less \
        curl \
        jq \
        build-essential \
        python3 \
        python3-venv \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/* && \
    # openssh-server's postinst generates host keys at install time; drop
    # them so the image carries none — they are (re)generated at boot into
    # the runtime dir per the header comment above, and baked keys trip
    # trivy's secret scanner (HIGH: AsymmetricPrivateKey) for no benefit.
    rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub && \
    # sshd refuses to start without its privilege-separation directory,
    # even when running unprivileged.
    mkdir -p /run/sshd

# Re-assert suid stripping (openssh-server ships ssh-keysign setuid).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

COPY rootfs/ /

# Runtime contract: port 2222 = SSH (guacd protocol "ssh").
EXPOSE 2222

ENV WAAS_SSH_ENABLED=1 \
    WAAS_SSH_PORT=2222

USER 1000:1000
