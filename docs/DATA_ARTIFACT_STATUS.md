# Data Artifact Status

| Artifact | Status | Intended use |
|---|---|---|
| `data/interim/products/product_staging.parquet` | Usable | AI-Hub normalized staging |
| `data/processed/backend_seed_v5/product_catalog_seed_v5.csv` | Seed / local-only | Product Catalog candidate with Seed IDs; not Backend production IDs |
| `data/processed/backend_seed_v5/category_seed_v5.csv` | Seed / local-only | Category candidate with Seed IDs; not Backend production IDs |
| `data/interim/facet_discovery/i0030_products_clean_dedup.csv` | Partial | MFDS product facts; not an approved taxonomy |
| `data/interim/facet_evidence_v3/facet_evidence_unified.parquet` | Evidence / local-only | Unified evidence; category-scoped non-product evidence is supplementary |
| `data/processed/model2_gold_v1/model2_gold_runtime_input_v2_2_5.csv` | Test-only | Demand Labeling evaluation/runtime candidate, not production user Demand |
| `config/facet_taxonomy_v2_2.json` | Reviewed candidate | Current taxonomy contract; changes still require Human Review |
| `data/reports/mfds_status.json` | Failed/Pending | Must reflect the latest MFDS collection attempt |

Generated data and raw files are ignored by Git. Only code, tests, and documentation should be committed to the repository.

The AI-Hub source has 6,382 barcode-format-invalid observations. They remain in staging for auditability, but are excluded from barcode identity grouping.
