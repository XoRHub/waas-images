# Vendored WaaS catalog JSON Schema

`v1.schema.json` is vendored byte-for-byte from the `waas` repo
(`shared/catalog/schema/v1.schema.json`, commit `dd9f6cd7beaf`) —
**`waas` is the source of truth** for the wire format (see its
`docs/image-catalog.md` § "Wire format and schema"). The schema is
generated there from the Go structs `catalog.File`/`catalog.Entry`, so
it can never drift from the actual parser. The generator lived under
`operator/pkg/catalog/schema/` before `waas` commit `3581fffc095e`
moved it to `shared/catalog/schema/`.

The `v1` contract is frozen/additive-only by `waas`'s own discipline,
so silent drift risk is low. To re-sync by hand: copy the file from
`waas` `main` unchanged and update the commit SHA above.

`.github/workflows/catalog-schema-sync.yml` also checks weekly (plus
`workflow_dispatch`) for drift and opens a PR — never merges it
automatically, since a schema change can be breaking — via
`ci/sync_schema.sh`. That script is the authoritative re-sync
procedure; the by-hand steps above are only for running it locally or
understanding what it does.

If `waas` ever publishes a `v2.schema.json`, vendor it alongside this
one and branch `ci/validate_catalog.py` on `apiVersion`.
