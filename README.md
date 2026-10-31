# Compound Research — 위대한 기업 관찰실

GitHub Pages에서 동작하는 **워런 버핏식 장기 투자 리서치 대시보드**입니다. 내가 선정한 기업 60개와 버크셔 해서웨이 13F(2026-06-30) 보유 평가액 상위 25개 기업을 함께 관찰합니다. 중복 제거 시 **81개**입니다.

**내재가치·적정 매수가 자동 산출은 하지 않습니다.** 이 사이트는 기업의 질을 장기 재무지표로 살펴보기 위한 보조 도구입니다.

## 기능

- 나의 위대한 기업 60개(사용자가 정한 순위 그대로), 버크셔 상위 25개, 공통 4개, 전체 81개 목록
- 티커·기업명 검색, 즐겨찾기, 재무자료가 있는 기업만 필터링
- 기업별 최근 10년 **최대 40개 분기**의 매출, 영업이익, 영업이익률, ROE, ROIC, 영업현금흐름, CapEx, FCF, FCF마진, 현금, 이자발생부채, 순부채, 이자보상배율, 희석 가중평균 주식 수
- 분기/TTM 및 5년/10년 차트 전환, 모든 분기 수치의 CSV 내보내기
- 경제적 해자 체크리스트, 개인 투자 메모, 즐겨찾기 (브라우저 `localStorage`)
- 외부 API를 통한 **최근 종가와 1년 일별 종가 차트** 수집 (실시간 가격 아님)
- 목표 매수가를 직접 정하고 GitHub Actions + Telegram으로 가격 조건 도달 알림 (선택)
- 주가 알림 조건과 투자 메모를 혼동하지 않도록 저장 장소 구분

## GitHub Pages 게시: 5단계

1. GitHub에서 새 저장소를 만듭니다. (예: `compound-research`)
2. 이 ZIP을 풀고 **안의 모든 파일과 숨김 폴더 `.github`까지** 저장소 루트에 업로드한 다음 `main` 브랜치에 커밋합니다.
3. 저장소 **Settings → Pages → Build and deployment → Source: GitHub Actions**를 선택합니다.
4. **Settings → Secrets and variables → Actions → New repository secret**에서 `SEC_USER_AGENT`를 추가합니다. 값은 **본인 이름(또는 조직 이름)과 실제 연락 이메일**이 들어간 문자열이어야 합니다. 예: `My Investment Research my-real-email@yourdomain.com` (이 예시 주소를 그대로 쓰지 마세요). SEC의 공정 접근 정책을 준수하기 위한 식별 정보이며 브라우저로 노출하지 않습니다.
5. **Actions → 데이터 수집 및 GitHub Pages 배포 → Run workflow**를 실행합니다. 실행 후 Pages 주소에서 사이트를 확인합니다. 수집 실패한 기업은 기존 값 또는 빈 그래프를 표시합니다.

최초 데이터 수집은 SEC에 여러 번 요청하므로 다소 시간이 걸릴 수 있습니다. GitHub Actions는 설정된 예약 시각에 반드시 즉시 실행되지는 않습니다.

### 데이터 수집 시 주의사항

