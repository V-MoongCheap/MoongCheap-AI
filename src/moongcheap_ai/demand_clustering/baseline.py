"""Deterministic clustering baseline for the local MVP handoff."""

from __future__ import annotations

import hashlib

import pandas as pd


REQUIRED_COLUMNS = {"demand_id", "catalog_id", "label", "category_id", "quantity", "is_substitutable"}


def cluster_demands(frame: pd.DataFrame) -> pd.DataFrame:
    """Assign a stable cluster ID using catalog, category, and facet label.

    Substitutable demands may share a cluster across catalog IDs; strict demands
    remain bound to their requested catalog. This is a V0 baseline, not a final
    clustering policy.
    """
    result = frame.copy().fillna("")
    if "category_id" not in result and "service_category_key" in result:
        result["category_id"] = result["service_category_key"]
    missing = REQUIRED_COLUMNS - set(result.columns)
    if missing:
        raise ValueError(f"missing clustering columns: {sorted(missing)}")
    result["is_substitutable"] = result["is_substitutable"].astype(str).str.casefold().isin({"true", "1", "yes", "y"})
    result["quantity"] = pd.to_numeric(result["quantity"], errors="coerce").fillna(1).clip(lower=1).astype(int)
    result["_cluster_key"] = result.apply(
        lambda row: "|".join(
            [str(row["category_id"]), str(row["label"]), "SUBSTITUTABLE" if row["is_substitutable"] else str(row["catalog_id"])]
        ),
        axis=1,
    )
    result["cluster_id"] = result["_cluster_key"].map(
        lambda value: "cluster-" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    )
    result["cluster_participant_count"] = result.groupby("cluster_id")["demand_id"].transform("nunique")
    result["cluster_total_quantity"] = result.groupby("cluster_id")["quantity"].transform("sum")
    return result.drop(columns="_cluster_key")


def summarize_clusters(clustered: pd.DataFrame) -> pd.DataFrame:
    """Create the compact handoff table consumed by seller analysis."""
    return (
        clustered.groupby(["cluster_id", "category_id", "label"], as_index=False)
        .agg(
            participant_count=("demand_id", "nunique"),
            total_quantity=("quantity", "sum"),
            catalog_count=("catalog_id", "nunique"),
            substitutable=("is_substitutable", "max"),
            demand_ids=("demand_id", lambda values: "|".join(map(str, values))),
        )
    )
