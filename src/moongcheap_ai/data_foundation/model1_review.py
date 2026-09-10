"""Deterministic review gates for multi-source Model 1 facet candidates."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


def _u(value: str) -> str:
    if "\\u" in value:
        return re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match.group(1), 16)), value)
    return value


FACET_MAP = {
    "product form": ("product_form", "PRODUCT"), _u("\uc81c\ud488 \ud615\ud0dc"): ("product_form", "PRODUCT"),
    "functional ingredients": ("functional_ingredients", "PRODUCT"), _u("\uae30\ub2a5\uc131 \uc131\ubd84"): ("functional_ingredients", "PRODUCT"),
    "regulated function": ("regulated_function", "EVIDENCE_ONLY"), _u("\uaddc\uc81c \uae30\ub2a5"): ("regulated_function", "EVIDENCE_ONLY"),
    "intake method": ("intake_method", "PRODUCT"), _u("\uc12d\ucde8 \ubc29\ubc95"): ("intake_method", "PRODUCT"),
    "price band": ("price_band", "DEMAND"), _u("\uac00\uaca9\ub300"): ("price_band", "DEMAND"),
    "consumer preference": ("consumer_preference", "DEMAND_SIGNAL"), "purchase intent": ("purchase_intent", "DEMAND_SIGNAL"),
}
FORM_MAP = {"powder": "powder", _u("\ubd84\ub9d0"): "powder", "tablet": "tablet", _u("\uc815"): "tablet", _u("\uc815\uc81c"): "tablet", "capsule": "capsule", _u("\ucea1\uc290"): "capsule", "liquid": "liquid", _u("\uc561\uc0c1"): "liquid", "stick": "stick", _u("\uc2a4\ud2f1"): "stick"}
FORM_MAP[_u("\ud658")] = "pill"
CATEGORY_NAMES = {
    "health-functional-food:vitamin_mineral": _u("\ube44\ud0c0\ubbfc\u00b7\ubbf8\ub124\ub784"),
    "health-functional-food:probiotics": _u("\uc720\uc0b0\uade0\u00b7\ud504\ub85c\ubc14\uc774\uc624\ud2f1\uc2a4"),
    "health-functional-food:skin_collagen": _u("\ud53c\ubd80\u00b7\ucf5c\ub77c\uac94"),
}
OUT_OF_SCOPE = tuple(_u(value) for value in ("\uc57d", "\uc758\uc57d", "\uce58\ub8cc", "\uc9c8\ud658", "\ucc98\ubc29", "\uc54c\ub808\ub974\uae30", "\ud558\uc774\ub4dc\ub85c\uac94", "\uc5d0\uc13c\uc2a4")) + ("medicine", "drug", "treatment", "cosmetic")
RAW_SENTENCE_MARKERS = tuple(_u(value) for value in ("\ub3c4\uc6c0\uc744 \uc904", "\uc720\uc9c0\ud558\ub294\ub370", "\uac00\uc7a5 \uc88b\uc740", "\ud544\uc694", "\ucd94\ucc9c"))
REGULATED_CANONICAL_PATTERNS = (
    (re.compile(_u(r"\ud53c\ubd80\s*\ubcf4\uc2b5")), _u("\ud53c\ubd80 \ubcf4\uc2b5")),
    (re.compile(_u(r"\uc790\uc678\uc120.*\ud53c\ubd80.*\uac74\uac15|\ud53c\ubd80.*\uc790\uc678\uc120")), _u("\uc790\uc678\uc120 \ud53c\ubd80 \uac74\uac15")),
    (re.compile(_u(r"\ud608\uc911\s*\ucf5c\ub808\uc2a4\ud14c\ub864")), _u("\ud608\uc911 \ucf5c\ub808\uc2a4\ud14c\ub864")),
    (re.compile(_u(r"\ud608\ud589")), _u("\ud608\ud589")),
    (re.compile(_u(r"\uc6d4\uacbd\uc804")), _u("\uc6d4\uacbd\uc804 \ubd88\ud3b8")),
    (re.compile(_u(r"\uba74\uc5ed\uacfc\ubbfc\ubc18\uc751.*\ud53c\ubd80")), _u("\uba74\uc5ed\uacfc\ubbfc\ubc18\uc751 \ud53c\ubd80 \uc0c1\ud0dc")),
)
RECOGNITION_NUMBER_RE = re.compile(r"(?:\uae30\ub2a5\uc131\uc6d0\ub8cc\uc778\uc815\uc81c|\uc778\uc815\uc81c|\uc0dd\ub9ac\ud65c\uc131\uae30\ub2a5\s*)?(\d{4})\s*[-\u2013]\s*(\d+)\s*\ud638?", re.I)
INTAKE_RE = re.compile(r"(?:(\d+)\s*\uc77c\s*)?(?:(\d+)\s*\ud68c)?", re.I)
PRICE_RE = re.compile(r"^(?:UNDER_(\d+)|OVER_(\d+)|(\d+)_TO_(\d+))$", re.I)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().casefold()


def display_category_name(category_key: Any, fallback: Any = "") -> str:
    key = str(category_key or "").strip()
    return CATEGORY_NAMES.get(key, str(fallback or key))


def normalize_value(facet_id: str, value: Any) -> str:
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()
    if facet_id == "product_form":
        return FORM_MAP.get(text.casefold(), text)
    if facet_id == "functional_ingredients":
        text = re.sub(r"\s*\((?:" + _u("\ub610\ub294") + r"|or)\s*[^)]*\)", "", text, flags=re.I)
        text = re.sub(r"\s*\([^)]*(?:" + _u("\uae30\ub2a5\uc131") + r"|" + _u("\uc0dd\ub9ac\ud65c\uc131") + r")[^)]*\)", "", text, flags=re.I)
        text = re.sub(r"\s*\([^)]*\d{4}\s*[-\u2013]\s*\d+\s*\ud638?[^)]*\)", "", text, flags=re.I)
    if facet_id == "regulated_function":
        text = re.sub(_u(r"\(\s*\uad6d\ubb38\s*\)"), "", text, flags=re.I)
        text = re.sub(_u(r"\(\s*\uc601\ubb38\s*\).*"), "", text, flags=re.I)
        text = re.sub(r"\s+May help.*$", "", text, flags=re.I)
        text = re.sub(r"\s*\([^)]*\)", "", text)
    return text.strip()


def canonical_semantic_value(facet_id: str, value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if facet_id == "regulated_function":
        for pattern, canonical in REGULATED_CANONICAL_PATTERNS:
            if pattern.search(text):
                return canonical
    return text


def _contains(haystack: Any, needle: str) -> bool:
    return bool(needle) and needle in normalize_text(haystack)


def review_candidates(candidates: pd.DataFrame, inputs: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    input_frame = inputs.fillna("").copy()
    text_columns = [column for column in ("product_name", "product_form", "functional_ingredients", "regulated_function", "consumer_search_text", "intake_method", "price_text", "quantity_text", "seller_condition", "evidence_text") if column in input_frame.columns]
    normalized_input = input_frame[text_columns].astype(str).map(normalize_text) if text_columns else pd.DataFrame(index=input_frame.index)
    for _, candidate in candidates.fillna("").iterrows():
        raw_name = str(candidate.get("name", ""))
        facet_id, scope = FACET_MAP.get(normalize_text(raw_name), (normalize_text(raw_name).replace(" ", "_"), "UNKNOWN"))
        raw_value = str(candidate.get("value", ""))
        normalized = normalize_value(facet_id, raw_value)
        category = str(candidate.get("category_key", ""))
        category_rows = input_frame[input_frame["category_key"].astype(str).eq(category)] if "category_key" in input_frame else input_frame.iloc[0:0]
        category_normalized = normalized_input.loc[category_rows.index]
        needle = normalize_text(raw_value)
        matching_rows = category_rows[category_normalized.map(lambda value: needle in value if needle else False).any(axis=1)] if text_columns and not category_rows.empty else category_rows.iloc[0:0]
        evidence_matches = _contains(str(candidate.get("source_text", "")), normalize_text(raw_value))
        reasons: list[str] = []
        status = "ACCEPT_CANDIDATE"
        if scope == "UNKNOWN": status, reasons = "REVIEW_REQUIRED", ["unrecognized_facet"]
        if not normalized: status, reasons = "REJECT", reasons + ["empty_value"]
        if any(token in normalize_text(raw_value) for token in OUT_OF_SCOPE): status, reasons = "REJECT", reasons + ["out_of_scope_product_or_treatment_term"]
        if any(marker in raw_value for marker in RAW_SENTENCE_MARKERS): status, reasons = ("REVIEW_REQUIRED" if status != "REJECT" else status), reasons + ["raw_natural_language_sentence"]
        if scope == "EVIDENCE_ONLY": status, reasons = ("REVIEW_REQUIRED" if status != "REJECT" else status), reasons + ["regulated_function_is_evidence_only"]
        if scope in {"DEMAND", "DEMAND_SIGNAL"}: status, reasons = ("REVIEW_REQUIRED" if status != "REJECT" else status), reasons + ["demand_signal_not_product_facet"]
        if facet_id == "intake_method": status, reasons = ("REVIEW_REQUIRED" if status != "REJECT" else status), reasons + ["requires_structured_intake_parser"]
        if not evidence_matches: status, reasons = ("REVIEW_REQUIRED" if status != "REJECT" else status), reasons + ["evidence_text_mismatch"]
        if len(matching_rows) == 0: status, reasons = "REJECT", reasons + ["no_matching_input_row"]
        elif len(matching_rows) < 2 and status == "ACCEPT_CANDIDATE": status, reasons = "REVIEW_REQUIRED", reasons + ["single_observed_input_row"]
        rows.append({**candidate.to_dict(), "canonical_facet_id": facet_id, "normalized_value": normalized, "review_scope": scope, "input_match_count": int(len(matching_rows)), "evidence_text_matches_value": bool(evidence_matches), "review_status": status, "review_reasons": "|".join(dict.fromkeys(reasons)) or "passes_basic_gates"})
    return pd.DataFrame(rows)


def normalize_review_candidates(reviewed: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in reviewed.fillna("").iterrows():
        facet_id = str(row.get("canonical_facet_id", ""))
        raw_value = str(row.get("value", ""))
        value = str(row.get("normalized_value", raw_value))
        atoms = [part.strip(" .") for part in re.split(r"[,;·•\n]+", value) if part.strip(" .")] if facet_id in {"functional_ingredients", "regulated_function"} else [value]
        if facet_id == "regulated_function": atoms = [re.sub(r"^\s*[①-⑳\d.)]+\s*", "", part).strip() for part in atoms]
        atoms = [canonical_semantic_value(facet_id, atom) for atom in atoms]
        match = RECOGNITION_NUMBER_RE.search(raw_value)
        recognition = f"{match.group(1)}-{match.group(2)}" if match else ""
        intake_days = intake_frequency = ""
        if facet_id == "intake_method":
            intake_match = INTAKE_RE.fullmatch(value)
            if intake_match: intake_days, intake_frequency = intake_match.group(1) or "", intake_match.group(2) or ""
        price_min = price_max = ""
        if facet_id == "price_band":
            price_match = PRICE_RE.fullmatch(value)
            if price_match: price_min, price_max = (price_match.group(3) or price_match.group(2) or "0"), (price_match.group(1) or price_match.group(4) or "")
        for atom in atoms:
            rows.append({**row.to_dict(), "normalized_atom": atom, "recognition_number": recognition, "intake_days": intake_days, "intake_frequency": intake_frequency, "price_min": price_min, "price_max": price_max, "normalization_status": "PARSED" if atom else "EMPTY", "finalization_status": "EVIDENCE_ONLY" if facet_id == "regulated_function" else str(row.get("review_status", "REVIEW_REQUIRED"))})
    return pd.DataFrame(rows)


def collapse_same_model_candidates(normalized: pd.DataFrame) -> pd.DataFrame:
    """Collapse repeated evidence rows while retaining all source product IDs."""
    if normalized.empty:
        return normalized
    group_columns = ["model", "category_key", "canonical_facet_id", "normalized_atom"]
    rows: list[dict[str, Any]] = []
    for _, group in normalized.fillna("").groupby(group_columns, dropna=False, sort=True):
        row = group.iloc[0].to_dict()
        product_ids = sorted({str(value) for value in group["source_product_id"].astype(str) if str(value)})
        for column in ("source_text", "source_field", "evidence_source_type", "review_reasons"):
            values = sorted({str(value) for value in group[column].astype(str) if str(value)}) if column in group else []
            row[column] = " | ".join(values)
        row["source_product_id"] = " | ".join(product_ids)
        row["source_product_ids"] = row["source_product_id"]
        row["candidate_row_count"] = int(len(group))
        row["evidence_product_count"] = int(len(product_ids))
        rows.append(row)
    return pd.DataFrame(rows)


def build_review_queue(normalized: pd.DataFrame) -> pd.DataFrame:
    """Create one editable decision row per candidate, not per evidence record."""
    if normalized.empty:
        return pd.DataFrame(columns=["review_id", "category_name", "category_key", "facet_name", "facet_id", "facet_value", "model", "model_reason", "observed_data_reason", "review_status", "review_reason", "source_product_ids", "human_decision", "human_value", "human_note"])
    queue = normalized[normalized["review_status"].ne("ACCEPT_CANDIDATE")].copy()
    queue["review_id"] = queue.apply(lambda row: "|".join(str(row.get(column, "")) for column in ("model", "category_key", "canonical_facet_id", "normalized_atom")), axis=1)
    queue = queue.rename(columns={"name": "facet_name", "canonical_facet_id": "facet_id", "normalized_atom": "facet_value", "selection_reason": "model_reason", "data_selection_reason": "observed_data_reason", "review_reasons": "review_reason"})
    columns = ["review_id", "category_name", "category_key", "facet_name", "facet_id", "facet_value", "model", "model_reason", "observed_data_reason", "review_status", "review_reason", "source_product_ids", "human_decision", "human_value", "human_note"]
    for column in ("human_decision", "human_value", "human_note"):
        queue[column] = ""
    return queue.reindex(columns=columns).drop_duplicates("review_id").sort_values(["category_key", "facet_id", "facet_value", "model"], ignore_index=True)


def apply_human_decisions(queue: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Resolve editable queue decisions and return all rows plus accepted rows."""
    result = queue.fillna("").copy()
    allowed = {"ACCEPT", "REJECT", "DEFER", ""}
    result["human_decision"] = result["human_decision"].astype(str).str.strip().str.upper()
    invalid = sorted(set(result.loc[~result.human_decision.isin(allowed), "human_decision"]))
    if invalid:
        raise ValueError(f"Unsupported human_decision values: {invalid}; use ACCEPT, REJECT, or DEFER")
    result["resolved_value"] = result["human_value"].where(result["human_value"].ne(""), result["facet_value"])
    result["resolution_status"] = result["human_decision"].map({"ACCEPT": "ACCEPTED_BY_HUMAN", "REJECT": "REJECTED_BY_HUMAN", "DEFER": "DEFERRED", "": "UNREVIEWED"})
    return result, result[result["resolution_status"].eq("ACCEPTED_BY_HUMAN")].copy()


