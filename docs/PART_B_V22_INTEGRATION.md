# Part B의 A V2.2 연계

B는 DB의 `extra_requirement`를 기존 v0.46 규칙과 Kiwi로 직접 해석한다.
A 분류표를 기준으로 B 별칭을 사용하고, A 승인 별칭이 있으면 함께 적용한다.
수요 `label`을 해석 입력으로 활용하는 작업은 별도 계약을 정한 뒤 진행한다.

## Part A 5,000건 handoff의 Label 의미

Part A의 `label`은 동일 Category 안에서 후보를 빠르게 찾기 위한 압축 코드다.
특히 단일 `PREFER` 조건도 코드에 나타날 수 있으므로, Part B는 Label만으로
필수 조건을 판정하거나 Cluster를 분리하면 안 된다.

최신 handoff에는 아래 구조화 필드도 함께 포함한다.

| 필드 | 용도 |
| --- | --- |
| `constraints` | `MUST` / `PREFER` / `EXCLUDE`가 명시된 JSON 배열 |
| `preference_groups` | OR 등 복수 선호 조건의 JSON 배열 |
| `passthrough_text` | Taxonomy 밖의 원문 요구 |
| `reason_codes` | 파서 판단 근거·검토 사유 |
| `labeling_status` | `LABELED` 또는 `LABELED_WITH_REVIEW` |

Part B는 `constraints`의 `MUST`/`EXCLUDE`만 hard gate로 사용하고, `PREFER`는
동점 후보 순위에만 사용한다. `labeling_status=LABELED_WITH_REVIEW`은 Label을
신뢰한 자동 확정 대상이 아니며, 기존 B parser와 원문을 함께 사용해 보수적으로
처리한다.

## 실행 자료와 별칭 정책

| 설정 | 자료와 역할 |
| --- | --- |
| `DEMAND_TAXONOMY_PATH` | A `config/facet_taxonomy_v2_2.json`을 복사한 배포용 `taxonomy.json` |
| `DEMAND_CATALOG_SEED_PATH` | Backend와 같은 도매꾹 v5 `product_catalog_seed_v5.csv` |
| `DEMAND_CONSTRAINT_RULES_PATH` | 이미지에 포함된 B `config/demand_constraint_rules.json` |
| `DEMAND_CONSTRAINT_COMPAT_ALIASES_PATH` | 이미지에 포함된 필수 B `config/demand_constraint_aliases.json` |
| `DEMAND_CONSTRAINT_ALIASES_PATH` | 이미지에 포함된 선택 A `config/model1_aliases_reviewed_v2.json` |

- B 별칭은 항상 사용한다. 해당 카테고리의 facet에 대표값이 있을 때 연결한다.
- 같은 카테고리·표현에 유효한 A 연결이 있으면 A를 우선한다. A에 없는 표현·카테고리는 B가 처리한다.
- A 경로를 비우거나 설정하지 않으면 B만 사용한다. A의 표현·카테고리 연결이 삭제되어도 B에 남아 있으면 사용한다.
- A 경로를 설정했는데 파일이 없으면 배포 경로 오타나 이미지 패키징 누락으로 보고 중단한다.
- A 파일이 있으면 버전과 카테고리·facet·코드·값을 검증한다. 잘못된 JSON, 모순된 연결,
  권한 오류는 DB 연결 전에 중단하며 파일 누락으로 취급하지 않는다.
- B 파일 누락은 설정 오류다. A-only는 비교 평가에서만 사용한다.

`part_a_integration.py`는 별칭을 메모리의 분류표 사본에 연결해 기존 파서를 구성한다.
배치 결과 `partAIntegration`에는 분류표·별칭 버전과 해시, A 로드 상태, 적용 건수가 남는다.
`aliasMode=A_AND_B/B_ONLY`, `primaryAliasLoadStatus=LOADED/NOT_CONFIGURED`로
실제 사용한 조합을 확인한다. B 별칭은 B의 개발·검수 자료이며 A 승인 상태로 바꾸지 않는다.

## v5 상품 시드 준비

Backend가 적재하는 `product_catalog_seed_v5.csv`를 그대로 이미지 입력으로
포장한다. 런타임에서 DB의 숫자 `product_catalog.id`를 시드 ID로 간주하지
않는다. Backend에서 UNIQUE인 `product_catalog.name`과 v5 `name`을 정확히 일치시켜
현재 DB ID에 결합한다.

`extra_requirement`의 MUST/PREFER/EXCLUDE 구조화는 V2.2 taxonomy와 기존 B 파서를
그대로 사용한다. 대체상품 후보는 같은 v5 말단 카테고리와 같은
서비스 taxonomy 카테고리로 제한한다. 상품명에 원료가 명시된 경우에만
같은 원료를 요구한다. MFDS claim ID와 기능 containment는 운영 경로에서
사용하지 않는다.

상품명이 v5에 없는 사용자 추가 상품과 `source_category_id`가 빈 99건은
동일상품 보드 편입·신규 보드 생성을 계속하고 대체상품 제안만 건너뛴다.
따라서 일부 상품 불일치가 전체 배치나 기본 보드 생성을 중단하지 않는다.

