#!/bin/sh
# build_image.sh — build, smoke-test, scan and push ONE image for ONE
# architecture, natively on a runner of that arch (runner tags amd/arm —
# no QEMU anywhere). ci/merge_image.sh then assembles the arch tags into
# the final manifest list. Driven by IMG_* / SMOKE_* variables emitted
# by ci/generate_pipeline.py.
#
# Flow: native build (--load) -> smoke test against a real container ->
# trivy gate -> push of the arch tag <version>-g<sha>-<arch>. Nothing
# reaches the registry (cache aside) before the smoke and scan gates.
set -eu

: "${IMG_NAME:?}" "${IMG_CONTEXT:?}" "${IMG_VERSION:?}" "${IMG_ARCH:?}"
REGISTRY="${CI_REGISTRY_IMAGE:?}"
ARCH="${IMG_ARCH#linux/}"
SHA_TAG="${IMG_VERSION}-g${CI_COMMIT_SHORT_SHA:?}"
ARCH_TAG="${SHA_TAG}-${ARCH}"
IMAGE="${REGISTRY}/${IMG_NAME}"
CACHE_REF="${REGISTRY}/cache:${IMG_NAME}-${ARCH}"

log() { printf '\n=== %s\n' "$*"; }

# ---------------------------------------------------------------- setup
log "docker login + buildx builder"
docker login -u "${CI_REGISTRY_USER}" -p "${CI_REGISTRY_PASSWORD}" "${CI_REGISTRY}"
# Container driver: required for the registry cache export. BuildKit
# pinned; renovate keeps it fresh. Reuse an existing builder (no-op on
# fresh CI runners; lets a local run pre-provision one, e.g. with
# host networking against a local registry).
docker buildx inspect waas >/dev/null 2>&1 || \
    docker buildx create --name waas \
        --driver-opt image=moby/buildkit:v0.21.0 >/dev/null
docker buildx use waas

# QEMU fallback: when this job lands on a runner of another arch (the
# generator routes everything to the amd fleet when
# WAAS_IMAGES_BUILD_STRATEGY=qemu), install the binfmt handlers and
# build emulated. Nominal case is native — this block is a no-op.
RUNNER_ARCH=$(uname -m)
case "${RUNNER_ARCH}" in
    x86_64) RUNNER_ARCH=amd64 ;;
    aarch64) RUNNER_ARCH=arm64 ;;
esac
if [ "${ARCH}" != "${RUNNER_ARCH}" ]; then
    log "non-native build (${RUNNER_ARCH} runner -> ${ARCH}): installing QEMU binfmt"
    docker run --privileged --rm tonistiigi/binfmt:qemu-v9.2.2 --install all >/dev/null
fi

BUILD_ARG_FLAGS=""
for kv in ${IMG_BUILD_ARGS:-}; do
    BUILD_ARG_FLAGS="${BUILD_ARG_FLAGS} --build-arg ${kv}"
done
# recipe: images build from Dockerfile.generated (materialised by
# ci/recipe_compiler.py in the generate stage, delivered as an artifact).
DOCKERFILE_FLAG=""
if [ -n "${IMG_DOCKERFILE:-}" ]; then
    [ -f "${IMG_CONTEXT}/${IMG_DOCKERFILE}" ] \
        || { echo "FATAL: ${IMG_CONTEXT}/${IMG_DOCKERFILE} missing — generate-pipeline artifacts not downloaded?"; exit 1; }
    DOCKERFILE_FLAG="-f ${IMG_CONTEXT}/${IMG_DOCKERFILE}"
fi
# Derived images consume the parent's SAME-ARCH tag pushed earlier in
# this very pipeline (IMG_FROM_REF is "<name>:<version>"; the same-commit
# sha suffix pins it).
if [ -n "${IMG_FROM_REF:-}" ]; then
    BUILD_ARG_FLAGS="${BUILD_ARG_FLAGS} --build-arg BASE_IMAGE=${REGISTRY}/${IMG_FROM_REF}-g${CI_COMMIT_SHORT_SHA}-${ARCH}"
