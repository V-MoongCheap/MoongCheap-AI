"""Offline retrieval metrics for adjudicated function-coverage relations."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pandas as pd


GOLD_COLUMNS = {
    "direction_id",
    "source_claim_id",
    "candidate_claim_id",
    "final_coverage_label",
}
SCORE_COLUMNS = {"source_claim_id", "candidate_claim_id", "score"}
CLAIM_COLUMNS = {"claim_id", "claim_text"}
KNOWN_RELATION_COLUMNS = {
    "source_claim_id",
    "candidate_claim_id",
    "final_coverage_label",
    "relation_artifact_eligible",
}


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    name: str,
) -> None:
    if missing := sorted(required - set(frame.columns)):
        raise ValueError(f"{name} missing columns: {', '.join(missing)}")


def _pairwise_auc(labels: pd.Series, scores: pd.Series) -> float | None:
    positives = scores.loc[labels].astype(float).tolist()
    negatives = scores.loc[~labels].astype(float).tolist()
    if not positives or not negatives:
        return None
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def evaluate_function_relation_retrieval(
    gold: pd.DataFrame,
    candidate_scores: pd.DataFrame,
    *,
    top_ks: tuple[int, ...] = (1, 3, 5, 10, 20),
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Evaluate judged-pair separation and known-positive retrieval ranks.

    Gold is intentionally sparse. Unjudged candidates are allowed to outrank a
    known positive, so recall and reciprocal-rank values are conservative
    diagnostics rather than complete-corpus recall estimates.
    """

    _require_columns(gold, GOLD_COLUMNS, "gold")
    _require_columns(candidate_scores, SCORE_COLUMNS, "candidate scores")
    if gold.empty:
        raise ValueError("gold must not be empty")
    if gold["direction_id"].duplicated().any():
        raise ValueError("gold direction_id must be unique")
    score_keys = ["source_claim_id", "candidate_claim_id"]
    if candidate_scores.duplicated(score_keys).any():
        raise ValueError("candidate score direction keys must be unique")
    if any(value <= 0 for value in top_ks) or not top_ks:
        raise ValueError("top_ks must contain positive integers")

    normalized_gold = gold.loc[:, sorted(GOLD_COLUMNS)].fillna("").copy()
    allowed_labels = {"COVERS", "DOES_NOT_COVER"}
    unknown_labels = sorted(
        set(normalized_gold["final_coverage_label"]) - allowed_labels
    )
    if unknown_labels:
        raise ValueError(
            "retrieval gold must contain only adjudicated binary labels: "
            + ", ".join(unknown_labels)
        )
    scores = candidate_scores.loc[:, list(SCORE_COLUMNS)].copy()
    scores["score"] = pd.to_numeric(scores["score"], errors="raise")
    judged = normalized_gold.merge(
        scores,
        on=score_keys,
        how="left",
        validate="one_to_one",
    )
    if judged["score"].isna().any():
        missing_ids = judged.loc[judged["score"].isna(), "direction_id"]
        raise ValueError(
            "candidate scores missing gold directions: "
            + ", ".join(missing_ids.astype(str))
        )

    is_positive = judged["final_coverage_label"].eq("COVERS")
    positive_gold = judged.loc[
        is_positive,
        ["direction_id", "source_claim_id", "candidate_claim_id", "score"],
    ].copy()
    rank_rows: list[dict[str, Any]] = []
    for row in positive_gold.itertuples(index=False):
        source_scores = scores.loc[
            scores["source_claim_id"].eq(row.source_claim_id)
        ].sort_values(
            ["score", "candidate_claim_id"],
            ascending=[False, True],
            kind="stable",
        )
        if source_scores.empty:
            raise ValueError(f"candidate scores missing source: {row.source_claim_id}")
        matches = source_scores["candidate_claim_id"].eq(row.candidate_claim_id)
        if not matches.any():
            raise ValueError(
                "candidate scores missing known positive: "
                f"{row.source_claim_id}->{row.candidate_claim_id}"
            )
        rank = int(matches.to_numpy().nonzero()[0][0]) + 1
        rank_rows.append({
            "direction_id": row.direction_id,
            "source_claim_id": row.source_claim_id,
            "candidate_claim_id": row.candidate_claim_id,
            "score": float(row.score),
            "rank": rank,
            "candidate_count": len(source_scores),
        })
    ranks = pd.DataFrame(rank_rows)
    positive_sources = sorted(set(positive_gold["source_claim_id"]))
    source_best_ranks = (
        ranks.groupby("source_claim_id")["rank"].min()
        if not ranks.empty
        else pd.Series(dtype=float)
    )
    auc = _pairwise_auc(is_positive, judged["score"])
    metrics = {
        "schemaVersion": "mfds-function-relation-retrieval-eval.v1",
        "judgedDirections": len(judged),
        "knownPositiveDirections": int(is_positive.sum()),
        "knownNegativeDirections": int((~is_positive).sum()),
        "positiveSourceClaims": len(positive_sources),
        "judgedDirectionRocAuc": None if auc is None else round(auc, 6),
        "meanKnownPositiveRank": (
            None if ranks.empty else round(float(ranks["rank"].mean()), 6)
        ),
        "meanReciprocalRankToFirstKnownPositive": (
            None
            if source_best_ranks.empty
            else round(float((1.0 / source_best_ranks).mean()), 6)
        ),
        "knownPositiveRecallAtK": {
            str(k): (
                None
                if ranks.empty
                else round(float(ranks["rank"].le(k).mean()), 6)
            )
            for k in sorted(set(top_ks))
        },
        "sourceHitAtK": {
            str(k): (
                None
                if source_best_ranks.empty
                else round(float(source_best_ranks.le(k).mean()), 6)
            )
            for k in sorted(set(top_ks))
        },
        "interpretation": (
            "Known-positive ranks are conservative diagnostics because only "
            "sampled pairs are adjudicated; candidates without labels are not "
            "treated as negatives."
        ),
    }
    return metrics, ranks