확정된 시드를 다음 명령으로 이미지 입력에 반영한다.

```bash
python scripts/deployment/prepare_demand_clustering_assets.py pack-seed \
  --seed /path/to/product_catalog_seed_v5.csv \
  --category-seed /path/to/category_seed_v5.csv \
  --taxonomy config/facet_taxonomy_v2_2.json \
  --release backend-v5-domeggook-YYYYMMDD \
  --assets packaging/demand-clustering/runtime-assets
```

스크립트는 상품 1,989건·카테고리 42건의 행 수, 상품명·Seed ID·도매꾹 ID
유일성, category 부모 계층, 상품→category FK·경로·taxonomy 매핑과 파일 해시를
검증한다. `product_catalog_seed_v5.csv.gz`, `category_seed_v5.csv.gz`,
`taxonomy.json`, `catalog.json`을 함께 커밋하고 이미지를 재빌드한다.
[자료 갱신 안내](../packaging/demand-clustering/runtime-assets/README.md)와
[컨테이너 실행 안내](DEMAND_CLUSTERING_CONTAINER.md)를 따른다. 기존 MFDS profile/claim
생성 스크립트는 오프라인 평가 자료로만 남으며 운영 이미지 입력이 아니다.

## 별칭·자연어 해석 회귀 검증

기본 검증은 저장소에 포함된 자료만으로 실행한다. 외부 LLM·DB·Backend·E5 호출이 없다.

```bash
pytest -c packaging/demand-clustering/pyproject.toml \
  tests/demand_clustering/test_alias_fallback.py \
  tests/demand_clustering/test_profile_artifacts.py \
  tests/demand_clustering/test_runtime_job.py
PYTHONPATH=src python scripts/evaluation/evaluate_b_v22_parser_regression.py \
  --output data/reports/b_v22_integration/regression.json
```

- pytest는 A의 94개 category/surface 연결, A 부재·삭제·오류, B 표현 보존, A 우선 적용,
  v5 시드·taxonomy 검사와 모의 배치를 검증한다. 의도한 A 연결 변경은 검수 후 고정 fixture를 갱신한다.
- 실행기는 기존 B / A 별칭만 / A+B의 세 설정으로 129건의 동결 평가셋을 채점하고,
  별칭 전환 사례 15건을 합친 144건의 상태·조건·선호 그룹·자유 텍스트·동등 코드를 비교한다.
- `--input`으로 추가 비교 CSV를 지정하고, `--baseline-taxonomy`로 이전 분류표를 지정할 수 있다.
  기본 이전 분류표는 저장소의 `v042_taxonomy.json` fixture다.
- 결과는 `gold`의 정답·오판 집계와 `comparison`의 조건 누락·변경 사례로 나뉜다.
  실행기는 보고서를 작성하며, pytest가 고정 사례의 회귀를 차단한다.

기존 5,000건 자료가 있을 때는 같은 실행기에 두 옵션을 함께 전달한다.

```bash
PYTHONPATH=src python scripts/evaluation/evaluate_b_v22_parser_regression.py \
  --service-input /path/to/part_c_clustering_input_grounded_5000_v1.csv \
  --archived-service-output /path/to/v046_service_aligned_part_c_input_5000_candidate.csv \
  --output data/reports/b_v22_integration/regression_with_archive.json
```

행 ID·카테고리·동의한 수요 원문이 과거 결과와 대응하는지 확인한 뒤 `service`에 비교 결과를 추가한다.
보고서에는 입력 해시와 규칙·Kiwi 버전도 기록한다. 기본 144건 검증에는 이 외부 자료가 필요하지 않다.

129건은 모델이 생성한 문장을 Codex가 의미 검수한 개발 평가셋이다. 기존 언어 해석은
127/129 정답, 자동 PARSED 오판 0건이며 알려진 인용·전언 관련 실패 2건을 회귀 기준으로 둔다.
5,000건은 과거 규칙 개발에 사용한 합성 자료다. 이 결과를 실제 사용자 정확도로 해석하지 않는다.

## 과거 2026-09-11 MFDS profile 검증 결과

아래는 현재 v5 운영 자료로 전환하기 전의 회귀 기록이다.

- C/API를 제외한 저장소 테스트: 559 passed. 별칭·profile·모의 배치·패키지 경계 검사 포함.
- 기존 B / A-only / A+B 모두 동결 평가셋 127/129 정답, 자동 PARSED 오판 0건.
- 144건 비교에서 A-only는 기존 조건 누락 6건, A+B는 누락 0건. A+B의 변경 2건은
  “가루”와 “알약”을 승인된 값으로 연결한 결과다.
- 5,000건은 세 설정 모두 과거 v0.46 결과와 비교 대상 의미가 동일했다.
- A 매핑·기능성 문장 후보를 준비한 뒤 기존 생성기로 profile 45,996건을 원재료부터 생성했다.
  이전 파일과 profile 내용이 일치하며, 복사된 분류표로 runtime profile 45,996건을 구성했다.
- 실행 결과와 대량 profile은 로컬 `data/reports/`에 보관한다. 실제 DB/Backend 연동은 이 검증에 포함하지 않는다.
