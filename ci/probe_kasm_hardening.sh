#!/bin/sh
# probe_kasm_hardening.sh — empirically determine whether an upstream
# kasmweb/* image (we don't build it, no local manifest/HARDENING.md
# doctrine to derive a profile from statically) tolerates a hardened pod
# securityContext, the same way ci/smoke_test.sh already proves it for
# this repo's own images: actually run the container under those
# constraints and see if it survives, rather than trust what the
# upstream Dockerfile merely declares.
#
# An explicit `docker pull` runs first (progress on stderr — see below),
# then two sequential probes against the SAME image ref, best-effort by
# design (this is a scheduled/manual catalog job, never allowed to
# fail the whole run — ci/generate_kasm_catalog.py's probe_hardening()
# wraps this in a try/except regardless):
#
#   0. `docker pull` the ref up front. `docker run` would pull it
#      implicitly anyway, but silently — for a manual run against a
#      multi-GB desktop image that's indistinguishable from a hang.
#      Failure here (bad ref, network down) -> "unknown" immediately,
#      same as any other inconclusive probe.
#   1. Plain `docker run` (no hardening flags) — confirms the
#      documented Kasm baseline (non-root UID 1000). If the container
#      never comes up or isn't UID 1000, prints "unknown": no claim
#      about anything stronger is safe.
#   2. A second, separate run of the same ref with
#      --read-only --cap-drop ALL --security-opt no-new-privileges.
#      Kasm images use /home/kasm-user (not this repo's
#      /home/waas_user — verified against
#      kasmtech/workspaces-images:dockerfile-kasm-terminal/-firefox).
#      Still running after the wait -> "hardened". Exited/crash-looped
#      -> "normal".
#
# Only ever prints exactly one of: hardened | normal | unknown — to
# stdout, nothing else (docker pull's progress and every other message
# below is redirected to stderr to keep that contract, since
# ci/generate_kasm_catalog.py's probe_hardening() parses stdout
# verbatim). Always exits 0 (the verdict IS the output, not the exit
# code) so a single flaky image can never fail the catalog job; the
# caller treats anything other than "hardened"/"normal" as "couldn't
# determine" and omits profile/recommended for that entry.
set -u

IMAGE="${1:?usage: probe_kasm_hardening.sh <image-ref>}"
NAME="probe-$$"

cleanup() {
    docker rm -f "${NAME}" >/dev/null 2>&1 || true
}

wait_running() {
    # Poll up to ~30s for the container to reach Running; a container
    # that never starts (bad entrypoint, missing required env, pull
    # failure) is as inconclusive as one that starts and immediately
    # exits under hardening — both just mean "unknown"/"normal".
    i=0
    while [ $i -lt 15 ]; do
        [ "$(docker inspect -f '{{.State.Running}}' "${NAME}" 2>/dev/null)" = "true" ] && return 0
        i=$((i + 1)); sleep 2
    done
    return 1
}

# --- Probe 0: pull the ref up front, verbosely (stderr) ---
echo "pulling ${IMAGE} ..." >&2
if ! docker pull "${IMAGE}" >&2; then
    echo unknown
    exit 0
fi

# --- Probe 1: plain run, confirm UID 1000 ---
if ! docker run -d --name "${NAME}" "${IMAGE}" >/dev/null 2>&1; then
    echo unknown
    exit 0
fi

if ! wait_running; then
    cleanup
    echo unknown
    exit 0
fi

UID_SEEN=$(docker exec "${NAME}" id -u 2>/dev/null || true)
cleanup

if [ "${UID_SEEN}" != "1000" ]; then
    echo unknown
    exit 0
fi

# --- Probe 2: same ref, hardened flags ---
if ! docker run -d --name "${NAME}" \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp --tmpfs /run --tmpfs /home/kasm-user:mode=1777 \
    "${IMAGE}" >/dev/null 2>&1; then
    echo normal
    exit 0
fi

# Give it a beat past the "did it even start" check: a container that
# survives the same ~30s a working one needs to initialize, without
# exiting, is a reasonable proxy for "tolerates the hardened profile".
if wait_running && sleep 15 && [ "$(docker inspect -f '{{.State.Running}}' "${NAME}" 2>/dev/null)" = "true" ]; then
    cleanup
    echo hardened
else
    cleanup
    echo normal
fi
