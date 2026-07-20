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


def test_concise_summary_uses_source_content_or_safe_title_facts_within_50_chars() -> None:
    source_backed = selected(description="실제 기사 첫 문장에 확인된 내용이 있다. 둘째 문장이다.")
    title_backed = selected(
        title="육군 제6보병사단, 철원과 포천 일대에서 전투지휘검열 훈련 실시",
        description="",
    )

    assert concise_summary(source_backed) == "실제 기사 첫 문장에 확인된 내용이 있다."
    assert concise_summary(title_backed).endswith("관련 소식임")
    assert len(concise_summary(title_backed)) <= 50


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

    assert html.startswith("['26.7.19.(일), 아침 언론 모니터 결과]\n")
    assert "※" not in html
    assert html.index("■ [사단]") < html.index("■ [지역]")
    assert html.index("■ [지역]") < html.index("■ [외교/북한]")
    assert (
        "■ [사단] 8사단 &lt;안전&gt; 점검 &amp; 교육 (공식 &amp; 뉴스)\n"
        '<a href="https://news.example/a?x=1&amp;unsafe=&quot;yes&quot;">'
        "기사 링크 바로가기</a>\n"
        "- 첫 문장에 &lt;점검&gt; 사실이 있다."
    ) in html
    assert "■ [사단] 8사단 추가 소식" in html
    assert "■ [지역] 양주 산불 대응" in html
    assert "■ [지역] 동두천 협력 소식" in html
    assert "■ [외교/북한] 북한 군사 동향" in html
    assert split_html_message(html)


def test_renderer_header_uses_short_kst_date_and_weekday() -> None:
    sunday = render_briefing_html({}, datetime(2026, 7, 18, 21, 30, tzinfo=UTC))
    sunday_rerun = render_briefing_html({}, datetime(2026, 7, 18, 21, 30, tzinfo=UTC))
    monday = render_briefing_html({}, datetime(2026, 7, 19, 21, 30, tzinfo=UTC))

    assert sunday == sunday_rerun
    assert sunday.startswith("['26.7.19.(일), 아침 언론 모니터 결과]")
    assert monday.startswith("['26.7.20.(월), 아침 언론 모니터 결과]")


def test_renderer_uses_title_facts_when_description_only_repeats_title_and_source() -> None:
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

    assert "- 8사단 훈련 소식 관련 소식임" in html
    assert "세부 내용은 원문 기사에서 확인하세요" not in html


def test_renderer_combines_empty_groups_in_notice() -> None:
    html = render_briefing_html({}, datetime(2026, 7, 19, 6, tzinfo=KST))

    assert html == (
        "['26.7.19.(일), 아침 언론 모니터 결과]\n\n※ 사단, 지역, 외교/북한 관련 보도 없음"
    )
