"""Deterministic Seller Offer to Demand Cluster matching baseline."""

from __future__ import annotations

import re
import math

import pandas as pd


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _text(value: object) -> str:
    """Missing scalar values are not category tokens."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().casefold()


def _cluster_needles(cluster: pd.Series) -> set[str]:
    """수요 쪽에서 대조에 쓸 문자열을 모은다.

    ⛔ `category_id` 만 쓰면 안 된다. 그 값은 `health-functional-food:red_ginseng`
       처럼 영문 슬러그인데 판매 공고 텍스트는 한글이라 사실상 맞지 않는다.
       `summarize_clusters` 가 `label` 을 groupby 키로 내보내므로 이 함수에는
       한글 수요 라벨이 항상 함께 들어온다. 그것을 버리지 않는다.
    """
    values = {
        _text(cluster.get("label", "")),
        _text(cluster.get("category_id", "")).rsplit(":", 1)[-1],
    }
    values |= {re.sub(r"[_-]", " ", value) for value in values}
    return {value for value in values if value}


def match_offers(clusters: pd.DataFrame, offers: pd.DataFrame) -> pd.DataFrame:
    """Score offers with transparent category, price, and MOQ checks.

    Category matching uses the observed offer category text. Because the source
    offer corpus has no canonical catalog ID, this function never claims an
    exact product identity from fuzzy text alone.

    ⛔ 세 검사를 **모두** 통과해야 `CANDIDATE` 다. 점수 합만 보면 카테고리가 전혀
       맞지 않아도 MOQ·가격만으로 임계값을 채워, 무관한 상품이 후보로 올라간다.
       AI 는 낙찰 판매자를 결정하지 않으므로(「AI API Contract」 4절) 후보 제시는
       좁게 간다.

    ⚠️ 이것은 로컬 MVP 데모의 임시 기준선이다. 순위 산정 방식은 EXP-008 비교
       실험이 정한다.
    """
    if clusters.empty or offers.empty:
        return pd.DataFrame(columns=["cluster_id", "item_id", "match_status", "score", "reason"])
    rows = []
    for _, cluster in clusters.iterrows():
        needles = _cluster_needles(cluster)
        quantity = _number(cluster.get("total_quantity"), 0)
        for _, offer in offers.iterrows():
            text = " ".join(_text(offer.get(column, "")) for column in ("category_leaf", "category_l2", "title", "semantic_text"))
            category_hit = any(needle in text for needle in needles)
            moq = _number(offer.get("moq"), 0)
            price = _number(offer.get("min_unit_price"), _number(offer.get("base_unit_price"), 0))
            # ⛔ MOQ 를 모르는 것은 충족이 아니다. 확인되지 않은 조건을 통과로 두면
            #    실제로는 성사할 수 없는 응찰이 후보에 남는다.
            moq_known = moq > 0
            moq_ok = moq <= quantity if moq_known else False
            price_ok = price > 0
            score = int(category_hit) * 50 + int(moq_ok) * 25 + int(price_ok) * 25
            failed = [
                name
                for name, ok in (
                    ("category", category_hit),
                    ("moq", moq_ok),
                    ("price", price_ok),
                )
                if not ok
            ]
            rows.append(
                {
                    "cluster_id": cluster["cluster_id"],
                    "item_id": offer.get("item_id", ""),
                    "seller_id": offer.get("seller_id", ""),
                    # ⛔ 점수 합이 아니라 세 검사를 모두 통과해야 후보다. 점수만 보면
                    #    카테고리가 어긋나도 MOQ·가격만으로 임계값을 채운다.
                    "match_status": "CANDIDATE" if not failed else "REVIEW",
                    "score": score,
                    "category_match": category_hit,
                    "moq_known": moq_known,
                    "moq_ok": moq_ok,
                    "price_available": price_ok,
                    "reason": (
                        "category/quantity/price checks; exact catalog identity unresolved"
                        + (f"; failed: {','.join(failed)}" if failed else "")
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(["cluster_id", "score"], ascending=[True, False]).reset_index(drop=True)
