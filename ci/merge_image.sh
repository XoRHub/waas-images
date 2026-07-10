#!/bin/sh
# merge_image.sh — assemble the per-arch tags pushed by build_image.sh
# into the final manifest list <version>-g<sha>, publish the immutable
# <version> tag from the default branch, and cosign-sign the digest.
# Driven by IMG_* variables emitted by ci/generate_pipeline.py.
set -eu

: "${IMG_NAME:?}" "${IMG_VERSION:?}" "${IMG_ARCHS:?}"
REGISTRY="${CI_REGISTRY_IMAGE:?}"
SHA_TAG="${IMG_VERSION}-g${CI_COMMIT_SHORT_SHA:?}"
IMAGE="${REGISTRY}/${IMG_NAME}"

log() { printf '\n=== %s\n' "$*"; }

log "docker login"
docker login -u "${CI_REGISTRY_USER}" -p "${CI_REGISTRY_PASSWORD}" "${CI_REGISTRY}"

SOURCES=""
for arch in $(echo "${IMG_ARCHS}" | tr ',' ' '); do
    SOURCES="${SOURCES} ${IMAGE}:${SHA_TAG}-${arch#linux/}"
done

# Immutable tags: <version>-g<sha> is always unique and pushed from every
# branch. The clean <version> tag is published from the default branch
# only, once, and never moved (ArgoCD/templates pin it, or better, the
# digest).
TAG_FLAGS="-t ${IMAGE}:${SHA_TAG}"
if [ "${CI_COMMIT_BRANCH:-}" = "${CI_DEFAULT_BRANCH:-main}" ]; then
    if docker buildx imagetools inspect "${IMAGE}:${IMG_VERSION}" >/dev/null 2>&1; then
        log "WARNING: ${IMG_NAME}:${IMG_VERSION} already published — bump 'version' in the manifest; pushing only ${SHA_TAG}"
    else
        TAG_FLAGS="${TAG_FLAGS} -t ${IMAGE}:${IMG_VERSION}"
    fi
fi

# Index annotations: the per-arch config labels set by build_image.sh do
# NOT propagate to the manifest list created here — re-assert the same
# OCI keys on the index itself ("index:" prefix, buildx >= 0.12) so
# registry/catalog tooling reads them without pulling an arch image.
ANNOTATION_FLAGS=""
annotate() {
    [ -n "$2" ] || return 0
    ANNOTATION_FLAGS="${ANNOTATION_FLAGS} --annotation \"index:$1=$2\""
}
annotate org.opencontainers.image.title       "${IMG_NAME}"
annotate org.opencontainers.image.description "${IMG_DESCRIPTION:-}"
annotate org.opencontainers.image.version     "${IMG_VERSION}"
annotate org.opencontainers.image.revision    "${CI_COMMIT_SHA:-}"
annotate org.opencontainers.image.created     "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
annotate org.opencontainers.image.source      "${CI_PROJECT_URL:-}"
annotate org.opencontainers.image.licenses    "Apache-2.0"
annotate org.opencontainers.image.vendor      "XorHub"
annotate io.xorhub.waas.os                    "${IMG_OS:-}"
annotate io.xorhub.waas.layer                 "${IMG_LAYER:-}"
annotate io.xorhub.waas.profile               "${IMG_PROFILE:-standard}"
annotate io.xorhub.waas.parent                "${IMG_FROM_REF:-}"

log "manifest list ${IMAGE}:${SHA_TAG} <-${SOURCES}"
# eval: ANNOTATION_FLAGS carries values with spaces (description) that
# plain word-splitting would tear apart.
eval "docker buildx imagetools create ${TAG_FLAGS} ${ANNOTATION_FLAGS} ${SOURCES}"

DIGEST=$(docker buildx imagetools inspect "${IMAGE}:${SHA_TAG}" --format '{{.Manifest.Digest}}')
log "published ${IMAGE}@${DIGEST}"

# ----------------------------------------------------------------- sign
# Two modes, both default-branch only (branch tags are throwaway):
#   keyed   — COSIGN_PRIVATE_KEY (+ COSIGN_PASSWORD) as masked CI
#             variables; the GitLab setup.
#   keyless — COSIGN_KEYLESS=1 (set by the GitHub workflow, which also
#             declares permissions id-token: write): OIDC identity
#             certificate via the ambient ACTIONS_ID_TOKEN_REQUEST_*
#             env. A verifying policy-controller must check the
#             certificate identity on GitHub-signed images and the
#             public key on GitLab-signed ones while both coexist.
# Skipped when neither is configured.
if [ "${CI_COMMIT_BRANCH:-}" = "${CI_DEFAULT_BRANCH:-main}" ]; then
    if [ -n "${COSIGN_PRIVATE_KEY:-}" ]; then
        log "cosign sign (key)"
        # Registry auth via flags: the job's ~/.docker is not visible to a
        # container started on the dind daemon, so mounting it cannot work.
        docker run --rm -e COSIGN_PRIVATE_KEY -e COSIGN_PASSWORD \
            ghcr.io/sigstore/cosign/cosign:v2.5.0 sign --yes \
            --key env://COSIGN_PRIVATE_KEY \
            --registry-username "${CI_REGISTRY_USER}" \
            --registry-password "${CI_REGISTRY_PASSWORD}" \
            -a revision="${CI_COMMIT_SHA}" \
            "${IMAGE}@${DIGEST}"
    elif [ "${COSIGN_KEYLESS:-0}" = "1" ]; then
        log "cosign sign (keyless OIDC)"
        docker run --rm \
            -e ACTIONS_ID_TOKEN_REQUEST_TOKEN -e ACTIONS_ID_TOKEN_REQUEST_URL \
            ghcr.io/sigstore/cosign/cosign:v2.5.0 sign --yes \
            --registry-username "${CI_REGISTRY_USER}" \
            --registry-password "${CI_REGISTRY_PASSWORD}" \
            -a revision="${CI_COMMIT_SHA}" \
            "${IMAGE}@${DIGEST}"
    fi
fi
