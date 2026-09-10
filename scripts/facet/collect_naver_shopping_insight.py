"""Collect Korean Shopping Insight evidence for reviewed facet candidates.

The API reports relative shopping-click trends, not raw search volume or
purchase counts. Results are therefore stored as consumer-salience evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv


API_URL = "https://naverapihub.apigw.ntruss.com/shopping/v1/category/keywords"
REQUIRED_COLUMNS = ("category_key", "facet_name", "facet_value")


def load_category_map(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("category map must be a JSON object")
    return {str(key): str(value) for key, value in payload.items() if str(value).strip()}


def build_requests(
    candidates: pd.DataFrame,
    category_map: dict[str, str],
    start_date: str,
    end_date: str,
    time_unit: str,
    max_keywords: int = 100,
) -> list[dict[str, Any]]:
    missing = [column for column in REQUIRED_COLUMNS if column not in candidates.columns]
    if missing:
        raise ValueError(f"candidate input is missing columns: {missing}")
    rows = candidates[list(REQUIRED_COLUMNS)].fillna("").astype(str)
    rows["facet_value"] = rows["facet_value"].str.replace(r"\s+", " ", regex=True).str.strip()
    rows = rows[(rows["category_key"].isin(category_map)) & rows["facet_value"].ne("")]
    rows = rows.drop_duplicates(["category_key", "facet_name", "facet_value"])
    requests_to_send: list[dict[str, Any]] = []
    for category_key, group in rows.groupby("category_key", sort=True):
        terms = group.head(max_keywords)
        pairs = [
            {"name": f"{row.facet_name}:{row.facet_value}", "param": [row.facet_value]}
            for row in terms.itertuples()
        ]
        for offset in range(0, len(pairs), 5):
            requests_to_send.append({
                "category_key": category_key,
                "category_id": category_map[category_key],
                "body": {
                    "startDate": start_date,
                    "endDate": end_date,
                    "timeUnit": time_unit,
                    "category": category_map[category_key],
                    "keyword": pairs[offset:offset + 5],
                },
            })
    return requests_to_send


def flatten_response(request_meta: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for result in payload.get("results", []):
        title = str(result.get("title", ""))
        facet_candidate, _, value_candidate = title.partition(":")
        for point in result.get("data", []):
            rows.append({
                "service_category": request_meta["category_key"],
                "naver_category_id": request_meta["category_id"],
                "facet_keyword_group": title,
                "facet_candidate": facet_candidate,
                "value_candidate": value_candidate,
                "keyword": ",".join(result.get("keyword", [])),
                "period": point.get("period", ""),
                "ratio": point.get("ratio"),
                "source": "NAVER_SHOPPING_INSIGHT",
                "source_type": "CONSUMER_SEARCH_TREND",
            })
    return rows


def collect(
    requests_to_send: list[dict[str, Any]],
    client_id: str,
    client_secret: str,
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
        "Content-Type": "application/json",
    }
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for request_meta in requests_to_send:
        response = requests.post(API_URL, headers=headers, json=request_meta["body"], timeout=timeout)
        if response.ok:
            rows.extend(flatten_response(request_meta, response.json()))
        else:
            failures.append({
                "category_key": request_meta["category_key"],
                "status_code": response.status_code,
                "response": response.text[:1000],
            })
    return rows, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/processed/model1_multisource_v1/multisource_candidate_readable_v1.csv"))
    parser.add_argument("--category-map", type=Path, required=True, help="JSON mapping of internal category_key to Naver cat_id")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/facet_discovery/naver_shopping_insight"))
    parser.add_argument("--start-date", default=(date.today() - timedelta(days=365)).isoformat())
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--time-unit", choices=("date", "week", "month"), default="month")
    parser.add_argument("--max-keywords", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates = pd.read_csv(args.input, dtype=str).fillna("")
    category_map = load_category_map(args.category_map)
    request_list = build_requests(candidates, category_map, args.start_date, args.end_date, args.time_unit, args.max_keywords)
    (args.output_dir / "naver_shopping_insight_request_preview.json").write_text(json.dumps(request_list, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.dry_run:
        print({"status": "DRY_RUN", "request_count": len(request_list), "output_dir": str(args.output_dir)})
        return 0

    client_id = os.getenv("NAVER_API_HUB_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_API_HUB_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print({"status": "BLOCKED_MISSING_NAVER_API_HUB_CREDENTIALS", "request_count": len(request_list)})
        return 2
    rows, failures = collect(request_list, client_id, client_secret)
    result = pd.DataFrame(rows)
    result.to_csv(args.output_dir / "naver_facet_keyword_trends_preview.csv", index=False, encoding="utf-8-sig")
    if not result.empty:
        try:
            result.to_parquet(args.output_dir / "naver_facet_keyword_trends.parquet", index=False)
        except ImportError:
            pass
    (args.output_dir / "naver_shopping_insight_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print({"status": "COMPLETED" if not failures else "COMPLETED_WITH_FAILURES", "request_count": len(request_list), "result_rows": len(result), "failure_count": len(failures)})
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
