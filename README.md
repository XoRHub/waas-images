# waas-images

OCI images for WaaS Linux workspaces — Kasm-style, 100 % OSS, built for
the platform's Workspace CR (operator → pod → guacd → wwt → browser).

```
base/ubuntu         TigerVNC Xvnc + openbox, optional xrdp — apt,   ┐
                    OS-parameterized FROM: ubuntu-* AND debian-*    │
base/fedora         dnf sibling (own Dockerfile + rootfs copy)      │
desktop/xfce        XFCE on the apt base-rdp (ubuntu-* + debian-*)  ├─ layers
desktop/xfce-fedora XFCE on fedora-base-rdp                         │
apps/firefox        XFCE + policy-managed Firefox                   │
apps/devtools       VS Code + toolchain (+ ubuntu-devtools-dev)     │
apps/libreoffice    recipe:-generated (no Dockerfile in tree)       │
apps/chrome         recipe:-generated, third-party repo             ┘
images.yaml         global build config (OS matrix, archs, scan gate)
ci/                 pipeline generator + recipe compiler, build/smoke scripts
.github/workflows/  GitHub Actions pipeline (canonical forge)
examples/           WorkspaceTemplate + NetworkPolicy
HARDENING.md        verifiable hardening checklist + threat model
```

## Design in one paragraph

TigerVNC's **Xvnc is the display server** (no Xvfb double stack): it
serves RFB 3.8 natively, which is exactly what guacd's VNC client
speaks, and supports RandR resize. **RDP is a bridge**: xrdp without
sesman/PAM, its `libvnc` backend pointed at the local Xvnc
(`password=ask` forwards the RDP password as the VNC password) — fully
non-root, both protocols always show the same session. Services run
under **tini + supervisord**, entirely unprivileged; the entrypoint
renders all mutable config into tmpfs so the rootfs can be read-only.
The web client is guacd/wwt from the platform — no noVNC in the images.

## Contract with the Workspace CR

