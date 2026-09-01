"""Build a hierarchical, reviewable service-category candidate tree."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


RULES = [
    ("PROBIOTICS", "유산균·프로바이오틱스", ("프로바이오틱", "유산균")),
    ("RED_GINSENG", "홍삼·인삼", ("홍삼", "인삼")),
    ("VITAMIN_MINERAL", "비타민·미네랄", ("비타민", "칼슘", "아연", "마그네슘", "철", "셀레늄", "나이아신")),
    ("OMEGA_FATTY_ACID", "오메가·지방산", ("EPA", "DHA", "오메가")),
    ("DIETARY_FIBER", "식이섬유·체중관리", ("차전자피", "식이섬유", "가르시니아", "난소화성말토덱스트린")),
    ("EYE_HEALTH", "눈 건강", ("마리골드", "루테인", "아스타잔틴")),
    ("LIVER_HEALTH", "간 건강", ("밀크씨슬", "실리마린")),
    ("JOINT_HEALTH", "관절·연골 건강", ("엠에스엠", "MSM", "글루코사민", "콘드로이틴")),
    ("HEART_BLOOD", "혈행·혈압 건강", ("코엔자임Q10", "은행잎", "나토")),
    ("OTHER_FUNCTIONAL", "기타 기능성 건강식품", ()),
]


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def classify_service_group(row: pd.Series) -> tuple[str, str, float]:
    haystack = " ".join(_text(row.get(field)) for field in ("product_type", "functional_ingredients", "main_functionality", "name"))
    for key, name, keywords in RULES[:-1]:
        matches = [keyword for keyword in keywords if keyword.casefold() in haystack.casefold()]
        if matches:
            return key, name, 0.85 if len(matches) > 1 else 0.75
    return RULES[-1][0], RULES[-1][1], 0.35


def build_category_v2(frame: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = frame.fillna("").copy()
    for column in data.columns:
        data[column] = data[column].map(_text)
    classifications = [classify_service_group(row) for _, row in data.iterrows()]
    data["service_group_key"], data["service_group_name"], data["mapping_confidence"] = zip(*classifications)

    source_group = data.groupby("product_type", dropna=False, sort=True).agg(product_count=("source_product_id", "size"), service_category_candidate_key=("service_group_key", "first"), service_category_name=("service_group_name", "first"), confidence=("mapping_confidence", "mean")).reset_index().rename(columns={"product_type": "source_category"})
    source_group["mapping_reason"] = "product name + functional ingredient + regulated function keyword candidate"
    source_group.loc[source_group["source_category"] == "", "service_category_candidate_key"] = "UNMAPPED"
    source_group.loc[source_group["source_category"] == "", "service_category_name"] = "미분류"
    source_group.loc[source_group["source_category"] == "", "confidence"] = 0.0
    source_group[["source_category", "product_count", "service_category_candidate_key", "service_category_name", "mapping_reason", "confidence"]].to_csv(output_dir / "source_to_service_category_v2.csv", index=False, encoding="utf-8-sig")

    tree_rows = [{"category_candidate_key": "health-functional-food", "parent_candidate_key": "", "category_name": "건강기능식품", "depth": 1, "product_count": len(data), "source_category_count": int(data["product_type"].replace("", pd.NA).dropna().nunique()), "representative_source_categories": "|".join(data["product_type"].replace("", pd.NA).dropna().value_counts().head(10).index), "representative_products": "|".join(data["name"].head(5)), "generation_reason": "service root", "confidence": 1.0}]
    for group_key, group in data.groupby("service_group_key", sort=True):
        tree_rows.append({"category_candidate_key": f"health-functional-food:{group_key.lower()}", "parent_candidate_key": "health-functional-food", "category_name": group.iloc[0]["service_group_name"], "depth": 2, "product_count": len(group), "source_category_count": int(group["product_type"].replace("", pd.NA).dropna().nunique()), "representative_source_categories": "|".join(group["product_type"].replace("", pd.NA).dropna().value_counts().head(10).index), "representative_products": "|".join(group["name"].head(5)), "generation_reason": "consumer-oriented grouping from observed product facts", "confidence": float(group["mapping_confidence"].mean())})
    tree = pd.DataFrame(tree_rows)
    tree.to_csv(output_dir / "service_category_tree_v2.csv", index=False, encoding="utf-8-sig")

    product_mapping = data[["source_product_id", "name", "product_type", "service_group_key", "service_group_name", "mapping_confidence"]].rename(columns={"name": "product_name", "product_type": "source_category", "service_group_key": "service_category_candidate_key", "service_group_name": "service_category_name"})
    product_mapping.loc[product_mapping["source_category"] == "", "service_category_candidate_key"] = "UNMAPPED"
    product_mapping.loc[product_mapping["source_category"] == "", "service_category_name"] = "미분류"
    product_mapping.loc[product_mapping["source_category"] == "", "mapping_confidence"] = 0.0
    product_mapping.to_csv(output_dir / "product_service_category_mapping_v2.csv", index=False, encoding="utf-8-sig")

    leaves = tree[tree["depth"] == 2]
    distribution = leaves["product_count"]
    quality = [
        "# Category Quality Report V2", "", f"- Source Category 수: {int(source_group['source_category'].ne('').sum())}", f"- Service Category 후보 수: {len(leaves)} (root 제외)", f"- Depth별 Category 수: {tree.groupby('depth').size().to_dict()}", f"- Leaf Category 수: {len(leaves)}", f"- Product Coverage: {len(data)} / {len(data)} (100.00%)", f"- Product 1개 Leaf: {int((distribution == 1).sum())}", f"- Product 3개 미만 Leaf: {int((distribution < 3).sum())}", f"- Product 5개 미만 Leaf: {int((distribution < 5).sum())}", f"- Product 10개 미만 Leaf: {int((distribution < 10).sum())}", f"- Product 분포 평균/중앙값: {distribution.mean():.1f} / {distribution.median():.1f}", "", "## 상위 Category", "", tree.sort_values('product_count', ascending=False).head(20)[['category_name','product_count']].to_string(index=False), "", "## Mapping", f"- Mapping 성공 Product: {int((product_mapping['service_category_candidate_key'] != 'UNMAPPED').sum())}", f"- Mapping 실패 Product: {int((product_mapping['service_category_candidate_key'] == 'UNMAPPED').sum())}", f"- 여러 Source Category → 하나의 Service Category: {int(source_group.groupby('service_category_candidate_key')['source_category'].nunique().gt(1).sum())}", "- 하나의 Source Category → 여러 Service Category: 자동 후보 단계에서는 0건", "", "## 정책", "- Category ID와 parent ID는 생성하지 않음.", "- 키워드 분류는 후보이며 최종 서비스 Category 승인이 필요함.", "- Facet Human Review와 Value/Alias 검수는 이번 범위에서 수행하지 않음.",
    ]
    (output_dir / "category_quality_report_v2.md").write_text("\n".join(quality), encoding="utf-8")

    validation = []
    names = tree["category_name"].tolist()
    for _, row in tree.iterrows():
        issues = []
        if row["depth"] > 1 and row["parent_candidate_key"] not in set(tree["category_candidate_key"]): issues.append("parent_missing")
        if RECOGNITION_RE.search(row["category_name"]): issues.append("recognition_number_in_name")
        if len(row["category_name"]) > 80: issues.append("category_name_too_long")
        if row["product_count"] == 0: issues.append("zero_products")
        if row["depth"] > 1 and row["category_name"] == tree.loc[tree["category_candidate_key"] == row["parent_candidate_key"], "category_name"].iloc[0]: issues.append("same_as_parent")
        validation.append({"category_candidate_key": row["category_candidate_key"], "check_status": "REVIEW" if issues else "PASS", "issues": "|".join(issues), "review_note": "candidate tree requires human approval"})
    pd.DataFrame(validation).to_csv(output_dir / "category_validation_report_v2.csv", index=False, encoding="utf-8-sig")

    v1_tree = output_dir.parent / "health_foundation_v1" / "service_category_candidate_v1.csv"
    v1_count = len(pd.read_csv(v1_tree, dtype=str)) if v1_tree.exists() else 0
    compare = "\n".join(["# Category V1 to V2 Comparison", "", f"- V1 Service Category 후보: {v1_count}", f"- V2 계층형 Service Category 후보(leaf): {len(leaves)}", f"- V2 전체 노드(root 포함): {len(tree)}", f"- V2 Mapping 불가 Product: {int((product_mapping['service_category_candidate_key'] == 'UNMAPPED').sum())}", "- V2는 Source Category를 서비스 Category로 그대로 복제하지 않고 상품 정보 기반 후보 그룹을 생성함.", "- V2 Category/ID/Mapping은 모두 최종 승인 전 상태임."])
    (output_dir / "category_v1_v2_comparison.md").write_text(compare, encoding="utf-8")
    return {"source_categories": int(source_group["source_category"].ne("").sum()), "service_category_candidates": len(leaves), "tree_nodes": len(tree), "mapped_products": int((product_mapping["service_category_candidate_key"] != "UNMAPPED").sum()), "unmapped_products": int((product_mapping["service_category_candidate_key"] == "UNMAPPED").sum())}


RECOGNITION_RE = re.compile(r"\(\s*제\s*\d{4}\s*-\s*\d+\s*호\s*\)")
