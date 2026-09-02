"""Database-free downstream pipeline for the fixed V2.1 category candidates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .data_foundation.category_v2_1 import classify_v2_1
from .data_foundation.health_v1 import classify_record_type, normalize_form, parse_intake, split_ingredient_text, split_recognition_number
from .data_foundation.labeling import TaxonomyLoader, label_demands


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _catalog_and_types(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, type_rows = [], []
    for index, (_, row) in enumerate(frame.iterrows(), 1):
        key, name, confidence, reason = classify_v2_1(row)
        record_type, evidence, type_confidence = classify_record_type(row)
        provisional_ref = f"catalog-candidate-{index:06d}"
        rows.append({"catalog_id": "", "provisional_catalog_ref": provisional_ref, "source_product_id": row["source_product_id"], "product_name": row["name"], "service_category_key": "UNMAPPED" if not row["product_type"] else f"health-functional-food:{key.lower()}", "service_category_name": "미분류" if not row["product_type"] else name, "record_type_candidate": record_type, "product_form": row["product_form"], "functional_ingredients": row["functional_ingredients"], "standard_spec": row["standard_spec"], "main_functionality": row["main_functionality"], "catalog_status": "UNMAPPED" if not row["product_type"] else "PROVISIONAL", "mapping_status": "UNMAPPED" if not row["product_type"] else "PROVISIONAL", "mapping_confidence": 0.0 if not row["product_type"] else confidence, "review_reason": "source category missing" if not row["product_type"] else reason})
        type_rows.append({"provisional_catalog_ref": provisional_ref, "record_type_candidate": record_type, "record_type_confidence": type_confidence, "record_type_evidence": evidence})
    return pd.DataFrame(rows), pd.DataFrame(type_rows)


def _candidate_value(raw: str) -> str:
    value, _ = split_recognition_number(raw)
    return _text(value)


def build_provisional_taxonomy(frame: pd.DataFrame, catalog: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    review_rows, summary_rows, categories = [], [], []
    for category_key, group in catalog[catalog["service_category_key"] != "UNMAPPED"].groupby("service_category_key", sort=True):
        category_name = group.iloc[0]["service_category_name"]
        source_ids = set(group["source_product_id"])
        source = frame[frame["source_product_id"].isin(source_ids)]
        facet_specs = [("product_form", "관측된 제품 형태", source["product_form"].map(normalize_form)), ("functional_ingredients", "관측된 기능성 원료 후보", source["functional_ingredients"].map(lambda value: _candidate_value(value))), ("daily_frequency", "구조화된 1일 섭취 횟수 후보", source["intake_method"].map(lambda value: parse_intake(value)["daily_frequency_candidate"]))]
        facet_objects = []
        for facet_id, (facet_name, definition, values) in enumerate(facet_specs, 1):
            counts = values[values != ""].value_counts().head(10)
            if counts.empty:
                continue
            value_objects = [{"code": 0, "value": "ALL", "aliases": [], "status": "PROVISIONAL"}]
            for code, (value, count) in enumerate(counts.items(), 1):
                matching = source.loc[values == value]
                review_rows.append({"service_category_key": category_key, "service_category_name": category_name, "facet_id_candidate": facet_id, "facet_name_candidate": facet_name, "definition": definition, "candidate_value": value, "normalized_value": value, "source_field": facet_name, "support_count": int(count), "support_ratio": float(count / len(source)), "example_source_product_ids": "|".join(matching["source_product_id"].head(5)), "example_source_values": value, "multi_value_candidate": facet_name == "functional_ingredients", "review_status": "PROVISIONAL", "review_note": "candidate only; value code is provisional"})
                value_objects.append({"code": code, "value": value, "aliases": [], "status": "PROVISIONAL"})
            facet_objects.append({"facet_id": facet_id, "name": facet_name, "order": facet_id, "definition": definition, "values": value_objects, "status": "PROVISIONAL"})
        categories.append({"category_id": category_key, "category_name": category_name, "facets": facet_objects, "status": "PROVISIONAL"})
        summary_rows.append({"category_name": category_name, "category_key": category_key, "product_count": len(source), "facet_candidate_count": len(facet_objects), "value_candidate_count": sum(max(0, len(facet["values"]) - 1) for facet in facet_objects), "source_coverage": 1.0 if facet_objects else 0.0, "validation_error_count": 0})
    taxonomy = {"version": "v2.1-provisional", "status": "PROVISIONAL", "categories": categories}
    return taxonomy, pd.DataFrame(review_rows), pd.DataFrame(summary_rows)


def build_synthetic_v21(catalog: pd.DataFrame, taxonomy: dict[str, Any], count: int = 32) -> pd.DataFrame:
    categories = [category for category in taxonomy["categories"] if category["facets"]]
    rows = []
    cases = ["single", "multi", "none", "alias", "negation", "outside", "conflict", "ambiguous"]
    for index in range(count):
        category = categories[index % len(categories)]
        product = catalog[catalog["service_category_key"] == category["category_id"]].iloc[index % len(catalog[catalog["service_category_key"] == category["category_id"]])]
        facets = category["facets"]
        values = [value for facet in facets for value in facet["values"] if value["code"] != 0]
        case = cases[index % len(cases)]
        requirement = ""
        if case == "single" and values:
            requirement = values[0]["value"]
        elif case == "multi" and len(values) > 1:
            requirement = f"{values[0]['value']} {values[1]['value']}"
        elif case == "none":
            requirement = "조건 없음"
        elif case == "alias" and values:
            requirement = values[0]["value"]
        elif case == "negation" and values:
            requirement = f"{values[0]['value']} 말고 다른 조건"
        elif case == "outside":
            requirement = "반려동물도 먹을 수 있는 제품"
        elif case == "conflict" and len(values) > 1:
            requirement = f"{values[0]['value']}이면서 {values[1]['value']}가 아닌 제품"
        else:
            requirement = "적당한 제품"
        rows.append({"demand_id": f"synthetic-demand-v21-{index + 1:05d}", "catalog_id": "", "provisional_catalog_ref": product["provisional_catalog_ref"], "category_id": category["category_id"], "service_category_key": category["category_id"], "service_category_name": category["category_name"], "extra_requirement": requirement, "desired_price_min": 10000 + (index % 4) * 10000, "desired_price_max": 30000 + (index % 4) * 10000, "quantity": 1 + index % 3, "is_substitutable": index % 3 != 0, "processed_at": "", "synthetic": True, "data_origin": "MOCK", "taxonomy_status": "PROVISIONAL", "case_type": case})
    return pd.DataFrame(rows)


def run_downstream_v21(frame: pd.DataFrame, output_dir: Path, count: int = 32) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog, _ = _catalog_and_types(frame)
    catalog.to_csv(output_dir / "product_catalog_v2_1_provisional.csv", index=False, encoding="utf-8-sig")
    taxonomy, review, summary = build_provisional_taxonomy(frame, catalog)
    (output_dir / "taxonomy_candidate_v2_1.json").write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2), encoding="utf-8")
    review.to_csv(output_dir / "taxonomy_review_v2_1.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / "taxonomy_summary_v2_1.csv", index=False, encoding="utf-8-sig")
    demands = build_synthetic_v21(catalog, taxonomy, count=count)
    demands.to_csv(output_dir / "synthetic_demand_v2_1.csv", index=False, encoding="utf-8-sig")
    labeled = label_demands(demands, TaxonomyLoader(taxonomy))
    labeled.to_csv(output_dir / "demand_labeled_v2_1.csv", index=False, encoding="utf-8-sig")
    failures = labeled[labeled["label_status"] != "LABELED"].copy()
    failures["taxonomy_version"] = "v2.1-provisional"
    failures["failure_type"] = failures["label_warnings"].map(lambda value: "taxonomy_missing" if "did not match" in str(value) else "ambiguous_expression")
    failures.to_csv(output_dir / "labeling_failures_v2_1.csv", index=False, encoding="utf-8-sig")
    matching = []
    for category in taxonomy["categories"]:
        subset = labeled[labeled["category_id"] == category["category_id"]]
        for facet in category["facets"]:
            values = subset["facet_values"].map(lambda value: json.loads(value).get(facet["name"], {}))
            matched = int(values.map(lambda value: int(value.get("code", 0)) != 0).sum())
            matching.append({"category_name": category["category_name"], "category_key": category["category_id"], "facet_id": facet["facet_id"], "facet_name": facet["name"], "total": len(subset), "matched": matched, "all_count": len(subset) - matched, "unresolved": int((subset["label_status"] != "LABELED").sum()), "match_rate": matched / len(subset) if len(subset) else 0})
    pd.DataFrame(matching).to_csv(output_dir / "facet_matching_report_v2_1.csv", index=False, encoding="utf-8-sig")
    cluster = labeled.copy()
    cluster["product_reference"] = cluster["provisional_catalog_ref"]
    cluster["taxonomy_version"] = "v2.1-provisional"
    cluster["taxonomy_status"] = "PROVISIONAL"
    cluster["data_origin"] = "MOCK"
    cluster.to_csv(output_dir / "clustering_input_v2_1.csv", index=False, encoding="utf-8-sig")
    report = ["# AI V1 Pipeline Report", "", "## Category", f"- Service Category 후보: {len(taxonomy['categories'])}", f"- Mapping 성공 Product: {int((catalog['mapping_status'] != 'UNMAPPED').sum())}", f"- UNMAPPED Product: {int((catalog['mapping_status'] == 'UNMAPPED').sum())}", "", "## Catalog", f"- Provisional Catalog 후보: {len(catalog)}", f"- Finished Product Candidate: {int((catalog['record_type_candidate'] == 'FINISHED_PRODUCT_CANDIDATE').sum())}", f"- Ingredient Material Candidate: {int((catalog['record_type_candidate'] == 'INGREDIENT_MATERIAL_CANDIDATE').sum())}", f"- Uncertain: {int((catalog['record_type_candidate'] == 'UNCERTAIN').sum())}", "", "## Facet", f"- Category별 결과: {len(summary)}개", f"- 전체 Facet Candidate: {len(review)}", "- Taxonomy status: PROVISIONAL", "", "## Demand", f"- Synthetic Demand: {len(demands)}", f"- Labeling 성공: {int((labeled['label_status'] == 'LABELED').sum())}", f"- Labeling 검토: {int((labeled['label_status'] != 'LABELED').sum())}", f"- unresolved 포함: {int((labeled['unresolved_items'] != '[]').sum())}", "", "## Clustering Input", f"- Export Row: {len(cluster)}", f"- 필수 ID 미확정: catalog_id는 의도적으로 공란", "", "## 상태", "- DB 연결 없음", "- Category/Catalog/Facet/Code는 PROVISIONAL 또는 NEEDS_REVIEW", "- Synthetic Demand는 MOCK 데이터", "- Final ID, Alias, Multi-value Encoding은 미확정"]
    (output_dir / "ai_v1_pipeline_report.md").write_text("\n".join(report), encoding="utf-8")
    return {"categories": len(taxonomy["categories"]), "catalog_rows": len(catalog), "unmapped": int((catalog["mapping_status"] == "UNMAPPED").sum()), "facet_rows": len(review), "demands": len(demands), "labeled": int((labeled["label_status"] == "LABELED").sum()), "review": int((labeled["label_status"] != "LABELED").sum())}
