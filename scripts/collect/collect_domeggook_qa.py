"""Collect a small QA fixture from public Domeggook category listings."""

from __future__ import annotations

import csv
import re
from html import unescape
from pathlib import Path

import requests


CATEGORIES = (
    ("cosmetics_beauty", "화장품/미용", "07_06_08_00_00"),
    ("kitchen_living", "주방용품", "12_08_16_04_00"),
    ("sports_leisure", "스포츠/레저", "01_17_07_00_00"),
)
OUTPUT_DIR = Path("data/raw/external/domeggook_qa_20260924")
LIST_URL = "https://domeggook.com/main/item/itemList.php"


def strip_html(value: str) -> str:
    return unescape(re.sub(r"<.*?>", "", value)).strip()


def collect_category(key: str, category_name: str, category_code: str) -> list[dict[str, str]]:
    response = requests.get(
        LIST_URL,
        params={"ca": category_code, "pg": 1, "so": "sd", "sw": ""},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"{key}.html").write_bytes(response.content)
    text = response.content.decode("cp949", errors="replace")
    rows: list[dict[str, str]] = []
    item_pattern = re.compile(r'<li id="li(\d+)"[^>]*>(.*?)(?=<li id="li|</ul>)', re.S)
    for match in item_pattern.finditer(text):
        item_id, block = match.groups()
        image = re.search(r'<img[^>]*src="([^"]+)', block, re.S)
        title = re.search(r'class="title">(.*?)</a>', block, re.S)
        price = re.search(r'class="amt"[^>]*>\s*<b>([0-9,]+)</b>', block, re.S)
        minimum = re.search(r'class="unitQty"[^>]*>.*?<b>([0-9,]+)</b>', block, re.S)
        if not image or not title or not price:
            continue
        image_url = image.group(1)
        if image_url.startswith("//"):
            image_url = "https:" + image_url
        rows.append(
            {
                "source": "DOMEGGOOK_PUBLIC",
                "source_product_id": item_id,
                "name": strip_html(title.group(1)),
                "category_name": category_name,
                "category_code": category_code,
                "price": price.group(1).replace(",", ""),
                "min_quantity": minimum.group(1).replace(",", "") if minimum else "",
                "thumbnail_url": image_url,
                "source_url": f"https://domeggook.com/{item_id}",
            }
        )
        if len(rows) >= 50:
            break
    return rows


def main() -> None:
    rows: list[dict[str, str]] = []
    for key, name, code in CATEGORIES:
        category_rows = collect_category(key, name, code)
        rows.extend(category_rows)
        print({"category": name, "rows": len(category_rows)})
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "domeggook_qa_products_v1.csv"
    fieldnames = list(rows[0]) if rows else ["source_product_id"]
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print({"total": len(rows), "output": str(output)})


if __name__ == "__main__":
    main()
