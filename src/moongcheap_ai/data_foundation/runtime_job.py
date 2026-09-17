"""Connection-ready A labeling runtime with CSV dry-run support."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from .backend_contract import build_label_result_payload, post_label_results
from .labeling import (
    taxonomy_from_category_facet_rows,
)
from .part_a_runtime import run_part_a_batch
from .postgres_reader import open_read_only_postgres, read_unprocessed_demands
from .postgres_writer import open_postgres, write_label_results


def _required(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def run_batch(
    demands: pd.DataFrame,
    taxonomy_path: Path | None,
    *,
    taxonomy_payload: dict[str, Any] | None = None,
    product_facets_path: Path | None = None,
    alias_registry_path: Path | None = None,
    rules_path: Path = Path("config/demand_constraint_rules.json"),
    compatibility_alias_registry_path: Path | None = None,
    processed_at: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    timestamp = processed_at or datetime.now(UTC).isoformat()
    if demands.empty:
        empty = demands.copy()
        for column in ("demand_id", "catalog_id", "category_id", "label", "facet_values", "label_status"):
            if column not in empty.columns:
                empty[column] = pd.Series(dtype="string")
        return empty, {
            "schemaVersion": "demand-label-result.v0.1",
            "processedAt": timestamp,
            "results": [],
        }
    if taxonomy_payload is None and taxonomy_path is None:
        raise ValueError("taxonomy_path or taxonomy_payload is required")
    # Product facts describe the selected catalog; they must not silently turn
    # into consumer requirements. The shared Part A parser emits only typed
    # constraints from extra_requirement and keeps unresolved requests pending.
    del product_facets_path
    labeled, _ = run_part_a_batch(
        demands,
        taxonomy_path,
        rules_path,
        alias_registry_path or Path("config/model1_aliases_reviewed_v2.json"),
        taxonomy_payload=taxonomy_payload,
        compatibility_alias_registry_path=compatibility_alias_registry_path,
        processed_at=timestamp,
        skip_processed=False,
    )
    labeled["label_status"] = labeled["status"].map({
        "PARSED": "LABELED",
        "NONE": "LABELED",
        "NOT_APPLICABLE": "LABELED",
    }).fillna("REVIEW")
    labeled["label_warnings"] = labeled["reasonCodes"]
    return labeled, build_label_result_payload(labeled, processed_at=timestamp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the A Demand labeling batch")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--input", type=Path, help="CSV dry-run input")
    parser.add_argument("--taxonomy", type=Path)
    parser.add_argument("--product-facets", type=Path)
    parser.add_argument("--alias-registry", type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--compatibility-alias-registry", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/processed/demands/runtime_labeled_v0.csv"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="write completed labels directly to PostgreSQL; mutually exclusive with Backend submission",
    )
    args = parser.parse_args(argv)
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    source = os.environ
    taxonomy_path = args.taxonomy or Path(source.get("A_TAXONOMY_PATH", "config/facet_taxonomy_v2_2.json"))

    connection = None
    write_to_database = args.write_db or source.get("A_WRITE_DATABASE", "").strip().lower() in {"1", "true", "yes"}
    if args.dry_run and write_to_database:
        raise SystemExit("--dry-run cannot be combined with --write-db or A_WRITE_DATABASE=true")
    try:
        if args.input:
            demands = pd.read_csv(args.input, dtype=str)
        else:
            connection = (
                open_postgres(_required(source, "A_DATABASE_URL"))
                if write_to_database
                else open_read_only_postgres(_required(source, "A_DATABASE_URL"))
            )
            demands = read_unprocessed_demands(connection)
        taxonomy_payload = None
        if not args.input and "category_facet" in demands.columns and not demands.empty:
            taxonomy_payload = taxonomy_from_category_facet_rows(demands)
        if taxonomy_payload is None and not demands.empty and not taxonomy_path.is_file():
            raise SystemExit(f"taxonomy file not found: {taxonomy_path}")
        primary_alias_registry = args.alias_registry or Path(
            source.get("A_ALIAS_REGISTRY_PATH", "config/model1_aliases_reviewed_v2.json")
        )
        compatibility_alias_registry = args.compatibility_alias_registry or Path(
            source.get("A_COMPATIBILITY_ALIAS_REGISTRY_PATH", "config/demand_constraint_aliases.json")
        )
        # The reviewed A alias export is version-bound to v2.2. A taxonomy
        # reconstructed from Backend category.facet must use its own values
        # until Backend publishes the matching reviewed alias export.
        if taxonomy_payload is not None and taxonomy_payload.get("version") != "v2.2":
            primary_alias_registry = None
            compatibility_alias_registry = None
        labeled, payload = run_batch(
            demands,
            taxonomy_path,
            taxonomy_payload=taxonomy_payload,
            product_facets_path=args.product_facets or (Path(source["A_PRODUCT_FACETS_PATH"]) if source.get("A_PRODUCT_FACETS_PATH") else None),
            alias_registry_path=primary_alias_registry,
            rules_path=args.rules or Path(source.get("A_RULES_PATH", "config/demand_constraint_rules.json")),
            compatibility_alias_registry_path=compatibility_alias_registry,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        labeled.to_csv(args.output, index=False, encoding="utf-8-sig")
        if write_to_database:
            if connection is None:
                connection = open_postgres(_required(source, "A_DATABASE_URL"))
            written = write_label_results(
                connection,
                labeled.to_dict(orient="records"),
                processed_at=payload["processedAt"],
            )
            response = {"status": "DB_APPLIED", "updatedCount": written}
        elif not args.dry_run:
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
