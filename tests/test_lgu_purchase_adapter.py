from __future__ import annotations

import pandas as pd

from scripts.purchase.ingest_manual_aggregate import normalize_lgu


def test_normalize_lgu_preserves_aggregate_semantics() -> None:
    frame = pd.DataFrame(
        {
            "INDEX_KEY": ["r1"],
            "CRTR_YM": ["202112"],
            "CTPV_CD": ["11"],
            "CTPV_NM": ["서울"],
            "SGG_CD": ["110"],
            "SGG_NM": ["종로구"],
            "DONG_CD": ["1101"],
            "DONG_NM": ["청운동"],
            "MOAV_DYNMC_PUL_CNT": ["100"],
            "MOAV_LIVE_PUL_CNT": ["90"],
            "HMDLV_NOCS": ["12"],
            "OFLNE_SLS_AMT": ["3456"],
            "SHOP_SLS_AMT": ["789"],
        }
    )

    normalized, audit = normalize_lgu(frame, "snapshot:hash")

    assert len(normalized) == 3
    assert set(normalized["market_metric_type"]) == {
        "ONLINE_ORDER_COUNT",
        "OFFLINE_PURCHASE_AMOUNT",
        "SPECIALTY_STORE_PURCHASE_AMOUNT",
    }
    assert normalized["product_level_mapping"].eq("NOT_APPLICABLE").all()
    assert normalized["source_type"].eq("KOREAN_HFF_PURCHASE_AGGREGATE").all()
    assert audit["duplicate_rows"] == 0
