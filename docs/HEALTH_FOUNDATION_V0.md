# Health Foundation V0

The health foundation candidates are built from the local MFDS I0030 processed
corpus. They are review artifacts, not approved service categories or
production taxonomy.

```powershell
$env:PYTHONPATH = "src"
python scripts/facet/build_health_artifacts.py
```

Outputs are written under `data/processed/health_foundation/`:

- `category_source_analysis.csv`: observed MFDS product classifications and counts
- `category_v0.csv`: service-category candidates with intentionally blank IDs
- `product_category_mapping_review.csv`: product-to-category review queue
- `product_catalog_v0.csv`: candidate Catalog rows preserving source IDs separately
- `catalog_source_mapping.csv`: candidate Catalog to source mapping
- `taxonomy_review_v0.csv`: category/facet/value candidates with product evidence
- `taxonomy_candidate_v0.json`: draft category-specific taxonomy candidates

Missing source categories remain in the Product Catalog candidate and are marked
`BLOCKED_MISSING_SOURCE_CATEGORY`; they are not silently discarded. Final
category IDs, Value Codes, aliases, mappings, and Facet approval require review.
