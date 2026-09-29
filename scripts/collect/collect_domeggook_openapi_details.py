"""Collect Domeggook product details for known item numbers via the public detail API.

This script intentionally does not use the private product-sync endpoint.  The
detail endpoint can enrich known item numbers with structured product evidence
without requiring the product-sync permission.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv


DETAIL_ENDPOINT = "https://www.domeggook.com/ssl/api/"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key, "")
    return current


def _category_path(item: dict[str, Any]) -> str:
    parents = _nested(item, "category", "parents")
    names = [
        _text(parent.get("name"))
        for parent in parents or []
        if isinstance(parent, dict) and _text(parent.get("name"))
    ]
    current = _nested(item, "category", "current", "name")
    if _text(current):
        names.append(_text(current))
    return " > ".join(dict.fromkeys(names))


def _flatten(item: dict[str, Any], source_row: dict[str, Any]) -> dict[str, Any]:
    contents = _nested(item, "desc", "contents")
    info_duty = _nested(item, "detail", "infoDuty", "item")
    return {
        "source": "DOMEGGOOK_OPEN_API_DETAIL",
        "source_product_id": _text(item.get("no")) or _text(source_row.get("source_product_id")),
        "name": _text(item.get("title")) or _text(source_row.get("name")),
        "status": _text(item.get("status")),
        "category_path": _category_path(item),
        "category_code": _text(_nested(item, "category", "current", "code")),
        "keywords": _text(_nested(item, "keywords", "kw")),
        "description_item": _text(contents.get("item") if isinstance(contents, dict) else ""),
        "description_comment": _text(contents.get("comment") if isinstance(contents, dict) else ""),
        "description_delivery": _text(contents.get("deli") if isinstance(contents, dict) else ""),
        "detail_size": _text(_nested(item, "detail", "size")),
        "detail_weight": _text(_nested(item, "detail", "weight")),
        "manufacturer": _text(_nested(item, "detail", "manufacturer")),
        "model": _text(_nested(item, "detail", "model")),
        "info_duty": _text(info_duty),
        "dome_price": _text(_nested(item, "price", "dome")),
        "dome_moq": _text(_nested(item, "qty", "domeMoq")),
        "dome_unit": _text(_nested(item, "qty", "domeUnit")),
        "inventory": _text(_nested(item, "qty", "inventory")),
        "thumbnail_url": _text(_nested(item, "thumb", "original"))
        or _text(_nested(item, "thumb", "large")),
        "source_url": f"https://www.domeggook.com/{_text(item.get('no'))}",
        "detail_api_status": "OK",
    }


def collect(input_path: Path, output_dir: Path, sleep_seconds: float) -> dict[str, int]:
    load_dotenv(".env")
    api_key = os.getenv("DOMEGGOOK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DOMEGGOOK_API_KEY is required in .env")

    source = pd.read_csv(input_path, dtype=str).fillna("")
    if "source_product_id" not in source.columns:
        raise ValueError("input must contain source_product_id")

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw_json"
    raw_dir.mkdir(exist_ok=True)
    session = requests.Session()
    rows: list[dict[str, Any]] = []
    ok = 0
    failed = 0

    for source_row in source.to_dict(orient="records"):
        item_id = str(source_row["source_product_id"]).strip()
        raw_path = raw_dir / f"{item_id}.json"
        try:
            response = session.get(
                DETAIL_ENDPOINT,
                params={
                    "ver": "4.6",
                    "mode": "getItemView",
                    "aid": api_key,
                    "market": "dome",
                    "om": "json",
                    "no": item_id,
                },
                timeout=30,
            )
            payload = response.json()
            raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            item = _nested(payload, "domeggook")
            if response.status_code != 200 or not isinstance(item, dict) or not item.get("basis"):
                failed += 1
                rows.append({**source_row, "source_product_id": item_id, "detail_api_status": "ERROR"})
            else:
                rows.append(_flatten(item, source_row))
                ok += 1
        except (OSError, requests.RequestException, ValueError) as exc:
            failed += 1
            rows.append({
                **source_row,
                "source_product_id": item_id,
                "detail_api_status": f"ERROR:{type(exc).__name__}",
            })
        time.sleep(max(0.0, sleep_seconds))

    pd.DataFrame(rows).to_csv(output_dir / "domeggook_openapi_detail_products_v1.csv", index=False, encoding="utf-8-sig")
    summary = {"input_rows": len(source), "api_ok": ok, "api_failed": failed}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/external/domeggook_qa_20260924/domeggook_qa_products_v1.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/external/domeggook_openapi_20260924"),
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    args = parser.parse_args()
    print(json.dumps(collect(args.input, args.output_dir, args.sleep_seconds), ensure_ascii=False))


if __name__ == "__main__":
    main()
