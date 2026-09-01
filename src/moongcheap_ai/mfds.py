from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests


class MFDSCollectionError(RuntimeError):
    pass


def _rows(payload: dict[str, Any], service: str) -> list[dict[str, Any]]:
    body = payload.get(service, payload)
    values = body.get("row", []) if isinstance(body, dict) else []
    if isinstance(values, dict): values = [values]
    return values if isinstance(values, list) else []


def collect(service: str, api_key: str | None, output_dir: Path, max_pages: int | None = None,
            rows_per_page: int = 100, session: requests.Session | None = None) -> dict[str, Any]:
    if not api_key: raise MFDSCollectionError("MFDS_API_KEY is required")
    output_dir.mkdir(parents=True, exist_ok=True); session = session or requests.Session()
    page = 1; total = 0; skipped = 0
    while max_pages is None or page <= max_pages:
        path = output_dir / f"page_{page:03d}.json"
        if path.exists():
            try: payload = json.loads(path.read_text(encoding="utf-8")); page_rows = _rows(payload, service); skipped += 1
            except (OSError, json.JSONDecodeError): page_rows = []
        else:
            start = (page - 1) * rows_per_page + 1
            url = f"https://openapi.foodsafetykorea.go.kr/api/{api_key}/{service}/json/{start}/{start + rows_per_page - 1}"
            for attempt in range(3):
                try:
                    response = session.get(url, timeout=30)
                except requests.RequestException as exc:
                    raise MFDSCollectionError(f"MFDS {service} request failed: {exc}") from exc
                if response.status_code in {401, 403}: raise MFDSCollectionError(f"MFDS authentication failed: HTTP {response.status_code}")
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 2: response.raise_for_status()
                    time.sleep(2 ** attempt); continue
                response.raise_for_status(); payload = response.json(); break
            status = payload.get(service, {}).get("RESULT", {}).get("CODE") if isinstance(payload.get(service), dict) else None
            if status and status not in {"INFO-000", "INFO-200"}:
                raise MFDSCollectionError(f"MFDS {service} returned {status}")
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            page_rows = _rows(payload, service)
        total += len(page_rows); page += 1
        if len(page_rows) < rows_per_page: break
    return {"service": service, "pages": page - 1, "rows": total, "skipped_existing_pages": skipped}
