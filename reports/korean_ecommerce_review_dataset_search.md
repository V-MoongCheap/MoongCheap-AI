# 한국 이커머스 리뷰 Dataset 조사 결과

## 조사 목적

기존 Nutrime Review 423건을 보강할 수 있는 공개 한국 이커머스 Consumer Review 원자료를 조사했다. 이번 조사의 usable 기준은 단순한 한국어 리뷰 텍스트가 아니라, 건강기능식품 여부를 판별할 수 있는 상품명 또는 카테고리와 리뷰를 연결할 수 있는 구조를 갖추는 것이다.

합성·생성 데이터와 외국 리뷰는 Consumer Evidence에 사용하지 않는다. 원자료를 확인하지 못한 프로젝트 소개 페이지도 실제 Dataset으로 판정하지 않는다.

## 판정 기준

| 상태 | 의미 |
|---|---|
| USABLE_HFF_DIRECT | 건강기능식품 리뷰임을 Dataset 자체에서 확인 가능 |
| USABLE_HFF_FILTERABLE | 한국 이커머스 리뷰이며 상품명·카테고리로 HFF 필터 가능 |
| KOREAN_REVIEW_EXPRESSION_ONLY | 한국 리뷰지만 상품·카테고리 연결 정보가 없어 표현 참고만 가능 |
| FOREIGN_REFERENCE | 외국 플랫폼 또는 외국어 데이터 |
| SYNTHETIC | 생성·시뮬레이션 데이터 |
| NO_RAW_REVIEW | 리뷰 수·평점 등 집계만 있고 원문이 없음 |
| UNVERIFIED | 원자료 파일 또는 스키마를 공개적으로 확인하지 못함 |
| BLOCKED_ACCESS | 다운로드 또는 원자료 접근이 막혀 실제 검증 불가 |

## 후보 조사 결과

| Dataset / Source | Source | 확인된 규모 | 한국 리뷰 | Raw Review | Product ID | Product Name | Category | HFF Filterable | 판정 | 근거 |
|---|---|---:|---|---|---|---|---|---|---|---|
| Naver Shopping Corpus | `bab2min/corpus/sentiment/naver_shopping.txt` | 200,000 | YES | YES | NO | NO | NO | NO | KOREAN_REVIEW_EXPRESSION_ONLY | 실제 파일은 별점과 리뷰 텍스트 2개 필드이며 2020년 6~7월 수집 |
| SimKoR | `DILAB-HYU/SimKoR` | 30,000 | YES | NO | NO | NO | NO | NO | KOREAN_REVIEW_EXPRESSION_ONLY | 네이버 쇼핑 리뷰를 문장 유사도 pair로 재구성한 파생 Dataset |
| KR3 | `yejoon-lee/kr3` | 459,021(+182,741) | YES | YES | NO | NO | Restaurant category | NO | UNVERIFIED / 제외 | 한국 음식점 리뷰 Dataset이며 이커머스 상품 리뷰가 아님 |
| Coupang fake reviewer dataset | `festring/coupang_review_dataset` | 759 accounts | YES | NO | NO | NO | NO | NO | NO_RAW_REVIEW | 리뷰 원문이 아니라 계정 수준 특징과 가짜 리뷰어 라벨 |
| Coupang review project | `hw1004/Data-Full-Stack-Project` | 약 160,000 reviews 주장 | YES | 프로젝트 설명상 YES | 미확인 | 미확인 | 미확인 | 미확인 | UNVERIFIED | 공개 저장소에서 실제 원자료 파일·스키마를 확인하지 못함 |
| Naver Shopping Review Analysis | `hyorea1/Naver-Shopping-Review-Analysis` | 43,596 + 423 주장 | YES | 프로젝트 설명상 YES | 미확인 | 미확인 | 미확인 | 미확인 | UNVERIFIED | 수집 코드와 결과 설명은 있으나 재현 가능한 공개 Raw 파일을 확인하지 못함 |
| ICEB Naver Shopping study data | 논문 부록/연구자료 | 미상 | YES | 논문상 YES | 미상 | 논문상 YES | 논문상 YES | 미확인 | UNVERIFIED | 상품명·카테고리·리뷰가 언급되지만 공개 다운로드 파일을 확인하지 못함 |
| Apify Naver/Coupang Actors | 상용 수집 도구 | 실행 시 생성 | YES | 실행 가능 | YES | YES | 일부 | 가능 | BLOCKED_ACCESS | 정적 공개 Dataset이 아니며 실행·약관·비용 검토가 별도 필요 |
| GearDel Naver Shopping catalog | Dataset catalog | 200,000 주장 | YES | 원본 링크 참조 | NO | NO | NO | NO | KOREAN_REVIEW_EXPRESSION_ONLY | 원본을 호스팅하지 않는 카탈로그이며 실제 구조는 bab2min 원본과 동일 |

