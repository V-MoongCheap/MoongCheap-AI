# Runtime-only A product Facet artifact

Before building a deployable A Labeling image, the trusted release pipeline must
stage `product_facets.csv` in this directory. The CSV is intentionally not
versioned in Git. It must contain the actual Backend `product_catalog.id` in
`backend_catalog_id`, use the category key embedded in `category.facet`, and
cover every Facet for each included catalog. `UNKNOWN` is distinct from `ALL`
and cannot be represented by the current numeric label contract, so a profile
containing `UNKNOWN` remains unprocessed rather than receiving a fabricated
`ALL` value. See
`docs/A_LABELING_RUNTIME_HANDOFF.md` for the full contract.

The Docker build includes this directory when the release CSV is staged. A build
without the CSV is useful for CI/code validation, but its image must fail closed
for a non-empty labeling batch; do not deploy it as a working A Labeling image.
