# A 입력·모델·Release 검증 정책

DB checkpoint, 같은 A parser를 사용하는 평가 경로, 숫자 코드 비교 및 과거 CSV 데모 경계는 [2026-10-04 후속 기준](A_AUDIT_FIXES_20261004.md)을 함께 따른다.

이 문서는 A 전용 동작을 설명한다. B/C의 조건·클러스터링·낙찰 정책을 변경하지 않는다.

## Demand Labeling

- 원상품의 확인된 Facet만 기본값으로 사용한다. 미확인 축은 `0`이며 상품 전체의 모든 Facet이 확정되어야 하는 것은 아니다.
- 명확한 긍정 구매 요구만 해당 Facet을 덮어쓴다. 비어 있음·실패·모호·부정·충돌은 유효한 원상품 기본값을 유지한다.
- 인용된 예문·번역 요청·타인의 요청·역할 지시문은 구매 요구로 승격하지 않으며 LLM 재해석 대상으로 보내지 않는다. 보수적 문맥 guard가 적용되므로 복잡한 혼합 문장은 기본값 유지로 끝날 수 있다.
- 원료명의 괄호와 식별 문자(C/D 등)를 보존한다. 같은 Facet에서 짧은 별칭이 긴 원자 값 안에 포함된 경우 별도 값으로 세지 않는다. 독립된 복수 값은 단일 Label로 임의 압축하지 않는다.
- 쉼표로 나열한 복합 원료 요구는 기존 Taxonomy에 하나의 문자열로 있더라도 신규 단일 값 override로 압축하지 않는다. 원상품 baseline은 유지한다.
- 원료명 안의 `분말`처럼 긴 기능성 원료 표현에 포함된 제형 문자열은 별도의 제형 요구로 승격하지 않는다. 원료명과 분리해서 제형을 요청한 경우에만 제형 변경을 검토한다.
- A의 파서 인스턴스에서만 `DEPRECATED` 값을 제외한다. 동일 Facet의 NFKC 정규화 후 완전히 동일한 값은 가장 작은 활성 code로 신규 요구를 표현한다. 기존 상품 기본값과 원본 Taxonomy/B 파서는 변경하지 않는다.
- 모델 응답은 Facet 이름·값·코드·원문 근거를 검증한다. **원상품과 동일한 값은 override가 아니므로 소비자가 반복해서 언급할 필요가 없다.** 변경되는 값에만 구매 요구의 근거를 요구한다. 다른 Facet의 근거 부족·잘못된 코드가 있으면 해당 응답을 적용하지 않는다.
- 모델에 각 행을 독립적으로 해석하도록 지시하며 행별 검증을 수행한다. 이것은 생성 모델 출력의 절대적 결정론이나 의미 정확도를 보증하지 않는다.

## 설정과 Release 연결

- `A_LLM_*`가 설정되면 대응하는 기존 `A_MODEL2_*`보다 우선한다. `/api/tags` preflight와 실제 `/api/generate` 호출은 같은 endpoint/model을 사용한다.
- `alias_registry_path=None`은 명시적 비활성이다. 기본 alias로 다시 대체하지 않는다.
- 현재 reviewed alias는 `v2.2`에 묶여 있다. 다른 버전, 특히 Backend `category.facet`에서 구성한 Taxonomy는 자체 값/alias만 사용한다. DB ID를 seed/source ID로 추정하지 않는다.
- 모델 준비 상태 확인 실패는 DB 작업 전 배치 실패다. 개별 응답 실패는 검증된 원상품 기본값 유지이며, 전체 상품 profile 누락·카테고리 불일치는 저장 보류다.

## Model 1 오프라인 후보 생성

- 모든 일반 prompt에 파서가 요구하는 JSON Schema(`facets/values/evidence`)를 명시한다. 상품 원문은 지시가 아닌 근거다.
- 비정상 응답 envelope·비문자열·객체가 아닌 JSON은 `ModelCallError`로 처리한다.
- 자동 gate와 review 연결 키는 **Category + Facet + Value**다. 동일 Value가 다른 Facet에 있다는 이유로 승인 근거를 공유하지 않는다. 같은 키의 거부 근거는 입력 순서로 덮어쓰지 않는다.
- Self-consistency는 생성 1회당 후보 1표만 집계한다. 한 생성에 근거 행이 여러 개 있어도 표 수가 늘어나지 않는다. 독립 생성 N회에서 `N // 2 + 1`표 이상을 요구한다. 실패 생성도 전체 N회 분모에서 제외하지 않는다.
- 과거 실험 수치는 당시 prompt·집계 코드의 기록이다. Schema 명시 또는 투표 집계 수정 이후의 결과로 재인용하지 않는다. 특히 이전 evidence-row 기반 self-consistency 수치는 수정 후 비교 성능 근거로 사용하지 않는다.

## 회귀 검사

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/data_foundation/test_a_audit_regressions.py \
  tests/data_foundation/test_runtime_labeling.py \
  tests/data_foundation/test_part_a_input_policy.py \
  tests/test_model1.py
```

실제 모델·Cloud 배포·운영 DB 검증은 위 결정적 단위 테스트와 구분해서 기록한다. 로컬 통과만으로 새 이미지 배포 및 DB 쓰기가 검증됐다고 보고하지 않는다.
