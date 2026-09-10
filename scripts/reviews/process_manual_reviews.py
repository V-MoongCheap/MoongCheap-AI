"""Process an authorized local review export; never crawl the source site."""

from __future__ import annotations

import argparse
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PII_PATTERNS = (
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:01\d|02|0[3-6]\d|070)[- .]?\d{3,4}[- .]?\d{4}(?!\d)"), "[PHONE]"),
)
MEDICAL_OUTCOME = re.compile(r"혈압|혈당|통증|염증|질환|병이|치료|완치|낫|수치가 낮|수치가 내려|효과가 있", re.I)
HFF_MARKERS = re.compile(r"건강기능식품|건기식|기능성 원료|영양제|비타민|유산균|오메가|콜라겐|홍삼|프로바이오틱", re.I)
FACET_PATTERNS = {
    "capsule_size": (re.compile(r"알약|캡슐|알이|목넘김|삼키"), "product_form_or_size"),
    "odor": (re.compile(r"비린내|냄새|향이|무취"), "odor"),
    "taste": (re.compile(r"맛|단맛|쓴맛|뒷맛"), "taste"),
    "intake_convenience": (re.compile(r"하루 ?한 ?번|섭취하기|먹기 편|간편"), "intake_convenience"),
    "packaging_type": (re.compile(r"개별 ?포장|스틱|휴대|포장"), "packaging_type"),
    "storage": (re.compile(r"보관|냉장|용해|잘 녹"), "storage_or_solubility"),
}


def mask_pii(value: object) -> str:
    text = "" if value is None or pd.isna(value) else str(value)
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


def process_reviews(frame: pd.DataFrame, source_id: str = "esthermall_goodsreview") -> tuple[pd.DataFrame, dict[str, int]]:
    frame = frame.fillna("").copy()
    required = {"source_review_id", "review_text"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"review export is missing columns: {missing}")
    for column in ("product_name", "product_type", "source_product_id", "review_title"):
        if column not in frame:
            frame[column] = ""
    frame["review_text"] = frame["review_text"].map(mask_pii)
    frame["review_title"] = frame["review_title"].map(mask_pii)
    frame = frame.drop_duplicates("source_review_id")
    hff = frame[frame[["product_name", "product_type"]].astype(str).apply(lambda column: column.str.contains(HFF_MARKERS, na=False)).any(axis=1)].copy()
    rows = []
    for item in hff.itertuples():
        text = " ".join(str(getattr(item, column, "")) for column in ("review_title", "review_text") if str(getattr(item, column, ""))).strip()
        medical = bool(MEDICAL_OUTCOME.search(text))
        for facet, (pattern, value) in FACET_PATTERNS.items():
            if pattern.search(text):
                rows.append({
                    "evidence_id": f"{source_id}:{item.source_review_id}:{facet}",
                    "source_id": source_id,
                    "source_review_id": str(item.source_review_id),
                    "source_product_id": str(item.source_product_id),
                    "product_name": str(item.product_name),
                    "service_category": "health-functional-food",
                    "facet_candidate": facet,
                    "value_candidate": value,
                    "evidence_text": text,
                    "evidence_type": "SUBJECTIVE_MEDICAL_OUTCOME" if medical else "CONSUMER_EXPERIENCE",
                    "medical_outcome": medical,
                    "rating": str(getattr(item, "rating", "")),
                    "verified_purchase": str(getattr(item, "verified_purchase", "")),
                    "verification_basis": str(getattr(item, "verification_basis", "")),
                    "source_type": "KOREAN_HFF_PURCHASED_REVIEW",
                })
    result = pd.DataFrame(rows)
    if not result.empty:
        result = result[~result["medical_outcome"]].copy()
    stats = {
        "collected_review_count": int(len(frame)),
        "usable_review_text_count": int(frame["review_text"].astype(str).str.strip().ne("").sum()),
        "unique_review_count": int(frame["source_review_id"].nunique()),
        "hff_product_review_count": int(len(hff)),
        "medical_outcome_excluded_count": int(sum(bool(MEDICAL_OUTCOME.search(str(value))) for value in hff["review_text"])),
        "facet_expression_evidence_count": int(len(result)),
    }
    return result, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/reviews"))
    args = parser.parse_args()
    frame = pd.read_parquet(args.input) if args.input.suffix.lower() == ".parquet" else pd.read_csv(args.input, dtype=str)
    result, stats = process_reviews(frame)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result.to_parquet(args.output_dir / "esthermall_hff_review_evidence.parquet", index=False)
    result.to_csv(args.output_dir / "esthermall_hff_review_evidence_preview.csv", index=False, encoding="utf-8-sig")
    raw_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    report = {"source_file": str(args.input), "raw_sha256": raw_hash, "collected_at": datetime.now(timezone.utc).isoformat(), **stats}
    (args.output_dir / "esthermall_review_processing_report.json").write_text(pd.Series(report).to_json(force_ascii=False, indent=2), encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
