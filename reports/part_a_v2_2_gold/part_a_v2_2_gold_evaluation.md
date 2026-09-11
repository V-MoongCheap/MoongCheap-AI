# Part A V2.2 Gold 평가 결과

이 평가는 finalized Gold의 기대값과 현재 수요 조건 파서의 결과를 비교한다.
각 행은 status, parser-level mode, effective mode, constraints, preference groups, passthrough를 독립적으로 비교한다.

- 전체 행: 200
- 전체 row pass: 146/200

## 파티션별 결과

| Partition | Rows | Status | Parser Mode | Effective Mode | Constraints | Groups | Passthrough | Row Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| DEV | 100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 | 100/100 |
| HOLDOUT | 50 | 32/50 | 31/50 | 32/50 | 31/50 | 50/50 | 50/50 | 31/50 |
| CHALLENGE | 50 | 15/50 | 20/50 | 15/50 | 28/50 | 42/50 | 44/50 | 15/50 |

## 실패 사례

| Case | Partition | Mismatch | Input |
|---|---|---|---|
| part-a-v2-2-106 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 제품을 고를 때 1일 2회 포함 여부를 먼저 봐요. |
| part-a-v2-2-107 | HOLDOUT | parser_mode_match, constraints_match | 이번 요청에서는 정 없는 제품을 찾아주세요. |
| part-a-v2-2-108 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 겔 포함 여부를 중요하게 봐요. |
| part-a-v2-2-112 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 환 포함 여부를 중요하게 봐요. |
| part-a-v2-2-113 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 인삼 포함 여부를 중요하게 봐요. |
| part-a-v2-2-114 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 액상 포함 여부를 중요하게 봐요. |
| part-a-v2-2-115 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 제품을 고를 때 액상 포함 여부를 먼저 봐요. |
| part-a-v2-2-118 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 1일 5회 포함 여부를 중요하게 봐요. |
| part-a-v2-2-120 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 정 포함 여부를 중요하게 봐요. |
| part-a-v2-2-122 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 1일 2회 포함 여부를 중요하게 봐요. |
| part-a-v2-2-123 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 과립 포함 여부를 중요하게 봐요. |
| part-a-v2-2-124 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 캡슐 포함 여부를 중요하게 봐요. |
| part-a-v2-2-126 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 감태추출물 포함 여부를 중요하게 봐요. |
| part-a-v2-2-130 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 1일 1회 포함 여부를 중요하게 봐요. |
| part-a-v2-2-132 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 글루코사민 제품 포함 여부를 중요하게 봐요. |
| part-a-v2-2-139 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 제품을 고를 때 환 포함 여부를 먼저 봐요. |
| part-a-v2-2-143 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 쏘팔메토 열매 추출물 포함 여부를 중요하게 봐요. |
| part-a-v2-2-146 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 칼슘 포함 여부를 중요하게 봐요. |
| part-a-v2-2-149 | HOLDOUT | status_match, parser_mode_match, effective_mode_match, constraints_match | 오메가-3지방산함유유지가 포함된 제품을 찾습니다. |
| part-a-v2-2-151 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 정 포함은 필수이고, 분말 포함은 선호합니다. |
| part-a-v2-2-152 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 환 포함은 필수이고, 정 포함은 선호합니다. |
| part-a-v2-2-153 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 정 포함은 필수이고, 기타 포함은 선호합니다. |
| part-a-v2-2-154 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 액상 포함은 필수이고, 과립 포함은 선호합니다. |
| part-a-v2-2-155 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 환 포함은 필수이고, 과립 포함은 선호합니다. |
| part-a-v2-2-156 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 젤리 포함은 필수이고, 밀크씨슬(카르두스 마리아누스) 추출물 포함은 선호합니다. |
| part-a-v2-2-157 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 쏘팔메토 열매 추출물 포함은 필수이고, 쏘팔메토 열매 추출물, 옥타코사놀 함유 유지 포함은 선호합니다. |
| part-a-v2-2-158 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 오메가-3지방산함유유지 제품 포함은 필수이고, 필수 지방산 포함은 선호합니다. |
| part-a-v2-2-159 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 과립 포함은 필수이고, 바 포함은 선호합니다. |
| part-a-v2-2-160 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 겔 포함은 필수이고, 프로바이오틱스 포함은 선호합니다. |
| part-a-v2-2-161 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 프로폴리스추출물(원료성) 포함은 필수이고, 프로폴리스추출물(원료성), 프로폴리스추출물 제품 포함은 선호합니다. |
| part-a-v2-2-162 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 판토텐산, 비오틴 포함은 필수이고, 바나바잎 추출물, 크롬 포함은 선호합니다. |
| part-a-v2-2-163 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 인삼 포함은 필수이고, 인삼제품 포함은 선호합니다. |
| part-a-v2-2-164 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 감마리놀렌산 함유 유지 포함은 필수이고, 저분자콜라겐펩타이드 포함은 선호합니다. |
| part-a-v2-2-165 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 미강주정추출물 포함은 필수이고, 유단백가수분해물(락티움) 포함은 선호합니다. |
| part-a-v2-2-166 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, preference_groups_match | 비타민 C 또는 비타민 D 중 하나면 괜찮아요. |
| part-a-v2-2-167 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, preference_groups_match | 바나바잎 추출물 또는 녹차추출물, 바나바잎 추출물 중 하나면 괜찮아요. |
| part-a-v2-2-168 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, preference_groups_match | 차전자피식이섬유 또는 가르시니아캄보지아 추출물 중 하나면 괜찮아요. |
| part-a-v2-2-169 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, preference_groups_match | 1일 1회 또는 1일 2회면 괜찮아요. |
| part-a-v2-2-170 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, preference_groups_match | 1일 1회 또는 1일 2회 중 하나면 괜찮아요. |
| part-a-v2-2-171 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, preference_groups_match | 1일 2회 또는 1일 1회면 괜찮아요. |
| part-a-v2-2-172 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, preference_groups_match | 정 또는 캡슐 중 하나면 괜찮아요. |
| part-a-v2-2-173 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, preference_groups_match | 캡슐 또는 분말이면 괜찮아요. |
| part-a-v2-2-174 | CHALLENGE | status_match, effective_mode_match, passthrough_match | 개별 포장이라 휴대하기 편하면 좋겠어요. |
| part-a-v2-2-175 | CHALLENGE | status_match, effective_mode_match, passthrough_match | 섭취 후 속이 편안하면 좋겠어요. |
| part-a-v2-2-176 | CHALLENGE | status_match, effective_mode_match, passthrough_match | 맛이 강하지 않고 부담 없으면 좋겠어요. |
| part-a-v2-2-177 | CHALLENGE | status_match, effective_mode_match, passthrough_match | 보관하기 쉬운 포장이면 좋겠어요. |
| part-a-v2-2-178 | CHALLENGE | status_match, effective_mode_match, passthrough_match | 물에 잘 섞이면 좋겠어요. |
| part-a-v2-2-179 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match, passthrough_match | 알약이 작아 삼키기 편하면 좋겠어요. |
| part-a-v2-2-180 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 겔은 반드시 포함하고, 겔은 제외해주세요. |
| part-a-v2-2-181 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 감태추출물은 반드시 포함하고, 감태추출물은 제외해주세요. |
| part-a-v2-2-182 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 액상은 반드시 포함하고, 액상은 제외해주세요. |
| part-a-v2-2-183 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 녹차추출물, 바나바잎 추출물 조합은 반드시 포함하고, 같은 조합은 제외해주세요. |
| part-a-v2-2-184 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 과립은 반드시 포함하고, 과립은 제외해주세요. |
| part-a-v2-2-185 | CHALLENGE | status_match, parser_mode_match, effective_mode_match, constraints_match | 마리골드꽃추출물, 베타카로틴 조합은 반드시 포함하고, 같은 조합은 제외해주세요. |

## 산출물

- 상세 결과: `reports/part_a_v2_2_gold/part_a_v2_2_gold_evaluation_results.csv`
- 요약 JSON: `reports/part_a_v2_2_gold/part_a_v2_2_gold_evaluation_summary.json`

참고: Gold의 expected 값은 정답 기준이며, 실패 행은 파서 또는 Gold 기대값의 추가 검토 대상이다. 자동으로 수정하지 않는다.
