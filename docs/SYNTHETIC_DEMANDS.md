# Synthetic Demand Input

`synthetic_demands_v0.csv` is a mechanics fixture, not a user Demand dataset.
It is generated from observed AI-Hub health-food candidate Catalog IDs so the
ERD lookup path can be exercised without inventing product facts.

```powershell
$env:PYTHONPATH = "src"
python scripts/demand/generate_synthetic_demands.py `
  --catalog data/processed/product_catalog/product_catalog_health_food_subset_v0.parquet `
  --output data/synthetic/demands/synthetic_demands_v0.csv `
  --count 30 `
  --seed 42
```

The generator writes `synthetic=true` and a `source_note` to every row.
Price, quantity, substitutability, and natural-language requirements are test
scenario values; they are not observed product or consumer facts. The output
is ignored by Git and can be regenerated deterministically.

To label the input after an approved taxonomy is available:

```powershell
$env:PYTHONPATH = "src"
python scripts/labeling/label_demands.py `
  --input data/synthetic/demands/synthetic_demands_v0.csv `
  --taxonomy data/processed/facet_discovery/facet_taxonomy_v0.json `
  --output data/processed/demands/demand_labeled_v0.csv
```

The current AI-Hub exploratory taxonomy must not be presented as a
health-functional-food taxonomy. Until MFDS-backed taxonomy data is approved,
unmatched synthetic requirements should remain in the review queue.
