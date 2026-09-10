"""Inspect and normalize authorized local purchase/sales aggregate exports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


ALIASES = {
    "period": ("년월", "period", "date"),
    "category_detail": ("상품 분류", "category_detail", "category"),
    "product_name": ("제품명", "product_name", "상품명"),
    "sales_count": ("판매건수", "sales_count"),
    "sales_amount": ("판매금액", "sales_amount", "구매금액"),
    "unit_price": ("판매단가", "unit_price"),
}


def normalize_aggregate(frame: pd.DataFrame, source_type: str) -> pd.DataFrame:
    """Keep the legacy manual-export adapter contract for non-LG U+ files."""
    frame = frame.fillna("")
    result = pd.DataFrame(index=frame.index)
    for target, names in ALIASES.items():
        matched = next((name for name in names if name in frame.columns), None)
        result[target] = frame[matched] if matched else ""
    result["source_type"] = source_type
    result["market_metric_type"] = result.apply(lambda row: "sales_count" if str(row.sales_count).strip() else "sales_amount" if str(row.sales_amount).strip() else "unknown", axis=1)
    return result


LGU_COLUMNS = {
    "period": "CRTR_YM",
    "region_sido": "CTPV_NM",
    "region_sigungu": "SGG_NM",
    "region_dong": "DONG_NM",
    "online_order_count": "HMDLV_NOCS",
    "offline_mart_purchase_amount": "OFLNE_SLS_AMT",
    "specialty_store_purchase_amount": "SHOP_SLS_AMT",
}


def _find_file(input_dir: Path) -> Path | None:
    files = [path for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() in {".csv", ".xlsx", ".xls"}] if input_dir.exists() else []
    return sorted(files)[0] if files else None


def _read_csv(path: Path) -> tuple[pd.DataFrame, str, str]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            raw = path.read_bytes()[:200_000]
            delimiter = "," if raw.count(b",") >= raw.count(b";") else ";"
            return pd.read_csv(path, encoding=encoding, dtype=str, sep=delimiter).fillna(""), encoding, delimiter
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_error = exc
    raise ValueError(f"unable to decode CSV: {path}") from last_error


def read_source(path: Path) -> tuple[pd.DataFrame, str, str]:
    if path.suffix.lower() == ".csv":
        return _read_csv(path)
    return pd.read_excel(path, dtype=str).fillna(""), "excel", ""


def _numeric(series: pd.Series) -> tuple[pd.Series, int]:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.replace("원", "", regex=False).str.strip()
    values = pd.to_numeric(cleaned, errors="coerce")
    return values, int(values.notna().sum())


def normalize_lgu(frame: pd.DataFrame, snapshot_id: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = [*LGU_COLUMNS.values(), "INDEX_KEY"]
    missing_columns = [column for column in required if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"required LG U+ columns missing: {', '.join(missing_columns)}")
    base = pd.DataFrame({name: frame[column].astype(str) for name, column in LGU_COLUMNS.items()})
    base["source_category"] = ""
    base["service_category"] = ""
    base["product_name"] = ""
    base["product_level_mapping"] = "NOT_APPLICABLE"
    base["source_type"] = "KOREAN_HFF_PURCHASE_AGGREGATE"
    base["snapshot_id"] = snapshot_id
    base["source_record_id"] = frame["INDEX_KEY"].astype(str)
    rows = []
    numeric_stats = {}
    metric_columns = {
        "ONLINE_ORDER_COUNT": "online_order_count",
        "OFFLINE_PURCHASE_AMOUNT": "offline_mart_purchase_amount",
        "SPECIALTY_STORE_PURCHASE_AMOUNT": "specialty_store_purchase_amount",
    }
    for metric_type, column in metric_columns.items():
        numeric, parsed = _numeric(base[column])
        numeric_stats[column] = {"numeric_parse_success": parsed, "negative_value_count": int((numeric < 0).sum()), "missing_count": int(numeric.isna().sum())}
        metric = base[["source_record_id", "snapshot_id", "source_type", "period", "region_sido", "region_sigungu", "region_dong", "source_category", "service_category", "product_name", "product_level_mapping"]].copy()
        metric["market_metric_type"] = metric_type
        metric["market_metric_raw"] = base[column]
        metric["market_metric_value"] = numeric
        rows.append(metric)
    normalized = pd.concat(rows, ignore_index=True)
    audit = {
        "total_rows": int(len(frame)), "column_count": int(len(frame.columns)), "columns": list(frame.columns),
        "missing_ratio": {column: float(frame[column].eq("").mean()) for column in frame.columns},
        "unique_count": {column: int(frame[column].nunique(dropna=False)) for column in frame.columns},
        "sample_values": {column: frame[column].head(3).tolist() for column in frame.columns},
        "duplicate_rows": int(frame.duplicated().sum()), "period_distribution": frame["CRTR_YM"].value_counts(dropna=False).astype(int).to_dict(),
        "region_distribution": {"sido": int(frame["CTPV_NM"].nunique()), "sigungu": int(frame["SGG_NM"].nunique()), "dong": int(frame["DONG_NM"].nunique())},
        "category_distribution": "NOT_AVAILABLE_SOURCE_HAS_NO_CATEGORY_COLUMN", "gender_distribution": "NOT_AVAILABLE_SOURCE_HAS_NO_GENDER_COLUMN", "age_distribution": "NOT_AVAILABLE_SOURCE_HAS_NO_AGE_COLUMN", "product_name": "NOT_AVAILABLE_SOURCE_HAS_NO_PRODUCT_COLUMN", "numeric_stats": numeric_stats, "product_level_mapping": "NOT_APPLICABLE", "source_type": "KOREAN_HFF_PURCHASE_AGGREGATE",
    }
    return normalized, audit


def write_report(path: Path, source_path: Path, audit: dict[str, Any], encoding: str, delimiter: str, sha256: str) -> None:
    lines = ["# LG U+ 건강기능식품 융합데이터 분석", "", "## Raw Snapshot", f"- filename: `{source_path.name}`", f"- file_size_bytes: {source_path.stat().st_size}", f"- sha256: `{sha256}`", f"- encoding: `{encoding}`", f"- delimiter: `{delimiter or 'excel'}`", f"- row_count: {audit['total_rows']}", f"- column_count: {audit['column_count']}", "- source_type: `KOREAN_HFF_PURCHASE_AGGREGATE`", "", "## 실제 Schema", "| column | missing ratio | unique count | sample values |", "|---|---:|---:|---|"]
    for column in audit["columns"]:
        samples = " / ".join(str(value) for value in audit["sample_values"][column])
        lines.append(f"| {column} | {audit['missing_ratio'][column]:.2%} | {audit['unique_count'][column]} | {samples[:120]} |")
    lines += ["", "## 의미 해석", "- `CRTR_YM`: 기준년월", "- `CTPV_NM`, `SGG_NM`, `DONG_NM`: 지역", "- `HMDLV_NOCS`: 온라인/택배 지표로 사용", "- `OFLNE_SLS_AMT`: 오프라인 판매금액 지표", "- `SHOP_SLS_AMT`: 전문매장/쇼핑 판매금액 지표", "- 유동·생활인구 지표는 구매금액·주문건수와 구분해 원본 분석 정보로만 보존", "- 제품명·상품분류·성별·연령대가 없어 Product/MFDS Mapping과 Category Mapping은 `NOT_APPLICABLE`", "", "## Quality", f"- duplicate_rows: {audit['duplicate_rows']}", f"- period_distribution: `{audit['period_distribution']}`", f"- region_distribution: `{audit['region_distribution']}`", f"- numeric_stats: `{audit['numeric_stats']}`", "", "## Model 1 사용 범위", "- 구매활동 존재 여부와 시장 Evidence로 사용한다.", "- 구매금액·주문건수 자체를 Facet Candidate로 생성하지 않는다.", "- 개별 소비자 Transaction, Product-level sales, MFDS SKU 판매량으로 해석하지 않는다."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("foodpolis", "lg_uplus"), required=True)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    input_dir = args.input_dir or Path("data/raw/purchase") / args.source
    source_path = _find_file(input_dir)
    if source_path is None:
        print({"status": "WAITING_FOR_MANUAL_DOWNLOAD", "source": args.source, "input_dir": str(input_dir)})
        return 0
    if args.source != "lg_uplus":
        raise ValueError("only the LG U+ schema is supported by this adapter")
    frame, encoding, delimiter = read_source(source_path)
    sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    snapshot_id = f"{source_path.stem}:{sha256[:12]}"
    normalized, audit = normalize_lgu(frame, snapshot_id)
    output = args.output or Path("data/processed/purchase") / "lg_uplus_aggregate.parquet"
    report = args.report or Path("reports/lg_uplus_purchase_analysis.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    normalized.to_parquet(output, index=False)
    normalized.to_csv(output.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    (output.parent / "lg_uplus_schema_audit.json").write_text(json.dumps({**audit, "filename": source_path.name, "file_size_bytes": source_path.stat().st_size, "sha256": sha256, "encoding": encoding, "delimiter": delimiter, "snapshot_id": snapshot_id}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report, source_path, audit, encoding, delimiter, sha256)
    print({"status": "COMPLETED", "source": args.source, "raw_rows": len(frame), "normalized_rows": len(normalized), "filename": source_path.name, "sha256": sha256, "encoding": encoding, "output": str(output), "report": str(report)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
