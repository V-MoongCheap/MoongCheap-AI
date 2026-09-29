# A Labeling DB schema compatibility

## Current Backend schema

The current Backend migration does **not** define `product_catalog.category_id`.
The category cannot be inferred safely from a product name or from the numeric
IDs, so the A batch must not issue a hard-coded join on that column.

At runtime, A first probes the schema:

- If `product_catalog.category_id` exists, the batch uses the direct
  `product_catalog -> category` join.
- If it does not exist, the batch requires an authoritative CSV mapping and
  loads `category.facet` using the real Backend category IDs.

## Mapping file

Set `A_CATALOG_CATEGORY_MAP_PATH` to a UTF-8 CSV mounted into the A job. The
file must contain exactly these identifying columns:

```csv
catalog_id,category_id
3901,17
```

- `catalog_id` must be the actual `product_catalog.id` in the target DB.
- `category_id` must be the actual `category.id` in the target DB.
- AI taxonomy keys such as `health-functional-food:probiotics` must not be put
  in `category_id`.

The batch fails with a diagnostic error when the mapping is missing, incomplete,
conflicting, or points to a category without `facet`. It never guesses a
relationship from names or sequential IDs.
