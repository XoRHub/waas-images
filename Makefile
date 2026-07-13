# Local developer loop. CI uses ci/*.sh directly; these targets wrap the
# same scripts so local == CI.
#
#   make build IMAGE=ubuntu-base-vnc
#   make run   IMAGE=ubuntu-base-vnc     # then connect a VNC client to :15901
#   make smoke IMAGE=ubuntu-base-vnc
#   make lint
#   make catalogs    # regenerate + schema-validate both picker catalogs
#
# Python tooling runs through uv: each ci/*.py script declares its own
# pinned dependencies inline (PEP 723 `# /// script` block), so uv is
# the only local prerequisite — no pip install, no venv to manage.

IMAGE      ?= ubuntu-base-vnc
REGISTRY   ?= waas-local
TAG        := $(REGISTRY)/$(IMAGE):dev

# Map variant -> context + build args (local mirror of the manifests).
ifeq ($(IMAGE),ubuntu-base-vnc)
  CTX := base/ubuntu
  ARGS := --build-arg INSTALL_RDP=0
else ifeq ($(IMAGE),ubuntu-base-rdp)
  CTX := base/ubuntu
  ARGS := --build-arg INSTALL_RDP=1
else ifeq ($(IMAGE),ubuntu-xfce)
  CTX := desktop/xfce
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/ubuntu-base-rdp:dev
else ifeq ($(IMAGE),ubuntu-firefox)
  CTX := apps/firefox
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/ubuntu-xfce:dev
else ifeq ($(IMAGE),dev-ssh)
  CTX := apps/dev-ssh
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/ubuntu-base-vnc:dev
else ifeq ($(IMAGE),debian-base-vnc)
  CTX := base/ubuntu
  ARGS := --build-arg INSTALL_RDP=0 --build-arg OS_BASE_IMAGE=debian:13-slim
else ifeq ($(IMAGE),debian-base-rdp)
  CTX := base/ubuntu
  ARGS := --build-arg INSTALL_RDP=1 --build-arg OS_BASE_IMAGE=debian:13-slim
else ifeq ($(IMAGE),debian-xfce)
  CTX := desktop/xfce
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/debian-base-rdp:dev
else ifeq ($(IMAGE),fedora-base-vnc)
  CTX := base/fedora
  ARGS := --build-arg INSTALL_RDP=0
else ifeq ($(IMAGE),fedora-base-rdp)
  CTX := base/fedora
  ARGS := --build-arg INSTALL_RDP=1
else ifeq ($(IMAGE),fedora-xfce)
  CTX := desktop/xfce-fedora
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/fedora-base-rdp:dev
else ifeq ($(IMAGE),ubuntu-devtools)
  CTX := apps/devtools
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/ubuntu-xfce:dev
else ifeq ($(IMAGE),ubuntu-devtools-dev)
  CTX := apps/devtools
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/ubuntu-xfce:dev --build-arg INSTALL_SUDO=1 --build-arg WAAS_PROFILE=dev
else ifeq ($(IMAGE),ubuntu-libreoffice)
  CTX := apps/libreoffice
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/ubuntu-xfce:dev
else ifeq ($(IMAGE),ubuntu-chrome)
  CTX := apps/chrome
  ARGS := --build-arg BASE_IMAGE=$(REGISTRY)/ubuntu-xfce:dev
endif

.PHONY: build run smoke lint clean recipes catalogs

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

build: recipes
	docker build $(ARGS) $(if $(wildcard $(CTX)/Dockerfile.generated),-f $(CTX)/Dockerfile.generated) -t $(TAG) $(CTX)

run: build
	docker run --rm -it \
		--read-only --cap-drop ALL --security-opt no-new-privileges \
		--tmpfs /tmp --tmpfs /run --tmpfs /home/waas_user:mode=1777 \
		-p 15901:5901 -p 13389:3389 \
		-e VNC_PW=devpassword -e WAAS_RDP_ENABLED=$(if $(findstring rdp,$(IMAGE)),1,0) \
		$(TAG)

smoke: build
	SMOKE_IMAGE=$(TAG) SMOKE_HOST=localhost SMOKE_VNC=1 sh ci/smoke_test.sh

lint: recipes
	hadolint --failure-threshold warning $$(find . -name Dockerfile -o -name Dockerfile.generated)
	shellcheck ci/*.sh base/*/rootfs/usr/local/bin/* $$(find . -path '*/entrypoint.d/*.sh')

clean:
	docker rmi -f $(TAG) 2>/dev/null || true
