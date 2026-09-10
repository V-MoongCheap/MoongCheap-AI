# 국내 건강기능식품 Raw Review Source Preflight

조사 기준일: 2026-09-09

공개 리뷰, robots.txt, 공식 약관, 정상 HTTP 접근성을 함께 확인했다. 일반적인 저작권 문구는 자동수집 금지로 보지 않았고, robots 차단·자동화 금지 약관·공개 원문 미확인은 명시적인 BLOCKED 사유로 기록했다.

## 요약
- 조사 후보: 45곳
- 이번 단계 추가 조사 후보: 20곳
- GREEN: 2곳
- BLOCKED: 43곳
- CONDITIONAL: 0곳
- Raw Review: 뉴트리미 공개 Pagination에서 423건 확보. 고정 3,000/5,000건을 목표로 삼지 않으며 신규 공개분만 증분 수집한다.
- Pilot Source: nutrime
- Pilot Review 수: 423
- Analysis Review 수: 399 (상품별 최대 50건 샘플링; Raw와 분리)
- Pilot Review Text Usable Rate: 100%
- Pilot Rating Coverage: 100%
- Pilot Product Mapping Rate: 82.27% (348/423)
- Pilot verified_purchase Coverage: 0% 확정 (공식 구매완료 정책 근거 미확인, 값은 null)
- HFF Review 처리: 공식 HFF 범위의 공개 후기 423건을 확보했으며, 상품 연결이 확인된 348건만 상품 기반 downstream 분석 대상으로 사용한다.
- Chongkundang Pilot: 0건. 공개 Review 요청이 비JSON/403 응답으로 반환되어 우회 없이 중단.
- verified_purchase: 공식 구매완료 정책 근거가 확인되지 않은 후보는 null로 처리해야 함.

