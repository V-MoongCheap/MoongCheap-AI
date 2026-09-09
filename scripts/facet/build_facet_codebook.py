from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from moongcheap_ai.data_foundation.facet_codebook import build_clustering_input, load_codebook


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a versioned facet codebook and clustering input")
    parser.add_argument("--taxonomy", type=Path, default=Path("data/processed/downstream_v2_1/taxonomy_candidate_v2_1.json"))
    parser.add_argument("--labeled", type=Path, default=Path("data/processed/consumer_reference/grounded_demand_labeled_with_product_facets_v2.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/facet_codebook_v2_1"))
    parser.add_argument("--version", default="v2.1")
    args = parser.parse_args()
    if not args.taxonomy.exists() or not args.labeled.exists():
        raise SystemExit(f"missing input: taxonomy={args.taxonomy.exists()}, labeled={args.labeled.exists()}")
    codebook = load_codebook(args.taxonomy, args.version)
    labeled = pd.read_csv(args.labeled, dtype=str)
    clustering = build_clustering_input(labeled, codebook)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    codebook.to_csv(args.output_dir / "facet_value_codebook_v2_1.csv", index=False, encoding="utf-8-sig")
    clustering.to_csv(args.output_dir / "clustering_input_v2_1.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "facet_codebook_summary.json").write_text(json.dumps({
        "taxonomy_version": args.version,
        "category_count": int(codebook["category_id"].nunique()),
        "facet_count": int(codebook[["category_id", "facet_name"]].drop_duplicates().shape[0]),
        "value_count": len(codebook),
        "demand_count": len(clustering),
        "all_value_code": 0,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"status": "COMPLETED", "codebook_rows": len(codebook), "clustering_rows": len(clustering), "output_dir": str(args.output_dir)})


if __name__ == "__main__":
    main()
