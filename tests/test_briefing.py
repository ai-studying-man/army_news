from datetime import UTC, datetime, timedelta, timezone

import pytest

from army_morning_brief.briefing import concise_summary, extractive_summary, render_briefing_html
from army_morning_brief.classification import ClassificationResult, OutputGroup
from army_morning_brief.models import Article, Source
from army_morning_brief.pipeline import SelectedArticle
from army_morning_brief.telegram import split_html_message

KST = timezone(timedelta(hours=9))


def selected(
    *,
    title: str = "8사단 <안전> 점검 & 교육",
    description: str = "첫 문장에 <점검> 사실이 있다. 둘째 문장도 기사에 있다!",
    url: str = 'https://news.example/a?x=1&unsafe="yes"',
    source: str = "공식 & 뉴스",
    group: OutputGroup = OutputGroup.DIVISION,
) -> SelectedArticle:
    item = Article(
        title=title,
        description=description,
        url=url,
        published_at=datetime(2026, 7, 18, 6, 5, tzinfo=KST),
        source=Source(name=source, url="https://news.example/feed"),
    )
    return SelectedArticle(item, ClassificationResult(group, "8사단"))


def test_extractive_summary_uses_one_source_sentence() -> None:
    item = selected()

    summary = extractive_summary(item)

    assert summary == "첫 문장에 <점검> 사실이 있다."
    assert summary in item.article.description
    assert "둘째 문장" not in summary


@pytest.mark.parametrize("description", ["", "   ", "\t\n"])
def test_extractive_summary_omits_empty_description(description: str) -> None:
    item = selected(title="원문 제목 그대로", description=description)

    assert extractive_summary(item) is None


def test_extractive_summary_replaces_redundant_title_and_publisher() -> None:
    item = selected(
        title="8사단 훈련 소식",
        description="8사단 훈련 소식 - 공식 & 뉴스",
    )

    assert extractive_summary(item) is None

    plain_space_item = selected(
        title="8사단 훈련 소식",
        description="8사단 훈련 소식 공식 & 뉴스",
    )

    assert extractive_summary(plain_space_item) is None

    google_suffix_item = selected(
        title="유럽 방공시장 커지는데 K방산 새 돌파구는 현지생산 - 이뉴스투데이",
        description="유럽 방공시장 커지는데 K방산 새 돌파구는 현지생산",
        source="Google 뉴스: 국방·안보",
    )

    assert extractive_summary(google_suffix_item) is None


def test_concise_summary_uses_source_content_and_omits_title_only_fallback() -> None:
    source_backed = selected(description="실제 기사 첫 문장에 확인된 내용이 있다. 둘째 문장이다.")
    title_backed = selected(
        title="육군 제6보병사단, 철원과 포천 일대에서 전투지휘검열 훈련 실시",
        description="",
    )

    assert concise_summary(source_backed) == "실제 기사 첫 문장에 확인된 내용이 있다."
    assert concise_summary(title_backed) is None


def test_renderer_uses_final_digest_template_and_escapes_dynamic_html() -> None:
    html = render_briefing_html(
        {
            OutputGroup.DIVISION: (
                selected(),
                selected(
                    title="8사단 추가 소식",
                    description="추가 기사 첫 문장.",
                    url="https://news.example/division-2",
                ),
            ),
            OutputGroup.REGION: (
                selected(title="양주 산불 대응", group=OutputGroup.REGION),
                selected(
                    title="동두천 협력 소식",
                    description="지역 기사 첫 문장.",
                    url="https://news.example/region-2",
                    group=OutputGroup.REGION,
                ),
            ),
            OutputGroup.DIPLOMACY_NORTH_KOREA: (
                selected(
                    title="북한 군사 동향",
                    group=OutputGroup.DIPLOMACY_NORTH_KOREA,
                ),
            ),
        },
        datetime(2026, 7, 18, 21, 30, tzinfo=UTC),
    )

    assert html.startswith("💡26년 7월 19일(일) 육군 브리핑\n")
    assert "※ 육군, 군단, 국방·안보, 칼럼·사설 관련 보도 없음" in html
    assert html.index("[사단]") < html.index("[지역]")
    assert html.index("[지역]") < html.index("[외교·북한]")
    assert (
        "[사단]\n"
        "1. 8사단 &lt;안전&gt; 점검 &amp; 교육 (공식 &amp; 뉴스)\n"
        '<a href="https://news.example/a?x=1&amp;unsafe=&quot;yes&quot;">'
        "기사 링크 바로가기</a>\n"
        "2. 8사단 추가 소식 (공식 &amp; 뉴스)"
    ) in html
    assert "[지역]\n1. 양주 산불 대응" in html
    assert "2. 동두천 협력 소식" in html
    assert "[외교·북한]\n1. 북한 군사 동향" in html
    assert "첫 문장에 &lt;점검&gt; 사실이 있다." not in html
    assert split_html_message(html)