def evaluate_known_positive_rank_union(
    named_ranks: dict[str, pd.DataFrame],
    *,
    top_ks: tuple[int, ...] = (1, 3, 5, 10, 20),
) -> dict[str, Any]:
    """Return recall diagnostics for a union of equal-k retrieval lists."""

    if len(named_ranks) < 2:
        raise ValueError("rank union requires at least two retrievers")
    if any(value <= 0 for value in top_ks) or not top_ks:
        raise ValueError("top_ks must contain positive integers")
    required = {"direction_id", "source_claim_id", "candidate_claim_id", "rank"}
    merged: pd.DataFrame | None = None
    expected_keys: set[tuple[str, str, str]] | None = None
    for name, frame in sorted(named_ranks.items()):
        _require_columns(frame, required, f"{name} ranks")
        normalized = frame.loc[:, sorted(required)].fillna("").copy()
        if normalized["direction_id"].duplicated().any():
            raise ValueError(f"{name} direction_id must be unique")
        normalized["rank"] = pd.to_numeric(normalized["rank"], errors="raise")
        if normalized["rank"].le(0).any():
            raise ValueError(f"{name} ranks must be positive")
        keys = set(normalized[
            ["direction_id", "source_claim_id", "candidate_claim_id"]
        ].itertuples(index=False, name=None))
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise ValueError("retriever known-positive direction sets must match")
        renamed = normalized.rename(columns={"rank": f"{name}_rank"})
        join_columns = ["direction_id", "source_claim_id", "candidate_claim_id"]
        merged = (
            renamed
            if merged is None
            else merged.merge(
                renamed,
                on=join_columns,
                how="inner",
                validate="one_to_one",
            )
        )
    assert merged is not None
    rank_columns = [f"{name}_rank" for name in sorted(named_ranks)]
    positive_sources = merged["source_claim_id"].nunique()
    union: dict[str, dict[str, float | int | None]] = {}
    for k in sorted(set(top_ks)):
        hit = merged[rank_columns].le(k).any(axis=1)
        source_hit = hit.groupby(merged["source_claim_id"]).any()
        union[str(k)] = {
            "knownPositiveRecall": (
                None if merged.empty else round(float(hit.mean()), 6)
            ),
            "knownPositiveCount": int(hit.sum()),
            "sourceHit": (
                None if not positive_sources else round(float(source_hit.mean()), 6)
            ),
            "sourceCount": int(source_hit.sum()),
            "maxCandidateBudget": k * len(named_ranks),
        }
    return {
        "schemaVersion": "mfds-function-relation-rank-union.v1",
        "retrievers": sorted(named_ranks),
        "knownPositiveDirections": len(merged),
        "positiveSourceClaims": positive_sources,
        "unionAtK": union,
        "candidateBudgetInterpretation": (
            "Maximum before duplicate candidates across retrievers are removed."
        ),
    }


