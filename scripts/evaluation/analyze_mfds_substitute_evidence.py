from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from moongcheap_ai.demand_clustering.evaluation.evidence_analysis import (
    analyze_substitute_evidence,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile MFDS evidence for substitute-product AI design"
    )
    parser.add_argument(
        "--products",
        type=Path,
        default=Path(
            "data/interim/facet_discovery/i0030_products_clean_dedup.csv"
        ),
    )
    parser.add_argument(
        "--references",
        type=Path,
        default=Path("data/interim/facet_discovery/i2710_reference.csv"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/mfds_substitute_evidence_analysis_v2.json"),
    )
    parser.add_argument(
        "--unmatched-types",
        type=Path,
        default=Path(
            "data/reports/mfds_substitute_unmatched_product_types_v2.csv"
        ),
    )
    parser.add_argument(
        "--ingredient-issues",
        type=Path,
        default=Path(
            "data/reports/mfds_substitute_ingredient_linkage_issues_v2.csv"
        ),
    )
    parser.add_argument(
        "--function-divergence",
        type=Path,
        default=Path(
            "data/reports/mfds_substitute_function_divergence_v2.csv"
        ),
    )
    args = parser.parse_args()

    products = pd.read_csv(args.products, dtype=str, keep_default_na=False)
    references = pd.read_csv(
        args.references, dtype=str, keep_default_na=False
    )
    summary, unmatched_types, ingredient_issues, divergence = (
        analyze_substitute_evidence(products, references)
    )
    for path in (
        args.report,
        args.unmatched_types,
        args.ingredient_issues,
        args.function_divergence,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    unmatched_types.to_csv(
        args.unmatched_types, index=False, encoding="utf-8-sig"
    )
    ingredient_issues.to_csv(
        args.ingredient_issues, index=False, encoding="utf-8-sig"
    )
    divergence.to_csv(
        args.function_divergence, index=False, encoding="utf-8-sig"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
