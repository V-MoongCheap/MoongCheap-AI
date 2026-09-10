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
    "naver_shopping_insight": ("https://api.ncloud-docs.com/docs/naver-api-hub-shopping-insight-keywords", "SEE_TERMS"),
    "lgu_hff": ("", "UNKNOWN"), "korean_consumer_aggregate": ("", "UNKNOWN"),
    "aihub": ("", "UNKNOWN"), "nutrime": ("https://www.nutrime.co.kr/board/?id=goods_review", "INTERNAL_ONLY_PUBLIC_SOURCE"),
    "chongkundang": ("https://ckdhcmall.co.kr/brandProductList.do?idx=43&pidx=1", "INTERNAL_ONLY_PUBLIC_SOURCE"),
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
    return _extract_text_evidence("domeggook", "SELLER_PRODUCT_EVIDENCE", frame, ["title", "semantic_text", "package_spec", "ingredients_raw", "functionality_raw", "intake_raw"], "service_category", "item_id", "item_id")


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
                            rows.append(_row("kuaisearch", "FOREIGN_CONSUMER_SEARCH_REFERENCE", record.get("session_id"), item_id, "health-functional-food", text, attribute, value, term=value, behavior=behavior, license_status="MIT"))
    if query_output is not None:
        query_output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(query_rows, columns=["source", "query_raw", "language", "health_item_id", "behavior_evidence", "source_record_id"]).to_parquet(query_output, index=False)
        pd.DataFrame(query_rows, columns=["source", "query_raw", "language", "health_item_id", "behavior_evidence", "source_record_id"]).to_csv(query_output.with_name("kuaiseach_health_queries_preview.csv"), index=False, encoding="utf-8-sig")
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS) if rows else _empty()


def build_kuaisearch_reference(path: Path) -> pd.DataFrame:
    """Use the reviewed translation layer without rescanning the multi-GB raw log."""
    if not path.exists():
        return _empty()
    frame = pd.read_parquet(path).fillna("")
    frame = frame[frame.get("query_translated", "").astype(str).str.strip().ne("")].copy()
    frame["category"] = "health-functional-food"
    frame["query_id"] = frame.get("source_record_id", pd.Series(frame.index, index=frame.index)).astype(str)
    return _extract_text_evidence(
        "kuaisearch", "FOREIGN_CONSUMER_SEARCH_REFERENCE", frame,
        ["query_translated", "query_raw"], "category", "query_id", "query_id", "MIT",
    )


def build_naver_trends(path: Path) -> pd.DataFrame:
    """Load already-collected Naver trends as Korean search evidence."""
    if not path.exists():
        return _empty()
    frame = pd.read_csv(path, dtype=str).fillna("")
    rows = []
    for item in frame.itertuples():
        facet = _text(getattr(item, "facet_candidate", ""))
        value = _text(getattr(item, "value_candidate", ""))
        if not facet or not value:
            title = _text(getattr(item, "facet_keyword_group", ""))
            facet, _, value = title.partition(":")
        if not value:
            continue
        rows.append(_row(
            "naver_shopping_insight", "KOREAN_CONSUMER_SEARCH_EVIDENCE",
            f"{getattr(item, 'service_category', '')}:{getattr(item, 'period', '')}:{value}",
            "", getattr(item, "service_category", ""),
            getattr(item, "keyword", value), facet, value,
            term=value, behavior=f"ratio={getattr(item, 'ratio', '')}",
            license_status="SEE_TERMS",
        ))
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS) if rows else _empty()


