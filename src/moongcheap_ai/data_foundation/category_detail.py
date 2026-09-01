"""Detail analysis for selected service-category candidates; no category mutation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from .category_v2 import classify_service_group
from .health_v1 import split_ingredient_text, split_recognition_number


TARGETS = {"VITAMIN_MINERAL": "비타민·미네랄", "OTHER_FUNCTIONAL": "기타 기능성 건강식품"}
FUNCTION_GROUPS = ("면역력", "피로", "혈행", "기억력", "항산화", "배변", "장 건강", "관절", "눈 건강", "혈당", "체지방", "간 건강", "피부", "콜레스테롤", "혈압", "수면")
SUBGROUP_RULES = {
    "VITAMIN_MINERAL": (("비타민", ("비타민",)), ("미네랄", ("칼슘", "아연", "마그네슘", "철", "셀레늄", "구리", "망간"))),
    "OTHER_FUNCTIONAL": (("단백질", ("단백질",)), ("프로폴리스", ("프로폴리스",)), ("피부·콜라겐", ("콜라겐", "히알루론산", "피부")), ("혈당·대사", ("바나바", "혈당", "코엔자임Q10")), ("남성 건강", ("쏘팔메토", "남성")), ("테아닌·수면", ("테아닌", "수면")), ("체중관리", ("체중", "가르시니아", "식이섬유"))),
}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _representatives(group: pd.DataFrame) -> tuple[str, str]:
    return "|".join(group["name"].drop_duplicates().head(5)), "|".join(group["source_product_id"].drop_duplicates().head(5))


def _add_rows(rows: list[dict[str, Any]], category_key: str, category_name: str, analysis_type: str, series: pd.Series, frame: pd.DataFrame, top_n: int = 30, denominator: int | None = None) -> None:
    counts = series[series != ""].value_counts().head(top_n)
    total = denominator or len(frame)
    for rank, (value, count) in enumerate(counts.items(), 1):
        group = frame.loc[series == value]
        names, ids = _representatives(group)
        rows.append({"category_key": category_key, "category_name": category_name, "analysis_type": analysis_type, "rank": rank, "group_value": value, "product_count": int(count), "category_ratio": float(count / total), "source_category_count": int(group["product_type"].replace("", pd.NA).dropna().nunique()), "representative_source_product_ids": ids, "representative_product_names": names})


def build_category_detail_analysis(frame: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = frame.fillna("").copy()
    for column in data.columns:
        data[column] = data[column].map(_text)
    classifications = [classify_service_group(row) for _, row in data.iterrows()]
    data["service_group_key"], data["service_group_name"], _ = zip(*classifications)
    rows: list[dict[str, Any]] = []
    report_sections: list[str] = ["# Category Detail Analysis V2", "", "V2 Category Tree와 Product Mapping은 변경하지 않았습니다. 아래는 분할 여부 판단을 위한 분석 후보입니다."]
    for key, name in TARGETS.items():
        category = data[data["service_group_key"] == key].copy()
        total = len(category)
        if not total:
            continue
        _add_rows(rows, key, name, "SOURCE_CATEGORY_TOP30", category["product_type"], category)
        ingredient_rows = []
        for _, product in category.iterrows():
            tokens, _ = split_ingredient_text(product["functional_ingredients"])
            for token in tokens:
                canonical, _ = split_recognition_number(token)
                canonical = _text(canonical)
                if canonical:
                    ingredient_rows.append({"source_product_id": product["source_product_id"], "name": product["name"], "product_type": product["product_type"], "ingredient": canonical})
        ingredient_frame = pd.DataFrame(ingredient_rows)
        ingredient_series = ingredient_frame["ingredient"] if not ingredient_frame.empty else pd.Series(dtype=str)
        _add_rows(rows, key, name, "NORMALIZED_FUNCTIONAL_INGREDIENT_TOP30", ingredient_series, ingredient_frame, denominator=total)
        function_series = category["main_functionality"].map(lambda value: next((term for term in FUNCTION_GROUPS if term in value), "UNCLASSIFIED"))
        _add_rows(rows, key, name, "REGULATED_FUNCTION_GROUP", function_series, category)
        subgroup_series = category.apply(lambda row: next((group_name for group_name, keywords in SUBGROUP_RULES[key] if any(keyword.casefold() in (row["product_type"] + " " + row["functional_ingredients"] + " " + row["main_functionality"]).casefold() for keyword in keywords)), "UNSPECIFIED"), axis=1)
        _add_rows(rows, key, name, "CANDIDATE_SUBGROUP", subgroup_series, category, top_n=50)
        report_sections.extend(["", f"## {name}", f"- Category 상품 수: {total:,}건", "- 아래 Group은 자동 분할 결과가 아닌 검토용 후보입니다."])
        report_sections.append("\n### 후보 하위 Group")
        subgroup_counts = subgroup_series.value_counts()
        for subgroup, count in subgroup_counts.items():
            report_sections.append(f"- {subgroup}: {int(count):,}건 ({count / total:.2%})")
        report_sections.append("\n### 분할 판단 질문")
        if key == "VITAMIN_MINERAL":
            report_sections.append("- 비타민과 미네랄이 각각 충분한 상품 규모와 독립적인 탐색 목적을 가지는지 확인해야 합니다.")
        else:
            report_sections.append("- 특정 Group이 독립 Category로 분리할 만큼 규모와 소비자 탐색 의미를 동시에 가지는지 확인해야 합니다.")
        report_sections.append("- 대표 상품과 Source Category 분포는 CSV의 각 분석 유형에서 확인합니다.")
    result = pd.DataFrame(rows)
    result.to_csv(output_dir / "category_detail_analysis_v2.csv", index=False, encoding="utf-8-sig")
    report_sections.extend(["", "## 해석 주의", "- Source Category, 기능성 원료, 기능성 문구는 원천 근거이지 서비스 Category 확정값이 아닙니다.", "- 상품은 중복 Group에 자동 복제하지 않고 첫 번째 규칙에 따라 후보 Group 하나에만 배정했습니다.", "- Category 추가·삭제, Product Mapping 변경, Facet 검수는 수행하지 않았습니다."])
    (output_dir / "category_detail_analysis_v2.md").write_text("\n".join(report_sections), encoding="utf-8")
    return {"categories": {key: int((data["service_group_key"] == key).sum()) for key in TARGETS}, "rows": len(result), "output": str(output_dir)}
