from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests import JSONDecodeError


BASE_URL = "https://ckdhcmall.co.kr"
PRODUCT_LIST_URL = f"{BASE_URL}/brandProductList.do?idx=43&pidx=1"
REVIEW_URL = f"{BASE_URL}/productReviewAjax.do"
PRODUCT_INDEX = "471"
USER_AGENT = "MoongCheapResearch/1.0 (internal HFF Model 1 pilot)"


def run_pilot(output: Path, limit: int = 100, delay_seconds: float = 1.0) -> dict[str, object]:
    if not 1 <= limit <= 100:
        raise ValueError("Chongkundang pilot limit must be between 1 and 100")
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9", "Referer": f"{BASE_URL}/prdView.do?prdCode=G2310110940_0456"})
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    stop_reason = "LIMIT_REACHED"
    page = 1
    while len(rows) < limit and page <= 20:
        response = session.post(REVIEW_URL, data={"idx": PRODUCT_INDEX, "ord": "reg", "pageUnit": 5, "pageIndex": page}, timeout=20)
        if response.status_code in (403, 429):
            stop_reason = f"STOP_HTTP_{response.status_code}"
            break
        response.raise_for_status()
        if re_challenge(response.text):
            stop_reason = "STOP_CHALLENGE"
            break
        try:
            payload = response.json()
        except JSONDecodeError:
            stop_reason = "STOP_NON_JSON_RESPONSE"
            break
        items = payload.get("list", []) if isinstance(payload, dict) else []
        if not items:
            stop_reason = "NO_PUBLIC_REVIEW"
            break
        for item in items:
            review_id = str(item.get("idx") or item.get("reviewIdx") or item.get("seq") or f"{PRODUCT_INDEX}:{page}:{len(rows)}")
            if review_id in seen:
                continue
            rows.append({
                "source_id": "chongkundang",
                "source_review_id": review_id,
                "source_product_id": PRODUCT_INDEX,
                "product_name": str(item.get("data3") or ""),
                "review_title": "",
                "review_text": str(item.get("contents") or "").strip(),
                "rating": int(float(item.get("data1"))) if str(item.get("data1", "")).replace(".", "", 1).isdigit() else None,
                "review_date": str(item.get("data") or ""),
                "verified_purchase": None,
                "verification_basis": None,
                "source_url": f"{BASE_URL}/prdView.do?prdCode=G2310110940_0456#review",
                "retrieved_at": retrieved_at,
            })
            seen.add(review_id)
            if len(rows) >= limit:
                break
        page += 1
        time.sleep(delay_seconds)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "status": "COMPLETED" if rows else "FAILED",
        "source": "chongkundang",
        "rows": len(rows),
        "usable_review_text_rows": sum(bool(row["review_text"]) for row in rows),
        "rating_rows": sum(row["rating"] is not None for row in rows),
        "product_mapping_rate": 1.0 if rows else 0.0,
        "stop_reason": stop_reason,
        "output": str(output),
    }


def re_challenge(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("captcha challenge", "cloudflare challenge", "access denied"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/raw/reviews/chongkundang/chongkundang_reviews_100_20260909.jsonl"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    print(json.dumps(run_pilot(args.output, args.limit, args.delay), ensure_ascii=False))