- **사이트를 로컬 HTML 파일로 직접 더블클릭하면** JSON을 불러오지 못할 수 있습니다. `python -m http.server 8000`을 실행한 후 `http://localhost:8000`에서 확인하세요.
- `data/financials.json`과 `data/prices.json`은 처음에는 **빈 자료**입니다. 실제 SEC 및 시세 데이터를 Actions가 수집해야 40분기 차트가 나타납니다. 허구의 데이터를 실제 수치로 표시하지 않습니다.
- 일부 해외 기업의 SEC 공시는 EUR/GBP 등 보고통화를 사용합니다. 사이트는 별도 환율 변환 없이 **원래 보고통화**로 보여줍니다. 주가는 미국 상장 종목 기준 달러로 표시됩니다.
- SEC는 CORS를 지원하지 않으므로 **브라우저가 아니라 GitHub Actions의 Python**이 재무자료를 수집합니다. [SEC API 가이드](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- GitHub Actions는 SEC 정보를 72시간에 한 번(캐시 기준) 갱신하려고 하며 가격은 예약된 실행마다 갱신합니다. 가격 데이터는 Stooq의 지연 종가, 실패 시 Yahoo Finance 지연 종가를 조회하는 **비공식/제3자 데이터**이며 차단·누락될 수 있습니다. 실시간 알림이 아닙니다. 사용 전 이용약관을 검토하세요.
- SEC의 US-GAAP / IFRS 표준 태그를 이용하므로 기업에 따라 **지표가 일부 비어 있을 수 있습니다**. 연간·반기 위주로 보고하는 해외기업에서 특히 그렇습니다. 데이터가 없는데 임의로 40개 수치를 만드는 일은 없습니다.
- 버크셔 리스트는 `data/watchlists.json`에 저장된 **2026년 2분기말 고정 스냅샷**입니다. 신규 13F 발표 시 목록을 수동 갱신해야 합니다. 자동 리밸런싱 기능이 아닙니다.

## 목표 매수가 알림 (선택)

1. 사이트 왼쪽 **가격 알림 설정**에서 기업별 목표 매수가를 입력합니다.
2. **알림 설정 JSON 내보내기**를 클릭하고 결과 파일을 GitHub 저장소의 `config/alerts.json`으로 업로드/커밋합니다. 브라우저 `localStorage` 설정만으로 GitHub Actions 서버에 반영되지는 **않습니다**.
3. [Telegram BotFather](https://t.me/BotFather)에서 개인 봇을 만들고 메시지를 받을 채팅 ID를 확인합니다.
4. 저장소의 **Actions secrets**에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`를 추가합니다.
5. 워크플로가 **최근 종가 <= 목표 매수가** 조건을 처음 발견할 때 텔레그램 알림을 보냅니다. 같은 조건 반복 메시지를 막으며 주가가 목표가보다 2% 이상 높아지면 알림을 재설정합니다.

알림은 시장 데이터 제공업체 장애, GitHub Actions 실행 지연, 시세 지연, 네트워크 문제로 늦거나 누락될 수 있으며 실제 매수 주문은 일어나지 않습니다.

## 데이터와 계산 정의

| 지표 | 분기 표시 | TTM 표시 |
|---|---|---|
| 매출·영업이익·영업현금흐름·CapEx·FCF | 해당 분기 금액 | 최근 연속된 4분기 합계 |
| 영업이익률·FCF 마진 | 해당 분기 이익/매출 | 최근 4분기 합산 이익 / 합산 매출 |
| ROE | — | 최근 4분기 순이익 / 기간 초말 평균 자기자본 |
| ROIC | — | 최근 4분기 영업이익 × (1 − 유효세율) / 기간 초말 평균 투하자본 |
| 현금·부채·순부채 | 분기말 잔액 | 분기말 잔액 (합산 금지) |
| 이자보상배율 | — | TTM 영업이익 / TTM 이자비용 |
| 희석 가중평균 주식 수 | 분기 가중평균 | 최근 4분기 가중평균 수량 |

- **FCF = CFO − |CapEx|** (설비 외 투자·리스 등 세부 항목은 공급 기업의 계정과목별 차이가 있음).
- **투하자본 = 자기자본 + 이자발생부채 − 현금**이라는 근사치를 사용하며, 금융업의 ROIC는 표시하지 않습니다.
- **유효세율 = TTM 법인세 비용 / TTM 세전이익**, 0~50%일 때만 ROIC 계산에 사용합니다. 계산 불가능하면 ROIC는 공란입니다.
- 분기 10-Q는 일부 기업이 누적 매출·현금흐름만 공시하므로, 비교 가능한 누적 기간 차이로 개별 분기를 복원합니다. 연간 수치에서 3개 분기를 빼 Q4를 산출할 수 있습니다. 제공되지 않은 분기는 **null** 처리합니다.
- SEC 재작성, 인수합병, 부채 분류, 해외회계 기준, 자사주 분할, 회계연도 변경 등에 따라 자동 계산은 오차가 있을 수 있습니다. 공시 원문과 대조하세요.

## 프로젝트 구조

```text
index.html                 메인 웹페이지
assets/style.css           모바일 대응 스타일
js/app.js                  목록·그래프·메모·CSV UI
config/alerts.json         GitHub Actions에 적용하는 목표 매수가
scripts/update_financials.py  SEC Company Facts 파서
scripts/update_prices.py      종가 조회 + 선택형 Telegram 알림
.github/workflows/publish.yml 수집, 데이터 커밋, Pages 배포
requirements.txt           Python 의존성
data/watchlists.json       관심기업 및 버크셔 13F 목록
data/financials.json       수집된 재무 시계열 (처음에는 비어 있음)
data/prices.json           수집된 주가 데이터 (처음에는 비어 있음)
data/alert_state.json      반복 알림 방지 상태
```

## 실행 및 검증

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m http.server 8000
# localhost:8000 에서 열기
```

로컬에서 실제 데이터를 수집하려면 `SEC_USER_AGENT` 환경변수에 유효한 연락처를 넣은 후 `python scripts/update_financials.py`를 실행하세요.

원자료: [SEC Company Facts API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [버크셔 2026 Q2 13F](https://www.sec.gov/Archives/edgar/data/1067983/000119312526352200/0001193125-26-352200-index.htm). 공개 13F는 현시점 실보유와 다를 수 있습니다.

**면책:** 본 사이트는 개인 연구 목적이며 정확성, 적시성 또는 투자 성과를 보장하지 않습니다.
