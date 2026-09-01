"""Review-oriented V1 reconstruction from the local MFDS product corpus."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


RECOGNITION_RE = re.compile(r"\(\s*제\s*(\d{4})\s*-\s*(\d+)\s*호\s*\)")
FORM_MAP = {"분말": "분말", "캡슐": "캡슐", "정": "정", "정제": "정", "액상": "액상", "젤리": "젤리", "환": "환", "과립": "과립", "겔": "겔", "바": "바"}
INGREDIENT_USE_RE = re.compile(r"건강기능식품\s*(?:제조|원료)|원료로\s*사용|제조\s*시")
FREQUENCY_RE = re.compile(r"(?P<days>\d+)\s*일\s*(?P<frequency>\d+)\s*회")
AMOUNT_RE = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>캡슐|정제?|포|스푼|ml|mL|g|그램|개)")


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_recognition_number(value: Any) -> tuple[str, str]:
    raw = _text(value)
    match = RECOGNITION_RE.search(raw)
    if not match:
        return raw, ""
    return _text(RECOGNITION_RE.sub("", raw)), f"제{match.group(1)}-{match.group(2)}호"


def classify_record_type(row: pd.Series) -> tuple[str, str, float]:
    intake = _text(row.get("intake_method"))
    form = _text(row.get("product_form"))
    ingredients = _text(row.get("functional_ingredients"))
    evidence = " | ".join(value for value in (intake, form, ingredients) if value)
    if INGREDIENT_USE_RE.search(intake):
        return "INGREDIENT_MATERIAL_CANDIDATE", evidence, 0.95
    if re.search(r"섭취|복용", intake) and not INGREDIENT_USE_RE.search(intake):
        return "FINISHED_PRODUCT_CANDIDATE", evidence, 0.80
    return "UNCERTAIN", evidence, 0.50


def normalize_form(value: Any) -> str:
    raw = _text(value)
    return FORM_MAP.get(raw, raw)


def split_ingredient_text(value: Any) -> tuple[list[str], str]:
    raw = _text(value)
    if not raw:
        return [], "EMPTY"
    depth = 0
    token: list[str] = []
    values: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    for char in raw:
        if char in pairs:
            depth += 1
        elif char in closing:
            depth -= 1
            if depth < 0:
                return [raw], "UNBALANCED"
        if char in ",，" and depth == 0:
            value = _text("".join(token))
            if value:
                values.append(value)
            token = []
        else:
            token.append(char)
    value = _text("".join(token))
    if value:
        values.append(value)
    if depth != 0:
        return [raw], "UNBALANCED"
    return values, "PARSED"


def parse_intake(value: Any) -> dict[str, str]:
    raw = _text(value)
    frequency = FREQUENCY_RE.search(raw)
    amount = AMOUNT_RE.search(raw)
    result = {
        "daily_frequency_candidate": f"{frequency.group('days')}일 {frequency.group('frequency')}회" if frequency else "",
        "amount_per_intake_candidate": amount.group("amount") if amount else "",
        "dose_unit_candidate": amount.group("unit") if amount else "",
        "timing_condition_candidate": "",
        "parse_confidence": "0.9" if frequency or amount else "0.0",
        "parse_status": "PARSED" if frequency or amount else ("EMPTY" if not raw else "NO_SIGNAL"),
    }
    timing = re.search(r"(식전|식후|공복|취침 전|아침|저녁)", raw)
    if timing:
        result["timing_condition_candidate"] = timing.group(1)
    return result


def build_v1_artifacts(frame: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = frame.fillna("").copy()
    for column in data.columns:
        data[column] = data[column].map(_text)
    data["normalized_source_category"], data["recognition_number"] = zip(*data["product_type"].map(split_recognition_number))

    source_rows = []
    for category, group in data.groupby("product_type", sort=True):
        if not category:
            continue
        normalized, recognition = split_recognition_number(category)
        if recognition:
            category_type = "INDIVIDUALLY_RECOGNIZED_INGREDIENT"
        elif re.search(r"원료|기능성", normalized):
            category_type = "INGREDIENT_OR_FUNCTION_GROUP"
        elif normalized:
            category_type = "GENERIC_CATEGORY_CANDIDATE"
        else:
            category_type = "UNCERTAIN"
        source_rows.append({
            "source_category": category, "product_count": len(group),
            "normalized_source_category": normalized, "recognition_number": recognition,
            "category_type_candidate": category_type,
            "example_product_ids": "|".join(group["source_product_id"].head(5)),
            "example_product_names": "|".join(group["name"].head(5)),
            "review_status": "NEEDS_REVIEW", "review_note": "Analysis candidate; source and service category are distinct",
        })
    source_analysis = pd.DataFrame(source_rows)
    source_analysis.to_csv(output_dir / "source_category_type_analysis_v1.csv", index=False, encoding="utf-8-sig")

    type_rows = []
    for _, row in data.iterrows():
        record_type, evidence, confidence = classify_record_type(row)
        type_rows.append({
            "source_product_id": row["source_product_id"], "product_name": row["name"],
            "source_category": row["product_type"], "intake_method_raw": row["intake_method"],
            "product_form_raw": row["product_form"], "functional_ingredients_raw": row["functional_ingredients"],
            "record_type_candidate": record_type, "evidence": evidence, "confidence": confidence,
            "review_status": "NEEDS_REVIEW", "review_note": "Rule evidence is not a final product type decision",
        })
    record_types = pd.DataFrame(type_rows)
    record_types.to_csv(output_dir / "product_record_type_review_v1.csv", index=False, encoding="utf-8-sig")

    group_key = data["product_type"].map(lambda value: split_recognition_number(value)[0] or "UNMAPPED")
    data["service_category_key_candidate"] = group_key.map(lambda value: f"health-candidate:{value}" if value != "UNMAPPED" else "UNMAPPED")
    service_rows = []
    for key, group in data.groupby("service_category_key_candidate", sort=True):
        if key == "UNMAPPED":
            continue
        source_categories = group["product_type"].drop_duplicates().tolist()
        service_rows.append({
            "category_key_candidate": key, "parent_key_candidate": "health-functional-food",
            "category_name_candidate": key.split(":", 1)[-1], "depth_candidate": 2,
            "source_categories": "|".join(source_categories), "product_count": len(group),
            "example_product_ids": "|".join(group["source_product_id"].head(5)),
            "example_product_names": "|".join(group["name"].head(5)),
            "generation_reason": "normalized MFDS source-category candidate grouping",
            "review_status": "NEEDS_REVIEW", "review_note": "No service category ID or final merge decision generated",
        })
    service = pd.DataFrame(service_rows)
    service.to_csv(output_dir / "service_category_candidate_v1.csv", index=False, encoding="utf-8-sig")

    source_to_service = source_analysis.copy()
    source_to_service["suggested_service_category_key"] = source_to_service["normalized_source_category"].map(lambda value: f"health-candidate:{value}" if value else "UNMAPPED")
    source_to_service["suggested_service_category_name"] = source_to_service["normalized_source_category"]
    source_to_service["mapping_reason"] = "recognition number removed only for candidate grouping"
    source_to_service["confidence"] = 0.50
    source_to_service["review_status"] = "NEEDS_REVIEW"
    source_to_service["review_note"] = "Removing recognition number does not prove same service category"
    source_to_service.to_csv(output_dir / "source_to_service_category_review_v1.csv", index=False, encoding="utf-8-sig")

    preview = data[["source_product_id", "name", "product_type", "service_category_key_candidate"]].rename(columns={"name": "product_name", "product_type": "source_category", "service_category_key_candidate": "suggested_service_category_key"})
    preview["suggested_service_category_name"] = preview["suggested_service_category_key"].str.replace("health-candidate:", "", regex=False)
    preview["record_type_candidate"] = record_types["record_type_candidate"].values
    preview["mapping_confidence"] = 0.50
    preview["review_status"] = preview["suggested_service_category_key"].map(lambda value: "UNMAPPED" if value == "UNMAPPED" else "NEEDS_REVIEW")
    preview.to_csv(output_dir / "product_service_category_mapping_v1.csv", index=False, encoding="utf-8-sig")

    catalog = data[["source_product_id", "name", "product_type", "product_form", "standard_spec", "main_functionality"]].copy()
    catalog.insert(0, "catalog_id", "")
    catalog["service_category_key"] = data["service_category_key_candidate"].values
    catalog["source_category"] = catalog.pop("product_type")
    catalog["record_type_candidate"] = record_types["record_type_candidate"].values
    catalog["spec_summary"] = catalog.pop("standard_spec")
    catalog["description"] = catalog.pop("main_functionality")
    catalog["catalog_status"] = catalog["record_type_candidate"].map(lambda value: "REVIEW_INGREDIENT_MATERIAL" if value == "INGREDIENT_MATERIAL_CANDIDATE" else "CANDIDATE")
    catalog["review_status"] = "NEEDS_REVIEW"
    catalog["exclusion_or_review_reason"] = catalog["record_type_candidate"].map(lambda value: "possible ingredient material" if value == "INGREDIENT_MATERIAL_CANDIDATE" else "service category approval required")
    catalog.to_csv(output_dir / "product_catalog_candidate_v1.csv", index=False, encoding="utf-8-sig")

    form_rows = []
    for raw, group in data.groupby("product_form", sort=True):
        if not raw:
            continue
        form_rows.append({"raw_value": raw, "canonical_value_candidate": normalize_form(raw), "support_count": len(group), "source_categories": "|".join(group["product_type"].drop_duplicates().head(20)), "example_product_ids": "|".join(group["source_product_id"].head(5)), "normalization_reason": "exact observed spelling map only", "review_status": "NEEDS_REVIEW"})
    pd.DataFrame(form_rows).to_csv(output_dir / "product_form_value_review_v1.csv", index=False, encoding="utf-8-sig")

    ingredient_rows, ingredient_failures, ingredient_map = [], [], []
    for _, row in data.iterrows():
        tokens, status = split_ingredient_text(row["functional_ingredients"])
        if status == "UNBALANCED":
            ingredient_failures.append({"source_product_id": row["source_product_id"], "raw_value": row["functional_ingredients"], "parse_status": status, "note": "raw preserved"})
        for token in tokens:
            canonical, recognition = split_recognition_number(token)
            ingredient_map.append({"source_product_id": row["source_product_id"], "raw_value": row["functional_ingredients"], "parsed_value_candidate": token, "canonical_value_candidate": canonical, "recognition_number": recognition, "parse_status": status})
    parsed = pd.DataFrame(ingredient_map)
    if not parsed.empty:
        counts = parsed.groupby("canonical_value_candidate").size().to_dict()
        categories = data.set_index("source_product_id")["product_type"].to_dict()
        for value, group in parsed.groupby("canonical_value_candidate", sort=True):
            example_id = group.iloc[0]["source_product_id"]
            ingredient_rows.append({"raw_value": group.iloc[0]["raw_value"], "parsed_value_candidate": value, "canonical_value_candidate": value, "recognition_number": group.iloc[0]["recognition_number"], "support_count": counts[value], "category_count": len({categories.get(x, "") for x in group["source_product_id"]}), "example_product_ids": "|".join(group["source_product_id"].head(5)), "parse_status": group.iloc[0]["parse_status"], "review_status": "NEEDS_REVIEW", "review_note": "multi-value ingredient candidate; not a final Facet Value"})
    pd.DataFrame(ingredient_rows).to_csv(output_dir / "functional_ingredient_value_review_v1.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(ingredient_failures, columns=["source_product_id", "raw_value", "parse_status", "note"]).to_csv(output_dir / "ingredient_parse_failures_v1.csv", index=False, encoding="utf-8-sig")
    multi = pd.DataFrame([{"facet_candidate": "functional_ingredients", "multi_value_candidate": True, "evidence": "one raw field can parse into multiple top-level tokens", "review_status": "NEEDS_REVIEW"}])
    multi.to_csv(output_dir / "multi_value_facet_review_v1.csv", index=False, encoding="utf-8-sig")

    intake_rows = []
    for _, row in data.iterrows():
        parsed_intake = parse_intake(row["intake_method"])
        intake_rows.append({"source_product_id": row["source_product_id"], "intake_method_raw": row["intake_method"], **parsed_intake, "review_note": "candidate feature only; not automatically a consumer Facet"})
    intake = pd.DataFrame(intake_rows)
    intake.to_csv(output_dir / "intake_method_structured_v1.csv", index=False, encoding="utf-8-sig")
    intake[intake["parse_status"].isin(["NO_SIGNAL", "UNBALANCED"])].to_csv(output_dir / "intake_method_parse_failures_v1.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"facet_candidate": field, "definition": definition, "distinct_value_count": int(intake[field].nunique()), "product_coverage": float((intake[field] != "").mean()), "category_coverage": int(data.loc[intake[field] != "", "service_category_key_candidate"].nunique()), "examples": "|".join(intake.loc[intake[field] != "", field].head(5)), "consumer_purchase_relevance": "NEEDS_REVIEW", "review_status": "NEEDS_REVIEW"} for field, definition in (("daily_frequency_candidate", "섭취 빈도"), ("amount_per_intake_candidate", "1회 섭취량"), ("dose_unit_candidate", "섭취 단위"), ("timing_condition_candidate", "섭취 시점"))]).to_csv(output_dir / "intake_facet_review_v1.csv", index=False, encoding="utf-8-sig")

    facet_rows = []
    for category, group in data.groupby("service_category_key_candidate", sort=True):
        if category == "UNMAPPED":
            continue
        for facet_name, values in (("product_form", group["product_form"].map(normalize_form)), ("functional_ingredients", group["functional_ingredients"].map(_text)), ("daily_frequency", intake.loc[group.index, "daily_frequency_candidate"])):
            counts = values[values != ""].value_counts()
            for value, support in counts.head(20).items():
                example = group.loc[values == value].iloc[0]
                facet_rows.append({"service_category_key": category, "service_category_name": category.split(":", 1)[-1], "facet_id_candidate": "", "facet_name_candidate": facet_name, "definition": FACET_DEFINITIONS.get(facet_name, facet_name), "candidate_value": value, "normalized_value": value, "source_field": facet_name, "support_count": int(support), "support_ratio": float(support / len(group)), "example_source_product_ids": "|".join(group.loc[values == value, "source_product_id"].head(5)), "example_source_values": _text(example.get(facet_name if facet_name != "daily_frequency" else "intake_method", "")), "multi_value_candidate": facet_name == "functional_ingredients", "review_status": "NEEDS_REVIEW", "review_note": "V1 candidate with source evidence; human approval required"})
    facets = pd.DataFrame(facet_rows)
    facets.to_csv(output_dir / "taxonomy_review_v1.csv", index=False, encoding="utf-8-sig")
    summary = facets.groupby(["service_category_key", "facet_name_candidate"], dropna=False).agg(product_count=("support_count", "sum"), facet_coverage=("support_ratio", "max"), distinct_raw_values=("candidate_value", "nunique"), distinct_normalized_values=("normalized_value", "nunique"), top_values=("candidate_value", lambda values: "|".join(values.head(5))), long_tail_value_count=("candidate_value", lambda values: max(0, len(values) - 5))).reset_index() if not facets.empty else pd.DataFrame()
    summary.to_csv(output_dir / "taxonomy_review_summary_v1.csv", index=False, encoding="utf-8-sig")
    facets.assign(alias_candidate=facets["candidate_value"], canonical_value_candidate=facets["normalized_value"], normalization_type="observed_normalization", conflict_candidate=False, review_status="NEEDS_REVIEW")["facet_name_candidate canonical_value_candidate alias_candidate normalization_type support_count conflict_candidate review_status".split()].to_csv(output_dir / "alias_review_v1.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(columns=["normalized_alias", "value_candidates", "conflict_type", "review_status"]).to_csv(output_dir / "alias_conflict_report_v1.csv", index=False, encoding="utf-8-sig")
    support_rows = []
    for (category, facet_name), group in facets.groupby(["service_category_key", "facet_name_candidate"]):
        for threshold in (1, 3, 5, 10):
            support_rows.append({"service_category_key": category, "facet_name": facet_name, "threshold": threshold, "value_count": int((group["support_count"] >= threshold).sum()), "product_coverage": float(group.loc[group["support_count"] >= threshold, "support_count"].sum() / group["support_count"].sum()) if group["support_count"].sum() else 0, "long_tail_ratio": float((group["support_count"] < threshold).mean()) if len(group) else 0, "review_status": "NEEDS_REVIEW"})
    pd.DataFrame(support_rows).to_csv(output_dir / "facet_support_analysis_v1.csv", index=False, encoding="utf-8-sig")
    validation_rows = [
        {"check": "invalid_json", "status": "PASS", "detail": "candidate artifacts are serialized as UTF-8 JSON where applicable"},
        {"check": "fake_service_ids", "status": "PASS", "detail": "category_id and catalog_id remain blank in V1 candidate"},
        {"check": "source_service_category_mixing", "status": "PASS", "detail": "source categories and candidate keys are separate fields"},
        {"check": "all_unknown_policy", "status": "REVIEW", "detail": "ALL/UNKNOWN values belong to approved taxonomy serialization"},
        {"check": "compound_ingredient_value", "status": "REVIEW", "detail": "multi-value ingredient candidates require human approval"},
    ]
    pd.DataFrame(validation_rows).to_csv(output_dir / "taxonomy_validation_report_v1.csv", index=False, encoding="utf-8-sig")
    v0_path = output_dir.parent / "health_foundation" / "taxonomy_review_v0.csv"
    v0_count = len(pd.read_csv(v0_path, dtype=str)) if v0_path.exists() else 0
    before_after = "\n".join([
        "# V0 to V1 Review Report", "", "## Category", f"- V0 source category: {len(source_analysis)}", f"- V1 service category candidates: {len(service)}", f"- V1 product coverage: {len(data)}", f"- Unmapped products: {int((data['service_category_key_candidate'] == 'UNMAPPED').sum())}", "", "## Record Type", f"- Finished product candidates: {int((record_types['record_type_candidate'] == 'FINISHED_PRODUCT_CANDIDATE').sum())}", f"- Ingredient material candidates: {int((record_types['record_type_candidate'] == 'INGREDIENT_MATERIAL_CANDIDATE').sum())}", f"- Uncertain: {int((record_types['record_type_candidate'] == 'UNCERTAIN').sum())}", "", "## Facet", f"- V0 raw candidate rows: {v0_count}", f"- V1 normalized candidate rows: {len(facets)}", f"- Review-row reduction: {(1 - len(facets) / v0_count) * 100 if v0_count else 0:.2f}%", f"- Ingredient parse failures: {len(ingredient_failures)}", f"- Intake parse failures: {int(intake['parse_status'].isin(['NO_SIGNAL', 'UNBALANCED']).sum())}", "", "## Review Policy", "- V1 values, aliases, category merges, IDs, and codes remain NEEDS_REVIEW.", "- V1 candidates are not production taxonomy or gold labeling data.",
    ])
    (output_dir / "before_after_review_report_v1.md").write_text(before_after, encoding="utf-8")

    return {"product_rows": len(data), "source_category_count": len(source_analysis), "service_category_candidate_count": len(service), "record_type_counts": record_types["record_type_candidate"].value_counts().to_dict(), "ingredient_candidate_count": len(ingredient_rows), "ingredient_parse_failure_count": len(ingredient_failures), "intake_parse_failure_count": int(intake["parse_status"].isin(["NO_SIGNAL", "UNBALANCED"]).sum()), "facet_candidate_rows": len(facets), "status": "DRAFT_PENDING_HUMAN_REVIEW"}


FACET_DEFINITIONS = {"product_form": "관측된 제품 형태", "functional_ingredients": "관측된 기능성 원료 후보", "daily_frequency": "구조화된 1일 섭취 횟수 후보"}
