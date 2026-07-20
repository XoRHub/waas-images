#!/bin/sh
# smoke_test.sh — prove the image actually serves its protocols.
#
# The container is deliberately run the hard way — read-only rootfs,
# every capability dropped, no-new-privileges, tmpfs home — so the
# hardening contract is enforced by CI, not just documented. If someone
# adds a service that needs to write outside /tmp|/run|$HOME, this fails.
# A suid sweep asserts "no setuid/setgid binaries" (standard profile) or
# "exactly sudo" (SMOKE_PROFILE=dev, reduced-hardening images).
#
# Checks (retried, because published ports accept connections before the
# in-container service is up — docker-proxy answers first):
#   VNC: read the RFB banner ("RFB 003.008") from port 5901.
#   RDP: send an X.224 Connection Request, expect a TPKT (0x03) reply.
#   SSH: read the protocol banner ("SSH-2.0-...") from port 2222.
#   AUDIO: pactl (in-container) against the PulseAudio TCP module — the
#          native protocol has no server-first banner to read from outside.
#
# Plus one non-protocol gate, run only on images that ship it: mise must
# be wired BOTH ways — shims on PATH (non-interactive contexts) and
# `mise activate` in an interactive bash. See the block below.
set -eu

: "${SMOKE_IMAGE:?}"
HOST="${SMOKE_HOST:-localhost}"   # Kubernetes executor: pod-shared netns with the dind service
NAME="smoke-$$"

# SMOKE_PROFILE=dev (generator: manifest variant with profile: dev): the
# image ships sudo, so the container mirrors the relaxed pod profile its
# WorkspaceTemplate must set — no --read-only, no no-new-privileges, and
# the RUNTIME DEFAULT capability set instead of --cap-drop ALL: a setuid
# binary regains capabilities only within the bounding set, so an
# ALL-dropped pod keeps sudo dead even with privilege escalation allowed
# (verified live: 'unable to change to root gid'). The suid gate below
# expects EXACTLY /usr/bin/sudo, and sudo is exercised for real.
PROFILE="${SMOKE_PROFILE:-standard}"
if [ "${PROFILE}" = "dev" ]; then
    HARDEN_FLAGS=""
else
    HARDEN_FLAGS="--read-only --cap-drop ALL --security-opt no-new-privileges"
fi

ENV_FLAGS="-e WAAS_DESKTOP_PASSWORD=smoketest-$$"
for kv in ${SMOKE_ENV:-}; do
    ENV_FLAGS="${ENV_FLAGS} -e ${kv}"
done

