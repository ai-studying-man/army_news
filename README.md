# ARMY Morning Brief

대한민국 육군 출근자를 위한 일일 공개 뉴스 브리핑 자동화 프로젝트입니다. Python 3.12와
`uv`를 사용하며, 공개된 HTTPS 출처에서 확인한 기사만 결정론적 규칙으로 수집·분류·중복
제거합니다. DAPA News와 수집·발행·Telegram 전송 아키텍처를 공유하지만, Army News는
육군 및 담당 지역이라는 주제와 별도의 수집 시간 창을 사용합니다.

## 핵심 원칙

- 수집원은 로그인 없이 접근 가능한 공개 HTTPS 페이지와 피드로 제한합니다.
- 요약은 기사 제목·설명·본문에서 확인되는 문장을 발췌해 구성합니다. 여러 기사를 합쳐 새
  사실을 만들거나 전망을 생성하지 않습니다.
- 사단 정식 명칭·별칭·담당 지역은 `ARMY_BRIEF_CONFIG_JSON` 환경 변수의 JSON 설정으로
  관리합니다. 설정을 바꾸기 위해 수집·분류 코드를 수정할 필요가 없습니다.
- Army News의 부대 별칭은 `육군`, `8사단`, `8기동사단`, `3070부대`, `오뚜기부대`이고,
  담당 지역은 `양주`, `동두천`, `포천`, `연천`, `의정부`입니다.
- 지역 범위에는 해당 지역의 음주 사건과 자연재해를 포함합니다. 이 두 주제는 담당 지역과
  허용 주제가 확인되면 육군 맥락을 요구하지 않습니다. 육군 관련 지자체 업무·행사는
  관련 군사·육군 맥락이 확인되는 공개 기사만 선별합니다.
- 부대 위치, 이동 경로, 병력 규모, 장비 배치 등 공개 기사에 없는 민감 정보를 추론하지
  않습니다.
- Telegram 자격 증명을 등록하기 전에 반드시 로컬 dry-run 결과를 검토합니다.

## 수집 시간 창

정기 전송은 매일 06:30 KST입니다. 수집 구간은 **D-1 14:00 KST부터 D-day 05:00 KST까지**로
고정하고, 05:00 이후 새 기사는 다음 브리핑으로 넘깁니다. 모든 비교는 KST 기준의 시간대
인식 값으로 수행합니다. DAPA News와 Army News는 이처럼 주제와 수집 시간 창이 다르며,
공통 아키텍처를 공유한다는 이유로 규칙을 섞지 않습니다.

## 설정(JSON)

현재 구현은 사단의 정식 명칭, 검색 별칭, 담당 지역을 `ARMY_BRIEF_CONFIG_JSON`으로
재정의합니다. JSON 객체의 `divisions`는 하나 이상의 규칙을 담고, 각 규칙은 비어 있지
않은 문자열 `name`과 중복 없는 문자열 배열 `aliases`, `regions`를 가져야 합니다. 아래
예시는 그대로 `BriefConfig.from_mapping`/`BriefConfig.from_env`로 검증되는 설정입니다.

```json
{
  "divisions": [
    {
      "name": "제8기동사단",
      "aliases": ["육군", "8사단", "8기동사단", "3070부대", "오뚜기부대"],
      "regions": ["양주", "동두천", "포천", "연천", "의정부"]
    }
  ]
}
```

셸에서는 이 객체를 JSON 문자열로 `ARMY_BRIEF_CONFIG_JSON`에 넣습니다. 변수가 없으면
위 기본 규칙을 사용하며, 잘못된 JSON·빈 값·중복 별칭은 거부합니다.

초기 공개 RSS 목록과 우선순위는 설정 파일이 아니라
[`src/army_morning_brief/sources.py`](src/army_morning_brief/sources.py)에서 명시적으로
코드 리뷰했습니다. 국방부 보도자료(priority **100**)와 국방부 공지사항(priority **80**)을
먼저 읽고, 설정된 사단 별칭 Google News RSS(priority **60**)와 지역 Google News RSS
(priority **40**)를 보조 출처로 추가합니다. 공개 출처 URL·우선순위를 환경 JSON으로 바꾸는
기능은 현재 범위에 포함하지 않습니다.

