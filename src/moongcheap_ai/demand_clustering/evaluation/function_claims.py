"""Create review candidates for atomic MFDS health-function claims.

The output is deliberately a candidate inventory. Splitting a sentence does not
approve a service ontology code or a substitute-product relationship.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pandas as pd


ENGLISH_MARKER_RE = re.compile(r"\(?\s*영문\s*\)?", re.I)
DAILY_INTAKE_RE = re.compile(r"(?:\(\s*2\s*\)|②)\s*일일\s*섭취량")
INDIRECT_REFERENCE_RE = re.compile(r"에\s*따름|참조")
ENUMERATOR_RE = re.compile(
    r"(?:^|\s)(?:\(\s*(?:\d+|[가-힣])\s*\)|[①②③④⑤⑥⑦⑧⑨⑩]|"
    r"\d+[.)]\s*)\s*"
)
TERMINAL_COMMA_RE = re.compile(
    r"(도움을?\s*줄\s*수\s*있(?:음|습니다)|도움이?\s*될\s*수\s*있음|"
    r"도움을?\s*줌|필요|관여|작용)\s*,\s*"
)
TERMINAL_NEXT_CLAIM_RE = re.compile(
    r"(도움을?\s*줄\s*수\s*있(?:음|습니다)|도움이?\s*될\s*수\s*있음|"
    r"도움을?\s*줌|필요|관여|작용)\s*[.]?\s+(?=[가-힣])"
)
PREDICATE_RE = re.compile(
    r"도움|필요|관여|작용|개선|보충|증식|억제|원활|항산화|"
    r"적을\s*수\s*있음|구성성분|"
    r"균형\s*유지|운반과\s*저장"
)
TERMINAL_PREDICATE_RE = re.compile(r"도움|필요|관여|작용|적을\s*수\s*있음")
SHARED_SUFFIX_RE = re.compile(
    r"((?:에|하는데)\s*도움.*|에\s*필요.*|에\s*관여.*)$"
)
PROTECTED_MIDDOT_PHRASES = (
    "산화·환원",
    "기관·기관지",
)
PROTECTED_COMMA_PHRASES = (
    "지방, 탄수화물, 단백질",
    "탄수화물, 지방, 단백질",
    "근육, 결합조직 등",
    "효소, 호르몬, 항체",
    "체액, 산-염기",
    "에너지, 포도당, 지질",
)


def _text(value: object) -> str:
    return re.sub(
        r"\s+",
        " ",
        unicodedata.normalize("NFKC", str(value or "")),
    ).strip()


def _key(value: object) -> str:
    return re.sub(r"[^0-9가-힣]+", "", _text(value).casefold())


def function_claim_key(value: object) -> str:
    """Return the normalized key used by the 190-claim relation universe."""

    return _key(value)


def clean_korean_functionality(value: object) -> str:
    """Remove translation, dose, labels, and footnotes while preserving clauses."""

    text = str(value or "")
    for number, marker in enumerate("①②③④⑤⑥⑦⑧⑨⑩", start=1):
        text = text.replace(marker, f"({number})")
    text = unicodedata.normalize("NFKC", text)
    text = ENGLISH_MARKER_RE.split(text, maxsplit=1)[0]
    text = DAILY_INTAKE_RE.split(text, maxsplit=1)[0]
    text = text.split("※", 1)[0]
    text = re.sub(r"\(?\s*국문\s*\)?", " ", text)
    text = re.sub(r"기능성\s*내용\s*:", " ", text)
    text = re.sub(r"\[[^\]]*제조방법[^\]]*\]", " ", text)
    text = re.sub(
        r"\(\s*(?:생리활성기능(?:\s*\d등급[ⅠIⅡV]*)?|"
        r"기타\s*(?:기능)?\s*[ⅠIⅡV]+)\s*\)",
        " ",
        text,
    )
    text = text.replace("･", "·").replace("・", "·").replace("․", "·")
    return _text(text).strip("-·,.;: ")


def _protect_parenthetical_delimiters(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return (
            match.group(0)
            .replace("·", "<MIDDOT>")
            .replace(",", "<COMMA>")
        )

    return re.sub(r"\([^)]*\)", replace, text)


@dataclass(frozen=True)
class FunctionClaimExtraction:
    cleaned_functionality: str
    claims: tuple[str, ...]
    parse_status: str
    review_reasons: tuple[str, ...]
    extraction_rules: tuple[str, ...]


def extract_atomic_function_claims(value: object) -> FunctionClaimExtraction:
    """Split a reference function into auditable atomic-claim candidates."""

    cleaned = clean_korean_functionality(value)
    if not cleaned:
        return FunctionClaimExtraction(
            cleaned,
            (),
            "EMPTY",
            ("EMPTY_FUNCTION",),
            (),
        )
    if INDIRECT_REFERENCE_RE.search(cleaned):
        return FunctionClaimExtraction(
            cleaned,
            (),
            "INDIRECT_REFERENCE",
            ("REFERENCE_TARGET_REQUIRED",),
            (),
        )

    rules: list[str] = []
    protected = _protect_parenthetical_delimiters(cleaned)
    for phrase in PROTECTED_MIDDOT_PHRASES:
        protected = protected.replace(phrase, phrase.replace("·", "<MIDDOT>"))
    for phrase in PROTECTED_COMMA_PHRASES:
        protected = protected.replace(phrase, phrase.replace(",", "<COMMA>"))
    protected = re.sub(r"하여\s*,", "하여<COMMA>", protected)

    enumerated = ENUMERATOR_RE.sub(" || ", protected)
    if enumerated != protected:
        rules.append("ENUMERATOR")
    terminal_split = TERMINAL_COMMA_RE.sub(r"\1 || ", enumerated)
    if terminal_split != enumerated:
        rules.append("TERMINAL_COMMA")
    next_claim_split = TERMINAL_NEXT_CLAIM_RE.sub(r"\1 || ", terminal_split)
    if next_claim_split != terminal_split:
        rules.append("TERMINAL_NEXT_CLAIM")
    period_split = re.sub(
        r"(있음|있습니다|필요|관여|작용)\s*[.]\s*(?=[가-힣])",
        r"\1 || ",
        next_claim_split,
    )
    if period_split != next_claim_split:
        rules.append("PERIOD_LIST")
    spaced_period_split = re.sub(r"\s+[.]\s*(?=[가-힣])", " || ", period_split)
    if spaced_period_split != period_split:
        rules.append("SPACED_PERIOD_LIST")
    hyphen_split = re.sub(
        r"\s+-\s*(?=[가-힣])",
        " || ",
        spaced_period_split,
    )
    if hyphen_split != spaced_period_split:
        rules.append("HYPHEN_LIST")

    parts: list[str] = []
    for major_part in hyphen_split.split("||"):
        comma_split = re.sub(r"\s*,\s*", " | ", major_part)
        if comma_split != major_part:
            rules.append("COMMA_LIST")
        middot_split = re.sub(r"\s*·\s*", " | ", comma_split)
        if middot_split != comma_split:
            rules.append("MIDDOT_LIST")
        minor_parts = [
            _text(
                part.replace("<MIDDOT>", "·").replace("<COMMA>", ",")
            ).strip("-·,.;: ")
            for part in middot_split.split("|")
        ]
        minor_parts = [part for part in minor_parts if part]
        if not minor_parts:
            continue

        suffix_match = SHARED_SUFFIX_RE.search(minor_parts[-1])
        if suffix_match and len(minor_parts) > 1:
            shared_suffix = suffix_match.group(1)
            propagated: list[str] = []
            for part in minor_parts:
                if TERMINAL_PREDICATE_RE.search(part):
                    propagated.append(part)
                else:
                    propagated.append(f"{part}{shared_suffix}")
            if propagated != minor_parts:
                rules.append("SHARED_SUFFIX")
            minor_parts = propagated
        parts.extend(minor_parts)

    if not parts:
        return FunctionClaimExtraction(
            cleaned,
            (),
            "NEEDS_REVIEW",
            ("NO_CLAIM_AFTER_SPLIT",),
            tuple(rules),
        )

    deduplicated = tuple(dict.fromkeys(parts))
    reasons: list[str] = []
    if any(not PREDICATE_RE.search(part) for part in deduplicated):
        reasons.append("PREDICATE_NOT_DETECTED")
    if any(
        len(_key(part)) < 4 and _key(part) not in {"항산화"}
        for part in deduplicated
    ):
        reasons.append("CLAIM_TOO_SHORT")
    parse_status = "NEEDS_REVIEW" if reasons else (
        "PARSED_MULTI" if len(deduplicated) > 1 else "PARSED_SINGLE"
    )
    return FunctionClaimExtraction(
        cleaned,
        deduplicated,
        parse_status,
        tuple(reasons),
        tuple(dict.fromkeys(rules)),
    )


def _dereference_functions(references: pd.DataFrame) -> tuple[list[str], list[str]]:
    name_to_function = {
        _key(row["category_reference_name"]): str(row["main_functionality"] or "")
        for _, row in references.iterrows()
        if _key(row["category_reference_name"])
        and _text(row["main_functionality"])
        and not INDIRECT_REFERENCE_RE.search(_text(row["main_functionality"]))
    }
    resolved: list[str] = []
    targets: list[str] = []
    for _, row in references.iterrows():
        function_raw = str(row["main_functionality"] or "")
        function_normalized = _text(function_raw)
        if not INDIRECT_REFERENCE_RE.search(function_normalized):
            resolved.append(function_raw)
            targets.append("")
            continue
        prefix_key = _key(
            INDIRECT_REFERENCE_RE.split(function_normalized, maxsplit=1)[0]
        )
        candidates = [key for key in name_to_function if prefix_key.endswith(key)]
        if candidates:
            target_key = max(candidates, key=len)
            resolved.append(name_to_function[target_key])
            targets.append(target_key)
        else:
            resolved.append(function_raw)
            targets.append("")
    return resolved, targets


def build_function_claim_candidates(
    references: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return signature, atomic-claim candidate, and audit summary tables."""

    required = {"category_reference_name", "main_functionality"}
    if missing := sorted(required - set(references.columns)):
        raise ValueError(f"I2710 frame missing columns: {', '.join(missing)}")

    frame = references.fillna("").copy()
    frame["resolved_functionality"], frame["indirect_target_key"] = (
        _dereference_functions(frame)
    )
    frame["extraction"] = frame["resolved_functionality"].map(
        extract_atomic_function_claims
    )
    frame["signature_key"] = frame["extraction"].map(
        lambda extraction: "||".join(
            sorted(_key(claim) for claim in extraction.claims)
        )
    )

    signature_rows: list[dict[str, Any]] = []
    claim_rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for signature_key, group in frame.loc[frame["signature_key"].ne("")].groupby(
        "signature_key",
        sort=True,
    ):
        representative = group.iloc[0]
        extraction = representative["extraction"]
        group_extractions = group["extraction"].tolist()
        parse_status = (
            "NEEDS_REVIEW"
            if any(item.parse_status == "NEEDS_REVIEW" for item in group_extractions)
            else ("PARSED_MULTI" if len(extraction.claims) > 1 else "PARSED_SINGLE")
        )
        review_reasons = sorted({
            reason
            for item in group_extractions
            for reason in item.review_reasons
        })
        extraction_rules = sorted({
            rule
            for item in group_extractions
            for rule in item.extraction_rules
        })
        signature_id = "MFDS-FSIG-" + hashlib.sha256(
            signature_key.encode("utf-8")
        ).hexdigest()[:12].upper()
        reference_names = sorted(
            {
                _text(value)
                for value in group["category_reference_name"]
                if _text(value)
            }
        )
        status_counts[parse_status] += 1
        signature_rows.append({
            "function_signature_id": signature_id,
            "function_signature_text": " | ".join(extraction.claims),
            "reference_count": len(group),
            "source_reference_names": " | ".join(reference_names),
            "claim_count_candidate": len(extraction.claims),
            "parse_status": parse_status,
            "review_reasons": "|".join(review_reasons),
            "extraction_rules": "|".join(extraction_rules),
            "uses_dereferenced_function": bool(
                group["indirect_target_key"].map(_text).ne("").any()
            ),
            "review_status": "NEEDS_HUMAN_APPROVAL",
        })
        for claim_index, claim in enumerate(extraction.claims, start=1):
            claim_rows.append({
                "function_signature_id": signature_id,
                "claim_index": claim_index,
                "claim_text_candidate": claim,
                "claim_key_candidate": function_claim_key(claim),
                "source_reference_count": len(group),
                "source_reference_names": " | ".join(reference_names),
                "signature_parse_status": parse_status,
                "review_status": "NEEDS_HUMAN_APPROVAL",
                "canonical_function_code": "",
            })

    signatures = pd.DataFrame(signature_rows).sort_values(
        ["parse_status", "reference_count", "function_signature_id"],
        ascending=[True, False, True],
    )
    claims = pd.DataFrame(claim_rows).sort_values(
        ["function_signature_id", "claim_index"]
    )
    summary = {
        "schemaVersion": "mfds-function-claim-candidates.v1",
        "referenceRows": len(frame),
        "emptyFunctionRows": int(frame["main_functionality"].map(_text).eq("").sum()),
        "indirectReferenceRows": int(
            frame["main_functionality"]
            .map(lambda value: bool(INDIRECT_REFERENCE_RE.search(_text(value))))
            .sum()
        ),
        "dereferencedRows": int(frame["indirect_target_key"].map(_text).ne("").sum()),
        "functionSignatures": len(signatures),
        "parseStatusCounts": dict(status_counts),
        "claimCandidateRows": len(claims),
        "uniqueClaimKeyCandidates": int(claims["claim_key_candidate"].nunique()),
        "reviewPolicy": (
            "Every extracted claim remains NEEDS_HUMAN_APPROVAL; no ontology or "
            "substitute relation is approved by this script."
        ),
    }
    return signatures, claims, summary