## 판정표
| source | review_exists | hff_scope | public_access | product_linkable | robots_status | terms_status | bot_protection | purchase_verified_policy | pilot_possible | decision | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|
| esthermall | YES | YES | YES | YES | NOT_CONFIRMED | BLOCKS_CRAWLING_OR_UNAUTHORIZED_COLLECTION | CHALLENGE_REPORTED | UNKNOWN | NO | BLOCKED_TERMS | 공식 약관에 크롤링 및 무단 수집 제한이 확인되어 자동수집하지 않음. |
| gnm_natural_quality | YES | YES | YES | YES | REVIEW_PAGINATION_BLOCKED | NO_AUTOMATION_KEYWORD_FOUND | CAFE24_CHALLENGE_POSSIBLE | UNKNOWN | NO | BLOCKED_ROBOTS | robots.txt가 리뷰 페이지의 page 쿼리와 상품 페이지네이션을 차단함. |
| nutrione | PARTIAL | YES | YES | YES | NOT_CONFIRMED | NO_AUTOMATION_KEYWORD_FOUND | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰 robots는 확인했지만 공개 후기 원문과 상품 연결이 확인되지 않아 파일럿 대상으로 삼지 않음. |
| ckd_health | YES | YES | YES | YES | NOT_CONFIRMED | NO_AUTOMATION_KEYWORD_FOUND | UNKNOWN | UNKNOWN | GREEN | GREEN | robots가 전체 경로를 허용하고 공개 상품목록에서 건강기능식품·리뷰 수·상품 연결을 확인함. |
| nutrime | YES | YES | YES | YES | NOT_CONFIRMED | NO_AUTOMATION_KEYWORD_FOUND | UNKNOWN | UNKNOWN | GREEN | GREEN | robots가 전체 경로를 허용하고 공개 후기에서 상품명·본문·평점·작성일·상품 링크를 확인했으며 약관 금지 키워드가 없음. |
| lactiv | YES | YES | YES | YES | NOT_CONFIRMED | NO_AUTOMATION_KEYWORD_FOUND | UNKNOWN | NAVER_PAY_LABEL_ONLY | NO | BLOCKED_ROBOTS | robots.txt가 review pagination(page_6)을 명시적으로 차단함. |
| frombio | YES | YES | YES | PARTIAL | NOT_CONFIRMED | NO_AUTOMATION_KEYWORD_FOUND | UNKNOWN | UNKNOWN | NO | BLOCKED_ROBOTS | robots.txt가 board/article pagination을 명시적으로 차단함. |
| nutridday | PARTIAL | YES | YES | YES | NOT_CONFIRMED | NO_AUTOMATION_KEYWORD_FOUND | UNKNOWN | UNKNOWN | NO | BLOCKED_ROBOTS | robots.txt가 board/article pagination을 명시적으로 차단함. |
| nutricore | NOT_CONFIRMED | YES | YES | YES | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 상품 페이지는 확인했으나 공식몰 공개 리뷰 원문과 수집 가능한 연결을 확인하지 못함. |
| anguk_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰에서 공개 리뷰 원문을 확인하지 못했고 검색 결과는 외부 판매처 리뷰였음. |
| korea_eundan | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰 리뷰 원문은 확인하지 못했고 확인된 리뷰는 외부 플랫폼 자료였음. |
| doctorlin | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰 공개 리뷰 원문·상품 연결을 확인하지 못해 자동수집 후보에서 제외함. |
| funeat | YES | YES | YES | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰과 리뷰 존재 정황은 확인했지만 리뷰 원문·상품 연결·약관·robots 전체를 이번 preflight에서 검증하지 못함. |
| zkliving | YES | YES | YES | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 건기식 전문몰과 리뷰 기능은 확인했지만 정상 수집 가능성 및 정책 근거가 완결되지 않음. |
| kolon_health | YES | PARTIAL | YES | YES | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰 상품 리뷰 수는 확인했지만 건기식 범위 필터와 자동수집 정책을 완결 검증하지 못함. |
| kgc_cheongkwanjang | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 브랜드몰 후보이나 공개 리뷰 원문과 정상 수집 정책을 이번 조사에서 확인하지 못함. |
| pulmuone_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 건기식 브랜드몰 후보이나 공식 리뷰 원문·상품 연결을 자동수집 가능한 형태로 확인하지 못함. |
| dong_a_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 건강제품 판매 후보이나 공개 리뷰 수집 경로와 정책 근거가 이번 조사에서 확인되지 않음. |
| hy_himoon | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 건기식 전문 브랜드 후보이나 공식몰 리뷰 원문·상품 연결·정책 확인이 부족함. |
| cj_wellcare | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 건기식 공식몰 후보이나 공개 리뷰 수집 가능성과 정책을 이번 조사에서 완결하지 못함. |
| rockpid | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰 후보이나 공개 Raw Review와 상품 연결·정책을 이번 조사에서 완결 확인하지 못함. |
| hiwell_korea | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰 후보이나 공개 Raw Review와 정상 수집 정책을 검증하지 못함. |
| naturemade_korea | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 온라인스토어 후보이나 한국 공개 Review 원문과 수집 정책 근거가 부족함. |
| more_nature | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식몰 후보이나 공개 Review 원문·상품 연결·정책 확인이 완결되지 않음. |
| vitamin_village | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 전문몰 후보이나 공개 Review를 정상 수집할 수 있는지 확인하지 못함. |
| drs_best_korea | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 국내 공식 유통·판매몰 여부와 공개 Review 연결을 확인하지 못함. |
| ilyang_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 회사 홈페이지 후보이며 공식 건강기능식품몰과 공개 Review를 확인하지 못함. |
| dongkook_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 회사 사이트와 판매 채널을 구분할 수 있어 공개 Review Source로 확정하지 않음. |
| daewoong_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 회사 사이트 후보이나 자사몰 Review 원문과 상품 연결을 확인하지 못함. |
| gc_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 기업 사이트 후보이며 공개 건기식 Review 몰을 확인하지 못함. |
| ildong_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 브랜드·기업 사이트 후보이나 정상 공개 Review 경로를 검증하지 못함. |
| kwangdong_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 기업 사이트와 별개로 공개 Review를 연결할 수 있는 자사몰을 확인하지 못함. |
| hanmi_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 제약사 사이트 후보이나 건기식 자사몰 Review를 확인하지 못함. |
| yuyu_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 회사 사이트 후보이나 공개 Review와 상품 연결을 검증하지 못함. |
| huons_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 회사 사이트 후보이며 공개 건기식 Review 판매몰을 확인하지 못함. |
| d_mall_donga | NOT_CONFIRMED | PARTIAL | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 브랜드몰 후보이나 공개 Review 원문과 자동수집 정책을 확인하지 못함. |
| daesang_wellife | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 브랜드 후보이나 공개 Review와 Product 연결을 확인하지 못함. |
| vitatree | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 건기식 전문몰 후보이나 공식몰 여부와 공개 Review 정책을 확인하지 못함. |
| new_origin | NOT_CONFIRMED | PARTIAL | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 브랜드몰 후보이나 건강기능식품 범위와 공개 Review 연결을 확인하지 못함. |
| solgar_korea | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 국내 공식 판매몰 여부와 공개 Review 원문을 확인하지 못함. |
| gnc_korea | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 국내 공식 유통몰 여부와 공개 Review 접근 경로를 확인하지 못함. |
| denps | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 브랜드몰 후보이나 공개 Review·정책·Product 연결을 확인하지 못함. |
| celltrion_health | NOT_CONFIRMED | PARTIAL | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 공식 브랜드 사이트 후보이나 건기식 자사몰 Review 수집 조건을 확인하지 못함. |
| jw_health | NOT_CONFIRMED | PARTIAL | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 제약사 공식 사이트 후보이나 공개 Review와 상품 연결을 확인하지 못함. |
| pharmbio_health | NOT_CONFIRMED | YES | PARTIAL | PARTIAL | NOT_CONFIRMED | UNCLEAR | UNKNOWN | UNKNOWN | NO | BLOCKED_OTHER | 건기식 브랜드 후보이나 공식몰과 공개 Review를 검증하지 못함. |

