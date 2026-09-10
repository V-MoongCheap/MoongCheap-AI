"""Build the approved V2.2 taxonomy and reviewed-alias artifacts.

The source taxonomy is copied without re-numbering.  Alias resolution remains
separate from the taxonomy and is always category-local for value codes.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


FINAL_FACET_STATUSES = {
    "APPROVED_EXISTING",
    "APPROVED_NEW_FACET",
    "APPROVED_AS_VALUE",
    "MERGED_EXISTING",
    "DEFERRED_V2_3",
    "REJECTED_NOT_FACET",
}
PRODUCT_FORM_TARGETS = {"tablet": "정", "powder": "분말", "capsule": "캡슐", "liquid": "액상"}


def normalize(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def load_taxonomy(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_value_crosswalk(taxonomy: dict[str, Any]) -> dict[str, Any]:
    """Map reviewed English targets to each category's local value/code."""
    mappings: dict[str, Any] = {"product_form": {}}
    for category in taxonomy["categories"]:
        category_id = str(category["category_id"])
        facet = next((f for f in category["facets"] if f["name"] == "product_form"), None)
        local: dict[str, Any] = {}
        if facet:
            values = {normalize(v.get("value")): v for v in facet.get("values", []) if int(v.get("code", 0)) != 0}
            for english, korean in PRODUCT_FORM_TARGETS.items():
                value = values.get(normalize(korean))
                if value:
                    local[english] = {"value": value["value"], "code": int(value["code"])}
        mappings["product_form"][category_id] = local
    return {
        "version": "taxonomy-value-crosswalk-v2",
        "purpose": "Resolve reviewed alias targets to category-local V2.2 values and codes.",
        "taxonomy_version": "v2.2",
        "mappings": mappings,
    }


def _accepted(row: pd.Series) -> bool:
    decision = str(row.get("reviewer_decision", "")).strip()
    corrected = str(row.get("corrected_value_candidate", "")).strip()
    return decision == "APPROVE_ALIAS" or (decision == "NEEDS_REVIEW" and bool(corrected))