def test_renderer_header_uses_short_kst_date_and_weekday() -> None:
    sunday = render_briefing_html({}, datetime(2026, 7, 18, 21, 30, tzinfo=UTC))
    sunday_rerun = render_briefing_html({}, datetime(2026, 7, 18, 21, 30, tzinfo=UTC))
    monday = render_briefing_html({}, datetime(2026, 7, 19, 21, 30, tzinfo=UTC))

    assert sunday == sunday_rerun
    assert sunday.startswith("💡26년 7월 19일(일) 육군 브리핑")
    assert monday.startswith("💡26년 7월 20일(월) 육군 브리핑")
    assert "💬오늘의 한마디 : " in monday


def test_renderer_omits_summary_when_description_only_repeats_title_and_source() -> None:
    html = render_briefing_html(
        {
            OutputGroup.DIVISION: (
                selected(
                    title="8사단 훈련 소식",
                    description="8사단 훈련 소식 - 공식 & 뉴스",
                ),
            )
        },
        datetime(2026, 7, 19, 6, tzinfo=KST),
    )

    assert "- 8사단 훈련 소식" not in html
    assert "세부 내용은 원문 기사에서 확인하세요" not in html


def test_renderer_combines_empty_groups_in_notice() -> None:
    html = render_briefing_html({}, datetime(2026, 7, 19, 6, tzinfo=KST))

    assert html.startswith("💡26년 7월 19일(일) 육군 브리핑\n💬오늘의 한마디 : ")
    assert "※ 육군, 군단, 사단, 지역, 국방·안보, 외교·북한, 칼럼·사설 관련 보도 없음" in html


def test_renderer_uses_requested_date_and_flow_phrase() -> None:
    groups = {
        OutputGroup.DIVISION: (
            selected(
                title="8사단 훈련 소식",
                description="실제 기사 설명은 렌더링하지 않습니다.",
            ),
        )
    }

    html = render_briefing_html(groups, datetime(2026, 7, 22, 8, tzinfo=KST))
    empty_html = render_briefing_html({}, datetime(2026, 7, 22, 8, tzinfo=KST))
    lines = html.splitlines()
    phrase = lines[1].split(" : ", 1)[1]
    empty_phrase = empty_html.splitlines()[1].split(" : ", 1)[1]

    assert lines[0] == "💡26년 7월 22일(수) 육군 브리핑"
    assert lines[1].startswith("💬오늘의 한마디 : ")
    assert 0 < len(phrase) <= 30
    rerun_phrase = render_briefing_html(
        groups, datetime(2026, 7, 22, 8, tzinfo=KST)
    ).splitlines()[1].split(" : ", 1)[1]
    assert phrase == rerun_phrase
    assert phrase != empty_phrase
    assert "8사단 훈련 소식" not in phrase


