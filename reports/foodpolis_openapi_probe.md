# Foodpolis 소매채널 판매정보 Open API Probe

확인 시각(UTC): 2026-09-09T02:29:07.736005+00:00

## 결론
- 상태: `FOODPOLIS_OPEN_API_ENDPOINT_NOT_FOUND`
- API Key 환경변수 설정 여부: `True` (값은 기록하지 않음)
- 공식 Retail Endpoint 설정 여부: `False`
- 현재 공식 문서에서 소매채널 판매정보의 공개 Endpoint 상세를 확인하지 못해 URL을 추측하거나 내부 Dashboard API를 호출하지 않았다.

## 공식 문서 확인
- Open API 목록: https://www.foodpolis.kr/food24/fo/io/api/apiData/list.do
- 서비스 소개: https://www.foodpolis.kr/food24/fo/cvd/main/fdGuide.do
- 소매채널 데이터 안내: https://www.foodpolis.kr/dfip/fo/cvd/main/fdGuide.do
- 소매채널 판매정보는 편의점·슈퍼마켓·하나로마트, 년월·지역·표준상품장 분류·제품명·판매건수·판매금액·판매단가로 설명되어 있다.

## Test Call
- HTTP Status: `None`
- Content-Type: `None`
- Top-level Schema: `NOT_AVAILABLE`
- Row Count: `None`
- HFF Row: API Endpoint가 확인된 경우에만 소량 응답에서 분류값을 검사한다.
- API Key는 Report·로그·Raw 응답에 저장하지 않는다.

## 상태값
- `FOODPOLIS_DATA_EXISTS=true`: 공식 서비스 소개에서 소매채널 판매정보가 설명됨.
- `FOODPOLIS_OPEN_API_AVAILABLE=false`: 현재 확인 가능한 공식 상세 Endpoint가 없음. Endpoint가 공식 문서에 확인되면 환경변수로 지정해 재실행한다.
- Endpoint가 확인될 때까지 기존 수동 Export 상태를 유지한다.
