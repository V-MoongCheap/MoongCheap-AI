# 한국 건강기능식품 Consumer Evidence 접근 상태

## 에스더몰 고객리뷰

공개 고객리뷰 페이지는 확인했지만, 공식 약관에 크롤링 등 부정한 이용과 무단 자료 수집·외부 이용 제한이 명시되어 있다. 자동 Pilot과 전체 수집은 진행하지 않는다. 공식 Export 또는 별도 사용 허가가 있을 때만 로컬 처리기를 사용한다.

- 상태: `BLOCKED`
- Pilot 건수: `0`
- HFF 리뷰 건수: `0`
- Preflight: `reports/esthermall_collection_preflight.md`

## 식품정보24

공식 플랫폼의 소매채널 판매정보는 수동 대시보드·Export 절차로만 사용한다. 파일은 `data/raw/purchase/foodpolis/`에 넣는다. 파일이 없으면 `WAITING_FOR_MANUAL_DOWNLOAD`로 처리한다.

## LG U+

무료 공식 파일의 다운로드 경로와 로컬 파일을 확인하지 못했다. `data/raw/purchase/lg_uplus/`에 파일이 들어오기 전까지 `MISSING_VALID_SOURCE`로 기록한다.
