from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.grounded_demand import generate_grounded_demands


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate catalog-bound synthetic Demand rows from local expression references")
    parser.add_argument("--products", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--mapping", type=Path, default=Path("data/processed/category_v2_1/product_service_category_mapping_v2_1.csv"))
    parser.add_argument("--taxonomy", type=Path, default=Path("data/processed/downstream_v2_1/taxonomy_review_v2_1.csv"))
    parser.add_argument("--xpqa", type=Path, default=Path("data/raw/consumer_reference/xpqa/xPQA"))
    parser.add_argument("--esci", type=Path, default=Path("data/processed/esci/queries.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/synthetic/consumer_reference/grounded_demand_v1.csv"))
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    required = [args.products, args.mapping, args.taxonomy, args.xpqa, args.esci]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("missing local input: " + ", ".join(missing))
    result = generate_grounded_demands(args.products, args.mapping, args.taxonomy, args.xpqa, args.esci, args.count, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    print({"status": "COMPLETED", "rows": len(result), "output": str(args.output), "reference_sources": result["reference_source"].value_counts().to_dict()})


if __name__ == "__main__":
    main()