fi

# ---------------------------------------------------------------- build
# OCI labels on every image (classification/catalog metadata; the merge
# job re-asserts the same keys as index annotations, which per-arch
# config labels do not propagate to). Applied here, NOT per Dockerfile,
# so hand-written, recipe-generated and future images all carry them.
# `source` reflects the forge that actually ran this build
# (CI_PROJECT_URL, exported by the GitHub workflow): revision/created
# describe THIS build, so pointing `source` at a forge that did not
# produce the artifact would mislead provenance tooling.
CREATED=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# One flag set for both invocations below: the artifact pushed after the
# gates must be byte-identical (same config, cache-hot layers) to the
# one that was smoked and scanned.
buildx_build() {
    # shellcheck disable=SC2086
    docker buildx build \
        --platform "${IMG_ARCH}" \
        --provenance=false \
        --cache-from "type=registry,ref=${CACHE_REF}" \
        ${BUILD_ARG_FLAGS} \
        ${DOCKERFILE_FLAG} \
        --label "org.opencontainers.image.title=${IMG_NAME}" \
        --label "org.opencontainers.image.description=${IMG_DESCRIPTION:-}" \
        --label "org.opencontainers.image.version=${IMG_VERSION}" \
        --label "org.opencontainers.image.revision=${CI_COMMIT_SHA:-}" \
        --label "org.opencontainers.image.created=${CREATED}" \
        --label "org.opencontainers.image.source=${CI_PROJECT_URL:-}" \
        --label "org.opencontainers.image.licenses=Apache-2.0" \
        --label "org.opencontainers.image.vendor=XorHub" \
        --label "io.xorhub.waas.os=${IMG_OS:-}" \
        --label "io.xorhub.waas.layer=${IMG_LAYER:-}" \
        --label "io.xorhub.waas.profile=${IMG_PROFILE:-standard}" \
        --label "io.xorhub.waas.parent=${IMG_FROM_REF:-}" \
        -t "${IMAGE}:${ARCH_TAG}" \
        "$@" \
        "${IMG_CONTEXT}"
}

log "build (${IMG_ARCH}) ${IMAGE}:${ARCH_TAG}"
buildx_build --load --cache-to "type=registry,ref=${CACHE_REF},mode=max"

# ---------------------------------------------------------------- smoke
log "smoke test"
SMOKE_IMAGE="${IMAGE}:${ARCH_TAG}" sh ci/smoke_test.sh

# ----------------------------------------------------------------- scan
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

log "trivy scan (gate: ${TRIVY_SEVERITY:-HIGH,CRITICAL})"
# shellcheck disable=SC2086
docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v trivy-cache:/root/.cache/trivy \
    ${TRIVY_MOUNT_FLAGS} \
    aquasec/trivy:0.72.0 image \
    --severity "${TRIVY_SEVERITY:-HIGH,CRITICAL}" \
    --ignore-unfixed="${TRIVY_IGNORE_UNFIXED:-true}" \
    --exit-code "${TRIVY_EXIT_CODE:-1}" \
    --scanners vuln,secret \
    ${TRIVY_IGNOREFILE_FLAG} \
    "${IMAGE}:${ARCH_TAG}"

# ----------------------------------------------------------------- push
# Re-run the SAME build (cache-hot: no layer work) with a registry
# output in OCI mediatypes, instead of `docker push`: the engine pushes
# Docker mediatypes, and a Docker manifest LIST cannot carry the index
# annotations merge_image.sh sets (buildx drops them silently — verified
# live). Gates stay ahead of the registry: this runs only after smoke
# and trivy passed on the --load'ed image.
log "push ${IMAGE}:${ARCH_TAG} (OCI mediatypes)"
buildx_build --output type=registry,oci-mediatypes=true
