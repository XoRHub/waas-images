#!/bin/sh
# scan_image.sh — trivy vulnerability scan of the per-arch tag
# ci/build_image.sh already pushed. Deliberately its own job (see that
# script's header): a finding must stay VISIBLE — this job still exits
# non-zero and shows red — without blocking the push/merge/catalog
# pipeline, which never lists this job in its `needs:`. Driven by IMG_*
# variables emitted by ci/generate_pipeline.py (same matrix as the
# layer-N build job it follows).
#
# TRIVY_SEVERITY / TRIVY_IGNORE_UNFIXED: sourced from images.yaml's
# scan: block, not chosen here — ci/generate_pipeline.py puts them in
# github-matrices.json's "scan" key, the workflow's setup job re-exposes
# them as outputs, and every scan-N job env-injects them before calling
# this script. The ${VAR:-default} fallbacks below only matter for a
# standalone/local invocation outside that pipeline. TRIVY_EXIT_CODE has
# no images.yaml equivalent — it stays a plain CI-variable override,
# there's no per-pipeline reason to change it.
set -eu

: "${IMG_NAME:?}" "${IMG_CONTEXT:?}" "${IMG_VERSION:?}" "${IMG_ARCH:?}"
REGISTRY="${CI_REGISTRY_IMAGE:?}"
ARCH="${IMG_ARCH#linux/}"
ARCH_TAG="${IMG_VERSION}-g${CI_COMMIT_SHORT_SHA:?}-${ARCH}"
IMAGE="${REGISTRY}/${IMG_NAME}:${ARCH_TAG}"

log() { printf '\n=== %s\n' "$*"; }

# Per-image exceptions: a "${IMG_CONTEXT}/.trivyignore", if present, is
# mounted in and passed via --ignorefile. Each entry must be a real,
# investigated false positive (documented inline in the file) — this is
# not a place to silence real findings.
TRIVY_MOUNT_FLAGS=""
TRIVY_IGNOREFILE_FLAG=""
if [ -f "${IMG_CONTEXT}/.trivyignore" ]; then
    TRIVY_MOUNT_FLAGS="-v $(pwd)/${IMG_CONTEXT}/.trivyignore:/.trivyignore:ro"
    TRIVY_IGNOREFILE_FLAG="--ignorefile /.trivyignore"
fi

log "trivy scan (gate: ${TRIVY_SEVERITY:-HIGH,CRITICAL}) ${IMAGE}"
# --username/--password: trivy pulls the image itself via its own
# registry client — no local docker daemon involved, this job never
# builds, it only ever reads the tag ci/build_image.sh already pushed.
# ghcr.io mirror, not aquasec/trivy (Docker Hub): this runs on EVERY
# matrix leg, so on docker.io it alone would burn ~30 of the
# 200-pulls/6h Docker Hub budget per full pipeline run. ghcr.io has no
# pull rate limit for public images.
# shellcheck disable=SC2086
docker run --rm \
    -v trivy-cache:/root/.cache/trivy \
    ${TRIVY_MOUNT_FLAGS} \
    ghcr.io/aquasecurity/trivy:0.72.0 image \
    --username "${CI_REGISTRY_USER}" --password "${CI_REGISTRY_PASSWORD}" \
    --severity "${TRIVY_SEVERITY:-HIGH,CRITICAL}" \
    --ignore-unfixed="${TRIVY_IGNORE_UNFIXED:-true}" \
    --exit-code "${TRIVY_EXIT_CODE:-1}" \
    --scanners vuln,secret \
    ${TRIVY_IGNOREFILE_FLAG} \
    "${IMAGE}"
