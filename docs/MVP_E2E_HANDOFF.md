# Local MVP E2E Handoff

## Flow

```text
Product / Category / Facet / Demand Labeling
  -> clustering_input_grounded_5000_v1.csv
  -> demand_clusters_v0.csv
  -> seller_offer_matches_v0.csv
  -> seller_demand_analysis_v0.csv
```

The local baseline is CSV-only. It does not connect to PostgreSQL, call an LLM,
or infer an exact catalog identity from fuzzy seller text.

`scripts/e2e/run_mvp_local_e2e.py` covers the B -> C leg only. It starts from an
already labeled demand CSV; the Part A parser and the A -> B input generator
(`scripts/demand/build_part_a_b_clustering_input.py`) are not run here.

## Run

Choose the input explicitly. There is no implicit default: giving only one of
`--input` / `--offers`, or mixing them with `--example`, exits with code 2 before
any output is written. A missing input file fails with `FileNotFoundError`.

### Synthetic samples

From the repository root, no data preparation needed:

```bash
python scripts/e2e/run_mvp_local_e2e.py --example --output-dir /tmp/e2e-smoke
```

The printed summary includes `mode`, `input` and `offers_file`, so the source of a
run is visible. The samples live in `data/samples/e2e/`; the README there lists the
expected candidate/review result of each offer.

### Your own files

Both files are required. The paths below are local processed exports; they are
not committed to the repository:

```bash
python scripts/e2e/run_mvp_local_e2e.py \
  --input data/processed/demand_5000_catalog_seed_v1/part_a_runtime_v2_2_6/clustering_input_grounded_5000_v2_2_6.csv \
  --offers data/processed/domeggook/seller_offers_core.csv \
  --output-dir data/processed/mvp_e2e_v1
```

Outputs:

- `demand_clusters_v0.csv`: one row per labeled demand with stable `cluster_id`
- `demand_cluster_summary_v0.csv`: participant and quantity totals
- `seller_offer_matches_v0.csv`: transparent category/MOQ/price candidate score
- `seller_demand_analysis_v0.csv`: seller-facing cluster summary

## Shared Files

The first handoff should include:

- `clustering_input_grounded_5000_v1.csv`
- `clustering_ground_truth_metadata_5000_v1.csv` (evaluation only, never a cluster feature)
- `demand_5000_quality_report_v1.csv`
- `config/facet_taxonomy_v2_2.json` and its version/status
- `seller_offers_core.csv` plus its source/provenance report
- `docs/MVP_E2E_HANDOFF.md`

Do not share `.env`, API keys, raw review text, or ignored bulk datasets through
GitHub. Share local paths or approved processed exports instead.

## Boundary Rules

- `is_substitutable=false`: requested catalog remains part of the cluster key.
- `is_substitutable=true`: same category and label can share a cluster across catalogs.
- `ALL` remains a valid facet code and is not treated as a wildcard string in the baseline.
- Price and MOQ are matching constraints, not Facets.
- Exact Product/Catalog identity is unresolved when the seller source lacks a canonical ID.
- Synthetic rows remain marked as synthetic and are not production consumer demand.
