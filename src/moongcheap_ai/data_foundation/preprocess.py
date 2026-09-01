from __future__ import annotations

import html
import re
import unicodedata
from typing import Any


def clean_title(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def category_path(item: dict[str, Any]) -> str:
    return " > ".join(clean_title(item.get(f"category{i}")) for i in range(1, 5) if clean_title(item.get(f"category{i}")))
