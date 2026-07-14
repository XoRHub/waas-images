#!/bin/sh
# merge_image.sh — assemble the per-arch tags pushed by build_image.sh
# into the final manifest list <version>-g<sha> on GHCR (CI-internal:
# same-registry assembly, sources and destination both on
# CI_REGISTRY_IMAGE — combining `buildx imagetools create` sources
# across DIFFERENT registries is unreliable, docker/buildx#1660 reports
# 400s). <version>-g<sha> is throwaway CI/traceability, never consumed
# externally, so it stays GHCR-only.
#
# On the default branch, when a NEW <version> is published (or when
# FORCE_MIRROR=1 asks to backfill an already-published one — see
# below), mirror it to the public Docker Hub registry (single-source
# registry copy — the pattern Docker's own docs demonstrate for
# cross-registry copies, unlike the multi-source combine above),
# cosign-sign that public copy, and best-effort attach a CycloneDX SBOM
# attestation to it too (see the sbom+attest section below) — nobody
# pulls or verifies the GHCR-internal one directly. Driven by IMG_*
# variables emitted by ci/generate_pipeline.py.
set -eu

: "${IMG_NAME:?}" "${IMG_VERSION:?}" "${IMG_ARCHS:?}"
: "${CI_PUBLIC_REGISTRY:?}" "${CI_PUBLIC_REGISTRY_USER:?}" "${CI_PUBLIC_REGISTRY_PASSWORD:?}" "${CI_PUBLIC_REGISTRY_IMAGE:?}"
REGISTRY="${CI_REGISTRY_IMAGE:?}"
SHA_TAG="${IMG_VERSION}-g${CI_COMMIT_SHORT_SHA:?}"
IMAGE="${REGISTRY}/${IMG_NAME}"
PUBLIC_IMAGE="${CI_PUBLIC_REGISTRY_IMAGE}/${IMG_NAME}"

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
# digest). PUBLISH_VERSION gates the Docker Hub mirror below: only a
# genuinely new release is worth mirroring/signing — EXCEPT
# FORCE_MIRROR=1 (workflow_dispatch's force_mirror input), the escape
# hatch for backfilling Docker Hub with whatever <version> GHCR already
# has, without bumping anything: a manifest version essentially never
# changes for most of these images, so left to itself the mirror would
# only ever fire for the rare image that gets bumped, and Docker Hub
# would otherwise never end up with the rest.
TAG_FLAGS="-t ${IMAGE}:${SHA_TAG}"
PUBLISH_VERSION=0
if [ "${CI_COMMIT_BRANCH:-}" = "${CI_DEFAULT_BRANCH:-main}" ]; then
    if docker buildx imagetools inspect "${IMAGE}:${IMG_VERSION}" >/dev/null 2>&1; then
        log "WARNING: ${IMG_NAME}:${IMG_VERSION} already published — bump 'version' in the manifest; pushing only ${SHA_TAG}"
        if [ "${FORCE_MIRROR:-0}" = "1" ]; then
            log "FORCE_MIRROR=1: mirroring the already-published ${IMG_VERSION} anyway"
            PUBLISH_VERSION=1
        fi
    else
        TAG_FLAGS="${TAG_FLAGS} -t ${IMAGE}:${IMG_VERSION}"
        PUBLISH_VERSION=1
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
annotate org.opencontainers.image.documentation "${IMG_DOCUMENTATION:-}"
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

# ------------------------------------------------------------- mirror
if [ "${PUBLISH_VERSION}" = "1" ]; then
    log "docker login (docker.io, mirror)"
    docker login -u "${CI_PUBLIC_REGISTRY_USER}" -p "${CI_PUBLIC_REGISTRY_PASSWORD}" "${CI_PUBLIC_REGISTRY}"
    log "mirror ${IMAGE}:${IMG_VERSION} -> ${PUBLIC_IMAGE}:${IMG_VERSION}"
    docker buildx imagetools create -t "${PUBLIC_IMAGE}:${IMG_VERSION}" "${IMAGE}:${IMG_VERSION}"
    PUBLIC_DIGEST=$(docker buildx imagetools inspect "${PUBLIC_IMAGE}:${IMG_VERSION}" --format '{{.Manifest.Digest}}')
    log "published ${PUBLIC_IMAGE}@${PUBLIC_DIGEST}"
fi

