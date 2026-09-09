"""Build a blinded, directional review set for MFDS function coverage."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

import pandas as pd

from ..substitute_admission import character_ngram_cosine_similarity


REVIEW_LABELS = ("COVERS", "DOES_NOT_COVER", "INSUFFICIENT_EVIDENCE")
SAMPLING_STRATA = (
    "BOILERPLATE_TRAP",
    "LEXICAL_NEAR",
    "DIRECTIONAL_SPECIFICITY",
    "LOW_SIMILARITY_CONTROL",
)


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}-{digest}"


def function_claim_id(claim_key: str) -> str:
    """Return the stable relation-universe ID for one normalized claim key."""

    normalized = _text(claim_key)
    if not normalized:
        raise ValueError("claim_key must not be blank")
    return _stable_id("MFDS-FCLAIM", normalized)


def _focus_key(value: object) -> str:
    """Remove common claim boilerplate for sampling diagnostics only."""

    text = re.sub(r"[^0-9가-힣]+", "", _text(value).casefold())
    patterns = (
        r"(?:에|하는데)?도움을?줄수있(?:음|습니다)",
        r"도움이?될수있음|도움을?줌",
        r"(?:에)?필요함?$",
        r"(?:에)?관여$",
    )
    for pattern in patterns:
        text = re.sub(pattern, "", text)
    return text


def _aggregate_claims(claims: pd.DataFrame) -> list[dict[str, str]]:
    required = {
        "claim_key_candidate",
        "claim_text_candidate",
        "source_reference_names",
    }
    if missing := sorted(required - set(claims.columns)):
        raise ValueError(f"claim frame missing columns: {', '.join(missing)}")

    rows: list[dict[str, str]] = []
    for claim_key, group in claims.fillna("").groupby(
        "claim_key_candidate",
        sort=True,
    ):
        if not _text(claim_key):
            continue
        texts = sorted(
            {_text(value) for value in group["claim_text_candidate"] if _text(value)},
            key=lambda value: (len(value), value),
        )
        reference_names = sorted({
            name
            for value in group["source_reference_names"]
            for name in _text(value).split(" | ")
            if name
        })
        rows.append({
            "claim_id": function_claim_id(claim_key),
            "claim_key": claim_key,
            "claim_text": texts[0],
            "focus_key": _focus_key(claim_key),
            "reference_names": " | ".join(reference_names),
        })
    return rows


def build_function_claim_index(claims: pd.DataFrame) -> pd.DataFrame:
    """Return the stable 190-claim index used by offline retrieval evaluation."""

    rows = _aggregate_claims(claims)
    return pd.DataFrame([
        {
            "claim_id": row["claim_id"],
            "claim_text": row["claim_text"],
        }
        for row in rows
    ]).sort_values("claim_id", kind="stable").reset_index(drop=True)


def _stratum(
    lexical_score: float,
    focus_score: float,
    left_focus: str,
    right_focus: str,
) -> str:
    if lexical_score >= 0.78 and focus_score <= 0.55:
        return "BOILERPLATE_TRAP"
    if lexical_score >= 0.84 and focus_score > 0.55:
        return "LEXICAL_NEAR"
    if (
        min(len(left_focus), len(right_focus)) >= 3
        and left_focus != right_focus
        and (left_focus in right_focus or right_focus in left_focus)
    ):
        return "DIRECTIONAL_SPECIFICITY"
    if lexical_score <= 0.25:
        return "LOW_SIMILARITY_CONTROL"
    return "OUT_OF_SAMPLE"


def build_function_relation_review_set(
    claims: pd.DataFrame,
    *,
    pairs_per_stratum: int = 30,
    seed: str = "mfds-function-relation-v1",
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return blinded review rows, private sampling audit, and manifest."""

    if pairs_per_stratum <= 0:
        raise ValueError("pairs_per_stratum must be positive")
    aggregated = _aggregate_claims(claims)
    pair_candidates: dict[str, list[dict[str, Any]]] = {
        stratum: [] for stratum in SAMPLING_STRATA
    }
    for left_index, left in enumerate(aggregated):
        for right in aggregated[left_index + 1:]:
            lexical_score = character_ngram_cosine_similarity(
                left["claim_key"],
                right["claim_key"],
            )
            focus_score = character_ngram_cosine_similarity(
                left["focus_key"],
                right["focus_key"],
            )
            stratum = _stratum(
                lexical_score,
                focus_score,
                left["focus_key"],
                right["focus_key"],
            )
            if stratum == "OUT_OF_SAMPLE":
                continue
            pair_key = "|".join(sorted((left["claim_id"], right["claim_id"])))
            pair_candidates[stratum].append({
                "pair_id": _stable_id("MFDS-FPAIR", pair_key),
                "pair_key": pair_key,
                "left": left,
                "right": right,
                "sampling_stratum": stratum,
                "character_bigram_similarity": round(lexical_score, 6),
                "focus_bigram_similarity": round(focus_score, 6),
                "selection_rank": hashlib.sha256(
                    f"{seed}|{stratum}|{pair_key}".encode("utf-8")
                ).hexdigest(),
            })

    selected: list[dict[str, Any]] = []
    selected_pair_ids: set[str] = set()
    available_counts: dict[str, int] = {}
    selected_counts: Counter[str] = Counter()
    for stratum in SAMPLING_STRATA:
        candidates = sorted(
            pair_candidates[stratum],
            key=lambda item: item["selection_rank"],
        )
        available_counts[stratum] = len(candidates)
        for candidate in candidates:
            if candidate["pair_id"] in selected_pair_ids:
                continue
            selected.append(candidate)
            selected_pair_ids.add(candidate["pair_id"])
            selected_counts[stratum] += 1
            if selected_counts[stratum] == pairs_per_stratum:
                break

    review_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for pair in sorted(selected, key=lambda item: item["pair_id"]):
        for source, candidate in (
            (pair["left"], pair["right"]),
            (pair["right"], pair["left"]),
        ):
            direction_key = f"{source['claim_id']}->{candidate['claim_id']}"
            direction_id = _stable_id("MFDS-FDIR", direction_key)
            review_rows.append({
                "direction_id": direction_id,
                "source_claim_id": source["claim_id"],
                "source_claim_text": source["claim_text"],
                "source_reference_names": source["reference_names"],
                "candidate_claim_id": candidate["claim_id"],
                "candidate_claim_text": candidate["claim_text"],
                "candidate_reference_names": candidate["reference_names"],
                "coverage_label": "",
                "reason_code": "",
                "reviewer_id": "",
                "review_note": "",
            })
            audit_rows.append({
                "direction_id": direction_id,
                "pair_id": pair["pair_id"],
                "sampling_stratum": pair["sampling_stratum"],
                "character_bigram_similarity": pair[
                    "character_bigram_similarity"
                ],
                "focus_bigram_similarity": pair["focus_bigram_similarity"],
                "source_focus_key": source["focus_key"],
                "candidate_focus_key": candidate["focus_key"],
                "sample_version": seed,
            })

    review = pd.DataFrame(review_rows).sort_values("direction_id")
    audit = pd.DataFrame(audit_rows).sort_values("direction_id")
    selected_counts_dict = {
        stratum: int(selected_counts[stratum]) for stratum in SAMPLING_STRATA
    }
    claim_fingerprint = hashlib.sha256(
        "\n".join(
            f"{row['claim_id']}|{row['claim_key']}|{row['reference_names']}"
            for row in aggregated
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schemaVersion": "mfds-function-relation-review.v1",
        "question": "Does candidate function B preserve the benefit and scope of source function A?",
        "allowedLabels": list(REVIEW_LABELS),
        "claimCount": len(aggregated),
        "claimFingerprintSha256": claim_fingerprint,
        "requestedPairsPerStratum": pairs_per_stratum,
        "availablePairCounts": available_counts,
        "selectedPairCounts": selected_counts_dict,
        "samplingStratumShortfalls": {
            stratum: max(0, pairs_per_stratum - selected_counts_dict[stratum])
            for stratum in SAMPLING_STRATA
        },
        "undirectedPairs": len(selected),
        "directedReviewRows": len(review),
        "blinding": (
            "Sampling strata and lexical scores are stored only in the audit "
            "file, not in the review file."
        ),
        "runtimePolicy": (
            "INSUFFICIENT_EVIDENCE is an offline label; production abstains "
            "without creating a REVIEW demand state."
        ),
    }
    return review, audit, manifest
