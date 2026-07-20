<!-- Paired with README.md § "Try it standalone": GHCR package pages
render the repo README, Docker Hub renders this template — the command
blocks must stay identical (locked by
ci/tests/test_publish_dockerhub_readme.py, {image} <-> the generic
docker.io/xorhub/<image>:<version> ref). -->
**Hardened, non-root workspace image for [WaaS](https://github.com/XoRHub/waas) — a self-hosted platform that streams browser-accessible desktops and apps from Kubernetes.**

Source, build pipeline and the durable usage contract (every `WAAS_*` env var, port and protocol): [XoRHub/waas-images](https://github.com/XoRHub/waas-images).

{about}

# Try it standalone

No platform needed to evaluate the image — it runs under the same constraints WaaS enforces in-cluster (non-root, read-only rootfs, every capability dropped):

```shell
docker run --rm -it \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp --tmpfs /run --tmpfs /home/waas_user:mode=1777 \
  -p 5901:5901 -e WAAS_DESKTOP_PASSWORD=changeme \
  {image}
```

Then point any VNC client at `localhost:5901` (password `changeme`).

# Supply chain

Multi-arch manifest list, cosign-signed (keyless OIDC) with a CycloneDX SBOM attested to the image itself:

```shell
cosign verify {image} \
  --certificate-identity-regexp 'github.com/XoRHub/waas-images' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
cosign verify-attestation --type cyclonedx {image} \
  --certificate-identity-regexp 'github.com/XoRHub/waas-images' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Versioning: immutable `X.Y.Z` tags, one `X.Y.Z-g<sha>-<arch>` tag per architecture behind each release. See [HARDENING.md](https://github.com/XoRHub/waas-images/blob/main/HARDENING.md) for the full threat model and known gaps.
