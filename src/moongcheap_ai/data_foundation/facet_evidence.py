"""Build provenance-preserving Facet evidence from local source snapshots.

This module produces candidate evidence only. It never mutates the approved
taxonomy and never treats search, Q&A, review, or seller text as demand truth.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


UNIFIED_COLUMNS = [
    "evidence_id", "category", "service_category", "source", "source_type",
    "document_id", "product_ref", "text_raw", "normalized_attribute",
    "normalized_value", "evidence_term", "behavior_evidence", "medical_risk",
    "license_status", "local_only",
]

HEALTH_TERMS = re.compile(r"건강|건기식|영양|비타민|미네랄|프로바이오틱|유산균|홍삼|인삼|오메가|콜라겐|단백질|루테인|마그네슘|supplement|vitamin|probiotic|collagen|protein|ginseng|omega|lutein|保健|维生素|益生菌|胶原蛋白|蛋白质|人参|鱼油|叶黄素|营养|膳食", re.I)
MEDICAL_TERMS = re.compile(r"질병|질환|진단|치료|처방|부작용|완치|암|당뇨 치료|medical|diagnos|cure|treat", re.I)
ATTRIBUTE_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "product_form": [("tablet", r"정제|타블렛|tablet"), ("capsule", r"캡슐|capsule"), ("powder", r"분말|가루|powder"), ("liquid", r"액상|액체|liquid"), ("stick", r"스틱|stick")],
    "intake_frequency": [("once_daily", r"하루s*(한|1)s*번|1일s*1회|once a day"), ("multiple_daily", r"하루s*(두|2)s*번|1일s*[2-9]회")],
    "sugar_type": [("sugar_free", r"무설탕|sugar[- ]?free"), ("low_sugar", r"저당|low sugar")],
    "odor": [("fishy", r"비린내|생선s*냄새|fishy"), ("low_odor", r"저취|냄새s*적은|low odor"), ("odorless", r"무취|냄새s*없|odorless")],
    "capsule_size": [("small", r"작은s*알약|삼키기s*쉬운|small pill"), ("large", r"큰s*알약|large pill")],
    "storage_type": [("refrigerated", r"냉장s*보관|refrigerat")],
    "portability": [("portable", r"휴대|portable|travel")],
    "taste": [("sweet", r"달다|달콤|sweet"), ("bitter", r"쓰다|쓴맛|bitter")],
    "ingredient_presence": [("contains_dairy", r"우유|유제품|dairy"), ("contains_gluten", r"글루텐|gluten")],
    "ingredient_absence": [("dairy_free", r"우유s*없|유제품s*없|dairy[- ]?free"), ("gluten_free", r"글루텐s*없|gluten[- ]?free")],
}
ATTRIBUTE_CANONICAL = {"intake_frequency": "daily_frequency", "functional_ingredient": "functional_ingredients"}
EXISTING_FACETS = {"product_form", "daily_frequency", "functional_ingredients"}
SOURCE_LICENSES = {
    "mfds": ("", "UNKNOWN"), "domeggook": ("", "UNKNOWN"),
    "esci": ("https://github.com/amazon-science/esci-data", "SEE_SOURCE_REPOSITORY"),
    "xpqa": ("https://github.com/amazon-science/contextual-product-qa", "CDLA-Sharing-1.0"),
    "kuaisearch": ("https://huggingface.co/datasets/benchen4395/KuaiSearch", "MIT"),
    "amazon_reviews": ("", "UNKNOWN"), "aihub": ("", "UNKNOWN"),
}


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _split_values(value: Any) -> list[str]:
    return [part.strip() for part in re.split(r"[,;|·\n]+", _text(value)) if part.strip()]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=UNIFIED_COLUMNS)


def _row(source: str, source_type: str, document_id: Any, product_ref: Any, category: Any, text_raw: Any, attribute: str, value: str, term: Any = "", behavior: Any = "", risk: str = "SAFE_ATTRIBUTE", license_status: str = "UNKNOWN") -> dict[str, Any]:
    return {
        "evidence_id": f"{source}:{document_id}:{attribute}:{value}", "category": _text(category), "service_category": _text(category),
        "source": source, "source_type": source_type, "document_id": _text(document_id), "product_ref": _text(product_ref),
        "text_raw": _text(text_raw), "normalized_attribute": attribute, "normalized_value": value, "evidence_term": _text(term) or value,
        "behavior_evidence": _text(behavior), "medical_risk": risk, "license_status": license_status, "local_only": True,
    }


def _extract_text_evidence(source: str, source_type: str, frame: pd.DataFrame, text_columns: list[str], category_column: str, id_column: str, product_column: str, license_status: str = "UNKNOWN") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        text = " | ".join(_text(item.get(column, "")) for column in text_columns if _text(item.get(column, "")))
        if not text:
            continue
        risk = "DROP" if MEDICAL_TERMS.search(text) else "SAFE_ATTRIBUTE"
        if risk == "DROP":
            continue
        for attribute, patterns in ATTRIBUTE_PATTERNS.items():
            for value, pattern in patterns:
                if re.search(pattern, text, re.I):
                    rows.append(_row(source, source_type, item.get(id_column, ""), item.get(product_column, ""), item.get(category_column, ""), text, attribute, value, term=value, license_status=license_status))
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS) if rows else _empty()


def build_mfds(path: Path, mapping_path: Path | None = None) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str).fillna("")
    mapping = None
    if mapping_path and mapping_path.exists():
        mapping = pd.read_csv(mapping_path, dtype=str).fillna("").set_index("source_product_id")
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        ref = _text(item.get("source_product_id"))
        category = mapping.loc[ref, "service_category_candidate_key"] if mapping is not None and ref in mapping.index else _text(item.get("product_type"))
        text = " | ".join(_text(item.get(column, "")) for column in ("name", "product_form", "main_functionality", "intake_method", "standard_spec", "functional_ingredients"))
        for attribute, field in (("product_form", "product_form"), ("intake_frequency", "intake_method"), ("functional_ingredient", "functional_ingredients"), ("regulated_function", "main_functionality")):
            for value in _split_values(item.get(field, "")):
                rows.append(_row("mfds", "PRODUCT_FACT", ref, ref, category, text, attribute, value, license_status="UNKNOWN"))
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS) if rows else _empty()


def build_seller(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str).fillna("")
    frame = frame[frame.get("health_scope", "").astype(str).eq("core")]
    frame = frame.copy(); frame["service_category"] = "health-functional-food"
    return _extract_text_evidence("domeggook", "SELLER_LISTING", frame, ["title", "semantic_text", "package_spec", "ingredients_raw", "functionality_raw", "intake_raw"], "service_category", "item_id", "item_id")


def build_esci(directory: Path) -> pd.DataFrame:
    queries = pd.read_parquet(directory / "queries.parquet")
    products = pd.read_parquet(directory / "products.parquet")
    health_products = products[products.astype(str).apply(lambda col: col.str.contains(HEALTH_TERMS, regex=True, na=False)).any(axis=1)]
    ids = set(health_products["product_id"].astype(str))
    queries = queries[queries["query"].astype(str).str.contains(HEALTH_TERMS, regex=True, na=False)]
    queries["category"] = "health-functional-food"
    return _extract_text_evidence("esci", "CONSUMER_SEARCH", queries, ["query", "query_clean"], "category", "query_id", "query_id", "SEE_SOURCE_REPOSITORY") if ids or not health_products.empty else _empty()


def build_xpqa(directory: Path) -> pd.DataFrame:
    files = list(directory.rglob("*.csv"))
    frames = [pd.read_csv(path, dtype=str, on_bad_lines="skip").fillna("") for path in files if path.name in {"train.csv", "dev.csv", "test.csv"}]
    if not frames:
        return _empty()
    frame = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["ASIN", "qa_id", "question"])
    frame = frame[frame[["title", "question", "question_en", "answer"]].astype(str).apply(lambda col: col.str.contains(HEALTH_TERMS, regex=True, na=False)).any(axis=1)]
    frame["category"] = "health-functional-food"
    return _extract_text_evidence("xpqa", "CONSUMER_QA", frame, ["title", "question", "question_en", "answer"], "category", "qa_id", "ASIN", "CDLA-Sharing-1.0")


def build_aihub(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty()
    frame = pd.read_csv(path, dtype=str).fillna("")
    rows = [_row("aihub", "KOREAN_EXPRESSION_REFERENCE", item.get("term"), "", "expression-reference", item.get("term"), "expression_reference", _text(item.get("term")), term=item.get("term"), license_status="UNKNOWN") for _, item in frame.iterrows() if _text(item.get("term"))]
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS) if rows else _empty()


def build_kuaisearch(directory: Path, query_output: Path | None = None, translated_path: Path | None = None) -> pd.DataFrame:
    """Join Lite item metadata to session behavior without retaining user IDs."""
    item_path = directory / "items_lite" / "train.jsonl"
    recall_path = directory / "recall_lite" / "train.jsonl"
    if not item_path.exists() or not recall_path.exists():
        return _empty()
    health_items: dict[str, dict[str, Any]] = {}
    with item_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = " | ".join(_text(item.get(key)) for key in ("item_title", "category_level1_name", "category_level2_name", "category_level3_name"))
            if HEALTH_TERMS.search(text):
                health_items[str(item.get("item_id"))] = item
    translation_map: dict[str, str] = {}
    if translated_path and translated_path.exists():
        translated = pd.read_parquet(translated_path).fillna("")
        translation_map = dict(zip(translated["query_raw"].astype(str), translated["query_translated"].astype(str)))
    rows: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []
    with recall_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            purchased = {str(value) for value in record.get("purchased_item_ids", [])}
            clicked = {str(value) for value in record.get("clicked_item_ids", [])}
            impressed = {str(value) for value in record.get("impressed_item_ids", [])}
            matched = (purchased | clicked | impressed) & health_items.keys()
            query = _text(record.get("query"))
            if not matched and not HEALTH_TERMS.search(query):
                continue
            behavior = "PURCHASED_HEALTH" if purchased & health_items.keys() else "CLICKED_HEALTH" if clicked & health_items.keys() else "IMPRESSION_HEALTH"
            query_rows.append({"source": "kuaisearch", "query_raw": query, "language": "zh", "health_item_id": "|".join(sorted(matched)), "behavior_evidence": behavior, "source_record_id": _text(record.get("session_id"))})
            for item_id in sorted(matched):
                item = health_items[item_id]
                text = f"{translation_map.get(query, '') or query} | {_text(item.get('item_title'))}"
                for attribute, patterns in ATTRIBUTE_PATTERNS.items():
                    for value, pattern in patterns:
                        if re.search(pattern, text, re.I):
                            rows.append(_row("kuaisearch", "CONSUMER_SEARCH", record.get("session_id"), item_id, "health-functional-food", text, attribute, value, term=value, behavior=behavior, license_status="MIT"))
    if query_output is not None:
        query_output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(query_rows, columns=["source", "query_raw", "language", "health_item_id", "behavior_evidence", "source_record_id"]).to_parquet(query_output, index=False)
        pd.DataFrame(query_rows, columns=["source", "query_raw", "language", "health_item_id", "behavior_evidence", "source_record_id"]).to_csv(query_output.with_name("kuaiseach_health_queries_preview.csv"), index=False, encoding="utf-8-sig")
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS) if rows else _empty()


def aggregate_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["category", "facet_candidate", "value_candidate", "mfds_document_count", "mfds_document_ratio", "seller_document_count", "seller_document_ratio", "search_query_count", "search_click_count", "search_purchase_count", "qa_count", "review_count", "korean_expression_count", "source_count", "product_verifiability", "consumer_salience", "commercial_salience", "new_facet_candidate", "review_status"])
    usable = frame[(frame["medical_risk"].ne("DROP")) & (frame["source_type"] != "KOREAN_EXPRESSION_REFERENCE")].copy()
    keys = ["category", "normalized_attribute", "normalized_value"]
    rows: list[dict[str, Any]] = []
    for (category, attribute, value), group in usable.groupby(keys, dropna=False):
        counts = group.groupby("source_type")["document_id"].nunique().to_dict()
        source_count = int(group["source"].nunique())
        attribute = ATTRIBUTE_CANONICAL.get(str(attribute), str(attribute))
        rows.append({
            "category": category, "facet_candidate": attribute, "value_candidate": value,
            "mfds_document_count": int(counts.get("PRODUCT_FACT", 0)), "mfds_document_ratio": 0.0,
            "seller_document_count": int(counts.get("SELLER_LISTING", 0)), "seller_document_ratio": 0.0,
            "search_query_count": int(counts.get("CONSUMER_SEARCH", 0)), "search_click_count": 0, "search_purchase_count": 0,
            "qa_count": int(counts.get("CONSUMER_QA", 0)), "review_count": int(counts.get("CONSUMER_REVIEW", 0)),
            "korean_expression_count": int(counts.get("KOREAN_EXPRESSION_REFERENCE", 0)), "source_count": source_count,
            "product_verifiability": "HIGH" if counts.get("PRODUCT_FACT", 0) else "LOW",
            "consumer_salience": "HIGH" if counts.get("CONSUMER_SEARCH", 0) or counts.get("CONSUMER_QA", 0) or counts.get("CONSUMER_REVIEW", 0) else "LOW",
            "commercial_salience": "HIGH" if counts.get("SELLER_LISTING", 0) else "LOW",
            "new_facet_candidate": attribute not in EXISTING_FACETS, "review_status": "REVIEW",
        })
    return pd.DataFrame(rows).sort_values(["category", "facet_candidate", "value_candidate"]).reset_index(drop=True)


def build_review_queue(aggregate: pd.DataFrame, evidence: pd.DataFrame) -> pd.DataFrame:
    if aggregate.empty:
        return pd.DataFrame()
    evidence = evidence.copy()
    if "text_raw" not in evidence:
        evidence["text_raw"] = ""
    evidence["normalized_attribute"] = evidence["normalized_attribute"].map(lambda value: ATTRIBUTE_CANONICAL.get(str(value), str(value)))
    examples = evidence.groupby(["category", "normalized_attribute", "normalized_value"], dropna=False).agg(example_product_evidence=("text_raw", "first"), source_count=("source", "nunique")).reset_index()
    examples = examples.rename(columns={"normalized_attribute": "facet_candidate", "normalized_value": "value_candidate"})
    result = aggregate.merge(examples, on=["category", "facet_candidate", "value_candidate"], how="left")
    result["aliases"] = result["value_candidate"]
    result["review_decision"] = ""
    result["review_note"] = "Candidate evidence only; reviewer approval required"
    return result


def build_audit(evidence: pd.DataFrame, aggregate: pd.DataFrame, source_status: list[dict[str, Any]]) -> str:
    lines = ["# FACET EVIDENCE RESULT", "", "## Existing Data", f"- MFDS evidence rows: {int((evidence.source == 'mfds').sum())}", f"- Seller evidence rows: {int((evidence.source == 'domeggook').sum())}", f"- AI-Hub expression rows: {int((evidence.source == 'aihub').sum())}", "", "## New Sources"]
    for item in source_status:
        lines.append(f"- {item['source']}: {item['status']} ({item['rows']} evidence rows)")
    lines += ["", "## Facet Candidates", f"- Candidate rows: {len(aggregate)}", f"- New Facet candidates: {int(aggregate['new_facet_candidate'].sum()) if not aggregate.empty else 0}", "- Existing taxonomy is not automatically changed.", "", "## Limitations", "- Search, Q&A, review, seller text, and AI-Hub expressions are reference evidence, not consumer-demand ground truth.", "- Missing or unknown license information is not inferred as permission.", "- Human review is required before taxonomy or alias approval."]
    return "\n".join(lines) + "\n"


def run_pipeline(root: Path, output_dir: Path, enable_reviews: bool = False) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mfds = root / "data/interim/facet_discovery/i0030_products_clean_dedup.csv"
    mapping = root / "data/processed/category_v2_1_current/product_service_category_mapping_v2_1.csv"
    evidence = [build_mfds(mfds, mapping) if mfds.exists() else _empty()]
    statuses = [{"source": "mfds", "status": "AVAILABLE" if mfds.exists() else "NOT_ACQUIRED", "rows": len(evidence[0])}]
    seller = root / "data/processed/domeggook/seller_offers_core.csv"
    seller_frame = build_seller(seller) if seller.exists() else _empty(); evidence.append(seller_frame); statuses.append({"source": "domeggook", "status": "AVAILABLE" if seller.exists() else "NOT_ACQUIRED", "rows": len(seller_frame)})
    esci = root / "data/processed/esci"; esci_frame = build_esci(esci) if (esci / "queries.parquet").exists() and (esci / "products.parquet").exists() else _empty(); evidence.append(esci_frame); statuses.append({"source": "esci", "status": "AVAILABLE" if not esci_frame.empty else "NO_HEALTH_MATCH", "rows": len(esci_frame)})
    xpqa = root / "data/raw/consumer_reference/xpqa"; xpqa_frame = build_xpqa(xpqa) if xpqa.exists() else _empty(); evidence.append(xpqa_frame); statuses.append({"source": "xpqa", "status": "AVAILABLE" if not xpqa_frame.empty else "NO_HEALTH_MATCH", "rows": len(xpqa_frame)})
    kuai = root / "data/raw/consumer_reference/kuaisearch"; kuai_frame = build_kuaisearch(kuai, output_dir / "kuaiseach_health_queries.parquet"); evidence.append(kuai_frame); statuses.append({"source": "kuaisearch", "status": "AVAILABLE" if (kuai / "items_lite" / "train.jsonl").exists() else "NOT_ACQUIRED", "rows": len(kuai_frame)})
    reviews = root / "data/raw/facet_evidence/amazon_reviews"; statuses.append({"source": "amazon_reviews", "status": "ENABLED" if enable_reviews and reviews.exists() else "NOT_ACQUIRED", "rows": 0})
    aihub = root / "data/interim/facet_discovery/aihub_repeated_terms.csv"; aihub_frame = build_aihub(aihub); evidence.append(aihub_frame); statuses.append({"source": "aihub", "status": "AVAILABLE_EXPRESSION_REFERENCE" if aihub.exists() else "NOT_ACQUIRED", "rows": len(aihub_frame)})
    unified = pd.concat(evidence, ignore_index=True) if evidence else _empty()
    aggregate = aggregate_evidence(unified); review = build_review_queue(aggregate, unified)
    unified.to_parquet(output_dir / "facet_evidence_unified.parquet", index=False); unified.to_csv(output_dir / "facet_evidence_unified_preview.csv", index=False, encoding="utf-8-sig")
    aggregate.to_csv(output_dir / "facet_cross_source_evidence.csv", index=False, encoding="utf-8-sig"); review.to_csv(output_dir / "facet_review_queue_v1.csv", index=False, encoding="utf-8-sig")
    (output_dir / "facet_candidates_v1.json").write_text(json.dumps({"version": "v1", "status": "REVIEW", "candidates": aggregate.to_dict(orient="records")}, ensure_ascii=False, indent=2), encoding="utf-8")
    license_rows = [{"source": item["source"], "official_url": SOURCE_LICENSES.get(item["source"], ("", "UNKNOWN"))[0], "license": SOURCE_LICENSES.get(item["source"], ("", "UNKNOWN"))[1], "download_allowed": "UNKNOWN", "processing_allowed": "UNKNOWN", "redistribution_allowed": "UNKNOWN", "github_raw_allowed": "UNKNOWN", "local_only": True, "notes": item["status"]} for item in statuses]
    pd.DataFrame(license_rows).to_csv(root / "data/reports/facet_discovery/facet_evidence_source_license.csv", index=False, encoding="utf-8-sig")
    (root / "data/reports/facet_discovery").mkdir(parents=True, exist_ok=True); (root / "data/reports/facet_discovery/FACET_EVIDENCE_RESULT.md").write_text(build_audit(unified, aggregate, statuses), encoding="utf-8")
    return {"status": "COMPLETED", "evidence_rows": len(unified), "candidate_rows": len(aggregate), "review_rows": len(review), "sources": statuses}