def write_review_artifacts(candidates_path: Path, input_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reviewed = review_candidates(pd.read_csv(candidates_path).fillna(""), pd.read_json(input_path, lines=True).fillna(""))
    reviewed.to_csv(output_dir / "multisource_candidate_review_v1.csv", index=False, encoding="utf-8-sig")
    summary = reviewed.groupby(["review_status", "review_scope"], dropna=False).size().reset_index(name="rows") if not reviewed.empty else pd.DataFrame(columns=["review_status", "review_scope", "rows"])
    summary.to_csv(output_dir / "multisource_candidate_review_summary_v1.csv", index=False, encoding="utf-8-sig")
    lines = ["# Multi-source Facet 후보 자동 검토 V1", "", "모델 출력 후보를 원본 입력과 대조한 결정론적 1차 검토 결과다.", "", "## 상태별 건수", "", "| 상태 | 건수 |", "|---|---:|"]
    for status, count in reviewed["review_status"].value_counts().items() if not reviewed.empty else []: lines.append(f"| {status} | {int(count)} |")
    lines += ["", "## 기준", "", "- 같은 Category의 입력 행에 후보 값이 실제로 존재하는지 확인", "- 증거 원문과 후보 값의 일치 여부 확인", "- 규제 기능은 근거로만 보존", "- 가격대·구매 의도는 Demand 신호로 분리", "- 범위 이탈 표현은 제외", "- 섭취 방법은 구조화 파서 검토 대상으로 분류"]
    (output_dir / "multisource_candidate_review_v1.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"rows": len(reviewed), "status_counts": reviewed["review_status"].value_counts().to_dict() if not reviewed.empty else {}}
