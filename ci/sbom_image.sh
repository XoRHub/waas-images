#!/bin/sh
# sbom_image.sh — generate a CycloneDX SBOM for the per-arch tag
# ci/build_image.sh already pushed, written to ./sbom.cdx.json for the
# workflow's upload-artifact step. Deliberately its own job (see
# ci/build_image.sh's header): must never block push/merge/catalog.
# Driven by IMG_* variables emitted by ci/generate_pipeline.py (same
# matrix as the layer-N build job it follows).
set -eu

: "${IMG_NAME:?}" "${IMG_VERSION:?}" "${IMG_ARCH:?}"
REGISTRY="${CI_REGISTRY_IMAGE:?}"
ARCH="${IMG_ARCH#linux/}"
ARCH_TAG="${IMG_VERSION}-g${CI_COMMIT_SHORT_SHA:?}-${ARCH}"
IMAGE="${REGISTRY}/${IMG_NAME}:${ARCH_TAG}"

log() { printf '\n=== %s\n' "$*"; }

log "trivy sbom (cyclonedx) ${IMAGE}"
# --username/--password: trivy pulls the image itself via its own
# registry client, same as ci/scan_image.sh — no local docker daemon
# involved.
docker run --rm \
    -v "$(pwd):/out" \
    -v trivy-cache:/root/.cache/trivy \
    ghcr.io/aquasecurity/trivy:0.72.0 image \
    --username "${CI_REGISTRY_USER}" --password "${CI_REGISTRY_PASSWORD}" \
    --format cyclonedx \
    --output /out/sbom.cdx.json \
    "${IMAGE}"
