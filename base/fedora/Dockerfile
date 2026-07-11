# syntax=docker/dockerfile:1.7
#
# waas fedora base — headless graphical session, VNC always, RDP opt-in.
#
# dnf-based sibling of base/ubuntu/Dockerfile: same design (TigerVNC
# Xvnc as THE X server, xrdp libvnc bridge without sesman/PAM,
# unprivileged PulseAudio null sink on tcp:4713, tini + supervisord),
# same runtime contract, same rootfs scripts. The rootfs/ tree is a
# DELIBERATE COPY of base/ubuntu/rootfs (the build context is the image
# directory, so it cannot be shared); any change to one copy must be
# mirrored in the other — both are shellcheck-linted in CI.
#
# Package-name deltas vs the apt base (verified against Fedora 43, not
# assumed): TigerVNC is split three ways (tigervnc-x11-server = Xvnc,
# tigervnc-server-common = vncconfig, tigervnc-server-minimal =
# vncpasswd); xauth is xorg-x11-xauth; dbus-uuidgen lives in dbus-tools;
# x11-xserver-utils is exploded (only xrandr is actually used, by
# waas-resize); fonts are dejavu-sans-fonts + xorg-x11-fonts-misc.

ARG OS_BASE_IMAGE=fedora:43
# hadolint ignore=DL3006
FROM ${OS_BASE_IMAGE}

# Fixed, overridable identity. The home path follows WAAS_USER
# (/home/waas_user by default) and must match the operator's
# DefaultHomeMountPath (waas-fable), where the Workspace home PVC is
# mounted — the two repos change this value together.
ARG WAAS_USER=waas_user
ARG WAAS_UID=1000
ARG WAAS_GID=1000
# Bake xrdp into the image (1) or ship VNC-only (0). Runtime toggles
# (WAAS_VNC_ENABLED / WAAS_RDP_ENABLED) can only enable what is installed.
ARG INSTALL_RDP=0

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# install_weak_deps=False is dnf's --no-install-recommends.
# hadolint ignore=DL3041
RUN dnf install -y --setopt=install_weak_deps=False \
        tigervnc-x11-server \
        tigervnc-server-common \
        tigervnc-server-minimal \
        supervisor \
        tini \
        openbox \
        xterm \
        xorg-x11-xauth \
        xrandr \
        dbus-x11 \
        dbus-tools \
        pulseaudio \
        pulseaudio-utils \
        dejavu-sans-fonts \
        xorg-x11-fonts-misc \
        ca-certificates \
        openssl \
    && if [ "${INSTALL_RDP}" = "1" ]; then \
        dnf install -y --setopt=install_weak_deps=False xrdp && \
        # xrdp config + keys are rendered at runtime into the (writable)
        # runtime dir; symlink the hardcoded paths there so the rootfs can
        # stay read-only.
        rm -f /etc/xrdp/xrdp.ini /etc/xrdp/rsakeys.ini /etc/xrdp/cert.pem /etc/xrdp/key.pem && \
        ln -s /tmp/waas/xrdp/xrdp.ini    /etc/xrdp/xrdp.ini && \
        ln -s /tmp/waas/xrdp/rsakeys.ini /etc/xrdp/rsakeys.ini && \
        ln -s /tmp/waas/xrdp/cert.pem    /etc/xrdp/cert.pem && \
        ln -s /tmp/waas/xrdp/key.pem     /etc/xrdp/key.pem; \
    fi && \
    # dbus-launch (session bus) wants a machine id; bake one so it works
    # on a read-only rootfs. Identical across containers — acceptable, it
    # is not used as an identity by anything we run.
    dbus-uuidgen > /etc/machine-id && \
    dnf clean all && \
    rm -rf /var/cache/* /var/log/* && \
    # Fail the build (not the runtime) if a packaging change moves one of
    # the binaries the rootfs scripts invoke.
    command -v Xvnc vncconfig vncpasswd supervisord tini openbox xterm \
        xauth xrandr dbus-launch pulseaudio pactl openssl >/dev/null

# Non-root user with fixed UID/GID (no default UID-1000 squatter on
# Fedora images — verified; kept unconditional-safe anyway).
RUN if id -u 1000 >/dev/null 2>&1; then userdel -r "$(id -un 1000)"; fi && \
    groupadd -g "${WAAS_GID}" "${WAAS_USER}" && \
    # Home is /home/waas_user: the mount path the operator uses for the
    # persistent home PVC (DefaultHomeMountPath in waas-fable).
    useradd -l -m -u "${WAAS_UID}" -g "${WAAS_GID}" -d /home/waas_user -s /bin/bash "${WAAS_USER}"

# Drop every setuid/setgid bit: nothing we run needs privilege escalation,
# and this neutralises su/passwd/chfn/... even if a shell is reached.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

COPY rootfs/ /

RUN chmod 0755 /usr/local/bin/waas-entrypoint /usr/local/bin/waas-session /usr/local/bin/waas-resize

# ---- Runtime contract (consumed by the Workspace operator) ----
# Port 5901: RFB/VNC (guacd protocol "vnc"). TCP-open == session ready.
# Port 3389: RDP via xrdp, only when INSTALL_RDP=1 and WAAS_RDP_ENABLED=1.
# Port 4713: PulseAudio native protocol for guacd's VNC audio stream,
#            unless WAAS_AUDIO_ENABLED=0.
EXPOSE 5901 3389 4713

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
    WAAS_AUDIO_ENABLED=1 \
    VNC_RESOLUTION=1920x1080 \
    VNC_COL_DEPTH=24 \
    WAAS_STARTUP=

USER ${WAAS_UID}:${WAAS_GID}
WORKDIR /home/waas_user

# tini is PID 1 (signal forwarding + zombie reaping); the entrypoint
# renders runtime config then execs supervisord in the foreground.
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/waas-entrypoint"]
