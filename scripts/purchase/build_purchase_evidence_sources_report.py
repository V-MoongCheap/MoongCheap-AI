"""Report verified and pending Korean HFF purchase/sales evidence sources."""

from __future__ import annotations

import argparse
from pathlib import Path


SOURCES = [
    {"source": "Foodpolis / 식품정보24", "basis": "공식 소매채널 판매정보 대시보드", "hff_separable": "YES", "access": "MANUAL_DASHBOARD_EXPORT", "cost": "UNKNOWN", "status": "WAITING_FOR_DASHBOARD_ACCESS", "next_step": "승인 후 마이페이지 → 나만의 대시보드 → 서비스 접속에서 Export"},
    {"source": "LG U+ 건강기능식품 융합데이터", "basis": "사용자가 제공한 공식 파일을 실제 검사·정규화함", "hff_separable": "YES", "access": "LOCAL_AUTHORIZED_FILE", "cost": "FREE_ONLY", "status": "AVAILABLE", "next_step": "Category/Product 식별자가 추가되면 별도 Crosswalk 검토"},
    {"source": "공공데이터포털 / FIS / 연구자료", "basis": "후보 탐색 대상이나 Product-level HFF 구매·판매 원자료는 현재 로컬 검증 없음", "hff_separable": "UNKNOWN", "access": "SEARCH_REQUIRED", "cost": "FREE_ONLY", "status": "NOT_VERIFIED", "next_step": "원자료·분류 기준·재사용 조건을 확인한 뒤 등록"},
]


def build_report(output: Path) -> dict[str, int]:
    lines = ["# 한국 건강기능식품 Purchase/Sales Evidence Sources", "", "이 보고서는 실제 구매·판매 기반 근거와 단순 생산량·검색순위·시장 기사 자료를 구분한다. 검증 전 자료는 파이프라인에 넣지 않는다.", "", "| Source | Basis | HFF 분리 | Access | Cost | Status | Next Step |", "|---|---|---|---|---|---|---|"]
    for row in SOURCES:
        lines.append("| " + " | ".join(row.values()) + " |")
    lines += ["", "## 현재 판정", "- 검증 완료된 Product-level 구매/판매 원자료: 0개.", "- Category/지역 Aggregate 구매 시장근거: LG U+ 파일 1개가 AVAILABLE.", "- LG U+ 파일은 제품명·상품분류가 없어 Product/MFDS Mapping과 Category Mapping을 수행하지 않는다.", "- Foodpolis 공식 서비스 소개에는 소매채널 판매정보가 존재하지만 Open API 상세 Endpoint는 현재 확인되지 않았다(`FOODPOLIS_OPEN_API_AVAILABLE=false`).", "- Foodpolis는 사용자의 대시보드 신청 후 승인 대기 상태이며, 비공개 API를 추측하지 않는다.", "- 생산실적, 일반 시장규모, 검색·클릭 비율은 구매/판매 evidence로 승격하지 않는다.", ""]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return {"source_count": len(SOURCES), "verified_source_count": sum(row["status"] == "VERIFIED" for row in SOURCES)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/purchase_evidence_sources.md"))
    args = parser.parse_args()
    print(build_report(args.output))
