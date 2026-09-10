# Facet Taxonomy V2.2 결정 보고서

## 범위
기존 V2.1 Category 구조와 Category-local Facet/Value Code를 보존하고, 검수 완료된 Alias만 별도 Registry에 연결했다.
Taxonomy 본문에는 Alias를 직접 삽입하지 않았다.

## 구조
- Category: 16
- Facet: 48 (V2.1: 48)
- Value: 413 (V2.1: 413)
- 신규 전역 Facet: 0

## 신규 Consumer Candidate 결정
| Candidate | 최종 결정 | 근거 요약 |
|---|---|---|
| `digestive_tolerance` | `REJECTED_NOT_FACET` | 소화·신체 반응 표현의 안전성 검토가 필요하며 Facet으로 자동 승인하지 않음. |
| `intake_frequency` | `MERGED_EXISTING` | 기존 daily_frequency와 의미가 겹치므로 별도 Facet을 만들지 않고 기존 개념으로 병합. Product domain field는 확인됐으나 Nutrime 상품 cross-match는 미해결. |
| `mixability` | `REJECTED_NOT_FACET` | 3건이지만 Product/Category 미매핑이고 기존 product_form/dissolution 계열과 중복 가능성이 있어 신규 Facet으로 승인하지 않음. |
| `opening_convenience` | `DEFERRED_V2_3` | 소수 상품/리뷰에 국한되고 packaging/intake convenience와의 경계가 남아 V2.3 보류. |
| `storage_convenience` | `DEFERRED_V2_3` | 1개 상품 중심의 약한 근거로 V2.3 보류. |

## Alias 적용
- 전체 검수 Row: 66
- APPLIED: 24
- DEFERRED_TAXONOMY_NOT_APPROVED: 38
- REJECTED_BY_HUMAN: 4
- TARGET_NOT_FOUND: 0
- corrected_value_candidate 적용 성공 Row: 19
- Product Form Alias는 Category별 local code로 해석한다.

## 호환성 검증
- 기존 Code 보존: PASS
- Code 수 V2.1 → V2.2: 413 → 413
- 중복 Code Facet 수: 0

## Demand 회귀 검증
동일한 200건 grounded sample을 사용했으며 LLM benchmark는 재실행하지 않았다.
- V2.1 Rule-only diagnostic agreement: 0.7250
- V2.2 Rule/Alias-only diagnostic agreement: 0.7250
- Alias hit: 116
- Corrected alias hit: 87
- Unresolved / Conflict / Invalid code: 16 / 17 / 16