cleanup() {
    docker logs "${NAME}" 2>&1 | tail -n 40 || true
    docker rm -f "${NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# shellcheck disable=SC2086
docker run -d --name "${NAME}" \
    ${HARDEN_FLAGS} \
    --tmpfs /tmp \
    --tmpfs /run \
    --tmpfs /home/waas_user:mode=1777 \
    -p 15901:5901 -p 13389:3389 -p 12222:2222 \
    ${ENV_FLAGS} \
    "${SMOKE_IMAGE}" >/dev/null

# Setuid/setgid gate — the HARDENING.md "No setuid/setgid binaries"
# checklist item, enforced (it used to rely on Dockerfile discipline
# alone). Runs before the protocol probes: it needs the container, not
# the services.
SUID_FOUND=$(docker exec "${NAME}" find / -xdev -perm /6000 -type f 2>/dev/null | sort | tr '\n' ' ' || true)
if [ "${PROFILE}" = "dev" ]; then
    if [ "${SUID_FOUND}" != "/usr/bin/sudo " ]; then
        echo "FAIL: dev profile must ship exactly /usr/bin/sudo setuid, got: '${SUID_FOUND}'"
        exit 1
    fi
    echo "OK: suid set is exactly /usr/bin/sudo (dev profile)"
    # The variant's whole point: prove sudo actually grants root under
    # the relaxed profile (NOPASSWD sudoers baked at build).
    docker exec "${NAME}" sudo -n true \
        || { echo "FAIL: sudo -n true failed in the dev-profile container"; exit 1; }
    echo "OK: sudo works (dev profile)"
else
    if [ -n "${SUID_FOUND}" ]; then
        echo "FAIL: setuid/setgid binaries found: ${SUID_FOUND}"
        exit 1
    fi
    echo "OK: no setuid/setgid binaries"
fi

# mise wiring gate — self-gating on the binary being present, so images
# without mise skip it silently. Deliberately NOT a new SMOKE_* key: that
# contract is a fixed list in ci/generate_pipeline.py mirrored three times
# in build.yml, i.e. a four-file change for one boolean.
#
# The build already asserts mise EXISTS (`mise --version` in the RUN). What
# it cannot see is the wiring, which is the fragile half — and there are
# two of them, covering different contexts:
#   shims on PATH  — the only mechanism that works non-interactively.
#   mise activate  — interactive shells only (prompt hook), but richer.
# Note this runs against the tmpfs home, i.e. the empty-PVC first boot.
if docker exec "${NAME}" sh -c 'command -v mise' >/dev/null 2>&1; then
    docker exec "${NAME}" sh -c 'case ":$PATH:" in *":$HOME/.local/share/mise/shims:"*) exit 0 ;; *) exit 1 ;; esac' \
        || { echo "FAIL: mise is installed but its shims dir is not on PATH"; exit 1; }
    # declare -f, not command -v: the binary in /usr/local/bin would
    # satisfy command -v without activation ever having run, proving
    # nothing. The shell FUNCTION only exists if activate was sourced.
    docker exec "${NAME}" bash -ic 'declare -f mise >/dev/null' \
        || { echo "FAIL: mise is not activated in an interactive shell"; exit 1; }
    echo "OK: mise shims on PATH and activated in interactive bash"
fi

# retry "<label>" <fn>: run <fn> up to 60 times, 2s apart, failing early
# if the container died. The probe itself is the readiness check.
retry() {
    label="$1"; shift
    i=0
    while [ $i -lt 60 ]; do
        if "$@"; then return 0; fi
        [ "$(docker inspect -f '{{.State.Running}}' "${NAME}")" = "true" ] \
            || { echo "FAIL: container exited during ${label} check"; return 1; }
        i=$((i + 1)); sleep 2
    done
    echo "FAIL: ${label} not answering after 120s"
    return 1
}

probe_vnc() {
    BANNER=$(nc -w 5 "${HOST}" 15901 </dev/null 2>/dev/null | dd bs=1 count=12 2>/dev/null || true)
    case "${BANNER}" in "RFB "*) return 0 ;; *) return 1 ;; esac
}

probe_rdp() {
    # TPKT + X.224 CR + RDP negotiation request (TLS|RDP security).
    REPLY=$(printf '\003\000\000\023\016\340\000\000\000\000\000\001\000\010\000\013\000\000\000' \
        | nc -w 5 "${HOST}" 13389 2>/dev/null | dd bs=1 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')
    [ "${REPLY}" = "03" ]
}

if [ "${SMOKE_VNC:-0}" = "1" ]; then
    retry "VNC" probe_vnc
    echo "OK: VNC answered with '${BANNER}'"
fi

if [ "${SMOKE_RDP:-0}" = "1" ]; then
    retry "RDP" probe_rdp
    echo "OK: RDP answered with a TPKT header"
fi

probe_ssh() {
    SSH_BANNER=$(nc -w 5 "${HOST}" 12222 </dev/null 2>/dev/null | dd bs=1 count=8 2>/dev/null || true)
    case "${SSH_BANNER}" in "SSH-2.0"*) return 0 ;; *) return 1 ;; esac
}

if [ "${SMOKE_SSH:-0}" = "1" ]; then
    retry "SSH" probe_ssh
    echo "OK: SSH answered with '${SSH_BANNER}'"
fi

probe_audio() {
    # A real native-protocol handshake against the TCP module, exercising
    # the same path guacd uses (out of scope: guacd itself / audio data).
    docker exec "${NAME}" pactl --server tcp:127.0.0.1:4713 info >/dev/null 2>&1
}

if [ "${SMOKE_AUDIO:-0}" = "1" ]; then
    retry "AUDIO" probe_audio
    echo "OK: PulseAudio answered on tcp:4713"
fi

echo "smoke test passed for ${SMOKE_IMAGE}"
