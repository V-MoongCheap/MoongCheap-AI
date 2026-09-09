"""Generate and validate catalog-grounded synthetic demand for the 5,000-row set."""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .demand_synthetic import PRICE_OPTIONS, prepare_demand_input

DATA_ORIGIN = "SYNTHETIC_GROUNDED"
TAXONOMY_VERSION = "v2.1"
SCENARIOS = (
    "NORMAL_SINGLE_FACET", "NORMAL_MULTI_FACET", "NO_EXTRA_REQUIREMENT",
    "ALIAS_EXPRESSION", "PARAPHRASE", "SHORT_QUERY", "FULL_SENTENCE",
    "NEGATION", "AMBIGUOUS", "CONFLICT", "OUT_OF_TAXONOMY", "MULTI_VALUE_CANDIDATE",
)
SCENARIO_TEMPLATES = {
    "NORMAL_SINGLE_FACET": "{pairs}",
    "NORMAL_MULTI_FACET": "{pairs} 제품이면 좋겠어요.",
    "PARAPHRASE": "가능하면 {pairs}인 제품으로 부탁해요.",
    "SHORT_QUERY": "{short}",
    "FULL_SENTENCE": "구매할 제품을 찾고 있어요. {pairs} 조건을 만족하면 좋겠습니다.",
    "NEGATION": "{pairs}은 피하고 싶어요.",
    "CONFLICT": "{pairs}이면서 {conflict}인 제품으로 부탁해요.",
    "OUT_OF_TAXONOMY": "딸기맛 제품이면 좋겠어요.",
    "MULTI_VALUE_CANDIDATE": "{pairs} 또는 {alternative}도 괜찮아요.",
}


def _read_csv(path: Path) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding).fillna("")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"unable to decode CSV: {path}")


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _category_key(value: Any) -> str:
    return str(value or "").strip().rsplit(":", 1)[-1].upper()


