"""Run multi-family Facet Discovery over product and seller evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd

from moongcheap_ai.data_foundation.model1 import (
    MODEL_OUTPUT_COLUMNS,
    ModelCallError,
    create_model_adapter,
    parse_model_output,
    sample_products,
)


PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "facet_discovery_multisource_v1.txt"
CATEGORY_KEYS = {
    "health-functional-food:vitamin_mineral",
    "health-functional-food:probiotics",
    "health-functional-food:skin_collagen",
}
SOURCE_COLUMNS = [
    "category_key", "category_name", "source_product_id", "product_name",
    "source_category", "product_form", "functional_ingredients",
    "regulated_function", "consumer_search_text", "intake_method", "sampling_reason", "source_type",
    "price_text", "quantity_text", "seller_condition", "evidence_text",
]


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value).casefold())


def _clean_output_text(value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    return value


def _empty_sources() -> pd.DataFrame:
    return pd.DataFrame(columns=SOURCE_COLUMNS)


def _as_source_rows(frame: pd.DataFrame, source_type: str) -> pd.DataFrame:
    result = frame.copy().fillna("")
    for column in SOURCE_COLUMNS:
        if column not in result:
            result[column] = ""
    result["source_type"] = source_type
    return result[SOURCE_COLUMNS]


def load_products(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_sources()
    products = pd.read_csv(path, dtype=str).fillna("")
    sampled = sample_products(products, max_per_category=8)
    sampled = sampled.rename(columns={"name": "product_name", "product_type": "source_category"})
    sampled["source_type"] = "MFDS_PRODUCT"
    sampled["evidence_text"] = sampled.apply(lambda row: " | ".join(_text(row.get(column)) for column in ("product_name", "product_form", "functional_ingredients", "regulated_function") if _text(row.get(column))), axis=1)
    return _as_source_rows(sampled, "MFDS_PRODUCT")


def load_seller_offers(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_sources()
    frame = pd.read_csv(path, dtype=str).fillna("")
    frame = frame[frame.get("health_scope", "").astype(str).eq("core")].copy()
    normalized = pd.DataFrame({
        "source_product_id": "seller:" + frame.get("item_id", "").astype(str),
        "product_name": frame.get("title", ""),
        "source_category": frame.get("category", ""),
        "product_form": frame.get("package_spec", ""),
        "functional_ingredients": frame.get("ingredients_raw", ""),
        "regulated_function": frame.get("functionality_raw", ""),
        "intake_method": frame.get("intake_raw", ""),
        "price_text": frame.get("base_unit_price", ""),
        "quantity_text": frame.get("moq", ""),
        "seller_condition": frame.get("semantic_text", ""),
        "sampling_reason": "seller listing evidence",
    })
    normalized["product_type"] = normalized["source_category"]
    sampled = sample_products(normalized, max_per_category=8)
    sampled = sampled.rename(columns={"name": "product_name", "product_type": "source_category"})
    sampled["source_product_id"] = sampled["source_product_id"].map(lambda value: value if str(value).startswith("seller:") else f"seller:{value}")
    sampled["evidence_text"] = sampled.apply(lambda row: " | ".join(_text(row.get(column)) for column in ("product_name", "source_category", "functional_ingredients", "price_text", "quantity_text", "seller_condition") if _text(row.get(column))), axis=1)
    return _as_source_rows(sampled, "SELLER_LISTING")


def load_demands(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_sources()
    frame = pd.read_csv(path, dtype=str).fillna("")
    requirement = frame.get("extra_requirement", "")
    normalized = pd.DataFrame({
        "category_key": frame.get("category_id", ""),
        "category_name": frame.get("category_id", ""),
        "source_product_id": "demand:" + frame.get("demand_id", "").astype(str),
        "product_name": frame.get("catalog_id", ""),
        "source_category": frame.get("reference_source", ""),
        "product_form": frame.get("facet_requirements", ""),
        "functional_ingredients": "",
        "regulated_function": requirement,
        "intake_method": requirement,
        "sampling_reason": "grounded synthetic demand evidence",
        "price_text": frame.get("price_option", ""),
        "quantity_text": frame.get("quantity", ""),
        "evidence_text": requirement,
    })
    normalized = normalized[normalized["category_key"].isin(CATEGORY_KEYS)]
    rows = []
    for category_key, group in normalized.groupby("category_key", sort=True):
        rows.append(group.head(8))
    return _as_source_rows(pd.concat(rows, ignore_index=True) if rows else normalized, "GROUNDED_DEMAND_SYNTHETIC")


def load_boards(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_sources()
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for board in payload.get("demandBoards", []):
        category_key = _text(board.get("categoryId"))
        if category_key not in CATEGORY_KEYS:
            continue
        evidence = f"participants={board.get('participantCount', '')}; price={board.get('priceMin', '')}-{board.get('priceMax', '')}; status={board.get('status', '')}"
        rows.append({
            "category_key": category_key,
            "category_name": category_key,
            "source_product_id": f"board:{board.get('demandBoardId', '')}",
            "product_name": _text(board.get("catalogId")),
            "source_category": category_key,
            "sampling_reason": "synthetic demand board aggregate",
            "price_text": f"{board.get('priceMin', '')}-{board.get('priceMax', '')}",
            "quantity_text": _text(board.get("participantCount")),
            "seller_condition": _text(board.get("status")),
            "evidence_text": evidence,
        })
    return _as_source_rows(pd.DataFrame(rows), "DEMAND_BOARD_SYNTHETIC") if rows else _empty_sources()


def load_translated_queries(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_sources()
    frame = pd.read_parquet(path).fillna("")
    query = frame.get("query_translated", pd.Series(dtype=str)).astype(str)
    rows = []
    for category_key, hints in {
        "health-functional-food:vitamin_mineral": ("비타민", "미네랄", "칼슘", "철분", "아연"),
        "health-functional-food:probiotics": ("유산균", "프로바이오틱", "배변", "장 건강"),
        "health-functional-food:skin_collagen": ("콜라겐", "피부", "보습", "주름"),
    }.items():
        mask = query.str.contains("|".join(re.escape(item) for item in hints), case=False, regex=True, na=False)
        for item in frame[mask].drop_duplicates("query_translated").head(4).itertuples():
            rows.append({
                "category_key": category_key,
                "category_name": category_key,
                "source_product_id": f"kuaisearch:{item.source_record_id}",
                "product_name": item.query_translated,
                "source_category": "KuaiSearch translated query",
                "consumer_search_text": item.query_translated,
                "sampling_reason": "translated consumer search evidence",
                "evidence_text": item.query_translated,
            })
    return _as_source_rows(pd.DataFrame(rows), "CONSUMER_SEARCH") if rows else _empty_sources()


def build_multisource_input(paths: dict[str, Path]) -> pd.DataFrame:
    # Demand data describes request conditions, not product attributes. Keep it
    # in the demand-labeling pipeline instead of allowing it to create facets.
    frames = [
        load_products(paths["products"]),
        load_seller_offers(paths["sellers"]),
        load_translated_queries(paths["queries"]),
    ]
    data = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)
    if data.empty:
        return _empty_sources()
    return data[data["category_key"].isin(CATEGORY_KEYS)].drop_duplicates(["category_key", "source_product_id"]).reset_index(drop=True)


def parse_reasoned_output(payload: dict[str, Any], input_frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    parsed, failures = parse_model_output(payload, input_frame)
    if parsed.empty:
        return parsed, failures
    reasons = {str(item.get("name", "")): _text(item.get("selection_reason") or item.get("reason")) for item in payload.get("facets", [])}
    value_reasons = {
        (str(item.get("name", "")), str(value.get("value", ""))): _text(value.get("value_reason"))
        for item in payload.get("facets", [])
        for value in item.get("values", [])
    }
    source_types = dict(zip(input_frame["source_product_id"].astype(str), input_frame["source_type"].astype(str)))
    parsed["selection_reason"] = parsed["name"].map(reasons).fillna("")
    parsed["value_reason"] = [value_reasons.get((str(name), str(value)), "") for name, value in zip(parsed["name"], parsed["value"])]
    parsed["reason"] = parsed["selection_reason"]
    parsed["evidence_source_type"] = parsed["source_product_id"].map(source_types).fillna("")
    parsed["reason_status"] = parsed["selection_reason"].map(lambda value: "PRESENT" if value else "MISSING")
    return parsed, failures


def add_data_selection_reason(candidates: pd.DataFrame, input_data: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    result = candidates.copy()
    text_columns = [column for column in ("product_name", "product_form", "functional_ingredients", "regulated_function", "consumer_search_text", "intake_method", "price_text", "quantity_text", "seller_condition", "evidence_text") if column in input_data.columns]
    source_counts = input_data.groupby(["category_key", "source_type"])["source_product_id"].nunique().to_dict()
    category_counts = input_data.groupby("category_key")["source_product_id"].nunique().to_dict()
    observed_cache: dict[tuple[str, str], tuple[int, list[str]]] = {}
    for key, group in result.groupby(["category_key", "value"], dropna=False):
        category_key, value = key
        value_norm = _normalize(value)
        category_rows = input_data[input_data["category_key"].eq(category_key)]
        mask = category_rows[text_columns].astype(str).apply(lambda column: column.map(_normalize).str.contains(re.escape(value_norm), regex=True, na=False)).any(axis=1) if value_norm else pd.Series(False, index=category_rows.index)
        observed = category_rows[mask]
        observed_types = sorted(observed["source_type"].drop_duplicates().tolist())
        observed_cache[key] = (len(observed), observed_types)
    evidence_counts = result.groupby(["model", "category_key", "name", "value"], dropna=False)["source_product_id"].nunique().to_dict()
    reasons = []
    observed_rows = []
    observed_type_counts = []
    observed_types_text = []
    for row in result.itertuples():
        key = (row.category_key, row.value)
        count, types = observed_cache[key]
        evidence_type = _text(row.evidence_source_type)
        evidence_count = int(evidence_counts.get((row.model, row.category_key, row.name, row.value), 0))
        source_text = ", ".join(f"{item}: {int(source_counts.get((row.category_key, item), 0))}건" for item in types)
        reasons.append(f"{row.model}의 {row.category_key} 후보. 입력 {int(category_counts.get(row.category_key, 0))}건 중 값과 일치하는 행 {count}건; 관찰 출처 {source_text or evidence_type or '없음'}; 모델 근거 {evidence_count}건.")
        observed_rows.append(count)
        observed_type_counts.append(len(types))
        observed_types_text.append("|".join(types))
    result["observed_row_count"] = observed_rows
    result["observed_source_type_count"] = observed_type_counts
    result["observed_source_types"] = observed_types_text
    result["data_selection_reason"] = reasons
    return result


def select_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    data = candidates.fillna("").copy()
    data["facet_norm"] = data["name"].map(_normalize)
    data["value_norm"] = data["value"].map(_normalize)
    rows = []
    for _, group in data.groupby(["category_key", "facet_norm", "value_norm"], dropna=False):
        best = group.sort_values(["source_product_id", "model"]).iloc[0].to_dict()
        models = group["model"].nunique()
        sources = group["evidence_source_type"].replace("", pd.NA).dropna().nunique()
        rows.append({**best, "model_support": models, "source_type_count": int(sources), "selection_score": round(models * 3 + min(int(sources), 5) * 0.5, 3), "selection_status": "SELECTED_CANDIDATE" if models >= 2 and sources >= 2 else "REVIEW_ONLY"})
    return pd.DataFrame(rows).drop(columns=["facet_norm", "value_norm"], errors="ignore").reset_index(drop=True)


def run_model(model_name: str, data: pd.DataFrame, categories: set[str], retries: int, provider: str = "ollama", endpoint: str = "", api_key: str = "") -> tuple[list[dict], list[dict], dict, list[dict]]:
    adapter = create_model_adapter(provider, model_name, endpoint=endpoint, api_key=api_key, prompt_path=PROMPT_PATH)
    raw, candidates, failures = [], [], []
    started = time.perf_counter()
    calls = 0
    for category_key, group in data[data["category_key"].isin(categories)].groupby("category_key", sort=True):
        for attempt in range(retries + 1):
            try:
                response = adapter.generate_facet_candidates(category_key, group.to_dict("records"), "facet_discovery_multisource_v1")
                calls += 1
                raw.append({"model": model_name, "category_key": category_key, "attempt": attempt + 1, "response": response})
                parsed, parse_failures = parse_reasoned_output(response, group)
                if not parsed.empty:
                    candidates.extend([{**row, "model": model_name} for row in parsed.to_dict("records")])
                failures.extend([{**item, "model": model_name, "category_key": category_key} for item in parse_failures])
                if not parse_failures or not parsed.empty:
                    break
            except ModelCallError as exc:
                calls += 1
                failures.append({"failure_type": "MODEL_CALL_FAILED", "detail": str(exc), "model": model_name, "category_key": category_key})
    report = {"provider": adapter.provider, "model": model_name, "calls": calls, "candidate_rows": len(candidates), "failure_rows": len(failures), "runtime_seconds": round(time.perf_counter() - started, 3)}
    return raw, candidates, report, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", type=Path, default=Path("data/interim/facet_discovery/i0030_products_clean_dedup.csv"))
    parser.add_argument("--sellers", type=Path, default=Path("data/processed/domeggook/seller_offers_core.csv"))
    parser.add_argument("--demands", type=Path, default=Path("data/synthetic/consumer_reference/grounded_demand_v2_1000.csv"))
    parser.add_argument("--boards", type=Path, default=Path(r"F:\downloadF\demand_board_snapshot_5000.json"))
    parser.add_argument("--queries", type=Path, default=Path("data/interim/facet_evidence/kuaiseach_health_queries_ko_reviewed_v27.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/model1_multisource_v1"))
    parser.add_argument("--models", default="qwen3:4b,gemma3:4b,llama3.2:3b,exaone3.5:2.4b-instruct-q4_K_M,phi4-mini")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "transformers", "huggingface", "openai", "openai_compatible", "vllm", "lm_studio"])
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--api-key-env", default="")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument("--retries", type=int, default=0)
    args = parser.parse_args()
    api_key = os.getenv(args.api_key_env, "") if args.api_key_env else ""
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = build_multisource_input({"products": args.products, "sellers": args.sellers, "demands": args.demands, "boards": args.boards, "queries": args.queries})
    data.to_json(args.output_dir / "multisource_model_input_v1.jsonl", orient="records", lines=True, force_ascii=False)
    categories = CATEGORY_KEYS if args.smoke_only else set(data["category_key"].unique())
    all_raw, all_candidates, model_reports, failures = [], [], [], []
    for model_name in [item.strip() for item in args.models.split(",") if item.strip()]:
        raw, candidates, report, model_failures = run_model(model_name, data, categories, args.retries, provider=args.provider, endpoint=args.endpoint, api_key=api_key)
        all_raw.extend(raw); all_candidates.extend(candidates); model_reports.append(report); failures.extend(model_failures)
    candidate_frame = pd.DataFrame(all_candidates)
    if not candidate_frame.empty:
        for column in candidate_frame.columns:
            candidate_frame[column] = candidate_frame[column].map(_clean_output_text)
    candidate_frame = add_data_selection_reason(candidate_frame, data)
    selected = select_candidates(candidate_frame)
    raw_path = args.output_dir / "multisource_model_raw_v1.jsonl"
    raw_path.write_text("\n".join(json.dumps(row, ensure_ascii=True) for row in all_raw) + "\n", encoding="utf-8")
    candidate_frame.to_csv(args.output_dir / "multisource_model_candidates_v1.csv", index=False, encoding="utf-8-sig")
    reason_columns = [
        "model", "category_key", "category_name", "name", "value",
        "selection_reason", "value_reason", "source_product_id",
        "source_field", "source_text", "evidence_source_type", "reason_status", "observed_row_count", "observed_source_type_count", "observed_source_types", "data_selection_reason",
    ]
    candidate_frame.reindex(columns=reason_columns, fill_value="").sort_values(
        ["model", "category_key", "name", "value"]
    ).to_csv(args.output_dir / "multisource_model_reason_comparison_v1.csv", index=False, encoding="utf-8-sig")
    selected.to_csv(args.output_dir / "multisource_selected_candidates_v1.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(failures).to_csv(args.output_dir / "multisource_model_failures_v1.csv", index=False, encoding="utf-8-sig")
    source_counts = data["source_type"].value_counts().to_dict() if not data.empty else {}
    report = {"status": "COMPLETED", "models": model_reports, "categories": sorted(categories), "input_rows": len(data), "source_row_counts": source_counts, "candidate_rows": len(candidate_frame), "selected_rows": len(selected), "consensus_selected_rows": int(selected.selection_status.eq("SELECTED_CANDIDATE").sum()) if not selected.empty else 0, "reason_present_rows": int(candidate_frame.reason_status.eq("PRESENT").sum()) if not candidate_frame.empty and "reason_status" in candidate_frame else 0, "failure_rows": len(failures), "excluded_sources": ["GROUNDED_DEMAND_SYNTHETIC", "DEMAND_BOARD_SYNTHETIC"], "taxonomy_changed": False}
    (args.output_dir / "multisource_facet_discovery_report_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 다중 소스 Facet Discovery V1", "", f"- 대상 Category: {len(categories)}개", f"- 입력 행: {len(data):,}건", f"- 전체 후보: {len(candidate_frame):,}건", f"- 합의 후보: {report['consensus_selected_rows']:,}건", f"- 이유 포함 후보: {report['reason_present_rows']:,}건", f"- 실패: {len(failures):,}건", "", "## 입력 소스", "", "| 소스 유형 | 행 수 |", "|---|---:|"]
    lines.extend(f"| {key} | {value:,} |" for key, value in sorted(source_counts.items()))
    lines += ["", "## 모델별 실행", "", "| 모델 | 호출 | 후보 | 실패 | 실행 시간(초) |", "|---|---:|---:|---:|---:|"]
    lines.extend(f"| {item['model']} | {item['calls']} | {item['candidate_rows']} | {item['failure_rows']} | {item['runtime_seconds']} |" for item in model_reports)
    lines += ["", "## 모델별 선정 이유", "", "아래 이유는 모델별 원본 후보 설명입니다. 모델 간 공통 후보가 아니어도 각 모델의 판단을 비교할 수 있습니다."]
    for model_name, group in candidate_frame.groupby("model", sort=True) if "model" in candidate_frame.columns else []:
        lines += ["", f"### {model_name}", "", "| Category | Facet | Value | 실제 데이터 관찰 요약 | 모델 설명 | 값의 의미 |", "|---|---|---|---|---|---|"]
        for row in group.head(20).itertuples():
            lines.append(f"| {row.category_key} | {row.name} | {row.value} | {row.data_selection_reason} | {row.selection_reason} | {row.value_reason} |")
    lines += ["", "## 해석", "", "data_selection_reason은 모델별 후보가 실제 입력 Category에서 몇 건 관찰됐고 어떤 출처 유형에 분포하는지 계산한 설명입니다. selection_reason과 value_reason은 모델이 반환한 보조 설명입니다.", "", "합성 구매 요청과 수요 보드의 가격·시간·참여자 수는 실제 사용자 행동으로 해석하지 않습니다."]
    (args.output_dir / "multisource_facet_discovery_report_v1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
