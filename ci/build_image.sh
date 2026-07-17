#!/bin/sh
# build_image.sh — build, smoke-test and push ONE image for ONE
# architecture, natively on a runner of that arch (runner tags amd/arm —
# no QEMU anywhere). ci/merge_image.sh then assembles the arch tags into
# the final manifest list. Driven by IMG_* / SMOKE_* variables emitted
# by ci/generate_pipeline.py.
#
# Flow: native build (--load) -> smoke test against a real container ->
# push of the arch tag <version>-g<sha>-<arch>. Trivy (ci/scan_image.sh)
# and the SBOM (ci/sbom_image.sh) run as separate jobs against this
# pushed tag, deliberately NOT in this script and NOT in merge/catalog's
# `needs:` — a scan finding must stay visible (that job still fails
# red) without blocking the push: the catalog job gates on every
# layer/merge job succeeding, so a HIGH CVE in ONE image (e.g. a
# node_modules blob bundled by a third-party .deb) used to silently
# block catalog regeneration for every other image in the same run too.
#
# Everything here — the per-arch tag, the build cache, a derived
# image's BASE_IMAGE parent — stays on CI_REGISTRY_IMAGE (GHCR):
# CI-internal, never consumed externally, no pull limit and
# GITHUB_TOKEN can push/pull it without a PAT. CI_PUBLIC_REGISTRY
# (Docker Hub) is logged into too, but ONLY so the OS base image pulls
# below (ubuntu/debian/fedora, docker.io/library/*) are authenticated
# against its 200-pulls/6h budget instead of the anonymous pool shared
# by every GitHub-hosted runner on the planet — this script never
# pushes there. ci/merge_image.sh mirrors the finished <version>
# manifest list to Docker Hub once, after assembly.
set -eu

: "${IMG_NAME:?}" "${IMG_CONTEXT:?}" "${IMG_VERSION:?}" "${IMG_ARCH:?}"
: "${CI_PUBLIC_REGISTRY:?}" "${CI_PUBLIC_REGISTRY_USER:?}" "${CI_PUBLIC_REGISTRY_PASSWORD:?}"
REGISTRY="${CI_REGISTRY_IMAGE:?}"
ARCH="${IMG_ARCH#linux/}"
SHA_TAG="${IMG_VERSION}-g${CI_COMMIT_SHORT_SHA:?}"
ARCH_TAG="${SHA_TAG}-${ARCH}"
IMAGE="${REGISTRY}/${IMG_NAME}"

log() { printf '\n=== %s\n' "$*"; }

# ---------------------------------------------------------------- setup
log "docker login + buildx builder"
docker login -u "${CI_REGISTRY_USER}" -p "${CI_REGISTRY_PASSWORD}" "${CI_REGISTRY}"
docker login -u "${CI_PUBLIC_REGISTRY_USER}" -p "${CI_PUBLIC_REGISTRY_PASSWORD}" "${CI_PUBLIC_REGISTRY}"
# Container driver: required for the GHA cache export (unsupported by
# the default docker driver). BuildKit pinned; renovate keeps it fresh.
# Reuse an existing builder (no-op on fresh CI runners; lets a local
# run pre-provision one, e.g. with host networking against a local
# registry).
docker buildx inspect waas >/dev/null 2>&1 || \
    docker buildx create --name waas \
        --driver-opt image=moby/buildkit:v0.31.2 >/dev/null
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
# gate must be byte-identical (same config, cache-hot layers) to the
# one that was smoke-tested.
buildx_build() {
    # shellcheck disable=SC2086
    docker buildx build \
        --platform "${IMG_ARCH}" \
        --provenance=false \
        --cache-from "type=gha,scope=${IMG_NAME}-${ARCH}" \
        ${BUILD_ARG_FLAGS} \
        ${DOCKERFILE_FLAG} \
        --label "org.opencontainers.image.title=${IMG_NAME}" \
        --label "org.opencontainers.image.description=${IMG_DESCRIPTION:-}" \
        --label "org.opencontainers.image.version=${IMG_VERSION}" \
        --label "org.opencontainers.image.revision=${CI_COMMIT_SHA:-}" \
        --label "org.opencontainers.image.created=${CREATED}" \
        --label "org.opencontainers.image.source=${CI_PROJECT_URL:-}" \
        --label "org.opencontainers.image.documentation=${IMG_DOCUMENTATION:-}" \
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
buildx_build --load --cache-to "type=gha,scope=${IMG_NAME}-${ARCH},mode=max"

# ---------------------------------------------------------------- smoke
log "smoke test"
SMOKE_IMAGE="${IMAGE}:${ARCH_TAG}" sh ci/smoke_test.sh

# ----------------------------------------------------------------- push
# Re-run the SAME build (cache-hot: no layer work) with a registry
# output in OCI mediatypes, instead of `docker push`: the engine pushes
# Docker mediatypes, and a Docker manifest LIST cannot carry the index
# annotations merge_image.sh sets (buildx drops them silently — verified
# live). Gates stay ahead of the registry: this runs only after smoke
# passed on the --load'ed image (trivy/SBOM run downstream, see header).
log "push ${IMAGE}:${ARCH_TAG} (OCI mediatypes)"
buildx_build --output type=registry,oci-mediatypes=true