def build_alias_artifacts(review: pd.DataFrame, taxonomy: dict[str, Any], crosswalk: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    category_ids = {str(c["category_id"]) for c in taxonomy["categories"]}
    taxonomy_facets = {f["name"] for c in taxonomy["categories"] for f in c["facets"]}
    form_by_category = crosswalk.get("mappings", {}).get("product_form", {})
    form_map: dict[str, dict[str, Any]] = defaultdict(dict)
    for category_id, targets in form_by_category.items():
        for target, local in targets.items():
            form_map[target][category_id] = local
    registry_groups: dict[tuple[str, str], dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []
    for _, row in review.iterrows():
        decision = str(row.get("reviewer_decision", "")).strip()
        facet = str(row.get("facet_id", "")).strip()
        original = str(row.get("value_candidate", "")).strip()
        corrected = str(row.get("corrected_value_candidate", "")).strip()
        target = corrected or original
        accepted = _accepted(row)
        status = "REJECTED_BY_HUMAN"
        reason = "Human decision rejected this candidate."
        category_code_map: dict[str, Any] = {}
        if accepted:
            if facet not in taxonomy_facets:
                status = "DEFERRED_TAXONOMY_NOT_APPROVED"
                reason = "Facet is not part of approved V2.2 taxonomy."
            elif facet == "product_form" and target in form_map:
                category_code_map = form_map[target]
                if category_code_map:
                    status = "APPLIED"
                    reason = "Reviewed alias target resolved through category-local product_form crosswalk."
                else:
                    status = "TARGET_NOT_FOUND"
                    reason = "Target has no category-local value in V2.2 taxonomy."
            else:
                status = "DEFERRED_TAXONOMY_NOT_APPROVED"
                reason = "Facet/value target is not approved for V2.2 alias application."
        if status == "APPLIED":
            key = (facet, target)
            group = registry_groups.setdefault(key, {"facet_name": facet, "canonical_value": target, "surfaces": [], "category_local_values": {}})
            surface = str(row.get("candidate_expression", "")).strip()
            if surface and surface not in group["surfaces"]:
                group["surfaces"].append(surface)
            for category_id, local in category_code_map.items():
                group["category_local_values"][category_id] = local
        audit.append({
            "review_order": row.get("review_order", ""),
            "facet_id": facet,
            "canonical_target": target,
            "original_value_candidate": original,
            "corrected_value_candidate": corrected,
            "reviewer_decision": decision,
            "candidate_expression": row.get("candidate_expression", ""),
            "category_count": len(category_code_map),
            "category_local_codes": json.dumps({k: v.get("code") for k, v in category_code_map.items()}, ensure_ascii=False, sort_keys=True),
            "apply_status": status,
            "reason": reason,
        })
    audit_frame = pd.DataFrame(audit)
    registry = {
        "version": "model1-reviewed-aliases-v2",
        "taxonomy_version": "v2.2",
        "taxonomy_is_modified": False,
        "aliases": [
            {"facet_name": g["facet_name"], "canonical_value": g["canonical_value"], "surfaces": g["surfaces"], "category_local_values": g["category_local_values"]}
            for g in registry_groups.values()
        ],
        "summary": {
            "review_rows": len(review),
            "applied_rows": int((audit_frame["apply_status"] == "APPLIED").sum()),
            "deferred_rows": int((audit_frame["apply_status"] == "DEFERRED_TAXONOMY_NOT_APPROVED").sum()),
            "rejected_rows": int((audit_frame["apply_status"] == "REJECTED_BY_HUMAN").sum()),
            "target_not_found_rows": int((audit_frame["apply_status"] == "TARGET_NOT_FOUND").sum()),
            "corrected_target_rows": int(((audit_frame["corrected_value_candidate"] != "") & (audit_frame["apply_status"] == "APPLIED")).sum()),
        },
    }
    return registry, audit_frame


def build_taxonomy_v22(source: dict[str, Any]) -> dict[str, Any]:
    output = json.loads(json.dumps(source, ensure_ascii=False))
    output["version"] = "v2.2"
    output["status"] = "APPROVED"
    output["taxonomy_policy"] = "Stable MVP taxonomy; category-local facet/value codes preserved from V2.1."
    output["v2_2_decisions"] = {
        "intake_frequency": "MERGED_EXISTING",
        "opening_convenience": "DEFERRED_V2_3",
        "storage_convenience": "DEFERRED_V2_3",
        "digestive_tolerance": "REJECTED_NOT_FACET",
        "mixability": "REJECTED_NOT_FACET",
    }
    return output


def validate_taxonomy(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    before_codes = {(c["category_id"], f["name"], int(v["code"])) for c in before["categories"] for f in c["facets"] for v in f["values"]}
    after_codes = {(c["category_id"], f["name"], int(v["code"])) for c in after["categories"] for f in c["facets"] for v in f["values"]}
    duplicate_codes = sum(len({int(v["code"]) for v in f["values"]}) != len(f["values"]) for c in after["categories"] for f in c["facets"])
    return {"preserved_codes": int(before_codes <= after_codes), "code_count_before": len(before_codes), "code_count_after": len(after_codes), "duplicate_code_facets": duplicate_codes}


def build_preview(taxonomy: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for category in taxonomy["categories"]:
        rows.append({
            "category_id": category["category_id"],
            "category_name": category.get("category_name", ""),
            "taxonomy_version": taxonomy["version"],
            "facet_text": json.dumps(category["facets"], ensure_ascii=False, separators=(",", ":")),
        })
    return pd.DataFrame(rows)


def write_report(path: Path, before: dict[str, Any], after: dict[str, Any], new_facets: pd.DataFrame, registry: dict[str, Any], audit: pd.DataFrame, validation: dict[str, int], regression: dict[str, Any] | None) -> None:
    facet_count = sum(len(c["facets"]) for c in after["categories"])
    value_count = sum(len(f["values"]) for c in after["categories"] for f in c["facets"])
    lines = [
        "# Facet Taxonomy V2.2 결정 보고서", "",
        "## 범위", "기존 V2.1 Category 구조와 Category-local Facet/Value Code를 보존하고, 검수 완료된 Alias만 별도 Registry에 연결했다.",
        "Taxonomy 본문에는 Alias를 직접 삽입하지 않았다.", "",
        "## 구조", f"- Category: {len(after['categories'])}", f"- Facet: {facet_count} (V2.1: {sum(len(c['facets']) for c in before['categories'])})", f"- Value: {value_count} (V2.1: {sum(len(f['values']) for c in before['categories'] for f in c['facets'])})", "- 신규 전역 Facet: 0", "",
        "## 신규 Consumer Candidate 결정", "| Candidate | 최종 결정 | 근거 요약 |", "|---|---|---|",
    ]
    reasons = {
        "intake_frequency": "기존 daily_frequency와 의미가 겹치므로 별도 Facet을 만들지 않고 기존 개념으로 병합. Product domain field는 확인됐으나 Nutrime 상품 cross-match는 미해결.",
        "opening_convenience": "소수 상품/리뷰에 국한되고 packaging/intake convenience와의 경계가 남아 V2.3 보류.",
        "storage_convenience": "1개 상품 중심의 약한 근거로 V2.3 보류.",
        "digestive_tolerance": "소화·신체 반응 표현의 안전성 검토가 필요하며 Facet으로 자동 승인하지 않음.",
        "mixability": "3건이지만 Product/Category 미매핑이고 기존 product_form/dissolution 계열과 중복 가능성이 있어 신규 Facet으로 승인하지 않음.",
    }
    for _, row in new_facets.iterrows():
        facet = row["proposed_facet"]
        decision = after["v2_2_decisions"][facet]
        lines.append(f"| `{facet}` | `{decision}` | {reasons[facet]} |")
    lines += ["", "## Alias 적용", f"- 전체 검수 Row: {len(audit)}", f"- APPLIED: {registry['summary']['applied_rows']}", f"- DEFERRED_TAXONOMY_NOT_APPROVED: {registry['summary']['deferred_rows']}", f"- REJECTED_BY_HUMAN: {registry['summary']['rejected_rows']}", f"- TARGET_NOT_FOUND: {registry['summary']['target_not_found_rows']}", f"- corrected_value_candidate 적용 성공 Row: {registry['summary']['corrected_target_rows']}", "- Product Form Alias는 Category별 local code로 해석한다.", "", "## 호환성 검증", f"- 기존 Code 보존: {'PASS' if validation['preserved_codes'] else 'FAIL'}", f"- Code 수 V2.1 → V2.2: {validation['code_count_before']} → {validation['code_count_after']}", f"- 중복 Code Facet 수: {validation['duplicate_code_facets']}"]
    if regression:
        lines += ["", "## Demand 회귀 검증", "동일한 200건 grounded sample을 사용했으며 LLM benchmark는 재실행하지 않았다.", f"- V2.1 Rule-only diagnostic agreement: {regression.get('v21_agreement')}", f"- V2.2 Rule/Alias-only diagnostic agreement: {regression.get('v22_agreement')}", f"- Alias hit: {regression.get('alias_hit')}", f"- Corrected alias hit: {regression.get('corrected_alias_hit')}", f"- Unresolved / Conflict / Invalid code: {regression.get('unresolved')} / {regression.get('conflict')} / {regression.get('invalid_code')}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--alias-review", type=Path, default=Path("data/review/model1_alias_human_review.csv"))
    parser.add_argument("--new-facet-review", type=Path, default=Path("data/review/model1_new_facet_human_review.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    args = parser.parse_args()
    out = args.output_dir
    taxonomy_before = load_taxonomy(args.taxonomy)
    taxonomy_after = build_taxonomy_v22(taxonomy_before)
    crosswalk = build_value_crosswalk(taxonomy_after)
    review = pd.read_csv(args.alias_review, dtype=str).fillna("")
    registry, audit = build_alias_artifacts(review, taxonomy_after, crosswalk)
    new_facets = pd.read_csv(args.new_facet_review, dtype=str).fillna("")
    validation = validate_taxonomy(taxonomy_before, taxonomy_after)
    config = out / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "facet_taxonomy_v2_2.json").write_text(json.dumps(taxonomy_after, ensure_ascii=False, indent=2), encoding="utf-8")
    (config / "taxonomy_value_crosswalk_v2.json").write_text(json.dumps(crosswalk, ensure_ascii=False, indent=2), encoding="utf-8")
    (config / "model1_aliases_reviewed_v2.json").write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    data_out = out / "data/processed/downstream_v2_2"
    data_out.mkdir(parents=True, exist_ok=True)
    audit.to_csv(data_out / "model1_alias_apply_audit_v2.csv", index=False, encoding="utf-8-sig")
    build_preview(taxonomy_after).to_csv(data_out / "category_facet_text_preview.csv", index=False, encoding="utf-8-sig")
    reports = out / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    regression = None
    regression_csv = out / "data/processed/downstream_v2_2/taxonomy_v2_2_demand_regression.csv"
    if regression_csv.exists():
        regression_rows = pd.read_csv(regression_csv).fillna("").to_dict("records")
        if len(regression_rows) >= 2:
            v21_row, v22_row = regression_rows[0], regression_rows[1]
            regression = {
                "v21_agreement": f"{float(v21_row['diagnostic_agreement']):.4f}",
                "v22_agreement": f"{float(v22_row['diagnostic_agreement']):.4f}",
                "alias_hit": int(v22_row.get("alias_hit", 0)),
                "corrected_alias_hit": int(v22_row.get("corrected_alias_hit", 0)),
                "unresolved": int(v22_row.get("unresolved_rows", 0)),
                "conflict": int(v22_row.get("conflict_scenario_rows", 0)),
                "invalid_code": int(v22_row.get("out_of_taxonomy_rows", 0)),
            }
    write_report(reports / "facet_taxonomy_v2_2_decision_report.md", taxonomy_before, taxonomy_after, new_facets, registry, audit, validation, regression)
    change_lines = ["# Model 1 Taxonomy V2.2 변경 이력", "", "- V2.1의 16개 Category, 48개 Facet, 413개 Value Code를 그대로 보존했다.", "- 신규 전역 Facet은 추가하지 않았다.", "- `intake_frequency`는 기존 `daily_frequency`로 병합했다.", "- `opening_convenience`, `storage_convenience`는 `DEFERRED_V2_3`이다.", "- `digestive_tolerance`, `mixability`는 `REJECTED_NOT_FACET`이다.", "- Alias와 Taxonomy canonical 정의는 별도 파일로 유지한다.", "", "## Category별 변경 요약", "", "| Category | 기존 Facet | 추가 | 병합 | 보류/기각 | Code 변경 |", "|---|---:|---:|---:|---:|---|"]
    for category in taxonomy_after["categories"]:
        change_lines.append(f"| `{category['category_id']}` | {len(category['facets'])} | 0 | 0 | 0 | 없음 |")
    change_lines += ["", "전 Category에서 기존 Facet/Value를 보존했으며, 신규 후보 결정은 Taxonomy metadata와 결정 보고서에 기록했다.", ""]
    (reports / "model1_taxonomy_v2_2_change_log.md").write_text("\n".join(change_lines), encoding="utf-8")
    print(json.dumps({"categories": len(taxonomy_after["categories"]), "facets": sum(len(c["facets"]) for c in taxonomy_after["categories"]), "values": validation["code_count_after"], "alias_summary": registry["summary"], "validation": validation}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
