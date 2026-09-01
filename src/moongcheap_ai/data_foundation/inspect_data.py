from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

SUPPORTED = {".zip", ".json", ".jsonl", ".csv", ".xlsx", ".parquet"}


def inventory(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        entry: dict[str, Any] = {"path": str(path.relative_to(root)), "suffix": path.suffix.lower(), "bytes": path.stat().st_size}
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                entry["archive_files"] = archive.namelist()[:100]
                entry["archive_file_count"] = len(archive.namelist())
        rows.append(entry)
    return rows


def read_sample(path: Path, nrows: int = 20) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv": return pd.read_csv(path, nrows=nrows)
    if suffix == ".xlsx": return pd.read_excel(path, nrows=nrows)
    if suffix == ".parquet": return pd.read_parquet(path).head(nrows)
    if suffix == ".jsonl": return pd.DataFrame([json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines()[:nrows]])
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return pd.DataFrame(value if isinstance(value, list) else value.get("data", value.get("rows", [])))
    return pd.DataFrame()


def inspect(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files = inventory(root); samples = []
    for entry in files:
        if entry["suffix"] == ".zip": continue
        try:
            sample = read_sample(root / entry["path"])
            entry.update({"columns": [str(c) for c in sample.columns], "sample_rows": len(sample), "null_rate": sample.isna().mean().round(4).to_dict()})
            samples.append({"path": entry["path"], "columns": entry["columns"], "rows": sample.to_dict("records")})
        except Exception as exc:
            entry["read_error"] = str(exc)
    return files, samples
