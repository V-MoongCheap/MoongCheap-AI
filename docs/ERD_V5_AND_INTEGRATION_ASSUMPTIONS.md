# ERD v5 및 통합 개발 가정

작성 기준: `docs/erd/v5/`에 보관된 MoongCheap ERD v5 산출물

## 문서의 성격

이 문서는 첨부된 ERD v5의 스키마 내용을 AI 파트 개발에 반영하기 위한 저장소 기준이다. ERD 파일 자체의 테이블·컬럼 정의와, 아직 확정되지 않은 운영 환경에 대한 개발 가정을 구분한다.

운영 DB의 최종 마이그레이션과 계정 발급 주체가 확정되면 이 문서의 가정을 실제 Backend/Cloud 계약으로 교체한다.

## AI 파트와 직접 연결되는 ERD v5 경로

```text
demand.catalog_id
  -> product_catalog.id
  -> product_catalog.category_id
  -> category.id
  -> category.facet (TEXT containing JSON text)
```

Part A 라벨링 런타임은 수요의 `extra_requirement`를 해석하고, `category.facet`을 Python에서 JSON으로 읽어 `demand.label`과 `demand.processed_at`을 갱신한다.

Part B/C의 통합 대상은 ERD v5 기준으로 다음과 같다.

- Cluster: `demand_board`
- Seller offer: `product`
- Seller matching evaluation: `product_award_evaluation`
- 대체상품 거절 이력: `reject_history`

## v5에서 확인된 AI 관련 변경·주의점

- `demand.pay_method_id BIGINT NOT NULL`이 추가되어 있다. AI 라벨링은 이 값을 생성하거나 변경하지 않는다.
- `demand.desired_price_min`, `desired_price_max`, `quantity`, `is_substitutable`은 nullable이므로 입력 계약과 Mock 데이터에서 null 처리를 유지한다.
- `product_catalog.thumbnail_url`은 ERD v5에서 NOT NULL이다. 외부 수집 데이터가 없는 로컬 Mock에서는 유효한 placeholder URL을 사용한다.
- `category.facet`은 JSONB가 아니라 TEXT다. DB에서 JSON 내부 조건검색을 전제로 하지 않고 전체 문자열을 읽어 Python에서 검증·파싱한다.
- `demand_board`는 `catalog_id`를 중심으로 구성되며 가격·참여자 집계가 포함된다.
- `product`는 판매자 Offer 단위이고, `product_catalog`와 다른 테이블이다. Seller 매칭에서 둘을 혼동하지 않는다.

## 확정 전 운영 환경에 대한 개발 정책

### DB 계정 및 접속 정보

실제 DB가 구축된 뒤 계정을 만들 주체는 Cloud 또는 Backend 중 아직 미정이다. 따라서 현재 소스에는 운영 계정, 비밀번호, 실제 DSN을 넣지 않는다.

- 런타임 접속은 `A_DATABASE_URL` 같은 환경변수 또는 Kubernetes Secret 참조로만 주입한다.
- `.env.example`에는 변수명과 형식만 기록하고 실제 값은 기록하지 않는다.
- 로컬 개발은 `local_db/`의 축소 Mock schema와 Docker PostgreSQL을 사용한다.
- `local_db/schema.sql`의 `source_key` 등은 재현 가능한 테스트를 위한 Mock 전용 보조 컬럼이며, 운영 ERD v5 컬럼으로 간주하지 않는다.
- 운영 DB 계정의 권한 범위가 확정되기 전까지 AI 런타임은 필요한 최소 권한만 요청하는 방향으로 유지한다. Part A의 쓰기는 `demand.label`, `demand.processed_at`으로 제한한다.

### 인프라 전달 사항

ECR 주소, Kubernetes namespace, Secret 이름, 실제 CPU/메모리 리소스, CronJob schedule 등은 인프라 구축 전까지 확정값으로 취급하지 않는다.

- 저장소의 Dockerfile, Kustomize, CronJob, CI/CD 문서는 placeholder와 Mock 실행을 기준으로 유지한다.
- 실제 Cloud 값은 배포 시 ConfigMap/Secret 또는 CI 변수로 주입한다.
- 로컬 Docker smoke test와 테스트용 DSN은 실제 운영 인프라의 존재를 의미하지 않는다.
- Cloud에 전달할 항목은 확정 전에는 “제안/검토 필요”로 표시하고, 확정 후 별도 handoff 문서에 반영한다.

## 운영 전환 체크리스트

다음 결정이 끝나면 Mock 가정을 실제 값으로 교체한다.

1. DB 계정 생성 주체와 계정명
2. AI 런타임의 DB 권한 및 네트워크 접근 방식
3. `A_DATABASE_URL` Secret 이름과 주입 방식
4. 실제 Kubernetes namespace, image registry, schedule
5. ERD v5 SQL이 Backend migration에 반영되었는지 여부
6. `category.facet`의 최종 저장 JSON 계약과 Human Review 반영 절차
7. 운영 DB에서 `product_catalog.category_id`와 `category.facet` 조회가 가능한지 확인

## 관련 파일

- `docs/erd/v5/moongcheap_erd_v5.sql`: ERD v5 SQL 원본
- `docs/erd/v5/moongcheap_erd_v5.snapshot.json`: ERD 도구 snapshot 원본
- `docs/erd/v5/moongcheap_erd_v5.xlsx`: 검토용 ERD 표
- `docs/erd/v5/moongcheap_erd_v5.png`: 시각 검토용 ERD
- `local_db/schema.sql`: 로컬 라벨링 Mock 전용 schema
- `docs/A_LABELING_RUNTIME_HANDOFF.md`: Part A 런타임 동작 및 DB 쓰기 범위
