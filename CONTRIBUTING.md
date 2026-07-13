# Contributing

Thanks for looking at `waas-images`. This repo builds the OCI images
that back WaaS Linux workspaces — read `README.md` for the full design
(TigerVNC + optional xrdp bridge, unprivileged, read-only-rootfs
friendly) before making changes; this file covers the day-to-day
mechanics of contributing.

## Prerequisites

- Docker (or a compatible builder) with buildx for multi-arch builds.
- Python 3 + PyYAML — needed by `ci/generate_pipeline.py` and `make recipes`.
- `hadolint` and `shellcheck` — used by `make lint` and by CI.
- `docker buildx imagetools` for inspecting published multi-arch manifests.

## Local dev loop

Every local target wraps the exact same scripts CI uses, so "works
locally" means "works in CI":

```
make build IMAGE=ubuntu-desktop-noble   # build
make run   IMAGE=ubuntu-desktop-noble   # run, VNC on localhost:15901 (password: devpassword)
make smoke IMAGE=ubuntu-desktop-noble   # ci/smoke_test.sh: protocol handshake + hardening checks
make lint                      # hadolint + shellcheck over every Dockerfile/script
```

See the `Makefile` for the current list of wired-up `IMAGE` values —
new images need an entry there for local convenience, but the CI
pipeline itself is driven entirely by `manifest.yaml` discovery, not by
the Makefile.

Python tests for the catalog/pipeline generators:

```
python3 -m unittest discover -s ci/tests
```

## Adding a new app image

Two paths — pick the declarative one whenever it fits.

**`recipe:` (declarative)** — for an app that's just apt packages plus
an autostart entry, no Dockerfile at all:

```yaml
name: libreoffice
layer: apps
version: "1.0.0"
from: core-ubuntu-noble-xfce
recipe:
  apt: [libreoffice, libreoffice-gtk3]
  autostart: libreoffice
variants:
  - name: libreoffice
    smoke: { vnc: true }
```

`ci/recipe_compiler.py` expands this into a `Dockerfile.generated` that
always includes `--no-install-recommends`, a cache purge, a suid
re-strip, and the final `USER 1000:1000` — you cannot forget them
because the compiler always emits them. A directory may not contain
both a `recipe:` block and a hand-written `Dockerfile`.

**Hand-written Dockerfile** — for anything beyond "install some apt
packages" (custom repos, non-apt installs, extra services — see
`apps/firefox`, `apps/devtools`):

1. `mkdir apps/<name>`, add a `Dockerfile`:
   ```dockerfile
   ARG BASE_IMAGE
   FROM ${BASE_IMAGE}
   USER 0
   # apt-get install ... && strip any new suid/setgid bits
   USER 1000:1000
   ```
2. Add `apps/<name>/manifest.yaml` (`name`, `layer: apps`, `version`,
   `from`, `variants:` with a `smoke:` block).
3. Autostart: ship `/etc/xdg/autostart/waas-app.desktop` for a
   full desktop, or set `ENV WAAS_STARTUP="<command>"` for a
   single-app image on the bare base.
4. Push — `ci/generate_pipeline.py` discovers the new directory
   automatically; nothing else in `images.yaml` or CI config needs
   editing. A new OS/distro instead of a new app needs a new `base/`
   directory plus an entry in `images.yaml`'s `os:` map.

Bump `version` in the manifest for any change to that image — tags are
immutable and CI refuses to move an already-published `<version>` tag.

## Required checks before opening a PR

- `make lint` passes (hadolint + shellcheck).
- `make build IMAGE=<name>` and `make smoke IMAGE=<name>` pass for every
  image you touched, including derived images downstream of a base/desktop
  change.
- `python3 -m unittest discover -s ci/tests` passes if you touched any
  `ci/*.py` generator.
- If you touched `icon:` in a manifest, verify the slug resolves at
  `https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/<slug>.svg`
  (200 = valid; an invalid slug fails silently, not in CI).
- Regenerate derived files that ended up stale in your working tree
  (`make recipes`, `python3 ci/generate_pipeline.py [--emitter github]`) —
  they're gitignored build artifacts, not something to hand-edit or commit.

## Security & hardening expectations

Read `HARDENING.md` before touching anything in `base/` or the
entrypoint/supervisord scripts — it's a verifiable checklist, not
aspirational, and CI enforces most of it via the smoke test (read-only
rootfs, `--cap-drop ALL`, no-new-privileges, suid sweep, trivy
vuln/secret scan). In particular:

- Images run as `waas_user` (UID/GID 1000) with no path to root.
- RDP client authentication (`RDP_AUTH_ENABLED`) is on by default and
  has no build-time opt-out — only a runtime env can disable it, and
  that logs a warning. Don't add a build arg that bypasses this.
- No secrets baked into layers; passwords arrive via runtime env only.
- `-dev` profile images (baked sudo, relaxed pod securityContext) are a
  deliberate, narrowly-scoped exception — see `HARDENING.md` § "Reduced
  profile" before adding another one.

## Commit messages

Conventional commits, scoped to the area touched:
`feat(scope): …`, `fix(scope): …`, `ci(scope): …`, `docs(scope): …`,
`chore: …`. Check `git log --oneline` for the established scope names
(`ci`, `catalog`, `identity`, `firefox`, `devtools`, `schema`, …)
before inventing a new one.

## GitHub is the forge

This project is open source on GitHub, its sole canonical and publicly
accessible forge — GitLab is no longer an active forge for this
project. `.github/workflows/build.yml` dispatches the same portable
`ci/*.sh` scripts that hold all the build/smoke/scan logic.

## Dependency updates

Renovate (`renovate.json`) manages base image digests, CI tool pins
(binfmt/trivy/cosign/buildkit). OS base bumps (Ubuntu/Debian/Fedora) are
grouped and labeled `os-bump` and never automerged — they're a
deliberate version decision, review them as such.
