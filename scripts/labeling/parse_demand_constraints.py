from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.labeling import load_taxonomy
from moongcheap_ai.demand_constraints import (
    DemandConstraintParser,
    parse_demand_constraints,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Korean demand requirements into typed constraints"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/synthetic/demands/synthetic_demands_v0.csv"),
    )
    parser.add_argument(
        "--taxonomy",
        type=Path,
        default=Path("data/processed/facet_discovery/facet_taxonomy_v0.json"),
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("config/demand_constraint_rules.json"),
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=Path("config/demand_constraint_aliases.json"),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        help="Product catalog CSV or Parquet containing id and category_id",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/demands/demand_constraints_v1.csv"),
    )
    parser.add_argument(
        "--diagnostic-output",
        "--review-output",
        dest="diagnostic_output",
        type=Path,
        default=Path("data/processed/demands/demand_constraint_diagnostics_v1.csv"),
        help=(
            "Diagnostic CSV for REVIEW, CONFLICT, or TAXONOMY_AMBIGUOUS rows "
            "(--review-output is retained as a compatibility alias)"
        ),
    )
    args = parser.parse_args()

    for path, label in (
        (args.input, "input demand"),
        (args.taxonomy, "taxonomy"),
        (args.rules, "constraint rules"),
        (args.aliases, "constraint aliases"),
    ):
        if not path.exists():
            raise SystemExit(f"{label} file not found: {path}")

    demands = pd.read_csv(args.input, dtype=str).fillna("")
    catalog_map = None
    if args.catalog:
        if not args.catalog.exists():
            raise SystemExit(f"catalog file not found: {args.catalog}")
        catalog = (
            pd.read_parquet(args.catalog)
            if args.catalog.suffix.lower() == ".parquet"
            else pd.read_csv(args.catalog, dtype=str)
        )
        id_column = (
            "id"
            if "id" in catalog.columns
            else "catalog_seed_id"
            if "catalog_seed_id" in catalog.columns
            else None
        )
        if not id_column or "category_id" not in catalog.columns:
            raise SystemExit(
                "catalog must contain id (or catalog_seed_id) and category_id"
            )
        catalog_map = dict(
            zip(catalog[id_column].astype(str), catalog["category_id"].astype(str))
        )

    taxonomy = load_taxonomy(args.taxonomy)
    constraint_parser = DemandConstraintParser.from_taxonomy(
        taxonomy.taxonomy,
        rules_path=args.rules,
        aliases_path=args.aliases,
    )
    result = parse_demand_constraints(demands, constraint_parser, catalog_map)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")

    diagnostics = result[
        result["constraint_status"].isin(
            {"REVIEW", "CONFLICT", "TAXONOMY_AMBIGUOUS"}
        )
    ].copy()
    args.diagnostic_output.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(args.diagnostic_output, index=False, encoding="utf-8-sig")

    print({
        "rows": len(result),
        "parsed_rows": int((result["constraint_status"] == "PARSED").sum()),
        "diagnostic_rows": len(diagnostics),
        "output": str(args.output),
        "diagnostic_output": str(args.diagnostic_output),
    })


if __name__ == "__main__":
    main()
