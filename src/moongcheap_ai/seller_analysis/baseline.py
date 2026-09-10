"""Seller-facing demand summaries for the local MVP."""

from __future__ import annotations

import pandas as pd


def summarize_seller_demand(clusters: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Aggregate cluster demand and offer coverage without an LLM."""
    if clusters.empty:
        return pd.DataFrame(columns=["cluster_id", "participant_count", "total_quantity", "candidate_offer_count", "top_offer_score"])
    offer_counts = matches[matches["match_status"].eq("CANDIDATE")].groupby("cluster_id").agg(
        candidate_offer_count=("item_id", "nunique"), top_offer_score=("score", "max")
    ) if not matches.empty else pd.DataFrame()
    result = clusters[["cluster_id", "participant_count", "total_quantity", "catalog_count", "substitutable"]].copy()
    if offer_counts.empty:
        result["candidate_offer_count"] = 0
        result["top_offer_score"] = 0
    else:
        result = result.merge(offer_counts, on="cluster_id", how="left")
        result[["candidate_offer_count", "top_offer_score"]] = result[["candidate_offer_count", "top_offer_score"]].fillna(0)
    result["analysis_status"] = "LOCAL_MVP_RULE_BASELINE"
    return result
