# Part A -> Part B 연결 점검

## 확인한 실제 구조

Part B의 `demand_clustering.runtime_job`은 PostgreSQL에서 원본 Demand와 Board를 읽고 자체 `DemandConstraintParser`를 호출한다. 즉 현재 구현은 A 결과 API를 선행 입력으로 기다리는 구조가 아니다.

따라서 이번 단계에서 B 알고리즘을 수정하지 않았다. A의 CSV 출력은 B local baseline이 요구하는 `demand_id`, `catalog_id`, `category_id`, `label`, `quantity`, `is_substitutable`을 보존하며, V2.2 typed 계약 필드는 추가로 제공한다.

## 스모크 결과

실제 A 런타임 20건 출력으로:

- B baseline 입력: 성공
- Demand: 20
- Cluster: 19
- C 로컬 매칭 후보 비교: 3,800건
- 외부 LLM: 0

산출 위치는 로컬 전용 `data/processed/mvp_e2e_v2_2/`이다.

## 남은 계약 차이

1. 운영 B가 A의 `constraints`를 직접 소비하는 API 계약은 아직 저장소에서 확인되지 않았다.
2. B 운영 런타임의 원본 DB 재파싱과 A 결과 전송 방식 중 어느 것을 최종 경로로 할지는 Backend 통합 결정이 필요하다.
3. `label`은 단일 압축 표현이므로 `PREFER`/ANY_OF의 완전한 표현으로 사용하면 안 된다. downstream은 typed 계약을 우선해야 한다.

이 차이는 B 알고리즘 변경 없이 Backend API/DTO 합의로 해결할 통합 항목이다.