def _direction_id(source_claim_id: str, candidate_claim_id: str) -> str:
    key = f"{source_claim_id}->{candidate_claim_id}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16].upper()
    return f"MFDS-FDIR-{digest}"


def _eligible_bool(value: object) -> bool:
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"invalid relation_artifact_eligible value: {value!r}")


def build_function_relation_candidate_set(
    claims: pd.DataFrame,
    named_candidate_scores: dict[str, pd.DataFrame],
    known_relations: pd.DataFrame,
    *,
    top_k: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build a bounded union candidate set without treating scores as approval.

    Each retriever must score every directed, non-self pair in the claim index.
    Known adjudications are joined for reuse; unseen pairs remain explicitly
    marked for offline v3 review.
    """

    _require_columns(claims, CLAIM_COLUMNS, "claims")
    _require_columns(known_relations, KNOWN_RELATION_COLUMNS, "known relations")
    if claims.empty or claims["claim_id"].duplicated().any():
        raise ValueError("claims must contain unique claim IDs")
    if claims["claim_text"].fillna("").astype(str).str.strip().eq("").any():
        raise ValueError("claim text must not be blank")
    if len(named_candidate_scores) < 2:
        raise ValueError("candidate union requires at least two retrievers")
    if top_k <= 0 or top_k >= len(claims):
        raise ValueError("top_k must be between 1 and claim count minus 1")

    retriever_names = sorted(named_candidate_scores)
    if any(not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in retriever_names):
        raise ValueError("retriever names must match [a-z][a-z0-9_]*")
    claim_ids = claims["claim_id"].fillna("").astype(str).tolist()
    claim_id_set = set(claim_ids)
    expected_pairs = {
        (source_id, candidate_id)
        for source_id in claim_ids
        for candidate_id in claim_ids
        if source_id != candidate_id
    }
    score_keys = ["source_claim_id", "candidate_claim_id"]
    ranked_scores: dict[str, pd.DataFrame] = {}
    union_keys: set[tuple[str, str]] = set()
    for name in retriever_names:
        frame = named_candidate_scores[name]
        _require_columns(frame, SCORE_COLUMNS, f"{name} candidate scores")
        normalized = frame.loc[:, [*score_keys, "score"]].fillna("").copy()
        if normalized.duplicated(score_keys).any():
            raise ValueError(f"{name} candidate score direction keys must be unique")
        normalized["score"] = pd.to_numeric(normalized["score"], errors="raise")
        actual_pairs = set(normalized[score_keys].itertuples(index=False, name=None))
        if actual_pairs != expected_pairs:
            missing_count = len(expected_pairs - actual_pairs)
            extra_count = len(actual_pairs - expected_pairs)
            raise ValueError(
                f"{name} scores must cover every directed non-self pair "
                f"(missing={missing_count}, extra={extra_count})"
            )
        ranked = normalized.sort_values(
            ["source_claim_id", "score", "candidate_claim_id"],
            ascending=[True, False, True],
            kind="stable",
        )
        ranked[f"{name}_rank"] = (
            ranked.groupby("source_claim_id", sort=False).cumcount() + 1
        )
        ranked = ranked.rename(columns={"score": f"{name}_score"})
        ranked_scores[name] = ranked
        union_keys.update(
            ranked.loc[
                ranked[f"{name}_rank"].le(top_k),
                score_keys,
            ].itertuples(index=False, name=None)
        )

    candidates = pd.DataFrame(sorted(union_keys), columns=score_keys)
    for name in retriever_names:
        candidates = candidates.merge(
            ranked_scores[name],
            on=score_keys,
            how="left",
            validate="one_to_one",
        )
    candidates["retrieval_channels"] = candidates.apply(
        lambda row: " | ".join(
            name.upper()
            for name in retriever_names
            if int(row[f"{name}_rank"]) <= top_k
        ),
        axis=1,
    )
    candidates["retriever_count"] = candidates["retrieval_channels"].str.count(
        r" \| "
    ) + 1
    candidates["best_rank"] = candidates[
        [f"{name}_rank" for name in retriever_names]
    ].min(axis=1)

    claim_text = claims.set_index("claim_id")["claim_text"].astype(str)
    candidates.insert(
        0,
        "direction_id",
        [
            _direction_id(source_id, candidate_id)
            for source_id, candidate_id in candidates[score_keys].itertuples(
                index=False,
                name=None,
            )
        ],
    )
    candidates.insert(
        2,
        "source_claim_text",
        candidates["source_claim_id"].map(claim_text),
    )
    candidates.insert(
        4,
        "candidate_claim_text",
        candidates["candidate_claim_id"].map(claim_text),
    )

    known = known_relations.fillna("").copy()
    if known.duplicated(score_keys).any():
        raise ValueError("known relation direction keys must be unique")
    unknown_claim_ids = (
        set(known["source_claim_id"]) | set(known["candidate_claim_id"])
    ) - claim_id_set
    if unknown_claim_ids:
        raise ValueError("known relations contain claim IDs outside the claim index")
    allowed_labels = {"COVERS", "DOES_NOT_COVER"}
    if unknown_labels := sorted(set(known["final_coverage_label"]) - allowed_labels):
        raise ValueError("known relations contain nonbinary labels: " + ", ".join(unknown_labels))
    known["_eligible"] = known["relation_artifact_eligible"].map(_eligible_bool)
    inconsistent = known["final_coverage_label"].eq("COVERS") != known["_eligible"]
    if inconsistent.any():
        raise ValueError("known COVERS labels and artifact eligibility must agree")
    if "direction_id" in known:
        expected_direction_ids = [
            _direction_id(source_id, candidate_id)
            for source_id, candidate_id in known[score_keys].itertuples(
                index=False,
                name=None,
            )
        ]
        if not known["direction_id"].astype(str).eq(expected_direction_ids).all():
            raise ValueError("known relation direction IDs do not match claim direction")
    else:
        known.insert(
            0,
            "direction_id",
            [
                _direction_id(source_id, candidate_id)
                for source_id, candidate_id in known[score_keys].itertuples(
                    index=False,
                    name=None,
                )
            ],
        )
    if "source_claim_text" not in known:
        known["source_claim_text"] = known["source_claim_id"].map(claim_text)
    if "candidate_claim_text" not in known:
        known["candidate_claim_text"] = known["candidate_claim_id"].map(claim_text)

    known_columns = [*score_keys, "final_coverage_label", "relation_artifact_eligible"]
    optional_known_columns = ["final_reason_code", "safety_audit_status"]
    known_columns.extend(column for column in optional_known_columns if column in known)
    known_for_join = known.loc[:, known_columns].rename(columns={
        "final_coverage_label": "known_coverage_label",
        "final_reason_code": "known_reason_code",
        "safety_audit_status": "known_safety_audit_status",
    })
    candidates = candidates.merge(
        known_for_join,
        on=score_keys,
        how="left",
        validate="one_to_one",
    )
    for column in (
        "known_coverage_label",
        "known_reason_code",
        "known_safety_audit_status",
        "relation_artifact_eligible",
    ):
        if column not in candidates:
            candidates[column] = ""
        candidates[column] = candidates[column].fillna("").astype(str)
    candidates["review_status"] = "NEEDS_V3_OFFLINE_REVIEW"
    candidates.loc[
        candidates["known_coverage_label"].eq("DOES_NOT_COVER"),
        "review_status",
    ] = "KNOWN_DOES_NOT_COVER"
    candidates.loc[
        candidates["known_coverage_label"].eq("COVERS"),
        "review_status",
    ] = "KNOWN_APPROVED_COVERS"
    candidates = candidates.sort_values(
        ["source_claim_id", "best_rank", "retriever_count", "candidate_claim_id"],
        ascending=[True, True, False, True],
        kind="stable",
    ).reset_index(drop=True)

    positives = known.loc[known["_eligible"], [
        column
        for column in (
            "direction_id",
            "source_claim_id",
            "source_claim_text",
            "candidate_claim_id",
            "candidate_claim_text",
            "final_coverage_label",
            "final_reason_code",
            "safety_audit_status",
        )
        if column in known
    ]].copy()
    for name in retriever_names:
        positives = positives.merge(
            ranked_scores[name],
            on=score_keys,
            how="left",
            validate="one_to_one",
        )
    positives["retrieval_channels"] = positives.apply(
        lambda row: " | ".join(
            name.upper()
            for name in retriever_names
            if int(row[f"{name}_rank"]) <= top_k
        ),
        axis=1,
    )
    positives["retrieved"] = positives["retrieval_channels"].ne("")
    positives = positives.sort_values("direction_id", kind="stable").reset_index(drop=True)

    per_source = candidates.groupby("source_claim_id").size()
    channel_counts = {
        channel: int(count)
        for channel, count in candidates["retrieval_channels"].value_counts().sort_index().items()
    }
    known_in_candidates = candidates["known_coverage_label"].ne("")
    retrieved_positive_count = int(positives["retrieved"].sum())
    summary = {
        "schemaVersion": "mfds-function-relation-candidate-set.v1",
        "claimCount": len(claims),
        "retrievers": retriever_names,
        "topKPerRetriever": top_k,
        "maxCandidateBudgetPerSource": top_k * len(retriever_names),
        "candidateDirections": len(candidates),
        "candidateDirectionsPerSource": {
            "min": int(per_source.min()),
            "max": int(per_source.max()),
            "mean": round(float(per_source.mean()), 6),
        },
        "retrievalChannelCounts": channel_counts,
        "knownDirectionsTotal": len(known),
        "knownDirectionsInCandidateSet": int(known_in_candidates.sum()),
        "knownApprovedPositiveDirections": len(positives),
        "knownApprovedPositiveRetrieved": retrieved_positive_count,
        "knownApprovedPositiveRecall": round(
            retrieved_positive_count / len(positives),
            6,
        ) if len(positives) else None,
        "knownNegativeDirections": int((~known["_eligible"]).sum()),
        "knownNegativeDirectionsInCandidateSet": int(
            candidates["known_coverage_label"].eq("DOES_NOT_COVER").sum()
        ),
        "knownApprovedDirectionsInCandidateSet": int(
            candidates["review_status"].eq("KNOWN_APPROVED_COVERS").sum()
        ),
        "offlineV3ReviewDirections": int(
            candidates["review_status"].eq("NEEDS_V3_OFFLINE_REVIEW").sum()
        ),
        "runtimePolicy": (
            "Retrieval scores only bound candidate generation. Production may "
            "use CPU embeddings, but only approved directional relations pass "
            "the substitution hard gate; unseen relations are not proposed."
        ),
    }
    return candidates, positives, summary
