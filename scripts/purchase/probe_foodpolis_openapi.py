"""Probe a documented Foodpolis retail-sales Open API without exposing credentials."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


OPEN_API_LIST_URL = "https://www.foodpolis.kr/food24/fo/io/api/apiData/list.do"
SERVICE_GUIDE_URL = "https://www.foodpolis.kr/food24/fo/cvd/main/fdGuide.do"
RETAIL_DATA_GUIDE_URL = "https://www.foodpolis.kr/dfip/fo/cvd/main/fdGuide.do"
DEFAULT_KEY_PARAM = "opapiAtkeyCn"


def _schema(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return {"top_level_type": "object", "row_container": key, "columns": list(value[0].keys()), "row_count": len(value)}
        return {"top_level_type": "object", "keys": list(payload.keys())}
    if isinstance(payload, list):
        return {"top_level_type": "array", "columns": list(payload[0].keys()) if payload and isinstance(payload[0], dict) else [], "row_count": len(payload)}
    return {"top_level_type": type(payload).__name__}


def probe(endpoint: str | None = None, output: Path = Path("reports/foodpolis_openapi_probe.md"), timeout: int = 20) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env"
    if not env_path.exists():
        env_path = repo_root.parent / ".env"
    load_dotenv(env_path if env_path.exists() else None)
    api_key = os.getenv("FOODPOLIS_API_KEY", "").strip()
    configured_endpoint = endpoint or os.getenv("FOODPOLIS_RETAIL_API_URL", "").strip()
    key_param = os.getenv("FOODPOLIS_API_KEY_PARAM", DEFAULT_KEY_PARAM).strip() or DEFAULT_KEY_PARAM
    result: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "api_key_configured": bool(api_key),
        "endpoint_configured": bool(configured_endpoint),
        "endpoint": configured_endpoint or None,
        "status": "ENDPOINT_NOT_CONFIRMED",
        "http_status": None,
        "content_type": None,
        "schema": None,
        "row_count": None,
        "hff_rows": None,
        "error": None,
    }
    if not configured_endpoint:
        result["status"] = "FOODPOLIS_OPEN_API_ENDPOINT_NOT_FOUND"
    elif not api_key:
        result["status"] = "MISSING_FOODPOLIS_API_KEY"
    else:
        try:
            response = requests.get(configured_endpoint, params={key_param: api_key, "type": "json"}, timeout=timeout)
            result["http_status"] = response.status_code
            result["content_type"] = response.headers.get("Content-Type", "")
            if response.status_code in (401, 403):
                result["status"] = "API_AUTH_FAILED"
            elif response.status_code >= 400:
                result["status"] = "API_HTTP_ERROR"
            else:
                try:
                    payload = response.json()
                    result["schema"] = _schema(payload)
                    result["row_count"] = result["schema"].get("row_count")
                    result["hff_rows"] = "NOT_CLASSIFIED_IN_PROBE"
                    result["status"] = "TEST_CALL_COMPLETED"
                except ValueError:
                    result["status"] = "API_RESPONSE_NOT_JSON"
        except requests.RequestException as exc:
            result["status"] = "API_REQUEST_FAILED"
            result["error"] = type(exc).__name__

    lines = [
        "# Foodpolis 소매채널 판매정보 Open API Probe",
        "",
        f"확인 시각(UTC): {result['checked_at']}",
        "",
        "## 결론",
        f"- 상태: `{result['status']}`",
        f"- API Key 환경변수 설정 여부: `{result['api_key_configured']}` (값은 기록하지 않음)",
        f"- 공식 Retail Endpoint 설정 여부: `{result['endpoint_configured']}`",
        "- 현재 공식 문서에서 소매채널 판매정보의 공개 Endpoint 상세를 확인하지 못해 URL을 추측하거나 내부 Dashboard API를 호출하지 않았다." if not configured_endpoint else f"- Endpoint: `{configured_endpoint}`",
        "",
        "## 공식 문서 확인",
        f"- Open API 목록: {OPEN_API_LIST_URL}",
        f"- 서비스 소개: {SERVICE_GUIDE_URL}",
        f"- 소매채널 데이터 안내: {RETAIL_DATA_GUIDE_URL}",
        "- 소매채널 판매정보는 편의점·슈퍼마켓·하나로마트, 년월·지역·표준상품장 분류·제품명·판매건수·판매금액·판매단가로 설명되어 있다.",
        "",
        "## Test Call",
        f"- HTTP Status: `{result['http_status']}`",
        f"- Content-Type: `{result['content_type']}`",
        f"- Top-level Schema: `{json.dumps(result['schema'], ensure_ascii=False) if result['schema'] else 'NOT_AVAILABLE'}`",
        f"- Row Count: `{result['row_count']}`",
        "- HFF Row: API Endpoint가 확인된 경우에만 소량 응답에서 분류값을 검사한다.",
        "- API Key는 Report·로그·Raw 응답에 저장하지 않는다.",
        "",
        "## 상태값",
        "- `FOODPOLIS_DATA_EXISTS=true`: 공식 서비스 소개에서 소매채널 판매정보가 설명됨.",
        "- `FOODPOLIS_OPEN_API_AVAILABLE=false`: 현재 확인 가능한 공식 상세 Endpoint가 없음. Endpoint가 공식 문서에 확인되면 환경변수로 지정해 재실행한다.",
        "- Endpoint가 확인될 때까지 기존 수동 Export 상태를 유지한다.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", help="Only use an Endpoint copied from an official Foodpolis API detail page")
    parser.add_argument("--output", type=Path, default=Path("reports/foodpolis_openapi_probe.md"))
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(probe(args.endpoint, args.output, args.timeout), ensure_ascii=False))