사단 별칭만 일치한 기사는 군 관련으로 확정하지 않으며 제목·출처·본문의 육군 업무 맥락을
확인합니다. 지역 기사는 위 허용 주제 기준을 적용하고, 지자체 업무·행사에는 관련
군사·육군 맥락을 추가 확인합니다.

## 개발 환경

필요 조건은 Python 3.12와 `uv`입니다.

```powershell
uv python install 3.12
uv sync --dev
Copy-Item .env.example .env
```

현재 구현과 회귀 테스트를 검증하는 명령은 다음과 같습니다. 네 명령 모두 통과해야 문서의
구현 완료 상태로 간주합니다.

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
```

수집기는 출처별 오류를 격리하고 transient HTTP/transport 오류를 최대 2회 재시도하며,
출처별 60초 예산과 지수형 대기 상한을 적용합니다. 파이프라인은 canonical URL과 사건
anchor를 사용해 다른 언론사의 같은 사건을 대표 원문 한 건으로 합치고, 상태·국가·지역이
다른 사건은 유지합니다. 분류·중복 제거·KST 경계·보안 반례는 `tests/`의 fixture 테스트로
검증합니다.

구현에서 제공하는 수집 전용 명령은 아래 형태로 고정합니다. `--dry-run`은 Telegram을
호출하지 않고 결과와 출처 URL만 로컬에 출력해야 합니다.

```powershell
uv run python -m army_morning_brief --dry-run
```

dry-run은 빈 `.env`로 검토하고, 실제 운영 값은 검토 후 GitHub Actions Secrets에 아래
이름으로만 등록합니다. 세 값은 모두 GitHub Secrets로 관리하며, 실제 값은 문서·코드·로그·
커밋에 절대 남기지 않습니다. 채팅에 노출된 토큰은 운영 전 반드시 폐기·회전합니다.
`TELEGRAM_CHAT_ID`는 기존 개인 대화 수신자이고 `TELEGRAM_CHANNEL_ID`는 브로드캐스트 채널
수신자입니다. 전송 단계는 두 수신자 ID를 쉼표로 결합해 동일한 브리핑을 두 곳에 순서대로
보냅니다. 두 수신자 ID가 없으면 실제 전송을 시작하지 않습니다.

```text
TELEGRAM_BOT_TOKEN=<secret>
TELEGRAM_CHAT_ID=<secret>
TELEGRAM_CHANNEL_ID=<secret>
```

## Telegram 항목 형식

Telegram HTML 메시지는 `['YY.M.D.(요일), 아침 언론 모니터 결과]`로 시작합니다. 기사가
없는 분류는 `※ 사단, 지역 관련 보도 없음`처럼 한 줄로 합쳐 표시합니다. 각 기사는
`■ [분류] 제목 (언론사)`, 클릭 가능한 링크, `-`로 시작하는 50자 이내 요약 순서이며,
사단·지역·외교/북한 순으로 배치합니다. RSS가 실제 설명을 제공하면 첫 문장을 사용하고,
제목과 언론사만 제공하면 제목에 명시된 사실만 `관련 소식임` 문장으로 정리합니다.

```text
['26.7.20.(월), 아침 언론 모니터 결과]

※ 지역 관련 보도 없음

■ [사단] 기사 제목 (언론사)
<a href="https://example.com/article">기사 링크 바로가기</a>
- 기사 내용을 50자 이내로 요약한 문장
```

제품 범위와 안전 기준은 [PRD.md](PRD.md), 구현 순서는 [TODOLIST.md](TODOLIST.md)에
정리되어 있습니다.

## 자동 실행 운영

GitHub Actions는 매일 06:30 KST(`30 21 * * *` UTC)에 예약됩니다. 예약 실행은 지연될 수
있고 공개 저장소 활동이 오래 없으면 비활성화될 수 있습니다. Secrets 설정, 수동 dry-run,
강제 재전송, 날짜별 중복 방지 한계와 현재 Telegram 자격 증명 인계 대기 상태는
[운영 문서](docs/OPERATIONS.md)를 따릅니다.
