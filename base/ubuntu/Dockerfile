# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
#
# waas ubuntu base — headless graphical session over VNC.
#
# Display server: TigerVNC's Xvnc. It IS the X server (no Xvfb + x11vnc
# double-buffering), supports RandR resize server-side, and speaks plain
# RFB 3.8 that guacd's libvncclient understands. KasmVNC was rejected
# because its transport is websocket-first and recent releases dropped the
# standard RFB compatibility guacd needs. Wayland headless was rejected
# because wayvnc lacks the multi-client/auth features we get from TigerVNC
# for free.
#
# VNC is the ONLY remote-access protocol: the platform reaches a Linux
# workspace over VNC and nothing else (waas#117 — rdp is for Windows VMs,
# ssh was dropped), so no image built here installs xrdp or sshd, and
# there is no build arg to add them back.
#
# Audio: PulseAudio in plain user mode (no root, no setuid, no rtkit).
# Apps play into a null sink (no sound hardware in a pod) and guacd
# streams that sink's monitor by connecting to PulseAudio's native
# protocol on TCP 4713 (guacd VNC params enable-audio/audio-servername).
#
# Supervisor: tini (PID 1, zombie reaping) + supervisord. supervisord runs
# entirely unprivileged, restarts crashed services, and reads config
# fragments the entrypoint renders at runtime (s6-overlay wants to own
# /init as root for its full feature set; a hand-rolled script gives no
# restart/ordering semantics).

# Full base reference so one parameterized Dockerfile serves every
# apt-based OS in images.yaml's os: map (ubuntu-noble, debian-13, ...).
ARG OS_BASE_IMAGE=ubuntu:24.04
# hadolint ignore=DL3006
FROM ${OS_BASE_IMAGE}

# Fixed, overridable identity. The home path follows WAAS_USER
# (/home/waas_user by default) and must match the operator's
# DefaultHomeMountPath (waas), where the Workspace home PVC is
# mounted — the two repos change this value together.
ARG WAAS_USER=waas_user
ARG WAAS_UID=1000
ARG WAAS_GID=1000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tigervnc-standalone-server \
        tigervnc-tools \
        supervisor \
        tini \
        openbox \
        xterm \
        xauth \
        x11-xserver-utils \
        dbus-x11 \
        pulseaudio \
        pulseaudio-utils \
        fonts-dejavu-core \
        xfonts-base \
        ca-certificates && \
    # dbus-launch (session bus) wants a machine id; bake one so it works
    # on a read-only rootfs. Identical across containers — acceptable, it
    # is not used as an identity by anything we run.
    dbus-uuidgen > /etc/machine-id && \
    apt-get purge -y --auto-remove && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/* /var/log/*

# Non-root user with fixed UID/GID. Ubuntu 24.04 ships a default "ubuntu"
# user squatting UID 1000 — remove it first.
RUN if id ubuntu >/dev/null 2>&1; then userdel -r ubuntu; fi && \
    groupadd -g "${WAAS_GID}" "${WAAS_USER}" && \
    # Home is /home/waas_user: the mount path the operator uses for the
    # persistent home PVC (DefaultHomeMountPath in waas).
    useradd -l -m -u "${WAAS_UID}" -g "${WAAS_GID}" -d /home/waas_user -s /bin/bash "${WAAS_USER}"

# Drop every setuid/setgid bit: nothing we run needs privilege escalation,
# and this neutralises su/passwd/chfn/... even if a shell is reached.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

COPY rootfs/ /

RUN chmod 0755 /usr/local/bin/waas-entrypoint /usr/local/bin/waas-session /usr/local/bin/waas-resize

# ---- Runtime contract (consumed by the Workspace operator) ----
# Port 5901: RFB/VNC (guacd protocol "vnc"). TCP-open == session ready.
# Port 4713: PulseAudio native protocol for guacd's VNC audio stream,
#            unless WAAS_AUDIO_ENABLED=0.
EXPOSE 5901 4713

ENV WAAS_USER=${WAAS_USER} \
    HOME=/home/waas_user \
    DISPLAY=:1 \
    WAAS_RUNTIME_DIR=/tmp/waas \
    WAAS_AUDIO_ENABLED=1 \
    # WAAS_VNC_RESOLUTION / WAAS_VNC_COL_DEPTH deliberately have NO baked
    # ENV default: their defaults live in the entrypoint, because an
    # always-set WAAS_* value would defeat the legacy aliases
    # (VNC_RESOLUTION / VNC_COL_DEPTH — WAAS_* wins when both are set).
    WAAS_STARTUP= \
    WAAS_APP=

USER ${WAAS_UID}:${WAAS_GID}
WORKDIR /home/waas_user

# tini is PID 1 (signal forwarding + zombie reaping); the entrypoint
# renders runtime config then execs supervisord in the foreground.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/waas-entrypoint"]
