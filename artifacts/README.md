# Runtime-only A product Facet artifact

The trusted release pipeline must stage `product_facets.csv` in this directory
before building a deployable A Labeling image. The file is intentionally not
versioned in Git. It must use actual Backend `product_catalog.id` values in
`backend_catalog_id` and the stable category key stored inside the matching
`category.facet` JSON.

Each row represents evidence for one Facet. A product does not need a confirmed
value for every Taxonomy Facet: `MAPPED` values are retained, while
`UNKNOWN`/`AMBIGUOUS`/`UNMAPPED` evidence and absent Facet rows leave only that
label position at code `0` (`ALL`). This does not claim the product has a known
`ALL` property. Conflicting duplicates, invalid mapped values, a missing whole
product profile, or category mismatch must remain unprocessed. See
`docs/A_LABELING_RUNTIME_HANDOFF.md` for the full contract.

The Docker build includes this directory when the release CSV is staged. Git and
Jenkins SCM checkout do not provide this ignored file by themselves; the release
pipeline must explicitly stage it and record its SHA-256. The A Docker build now
fails if the file is absent or empty, preventing a deployable image from being
produced without its required input. A database labeling run also validates the
artifact even when the selected batch has zero demands, so absence cannot be
hidden by a successful empty run. Verify the exact artifact hash inside the
image before deployment.
