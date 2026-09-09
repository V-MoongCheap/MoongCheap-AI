# Demand Clustering Tests

Consumer Demand clustering 기능의 테스트를 둔다.

`test_substitute_admission.py`는 서비스 입력의 STRUCTURED, SEMANTIC_TEXT, NONE
모드가 기존 대체 catalog Board 후보에 적용되는 방식과 사용자 확인 전후의
상태·참가자 수 계약을 검증한다.

`test_backend_http.py`는 `X-Internal-Key` 인증, `batchId` 없는 DTO,
HTTP 재전송·리다이렉트 차단과 현재 상태 기준의 응답 집계를 검증한다.
`test_batch_recovery.py`는 요청 전 실패와 처리 후 응답 미수신을 구분하여,
다음 실행에서 DB를 새로 읽고 원상품 경로부터 다시 계획하는지 검증한다.
거절·수락·취소·만료 이후의 재조회와 기존 참가자 수 불변식도 포함한다.

오프라인 평가 테스트도 이 디렉터리에 두되, 대상 모듈은
`moongcheap_ai.demand_clustering.evaluation`에서 import한다.
`test_package_boundaries.py`는 운영 코드의 평가·스크립트 의존을 금지하고,
별도 Python 프로세스에서 선택 모델 라이브러리 없이 운영 진입점과 평가 모듈을
로드할 수 있는지 검사한다. 별도 리뷰 앱의 annotation import 호환성도 검증한다.
