# Model 1 / Model 2 선택 상태 V2

## 현재 결정

모델을 정하지 않은 상태가 아니다. MVP 적용 방식은 다음과 같이 결정되어 있다.

- **Model 1:** `kakaocorp/kanana-nano-2.1b-instruct`를 Facet 후보 생성 보조로 사용한다. 다만 Rule/통계 Evidence와 Human Review가 최종 승격 조건이다.
- **Model 2:** Rule-first Hybrid를 사용한다. `qwen2.5:7b-instruct`는 Rule이 해결하지 못한 양성 요구에만 fallback으로 호출한다.
- **LLM-only:** 운영 경로에서 사용하지 않는다.
- **Embedding:** Model 2가 아니라 B/C의 Clustering·Seller Matching 실험 대상으로 둔다.

## 안전한 fallback 경계

Qwen은 이미 `PARSED` 또는 `NONE`인 Rule 결과를 덮어쓰지 않는다. 명시적 제외나 충돌을 긍정 조건으로 변환하지 않으며, Taxonomy에 없는 Facet/Value를 만들지 않는다. typed constraint를 만들 수 없는 응답도 저장하지 않는다.

호출 실패, timeout, 누락 결과, Taxonomy 불일치, 정보가 없는 결과는 `REVIEW`로 남긴다. `A_MODEL2_FALLBACK_ENABLED` 기본값은 `false`이며, Ollama 서비스가 준비된 환경에서만 `true`로 바꾼다.

## 실험 해석

동일 200건에서 Rule-only 138/200(69%), Qwen model-only 118/200(59%), Rule-first Hybrid 142/200(71%)이었다. 80건 최신 실행은 model-only만 측정했으므로 Hybrid 성능 측정으로 대체하지 않는다. 이 수치는 프로젝트용 합성·검토 데이터의 상대 비교이며 실제 사용자 정확도 증명이 아니다.

## 검증 전제

- Model 1 결과는 자동 Taxonomy 확정이 아니다.
- Model 2 Gold 85건은 사람 최종 승인 전 후보이다.
- Qwen 실제 배포 검증은 Ollama 서비스와 모델 가중치가 필요하다.
- Backend 실제 ID/DB 계정, AWS/EKS Secret과 CI/CD 검증은 외부 환경에서 수행한다.
