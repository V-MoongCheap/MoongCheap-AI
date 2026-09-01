from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


STOPWORDS = {"건강기능식품", "제품", "기능성", "섭취", "도움을 줄 수 있음", "기준", "규격", "제조"}


def extract_mfds_rows(raw_dir: Path, service: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("page_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = payload.get(service, payload)
        values = body.get("row", []) if isinstance(body, dict) else []
        if isinstance(values, dict):
            values = [values]
        rows.extend(values if isinstance(values, list) else [])
    return rows


def _pick(row: dict[str, Any], *names: str) -> str:
    normalized = {str(k).lower().replace("_", ""): v for k, v in row.items()}
    for name in names:
        value = normalized.get(name.lower().replace("_", ""))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def preprocess_i0030(raw_dir: Path, output_csv: Path) -> dict[str, int]:
    rows = extract_mfds_rows(raw_dir, "I0030")
    output = []
    for row in rows:
        output.append({
            "source_product_id": _pick(row, "PRDLST_REPORT_NO", "prdlstReportNo", "제품신고번호"),
            "name": _pick(row, "PRDLST_NM", "prdlstNm", "제품명"),
            "product_type": _pick(row, "PRDLST_CDNM", "PRDLST_TYPE", "제품유형"),
            "product_form": _pick(row, "PRDT_SHAP_CD_NM", "PRDT_SHAP", "제품형태"),
            "main_functionality": _pick(row, "PRIMARY_FNCLTY", "주된기능성"),
            "intake_method": _pick(row, "NTK_MTHD", "섭취방법"),
            "caution": _pick(row, "IFTKN_ATNT_MATR_CN", "IFTKN_ATNT_MATTER", "섭취시주의사항"),
            "storage_method": _pick(row, "CSTDY_MTHD", "보관방법"),
            "standard_spec": _pick(row, "STDR_STND", "기준규격"),
            "functional_ingredients": _pick(row, "RAWMTRL_NM", "기능성원재료"),
            "other_ingredients": _pick(row, "ETC_RAWMTRL_NM", "기타원재료"),
            "capsule_ingredients": _pick(row, "CAPSULE_RAWMTRL_NM", "캡슐원재료"),
            "manufacturer": _pick(row, "BSSH_NM", "제조업체"),
            "raw_category_name": _pick(row, "PRDLST_CDNM", "PRDLST_TYPE", "제품유형"),
        })
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(output).to_csv(output_csv, index=False, encoding="utf-8-sig")
    return {"raw_rows": len(rows), "processed_rows": len(output)}


def validate_i0030(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Deduplicate by MFDS report number and retain data-quality review rows."""
    if frame.empty:
        return frame.copy(), frame.copy(), {}
    work = frame.copy().fillna("")
    work = work.loc[work["source_product_id"].astype(str).str.strip() != ""].copy()
    duplicate_mask = work.duplicated("source_product_id", keep="first")
    duplicates = work.loc[duplicate_mask].copy()
    clean = work.loc[~duplicate_mask].copy()
    missing_counts = {
        column: int((clean[column].astype(str).str.strip() == "").sum())
        for column in clean.columns
    }
    stats = {
        "input_rows": len(frame),
        "rows_without_product_id": len(frame) - len(work),
        "duplicate_rows_removed": len(duplicates),
        "clean_rows": len(clean),
    }
    return clean, duplicates, {**stats, **{f"missing_{k}": v for k, v in missing_counts.items()}}


def preprocess_i2710(raw_dir: Path, output_csv: Path) -> dict[str, int]:
    """Keep the MFDS reference data flexible because the public schema may vary."""
    rows = extract_mfds_rows(raw_dir, "I2710")
    output = []
    for row in rows:
        output.append({
            "category_reference_name": _pick(row, "PRDLST_NM", "prdlstNm", "제품명", "categoryName", "분류명"),
            "main_functionality": _pick(row, "PRIMARY_FNCLTY", "주된기능성", "functionality"),
            "daily_intake_min": _pick(row, "MIN_INTAKE", "일일섭취최소량", "min"),
            "daily_intake_max": _pick(row, "MAX_INTAKE", "일일섭취최대량", "max"),
            "unit": _pick(row, "UNIT", "단위"),
            "ingredient_name": _pick(row, "RAWMTRL_NM", "원료명", "ingredient"),
            "caution": _pick(row, "IFTKN_ATNT_MATTER", "주의사항", "caution"),
        })
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(output).to_csv(output_csv, index=False, encoding="utf-8-sig")
    return {"raw_rows": len(rows), "processed_rows": len(output)}


def repeated_terms(df: pd.DataFrame, text_columns: list[str], min_documents: int = 3,
                   min_ratio: float = 0.05) -> pd.DataFrame:
    total = len(df)
    documents: defaultdict[str, set[int]] = defaultdict(set)
    fields: defaultdict[str, set[str]] = defaultdict(set)
    for idx, row in df.iterrows():
        seen: set[str] = set()
        for field in text_columns:
            for term in re.findall(r"[가-힣A-Za-z0-9]{2,}", str(row.get(field, "") or "")):
                if term.lower() not in STOPWORDS:
                    seen.add(term.lower())
                    fields[term.lower()].add(field)
        for term in seen:
            documents[term].add(int(idx))
    result = [{"term": term, "count": len(ids), "document_count": len(ids),
               "document_ratio": len(ids) / total if total else 0,
               "source_fields": "|".join(sorted(fields[term]))}
              for term, ids in documents.items() if len(ids) >= min_documents and (len(ids) / total if total else 0) >= min_ratio]
    return pd.DataFrame(result).sort_values(["document_count", "term"], ascending=[False, True]) if result else pd.DataFrame(columns=["term", "count", "document_count", "document_ratio", "source_fields"])


def structured_distribution(df: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    rows = []
    category_col = "raw_category_name" if "raw_category_name" in df.columns else None
    for field in fields:
        if field not in df.columns:
            continue
        values = df[field].fillna("").astype(str).str.strip()
        for value, count in values[values != ""].value_counts().items():
            rows.append({"category": "", "source_field": field, "normalized_value": value,
                         "count": int(count), "document_ratio": float(count / len(df)) if len(df) else 0})
    return pd.DataFrame(rows)


def taxonomy_v0(category_id: str | int, category_name: str, terms: pd.DataFrame,
                aliases: dict[str, list[str]] | None = None) -> dict[str, Any]:
    aliases = aliases or {}
    facets = []
    candidates = terms.head(3).to_dict("records") if not terms.empty else []
    for order, candidate in enumerate(candidates, 1):
        value = str(candidate["term"])
        facets.append({"facet_id": order, "name": f"candidate_{order}", "order": order,
                       "values": [{"code": 0, "value": "ALL", "aliases": []},
                                  {"code": 1, "value": value, "aliases": aliases.get(value, [])}]})
    return {"category_id": category_id, "category_name": category_name, "facets": facets,
            "status": "DRAFT_PENDING_HUMAN_REVIEW"}
