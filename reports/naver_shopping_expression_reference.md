# Naver Shopping Expression Reference

이 자료는 한국 쇼핑 리뷰 표현과 Alias 후보를 탐색하기 위한 참고 데이터다. 건강기능식품 리뷰로 분류하지 않으며 HFF Facet Consumer Salience Count에 포함하지 않는다.

## Raw Audit
- source_type: `KOREAN_SHOPPING_REVIEW_EXPRESSION_REFERENCE`
- raw_path: `..\data\raw\references\bab2min_naver_shopping\naver_shopping.txt`
- row_count: 200000
- columns: `['rating', 'review_text']`
- encoding: `utf-8` / delimiter: `tab`
- rating_values: `['1', '2', '4', '5']`
- duplicate_rows: 0
- duplicate_review_text: 92
- null_rating: 0
- null_review_text: 0
- review_length_chars: `{'min': 3, 'median': 29.0, 'max': 140}`
- sha256: `5d3c8ec4fbe19150dd6c452b4ad03faf7c54d2c461646a9f7e0461b60a4cda06`

## Interpretation Rules
- Nutrime의 Review-supported Facet seed에서 관련 문장을 먼저 검색했다.
- 검색된 문장에서 보수적인 표현 패턴을 추출했으며 단순 전체 빈도 순위로 Alias를 만들지 않았다.
- 의료 효능 표현과 명백한 무관 상품 문맥은 후보에서 제외했다.
- `proposed_alias`는 비워 두고 `reviewer_decision=PENDING_REVIEW`로 유지했다.
- 기존 Facet Taxonomy에는 자동 반영하지 않았다.

## Facet Summary
| facet_id:value | seed expressions | candidate aliases | related sentences | review queue |
|---|---:|---:|---:|---:|
| ingredient_inclusion:ingredient_mentioned | 4 | 3 | 481 | 3 |
| intake_convenience:convenient | 4 | 4 | 190 | 4 |
| intake_convenience:inconvenient | 4 | 4 | 190 | 4 |
| odor:fishy | 3 | 5 | 7212 | 5 |
| packaging:individual_packaging | 4 | 4 | 6249 | 4 |
| packaging:portable | 4 | 4 | 6249 | 4 |
| product_form:capsule | 6 | 6 | 861 | 6 |
| product_form:liquid | 6 | 6 | 861 | 6 |
| product_form:powder | 6 | 6 | 861 | 6 |
| product_form:tablet | 6 | 6 | 861 | 6 |
| swallowability:easy | 3 | 3 | 48 | 3 |
| tablet_size:large | 5 | 5 | 6757 | 5 |
| tablet_size:small | 5 | 5 | 6757 | 5 |
| taste:bitter | 4 | 5 | 15157 | 5 |

## Limitations
- 원본에는 Product ID, Product Name, Category, Brand, Review Date가 없으므로 HFF 여부나 상품별 대표성을 판단할 수 없다.
- 표현 후보는 사람이 검수하기 전까지 Alias가 아니다.
- Naver Corpus에서의 출현 빈도는 건강기능식품 소비자 중요도의 근거가 아니다.

## Version

- Commit: `e884998`
- Push: not performed
