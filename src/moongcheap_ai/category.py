from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def build_observed_kan(staging: pd.DataFrame, output: Path) -> dict[str, int]:
    rows = []
    if not staging.empty:
        for code, group in staging.groupby("kan_code", dropna=False, sort=True):
            code = str(code or "")
            if not code: continue
            name = next((str(x) for x in group.get("source_category_name", []) if str(x)), "")
            rows.append({"category_seed_id": f"kan-{code}", "category_key": f"KAN:{code}", "kan_code": code, "name": name or code, "parent_category_key": "", "depth": 1, "category_path": name or code, "source": "AI_HUB_OBSERVED", "source_category_name": name, "observed_only": True, "status": "DRAFT"})
    output.parent.mkdir(parents=True, exist_ok=True); pd.DataFrame(rows).to_csv(output, index=False, encoding="utf-8-sig")
    return {"observed_kan_codes": len(rows)}


def category_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()
