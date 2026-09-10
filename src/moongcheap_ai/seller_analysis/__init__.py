"""Seller demand analysis domain package.

계산 계층(`bid_guide`)은 표준 라이브러리만 쓴다. HTTP 진입 계층(`api`)은
FastAPI 를 필요로 하므로 여기서 재노출하지 않고 명시적으로 import 한다 —
`from moongcheap_ai.seller_analysis.api import create_app`.
"""

from .bid_guide import (
    METRICS_VERSION,
    ContractViolation,
    VersionMismatch,
    build_bid_guide,
    handle_bid_guide,
)

__all__ = [
    "METRICS_VERSION",
    "ContractViolation",
    "VersionMismatch",
    "build_bid_guide",
    "handle_bid_guide",
]
