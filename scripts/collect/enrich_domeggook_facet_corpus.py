"""Enrich public Domeggook listing rows with product-page evidence."""

from __future__ import annotations

import argparse
import html
import re
import time
from pathlib import Path

import pandas as pd
import requests


def text_only(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<script.*?</script>|<style.*?</style>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def meta(text: str, property_name: str) -> str:
    match = re.search(
        rf'<meta[^>]+property="{re.escape(property_name)}"[^>]+content="([^"]*)"',
        text,
        flags=re.I,
    )
    return html.unescape(match.group(1)).strip() if match else ""


def enrich(row: pd.Series, session: requests.Session, raw_dir: Path) -> dict[str, str]:
    item_id = str(row["source_product_id"])
    cached = raw_dir / f"{item_id}.html"
    if cached.exists():
        raw = cached.read_text(encoding="utf-8")
    else:
        response = session.get(f"https://domeggook.com/{item_id}", timeout=30)
        response.raise_for_status()
        raw = response.content.decode("euc-kr", errors="replace")
        cached.write_text(raw, encoding="utf-8")
    detail_match = re.search(
        r'<textarea[^>]+id="contentsBuffer"[^>]*>(.*?)</textarea>',
        raw,
        flags=re.S | re.I,
    )
    detail_html = html.unescape(detail_match.group(1)) if detail_match else ""
    result = row.to_dict()
    result.update(
        {
            "detail_title": meta(raw, "og:title"),
            "detail_image_url": meta(raw, "og:image"),
            "detail_description": meta(raw, "og:description"),
            "detail_text": text_only(detail_html)[:20000],
            "detail_source_url": f"https://domeggook.com/{item_id}",
            "detail_fetch_status": "OK",
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/external/domeggook_qa_20260924/domeggook_qa_products_v1.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/interim/facet_discovery/domeggook_multisource_v1/domeggook_facet_corpus_v1.csv"),
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    args = parser.parse_args()
    frame = pd.read_csv(args.input, dtype=str).fillna("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output.parent / "raw_detail_pages"
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    rows: list[dict[str, str]] = []
    for index, (_, row) in enumerate(frame.iterrows(), start=1):
        try:
            rows.append(enrich(row, session, raw_dir))
            print({"index": index, "item_id": row["source_product_id"], "status": "OK"})
        except requests.RequestException as exc:
            result = row.to_dict()
            result.update(
                {
                    "detail_title": "",
                    "detail_image_url": "",
                    "detail_description": "",
                    "detail_text": "",
                    "detail_source_url": f"https://domeggook.com/{row['source_product_id']}",
                    "detail_fetch_status": f"ERROR:{type(exc).__name__}",
                }
            )
            rows.append(result)
            print({"index": index, "item_id": row["source_product_id"], "status": "ERROR"})
        time.sleep(args.sleep_seconds)
    pd.DataFrame(rows).to_csv(args.output, index=False, encoding="utf-8-sig")
    print({"rows": len(rows), "output": str(args.output)})


if __name__ == "__main__":
    main()
