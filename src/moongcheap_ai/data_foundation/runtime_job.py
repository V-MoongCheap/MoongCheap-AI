"""Connection-ready A labeling runtime with CSV dry-run support."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from dotenv import load_dotenv

from ..mvp_pipeline import ReviewedAliasMatcher, _apply_aliases
from .backend_contract import build_label_result_payload, post_label_results
from .labeling import build_product_facet_map, label_demands, load_taxonomy
from .postgres_reader import open_read_only_postgres, read_unprocessed_demands


def _required(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def run_batch(
    demands: pd.DataFrame,
    taxonomy_path: Path,
    *,
    product_facets_path: Path | None = None,
    alias_registry_path: Path | None = None,
    processed_at: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    loader = load_taxonomy(taxonomy_path)
    facet_map = None
    if product_facets_path and product_facets_path.exists():
        facet_map = build_product_facet_map(pd.read_csv(product_facets_path, dtype=str).fillna(""))
    labeled = label_demands(demands.fillna(""), loader, product_facet_map=facet_map)
    if alias_registry_path and alias_registry_path.exists():
        labeled, alias_hits, corrected_alias_hits, alias_conflicts = _apply_aliases(
            labeled, ReviewedAliasMatcher(alias_registry_path)
        )
        labeled["taxonomy_version"] = "v2.2"
        labeled["alias_hits"] = alias_hits
        labeled["corrected_alias_hits"] = corrected_alias_hits
        labeled["alias_conflicts"] = alias_conflicts
    timestamp = processed_at or datetime.now(timezone.utc).isoformat()
    return labeled, build_label_result_payload(labeled, processed_at=timestamp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the A Demand labeling batch")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--input", type=Path, help="CSV dry-run input")
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--product-facets", type=Path)
    parser.add_argument("--alias-registry", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/processed/demands/runtime_labeled_v0.csv"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    source = os.environ
    taxonomy_path = args.taxonomy or Path(source.get("A_TAXONOMY_PATH", "config/facet_taxonomy_v2_2.json"))
    if not taxonomy_path.is_file():
        raise SystemExit(f"taxonomy file not found: {taxonomy_path}")

    connection = None
    try:
        if args.input:
            demands = pd.read_csv(args.input, dtype=str)
        else:
            connection = open_read_only_postgres(_required(source, "A_DATABASE_URL"))
            demands = read_unprocessed_demands(connection)
        labeled, payload = run_batch(
            demands,
            taxonomy_path,
            product_facets_path=args.product_facets or (Path(source["A_PRODUCT_FACETS_PATH"]) if source.get("A_PRODUCT_FACETS_PATH") else None),
            alias_registry_path=args.alias_registry or Path(source.get("A_ALIAS_REGISTRY_PATH", "config/model1_aliases_reviewed_v2.json")),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        labeled.to_csv(args.output, index=False, encoding="utf-8-sig")
        if not args.dry_run:
            response = post_label_results(
                _required(source, "A_BACKEND_BASE_URL"),
                _required(source, "A_BACKEND_INTERNAL_KEY"),
                _required(source, "A_LABEL_RESULT_ENDPOINT"),
                payload,
                timeout_seconds=int(source.get("A_BACKEND_HTTP_TIMEOUT_SECONDS", "15")),
            )
        else:
            response = {"status": "DRY_RUN"}
        print(json.dumps({"status": "COMPLETED", "rows": len(labeled), "output": str(args.output), "backend": response}, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