## 세부 검증

### Naver Shopping Corpus

원본 저장소의 README와 실제 파일 구조를 확인했다. `naver_shopping.txt`는 2020년 6~7월 네이버 쇼핑에서 수집한 20만 행이며, 각 행은 별점과 리뷰 텍스트로 구성된다. 3점 리뷰는 제외되었고 1~2점과 4~5점 비율을 맞추기 위한 샘플링이 적용되어 자연 발생 분포가 아니다.

상품 ID, 상품명, 카테고리, 브랜드, 리뷰 날짜가 없어 건강기능식품 필터와 MFDS Product Mapping을 수행할 수 없다. 따라서 이 자료를 기존 Consumer Evidence에 병합하지 않고, 한국 쇼핑 리뷰 표현의 보조 참고 자료로만 기록한다.

### SimKoR

원본 네이버 리뷰를 그대로 보존한 Dataset이 아니라 텍스트 두 개를 묶은 문장 유사도 Dataset이다. 상품 단위 연결과 원 리뷰 provenance가 사라져 있으므로 Facet Evidence나 HFF 필터에 사용할 수 없다.

### 한국 이커머스 프로젝트 저장소

Coupang/Naver 리뷰를 수집했다는 프로젝트는 일부 확인되었지만, 프로젝트 설명만으로는 실제 CSV/JSON 원자료와 라이선스, 상품-리뷰 연결 필드를 검증할 수 없었다. 설명에 등장하는 행 수를 실제 Dataset 행 수로 승격하지 않는다.

## HFF Filter Pilot 결과

이번 조사에서 실제로 다운로드해 스키마를 확인한 공개 Dataset 중 `USABLE_HFF_DIRECT` 또는 `USABLE_HFF_FILTERABLE` 후보는 0개다. 따라서 새 Dataset에 대한 HFF Pilot, MFDS Mapping, Review Evidence Extraction은 실행하지 않았다.

현재 확정된 한국 HFF Review 기준값은 기존 Nutrime Corpus를 유지한다.

| Metric | Current |
|---|---:|
| Raw Korean HFF Review | 423 |
| HFF mapped Review | 348 |
| Korean Review Source | 1 |
| Review Evidence | 360 |
| Review-supported Facet | 14 |
| Source 2+ | 8 |
| Source 3+ | 4 |

## 결론

1. 이번 조사 범위에서 기존 Nutrime에 바로 추가할 수 있는 공개 한국 HFF Review Dataset은 발견하지 못했다.
2. `bab2min/corpus`는 20만 건으로 규모는 크지만 상품·카테고리 정보가 없어 이번 목적에는 부적합하다.
3. 한국어 표현 학습 또는 감성 분류 보조에는 사용할 수 있으나, Model 1 Consumer Evidence와 HFF Facet 근거로 사용하면 출처와 상품 연결을 잃게 된다.
4. 합성 데이터, 외국 리뷰, 상품 메타데이터만 있는 자료, 원자료를 확인하지 못한 프로젝트 설명은 제외했다.
5. 현재는 Nutrime 423건을 유지하고, 향후 실제 Product Name/Product ID/Category가 포함된 승인 가능한 Dataset이 확보될 때만 기존 Review Pipeline에 추가한다.

## Sources

- https://github.com/bab2min/corpus/tree/master/sentiment
- https://github.com/bab2min/corpus/blob/master/sentiment/naver_shopping.txt
- https://huggingface.co/datasets/DILAB-HYU/SimKoR
- https://github.com/yejoon-lee/kr3
- https://github.com/festring/coupang_review_dataset
- https://github.com/hw1004/Data-Full-Stack-Project
- https://github.com/hyorea1/Naver-Shopping-Review-Analysis
- https://huggingface.co/cringepnh/koelectra-korean-shopping-rating

## Version

- Commit: `fedfc84`
- Push: not performed
