# 오프라인 평가 도구

이 패키지는 MFDS 근거 산출물 생성, 사람/LLM 리뷰, 검색·제안 품질 평가,
시뮬레이션 결과 변환을 담당한다. 시간별 운영 배치에서는 로드하지 않는다.

- `evidence_analysis`, `function_claims`, `mfds_product_profiles`:
  원천 근거 분석과 catalog profile 생성
- `function_relation_*`, `llm_function_relation_review`:
  방향성 relation 후보·리뷰·승인 자료와 평가
- `product_candidate_graph`, `product_retrieval_evaluation`,
  `product_proposal_quality`: 상품 후보 그래프와 품질 평가
- `substitute_review_set`, `substitute_annotation`: 상품쌍 리뷰셋과 annotation 저장
- `backend_requests`: 시뮬레이션을 HTTP 전송 없는 dry-run 요청 묶음으로 변환

운영 domain 규칙과 공통 계약은 상위 패키지에서 재사용하며, 운영 코드가 이
패키지를 역으로 참조하지 않도록 한다. 승인된 relation을 읽는
`function_relation_registry`, ID·컬럼·fingerprint의
`function_relation_contract`, profile 상태의 `profile_contract`,
CPU 임베딩 helper `function_relation_embedding`은 상위 패키지에 남긴다.
이번 분리는 평가 알고리즘, artifact schema, fingerprint 계산법을 바꾸지 않는다.

## import와 실행 경로

필요한 모듈을 명시적으로 import한다. 상위 `demand_clustering`과
`evaluation.__init__`에서는 평가 함수를 한꺼번에 재노출하지 않는다.

```python
from moongcheap_ai.demand_clustering.evaluation.mfds_product_profiles import (
    build_mfds_product_profile_candidates,
)
from moongcheap_ai.demand_clustering.evaluation.backend_requests import (
    build_backend_plan_request_bundle,
    build_board_plan_request_bundle_from_simulation,
)
```

기존 최상위 평가 모듈을 import하던 외부 코드는 `evaluation` 경로로 옮겨야 한다.
단, 별도 Streamlit 리뷰 앱이 사용하는 `demand_clustering.substitute_annotation`은
기존 공개 함수·클래스·상수를 그대로 재노출하는 호환 모듈을 유지한다.

`scripts/evaluation/`과 `scripts/demand/`의 실행 경로·인자·출력 계약은 바뀌지
않는다. 평가 모듈 import와 CLI `--help`는 모델 다운로드나 API 호출을 하지 않는다.
실제 E5 평가에는 `embeddings` 선택 의존성과 모델이 필요하며, LLM 리뷰는
명시적인 실행 설정과 인증이 필요하다. 평가를 실행하는 것과 운영 CLI를 실행하는
것은 별도 절차다.
