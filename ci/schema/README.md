# Vendored WaaS catalog JSON Schema

`v1.schema.json` is vendored byte-for-byte from the `waas` repo
(`operator/pkg/catalog/schema/v1.schema.json`, commit `db503cb8d30f`) —
**`waas` is the source of truth** for the wire format (see its
`docs/image-catalog.md` § "Wire format and schema"). The schema is
generated there from the Go structs `catalog.File`/`catalog.Entry`, so
it can never drift from the actual parser.

The `v1` contract is frozen/additive-only by `waas`'s own discipline,
so silent drift risk is low. To re-sync: copy the file from `waas`
`main` unchanged and update the commit SHA above. If `waas` ever
publishes a `v2.schema.json`, vendor it alongside this one and branch
`ci/validate_catalog.py` on `apiVersion`.
