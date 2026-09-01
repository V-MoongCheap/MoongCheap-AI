# 데이터 계보와 전처리 기준

이 문서는 원천 데이터가 상품·Category·Facet 산출물로 변환되는 경로와 버전을 기록한다. `v0`, `v1`, `v2`, `v2.1`은 프로젝트 산출물 버전이며 원천기관의 공식 버전과는 별개다.

## 원천 데이터

| 데이터 | 출처 | 내용 | 라벨 |
|---|---|---|---|
| AI-Hub 물류상품 | 프로젝트에 제공된 로컬 파일 | 일반 상품명, 바코드, 원천 Category | `AIHUB_LOGISTICS_LOCAL_SNAPSHOT`, 원천 버전 미확인 |
| MFDS I0030 | 식품의약품안전처 API 수집 결과 | 건강기능식품 제품·형태·원료·기능성 내용·섭취 방법 | `MFDS_I0030_LOCAL_SNAPSHOT_2026-09-01` |
| MFDS I2710 | 식품의약품안전처 API 수집 결과 | 기능성 원료·기능성 내용 참고 자료 | `MFDS_I2710_LOCAL_SNAPSHOT_2026-09-01` |
| KAN | 선택적으로 제공되는 공식 자료 | Category 코드 참고 | `KAN_OPTIONAL` |

원천에 공식 버전이 없으면 임의의 버전을 만들지 않고 `unknown`으로 기록한다. 수집일, 원천 파일, 원천 행 번호는 provenance로 보존한다.

## 전처리

- AI-Hub 컬럼 별칭을 표준 컬럼으로 매핑하고 상품명에 HTML·제어문자 제거, Unicode NFKC, 공백 정리를 적용한다.
- 바코드는 공백·하이픈을 제거하고 8~14자리 숫자 여부를 별도 기록한다. 잘못된 바코드도 감사 가능하도록 staging에 남긴다.
- 유효 바코드는 상품 후보를 묶는 기준으로 사용하고, 동일 바코드의 상품명·KAN 충돌은 별도 기록한다.
- MFDS 응답은 제품 단위로 평탄화하고 원문 필드는 삭제하지 않는다.
- 제품 형태는 관측값 기준으로 `정제 → 정` 등 표기를 통일한다.
- 기능성 원료는 괄호 안 쉼표를 보존하면서 최상위 구분자로 분리한다. 불완전한 괄호는 원문과 parse failure를 함께 보존한다.
- 인정번호, 섭취 횟수, 섭취량, 단위, 시점은 원문과 후보값을 분리한다.

## Category 매핑

V2.1은 `product_type + functional_ingredients + main_functionality + name`을 합친 관측 문자열에 우선순위 키워드 규칙을 적용한다. 예를 들어 `유산균`은 유산균·프로바이오틱스, `비타민`, `칼슘`, `아연` 등은 비타민·미네랄 후보가 된다. 일치하지 않는 상품은 기타 기능성 건강식품 후보로 남기며 원천 `product_type`이 비어 있으면 `UNMAPPED`로 기록한다.

상품의 `source_product_id`는 유지하고 최종 Category ID·Catalog ID는 만들지 않는다. confidence와 mapping reason은 후보 판정 근거일 뿐 승인 결과가 아니다.

## Facet 도출

Model 1은 MFDS 전처리 상품을 Category별로 샘플링해 Facet·Value·Alias 후보와 근거 상품을 만든다. 현재 실행 Category는 비타민·미네랄, 유산균·프로바이오틱스, 피부·콜라겐이다. 결과는 최종 Taxonomy가 아니며, 근거 ID와 원문이 입력에 존재하는지 검증한다.

후처리에서는 영어·한글 Facet 이름, 제품 형태, 복합 원료, 별칭, 인정번호, 규제 기능 문구를 정규화한다. 기능성 원료는 다중 값으로 유지하고, 규제 기능은 장 건강·피부 보습·자외선 피부 보호 같은 의미 그룹으로 기록한다. 원문은 source text로 보존한다.

상품 매핑은 후보가 생성된 Category의 모든 상품-Facet 조합을 `MAPPED` 또는 `UNMAPPED`로 기록한다. 아직 Model 1을 실행하지 않은 Category에는 Facet 후보가 없으므로 16개 전체 Category 결과로 해석하지 않는다.

## 버전 라벨

| 산출물 | 버전 | 상태 |
|---|---|---|
| AI-Hub staging | `product_staging_v0` | 원천 보존·후보 |
| Product Catalog | `product_catalog_v1` | 후보 |
| Service Category | `category_v2_1` | 검토 필요 |
| Model 1 입력·원본 | `facet_discovery_model_input_v0` / `facet_discovery_model_raw_v0` | 실행 기록 |
| Facet 후보·상품 매핑 | `facet_candidates_normalized_v0` / `product_facet_mapping_v0` | 검토 필요 |
| Synthetic Demand | `synthetic_demands_v0` | 테스트 전용 |
