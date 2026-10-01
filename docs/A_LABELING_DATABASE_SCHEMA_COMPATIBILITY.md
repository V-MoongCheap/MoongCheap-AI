# A Labeling DB schema compatibility

## Runtime behavior

Backend migration history and deployed database state may differ between environments.
Do not assume `product_catalog.category_id` exists (or is populated) based only on a
migration file, and never infer a Catalog–Category relationship from names or numeric IDs.

Before reading the pending batch, A probes the connected database schema:

- If `product_catalog.category_id` exists, A joins `product_catalog.category_id` to
  the actual `category.id` and reads the full `category.facet` text.
- If the column is absent, A requires an authoritative mapping CSV and uses its actual
  Backend `catalog_id` and `category_id` values to read `category.facet`.
- If a required mapping, Category row, or `facet` value is missing or conflicting, A
  stops before labeling; it does not guess or mark those Demands processed.

The schema probe and both query paths are covered by automated tests. Confirm the
specific dev/prod database state separately when diagnosing deployment issues.

## Mapping file (legacy schema only)

Set `A_CATALOG_CATEGORY_MAP_PATH` to a UTF-8 CSV mounted into the A job. It must include
these columns; additional columns are ignored:

```csv
catalog_id,category_id
3901,17
```

- `catalog_id` must be the actual `product_catalog.id` in the target DB.
- `category_id` must be the actual `category.id` in the target DB.
- AI taxonomy keys such as `health-functional-food:probiotics` must not be put
  in `category_id`.
- Every Catalog referenced by the current pending batch must have exactly one
  unambiguous Category mapping.

Conflicting duplicate mappings, missing Catalog mappings, or Categories without
`facet` cause an explicit error. Identical duplicate rows are harmless.
