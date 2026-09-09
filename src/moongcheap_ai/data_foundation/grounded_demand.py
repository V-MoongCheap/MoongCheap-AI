"""Generate catalog-bound synthetic Demand rows using reference expression styles."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pandas as pd

from .demand_synthetic import PRICE_OPTIONS, prepare_demand_input


STYLE_TEMPLATES = {
    "PREFERENCE": ("{value} 제품으로 찾아주세요.", "{value} 조건을 선호합니다."),
    "QUESTION": ("{value} 제품이 있을까요?",),
}


def _category_key(value: str) -> str:
    value = str(value).strip()
    return value.rsplit(":", 1)[-1].upper()


def load_reference_styles(xpqa_path: Path | None, esci_path: Path | None) -> list[dict[str, str]]:
    """Read reference records without treating their text as product facts."""
    records: list[dict[str, str]] = []
    if xpqa_path and xpqa_path.exists():
        for path in sorted(xpqa_path.glob("*.csv")):
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            if "question" not in frame:
                continue
            if "lang" in frame:
                frame = frame[frame["lang"].str.lower().isin({"ko", "kor", "korean"})]
            for index, row in frame.iterrows():
                text = str(row.get("question", "")).strip()
                if text:
                    records.append({"source": "xPQA", "record_id": f"{path.name}:{index}", "style": "QUESTION" if "?" in text else "PREFERENCE"})
    if esci_path and esci_path.exists():
        frame = pd.read_parquet(esci_path) if esci_path.suffix.lower() == ".parquet" else pd.read_csv(esci_path, dtype=str)
        query_column = "query_clean" if "query_clean" in frame else "query"
        for index, value in frame[query_column].fillna("").items():
            if str(value).strip():
                records.append({"source": "ESCI", "record_id": str(index), "style": "PREFERENCE"})
    return records


def _load_catalog(product_path: Path, mapping_path: Path) -> pd.DataFrame:
    products = pd.read_csv(product_path, dtype=str).fillna("")
    mapping = pd.read_csv(mapping_path, dtype=str).fillna("")
    mapping = mapping.rename(columns={"product_name": "name", "service_category_candidate_key": "category_id", "service_category_name": "category_name"})
    columns = ["source_product_id", "name", "category_id", "category_name"]
    merged = products[["source_product_id", "name"]].merge(mapping[["source_product_id", "category_id", "category_name"]], on="source_product_id", how="inner")
    merged = merged.drop_duplicates("source_product_id")
    merged["category_candidate_key"] = merged["category_id"]
    merged["category_id"] = "health-functional-food:" + merged["category_id"].astype(str).str.lower()
    merged["catalog_id"] = "catalog-seed-" + merged["source_product_id"].astype(str)
    return merged[columns + ["catalog_id", "category_candidate_key"]]


def _load_values(taxonomy_path: Path) -> dict[str, list[dict[str, str]]]:
    taxonomy = pd.read_csv(taxonomy_path, dtype=str).fillna("")
    taxonomy = taxonomy[taxonomy["review_status"].str.upper() != "DROP"]
    taxonomy["normalized_value"] = taxonomy["normalized_value"].str.strip()
    taxonomy = taxonomy[(taxonomy["normalized_value"] != "") & (taxonomy["normalized_value"].str.upper() != "ALL")]
    result: dict[str, list[dict[str, str]]] = {}
    taxonomy["category_match_key"] = taxonomy["service_category_key"].map(_category_key)
    for category_id, group in taxonomy.groupby("category_match_key", sort=True):
        result[category_id] = [
            {"facet": str(row["facet_name_candidate"] or row["source_field"]), "value": row["normalized_value"]}
            for _, row in group.drop_duplicates(["facet_name_candidate", "normalized_value"]).iterrows()
        ]
    return result


def generate_grounded_demands(
    product_path: Path,
    mapping_path: Path,
    taxonomy_path: Path,
    xpqa_path: Path | None = None,
    esci_path: Path | None = None,
    count: int = 100,
    seed: int = 42,
) -> pd.DataFrame:
    """Create synthetic requests tied to observed catalog seeds and approved candidates."""
    catalog = _load_catalog(product_path, mapping_path)
    values = _load_values(taxonomy_path)
    references = load_reference_styles(xpqa_path, esci_path)
    if catalog.empty:
        raise ValueError("catalog mapping is empty")
    if not values:
        raise ValueError("taxonomy has no usable candidate values")
    if not references:
        raise ValueError("no local expression reference records found")
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    candidates = catalog[catalog["category_id"].map(_category_key).isin(values)].reset_index(drop=True)
    if candidates.empty:
        raise ValueError("no catalog rows have a matching taxonomy category")
    for index in range(count):
        product = candidates.iloc[index % len(candidates)]
        candidate = rng.choice(values[_category_key(product["category_id"])])
        reference = rng.choice(references)
        style = rng.choice(STYLE_TEMPLATES[reference["style"]])
        option_code, minimum, maximum = rng.choice(PRICE_OPTIONS)
        rows.append({
            "demand_id": f"synthetic-grounded-demand-{index + 1:05d}",
            "catalog_id": product["catalog_id"],
            "category_id": product["category_id"],
            "category_candidate_key": product["category_candidate_key"],
            "extra_requirement": style.format(value=candidate["value"]),
            "desired_price_min": minimum,
            "desired_price_max": maximum,
            "price_option": option_code,
            "quantity": rng.choice([1, 1, 2, 3]),
            "is_substitutable": rng.choice([True, True, False]),
            "processed_at": "",
            "synthetic": True,
            "source_note": "grounded synthetic request; not a user Demand",
            "reference_source": reference["source"],
            "reference_record_id": reference["record_id"],
            "facet_requirements": f'{{"{candidate["facet"]}": "{candidate["value"]}"}}',
            "generation_status": "CANDIDATE_NEEDS_LABELING",
        })
    return prepare_demand_input(pd.DataFrame(rows), allow_open_ended_price=True)