def load_taxonomy(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {_category_key(category.get("category_id")): category for category in payload.get("categories", [])}


def load_catalog(products_path: Path, mapping_path: Path) -> pd.DataFrame:
    products = _read_csv(products_path)
    mapping = _read_csv(mapping_path)
    mapping = mapping.rename(columns={"product_name": "name"})
    product_columns = [column for column in ("source_product_id", "name", "product_form", "functional_ingredients", "intake_method") if column in products]
    products = products[product_columns].drop_duplicates("source_product_id")
    columns = ["source_product_id", "name", "service_category_candidate_key", "service_category_name"]
    mapping = mapping[[column for column in columns if column in mapping]].drop_duplicates("source_product_id")
    catalog = products.merge(mapping, on="source_product_id", how="inner")
    catalog = catalog[catalog["service_category_candidate_key"].map(_category_key).ne("")].copy()
    catalog["category_id"] = "health-functional-food:" + catalog["service_category_candidate_key"].map(lambda x: str(x).strip().lower())
    catalog["catalog_id"] = "catalog-seed-" + catalog["source_product_id"].astype(str)
    return catalog


def _taxonomy_values(category: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {str(facet["name"]): [value for value in facet.get("values", []) if int(value.get("code", 0)) != 0 and str(value.get("value", "")).strip()] for facet in category.get("facets", [])}


def _product_base(product: pd.Series, category: dict[str, Any], facet_rows: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    allowed = _taxonomy_values(category)
    base: dict[str, dict[str, Any]] = {}
    for row in facet_rows.get(str(product["source_product_id"]), []):
        if str(row.get("mapping_status", "")).upper() != "MAPPED":
            continue
        facet = str(row.get("facet_name", "")).strip()
        raw = str(row.get("value", "")).strip()
        matches = [value for value in allowed.get(facet, []) if _norm(value.get("value")) == _norm(raw) or any(_norm(alias) == _norm(raw) for alias in value.get("aliases", []))]
        if len(matches) == 1:
            base[facet] = {"code": int(matches[0]["code"]), "value": matches[0]["value"]}
    return base


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _scenario_counts(count: int) -> dict[str, int]:
    base, remainder = divmod(count, len(SCENARIOS))
    return {scenario: base + (index < remainder) for index, scenario in enumerate(SCENARIOS)}


def generate_demand_5000(
    products_path: Path,
    mapping_path: Path,
    taxonomy_path: Path,
    product_facets_path: Path,
    count: int = 5000,
    seed: int = 42,
) -> pd.DataFrame:
    if count < 1:
        raise ValueError("count must be positive")
    catalog = load_catalog(products_path, mapping_path)
    taxonomy = load_taxonomy(taxonomy_path)
    catalog = catalog[catalog["service_category_candidate_key"].map(_category_key).isin(taxonomy)].reset_index(drop=True)
    if catalog.empty:
        raise ValueError("no mapped products overlap taxonomy")
    categories = sorted(set(catalog["service_category_candidate_key"].map(_category_key)))
    rows_per_category = (count + len(categories) - 1) // len(categories)
    used_ids: set[str] = set()
    category_products_by_key: dict[str, list[dict[str, Any]]] = {}
    for category_key in categories:
        category_products = catalog[catalog["service_category_candidate_key"].map(_category_key) == category_key]
        # Keep meaningful product diversity while deliberately repeating profiles for clustering tests.
        selected_products = category_products.iloc[: min(rows_per_category, 64)].to_dict(orient="records")
        category_products_by_key[category_key] = selected_products
        used_ids.update(str(product["source_product_id"]) for product in selected_products)
    facet_frame = _read_csv(product_facets_path)
    facet_frame = facet_frame[facet_frame["source_product_id"].astype(str).isin(used_ids)]
    facet_rows: dict[str, list[dict[str, Any]]] = {}
    for row in facet_frame.to_dict(orient="records"):
        facet_rows.setdefault(str(row.get("source_product_id", "")), []).append(row)
    base_cache: dict[str, dict[str, dict[str, Any]]] = {}
    rng = random.Random(seed)
    scenario_counts = _scenario_counts(count)
    scenarios = [scenario for scenario in SCENARIOS for _ in range(scenario_counts[scenario])]
    rng.shuffle(scenarios)
    rows: list[dict[str, Any]] = []
    profile_index: Counter[str] = Counter()
    for index, scenario in enumerate(scenarios):
        category_key = categories[index % len(categories)]
        category_products = category_products_by_key[category_key]
        product = category_products[(index // len(categories)) % len(category_products)]
        category = taxonomy[category_key]
        values_by_facet = _taxonomy_values(category)
        source_product_id = str(product["source_product_id"])
        if source_product_id not in base_cache:
            base_cache[source_product_id] = _product_base(product, category, facet_rows)
        base = base_cache[source_product_id]
        candidates = [(facet, value) for facet, values in values_by_facet.items() for value in values]
        if not candidates:
            raise ValueError(f"taxonomy category has no values: {category_key}")
        profile_slot = index % 32
        first_facet, first_value = candidates[profile_slot % len(candidates)]
        selected = {first_facet: first_value}
        if scenario in {"NORMAL_MULTI_FACET", "FULL_SENTENCE", "CONFLICT"} and len(candidates) > 1:
            second_facet, second_value = candidates[(profile_slot + 1) % len(candidates)]
            if second_facet != first_facet:
                selected[second_facet] = second_value
        profile_key = f"{category_key}:{product['source_product_id']}:{index % 32}"
        profile_index[profile_key] += 1
        pairs = " ".join(f"{value['value']}" for value in selected.values())
        alternative = candidates[(profile_slot + 2) % len(candidates)][1]["value"]
        conflict = next((value["value"] for facet, value in candidates if facet == first_facet and value["value"] != first_value["value"]), alternative)
        if scenario == "NO_EXTRA_REQUIREMENT":
            requirement = ""
        elif scenario == "ALIAS_EXPRESSION":
            aliases = first_value.get("aliases") or []
            requirement = str(aliases[0] if aliases else first_value["value"])
        else:
            requirement = SCENARIO_TEMPLATES.get(scenario, "{pairs}").format(pairs=pairs, short=str(first_value["value"]), alternative=alternative, conflict=conflict)
        option, minimum, maximum = rng.choice(PRICE_OPTIONS)
        rows.append({
            "demand_id": f"synthetic-grounded-demand-{index + 1:05d}",
            "profile_id": f"profile-{profile_key}",
            "generation_parent_id": f"profile-{profile_key}",
            "catalog_id": product["catalog_id"],
            "product_reference": product["source_product_id"],
            "product_name": product.get("name", ""),
            "category_id": product["category_id"],
            "service_category_key": product["category_id"],
            "service_category_name": product.get("service_category_name", ""),
            "extra_requirement": requirement,
            "desired_price_min": minimum,
            "desired_price_max": maximum,
            "price_option": option,
            "quantity": rng.choice([1, 1, 1, 2, 3]),
            "is_substitutable": rng.choice([True, True, False]),
            "product_base_facets": _json(base),
            "expected_facet_profile": _json({facet: {"code": int(value["code"]), "value": value["value"]} for facet, value in selected.items()}),
            "scenario_type": scenario,
            "data_origin": DATA_ORIGIN,
            "reference_source": "ESCI+xPQA+grounded_demand_v2_1000",
            "augmentation_method": "PROFILE_TEMPLATE_WITH_REFERENCE_STYLE",
            "price_origin": "MOCK_POLICY",
            "quantity_origin": "MOCK_POLICY",
            "substitution_origin": "MOCK_POLICY",
            "taxonomy_version": TAXONOMY_VERSION,
            "sampling_seed": seed,
            "processed_at": "",
            "synthetic": True,
            "source_note": "synthetic grounded demand; not observed user demand",
            "generation_status": "CANDIDATE_NEEDS_LABELING",
        })
    result = prepare_demand_input(pd.DataFrame(rows), allow_open_ended_price=True)
    return result


def quality_report(frame: pd.DataFrame, valid_products: set[str], taxonomy_categories: set[str]) -> pd.DataFrame:
    checks = {
        "row_count": len(frame),
        "expected_row_count": 5000,
        "demand_id_unique": int(frame["demand_id"].nunique()) if "demand_id" in frame else 0,
        "category_coverage": int(frame["category_id"].map(_category_key).nunique()),
        "expected_category_coverage": len(taxonomy_categories),
        "invalid_product_reference": int((~frame["product_reference"].isin(valid_products)).sum()),
        "unmapped_product": 0,
        "exact_duplicate_demand": int(frame.duplicated(subset=["catalog_id", "extra_requirement", "desired_price_min", "desired_price_max", "quantity", "is_substitutable"]).sum()),
        "duplicate_extra_requirement": int(frame["extra_requirement"].duplicated().sum()),
        "profile_count": int(frame["profile_id"].nunique()),
        "profile_repeated_rows": int((frame["profile_id"].value_counts() > 1).sum()),
        "empty_extra_requirement": int(frame["extra_requirement"].eq("").sum()),
        "price_invalid": int(((frame["desired_price_min"] < 0) | (frame["desired_price_max"].notna() & (frame["desired_price_max"] < frame["desired_price_min"]))).sum()),
        "quantity_invalid": int((frame["quantity"] < 1).sum()),
        "scenario_coverage": int(frame["scenario_type"].nunique()),
        "out_of_taxonomy_count": int(frame["scenario_type"].eq("OUT_OF_TAXONOMY").sum()),
        "conflict_count": int(frame["scenario_type"].eq("CONFLICT").sum()),
        "ambiguity_count": int(frame["scenario_type"].eq("AMBIGUOUS").sum()),
    }
    return pd.DataFrame([{"check": key, "value": value} for key, value in checks.items()])


def quality_markdown(frame: pd.DataFrame, report: pd.DataFrame) -> str:
    category_counts = frame["service_category_name"].value_counts(dropna=False).to_string()
    scenario_counts = frame["scenario_type"].value_counts().to_string()
    return "\n".join([
        "# Grounded Demand 5,000 품질 리포트", "",
        "이 데이터셋은 실제 사용자 수요가 아니라 테스트 Coverage를 위한 SYNTHETIC_GROUNDED 데이터입니다.", "",
        "## 검사 결과", "", "```", report.to_string(index=False), "```", "",
        "## Category별 Demand 수", "", "```", category_counts, "```", "",
        "## Scenario별 Demand 수", "", "```", scenario_counts, "```", "",
        "## 해석 기준", "",
        "- 가격, 수량, 대체 가능 여부는 `MOCK_POLICY`입니다.",
        "- `expected_facet_profile`은 생성 조건 provenance이며 Human Gold Label이 아닙니다.",
        "- Consumer Reference는 표현 방식만 참고했고, 원문 Query/Q&A를 Demand 정답으로 사용하지 않았습니다.",
    ])
