#!/bin/sh
# commit_catalog.sh — commit FILE to main via the GitHub Contents API,
# not `git commit && git push`: this repo's main branch requires
# verified signatures (ruleset), and a plain github-actions[bot]
# commit pushed over the git protocol is never marked Verified — GH013
# rejects it (confirmed live: catalog-waas-images.yaml regeneration
# failing on every real content change). Commits the API creates on
# GitHub's behalf ARE automatically Verified, sidestepping the need
# for a GPG/SSH signing key as a CI secret. Unlike the rest of ci/*.sh,
# this is GitHub-only (gh api), not shared with GitLab. No-ops if FILE
# is byte-identical to what's already on main.
set -eu

FILE="${1:?usage: commit_catalog.sh <file>}"
: "${GITHUB_REPOSITORY:?}"

LOCAL_SHA=$(git hash-object "${FILE}")
REMOTE_SHA=$(gh api "repos/${GITHUB_REPOSITORY}/contents/${FILE}?ref=main" --jq .sha 2>/dev/null || true)

if [ "${LOCAL_SHA}" = "${REMOTE_SHA}" ]; then
    echo "${FILE} unchanged, nothing to commit"
    exit 0
fi

CONTENT_B64=$(base64 -w0 "${FILE}")
SHA_FLAG=""
[ -n "${REMOTE_SHA}" ] && SHA_FLAG="-f sha=${REMOTE_SHA}"

# shellcheck disable=SC2086
gh api --method PUT "repos/${GITHUB_REPOSITORY}/contents/${FILE}" \
    -f message="chore(catalog): regenerate ${FILE} [skip ci]" \
    -f content="${CONTENT_B64}" \
    -f branch=main \
    ${SHA_FLAG}
echo "committed ${FILE} to main via the Contents API"
