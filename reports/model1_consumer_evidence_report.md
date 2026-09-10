# Model 1 Consumer Evidence Report

## Nutrime
- Review snapshot: 423건 확보 (500건 목표, 공개 후기 종료)
- Mapping Before: 69% / 100건
- Mapping After: 82.27% / 348건 / 423건
- Mapping failure: 100건 기준 31건 모두 PRODUCT_ID_NOT_FOUND
- HFF confirmed review: 348건
- Analysis Review: 399건 (상품별 최대 50건), raw review snapshot 423건은 별도 보존
- Facet evidence used by this run: 333건
- Medical outcome sentence: 5건 별도 제외
- Unique product: 19개
- Top 10 product review share: 74.70%

## Chongkundang
- Review Pilot: 실패/중단
- Review 수: 0건
- 원인: 공개 상품 페이지는 접근 가능했으나 Review 목록 요청이 비JSON/403 응답으로 반환됨. 우회하지 않음.
- HFF Review: 0건

## Cross-source
- Facet Candidate Before: 37391
- Facet Candidate After: 37400
- Source >= 2 Before / After: 7 / 8
- Source >= 3 Before / After: 0 / 4
- Review Evidence Rows: 333
- Review-supported Candidate Rows: 14
- LG U+ Purchase Evidence Rows: 3402
- LG U+ regional purchase aggregates are retained as market evidence and excluded from Facet candidate generation.
- Review Source Count: 1 (Nutrime; Chongkundang은 0건)
- Product/category crosswalk: 쇼핑몰 ID와 MFDS ID를 숫자만으로 조인하지 않으며, 상품명 완전일치 외에는 미매핑으로 유지
- Review Source Agreement (both providers): 0

| Combination | Candidate count |
|---|---:|
| MFDS + Review | 0 |
| Seller + Review | 5 |
| MFDS + Seller + Review | 0 |
| Review Source 2 | 0 |

## Human Review
- Queue rows: 37400
- Review queue에는 nutrime/chongkundang source별 count, 짧은 review example, product/seller support, priority가 포함됨.
- Priority는 자동 승인값이 아니라 사람이 먼저 검토할 순서를 정하는 보조값이다.

## Policy
- Raw Review는 내부 Model 1 분석용으로만 보관한다.
- 작성자명·닉네임·IP는 저장하지 않는다.
- verified_purchase는 공식 구매완료 근거가 없으므로 null이다.
- 의료 결과 표현은 별도 count 후 Facet Evidence에서 제외한다.
