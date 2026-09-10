"""Deterministic Seller Offer to Demand Cluster matching baseline."""

from __future__ import annotations

import re

import pandas as pd


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def match_offers(clusters: pd.DataFrame, offers: pd.DataFrame) -> pd.DataFrame:
    """Score offers with transparent category, price, and MOQ checks.

    Category matching uses the observed offer category text. Because the source
    offer corpus has no canonical catalog ID, this function never claims an
    exact product identity from fuzzy text alone.
    """
    if clusters.empty or offers.empty:
        return pd.DataFrame(columns=["cluster_id", "item_id", "match_status", "score", "reason"])
    rows = []
    for _, cluster in clusters.iterrows():
        category = str(cluster.get("category_id", "")).rsplit(":", 1)[-1].casefold()
        quantity = _number(cluster.get("total_quantity"), 1)
        for _, offer in offers.iterrows():
            text = " ".join(str(offer.get(column, "")) for column in ("category_leaf", "category_l2", "title", "semantic_text")).casefold()
            category_hit = bool(category and (category in text or re.sub(r"[_-]", " ", category) in text))
            moq = _number(offer.get("moq"), 0)
            price = _number(offer.get("min_unit_price"), _number(offer.get("base_unit_price"), 0))
            moq_ok = moq <= quantity if moq else True
            price_ok = price > 0
            score = int(category_hit) * 50 + int(moq_ok) * 25 + int(price_ok) * 25
            rows.append(
                {
                    "cluster_id": cluster["cluster_id"],
                    "item_id": offer.get("item_id", ""),
                    "seller_id": offer.get("seller_id", ""),
                    "match_status": "CANDIDATE" if score >= 50 else "REVIEW",
                    "score": score,
                    "category_match": category_hit,
                    "moq_ok": moq_ok,
                    "price_available": price_ok,
                    "reason": "category/quantity/price checks; exact catalog identity unresolved",
                }
            )
    return pd.DataFrame(rows).sort_values(["cluster_id", "score"], ascending=[True, False]).reset_index(drop=True)
