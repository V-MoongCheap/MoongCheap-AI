"""Collect a broader exploratory product corpus from public category pages.

The public listing supplies item numbers and basic listing fields.  Detail
fields are enriched separately through the official public item-detail API.
This is not a backend seed or QA fixture.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from html import unescape
from pathlib import Path

import requests


DEFAULT_CATEGORIES = (
    ("cosmetics_beauty", "화장품/미용", "07_06_08_00_00"),
    ("kitchen_living", "주방용품", "12_08_16_04_00"),
    ("sports_leisure", "스포츠/레저", "01_17_07_00_00"),
)
LIST_URL = "https://domeggook.com/main/item/itemList.php"


def strip_html(value: str) -> str:
    return unescape(re.sub(r"<.*?>", "", value)).strip()


def collect_category(
    session: requests.Session,
    key: str,
    category_name: str,
    category_code: str,
    max_rows: int,
    max_pages: int,
    sleep_seconds: float,
    output_dir: Path,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    item_pattern = re.compile(r'<li id="li(\d+)"[^>]*>(.*?)(?=<li id="li|</ul>)', re.S)
    output_dir.mkdir(parents=True, exist_ok=True)

    for page in range(1, max_pages + 1):
        response = session.get(
            LIST_URL,
            params={"ca": category_code, "pg": page, "so": "sd", "sw": ""},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()
        (output_dir / f"{key}_page_{page:03d}.html").write_bytes(response.content)
        text = response.content.decode("cp949", errors="replace")
        page_count = 0
        for match in item_pattern.finditer(text):
            item_id, block = match.groups()
            if item_id in seen:
                continue
            image = re.search(r'<img[^>]*src="([^"]+)', block, re.S)
            title = re.search(r'class="title">(.*?)</a>', block, re.S)
            price = re.search(r'class="amt"[^>]*>\s*<b>([0-9,]+)</b>', block, re.S)
            minimum = re.search(r'class="unitQty"[^>]*>.*?<b>([0-9,]+)</b>', block, re.S)
            if not image or not title or not price:
                continue
            image_url = image.group(1)
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            seen.add(item_id)
            rows.append(
                {
                    "source": "DOMEGGOOK_PUBLIC_CATEGORY",
                    "source_product_id": item_id,
                    "name": strip_html(title.group(1)),
                    "category_name": category_name,
                    "category_code": category_code,
                    "source_page": str(page),
                    "price": price.group(1).replace(",", ""),
                    "min_quantity": minimum.group(1).replace(",", "") if minimum else "",
                    "thumbnail_url": image_url,
                    "source_url": f"https://domeggook.com/{item_id}",
                }
            )
            page_count += 1
            if len(rows) >= max_rows:
                return rows
        print({"category": category_name, "page": page, "page_rows": page_count, "total": len(rows)})
        if page_count == 0:
            break
        time.sleep(max(0.0, sleep_seconds))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/external/domeggook_public_facet_20260924"))
    parser.add_argument("--rows-per-category", type=int, default=300)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--categories-json", type=Path)
    args = parser.parse_args()

    session = requests.Session()
    rows: list[dict[str, str]] = []
    if args.categories_json:
        category_data = json.loads(args.categories_json.read_text(encoding="utf-8"))
        categories = tuple((item["key"], item["name"], item["code"]) for item in category_data)
    else:
        categories = DEFAULT_CATEGORIES
    for key, name, code in categories:
        rows.extend(collect_category(session, key, name, code, args.rows_per_category, args.max_pages, args.sleep_seconds, args.output_dir))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "domeggook_public_facet_products_v1.csv"
    fields = list(rows[0]) if rows else ["source_product_id"]
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print({"total": len(rows), "output": str(output)})


if __name__ == "__main__":
    main()
