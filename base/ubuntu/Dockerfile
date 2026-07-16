# syntax=docker/dockerfile:1.25@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12
#
# waas ubuntu base — headless graphical session, VNC always, RDP opt-in.
#
# Display server: TigerVNC's Xvnc. It IS the X server (no Xvfb + x11vnc
# double-buffering), supports RandR resize server-side, and speaks plain
# RFB 3.8 that guacd's libvncclient understands. KasmVNC was rejected
# because its transport is websocket-first and recent releases dropped the
# standard RFB compatibility guacd needs. Wayland headless was rejected
# because there is no mature RDP export path and wayvnc lacks the
# multi-client/auth features we get from TigerVNC for free.
#
# RDP: xrdp running WITHOUT sesman/PAM. xrdp's libvnc backend bridges the
# RDP client straight onto the local Xvnc session (password=ask forwards
# the RDP password as the VNC password). This keeps xrdp fully non-root
# (no PAM, no setuid) and means VNC and RDP always show the SAME session.
# Trade-off (documented in README): no chansrv on the RDP path, so RDP
# clipboard/audio are unavailable — VNC is the recommended protocol for
# Linux workspaces; RDP is a compatibility option.
#
# Audio: PulseAudio in plain user mode (no root, no setuid, no rtkit).
# Apps play into a null sink (no sound hardware in a pod) and guacd
# streams that sink's monitor by connecting to PulseAudio's native
# protocol on TCP 4713 (guacd VNC params enable-audio/audio-servername).
# The RDP path stays audio-less: xrdp audio needs chansrv (see below).
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
# Bake xrdp into the image (1) or ship VNC-only (0). Runtime toggles
# (WAAS_VNC_ENABLED / WAAS_RDP_ENABLED) can only enable what is installed.
ARG INSTALL_RDP=0
# Bake an unprivileged, publickey-only sshd into the image (1) or ship
# without one at all (0, default). Decoupled from WAAS_SSH_ENABLED below:
# unlike RDP, there is no auto-generated fallback credential for SSH, so
# even a variant built with INSTALL_SSH=1 must default to SSH disabled
# at runtime (see rootfs/etc/waas/entrypoint.d/50-sshd.sh).
ARG INSTALL_SSH=0

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
        ca-certificates \
        openssl \
    && if [ "${INSTALL_RDP}" = "1" ]; then \
        apt-get install -y --no-install-recommends xrdp && \
        # xrdp config + keys are rendered at runtime into the (writable)
        # runtime dir; symlink the hardcoded paths there so the rootfs can
        # stay read-only.
        rm -f /etc/xrdp/xrdp.ini /etc/xrdp/rsakeys.ini /etc/xrdp/cert.pem /etc/xrdp/key.pem && \
        ln -s /tmp/waas/xrdp/xrdp.ini    /etc/xrdp/xrdp.ini && \
        ln -s /tmp/waas/xrdp/rsakeys.ini /etc/xrdp/rsakeys.ini && \
        ln -s /tmp/waas/xrdp/cert.pem    /etc/xrdp/cert.pem && \
        ln -s /tmp/waas/xrdp/key.pem     /etc/xrdp/key.pem && \
        # xrdp pulls in ssl-cert, whose postinst bakes an unused snakeoil
        # keypair into the image; it trips trivy's secret scanner (HIGH:
        # AsymmetricPrivateKey) and nothing reads it since we symlink our
        # own cert/key above.
        rm -f /etc/ssl/private/ssl-cert-snakeoil.key /etc/ssl/certs/ssl-cert-snakeoil.pem; \
    fi && \
    if [ "${INSTALL_SSH}" = "1" ]; then \
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
# Port 3389: RDP via xrdp, only when INSTALL_RDP=1 and WAAS_RDP_ENABLED=1.
# Port 2222: SSH, only when INSTALL_SSH=1 and WAAS_SSH_ENABLED=1 — off by
#            default even when installed (see rootfs/etc/waas/
#            entrypoint.d/50-sshd.sh).
# Port 4713: PulseAudio native protocol for guacd's VNC audio stream,
#            unless WAAS_AUDIO_ENABLED=0.
EXPOSE 5901 3389 2222 4713

ENV WAAS_USER=${WAAS_USER} \
    HOME=/home/waas_user \
    DISPLAY=:1 \
    WAAS_RUNTIME_DIR=/tmp/waas \
    WAAS_VNC_ENABLED=1 \
    WAAS_RDP_ENABLED=${INSTALL_RDP} \
    # Secure by default: RDP clients must authenticate with the session
    # password. Only an explicit RDP_AUTH_ENABLED=false at runtime — never
    # a build — turns it off (see waas-entrypoint / README).
    RDP_AUTH_ENABLED=true \
    # Always off regardless of INSTALL_SSH — no auto-generated fallback
    # credential exists for SSH the way VNC_PW covers VNC/RDP, so a
    # template must opt in explicitly with WAAS_SSH_AUTHORIZED_KEYS(_FILE).
    WAAS_SSH_ENABLED=0 \
    WAAS_SSH_PORT=2222 \
    WAAS_AUDIO_ENABLED=1 \
    VNC_RESOLUTION=1920x1080 \
    VNC_COL_DEPTH=24 \
    WAAS_STARTUP=

USER ${WAAS_UID}:${WAAS_GID}
WORKDIR /home/waas_user

# tini is PID 1 (signal forwarding + zombie reaping); the entrypoint
# renders runtime config then execs supervisord in the foreground.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/waas-entrypoint"]
