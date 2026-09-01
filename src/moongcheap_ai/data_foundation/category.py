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


def build_aihub_category_hierarchy(staging: pd.DataFrame, output: Path) -> dict[str, int]:
    """Create an observed hierarchy from preserved AI-Hub source paths."""
    nodes: dict[str, dict] = {}
    if not staging.empty and "source_category_path" in staging:
        grouped = staging.groupby("source_category_path", dropna=False, sort=True)
        for raw_path, group in grouped:
            path = str(raw_path or "").strip()
            if not path:
                continue
            parts = [part.strip() for part in path.split(" > ") if part.strip()]
            for depth, name in enumerate(parts, 1):
                category_path = " > ".join(parts[:depth])
                parent_path = " > ".join(parts[: depth - 1])
                node = nodes.setdefault(category_path, {
                    "category_key": f"AIHUB:{category_path}",
                    "parent_category_key": f"AIHUB:{parent_path}" if parent_path else "",
                    "name": name,
                    "depth": depth,
                    "category_path": category_path,
                    "source": "AI_HUB_OBSERVED",
                    "observed_row_count": 0,
                    "observed_kan_codes": set(),
                    "observed_only": True,
                    "status": "DRAFT",
                })
                node["observed_row_count"] += int(len(group))
                node["observed_kan_codes"].update(set(group["kan_code"].astype(str).loc[lambda values: values.ne("")]))
    rows = []
    for node in nodes.values():
        node["observed_kan_codes"] = "|".join(sorted(node["observed_kan_codes"]))
        rows.append(node)
    result = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["category_key", "parent_category_key", "name", "depth", "category_path", "source", "observed_row_count", "observed_kan_codes", "observed_only", "status"])
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    return {"category_count": len(result), "source": "AI_HUB_OBSERVED"}


def category_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()