def test_renderer_groups_items_in_order_with_local_numbering() -> None:
    groups = {
        OutputGroup.CORPS: (
            selected(title="군단 첫 소식", group=OutputGroup.CORPS),
            selected(title="군단 둘째 소식", group=OutputGroup.CORPS),
        ),
        OutputGroup.DIVISION: (selected(title="사단 소식"),),
        OutputGroup.REGION: (
            selected(title="지역 첫 소식", group=OutputGroup.REGION),
            selected(title="지역 둘째 소식", group=OutputGroup.REGION),
        ),
        OutputGroup.ARMY: (selected(title="육군 소식", group=OutputGroup.ARMY),),
        OutputGroup.DEFENSE_SECURITY: (
            selected(title="국방 첫 소식", group=OutputGroup.DEFENSE_SECURITY),
            selected(title="국방 둘째 소식", group=OutputGroup.DEFENSE_SECURITY),
        ),
        OutputGroup.DIPLOMACY_NORTH_KOREA: (
            selected(title="외교·북한 소식", group=OutputGroup.DIPLOMACY_NORTH_KOREA),
        ),
        OutputGroup.COLUMN_EDITORIAL: (
            selected(title="칼럼 첫 소식", group=OutputGroup.COLUMN_EDITORIAL),
            selected(title="칼럼 둘째 소식", group=OutputGroup.COLUMN_EDITORIAL),
        ),
    }
    labels = (
        (OutputGroup.ARMY, "육군", 1),
        (OutputGroup.CORPS, "군단", 2),
        (OutputGroup.DIVISION, "사단", 1),
        (OutputGroup.REGION, "지역", 2),
        (OutputGroup.DEFENSE_SECURITY, "국방·안보", 2),
        (OutputGroup.DIPLOMACY_NORTH_KOREA, "외교·북한", 1),
        (OutputGroup.COLUMN_EDITORIAL, "칼럼·사설", 2),
    )

    html = render_briefing_html(groups, datetime(2026, 7, 22, 8, tzinfo=KST))
    positions = [html.index(f"[{label}]") for _group, label, _count in labels]

    assert positions == sorted(positions)
    for _group, label, count in labels:
        start = html.index(f"[{label}]")
        next_positions = [position for position in positions if position > start]
        end = min(next_positions, default=len(html))
        block = html[start:end]
        assert block.count(f"[{label}]") == 1
        for number in range(1, count + 1):
            assert f"\n{number}. " in block
        assert f"\n{count + 1}. " not in block


def test_renderer_combines_empty_notice_omits_empty_headers_and_summaries() -> None:
    html = render_briefing_html(
        {
            OutputGroup.DIVISION: (
                selected(
                    title="사단 제목",
                    description="이 설명은 링크 아래에 절대 표시하지 않습니다.",
                ),
            )
        },
        datetime(2026, 7, 22, 8, tzinfo=KST),
    )

    notice = "※ 육군, 군단, 지역, 국방·안보, 외교·북한, 칼럼·사설 관련 보도 없음"
    assert html.index(notice) < html.index("[사단]")
    assert "[군단]" not in html
    assert "[지역]" not in html
    assert "[육군]" not in html
    assert "[국방·안보]" not in html
    assert "[외교·북한]" not in html
    assert "[칼럼·사설]" not in html
    assert "이 설명은 링크 아래에 절대 표시하지 않습니다." not in html
    assert "\n- " not in html
    assert "[사단]\n1. 사단 제목 (공식 &amp; 뉴스)" in html


def test_renderer_escapes_dynamic_html_and_is_telegram_split_compatible() -> None:
    html = render_briefing_html(
        {
            OutputGroup.DIVISION: (
                selected(
                    title='제목 <태그> & "인용"',
                    source='매체 <&> "이름"',
                    url='https://news.example/a?x=1&unsafe="yes"',
                    description="설명은 노출되지 않습니다.",
                ),
            )
        },
        datetime(2026, 7, 22, 8, tzinfo=KST),
    )

    assert "제목 &lt;태그&gt; &amp; &quot;인용&quot;" in html
    assert "(매체 &lt;&amp;&gt; &quot;이름&quot;)" in html
    assert 'href="https://news.example/a?x=1&amp;unsafe=&quot;yes&quot;"' in html
    assert "기사 링크 바로가기" in html
    assert split_html_message(html, limit=120)
