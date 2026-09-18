"""Build ERD v5 category and product_catalog seed files from observed catalog rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd


PLACEHOLDER_THUMBNAIL = "https://placehold.co/600x600?text=MoongCheap"


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^0-9a-z가-힣]+", "-", normalized).strip("-")
    return normalized or "unclassified"


def _category_key(path: str) -> str:
    slug = "/".join(_slug(part) for part in path.split(" > "))
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:10]
    return f"cat-v5-{slug}-{digest}"


def _load_taxonomy(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(row["category_id"]): row for row in payload.get("categories", [])}


def _facet_json(taxonomy_row: dict | None) -> str:
    if not taxonomy_row:
        return ""
    return json.dumps(
        {
            "taxonomy_version": taxonomy_row.get("taxonomy_version", "v2.2"),
            "category_id": taxonomy_row.get("category_id", ""),
            "facets": taxonomy_row.get("facets", []),
            "status": "DRAFT_PENDING_HUMAN_REVIEW",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build(catalog_path: Path, taxonomy_path: Path, output_dir: Path) -> dict[str, object]:
    catalog = pd.read_csv(catalog_path, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"catalog_id", "name", "category", "category_id", "status"}
    missing = sorted(required - set(catalog.columns))
    if missing:
        raise ValueError("catalog seed missing columns: " + ", ".join(missing))
    if catalog["catalog_id"].duplicated().any():
        raise ValueError("catalog_id must be unique")
    if catalog["name"].str.strip().eq("").any():
        raise ValueError("catalog name must not be blank")

    taxonomy = _load_taxonomy(taxonomy_path)
    path_rows: dict[str, dict[str, str]] = {}
    taxonomy_ids_by_path: dict[str, list[str]] = {}
    for raw_path in catalog["category"].map(_text):
        parts = [part.strip() for part in raw_path.split(">") if part.strip()]
        if not parts:
            parts = ["미분류"]
        for index in range(1, len(parts) + 1):
            path = " > ".join(parts[:index])
            path_rows.setdefault(path, {"path": path, "name": parts[index - 1], "depth": str(index)})
    for row in catalog.to_dict("records"):
        raw_path = _text(row.get("category")) or "미분류"
        parts = [part.strip() for part in raw_path.split(">") if part.strip()] or ["미분류"]
        taxonomy_id = _text(row.get("category_id"))
        for index in range(1, len(parts) + 1):
            taxonomy_ids_by_path.setdefault(" > ".join(parts[:index]), []).append(taxonomy_id)

    key_by_path = {path: _category_key(path) for path in sorted(path_rows)}
    categories = []
    for path in sorted(path_rows, key=lambda value: (value.count(" > "), value)):
        parts = path.split(" > ")
        observed_ids = [value for value in taxonomy_ids_by_path.get(path, []) if value in taxonomy]
        health_id = (
            pd.Series(observed_ids).value_counts().sort_index(ascending=True).idxmax()
            if observed_ids else ""
        )
        categories.append({
            "category_key": key_by_path[path],
            "parent_key": key_by_path.get(" > ".join(parts[:-1]), ""),
            "name": parts[-1],
            "depth": len(parts),
            "facet": _facet_json(taxonomy.get(health_id)),
            "source": "DOMEGGOOK_CATEGORY_PATH",
            "source_category_path": path,
            "health_taxonomy_category_id": health_id,
        })
    category_frame = pd.DataFrame(categories)

    product_rows = []
    for row in catalog.sort_values("catalog_id", kind="stable").to_dict("records"):
        raw_path = _text(row.get("category")) or "미분류"
        parts = [part.strip() for part in raw_path.split(">") if part.strip()] or ["미분류"]
        path = " > ".join(parts)
        product_rows.append({
            "catalog_seed_id": _text(row["catalog_id"]),
            "source_product_id": _text(row.get("source_product_id")),
            "name": _text(row["name"])[:100],
            "category_id": key_by_path[path],
            "category_seed_id": key_by_path[path],
            "spec_summary": _text(row.get("spec_summary"))[:500],
            "list_price": _text(row.get("list_price")),
            "thumbnail_url": _text(row.get("thumbnail_url")) or PLACEHOLDER_THUMBNAIL,
            "description": _text(row.get("description")),
            "status": _text(row.get("status")) or "ACTIVE",
            "source": _text(row.get("source")),
            "source_category_path": path,
            "source_category_id": _text(row.get("category_id")),
        })
    product_frame = pd.DataFrame(product_rows)
    # Preserve the complete observed source snapshot. Backend v5 has a unique
    # constraint on product_catalog.name, so its insert seed is deduplicated
    # separately and never silently replaces the source snapshot.
    product_frame["source_status"] = product_frame["status"]
    product_frame["status"] = product_frame["status"].map(
        {"판매중": "ACTIVE", "ACTIVE": "ACTIVE", "판매종료": "INACTIVE", "INACTIVE": "INACTIVE"}
    ).fillna("INACTIVE")
    name_conflicts = product_frame[product_frame["name"].duplicated(keep="first")].copy()
    backend_products = product_frame.drop_duplicates("name", keep="first").copy()
    output_dir.mkdir(parents=True, exist_ok=True)
    category_frame.to_csv(output_dir / "category_seed_v5.csv", index=False, encoding="utf-8-sig")
    product_frame.to_csv(output_dir / "product_catalog_source_snapshot_v5.csv", index=False, encoding="utf-8-sig")
    backend_products.to_csv(output_dir / "product_catalog_seed_v5.csv", index=False, encoding="utf-8-sig")
    name_conflicts.to_csv(output_dir / "product_catalog_name_conflicts_v5.csv", index=False, encoding="utf-8-sig")
    summary = {
        "catalog_input_rows": len(catalog),
        "product_catalog_source_snapshot_rows": len(product_frame),
        "product_catalog_seed_rows": len(backend_products),
        "duplicate_name_rows_excluded_from_backend_seed": len(name_conflicts),
        "category_seed_rows": len(category_frame),
        "category_depth_counts": category_frame["depth"].value_counts().sort_index().astype(int).to_dict(),
        "health_facet_category_rows": int(category_frame["facet"].ne("").sum()),
        "non_health_category_rows": int(category_frame["facet"].eq("").sum()),
        "placeholder_thumbnail_rows": int(product_frame["thumbnail_url"].eq(PLACEHOLDER_THUMBNAIL).sum()),
        "backend_status_counts": backend_products["status"].value_counts().astype(int).to_dict(),
        "source_categories": sorted(catalog["source"].unique().tolist()) if "source" in catalog else [],
        "erd_reference": "docs/erd/v5/moongcheap_erd_v5.sql",
        "facet_policy": "health taxonomy only; non-health products remain cataloged with empty facet",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.catalog, args.taxonomy, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
