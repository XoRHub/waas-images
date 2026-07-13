# Local developer loop. CI uses ci/*.sh directly; these targets wrap the
# same scripts so local == CI.
#
#   make build IMAGE=core-ubuntu-noble
#   make run   IMAGE=core-ubuntu-noble     # then connect a VNC client to :15901
#   make smoke IMAGE=core-ubuntu-noble
#   make lint
#   make catalogs    # regenerate + schema-validate both picker catalogs
#   make image-readmes  # regenerate docs/images/*.md (org.opencontainers.image.documentation source)
#
# Python tooling runs through uv: each ci/*.py script declares its own
# pinned dependencies inline (PEP 723 `# /// script` block), so uv is
# the only local prerequisite — no pip install, no venv to manage.

IMAGE      ?= core-ubuntu-noble
REGISTRY   ?= waas-local
TAG        := $(REGISTRY)/$(IMAGE):dev

# Map variant -> context + build args (local mirror of the manifests).
# core-* names are internal build parents only (never catalogued).
ifeq ($(IMAGE),core-ubuntu-noble)
  CTX := base/ubuntu
  ARGS := --build-arg INSTALL_RDP=0 --build-arg INSTALL_SSH=0
else ifeq ($(IMAGE),core-ubuntu-noble-full)
  CTX := base/ubuntu
  ARGS := --build-arg INSTALL_RDP=1 --build-arg INSTALL_SSH=1
else ifeq ($(IMAGE),core-ubuntu-noble-xfce)
  CTX := desktop/xfce
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-ubuntu-noble:dev
else ifeq ($(IMAGE),ubuntu-desktop-noble)
  CTX := desktop/xfce
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-ubuntu-noble-full:dev
else ifeq ($(IMAGE),firefox)
  CTX := apps/firefox
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-ubuntu-noble-xfce:dev
else ifeq ($(IMAGE),core-debian-13)
  CTX := base/ubuntu
  ARGS := --build-arg INSTALL_RDP=0 --build-arg INSTALL_SSH=0 --build-arg OS_BASE_IMAGE=debian:13-slim
else ifeq ($(IMAGE),core-debian-13-full)
  CTX := base/ubuntu
  ARGS := --build-arg INSTALL_RDP=1 --build-arg INSTALL_SSH=1 --build-arg OS_BASE_IMAGE=debian:13-slim
else ifeq ($(IMAGE),debian-desktop-13)
  CTX := desktop/xfce
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-debian-13-full:dev
else ifeq ($(IMAGE),core-fedora-43)
  CTX := base/fedora
  ARGS := --build-arg INSTALL_RDP=0 --build-arg INSTALL_SSH=0
else ifeq ($(IMAGE),core-fedora-43-full)
  CTX := base/fedora
  ARGS := --build-arg INSTALL_RDP=1 --build-arg INSTALL_SSH=1
else ifeq ($(IMAGE),fedora-desktop-43)
  CTX := desktop/xfce-fedora
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-fedora-43-full:dev
else ifeq ($(IMAGE),devtools)
  CTX := apps/devtools
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-ubuntu-noble-xfce:dev
else ifeq ($(IMAGE),devtools-dev)
  CTX := apps/devtools
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-ubuntu-noble-xfce:dev --build-arg INSTALL_SUDO=1 --build-arg WAAS_PROFILE=dev
else ifeq ($(IMAGE),libreoffice)
  CTX := apps/libreoffice
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-ubuntu-noble-xfce:dev
else ifeq ($(IMAGE),chrome)
  CTX := apps/chrome
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/core-ubuntu-noble-xfce:dev
endif

.PHONY: build run smoke lint clean recipes catalogs image-readmes

# Materialise Dockerfile.generated for every recipe: manifest (gitignored;
# CI regenerates them in the generate stage).
recipes:
	uv run ci/generate_pipeline.py

# Regenerate both picker catalogs, then validate them against the
# vendored waas schema (ci/schema/v1.schema.json — see ci/schema/
# README.md). Local twin of the CI validation in build.yml's catalog
# job and catalog-kasmweb.yml. The kasm generator hits Docker Hub
# best-effort (knownVersion fallback); generate_catalog.py never checks
# that image refs exist — this target checks the FORMAT, not the tags.
catalogs: recipes
	uv run ci/generate_catalog.py --registry $(REGISTRY)
	uv run ci/generate_kasm_catalog.py
	uv run ci/validate_catalog.py catalog-waas-images.yaml catalog-kasmweb.yaml

# Regenerate the per-image README committed under docs/images/ (the
# org.opencontainers.image.documentation label/annotation points there).
image-readmes: recipes
	uv run ci/generate_image_readme.py

build: recipes
	docker build $(ARGS) $(if $(wildcard $(CTX)/Dockerfile.generated),-f $(CTX)/Dockerfile.generated) -t $(TAG) $(CTX)

run: build
	docker run --rm -it \
		--read-only --cap-drop ALL --security-opt no-new-privileges \
		--tmpfs /tmp --tmpfs /run --tmpfs /home/waas_user:mode=1777 \
		-p 15901:5901 -p 13389:3389 \
		-e VNC_PW=devpassword -e WAAS_RDP_ENABLED=$(if $(findstring full,$(IMAGE)),1,0) \
		$(TAG)

smoke: build
	SMOKE_IMAGE=$(TAG) SMOKE_HOST=localhost SMOKE_VNC=1 sh ci/smoke_test.sh

lint: recipes
	hadolint --failure-threshold warning $$(find . -name Dockerfile -o -name Dockerfile.generated)
	shellcheck ci/*.sh base/*/rootfs/usr/local/bin/* $$(find . -path '*/entrypoint.d/*.sh')

clean:
	docker rmi -f $(TAG) 2>/dev/null || true
