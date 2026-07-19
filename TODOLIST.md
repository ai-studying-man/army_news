# 구현 TODOLIST

이 문서는 현재 저장소의 구현·테스트 상태를 반영한다. 완료 항목은 코드와 회귀 테스트로
검증했으며, 실제 Telegram 자격 증명 등록·시험 전송처럼 외부 승인이 필요한 작업만 남겨 둔다.

## 0. 수용 요구사항 기준

- [x] DAPA News와 수집·발행·Telegram 전송 아키텍처를 공유하되 Army News의 주제와 수집
      시간은 별도로 관리
- [x] 별칭 `육군`, `8사단`, `8기동사단`, `3070부대`, `오뚜기부대`와 지역 `양주`, `동두천`,
      `포천`, `연천`, `의정부`를 기본 설정으로 문서화
- [x] 지역 범위에 음주 사건·자연재해(지역+허용 주제만으로 포함 가능), 육군 관련 지자체
      업무·행사(관련 군사·육군 맥락 확인 필요) 포함
- [x] 수집 구간 D-1 14:00 KST–D-day 05:00 KST, 발행 06:30 KST로 고정
- [x] 동일 사건은 canonical URL·사건 anchor로 deduplicate하고 대표 원문 한 건만 전송
- [x] 항목은 `■ [사단] 기사 제목 (신문명)` 또는 `■ [지역] 기사 제목 (신문명)`, 원문
      HTTPS 링크, `- 한두문장으로 기사 요약`의 정확한 세 논리 줄(항목 사이 빈 줄) 사용
- [x] Bot Token과 Chat ID는 절대 커밋하지 않고 GitHub Secrets로만 관리
- [x] 채팅에 노출된 토큰은 운영 전에 회전하고, `chat_id`가 없으면 실제 전송하지 않음

## 1. 설정과 출처

- [x] `ARMY_BRIEF_CONFIG_JSON`의 `divisions[].name`, `aliases`, `regions` 스키마와
      `BriefConfig.from_mapping`/`from_env` 검증 구현·문서화
- [x] 초기 공개 RSS 목록과 우선순위를 `src/army_morning_brief/sources.py`에서 코드로
      명시·리뷰(국방부 보도자료 100, 국방부 공지사항 80, Google 별칭 60, Google 지역 40)
- [x] 공개 HTTPS 전용 및 Google News RSS 쿼리 URL 인코딩 검증
- [x] 설정·수집 모델의 잘못된 URL·빈 값·중복 별칭·시간대 누락 거부 테스트
- [ ] 공개 RSS URL·우선순위를 환경 설정으로 바꾸는 기능(현재 제품 범위 밖)

## 2. 수집과 시간 경계

- [x] Python 3.12, `uv`, src-layout 패키지와 KST 수집 창 구현
- [x] D-1 14:00 시작·D-day 05:00 종료 경계(양 끝 포함) 및 지연 실행 테스트
- [x] RSS/XML 파싱, HTTPS 리디렉션, HTML 설명 정규화, publisher provenance 보존
- [x] 명시적 timeout, 출처별 오류 격리, transient HTTP/transport 오류 최대 2회 bounded retry
      (출처별 60초 예산·대기 상한 포함)
- [x] oversized/잘못된 XML·DTD/entity·발행 시각 누락과 부분 출처 실패 회귀 테스트

## 3. 분류와 안전 필터

- [x] 포함·제외·동명이인·숫자 사단명·지역 오탐 fixture와 문맥 기반 분류
- [x] 별칭·지역·허용 지역 주제와 관련 군사·육군 맥락(지자체 업무·행사)을 구분 평가
- [x] 부대 위치·이동·병력 규모·장비 배치 등 민감 정보 추론 방지 필터 테스트
- [x] 카테고리별 최대 5건 및 부족분 미충원

## 4. 사건 중복 제거와 대표 기사

- [x] canonical URL·추적 쿼리 제거와 제목/설명 사건 anchor 기반 event dedupe
- [x] 서로 다른 언론사의 재전재·near-duplicate는 대표 한 건으로 collapse
- [x] 국가·지역·계약 상태·시험/양산·훈련/사고 등 구별 차원은 별도 사건으로 유지
- [x] 조회수·RSS 순위·출처 우선순위·최신순의 결정론적 대표 기사 ranking 및 반복 실행 안정성

## 5. 발췌식 브리핑

- [x] 선택된 단일 원문의 제목·설명에서 최대 두 문장을 발췌하고 새 사실을 생성하지 않음
- [x] `[사단]`/`[지역]` 제목, 이스케이프된 클릭 가능 HTTPS URL, 요약의 정확한 세 논리 줄과
      빈 줄 구분
- [x] HTML escape, Telegram 4096자 분할, 빈 그룹의 명시적 출력 테스트

## 6. CLI와 Telegram

- [x] 자격 증명 없이 `--dry-run` 성공, fixture·실시간 수집 경로와 safe diagnostics
- [x] 환경 변수 기반 Telegram 전송, HTTP/API 오류·rate limit bounded retry와 비밀 마스킹
- [x] `chat_id`가 없으면 fixture/네트워크 접근 전에 `--send` 차단
- [x] Bot Token·Chat ID의 GitHub Secrets 주입 경로와 노출 토큰 회전 절차 문서화
- [x] 같은 날짜 예약 메시지 중복 방지 및 `force_send` 수동 재발행 동작
- [ ] 운영자가 회전한 Secrets를 등록한 뒤 실제 Telegram 시험 전송 승인

## 7. 자동화와 최종 검증

- [x] 06:30 KST에 해당하는 GitHub Actions cron(`30 21 * * *` UTC) 및 `workflow_dispatch`
- [x] 예약/수동 실행 구분, 고정 concurrency, 날짜별 cache marker 중복 guard
- [x] workflow inspector가 pinned actions·read-only permissions·secret 인자 노출 부재를 검증
- [x] `uv run pytest`
- [x] `uv run ruff check .` 및 `uv run ruff format --check .`
- [x] `uv run basedpyright`
- [x] 자격 증명 없는 로컬 dry-run과 adversarial/window-boundary fixture 검토
- [ ] 승인 뒤 GitHub Secrets 등록 및 Telegram 시험 전송