REVIEW_MEDICAL_TERMS = re.compile(r"효과가 있다|효과 봤|치료|완치|질환|병이|통증이 좋아|면역력이 좋아|혈압이 내려|혈당이 내려|medical|diagnos|cure|treat", re.I)
REVIEW_ATTRIBUTE_PATTERNS = {
    "product_form": [("tablet", r"정제|알약|tablet"), ("capsule", r"캡슐|capsule"), ("powder", r"분말|가루|powder"), ("liquid", r"액상|액체|liquid"), ("stick", r"스틱|stick")],
    "tablet_size": [("small", r"알이 작|작은 알|작아서|작은 정"), ("large", r"알이 크|큰 알|커서")],
    "swallowability": [("easy", r"목넘김이 편|삼키기 편|먹기 편"), ("difficult", r"목넘김이 어렵|삼키기 어렵")],
    "taste": [("sweet", r"달콤|달다|단맛|sweet"), ("bitter", r"쓰다|쓴맛|bitter"), ("aftertaste", r"끝맛|뒷맛|aftertaste")],
    "odor": [("fishy", r"비린내|비린|fishy"), ("low_odor", r"냄새가 약|냄새가 거의"), ("odorless", r"무취|냄새가 없다")],
    "intake_frequency": [("once_daily", r"하루 한 번|하루에 한 번|1일 1회"), ("multiple_daily", r"하루 두 번|하루에 여러 번|1일 2회")],
    "intake_convenience": [("convenient", r"간편|편리|챙겨먹기 편|휴대하기 편"), ("inconvenient", r"번거|귀찮|챙겨 먹기 힘")],
    "packaging": [("individual_packaging", r"개별 포장|한 포씩|한팩"), ("portable", r"휴대|들고 다니")],
    "mixability": [("easy_to_mix", r"잘 녹|잘 섞|녹이기 편"), ("hard_to_mix", r"안 녹|잘 안 섞")],
    "ingredient_inclusion": [("ingredient_mentioned", r"비타민|미네랄|유산균|칼슘|오메가|콜라겐|단백질")],
}


def _review_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?。？！])|\n+", _text(text)) if part.strip()]


