# Seller Demand Analysis

Cluster 통계를 기반으로 참여자 수, 총수량, 가격 분포, Facet 분포 등의 판매자용 분석을 생성한다.

## 현재 범위

Backend 가 호출하는 내부 HTTP API `POST /internal/v1/seller/bid-guide` 하나다.
Cluster 단위 집계와 판매자의 공급 조건을 받아 구조화 지표를 돌려준다.

| 모듈 | 역할 |
|---|---|
| `bid_guide.py` | 계약 검증과 지표 계산. **표준 라이브러리만 쓴다** |
| `api.py` | 전송 계층. FastAPI 앱 생성과 오류 바디 |

두 층을 나눈 이유는 계산을 FastAPI 없이도 검증하기 위해서다.
`tests/seller_analysis/test_bid_guide.py` 는 FastAPI 가 없어도 돌고,
`test_api_http.py` 는 없으면 건너뛰되 **건너뛴다는 사실이 보이게** 한다.

## 계산 규칙

⛔ **숫자는 생성 모델이 만들지 않는다.** 네 지표 모두 결정적 계산이고
설명 문장도 템플릿이다. `CONTRIBUTING.md` 의
*"판매자 분석 수치는 SQL/Python 집계에서 생성하고 LLM은 숫자를 계산하거나 변경하지 않는다"* 를 따른다.

- `moq_attainment_ratio` = `total_demand_quantity / minimum_success_quantity`
- `supply_coverage_ratio` = `maximum_supply_quantity / total_demand_quantity`
- 상태는 비율에서 도출한다 — `ratio >= 1.0` 이면 충족
- **상태 판정은 표시용 반올림 값이 아니라 원본 정수 비교로 한다.**
  `999 / 1000` 을 소수 둘째 자리에서 반올림하면 `1.00` 이 되어 미달 판정과 어긋난다

## 계약

`docs/contracts/` 에 둔다. `api.py` 가 이 파일들을 읽어 OpenAPI 를 만든다 —
계약과 문서가 갈리지 않게 하기 위해서다.

| 파일 | |
|---|---|
| `seller_bid_guide_request_v01.schema.json` | 요청 9필드 |
| `seller_bid_guide_response_v01.schema.json` | 성공 응답 7키 |
| `seller_bid_guide_error_v01.schema.json` | 오류 바디 |

## 기동

```bash
pip install -r requirements-api.txt
SELLER_ANALYSIS_INTERNAL_KEY=... \
  python -m uvicorn moongcheap_ai.seller_analysis.api:create_app --factory --app-dir src --port 8081
```

⛔ `SELLER_ANALYSIS_INTERNAL_KEY` 없이는 **기동하지 않는다.** 인증이 빠진 채 배포되면
헬스체크와 정상 응답이 모두 통과해 조용히 고장 나기 때문이다. 인증 없이 띄우는 것이
의도라면 `SELLER_ANALYSIS_ALLOW_UNAUTHENTICATED=1` 을 명시한다.

## 확인 대기

| 항목 | |
|---|---|
| `supply_coverage_ratio` 상한 1.0 | 팀 문서가 갈린다. 현재는 **상한 없이** 낸다 |
| `retryable` 의 코드별 값 · `details` 내용 | Backend 와 공동 확정 |
| 비율의 `number/null` 허용 | 계약은 null 을 두는데 요청이 전부 Required 양의 정수라 분모 0 경로가 없다 |
