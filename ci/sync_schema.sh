#!/bin/sh
# sync_schema.sh — detect drift between the vendored WaaS catalog JSON
# Schema (ci/schema/v1.schema.json) and its source of truth, waas's
# shared/catalog/schema/v1.schema.json (see ci/schema/README.md).
# Both waas and waas-images are public repos, so reading waas's file
# needs no cross-repo token — a plain raw.githubusercontent.com fetch.
# This script only stages the re-sync locally (updates the schema file
# + the commit SHA in ci/schema/README.md) and reports via
# $GITHUB_OUTPUT whether anything changed; it never commits, pushes,
# or opens a PR itself. That split matters here specifically because a
# schema change can be breaking (tightened enum, new required field) —
# unlike catalog-kasmweb.yml's regenerated data file, this always goes
# through .github/workflows/catalog-schema-sync.yml opening a PR for a
# human to review, never straight to main.
set -eu

SCHEMA_PATH="shared/catalog/schema/v1.schema.json"
LOCAL_SCHEMA="ci/schema/v1.schema.json"
LOCAL_README="ci/schema/README.md"

# Resolve the SHA first, then fetch the file content pinned to that
# exact SHA (not a second, separate "main" request) — otherwise a push
# to waas main landing between the two calls would make the SHA
# recorded below (and the PR title/link built from it) describe a
# different commit than the bytes actually vendored.
WAAS_SHA=$(gh api repos/XoRHub/waas/commits/main --jq .sha)

TMP_SCHEMA=$(mktemp)
trap 'rm -f "${TMP_SCHEMA}"' EXIT
curl -fsSL "https://raw.githubusercontent.com/XoRHub/waas/${WAAS_SHA}/${SCHEMA_PATH}" -o "${TMP_SCHEMA}"

if diff -q "${TMP_SCHEMA}" "${LOCAL_SCHEMA}" >/dev/null 2>&1; then
    echo "${LOCAL_SCHEMA} already matches waas @ ${WAAS_SHA}"
    [ -n "${GITHUB_OUTPUT:-}" ] && echo "changed=false" >> "${GITHUB_OUTPUT}"
    exit 0
fi

cp "${TMP_SCHEMA}" "${LOCAL_SCHEMA}"
sed -i.bak -E "s/commit \`[0-9a-f]{7,40}\`/commit \`$(echo "${WAAS_SHA}" | cut -c1-12)\`/" "${LOCAL_README}"
rm -f "${LOCAL_README}.bak"

echo "${LOCAL_SCHEMA} updated to waas @ ${WAAS_SHA}"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "changed=true" >> "${GITHUB_OUTPUT}"
    echo "waas_sha=${WAAS_SHA}" >> "${GITHUB_OUTPUT}"
fi
