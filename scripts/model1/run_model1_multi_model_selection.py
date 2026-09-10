"""Compare local Model 1 facet discovery models and rank grounded candidates."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd

from moongcheap_ai.data_foundation.model1 import (
    ModelCallError,
    OllamaAdapter,
    parse_model_output,
    sample_products,
)


MODEL_OUTPUT_COLUMNS = [
    "category_key", "category_name", "facet_id_candidate", "name", "definition",
    "value", "alias", "source_product_id", "source_field", "source_text", "status",
]

CATEGORY_QUERY_HINTS = {
    "vitamin_mineral": ("비타민", "미네랄", "칼슘", "철분", "아연", "비오틴", "비타민"),
    "probiotics": ("유산균", "프로바이오틱", "장 건강", "배변", "락토"),
    "skin_collagen": ("콜라겐", "피부", "마스크", "보습", "미백", "주름"),
    "red_ginseng": ("홍삼", "인삼", "진세노사이드"),
    "omega_fatty_acid": ("오메가", "생선", "EPA", "DHA", "지방산"),
    "joint_health": ("관절", "연골", "글루코사민", "콘드로이틴"),
    "eye_health": ("눈 건강", "루테인", "시력", "안구"),
    "liver_health": ("간 건강", "밀크시슬", "간 기능"),
    "heart_blood": ("혈행", "혈압", "콜레스테롤"),
    "dietary_fiber": ("식이섬유", "체중", "다이어트", "배변"),
    "protein": ("단백질", "프로틴", "근육"),
    "blood_sugar_metabolic": ("혈당", "대사", "식후"),
    "theanine_sleep": ("수면", "테아닌", "스트레스", "긴장"),
    "male_health": ("남성", "전립선", "남성 건강"),
    "propolis": ("프로폴리스", "구강", "항산화"),
    "other_functional": (),
}


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def add_query_evidence(sampled: pd.DataFrame, translated: pd.DataFrame, limit: int) -> pd.DataFrame:
    if translated.empty or limit <= 0:
        return sampled
    rows = []
    for category_key, category_name in sampled[["category_key", "category_name"]].drop_duplicates().itertuples(index=False):
        short_key = str(category_key).split(":")[-1]
        hints = CATEGORY_QUERY_HINTS.get(short_key, ())
        pool = translated
        if hints:
            pattern = "|".join(re.escape(hint) for hint in hints)
            pool = translated[translated["query_translated"].astype(str).str.contains(pattern, case=False, regex=True, na=False)]
        pool = pool.drop_duplicates("query_translated").head(limit)
        for row in pool.itertuples():
            rows.append({
                "category_key": category_key,
                "category_name": category_name,
                "source_product_id": f"kuaisearch:{row.source_record_id}",
                "product_name": row.query_translated,
                "source_category": "KuaiSearch consumer query",
                "product_form": "",
                "functional_ingredients": "",
                "regulated_function": row.query_translated,
                "intake_method": "",
                "sampling_reason": "translated consumer-query evidence",
            })
    return pd.concat([sampled, pd.DataFrame(rows)], ignore_index=True) if rows else sampled


def run_model(model_name: str, sampled: pd.DataFrame, categories: set[str], retries: int) -> tuple[list[dict], list[dict], dict]:
    adapter = OllamaAdapter(model_name)
    raw = []
    rows = []
    failures = []
    calls = 0
    started = time.perf_counter()
    for category_key, group in sampled[sampled.category_key.isin(categories)].groupby("category_key", sort=True):
        best = pd.DataFrame(columns=MODEL_OUTPUT_COLUMNS)
        category_failures = []
        for attempt in range(retries + 1):
            try:
                response = adapter.generate_facet_candidates(category_key, group.to_dict("records"), "facet_discovery_multi_model_v1")
                calls += 1
                raw.append({"model": model_name, "category_key": category_key, "attempt": attempt + 1, "response": response})
                parsed, parse_failures = parse_model_output(response, group)
                if not parsed.empty:
                    best = parsed
                if not parse_failures or not parsed.empty:
                    category_failures = parse_failures
                    break
                category_failures = parse_failures
            except ModelCallError as exc:
                calls += 1
                category_failures = [{"failure_type": "MODEL_CALL_FAILED", "detail": str(exc)}]
        rows.extend([{**item, "model": model_name} for item in best.to_dict("records")])
        failures.extend([{**item, "model": model_name, "category_key": category_key} for item in category_failures])
    report = {
        "model": model_name,
        "categories": len(categories),
        "calls": calls,
        "candidate_rows": len(rows),
        "failure_rows": len(failures),
        "successful_categories": len({row["category_key"] for row in rows}),
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }
    return raw, rows, {"report": report, "failures": failures}


def select_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=[*MODEL_OUTPUT_COLUMNS, "model_support", "evidence_count", "selection_score", "selection_status"])
    data = candidates.fillna("").copy()
    data["facet_norm"] = data["name"].map(normalize)
    data["value_norm"] = data["value"].map(normalize)
    grouped = []
    for keys, group in data.groupby(["category_key", "facet_norm", "value_norm"], dropna=False):
        best = group.sort_values(["source_product_id", "model"]).iloc[0].to_dict()
        model_support = group["model"].nunique()
        evidence_count = group["source_product_id"].nunique()
        score = round(model_support * 3 + min(evidence_count, 10) * 0.2, 3)
        grouped.append({**best, "model_support": model_support, "evidence_count": evidence_count, "selection_score": score, "selection_status": "SELECTED_CANDIDATE" if model_support >= 2 else "MODEL_SINGLETON_REVIEW"})
    result = pd.DataFrame(grouped).sort_values(["category_key", "selection_score", "facet_norm", "value_norm"], ascending=[True, False, True, True])
    return result.drop(columns=["facet_norm", "value_norm"], errors="ignore").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--translated", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko_reviewed_v27.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/model1_multi_model_v1"))
    parser.add_argument("--models", default="qwen3:4b,qwen2.5:3b-instruct,gemma3:4b")
    parser.add_argument("--max-per-category", type=int, default=12)
    parser.add_argument("--query-evidence-per-category", type=int, default=6)
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    products = pd.read_csv(args.products, dtype=str).fillna("")
    sampled = sample_products(products, max_per_category=args.max_per_category)
    translated = pd.read_parquet(args.translated).fillna("") if args.translated.exists() else pd.DataFrame()
    sampled = add_query_evidence(sampled, translated, args.query_evidence_per_category)
    sampled.to_json(args.output_dir / "model_input_with_kuaisearch_v1.jsonl", orient="records", lines=True, force_ascii=False)
    categories = {"health-functional-food:vitamin_mineral", "health-functional-food:probiotics", "health-functional-food:skin_collagen"} if args.smoke_only else set(sampled["category_key"].unique())
    all_raw, all_candidates, reports, failures = [], [], [], []
    for model_name in [item.strip() for item in args.models.split(",") if item.strip()]:
        raw, candidates, result = run_model(model_name, sampled, categories, args.retries)
        all_raw.extend(raw); all_candidates.extend(candidates); reports.append(result["report"]); failures.extend(result["failures"])
    (args.output_dir / "model_raw_responses_v1.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in all_raw) + "\n", encoding="utf-8")
    candidate_frame = pd.DataFrame(all_candidates, columns=[*MODEL_OUTPUT_COLUMNS, "model"])
    candidate_frame.to_csv(args.output_dir / "model_candidates_v1.csv", index=False, encoding="utf-8-sig")
    selected = select_candidates(candidate_frame)
    selected.to_csv(args.output_dir / "selected_facet_candidates_v1.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(failures).to_csv(args.output_dir / "model_failures_v1.csv", index=False, encoding="utf-8-sig")
    report = {"status": "COMPLETED", "models": reports, "categories": sorted(categories), "input_rows": len(sampled), "query_evidence_rows": int(sampled.source_product_id.astype(str).str.startswith("kuaisearch:").sum()), "candidate_rows": len(candidate_frame), "selected_rows": len(selected), "consensus_selected_rows": int(selected.selection_status.eq("SELECTED_CANDIDATE").sum()) if not selected.empty else 0, "failure_rows": len(failures), "selection_policy": "model support first, then grounded evidence count; singleton candidates remain review-only", "taxonomy_changed": False}
    (args.output_dir / "multi_model_selection_report_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Model 1 다중 모델 Facet 후보 비교 V1",
        "",
        "- 모델별 후보를 비교하고, 기존 Taxonomy는 변경하지 않았습니다.",
        f"- 대상 Category: {len(categories)}개",
        f"- 입력 행: {len(sampled):,}건",
        f"- KuaiSearch 보조 근거: {report['query_evidence_rows']:,}건",
        f"- 전체 후보: {len(candidate_frame):,}건",
        f"- 모델 합의 후보: {report['consensus_selected_rows']:,}건",
        f"- 실패 건: {len(failures):,}건",
        "",
        "## 모델별 결과",
        "",
        "| 모델 | 호출 | 후보 | 성공 Category | 실패 | 실행 시간(초) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in reports:
        lines.append(f"| {item['model']} | {item['calls']} | {item['candidate_rows']} | {item['successful_categories']} | {item['failure_rows']} | {item['runtime_seconds']} |")
    lines += [
        "",
        "## 자동 선정 규칙",
        "",
        "모델 합의 수를 우선하고, 근거 수를 보조 점수로 사용합니다. 단일 모델 후보는 검토 대상으로 남깁니다.",
        "",
        "## 합의 후보",
        "",
        "| Category | Facet | Value | 모델 수 | 근거 수 | 상태 |",
        "|---|---|---|---:|---:|---|",
    ]
    consensus = selected[selected.selection_status.eq("SELECTED_CANDIDATE")] if not selected.empty else selected
    for row in consensus.head(100).itertuples():
        lines.append(f"| {row.category_key} | {row.name} | {row.value} | {row.model_support} | {row.evidence_count} | {row.selection_status} |")
    lines += [
        "",
        "## 주의사항",
        "",
        "- 단일 모델 후보는 자동 확정하지 않고 검토 대상으로 남겼습니다.",
        "- 규제 기능 문장은 소비자 선호 Facet으로 바로 승인하지 않아야 합니다.",
        "- 모델 입력에 없는 evidence ID를 제시한 결과는 실패로 기록했습니다.",
    ]
    (args.output_dir / "multi_model_selection_report_v1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
