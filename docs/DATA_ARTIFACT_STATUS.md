# Data Artifact Status

| Artifact | Status | Intended use |
|---|---|---|
| `data/interim/products/product_staging.parquet` | Usable | AI-Hub normalized staging |
| `data/processed/product_catalog/product_catalog_v1.parquet` | Usable with caveats | Observed AI-Hub catalog and provenance |
| `data/processed/category/category_master_v1.csv` | Observed-only | KAN source exploration, not official master |
| `data/processed/facet_discovery/aihub_exploratory_facet_taxonomy_v0.json` | Exploratory only | AI-Hub logistics analysis; not health taxonomy |
| `data/processed/demands/demand_labeled_v0.csv` | Test-only | Temporary mechanics test; not a health result |
| `data/processed/category/health_category_seed_v0.csv` | Pending | Requires valid MFDS rows |
| `data/reports/mfds_status.json` | Failed/Pending | Must reflect the latest MFDS collection attempt |

Generated data and raw files are ignored by Git. Only code, tests, and documentation should be committed to the repository.

The AI-Hub source has 6,382 barcode-format-invalid observations. They remain in staging for auditability, but are excluded from barcode identity grouping.
