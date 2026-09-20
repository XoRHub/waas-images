# waas-images

OCI images for WaaS Linux workspaces — Kasm-style, 100 % OSS, built for
the platform's Workspace CR (operator → pod → guacd → wwt → browser).

```
base/ubuntu         core-ubuntu-noble, core-debian-13 — TigerVNC Xvnc ┐
                    + openbox, VNC only (no xrdp, no sshd),           │
                    OS-parameterized FROM: ubuntu-* AND debian-*      │
base/fedora         core-fedora-43, dnf sibling                       │
                    (own Dockerfile + rootfs copy)                    │
desktop/xfce        ubuntu-desktop-noble, debian-desktop-13 — XFCE    │
                    + baseline (firefox/git/ssh client/mise) on the   ├─ layers
                    core; ubuntu-desktop-noble is the devtools parent │
desktop/xfce-fedora fedora-desktop-43 — same baseline, dnf sibling    │
apps/firefox        policy-managed Firefox, single-app kiosk          │
apps/devtools       VS Code + build toolchain (+ devtools-dev)        │
apps/libreoffice    recipe:-generated (no Dockerfile in tree)         │
apps/chrome         recipe:-generated, third-party repo               │
apps/hermes-agent   Hermes Agent, dashboard kiosk (+ -dev variant)    ┘
images.yaml         global build config (OS matrix, archs, scan gate)
ci/                 pipeline generator + recipe compiler, build/smoke scripts
.github/workflows/  GitHub Actions pipeline (canonical forge)
examples/           WorkspaceTemplate + NetworkPolicy
HARDENING.md        verifiable hardening checklist + threat model
```

`core-*` images (the base layer) are internal build parents only — they
exist purely to be built FROM by another manifest and are never
published to `catalog-waas-images.yaml` (`ci/generate_catalog.py` skips
any variant name starting with `core-`, same for the per-image README
generator).

## Design in one paragraph

TigerVNC's **Xvnc is the display server** (no Xvfb double stack): it
serves RFB 3.8 natively, which is exactly what guacd's VNC client
speaks, and supports RandR resize. **VNC is the only protocol**: the
platform reaches a Linux workspace over VNC and nothing else (waas#117
— `rdp` is accepted on Windows VM templates only, `ssh` was dropped), so
no image here ships `xrdp` or `sshd`, there is no build arg to add
them, and ports 3389/2222 are not exposed. Services run under **tini +
supervisord**, entirely unprivileged; the entrypoint renders all
mutable config into tmpfs so the rootfs can be read-only. The web
client is guacd/wwt from the platform — no noVNC in the images. The
base (`core-*`) layer is the parent of the OS desktops
(`ubuntu-desktop-noble`, `debian-desktop-13`, `fedora-desktop-43`) and
of every `apps/*` kiosk (single-app via `WAAS_APP`, no desktop in the
image) — except `devtools`, a real desktop built FROM
`ubuntu-desktop-noble`.

## Try it standalone

No platform needed to evaluate an image — it runs under the same
constraints WaaS enforces in-cluster (non-root, read-only rootfs,
every capability dropped):

```shell
docker run --rm -it \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp --tmpfs /home/waas_user:mode=1777 \
  -p 5901:5901 -e WAAS_DESKTOP_PASSWORD=changeme \
  docker.io/xorhub/<image>:<version>
```

Then point any VNC client at `localhost:5901` (password `changeme`).

Published images are multi-arch manifest lists, cosign-signed (keyless
OIDC) with a CycloneDX SBOM attested to the image itself:

