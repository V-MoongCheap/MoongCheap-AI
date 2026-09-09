# Demand Requirement Normalization

## 목적

`extra_requirement`의 한국어 자유 문장을 외부 모델 호출 없이 결정론적인 typed
constraint로 변환한다. 이 결과는 개별 구매요청을 수요보드로 만들기 전 사용하는
전처리 신호이며, 수요보드와 판매자를 연결하는 매칭 결과가 아니다.

언어 판정 코어는 동결한 v0.42를 그대로 보존하고, 운영 입력 계약은 v0.46을
적용한다. 따라서 `DemandConstraintParser.parse()`는 동결 평가용 언어 판정을,
`interpret(..., is_substitutable=...)`는 실제 요청 정규화를 반환한다.

## v0.46 처리 원칙

- 대체상품 미동의 요청은 기본 수요에서 제외하지 않고 자연어 대체조건만
  `NOT_APPLICABLE / NONE`으로 무시한다.
- 대체상품 동의자가 단독 taxonomy 값이나 승인 alias를 입력하면 `PREFER`로
  해석한다.
- 서로 다른 facet으로 구성된 짧은 무술어 합성 입력과 명시적 완곡 선호 표현은
  구조화된 `PREFER`로 해석한다.
- `X 또는 Y도 괜찮다`는 평면 AND가 아니라 `ANY_OF`, 집계 `MAX` 그룹으로
  보존한다.
- taxonomy 밖의 명시적 선호는 `PASSTHROUGH / SEMANTIC_TEXT`로 원문을 보존한다.
- 동일 facet의 상충 값은 `CONFLICT` 진단을 남기되 실효 조건은 `NONE`이다.
- 같은 category/facet에서 NFKC 정규화 결과가 같은 code는 canonical code로
  정규화하고 전체 `equivalent_value_codes`를 함께 보존한다.
- `REVIEW`, `CONFLICT`, `TAXONOMY_AMBIGUOUS`는 진단 상태일 뿐 수요보드 편입
  전 사용자 질문이나 수동 처리 절차를 뜻하지 않는다. 구조화 또는 의미 신호가
  증명되지 않으면 실효 조건은 `NONE`이다.

## 배치 출력 계약

입력 행과 기존 `label`은 그대로 유지하고 다음 컬럼을 추가한다.

- `constraint_status`: `PARSED`, `PASSTHROUGH`, `CONFLICT`,
  `TAXONOMY_AMBIGUOUS`, `REVIEW`, `NONE`, `NOT_APPLICABLE`
- `effective_requirement_mode`: `STRUCTURED`, `SEMANTIC_TEXT`, `NONE`
- `constraints`: `MUST`, `PREFER`, `EXCLUDE`와 근거 proof를 담은 JSON 배열
- `constraint_preference_groups`: `ANY_OF / MAX` 등의 JSON 배열
- `semantic_preferences`: taxonomy 밖 선호 원문 JSON 배열
- `constraint_interpretation_method`, `constraint_diagnostic_code`
- `taxonomy_equivalences`: canonical/equivalent code 메타데이터 JSON 배열
- `constraint_warnings`, `constraint_clauses`

`is_substitutable` 컬럼이 있으면 반드시 그 동의값을 적용하고, 값이 비어 있으면
미동의로 본다. 이전 배치와의 호환을 위해 컬럼 자체가 없는 입력만 동의로
간주한다.

## 실행

저장소 루트에서 실행한다.

```bash
PYTHONPATH=src python scripts/labeling/parse_demand_constraints.py \
  --input data/synthetic/demands/synthetic_demands_v0.csv \
  --taxonomy data/processed/facet_discovery/facet_taxonomy_v0.json \
  --output data/processed/demands/demand_constraints_v1.csv \
  --diagnostic-output data/processed/demands/demand_constraint_diagnostics_v1.csv
```

Backend Demand export에 `category_id`가 없으면 `id`와 `category_id`를 가진
Product Catalog CSV 또는 Parquet을 `--catalog`로 전달한다. DB 연결이나 DML은
수행하지 않는다. `--review-output`은 기존 실행 명령을 위한
`--diagnostic-output`의 호환 alias다.

## 구성

- `config/demand_constraint_rules.json`: v0.42 언어 규칙과 v0.46 입력 정책을
  합친 단일 완결 설정
- `config/demand_constraint_aliases.json`: 사람이 승인한 추가 표면형
- `src/moongcheap_ai/demand_constraints`: classifier, extractor, taxonomy matcher,
  input policy, batch service

형태소 분석 결과가 규칙 판정에 영향을 주므로 `kiwipiepy==0.23.2`를 고정한다.

## 검증 범위

동결한 독립 fixture 129건에서 v0.42 언어 코어는 전체 127/129, 자동 확정
79/79 정확, 위험 자동 처리 0건을 그대로 재현한다. 실패 2건은 보수적으로
`REVIEW`한 누락이다.

별도 5,000건 서비스 입력 실험에서 v0.46은 대체상품 동의·비어 있지 않은
3,046건 중 `PARSED` 2,519건, `PASSTHROUGH` 266건, `CONFLICT` 261건,
`TAXONOMY_AMBIGUOUS` 0건, `REVIEW` 0건이었다. 이는 요청 정규화 실험 결과이며
수요보드 생성이나 판매자 매칭 성능을 뜻하지 않는다.