## 직접 확인 근거
- GNM robots: `Allow: /`, `Allow: /product/`이나 `Disallow: /*?*page=` 및 `Disallow: /product/*?*page=`가 있어 100건 페이지네이션 경로는 차단됨.
- 뉴트리미 robots: `User-agent: *` 아래 `Allow: /`; 공식 약관 본문에서 자동수집 금지 키워드를 확인하지 못함.
- 종근당건강 robots: `User-agent: *` 아래 `Allow: /`; 공개 상품목록 GET 200과 상품별 리뷰 수를 확인함.
- 종근당건강 Review Pilot: 상품 상세의 공개 JavaScript 요청을 사용했으나 목록 응답이 비JSON/403으로 반환되어 0건에서 중단.
- 락티브 robots: `Disallow: /*page_6=`가 있어 상품 리뷰 페이지네이션 경로를 차단함.
- 프롬바이오·뉴트리디데이 robots: `Disallow: /*board*page=` 및 `Disallow: /*article*page=`가 있어 리뷰 페이지네이션을 차단함.
- 뉴트리원 robots: 공개 루트는 허용하지만 이번 점검에서 공식 공개 Review 원문과 상품 연결을 확인하지 못함.
- 에스더몰 약관: 크롤링을 부정한 이용 방법으로 규정하고 상품·콘텐츠의 무단 수집을 제한하는 조항을 확인함.

## 출처 링크
- `esthermall`: https://m.esthermall.co.kr/board/list.php?bdId=goodsreview
- `gnm_natural_quality`: https://gnm.co.kr/
- `nutrione`: https://nutrione.co.kr/
- `ckd_health`: https://ckdhcmall.co.kr/brandProductList.do?idx=43&pidx=1
- `nutrime`: https://www.nutrime.co.kr/board/?id=goods_review
- `lactiv`: https://www.lactiv.co.kr/product/락티브-베베키즈-팝핑스타-프로바이오틱스-유산균/205/category/52/display/1/
- `frombio`: https://m.frombio.co.kr/
- `nutridday`: https://nutridday.com/
- `nutricore`: https://nutricore.co.kr/
- `anguk_health`: https://www.ahn-gook.com/
- `korea_eundan`: https://www.koreaeundan.com/
- `doctorlin`: https://doctorlin.com/
- `funeat`: https://funeat.co.kr/
- `zkliving`: https://zkliving.kr/
- `kolon_health`: https://www.kolonhealth.com/goods/goods_list.php?cateCd=019002
- `kgc_cheongkwanjang`: https://www.kgc.co.kr/
- `pulmuone_health`: https://www.pulmuone-lohas.com/
- `dong_a_health`: https://www.dapharm.com/
- `hy_himoon`: https://www.hy.co.kr/
- `cj_wellcare`: https://www.cjwellcare.com/
- `rockpid`: https://rockpid.com/
- `hiwell_korea`: https://hiwellkorea.com/
- `naturemade_korea`: https://www.naturemade.co.kr/
- `more_nature`: https://morenature.co.kr/
- `vitamin_village`: https://vitaminvillage.co.kr/
- `drs_best_korea`: https://www.drsbest.co.kr/
- `ilyang_health`: https://www.ilyang.co.kr/
- `dongkook_health`: https://www.dkpharm.co.kr/
- `daewoong_health`: https://www.daewoong.co.kr/
- `gc_health`: https://www.gccorp.com/
- `ildong_health`: https://www.ildong.com/
- `kwangdong_health`: https://www.ekwangdong.com/
- `hanmi_health`: https://www.hanmi.co.kr/
- `yuyu_health`: https://www.yuyu.co.kr/
- `huons_health`: https://www.huons.com/
- `d_mall_donga`: https://www.dmall.co.kr/
- `daesang_wellife`: https://www.daesangwellife.com/
- `vitatree`: https://www.vitatree.co.kr/
- `new_origin`: https://www.neworigin.co.kr/
- `solgar_korea`: https://www.solgar.co.kr/
- `gnc_korea`: https://www.gnc.co.kr/
- `denps`: https://www.denps.com/
- `celltrion_health`: https://www.celltrionskincure.com/
- `jw_health`: https://www.jwpharma.co.kr/
- `pharmbio_health`: https://www.pharmbio.co.kr/

## 다음 단계
1. GREEN Source는 짧은 Pilot으로 접근성을 확인한 뒤 정상 공개 Pagination 범위까지 raw를 증분 수집한다.
2. 403·429·CAPTCHA·Challenge가 발생하면 즉시 중단하고 우회하지 않는다.
3. 수집 데이터에는 작성자명·닉네임·IP를 저장하지 않고, 의료효과 표현은 Facet 후보에서 제외한다.