```shell
cosign verify docker.io/xorhub/<image>:<version> \
  --certificate-identity-regexp 'github.com/XoRHub/waas-images' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
cosign verify-attestation --type cyclonedx docker.io/xorhub/<image>:<version> \
  --certificate-identity-regexp 'github.com/XoRHub/waas-images' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

This section and `ci/dockerhub-readme-template.md` are the same
content on purpose — GHCR package pages render this README (via
`org.opencontainers.image.source`; GHCR has no per-package README),
Docker Hub renders the template — and a test locks the command blocks
together (`ci/tests/test_publish_dockerhub_readme.py`).

## Contract with the Workspace CR

| Aspect | Value |
|---|---|
| VNC port | `5901` (RFB 3.8, VncAuth) — guacd protocol `vnc`, the only protocol for `os: linux`. No RDP, no SSH: no other session listener (PulseAudio on `4713` is the audio stream, not a session) |
| Readiness/liveness | TCP open on `5901` ⇔ Xvnc accepting connections (matches the operator's TCP probes) |
| User | `waas_user`, UID/GID `1000:1000` (build-args `WAAS_USER`/`WAAS_UID`/`WAAS_GID`), home **`/home/waas_user`** = operator's PVC mount (`DefaultHomeMountPath`); fresh PVCs are seeded from `/etc/skel` |
| Writable paths | `/home/waas_user` (PVC), `/tmp` (emptyDir) — everything else read-only-safe |
| Desktop baseline | `desktop/xfce` and `desktop/xfce-fedora` ship Firefox, git, **openssh-client** (the client half only — outbound `git push`; no image ships an sshd), curl, vim, less and **mise** — inherited by the three OS desktops and, being built FROM `ubuntu-desktop-noble`, by `apps/devtools`. Kiosk apps built straight on a core image are deliberately excluded (no shell to use it). Before this, a desktop was XFCE and nothing else, and no image in the repo could `git push` over SSH |
| Persistent tooling | **mise** ships on both profiles (it needs no privileges): toolchains install under `~/.local/share/mise`, i.e. on the PVC, so they survive pod restarts. Wired two ways: shims first on `PATH` (non-interactive contexts) and `mise activate` from `/etc/bash.bashrc` (interactive shells). Two caveats: shims shadow the image's own tools, and this covers toolchains only — system libraries still mean `sudo apt install` on a `-dev` tag, still lost on restart (HARDENING.md § Durable tooling) |
| Init hook | optional ConfigMap mounted at `/etc/waas/init.d/` — `*.sh` sourced at boot after the image's own `entrypoint.d/` hooks (UID 1000, no privilege change; see HARDENING.md) |
| Dev profile | `-dev` tags only (e.g. `devtools-dev`): sudo NOPASSWD baked, `WAAS_PROFILE=dev` warning at boot; pod must set `readOnlyRootFilesystem: false`, `allowPrivilegeEscalation: true` AND keep the runtime default capability set (cap-drop ALL keeps sudo dead); keep the catalog `allowedGroups` gate (HARDENING.md § Reduced profile) |
| Required env | `WAAS_DESKTOP_PASSWORD` — the VNC session password. **Refuses to start without it.** The legacy names `VNC_PW`/`RDP_PASSWORD` are refused with an explicit error (see § Env naming). |
| Optional env | `WAAS_VNC_RESOLUTION` (`1920x1080`), `WAAS_VNC_COL_DEPTH` (`24`), `WAAS_AUDIO_ENABLED` (`1`), `WAAS_STARTUP` (session command), `WAAS_APP` (single-app kiosk command) |
| Recommended pod securityContext | `runAsNonRoot`, `runAsUser/fsGroup: 1000`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`, `allowPrivilegeEscalation: false`, `seccompProfile: RuntimeDefault` → PodSecurity **restricted** compliant |

See `examples/workspacetemplate-xfce.yaml` for a complete template.

**Env naming**: every variable these images interpret at runtime is
`WAAS_`-prefixed — that is the whole contract, no exceptions. Build
`ARG`s (`INSTALL_SUDO`, `*_VERSION`, base image pins) are a separate,
build-only namespace and deliberately stay unprefixed. Coming from the
headless-VNC container ecosystem (ConSol, accetto, kasm):

| Legacy name | Here | Behavior if set |
|---|---|---|
| `VNC_PW`, `RDP_PASSWORD` | `WAAS_DESKTOP_PASSWORD` | **Refused** — startup fails with the new name in the message. Secret-bearing names get no silent alias: the platform only recognizes `WAAS_DESKTOP_PASSWORD` as an explicit source, so honoring an old name here would let a generated password silently shadow yours. |
| `VNC_RESOLUTION`, `VNC_COL_DEPTH` | `WAAS_VNC_RESOLUTION`, `WAAS_VNC_COL_DEPTH` | **Honored as fallback alias** (cosmetic, never read by the platform); `WAAS_*` wins when both are set, and a log line nudges toward the new name. |