| Aspect | Value |
|---|---|
| VNC port | `5901` (RFB 3.8, VncAuth) — guacd protocol `vnc`, the default for `os: linux` |
| RDP port | `3389` (TLS negotiated) — only images built with `INSTALL_RDP=1` and `WAAS_RDP_ENABLED=1` |
| Readiness/liveness | TCP open on the template port ⇔ protocol server accepting connections (matches the operator's TCP probes) |
| User | UID/GID `1000:1000` (build-args `WAAS_UID/WAAS_GID`), home **`/home/user`** = operator's PVC mount; fresh PVCs are seeded from `/etc/skel` |
| Writable paths | `/home/user` (PVC), `/tmp`, `/run` (emptyDirs) — everything else read-only-safe |
| Init hook | optional ConfigMap mounted at `/etc/waas/init.d/` — `*.sh` sourced at boot after the image's own `entrypoint.d/` hooks (UID 1000, no privilege change; see HARDENING.md) |
| Dev profile | `-dev` tags only (e.g. `ubuntu-devtools-dev`): sudo NOPASSWD baked, `WAAS_PROFILE=dev` warning at boot; pod must set `readOnlyRootFilesystem: false`, `allowPrivilegeEscalation: true` AND keep the runtime default capability set (cap-drop ALL keeps sudo dead); keep the catalog `allowedGroups` gate (HARDENING.md § Reduced profile) |
| Required env | `VNC_PW` (or `VNC_PASSWORD` / `RDP_PASSWORD` — one shared session password). **Refuses to start without it.** |
| Optional env | `VNC_RESOLUTION` (`1920x1080`), `VNC_COL_DEPTH` (`24`), `WAAS_VNC_ENABLED` (`1`), `WAAS_RDP_ENABLED`, `RDP_AUTH_ENABLED` (`true`), `WAAS_STARTUP` (session command), `WAAS_TLS_CERT`/`WAAS_TLS_KEY` (mounted RDP cert) |
| Recommended pod securityContext | `runAsNonRoot`, `runAsUser/fsGroup: 1000`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`, `allowPrivilegeEscalation: false`, `seccompProfile: RuntimeDefault` → PodSecurity **restricted** compliant |

See `examples/workspacetemplate-xfce.yaml` for a complete template.

**RDP authentication (`RDP_AUTH_ENABLED`, default `true`)**: images are
secure by default — every build ships with RDP client authentication ON
(`ENV RDP_AUTH_ENABLED=true` in the base image), meaning the RDP client
must present the session password, which the xrdp bridge forwards to
Xvnc (`password=ask`). There is no build argument to turn it off: an
image can never leave the pipeline with an open RDP. The only opt-out is
the **runtime** env `RDP_AUTH_ENABLED=false` (lab/dev setups behind
their own gate): the bridge then authenticates to Xvnc itself and any
client reaching `:3389` gets the session — the entrypoint logs a loud
warning when this mode is active. The value must be exactly `true` or
`false`; anything else aborts startup. VNC authentication (VncAuth) is
unaffected in both modes, and a session password is required in every
configuration.

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
RDP-clipboard works text-only — xrdp's libvnc backend bridges cliprdr to
RFB cut-text itself, no chansrv involved (verified live against guacd,
both directions). RDP-audio is not shipped: chansrv would run fine
without sesman/PAM/root, but its sound path needs an xrdp module inside
the audio server and Ubuntu only packages the PipeWire variant
(`pipewire-module-xrdp`) while this image runs PulseAudio — see
HARDENING.md § Known gaps. VNC is the recommended protocol for Linux,
RDP is a compatibility option.

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
Firefox is amd64-only until packages.mozilla.org's arm64 debs are
validated). Pipeline: generate (incl. recipe compilation) →
hadolint/shellcheck → per image and per arch *build → smoke → trivy
gate → push `-g<sha>-<arch>` (OCI mediatypes)*, then a merge job
assembles the annotated manifest list and cosign-signs it. Both smoke
and scan run on BOTH arches. Fallback: the CI variable
`WAAS_IMAGES_BUILD_STRATEGY=qemu` routes every build job to the amd
fleet under emulation (arm fleet down) — same jobs, same gates, just
slower.

**Two forges, same scripts, two registries** — `ci/*.sh` is the
portable layer; only the YAML dispatch differs:

| | GitHub (canonical) | GitLab |
|---|---|---|
| Workflow | `.github/workflows/build.yml` (static skeleton + `--emitter github` matrices) | `.gitlab-ci.yml` → generated child pipeline |
| Runners | `ubuntu-24.04` / `ubuntu-24.04-arm` hosted | `amd` / `arm` self-hosted fleets |
| Registry | `ghcr.io/<owner>/waas-images/<image>` | GitLab project registry |
| Signing | cosign **keyless OIDC** (`COSIGN_KEYLESS=1`, verify the certificate identity) | cosign **key** (`COSIGN_PRIVATE_KEY`, verify the public key) |

A verifying policy-controller must accept both signature modes for as
long as the two forges publish in parallel.

The smoke test is also the hardening gate: every image must boot with
`--read-only --cap-drop ALL --security-opt no-new-privileges` and answer
a real RFB banner / X.224 handshake, and its setuid/setgid set must be
empty (exactly `/usr/bin/sudo` on `-dev` profiles). See `HARDENING.md`.

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
| `org.opencontainers.image.title` | variant name (`ubuntu-xfce`, …) |
| `org.opencontainers.image.description` | manifest `description:` |
| `org.opencontainers.image.version` | manifest `version:` |
| `org.opencontainers.image.revision` | full git commit of the build |
| `org.opencontainers.image.created` | build timestamp (UTC, RFC 3339) |
| `org.opencontainers.image.source` | URL of the forge that ran the build (`CI_PROJECT_URL` on GitLab) |
| `org.opencontainers.image.licenses` | `Apache-2.0` |
| `org.opencontainers.image.vendor` | `XorHub` |
| `io.xorhub.waas.os` | resolved `os:` key (`ubuntu-24.04`, `debian-13`, `fedora-43`) |
| `io.xorhub.waas.layer` | `base` / `desktop` / `apps` |
| `io.xorhub.waas.profile` | `standard` or `dev` |
| `io.xorhub.waas.parent` | parent ref (`ubuntu-xfce:1.1.0`), empty on layer roots |

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

WaaS (`waas-fable`) lets a user create a workspace straight from an
admin-approved registry image, without a per-image WorkspaceTemplate.
Its `WorkspaceImageReconciler` periodically fetches catalog files —
`{image, os, app, version, icon, displayName}` lists under
`apiVersion: waas.xorhub.io/catalog/v1` (full contract:
`docs/studies/prompt-feature13-catalog-publishing.md`) — and this repo
publishes two of them to its GitLab **Generic Package Registry**:

| Catalog | Generator | When | URL (`$CI_API_V4_URL/projects/<id>` prefix) |
|---|---|---|---|
| `catalog-waas-images.yaml` — the images this repo builds | `ci/generate_catalog.py` (reuses `generate_pipeline.py`'s manifest discovery — the catalog cannot drift from the build matrix) | every default-branch pipeline, `catalog` stage, after `build` | `/packages/generic/waas-catalog/latest/catalog-waas-images.yaml` |
| `catalog-kasmweb.yaml` — upstream `docker.io/kasmweb/*` images | `ci/generate_kasm_catalog.py` over the hand-curated `kasm/catalog-mapping.yaml` (add/remove/rename images and icons there; the script only resolves each image's newest `X.Y.Z` release tag from Docker Hub, falling back to the mapping's `knownVersion` when Hub is unreachable) | scheduled pipelines only | `/packages/generic/kasm-catalog/latest/catalog-kasmweb.yaml` |

Design notes:

- Catalog entries reference `<name>:<version>` with **no digest**: the
  `<version>` tags are immutable by CI construction (§ Build matrix &
  tagging), so the ref is already as stable as a digest.
- The `os:` field is always `linux` (workspace OS family, what guacd
  cares about) — not the build distro that `io.xorhub.waas.os` carries.
- **Generic Package Registry, not a GitLab Release**: this repo has no
  repo-global version or git tag (each image versions independently via
  its manifest), so a Release would need an artificial tag just to hold
  the asset. The package URL is stable, needs no tag, and re-uploading
  to the fixed `latest` version segment on every run is exactly the
  "consumer always wants the newest catalog" semantic. `-g<sha>`-tagged
  branch builds never publish (same guard as the immutable tags).
- Both publish jobs are `allow_failure` / best-effort: the catalogs are
  secondary deliverables and must never block image publication.

**One-time manual setup after merging** (GitLab UI, not in YAML):

1. Create the scheduled pipeline: Settings → CI/CD → Pipeline
   schedules → target branch `main`. Recommended cadence: **daily,
   `0 6 * * *` UTC** — Kasm cuts releases every few months, so daily
   detection is generous while staying far from Docker Hub's anonymous
   rate limits; anything tighter buys nothing.
2. Make the catalog URLs fetchable by `waas-fable`'s anonymous HTTP
   GET. The project is currently **private** (the API returns 404
   anonymously, checked 2026-07-11), so out of the box the URLs above
   require auth. Either flip the project public, or keep it private and
   enable Settings → General → Visibility → **Package registry** →
   "Allow anyone to pull from Package Registry", or give `waas-fable` a
   read-only deploy token. Until one of these is done the reconciler's
   fetch will 404 silently on its side — verify with an unauthenticated
   `curl` after setup.

## Adding an app image

**Declarative shortcut (`recipe:`)** — when the app is "a list of apt
packages (+ an autostart)", skip the Dockerfile entirely: add a
`recipe:` block to the manifest and `ci/recipe_compiler.py` emits a
`Dockerfile.generated` (gitignored; regenerated by CI's generate stage
and `make recipes`) from a template that bakes the non-negotiable
guards — `--no-install-recommends`, cache purge, re-asserted suid
strip, final `USER 1000:1000` — so they cannot be forgotten:

```yaml
name: ubuntu-libreoffice
layer: apps
version: "1.0.0"
from: ubuntu-xfce
recipe:
  apt: [libreoffice, libreoffice-gtk3]
  autostart: libreoffice   # or startup: <cmd> (bare base), program: <cmd> (supervisord)
  # repo: {url, keyUrl, fingerprint, pin}   # third-party apt repo (firefox pattern)
variants:
  - name: ubuntu-libreoffice
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
   name: ubuntu-<name>
   layer: apps
   version: "1.0.0"
   from: ubuntu-xfce        # or ubuntu-base-vnc for single-app style
   variants:
     - name: ubuntu-<name>
       smoke: { vnc: true }
   ```
3. To autostart the app in XFCE, ship an
   `/etc/xdg/autostart/waas-app.desktop`; for single-app on the bare
   base, set `ENV WAAS_STARTUP="<command>"` instead.
4. Push — the generator picks the directory up automatically; nothing
   else to edit. New OS/distro = new directory under `base/` + an entry
   in `images.yaml`'s `os:` map.

Local loop: `make build|run|smoke IMAGE=ubuntu-xfce` (same scripts as CI;
`make run` serves VNC on `localhost:15901`, password `devpassword`).
