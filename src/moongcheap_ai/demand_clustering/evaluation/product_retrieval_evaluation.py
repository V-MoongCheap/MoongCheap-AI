"""Evaluate bounded CPU product retrieval against the exhaustive hard gate."""

from __future__ import annotations

import json
from typing import Any, Iterable

import pandas as pd

from ..profile_contract import SUBSTITUTION_EVIDENCE_READY_STATUSES


PROFILE_COLUMNS = {
    "catalog_id",
    "service_category_id",
    "profile_status",
    "functional_ingredients_json",
    "main_functionality_claim_texts_json",
    "product_form",
}
PAIR_COLUMNS = {
    "source_catalog_id",
    "candidate_catalog_id",
    "coverage_mode",
}
SCORE_COLUMNS = {"source_catalog_id", "candidate_catalog_id", "score"}


def _json_strings(value: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as error:
        raise ValueError("profile JSON fields must contain arrays") from error
    if not isinstance(parsed, list):
        raise ValueError("profile JSON fields must contain arrays")
    return tuple(str(item).strip() for item in parsed if str(item).strip())


def build_product_retrieval_texts(
    profiles: pd.DataFrame,
    *,
    text_mode: str,
) -> pd.DataFrame:
    """Return deterministic function-focused text for CPU retrieval."""

    if missing := sorted(PROFILE_COLUMNS - set(profiles.columns)):
        raise ValueError("profiles missing columns: " + ", ".join(missing))
    if text_mode not in {"FUNCTION_ONLY", "FUNCTION_INGREDIENT_FORM"}:
        raise ValueError(f"unknown product retrieval text mode: {text_mode}")
    ready = profiles.fillna("").loc[
        profiles["profile_status"].isin(
            SUBSTITUTION_EVIDENCE_READY_STATUSES
        )
    ].copy()
    if ready["catalog_id"].duplicated().any():
        raise ValueError("profile catalog IDs must be unique")

    rows = []
    for row in ready.sort_values("catalog_id").itertuples(index=False):
        claims = _json_strings(row.main_functionality_claim_texts_json)
        if not claims:
            raise ValueError("candidate-ready profiles require function claims")
        lines = ["주기능: " + " | ".join(claims)]
        if text_mode == "FUNCTION_INGREDIENT_FORM":
            ingredients = _json_strings(row.functional_ingredients_json)
            lines.extend((
                "기능성 원료: " + " | ".join(ingredients),
                "제품 형태: " + str(row.product_form).strip(),
            ))
        rows.append({
            "catalog_id": str(row.catalog_id),
            "service_category_id": str(row.service_category_id),
            "retrieval_text": "\n".join(lines),
        })
    return pd.DataFrame(rows)


def evaluate_product_retrieval(
    retrieval_profiles: pd.DataFrame,
    eligible_pairs: pd.DataFrame,
    scores: pd.DataFrame,
    *,
    top_ks: Iterable[int] = (1, 3, 5, 10, 20),
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Measure pre-gate retrieval recall and post-gate candidate availability."""

    required_profiles = {"catalog_id", "service_category_id"}
    if missing := sorted(required_profiles - set(retrieval_profiles.columns)):
        raise ValueError("retrieval profiles missing columns: " + ", ".join(missing))
    if missing := sorted(PAIR_COLUMNS - set(eligible_pairs.columns)):
        raise ValueError("eligible pairs missing columns: " + ", ".join(missing))
    if missing := sorted(SCORE_COLUMNS - set(scores.columns)):
        raise ValueError("scores missing columns: " + ", ".join(missing))
    ks = tuple(sorted(set(int(value) for value in top_ks)))
    if not ks or ks[0] <= 0:
        raise ValueError("top_ks must contain positive integers")

    profiles = retrieval_profiles.fillna("").copy()
    profile_ids = set(profiles["catalog_id"].astype(str))
    pairs = eligible_pairs.fillna("").copy()
    pair_keys = set(zip(
        pairs["source_catalog_id"].astype(str),
        pairs["candidate_catalog_id"].astype(str),
        strict=True,
    ))
    if unknown := sorted(
        (
            set(pairs["source_catalog_id"].astype(str))
            | set(pairs["candidate_catalog_id"].astype(str))
        ) - profile_ids
    ):
        raise ValueError("eligible pairs contain unknown catalogs: " + ", ".join(unknown))
    pair_mode = {
        (str(row.source_catalog_id), str(row.candidate_catalog_id)): str(
            row.coverage_mode
        )
        for row in pairs.itertuples(index=False)
    }
    eligible_by_source = {
        source_id: set(group["candidate_catalog_id"].astype(str))
        for source_id, group in pairs.groupby("source_catalog_id", sort=True)
    }
    identity_sources = set(
        pairs.loc[
            pairs["coverage_mode"].eq("IDENTITY_ONLY"),
            "source_catalog_id",
        ].astype(str)
    )
    relation_sources = set(
        pairs.loc[
            pairs["coverage_mode"].eq("RELATION_ASSISTED"),
            "source_catalog_id",
        ].astype(str)
    )
    relation_rescued_sources = relation_sources - identity_sources

    normalized_scores = scores.fillna("").copy()
    normalized_scores["source_catalog_id"] = normalized_scores[
        "source_catalog_id"
    ].astype(str)
    normalized_scores["candidate_catalog_id"] = normalized_scores[
        "candidate_catalog_id"
    ].astype(str)
    normalized_scores["score"] = pd.to_numeric(
        normalized_scores["score"],
        errors="raise",
    )
    if normalized_scores[[
        "source_catalog_id",
        "candidate_catalog_id",
    ]].duplicated().any():
        raise ValueError("retrieval scores must contain unique directed pairs")
    categories = profiles.set_index("catalog_id")["service_category_id"].to_dict()
    expected_keys = {
        (source_id, candidate_id)
        for source_id in profile_ids
        for candidate_id in profile_ids
        if source_id != candidate_id
        and categories[source_id] == categories[candidate_id]
    }
    actual_keys = set(zip(
        normalized_scores["source_catalog_id"],
        normalized_scores["candidate_catalog_id"],
        strict=True,
    ))
    if actual_keys != expected_keys:
        raise ValueError("retrieval scores must cover every same-category direction")

    ranked_rows = []
    source_rows = []
    max_k = max(ks)
    for source_id in sorted(profile_ids):
        source_scores = normalized_scores.loc[
            normalized_scores["source_catalog_id"].eq(source_id)
        ].sort_values(
            ["score", "candidate_catalog_id"],
            ascending=[False, True],
            kind="stable",
        ).reset_index(drop=True)
        source_scores["rank"] = range(1, len(source_scores) + 1)
        source_eligible = eligible_by_source.get(source_id, set())
        eligible_ranks = source_scores.loc[
            source_scores["candidate_catalog_id"].isin(source_eligible),
            "rank",
        ]
        source_row: dict[str, Any] = {
            "source_catalog_id": source_id,
            "service_category_id": categories[source_id],
            "eligible_candidate_count": len(source_eligible),
            "first_eligible_rank": (
                int(eligible_ranks.min()) if len(eligible_ranks) else None
            ),
            "relation_rescued_source": source_id in relation_rescued_sources,
        }
        for k in ks:
            top = source_scores.head(k)
            survivor_count = int(
                top["candidate_catalog_id"].isin(source_eligible).sum()
            )
            source_row[f"eligible_in_top_{k}"] = survivor_count
            source_row[f"hit_at_{k}"] = survivor_count > 0
        source_rows.append(source_row)

        for row in source_scores.head(max_k).itertuples(index=False):
            key = (source_id, row.candidate_catalog_id)
            ranked_rows.append({
                "source_catalog_id": source_id,
                "candidate_catalog_id": row.candidate_catalog_id,
                "service_category_id": categories[source_id],
                "rank": int(row.rank),
                "score": round(float(row.score), 8),
                "hard_gate_eligible": key in pair_keys,
                "coverage_mode": pair_mode.get(key, "NOT_COVERED"),
            })

    source_summary = pd.DataFrame(source_rows)
    top_candidates = pd.DataFrame(ranked_rows)
    eligible_sources = source_summary["eligible_candidate_count"].gt(0)
    relation_rescued = source_summary["relation_rescued_source"]
    metrics_by_k = {}
    for k in ks:
        hit = source_summary[f"hit_at_{k}"]
        retrieved = top_candidates["rank"].le(k)
        metrics_by_k[str(k)] = {
            "eligibleSourceHitCount": int((eligible_sources & hit).sum()),
            "eligibleSourceHitRate": round(
                float(hit.loc[eligible_sources].mean()),
                6,
            ) if eligible_sources.any() else 0.0,
            "allReadySourceWithCandidateRate": round(float(hit.mean()), 6),
            "relationRescuedSourceHitCount": int((relation_rescued & hit).sum()),
            "relationRescuedSourceHitRate": round(
                float(hit.loc[relation_rescued].mean()),
                6,
            ) if relation_rescued.any() else 0.0,
            "retrievedDirections": int(retrieved.sum()),
            "hardGateEligibleDirections": int(
                top_candidates.loc[retrieved, "hard_gate_eligible"].sum()
            ),
            "hardGateEligibleDensity": round(
                float(
                    top_candidates.loc[retrieved, "hard_gate_eligible"].mean()
                ),
                6,
            ) if retrieved.any() else 0.0,
            "eligiblePairRecall": round(
                float(
                    top_candidates.loc[retrieved, "hard_gate_eligible"].sum()
                    / len(pairs)
                ),
                6,
            ) if len(pairs) else 0.0,
        }
    first_ranks = source_summary.loc[eligible_sources, "first_eligible_rank"].astype(int)
    summary = {
        "schemaVersion": "product-retrieval-evaluation.v1",
        "readySources": len(source_summary),
        "eligibleSources": int(eligible_sources.sum()),
        "relationRescuedSources": int(relation_rescued.sum()),
        "eligibleDirectedPairs": len(pairs),
        "firstEligibleRank": {
            "min": int(first_ranks.min()) if len(first_ranks) else 0,
            "median": float(first_ranks.median()) if len(first_ranks) else 0,
            "p90": float(first_ranks.quantile(0.9)) if len(first_ranks) else 0,
            "max": int(first_ranks.max()) if len(first_ranks) else 0,
        },
        "metricsByK": metrics_by_k,
        "interpretation": (
            "Retrieval proposes no product by itself. Scores create a bounded "
            "pool; the approved directional relation registry remains the hard gate."
        ),
    }
    return top_candidates, source_summary, summary