**No RDP, no SSH (since 3.0.0)**: earlier majors carried an optional
xrdp bridge and an opt-in unprivileged sshd on the OS desktops
(`WAAS_RDP_ENABLED`, `WAAS_RDP_AUTH_ENABLED`, `WAAS_SSH_ENABLED`,
`WAAS_SSH_AUTHORIZED_KEYS(_FILE)`, `WAAS_TLS_CERT`/`_KEY`). The platform
no longer accepts either protocol on a Linux workspace (waas#117), so
the daemons, their build args and those variables are gone rather than
defaulted off — setting them now does nothing, and a template still
declaring `rdp`/`ssh` on one of these images is rejected by the
platform itself, not by the image. Two tombstones stay loud on
purpose: `RDP_PASSWORD` is refused like `VNC_PW` (same shadowing trap,
see the table above), and `WAAS_VNC_ENABLED=0` — which used to mean
"RDP only", Xvnc bound to localhost — is refused rather than ignored,
since honoring it silently would expose VNC on a template that asked
for the opposite.

**Secrets**: nothing is baked into images; the password arrives via env
at runtime. Today the api-server reads the guacd-side password from the
template's literal `env` values — until it resolves `secretKeyRef`s,
inject the value into the WorkspaceTemplate manifest itself via
ESO/Vault in your GitOps repo (and RBAC-restrict template reads). The
images are already `valueFrom`-ready; only the api-server needs the
follow-up.

**Resize / clipboard / audio (honest status)**: clipboard works over VNC
(vncconfig bridge). Dynamic resolution is server-side only
(`waas-resize 2560x1440` inside the session) because Guacamole's VNC
channel doesn't push browser resizes; wiring wwt → `waas-resize` is the
clean future fix. Audio ships over VNC: an unprivileged PulseAudio (null
sink, native protocol on tcp:4713) that guacd streams when the session
sets `enable-audio` (see HARDENING.md for its network boundary).

## Build matrix & tagging

Global knobs live in `images.yaml` (OS matrix, default archs, trivy
gate); each image directory has a `manifest.yaml` declaring its
version, parent (`from:`), archs and smoke expectations.
`ci/generate_pipeline.py` discovers manifests, topo-sorts on `from` and
emits one child-pipeline job per variant: **base → desktop → apps in a
single pipeline**, derived images consuming the parent's same-arch tag
pushed minutes earlier (`BASE_IMAGE=<registry>/<parent>:<ver>-g<sha>-<arch>`).

Tags are **immutable**:

- `<version>-g<shortsha>` — pushed from every branch (unique, throwaway)
- `<version>` — pushed from `main` once; CI refuses to move it (bump
  `version` in the manifest instead)
- ArgoCD/templates should pin `<version>` or, better, the digest

Multi-arch: `linux/amd64` + `linux/arm64` built NATIVELY on the amd/arm
runner fleets — no QEMU in the nominal path (per-image override, e.g.
Chrome is amd64-only because Google publishes no arm64 deb).
Pipeline: generate (incl. recipe compilation) →
hadolint/shellcheck → per image and per arch *build → smoke → push
`-g<sha>-<arch>` (OCI mediatypes)*, then a merge job assembles the
annotated manifest list, mirrors it to Docker Hub, cosign-signs the
public copy and (best-effort) cosign-attests a CycloneDX SBOM to it too
— see § "SBOMs" below. Trivy and a second, per-arch SBOM run as
separate jobs against the pushed tag, in parallel with the merge —
both smoke (a hard gate) and push run on BOTH arches, but a trivy
finding or an SBOM failure never blocks the push, merge or catalog: it
only fails that specific job, visibly. Fallback: the CI variable
`WAAS_IMAGES_BUILD_STRATEGY=qemu` routes every build job to the amd
fleet under emulation (arm fleet down) — same jobs, same gates, just
slower.

**SBOMs**: two mechanisms, two purposes. The per-arch `sbom-N` jobs
upload a CycloneDX SBOM as a GitHub Actions workflow artifact — fine
for debugging that specific run, but it expires (default retention)
and isn't discoverable from the image alone. The one that matters for
consumers is the cosign attestation `merge_image.sh` adds to the
published Docker Hub image itself (one representative platform, amd64
— package sets barely differ by arch here): `cosign download sbom
<image>` or `cosign verify-attestation --type cyclonedx <image>`
retrieves it from the image reference alone, indefinitely, no separate
store to keep in sync. Best-effort like the trivy/SBOM jobs above — a
Sigstore Rekor/Fulcio hiccup must not undo the mirror+sign that already
succeeded.

**GitHub is the sole forge** — this project is open source on GitHub,
its one canonical and publicly accessible forge (GitLab is no longer
an active forge for this project). `ci/*.sh` is the portable layer
dispatched by `.github/workflows/build.yml`:

| | GitHub |
|---|---|
| Workflow | `.github/workflows/build.yml` (static skeleton + generated matrices) |
| Runners | `ubuntu-24.04` / `ubuntu-24.04-arm` hosted |
| Registry | `docker.io/<DOCKER_HUB_USERNAME>/<image>` |
| Signing | cosign **keyless OIDC** (`COSIGN_KEYLESS=1`, verify the certificate identity) |

A verifying policy-controller must accept this signature mode.

The smoke test is also the hardening gate: every image must boot with
`--read-only --cap-drop ALL --security-opt no-new-privileges` and answer
a real RFB banner (plus a PulseAudio handshake on 4713), and its
setuid/setgid set must be empty (exactly `/usr/bin/sudo` on `-dev`
profiles). See `HARDENING.md`.

## Image metadata (labels & index annotations)

Every published image carries the same metadata twice — as OCI config
labels on each per-arch image (`ci/build_image.sh --label`) and as OCI
index annotations on the multi-arch manifest list
(`ci/merge_image.sh --annotation "index:…"`, which per-arch labels do
not propagate to; the push uses OCI mediatypes for exactly this
reason). Set centrally in the CI scripts, never per Dockerfile, so
hand-written and recipe-generated images cannot drift. Intended
consumer: catalog/classification tooling (today the governance catalog
is maintained by hand; these keys are its future source of truth).

| Key | Value |
|---|---|
| `org.opencontainers.image.title` | variant name (`ubuntu-desktop-noble`, …) |
| `org.opencontainers.image.description` | manifest `description:` |
| `org.opencontainers.image.version` | manifest `version:` |
| `org.opencontainers.image.revision` | full git commit of the build |
| `org.opencontainers.image.created` | build timestamp (UTC, RFC 3339) |
| `org.opencontainers.image.source` | URL of the forge that ran the build (`CI_PROJECT_URL`, exported by the GitHub workflow) |
| `org.opencontainers.image.documentation` | URL of this README (the durable usage contract — WAAS_* env vars, ports, protocols; see § "Per-image docs" for the per-run, non-committed detail) |
| `org.opencontainers.image.licenses` | `Apache-2.0` |
| `org.opencontainers.image.vendor` | `XorHub` |
| `io.xorhub.waas.os` | resolved `os:` key (`ubuntu-noble`, `debian-13`, `fedora-43`) |
| `io.xorhub.waas.layer` | `base` / `desktop` / `apps` |
| `io.xorhub.waas.profile` | `standard` or `dev` |
| `io.xorhub.waas.parent` | parent ref (`core-ubuntu-noble:3.0.0`), empty on layer roots |

Verify: `docker buildx imagetools inspect <ref> --raw` (index) or
`docker inspect <arch-ref>` (config labels).

Manifests additionally carry one catalog-only key that is **not** baked
into the image:

- `icon:` (optional; manifest root or per-variant override, same
  root+override convention as `smoke:`/`buildArgs:`) — a
  [dashboard-icons](https://github.com/homarr-labs/dashboard-icons)
  slug shown next to the image in the WaaS workspace-creation picker
  (consumed by `ci/generate_catalog.py`, see § Image catalogs). Verify
  `https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/<slug>.svg`
  answers 200 before committing: an invalid slug fails nothing anywhere —
  WaaS silently falls back to a generic OS icon, same as when the key is
  absent, so add icons progressively. Slugs verified on 2026-07-11:
  `ubuntu-linux`, `debian-linux`, `fedora`, `linux`, `firefox`,
  `google-chrome`, `libreoffice`, `visual-studio-code`, `terminal`
  (the plain `ubuntu`, `debian`, `xfce` and `gnome-terminal` slugs do
  **not** exist).

## Image catalogs (WaaS picker)

WaaS (`waas`) lets a user create a workspace straight from an
admin-approved registry image, without a per-image WorkspaceTemplate.
Its api-server's `CatalogSyncWorker` periodically fetches catalog files —
`{image, os, app, version, icon, displayName, description,
architectures}` lists,
plus `profile`/`recommended` deployment hints on
`catalog-waas-images.yaml` entries (see Design notes below), under
`apiVersion: waas.xorhub.io/catalog/v1` (full contract: the JSON
Schema at
[shared/catalog/schema/v1.schema.json](https://github.com/XoRHub/waas/blob/main/shared/catalog/schema/v1.schema.json)
in the waas repo — `ci/schema/v1.schema.json` here is its vendored,
drift-checked copy) — directly from this repo's `main`
branch (Contents API or raw URL, e.g.
`https://raw.githubusercontent.com/XoRHub/waas-images/main/catalog-waas-images.yaml`).
No GitHub Release involved: `main` is the only source of truth, one
job, one commit, `[skip ci]` since neither file is in `build.yml`'s
path filter anyway.

| Catalog | Generator | When |
|---|---|---|
| `catalog-waas-images.yaml` — the images this repo builds | `ci/generate_catalog.py` (reuses `generate_pipeline.py`'s manifest discovery — the catalog cannot drift from the build matrix) | `build.yml`'s `catalog` job, every default-branch run, after `build`/`merge` |
| `catalog-kasmweb.yaml` — upstream `docker.io/kasmweb/*` images | `ci/generate_kasm_catalog.py` over the hand-curated `kasm/catalog-mapping.yaml` (rename images or add icons/displayName/description there by hand; the script resolves each image's newest `X.Y.Z` release tag from Docker Hub, falling back to the mapping's `knownVersion` when Hub is unreachable, then derives `architectures`/`profile`/`recommended` — see Design notes below). `generate_kasm_catalog.py <name>` (e.g. `vs-code`, no registry prefix) resolves/probes just that one image and upserts it in place — CI or by hand, same script — appending a minimal mapping entry first if `<name>` isn't tracked yet. | `catalog-kasmweb.yml`, scheduled daily `0 6 * * *` UTC + manual `workflow_dispatch` |

Both files are committed via the Contents API (`ci/commit_catalog.sh`),
not `git push`: `main` requires verified signatures and a bot's plain
git push is never marked Verified (GH013 — confirmed live, this used
to fail every real change). A public repo needs no auth to read them
back; a private one would need a token with `contents:read`.

Before publication, both catalogs are validated by
`ci/validate_catalog.py` against `ci/schema/v1.schema.json` — the JSON
Schema of the wire format, vendored from the `waas` repo (which is the
source of truth; re-sync procedure in `ci/schema/README.md`). `make
catalogs` reproduces the same regenerate-and-validate loop locally, so
a change to `images.yaml`, a `manifest.yaml` or
`kasm/catalog-mapping.yaml` can be checked before pushing. The only
tooling prerequisite is [uv](https://docs.astral.sh/uv/) — every
`ci/*.py` script pins its own dependencies inline (PEP 723), locally
and in CI alike.

The vendored schema itself can drift from `waas` (a schema change can
be breaking, unlike a regenerated data file), so
`catalog-schema-sync.yml` (weekly + `workflow_dispatch`, via
`ci/sync_schema.sh`) only opens a PR when it detects a difference —
never auto-merged, always human-reviewed; `build.yml`'s `catalog` job
re-validates both catalogs against the candidate schema as part of
that PR's normal checks.

Design notes:

- Catalog entries reference `<name>:<version>` with **no digest**: the
  `<version>` tags are immutable by CI construction (§ Build matrix &
  tagging), so the ref is already as stable as a digest.
- The `os:` field is always `linux` (workspace OS family, what guacd
  cares about) — not the build distro that `io.xorhub.waas.os` carries.
- `displayName` is a human-readable label: the manifest's optional
  `displayName:` (root, overridable per variant — the `icon:`
  convention) when set, else derived from the variant id
  (dashes/underscores → spaces, title case: `ubuntu-desktop-noble` →
  `Ubuntu Desktop Noble`). Ids the naive rule renders badly get an
  explicit `displayName:` in their manifest (`LibreOffice`,
  `DevTools (hardened)`), never a hard-coded exception in the
  generator. `description` carries the manifest's `description:`
  whole — the old 80-char `displayName` truncation is gone.
- `core-*` variants (internal build parents — the base layer) never
  appear here at all: the generator skips any variant name starting
  with `core-` before it reaches the fallback logic above.
- **`main` is the only ref, always overwritten in place**: this repo has
  no repo-global version or git tag (each image versions independently
  via its manifest), so there is nothing meaningful to pin a catalog
  snapshot to anyway — `waas` always wants the newest catalog, and
  `main` always has it. `-g<sha>`-tagged branch builds never publish
  (same guard as the immutable image tags).
- Both publish jobs are best-effort (`continue-on-error`): the catalogs
  are secondary deliverables and must never block image publication.
- `catalog-waas-images.yaml` entries carry `profile` (`hardened` for
  `standard`-profile variants, `normal` for `-dev` ones) and a
  `recommended` block, both derived from this repo's own
  `manifest.yaml`/`HARDENING.md` doctrine (`ci/generate_catalog.py`'s
  `RECOMMENDATION_STANDARD`/`RECOMMENDATION_DEV` + a `smoke:`-driven
  `env` hint list) — the securityContext/volumes parts are never
  hand-written; the `env` list additionally merges the manifest's own
  image-specific `env:` hints (root or per variant, manifest wins a
  name collision). `catalog-kasmweb.yaml` entries
  carry the same two fields, but since those upstream images have no
  local manifest/doctrine to derive a profile from statically,
  `ci/generate_kasm_catalog.py --probe-hardening` (`catalog-kasmweb.yml`
  only — too slow/Docker-dependent for `make catalogs`) derives them
  empirically: `ci/probe_kasm_hardening.sh` actually pulls+runs each
  resolved image under increasingly strict Docker flags (the same
  technique `ci/smoke_test.sh` uses on this repo's own images) and sets
  `profile: hardened`/`normal` from whether it survives
  `readOnlyRootFilesystem`/`cap-drop ALL`. A `normal` verdict's
  `recommended` only claims the documented Kasm baseline
  (`runAsNonRoot`/`runAsUser`/`fsGroup: 1000`) — no
  `securityContext`/`volumes` claim beyond what was actually verified.
  Probing a given `image:version` again is skipped once
  `catalog-kasmweb.yaml` already has a verdict for that exact ref (see
  `previous` in `ci/generate_kasm_catalog.py`'s `catalog()`).
- `architectures` (waas's per-image nodeSelector prefill hint) is
  derived from the build matrix (`archs:`) on `catalog-waas-images.yaml`,
  and from Docker Hub's per-tag manifest-list data
  (`ci/generate_kasm_catalog.py`'s `hub_architectures()`) on
  `catalog-kasmweb.yaml` — never hand-written on either file. (A
  hand-curated `architectures:` field used to live in
  `kasm/catalog-mapping.yaml` and drifted stale — it claimed kasmweb's
  plain `X.Y.Z` tags were amd64-only, which live Hub data disproved:
  they're multi-arch manifest lists.) Omitted = unknown, waas falls
  back to the entry-level `spec.architectures` hint.

## Per-image docs

`ci/generate_image_readme.py` (reuses `generate_pipeline.py`'s manifest
discovery, same pattern as `ci/generate_catalog.py`) renders one
section per published image — linking this project and
[WaaS](https://github.com/XoRHub/waas) (the platform that deploys these
images) and stating its protocol contract — VNC, the only one — with
the env vars that drive it.

Deliberately **not committed**: it runs in the `catalog` job of every
default-branch build and appends its output to that run's
`$GITHUB_STEP_SUMMARY` — visible in the Actions run UI only, gone with
the run. With the image count only growing, keeping one synced doc
file per image (committed, needing cleanup on every rename/removal) is
exactly the maintenance burden this avoids: regenerated fresh from the
current manifests every run, so it can never drift and there is
nothing to keep in sync. The durable, versioned usage contract (WAAS_*
env vars, ports, protocols common to every image) lives in this README
instead — what `org.opencontainers.image.documentation` actually
points at (§ Image metadata).

The same render is also pushed as each image's **Docker Hub overview**
by `ci/publish_dockerhub_readme.py` (same `catalog` job): GHCR pages
show this repo's README automatically via
`org.opencontainers.image.source`, but Docker Hub displays nothing
unless `full_description` is set through its HTTP API — the registry
push protocol cannot carry it. The overview splices the per-image
section into `ci/dockerhub-readme-template.md` (`{about}`/`{image}`
placeholders — shared standalone-quickstart and cosign-verify
boilerplate, the template-plus-section pattern
kasmtech/workspaces-images uses). Best-effort like the rest of the
job: a repo not yet mirrored to Hub warns and is skipped.

Local dev convenience: `make image-docs` prints the same output to
stdout (no `$GITHUB_STEP_SUMMARY` outside CI).

## Adding an app image

**Declarative shortcut (`recipe:`)** — when the app is "a list of apt
packages (+ a session command)", skip the Dockerfile entirely: add a
`recipe:` block to the manifest and `ci/recipe_compiler.py` emits a
`Dockerfile.generated` (gitignored; regenerated by CI's generate stage
and `make recipes`) from a template that bakes the non-negotiable
guards — `--no-install-recommends`, cache purge, re-asserted suid
strip, final `USER 1000:1000` — so they cannot be forgotten:

```yaml
name: libreoffice
layer: apps
version: "1.0.0"
from: core-ubuntu-noble
recipe:
  apt: [libreoffice, libreoffice-gtk3]
  app: libreoffice   # single-app kiosk (WAAS_APP); or autostart: <cmd> (XFCE
                     # desktop parent), startup: <cmd> (raw, no WM), program:
                     # <cmd> (supervisord)
  # repo: {url, keyUrl, fingerprint, pin}   # third-party apt repo (firefox pattern)
variants:
  - name: libreoffice
    smoke: { vnc: true }
```

Rules: a directory with BOTH `recipe:` and a Dockerfile is refused (one
source of truth); anything beyond apt-simple stays hand-written (see
apps/firefox). Recipe packages are deliberately not version-pinned:
they ride the archive at every rebuild — a package needing a
Renovate-tracked pin is exactly the hand-written case (`FIREFOX_VERSION`).

**Hand-written path** — everything else:

1. `mkdir apps/<name>` with a `Dockerfile` starting:
   ```dockerfile
   ARG BASE_IMAGE
   FROM ${BASE_IMAGE}
   USER 0
   # apt-get install ... && strip suid bits (copy the firefox layer)
   USER 1000:1000
   ```
2. Add `apps/<name>/manifest.yaml`:
   ```yaml
   name: <name>
   layer: apps
   version: "1.0.0"
   from: core-ubuntu-noble     # or ubuntu-desktop-noble for a full desktop
   variants:
     - name: <name>
       smoke: { vnc: true }
   ```
3. Set `ENV WAAS_APP="<command>"` for the single-app kiosk session
   (openbox undecorates + maximises the app, no desktop — the default
   for app images); on the XFCE parent, ship an
   `/etc/xdg/autostart/waas-app.desktop` instead.
4. Push — the generator picks the directory up automatically; nothing
   else to edit. New OS/distro = new directory under `base/` + an entry
   in `images.yaml`'s `os:` map.

Local loop: `make build|run|smoke IMAGE=ubuntu-desktop-noble` (same scripts as CI;
`make run` serves VNC on `localhost:15901`, password `devpassword`).
