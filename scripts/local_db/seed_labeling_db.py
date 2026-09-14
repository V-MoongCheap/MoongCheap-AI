"""Create and seed a local Backend-compatible PostgreSQL fixture database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

SCHEMA_PATH = Path("local_db/schema.sql")
DEFAULT_INPUT = Path("data/processed/a_labeling_runtime_smoke.csv")
DEFAULT_TAXONOMY = Path("config/facet_taxonomy_v2_2.json")
DEFAULT_DSN = "postgresql://moongcheap:moongcheap@localhost:5433/moongcheap_ai_local"


def _required_text(row: pd.Series, column: str, default: str = "") -> str:
    value = row.get(column, default)
    if pd.isna(value):
        return default
    return str(value).strip()


def _int_value(row: pd.Series, column: str, default: int = 0) -> int:
    value = _required_text(row, column)
    if not value:
        return default
    return int(float(value))


def _bool_value(row: pd.Series, column: str) -> bool:
    return _required_text(row, column).lower() in {"true", "1", "t", "yes"}


def _load_inputs(input_path: Path, taxonomy_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(input_path, dtype=str, encoding="utf-8-sig").fillna("")
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    required = {"demand_id", "catalog_id", "category_id", "extra_requirement"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"input is missing columns: {', '.join(missing)}")
    return frame, taxonomy


def seed_database(
    dsn: str,
    *,
    input_path: Path = DEFAULT_INPUT,
    taxonomy_path: Path = DEFAULT_TAXONOMY,
    schema_path: Path = SCHEMA_PATH,
) -> dict[str, int]:
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("Install psycopg before seeding the local database") from error

    frame, taxonomy = _load_inputs(input_path, taxonomy_path)
    categories = taxonomy.get("categories", [])
    if not categories:
        raise ValueError("taxonomy contains no categories")

    category_keys = sorted({str(item["category_id"]) for item in categories})
    category_rows = {key: item for key, item in ((str(item["category_id"]), item) for item in categories)}
    category_names = {key: str(category_rows[key].get("category_name", key)) for key in category_keys}
    root_name = "건강기능식품"

    catalog_keys = sorted({_required_text(row, "catalog_id") for _, row in frame.iterrows()})
    catalog_key_to_id = {key: index + 1 for index, key in enumerate(catalog_keys)}
    demand_key_to_id = {
        _required_text(row, "demand_id"): index + 1 for index, (_, row) in enumerate(frame.iterrows())
    }

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(schema_path.read_text(encoding="utf-8"))
            cursor.execute(
                "INSERT INTO category (id, parent_id, name, depth, facet) VALUES (%s, NULL, %s, 1, %s)",
                (1, root_name, json.dumps({"category_id": "health-functional-food", "facets": []}, ensure_ascii=False)),
            )
            category_id_map: dict[str, int] = {}
            for offset, key in enumerate(category_keys, start=2):
                item = category_rows[key]
                category_id_map[key] = offset
                cursor.execute(
                    "INSERT INTO category (id, parent_id, name, depth, facet) VALUES (%s, %s, %s, %s, %s)",
                    (
                        offset,
                        1,
                        category_names[key],
                        2,
                        json.dumps({"category_id": key, "facets": item.get("facets", [])}, ensure_ascii=False),
                    ),
                )

            for catalog_key in catalog_keys:
                rows = frame.loc[frame["catalog_id"].astype(str) == catalog_key]
                row = rows.iloc[0]
                category_key = _required_text(row, "category_id")
                product_name = _required_text(row, "product_name", catalog_key)[:100] or catalog_key[:100]
                cursor.execute(
                    """
                    INSERT INTO product_catalog
                        (id, source_key, name, category_id, thumbnail_url, status)
                    VALUES (%s, %s, %s, %s, %s, 'ACTIVE')
                    """,
                    (
                        catalog_key_to_id[catalog_key],
                        catalog_key,
                        product_name,
                        category_id_map[category_key],
                        f"https://example.invalid/local-catalog/{catalog_key}",
                    ),
                )

            for _, row in frame.iterrows():
                demand_key = _required_text(row, "demand_id")
                catalog_key = _required_text(row, "catalog_id")
                cursor.execute(
                    """
                    INSERT INTO demand
                        (id, source_key, catalog_id, desired_price_max, desired_price_min,
                         quantity, extra_requirement, is_substitutable, label, processed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
                    """,
                    (
                        demand_key_to_id[demand_key],
                        demand_key,
                        catalog_key_to_id[catalog_key],
                        _int_value(row, "desired_price_max"),
                        _int_value(row, "desired_price_min"),
                        max(1, _int_value(row, "quantity", 1)),
                        _required_text(row, "extra_requirement")[:200] or None,
                        _bool_value(row, "is_substitutable"),
                    ),
                )

            cursor.execute("SELECT setval(pg_get_serial_sequence('category', 'id'), %s, true)", (len(category_keys) + 1,))
            cursor.execute("SELECT setval(pg_get_serial_sequence('product_catalog', 'id'), %s, true)", (len(catalog_keys),))
            cursor.execute("SELECT setval(pg_get_serial_sequence('demand', 'id'), %s, true)", (len(frame),))

    return {
        "category_count": len(category_keys) + 1,
        "catalog_count": len(catalog_keys),
        "demand_count": len(frame),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.environ.get("A_DATABASE_URL", DEFAULT_DSN))
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args()
    summary = seed_database(args.dsn, input_path=args.input, taxonomy_path=args.taxonomy, schema_path=args.schema)
    print(json.dumps({"status": "SEEDED", **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
