# 한국 건강기능식품 Review Category Coverage

기준: Raw review snapshot을 보존한 상태에서 Product/Category 연결이 확인된 건만 매핑 카테고리에 집계한다. 연결되지 않은 상품은 별도 행으로 남긴다.

- 총 Raw Review: 423
- Analysis Review: 399 (상품별 상한: 50)
- 매핑 성공 Review: 142
- Unique Product: 19
- Review Source 수: 1

## Category Coverage
| Service Category | Review | Unique Product | Source | Mapped Review | Facet Evidence | Band |
|---|---:|---:|---:|---:|---:|---|
| 건강기능식품 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 혈당·대사 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 식이섬유·체중관리 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 눈 건강 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 혈행·혈압 건강 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 관절·연골 건강 | 4 | 1 | 1 | 4 | 1 | VERY_LOW |
| 간 건강 | 30 | 1 | 1 | 30 | 11 | VERY_LOW |
| 남성 건강 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 오메가·지방산 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 기타 기능성 건강식품 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 유산균·프로바이오틱스 | 14 | 1 | 1 | 14 | 10 | VERY_LOW |
| 프로폴리스 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 단백질 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 홍삼·인삼 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 피부·콜라겐 | 0 | 0 | 0 | 0 | 0 | CRITICAL |
| 테아닌·수면 | 22 | 1 | 1 | 22 | 5 | VERY_LOW |
| 비타민·미네랄 | 72 | 5 | 1 | 72 | 74 | LOW |
| UNMAPPED_REVIEW_PRODUCT | 281 | 10 | 1 | 0 | 0 | MODERATE |

## Product Concentration
| Source | Category | Reviews | Products | Median/Product | Max/Product | Top 1 | Top 5 | Top 10 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| nutrime | UNMAPPED_REVIEW_PRODUCT | 281 | 11 | 5.0 | 75 | 26.69% | 93.95% | 99.64% |
| nutrime | 간 건강 | 30 | 1 | 30.0 | 30 | 100.00% | 100.00% | 100.00% |
| nutrime | 관절·연골 건강 | 4 | 1 | 4.0 | 4 | 100.00% | 100.00% | 100.00% |
| nutrime | 비타민·미네랄 | 72 | 5 | 17.0 | 24 | 33.33% | 100.00% | 100.00% |
| nutrime | 유산균·프로바이오틱스 | 14 | 1 | 14.0 | 14 | 100.00% | 100.00% | 100.00% |
| nutrime | 테아닌·수면 | 22 | 1 | 22.0 | 22 | 100.00% | 100.00% | 100.00% |

## 해석
- CRITICAL/VERY_LOW 카테고리는 다음 Review Source 탐색 우선순위로만 사용하며 Taxonomy 승인 기준으로 사용하지 않는다.
- Product ID 체계가 MFDS mapping과 다르면 자동 결합하지 않는다. 현재 뉴트리미처럼 별도 쇼핑몰 ID만 가진 Review는 UNMAPPED_REVIEW_PRODUCT로 보존한다.
- 한 상품에 리뷰가 집중되는 경우 Consumer Salience를 전체 Category 대표값으로 확대 해석하지 않는다.
