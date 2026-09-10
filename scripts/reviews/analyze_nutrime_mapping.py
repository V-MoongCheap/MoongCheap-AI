from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests


BASE_URL = "https://www.nutrime.co.kr"
HFF_MARKERS = re.compile(r"건강기능식품|식약처|기능성 원료|영양제", re.I)


def load_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def analyze(input_path: Path, output_dir: Path, fetch_product_pages: bool = True) -> dict[str, object]:
    rows = load_jsonl(input_path)
    session = requests.Session()
    session.headers.update({"User-Agent": "MoongCheapResearch/1.0 (internal HFF Model 1 pilot)", "Accept-Language": "ko-KR,ko;q=0.9"})
    product_cache: dict[str, str] = {}
    mapping_rows = []
    failures = []
    for item in rows:
        review_id = str(item.get("source_review_id") or "")
        product_id = str(item.get("source_product_id") or "")
        product_name = str(item.get("product_name") or "")
        if not product_id:
            failures.append({
                "source_review_id": review_id,
                "source_product_id": "",
                "review_product_name": product_name,
                "source_product_url": "",
                "failure_type": "PRODUCT_ID_NOT_FOUND",
                "failure_reason": "공개 Review 상세 HTML에 상품 ID와 상품 정보 블록이 없음",
                "recoverable": False,
                "resolved_product_id": "",
                "resolved_product_name": "",
                "final_status": "UNRESOLVED",
            })
            continue
        url = f"{BASE_URL}/goods/view?no={product_id}"
        page_status = product_cache.get(product_id, "")
        if fetch_product_pages and not page_status:
            try:
                response = session.get(url, timeout=20)
                if response.status_code in (403, 429):
                    page_status = "PRODUCT_PAGE_UNAVAILABLE"
                elif response.status_code != 200:
                    page_status = "PRODUCT_PAGE_UNAVAILABLE"
                elif HFF_MARKERS.search(response.text):
                    page_status = "HEALTH_FUNCTIONAL_FOOD"
                else:
                    page_status = "UNKNOWN_PRODUCT_TYPE"
            except requests.RequestException:
                page_status = "PRODUCT_PAGE_UNAVAILABLE"
            product_cache[product_id] = page_status
            time.sleep(0.5)
        mapping_rows.append({
            "source_review_id": review_id,
            "source_product_id": product_id,
            "source_product_url": url,
            "mapping_method": "REVIEW_PRODUCT_ID_EXACT",
            "mapping_confidence": "EXACT",
            "resolved_product_name": product_name,
            "product_type": page_status or "UNKNOWN_PRODUCT_TYPE",
            "hff_status": "HFF_CONFIRMED" if page_status == "HEALTH_FUNCTIONAL_FOOD" else page_status or "UNKNOWN_PRODUCT_TYPE",
        })
    output_dir.mkdir(parents=True, exist_ok=True)
    failure_frame = pd.DataFrame(failures, columns=["source_review_id", "source_product_id", "review_product_name", "source_product_url", "failure_type", "failure_reason", "recoverable", "resolved_product_id", "resolved_product_name", "final_status"])
    failure_frame.to_csv(output_dir / "nutrime_mapping_failure_queue.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(mapping_rows).to_csv(output_dir / "nutrime_product_mapping_100.csv", index=False, encoding="utf-8-sig")
    hff_count = sum(row["hff_status"] == "HFF_CONFIRMED" for row in mapping_rows)
    report = {
        "input": str(input_path),
        "total_reviews": len(rows),
        "mapped_reviews": len(mapping_rows),
        "mapping_rate": len(mapping_rows) / len(rows) if rows else 0.0,
        "exact_mapping_count": len(mapping_rows),
        "url_mapping_count": 0,
        "normalized_name_mapping_count": 0,
        "unresolved_count": len(failures),
        "hff_confirmed_count": hff_count,
        "non_hff_count": sum(row["hff_status"] == "GENERAL_FOOD" for row in mapping_rows),
        "unknown_product_type_count": sum(row["hff_status"] == "UNKNOWN_PRODUCT_TYPE" for row in mapping_rows),
        "failure_types": failure_frame["failure_type"].value_counts().to_dict() if not failure_frame.empty else {},
    }
    (output_dir / "nutrime_mapping_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/raw/reviews/nutrime/nutrime_review_pilot_100.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/reviews/nutrime"))
    args = parser.parse_args()
    print(json.dumps(analyze(args.input, args.output_dir), ensure_ascii=False))
