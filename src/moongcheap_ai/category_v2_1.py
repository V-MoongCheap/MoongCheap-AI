"""Apply only the approved V2.1 category candidates; keep the V2 tree shape."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .category_v2 import classify_service_group
from .category_detail import SUBGROUP_RULES


NEW_GROUPS = {
    "SKIN_COLLAGEN": ("피부·콜라겐", ("콜라겐", "히알루론산", "피부")),
    "PROTEIN": ("단백질", ("단백질",)),
    "PROPOLIS": ("프로폴리스", ("프로폴리스",)),
    "BLOOD_SUGAR_METABOLIC": ("혈당·대사", ("바나바", "혈당", "코엔자임Q10")),
    "THEANINE_SLEEP": ("테아닌·수면", ("테아닌", "수면")),
    "MALE_HEALTH": ("남성 건강", ("쏘팔메토", "남성")),
}
SUBGROUP_KEY_ORDER = ("PROTEIN", "PROPOLIS", "SKIN_COLLAGEN", "BLOOD_SUGAR_METABOLIC", "MALE_HEALTH", "THEANINE_SLEEP")


def _text(value: Any) -> str:
    return str(value or "").strip()


def classify_v2_1(row: pd.Series) -> tuple[str, str, float, str]:
    base_key, base_name, base_confidence = classify_service_group(row)
    if base_key != "OTHER_FUNCTIONAL":
        return base_key, base_name, base_confidence, "existing_v2_category"
    # Match the evidence scope used by the V2 detail report. Product names are
    # representative evidence, not enough on their own for a category move.
    haystack = " ".join(_text(row.get(column)) for column in ("product_type", "functional_ingredients", "main_functionality"))
    subgroup_rules = SUBGROUP_RULES["OTHER_FUNCTIONAL"][:6]
    for key, (_, keywords) in zip(SUBGROUP_KEY_ORDER, subgroup_rules):
        name = NEW_GROUPS[key][0]
        matches = [keyword for keyword in keywords if keyword.casefold() in haystack.casefold()]
        if matches:
            return key, name, 0.75, f"other_functional_candidate_keyword:{','.join(matches)}"
    return base_key, base_name, base_confidence, "other_functional_retained"


def build_category_v2_1(frame: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = frame.fillna("").copy()
    for column in data.columns:
        data[column] = data[column].map(_text)
    classifications = [classify_v2_1(row) for _, row in data.iterrows()]
    data["v21_key"], data["v21_name"], data["mapping_confidence"], data["mapping_reason"] = zip(*classifications)

    tree_rows = [{"category_candidate_key": "health-functional-food", "parent_candidate_key": "", "category_name": "건강기능식품", "depth": 1, "product_count": len(data), "source_category_count": int(data["product_type"].replace("", pd.NA).dropna().nunique()), "representative_source_categories": "|".join(data["product_type"].replace("", pd.NA).dropna().value_counts().head(10).index), "representative_products": "|".join(data["name"].head(5)), "generation_reason": "existing V2 root", "confidence": 1.0}]
    for key, group in data.groupby("v21_key", sort=True):
        tree_rows.append({"category_candidate_key": f"health-functional-food:{key.lower()}", "parent_candidate_key": "health-functional-food", "category_name": group.iloc[0]["v21_name"], "depth": 2, "product_count": len(group), "source_category_count": int(group["product_type"].replace("", pd.NA).dropna().nunique()), "representative_source_categories": "|".join(group["product_type"].replace("", pd.NA).dropna().value_counts().head(10).index), "representative_products": "|".join(group["name"].head(20)), "generation_reason": "existing V2 category retained" if key not in NEW_GROUPS else "approved V2.1 split candidate from 기타 기능성 건강식품", "confidence": float(group["mapping_confidence"].mean())})
    tree = pd.DataFrame(tree_rows)
    tree.to_csv(output_dir / "service_category_tree_v2_1.csv", index=False, encoding="utf-8-sig")

    mapping = data[["source_product_id", "name", "product_type", "v21_key", "v21_name", "mapping_confidence"]].rename(columns={"name": "product_name", "product_type": "source_category", "v21_key": "service_category_candidate_key", "v21_name": "service_category_name"})
    mapping.loc[mapping["source_category"] == "", "service_category_candidate_key"] = "UNMAPPED"
    mapping.loc[mapping["source_category"] == "", "service_category_name"] = "미분류"
    mapping.loc[mapping["source_category"] == "", "mapping_confidence"] = 0.0
    mapping.to_csv(output_dir / "product_service_category_mapping_v2_1.csv", index=False, encoding="utf-8-sig")

    validation_rows = []
    for _, row in tree.iterrows():
        group = data[data["v21_key"] == row["category_candidate_key"].split(":")[-1].upper()]
        issues = []
        if row["depth"] > 1 and row["parent_candidate_key"] not in set(tree["category_candidate_key"]): issues.append("parent_missing")
        if len(row["category_name"]) > 80: issues.append("category_name_too_long")
        if row["product_count"] == 0: issues.append("zero_products")
        if row["category_name"] in {value[0] for value in NEW_GROUPS.values()} and row["product_count"] < 20: issues.append("small_new_candidate")
        validation_rows.append({"category_candidate_key": row["category_candidate_key"], "category_name": row["category_name"], "product_count": row["product_count"], "validation_status": "REVIEW" if issues or row["category_name"] in {value[0] for value in NEW_GROUPS.values()} else "PASS", "validation_errors": "|".join(issues), "representative_product_ids": "|".join(group["source_product_id"].head(20)) if not group.empty else "", "representative_product_names": "|".join(group["name"].head(20)) if not group.empty else "", "review_note": "new candidates require human approval" if row["category_name"] in {value[0] for value in NEW_GROUPS.values()} else "existing V2 category retained"})
    pd.DataFrame(validation_rows).to_csv(output_dir / "category_validation_report_v2_1.csv", index=False, encoding="utf-8-sig")

    counts = data["v21_name"].value_counts()
    other_count = int(counts.get("기타 기능성 건강식품", 0))
    weight_terms = SUBGROUP_RULES["OTHER_FUNCTIONAL"][-1][1]
    other = data[data["v21_key"] == "OTHER_FUNCTIONAL"]
    weight_mask = other.apply(lambda row: any(term.casefold() in " ".join(row.get(column, "") for column in ("product_type", "functional_ingredients", "main_functionality", "name")).casefold() for term in weight_terms), axis=1)
    dietary_mask = other.apply(lambda row: any(term.casefold() in " ".join(row.get(column, "") for column in ("product_type", "functional_ingredients", "main_functionality")).casefold() for term in ("차전자피", "식이섬유", "가르시니아", "난소화성말토덱스트린", "이눌린", "프락토올리고당")), axis=1)
    weight_count = int(weight_mask.sum())
    weight_note = "현재 corpus 기준 64건" if weight_count == 64 else f"현재 corpus 재집계 기준 {weight_count}건 (지시문 기준 64건과 차이 발생)"
    report = ["# Category V2 to V2.1 Comparison", "", "- 기존 V2 Category 구조는 유지하고 신규 후보만 같은 depth 2로 추가했습니다.", f"- V2 전체 Category 후보: 10개", f"- V2.1 전체 Category 후보: {len(tree) - 1}개 (root 제외)", f"- Product Mapping 실패: {int((mapping['service_category_candidate_key'] == 'UNMAPPED').sum())}건", "", "## 기타 기능성 건강식품", f"- V2.1 잔여 상품: {other_count:,}건", f"- 체중관리 후보 재현 수: {weight_note}", f"- 식이섬유·체중관리로 이동: {int((weight_mask & dietary_mask).sum()):,}건", "- 이동하지 않은 이유: 현재 후보의 기능성 근거가 기존 식이섬유·체중관리 Group과 일치하지 않아 기타에 유지", "", "## 정책", "- Category ID와 Catalog ID를 생성하지 않았습니다.", "- 신규 Category와 Mapping은 후보이며 최종 승인 전입니다.", "- Facet 관련 로직과 산출물은 수정하지 않았습니다."]
    (output_dir / "category_v2_v2_1_comparison.md").write_text("\n".join(report), encoding="utf-8")
    return {"category_count": len(tree) - 1, "counts": counts.to_dict(), "other_remaining": other_count, "weight_candidates": int(weight_mask.sum()), "weight_reassigned": int((weight_mask & dietary_mask).sum()), "unmapped": int((mapping["service_category_candidate_key"] == "UNMAPPED").sum())}
