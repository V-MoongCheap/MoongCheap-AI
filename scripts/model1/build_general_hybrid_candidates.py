"""Combine deterministic evidence with validated Model 1 candidates."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms", type=Path, required=True)
    parser.add_argument("--llm", type=Path, required=True)
    parser.add_argument("--model", help="Only use candidates from this model")
    parser.add_argument("--products", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    terms = pd.read_csv(args.terms, dtype=str).fillna("")
    llm = pd.read_csv(args.llm, dtype=str).fillna("") if args.llm.exists() and args.llm.stat().st_size else pd.DataFrame()
    if args.model and not llm.empty:
        if "model" not in llm.columns:
            raise SystemExit("--model requires a model column in the LLM candidate CSV")
        llm = llm.loc[llm["model"].eq(args.model)].copy()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rule = terms.loc[terms["document_ratio"].astype(float) >= 0.05].copy()
    rule_rows = pd.DataFrame({
        "category_key": "domeggook:" + rule["category_name"].astype(str),
        "facet_candidate": "observed_term",
        "value": rule["term"],
        "source": "RULE_EVIDENCE",
        "document_count": rule["document_count"],
        "document_ratio": rule["document_ratio"],
        "source_fields": rule["source_fields"],
        "status": "RULE_CANDIDATE_PENDING_REVIEW",
    })
    if not llm.empty:
        llm = llm[llm["value"].astype(str).str.strip() != ""].copy()
        llm["category_key"] = llm["category_key"].astype(str)
        llm["value_norm"] = llm["value"].map(clean)
        llm["term_match"] = False
        term_map = {(f"domeggook:{row.category_name}", clean(row.term)) for row in terms.itertuples()}
        llm["term_match"] = [
            (category, value) in term_map
            for category, value in zip(llm["category_key"], llm["value_norm"])
        ]
        llm_rows = llm.loc[llm["term_match"]].copy()
        llm_rows["facet_candidate"] = llm_rows["name"]
        llm_rows["source"] = "LLM_GROUNDED_AND_RULE_MATCHED"
        llm_rows["document_count"] = ""
        llm_rows["document_ratio"] = ""
        llm_rows["source_fields"] = llm_rows["source_field"]
        llm_rows["status"] = "HYBRID_CANDIDATE_PENDING_REVIEW"
        llm_rows = llm_rows[["category_key", "facet_candidate", "value", "source", "document_count", "document_ratio", "source_fields", "status"]]
    else:
        llm_rows = pd.DataFrame(columns=rule_rows.columns)
    hybrid = pd.concat([rule_rows, llm_rows], ignore_index=True)
    hybrid.to_csv(args.output_dir / "hybrid_candidates_v1.csv", index=False, encoding="utf-8-sig")
    coverage_report: dict[str, object] = {"status": "NOT_BUILT"}
    if args.products:
        products = pd.read_csv(args.products, dtype=str).fillna("")
        term_groups = {
            str(category): [clean(term) for term in group["term"].tolist() if clean(term)]
            for category, group in terms.groupby("category_name", sort=False)
        }
        llm_ids = set(llm.get("source_product_id", pd.Series(dtype=str)).astype(str)) if not llm.empty else set()
        product_rows = []
        text_fields = ("name", "category_path", "keywords", "description_item", "detail_size", "manufacturer", "model", "info_duty")
        for item in products.to_dict(orient="records"):
            category = str(item.get("category_path", ""))
            text = clean(" ".join(str(item.get(field, "")) for field in text_fields))
            matched_terms = [term for term in term_groups.get(category, []) if term in text]
            product_id = str(item.get("source_product_id", ""))
            rule_hit = bool(matched_terms)
            llm_hit = product_id in llm_ids
            if rule_hit and llm_hit:
                status = "RULE_AND_LLM"
            elif rule_hit:
                status = "RULE_ONLY"
            elif llm_hit:
                status = "LLM_ONLY"
            else:
                status = "NO_RELIABLE_FACET_EVIDENCE"
            product_rows.append({
                "source_product_id": product_id,
                "category_name": category,
                "rule_term_count": len(matched_terms),
                "rule_terms": "|".join(matched_terms[:20]),
                "llm_candidate": llm_hit,
                "coverage_status": status,
            })
        product_coverage = pd.DataFrame(product_rows)
        category_coverage = product_coverage.groupby("category_name", dropna=False).agg(
            product_count=("source_product_id", "size"),
            rule_or_llm_covered=("coverage_status", lambda s: int((s != "NO_RELIABLE_FACET_EVIDENCE").sum())),
            no_reliable_evidence=("coverage_status", lambda s: int((s == "NO_RELIABLE_FACET_EVIDENCE").sum())),
        ).reset_index()
        category_coverage["coverage_ratio"] = (category_coverage["rule_or_llm_covered"] / category_coverage["product_count"]).round(6)
        product_coverage.to_csv(args.output_dir / "product_coverage_v1.csv", index=False, encoding="utf-8-sig")
        product_coverage.loc[
            product_coverage["coverage_status"].eq("NO_RELIABLE_FACET_EVIDENCE")
        ].to_csv(args.output_dir / "llm_fallback_queue_v1.csv", index=False, encoding="utf-8-sig")
        category_coverage.to_csv(args.output_dir / "category_coverage_v1.csv", index=False, encoding="utf-8-sig")
        coverage_report = {
            "status": "COMPLETED",
            "products": len(product_coverage),
            "categories": len(category_coverage),
            "covered_products": int((product_coverage["coverage_status"] != "NO_RELIABLE_FACET_EVIDENCE").sum()),
            "unresolved_products": int((product_coverage["coverage_status"] == "NO_RELIABLE_FACET_EVIDENCE").sum()),
            "coverage_ratio": round(float((product_coverage["coverage_status"] != "NO_RELIABLE_FACET_EVIDENCE").mean()), 6) if len(product_coverage) else 0.0,
            "unresolved_policy": "Do not drop; route to LLM fallback or human review.",
            "coverage_definition": "Every input product is retained in product_coverage_v1.csv; coverage means an evidence-backed facet candidate exists, not that every product must have a facet.",
        }
    report = {
        "rule_candidate_rows": len(rule_rows),
        "llm_candidate_rows": len(llm),
        "hybrid_llm_rows": len(llm_rows),
        "hybrid_total_rows": len(hybrid),
        "policy": "Rule evidence is the baseline; LLM candidates enter Hybrid only when their value also appears in category-level evidence.",
        "requires_human_review": True,
        "coverage": coverage_report,
    }
    (args.output_dir / "hybrid_report_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