def build_review_evidence(path: Path, source: str, max_reviews_per_product: int | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Convert an authorized local Review JSONL snapshot into candidate evidence."""
    if not path.exists():
        return _empty(), {"review_count": 0, "mapped_count": 0, "medical_outcome_sentence_count": 0, "facet_expression_candidate_count": 0}
    reviews: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                reviews.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows: list[dict[str, Any]] = []
    medical_count = 0
    sampled_product_counts: dict[str, int] = {}
    sampled_review_count = 0
    for item in reviews:
        review_id = _text(item.get("source_review_id"))
        product_id = _text(item.get("source_product_id"))
        if max_reviews_per_product is not None:
            if max_reviews_per_product < 1:
                raise ValueError("max_reviews_per_product must be positive")
            if product_id:
                current_count = sampled_product_counts.get(product_id, 0)
                if current_count >= max_reviews_per_product:
                    continue
                sampled_product_counts[product_id] = current_count + 1
            sampled_review_count += 1
        text = " ".join(_text(item.get(key, "")) for key in ("review_title", "review_text") if _text(item.get(key, "")))
        for sentence_index, sentence in enumerate(_review_sentences(text)):
            if REVIEW_MEDICAL_TERMS.search(sentence):
                medical_count += 1
                continue
            for attribute, patterns in REVIEW_ATTRIBUTE_PATTERNS.items():
                for value, pattern in patterns:
                    if re.search(pattern, sentence, re.I):
                        rows.append(_row(source, "KOREAN_HFF_RAW_REVIEW", f"{review_id}:{sentence_index}", product_id, "health-functional-food", sentence, attribute, value, term=sentence, license_status="INTERNAL_ONLY_PUBLIC_SOURCE"))
    evidence = pd.DataFrame(rows, columns=UNIFIED_COLUMNS) if rows else _empty()
    return evidence, {
        "review_count": len(reviews),
        "mapped_count": sum(bool(_text(item.get("source_product_id"))) for item in reviews),
        "medical_outcome_sentence_count": medical_count,
        "facet_expression_candidate_count": len(evidence),
        "sampled_review_count": sampled_review_count if max_reviews_per_product is not None else len(reviews),
        "max_reviews_per_product": max_reviews_per_product or 0,
    }


def read_optional_aggregate(directory: Path, source: str, source_type: str) -> pd.DataFrame:
    """Read user-provided aggregate CSV/Parquet without inventing missing data."""
    if not directory.exists():
        return pd.DataFrame()
    paths = sorted([*directory.glob("*.csv"), *directory.glob("*.parquet")])
    if not paths:
        return pd.DataFrame()
    path = paths[0]
    frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, dtype=str)
    frame = frame.fillna("")
    frame.insert(0, "source", source)
    frame.insert(1, "source_type", source_type)
    frame.insert(2, "source_record_id", [f"{source}:{index}" for index in frame.index])
    return frame


def build_lgu_purchase_evidence(path: Path) -> pd.DataFrame:
    """Represent LG U+ market metrics in unified evidence without making facets."""
    if not path.exists():
        return _empty()
    frame = pd.read_parquet(path).fillna("")
    rows = []
    for item in frame.to_dict(orient="records"):
        behavior = " | ".join(str(item.get(column, "")) for column in ("period", "region_sido", "region_sigungu", "region_dong") if str(item.get(column, "")).strip())
        rows.append(_row("lgu_uplus", "KOREAN_HFF_PURCHASE_AGGREGATE", item.get("source_record_id", ""), "", "", item.get("market_metric_raw", ""), "market_metric", item.get("market_metric_type", ""), term=item.get("market_metric_raw", ""), behavior=behavior, license_status="INTERNAL_ONLY_PROVIDER_FILE"))
    return pd.DataFrame(rows, columns=UNIFIED_COLUMNS) if rows else _empty()


def aggregate_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["category", "facet_candidate", "value_candidate", "mfds_support", "nutrition_db_support", "seller_support", "korean_purchase_support", "korean_search_support", "korean_consumer_aggregate_support", "foreign_reference_support", "korean_expression_support", "source_count", "product_verifiability", "korean_consumer_salience", "commercial_salience", "foreign_only_flag", "new_facet_candidate", "review_status"])
    usable = frame[(frame["medical_risk"].ne("DROP")) & (~frame["source_type"].isin({"KOREAN_EXPRESSION_REFERENCE", "KOREAN_HFF_PURCHASE_AGGREGATE"}))].copy()
    keys = ["category", "normalized_attribute", "normalized_value"]
    rows: list[dict[str, Any]] = []
    for (category, attribute, value), group in usable.groupby(keys, dropna=False):
        counts = group.groupby("source_type")["document_id"].nunique().to_dict()
        source_count = int(group["source"].nunique())
        attribute = ATTRIBUTE_CANONICAL.get(str(attribute), str(attribute))
        rows.append({
            "category": category, "facet_candidate": attribute, "value_candidate": value,
            "mfds_support": int(counts.get("PRODUCT_FACT", 0)), "nutrition_db_support": int(counts.get("NUTRITION_DB_PRODUCT_FACT", 0)),
            "seller_support": int(counts.get("SELLER_PRODUCT_EVIDENCE", 0)),
            "korean_purchase_support": int(counts.get("KOREAN_HFF_PURCHASE_AGGREGATE", 0)),
            "korean_search_support": int(counts.get("KOREAN_CONSUMER_SEARCH_EVIDENCE", 0)),
            "korean_consumer_aggregate_support": int(counts.get("KOREAN_CONSUMER_AGGREGATE", 0)),
            "foreign_reference_support": int(counts.get("FOREIGN_CONSUMER_SEARCH_REFERENCE", 0)),
            "korean_expression_support": int(counts.get("KOREAN_EXPRESSION_REFERENCE", 0)), "source_count": source_count,
            "product_verifiability": "HIGH" if counts.get("PRODUCT_FACT", 0) else "LOW",
            "korean_consumer_salience": "HIGH" if counts.get("KOREAN_CONSUMER_SEARCH_EVIDENCE", 0) or counts.get("KOREAN_HFF_PURCHASE_AGGREGATE", 0) or counts.get("KOREAN_CONSUMER_AGGREGATE", 0) else "LOW",
            "commercial_salience": "HIGH" if counts.get("SELLER_PRODUCT_EVIDENCE", 0) else "LOW",
            "foreign_only_flag": bool(counts.get("FOREIGN_CONSUMER_SEARCH_REFERENCE", 0) and not any(counts.get(item, 0) for item in ("PRODUCT_FACT", "SELLER_PRODUCT_EVIDENCE", "KOREAN_CONSUMER_SEARCH_EVIDENCE"))),
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
    examples = examples.rename(columns={"normalized_attribute": "facet_candidate", "normalized_value": "value_candidate", "source_count": "evidence_source_count"})
    result = aggregate.merge(examples, on=["category", "facet_candidate", "value_candidate"], how="left")
    result["aliases"] = result["value_candidate"]
    result["review_decision"] = ""
    result["review_note"] = "Candidate evidence only; reviewer approval required"
    for source in ("nutrime", "chongkundang"):
        counts = evidence[evidence["source"].eq(source)].groupby(["category", "normalized_attribute", "normalized_value"]).size()
        key = pd.MultiIndex.from_frame(result[["category", "facet_candidate", "value_candidate"]].rename(columns={"facet_candidate": "normalized_attribute", "value_candidate": "normalized_value"}))
        result[f"{source}_review_evidence_count"] = [int(counts.get(item, 0)) for item in key]
    result["review_source_count"] = ((result.get("nutrime_review_evidence_count", 0) > 0).astype(int) + (result.get("chongkundang_review_evidence_count", 0) > 0).astype(int))
    result["consumer_review_support"] = ((result["review_source_count"] > 0).astype(int))
    result["product_fact_support"] = (result["mfds_support"] > 0).astype(int)
    result["seller_support"] = (result["seller_support"] > 0).astype(int)
    grouped_examples = evidence.groupby(["category", "normalized_attribute", "normalized_value"])["text_raw"].apply(lambda values: list(dict.fromkeys(str(value) for value in values if str(value).strip()))[:2]).to_dict()
    example_keys = list(zip(result["category"], result["facet_candidate"], result["value_candidate"]))
    result["review_example_1"] = [grouped_examples.get(key, ["", ""])[0] if grouped_examples.get(key) else "" for key in example_keys]
    result["review_example_2"] = [grouped_examples.get(key, ["", ""])[1] if len(grouped_examples.get(key, [])) > 1 else "" for key in example_keys]
    result["cross_source_support_count"] = result["source_count"]
    result["priority"] = "LOW"
    result.loc[(result["source_count"] >= 2) | (result["review_source_count"] >= 2), "priority"] = "HIGH"
    result.loc[(result["priority"] == "LOW") & (result["review_source_count"] > 0), "priority"] = "MEDIUM"
    return result


def build_baseline_comparison(evidence: pd.DataFrame) -> pd.DataFrame:
    tiers = {
        "Baseline A": {"PRODUCT_FACT", "NUTRITION_DB_PRODUCT_FACT"},
        "Baseline B": {"PRODUCT_FACT", "NUTRITION_DB_PRODUCT_FACT", "SELLER_PRODUCT_EVIDENCE"},
        "Extended C": {"PRODUCT_FACT", "NUTRITION_DB_PRODUCT_FACT", "SELLER_PRODUCT_EVIDENCE", "KOREAN_CONSUMER_SEARCH_EVIDENCE", "KOREAN_HFF_PURCHASE_AGGREGATE", "KOREAN_CONSUMER_AGGREGATE"},
        "Reference D": {"PRODUCT_FACT", "NUTRITION_DB_PRODUCT_FACT", "SELLER_PRODUCT_EVIDENCE", "KOREAN_CONSUMER_SEARCH_EVIDENCE", "KOREAN_HFF_PURCHASE_AGGREGATE", "KOREAN_CONSUMER_AGGREGATE", "FOREIGN_CONSUMER_SEARCH_REFERENCE", "KOREAN_EXPRESSION_REFERENCE"},
    }
    rows = []
    for name, source_types in tiers.items():
        subset = evidence[evidence["source_type"].isin(source_types)]
        current = aggregate_evidence(subset)
        rows.append({
            "baseline": name,
            "candidate_count": len(current),
            "product_supported_candidate_count": int(((current.get("mfds_support", 0) > 0) | (current.get("nutrition_db_support", 0) > 0)).sum()) if not current.empty else 0,
            "korean_market_supported_count": int(((current.get("seller_support", 0) > 0) | (current.get("korean_search_support", 0) > 0) | (current.get("korean_purchase_support", 0) > 0) | (current.get("korean_consumer_aggregate_support", 0) > 0)).sum()) if not current.empty else 0,
            "foreign_only_count": int(current["foreign_only_flag"].sum()) if not current.empty else 0,
            "source_2plus_supported": int((current["source_count"] >= 2).sum()) if not current.empty else 0,
            "source_3plus_supported": int((current["source_count"] >= 3).sum()) if not current.empty else 0,
        })
    return pd.DataFrame(rows)


def build_audit(evidence: pd.DataFrame, aggregate: pd.DataFrame, source_status: list[dict[str, Any]], baseline: pd.DataFrame | None = None) -> str:
    counts = evidence["source_type"].value_counts().to_dict() if not evidence.empty else {}
    lines = ["# KOREAN HFF MODEL 1 DATA RESULT", "", "## Existing Product Data", f"- MFDS evidence rows: {counts.get('PRODUCT_FACT', 0)}", f"- Seller evidence rows: {counts.get('SELLER_PRODUCT_EVIDENCE', 0)}", f"- Service categories represented: {evidence['category'].nunique() if not evidence.empty else 0}", "", "## Source Status"]
    for item in source_status:
        lines.append(f"- {item['source']} [{item.get('source_type', '')}]: {item['status']} ({item['rows']} rows)")
    lines += ["", "## Facet Candidates", f"- Candidate rows: {len(aggregate)}", f"- New Facet candidates: {int(aggregate['new_facet_candidate'].sum()) if not aggregate.empty else 0}", f"- Source 2+ support: {int((aggregate['source_count'] >= 2).sum()) if not aggregate.empty else 0}", f"- Source 3+ support: {int((aggregate['source_count'] >= 3).sum()) if not aggregate.empty else 0}", f"- Foreign-only candidates: {int(aggregate['foreign_only_flag'].sum()) if not aggregate.empty else 0}", "- Existing taxonomy is not automatically changed."]
    if baseline is not None and not baseline.empty:
        lines += ["", "## Baseline Comparison", baseline.to_csv(index=False).strip()]
    lines += ["", "## Limitations", "- Purchase data is aggregate evidence, not individual Korean order logs.", "- NAVER Shopping Insight ratio is relative click trend, not absolute search volume.", "- KuaiSearch is Chinese reference data.", "- AI-Hub is not a health-functional-food-only review corpus.", "- Korean health-functional-food review data is NOT_AVAILABLE under the current access policy.", "- Missing or unknown license information is not inferred as permission.", "- Human review is required before taxonomy or alias approval."]
    return "\n".join(lines) + "\n"


def run_pipeline(root: Path, output_dir: Path, enable_reviews: bool = False, max_reviews_per_product: int | None = None) -> dict[str, Any]:
    """Run the Korean HFF evidence pipeline without synthetic or foreign ecommerce facts."""
    del enable_reviews
    output_dir.mkdir(parents=True, exist_ok=True)
    mfds = root / "data/interim/facet_discovery/i0030_products_clean_dedup.csv"
    mapping = root / "data/processed/category_v2_1_current/product_service_category_mapping_v2_1.csv"
    evidence: list[pd.DataFrame] = []
    statuses: list[dict[str, Any]] = []

    mfds_frame = build_mfds(mfds, mapping) if mfds.exists() else _empty()
    evidence.append(mfds_frame)
    statuses.append({"source": "mfds", "source_type": "PRODUCT_FACT", "status": "AVAILABLE" if mfds.exists() else "NOT_ACQUIRED", "rows": len(mfds_frame)})

    nutrition = root / "data/raw/facet_evidence/nutrition_db"
    nutrition_frame = _empty()
    statuses.append({"source": "nutrition_db", "source_type": "NUTRITION_DB_PRODUCT_FACT", "status": "NOT_AVAILABLE" if not nutrition.exists() else "ADAPTER_PENDING", "rows": len(nutrition_frame)})

    seller = root / "data/processed/domeggook/seller_offers_core.csv"
    seller_frame = build_seller(seller) if seller.exists() else _empty()
    evidence.append(seller_frame)
    statuses.append({"source": "domeggook", "source_type": "SELLER_PRODUCT_EVIDENCE", "status": "AVAILABLE" if seller.exists() else "NOT_ACQUIRED", "rows": len(seller_frame)})

    kuai = root / "data/raw/consumer_reference/kuaisearch"
    kuai_translation = root / "data/interim/facet_evidence/kuaiseach_health_queries_ko_reviewed_v27.parquet"
    kuai_frame = build_kuaisearch_reference(kuai_translation)
    evidence.append(kuai_frame)
    statuses.append({"source": "kuaisearch", "source_type": "FOREIGN_CONSUMER_SEARCH_REFERENCE", "status": "AVAILABLE_TRANSLATED_REFERENCE" if not kuai_frame.empty else "NOT_ACQUIRED", "rows": len(kuai_frame), "raw_log_scan": False})

    naver_path = root / "data/processed/facet_discovery/naver_shopping_insight/naver_facet_keyword_trends_preview.csv"
    naver_frame = build_naver_trends(naver_path)
    evidence.append(naver_frame)
    statuses.append({"source": "naver_shopping_insight", "source_type": "KOREAN_CONSUMER_SEARCH_EVIDENCE", "status": "AVAILABLE" if not naver_frame.empty else "NOT_AVAILABLE", "rows": len(naver_frame)})

    aihub = root / "data/interim/facet_discovery/aihub_repeated_terms.csv"
    aihub_frame = build_aihub(aihub)
    evidence.append(aihub_frame)
    statuses.append({"source": "aihub", "source_type": "KOREAN_EXPRESSION_REFERENCE", "status": "AVAILABLE_EXPRESSION_REFERENCE" if aihub.exists() else "NOT_AVAILABLE", "rows": len(aihub_frame)})

    lgu_purchase_path = root / "data/processed/purchase/lg_uplus_aggregate.parquet"
    lgu_purchase_frame = build_lgu_purchase_evidence(lgu_purchase_path)
    evidence.append(lgu_purchase_frame)
    purchase_metrics = read_optional_aggregate(root / "data/raw/facet_evidence/lgu_hff", "lgu_hff", "KOREAN_HFF_PURCHASE_AGGREGATE")
    consumer_metrics = read_optional_aggregate(root / "data/raw/facet_evidence/korean_consumer_aggregate", "korean_consumer_aggregate", "KOREAN_CONSUMER_AGGREGATE")
    pd.concat([purchase_metrics, consumer_metrics], ignore_index=True).to_csv(output_dir / "consumer_aggregate_metrics.csv", index=False, encoding="utf-8-sig")
    statuses.append({"source": "lgu_uplus", "source_type": "KOREAN_HFF_PURCHASE_AGGREGATE", "status": "AVAILABLE" if not lgu_purchase_frame.empty else "NOT_AVAILABLE", "rows": len(lgu_purchase_frame), "raw_path": str(lgu_purchase_path)})
    statuses.append({"source": "korean_consumer_aggregate", "source_type": "KOREAN_CONSUMER_AGGREGATE", "status": "AVAILABLE" if not consumer_metrics.empty else "NOT_AVAILABLE", "rows": len(consumer_metrics)})
    review_paths = {
        "nutrime": sorted((root / "data/raw/reviews/nutrime").glob("*.jsonl")),
        "chongkundang": sorted((root / "data/raw/reviews/chongkundang").glob("*.jsonl")),
    }
    for source, paths in review_paths.items():
        path = paths[-1] if paths else root / f"data/raw/reviews/{source}/missing.jsonl"
        review_frame, review_stats = build_review_evidence(path, source, max_reviews_per_product=max_reviews_per_product)
        evidence.append(review_frame)
        statuses.append({"source": source, "source_type": "KOREAN_HFF_RAW_REVIEW", "status": "AVAILABLE" if review_stats["review_count"] else "BLOCKED_OR_EMPTY", "rows": len(review_frame), "review_count": review_stats["review_count"], "sampled_review_count": review_stats["sampled_review_count"], "mapped_count": review_stats["mapped_count"], "medical_outcome_sentence_count": review_stats["medical_outcome_sentence_count"]})

    unified = pd.concat(evidence, ignore_index=True) if evidence else _empty()
    aggregate = aggregate_evidence(unified)
    review = build_review_queue(aggregate, unified)
    unified.to_parquet(output_dir / "facet_evidence_unified.parquet", index=False)
    unified.to_csv(output_dir / "facet_evidence_unified_preview.csv", index=False, encoding="utf-8-sig")
    aggregate.to_csv(output_dir / "facet_cross_source_evidence.csv", index=False, encoding="utf-8-sig")
    review.to_csv(output_dir / "facet_review_queue_v2.csv", index=False, encoding="utf-8-sig")
    baseline = build_baseline_comparison(unified)
    baseline.to_csv(output_dir / "facet_baseline_comparison_v1.csv", index=False, encoding="utf-8-sig")
    (output_dir / "facet_candidates_v1.json").write_text(json.dumps({"version": "v2", "status": "REVIEW", "candidates": aggregate.to_dict(orient="records")}, ensure_ascii=False, indent=2), encoding="utf-8")
    report_dir = root / "data/reports/facet_discovery"
    report_dir.mkdir(parents=True, exist_ok=True)
    license_rows = [{"source": item["source"], "official_url": SOURCE_LICENSES.get(item["source"], ("", "UNKNOWN"))[0], "license_status": SOURCE_LICENSES.get(item["source"], ("", "UNKNOWN"))[1], "raw_redistribution": "UNKNOWN", "processed_use": "UNKNOWN", "github_raw_allowed": "false", "local_only": True, "notes": item["status"]} for item in statuses]
    pd.DataFrame(license_rows).to_csv(report_dir / "source_access_license_audit.csv", index=False, encoding="utf-8-sig")
    (report_dir / "KOREAN_HFF_MODEL1_DATA_RESULT.md").write_text(build_audit(unified, aggregate, statuses, baseline), encoding="utf-8")
    return {"status": "COMPLETED", "evidence_rows": len(unified), "candidate_rows": len(aggregate), "review_rows": len(review), "sources": statuses}