# ----------------------------------------------------------------- sign
# Two modes:
#   keyed   — COSIGN_PRIVATE_KEY (+ COSIGN_PASSWORD) as masked CI
#             variables.
#   keyless — COSIGN_KEYLESS=1 (set by the GitHub workflow, which also
#             declares permissions id-token: write): OIDC identity
#             certificate via the ambient ACTIONS_ID_TOKEN_REQUEST_*
#             env. A verifying policy-controller must check the
#             certificate identity on keyless-signed images and the
#             public key on keyed ones.
# Skipped when neither is configured, or when this run didn't mirror a
# new <version> (PUBLIC_DIGEST unset): signing the GHCR-internal
# <sha-tag> would be pointless, nothing ever verifies it directly.
if [ "${PUBLISH_VERSION}" = "1" ]; then
    if [ -n "${COSIGN_PRIVATE_KEY:-}" ]; then
        log "cosign sign (key)"
        # Registry auth via flags: the job's ~/.docker is not visible to a
        # container started on the dind daemon, so mounting it cannot work.
        docker run --rm -e COSIGN_PRIVATE_KEY -e COSIGN_PASSWORD \
            ghcr.io/sigstore/cosign/cosign:v2.6.3 sign --yes \
            --key env://COSIGN_PRIVATE_KEY \
            --registry-username "${CI_PUBLIC_REGISTRY_USER}" \
            --registry-password "${CI_PUBLIC_REGISTRY_PASSWORD}" \
            -a revision="${CI_COMMIT_SHA}" \
            "${PUBLIC_IMAGE}@${PUBLIC_DIGEST}"
    elif [ "${COSIGN_KEYLESS:-0}" = "1" ]; then
        log "cosign sign (keyless OIDC)"
        docker run --rm \
            -e ACTIONS_ID_TOKEN_REQUEST_TOKEN -e ACTIONS_ID_TOKEN_REQUEST_URL \
            ghcr.io/sigstore/cosign/cosign:v2.6.3 sign --yes \
            --registry-username "${CI_PUBLIC_REGISTRY_USER}" \
            --registry-password "${CI_PUBLIC_REGISTRY_PASSWORD}" \
            -a revision="${CI_COMMIT_SHA}" \
            "${PUBLIC_IMAGE}@${PUBLIC_DIGEST}"
    fi
fi

# ------------------------------------------------------------- sbom+attest
# Attaches a signed CycloneDX SBOM to the published image itself (cosign
# attest), so anyone with just the image ref can retrieve it
# (`cosign download sbom`/`verify-attestation`) forever — unlike the
# per-arch sbom-N jobs' workflow-artifact upload, which expires and
# isn't discoverable from the image alone. Consultable in the one place
# that matters, no separate store to keep in sync.
#
# One representative platform (amd64 — "mandatory" per images.yaml's
# archs comment): package sets barely differ by arch for these
# Dockerfiles, and attesting every platform would double Rekor writes
# for no real benefit.
#
# Best-effort, deliberately non-fatal — same tolerance already applied
# to scan-N/sbom-N (their own header comments: "must never block push/
# merge/catalog"): a Sigstore Rekor/Fulcio hiccup or a transient trivy
# failure here must not undo the mirror+sign that already succeeded
# above. Same key/keyless branching as the sign block; silently skipped
# if neither is configured (nothing to attest with).
attach_sbom() {
    log "trivy sbom (cyclonedx) ${PUBLIC_IMAGE}@${PUBLIC_DIGEST}"
    docker run --rm \
        -v "$(pwd):/out" \
        -v trivy-cache:/root/.cache/trivy \
        ghcr.io/aquasecurity/trivy:0.72.0 image \
        --username "${CI_PUBLIC_REGISTRY_USER}" --password "${CI_PUBLIC_REGISTRY_PASSWORD}" \
        --platform linux/amd64 \
        --format cyclonedx \
        --output /out/sbom.cdx.json \
        "${PUBLIC_IMAGE}@${PUBLIC_DIGEST}"

    log "cosign attest (cyclonedx sbom)"
    if [ -n "${COSIGN_PRIVATE_KEY:-}" ]; then
        docker run --rm -v "$(pwd):/work" -w /work -e COSIGN_PRIVATE_KEY -e COSIGN_PASSWORD \
            ghcr.io/sigstore/cosign/cosign:v2.6.3 attest --yes \
            --key env://COSIGN_PRIVATE_KEY \
            --predicate sbom.cdx.json --type cyclonedx \
            --registry-username "${CI_PUBLIC_REGISTRY_USER}" \
            --registry-password "${CI_PUBLIC_REGISTRY_PASSWORD}" \
            "${PUBLIC_IMAGE}@${PUBLIC_DIGEST}"
    elif [ "${COSIGN_KEYLESS:-0}" = "1" ]; then
        docker run --rm -v "$(pwd):/work" -w /work \
            -e ACTIONS_ID_TOKEN_REQUEST_TOKEN -e ACTIONS_ID_TOKEN_REQUEST_URL \
            ghcr.io/sigstore/cosign/cosign:v2.6.3 attest --yes \
            --predicate sbom.cdx.json --type cyclonedx \
            --registry-username "${CI_PUBLIC_REGISTRY_USER}" \
            --registry-password "${CI_PUBLIC_REGISTRY_PASSWORD}" \
            "${PUBLIC_IMAGE}@${PUBLIC_DIGEST}"
    else
        log "no cosign key configured — skipping SBOM attestation"
    fi
}

if [ "${PUBLISH_VERSION}" = "1" ]; then
    attach_sbom || log "WARNING: SBOM attestation failed (non-fatal) for ${PUBLIC_IMAGE}@${PUBLIC_DIGEST}"
fi
