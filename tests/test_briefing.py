from datetime import UTC, datetime, timedelta, timezone

from army_morning_brief.briefing import extractive_summary, render_briefing_html
from army_morning_brief.classification import ClassificationResult, OutputGroup
from army_morning_brief.models import Article, Source
from army_morning_brief.pipeline import SelectedArticle
from army_morning_brief.telegram import split_html_message

KST = timezone(timedelta(hours=9))


def selected(
    *,
    title: str = "8사단 <안전> 점검 & 교육",
    description: str = (
        "첫 문장에 <점검> 사실이 있다. 둘째 문장도 기사에 있다! 셋째 문장은 제외한다."
    ),
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


def test_extractive_summary_copies_only_first_two_description_sentences() -> None:
    item = selected()

    summary = extractive_summary(item)

    assert summary == "첫 문장에 <점검> 사실이 있다. 둘째 문장도 기사에 있다!"
    assert summary in item.article.description
    assert "실무" not in summary


def test_extractive_summary_falls_back_to_original_title() -> None:
    item = selected(title="원문 제목 그대로", description="   ")

    assert extractive_summary(item) == "원문 제목 그대로"


def test_renderer_uses_three_line_items_with_short_clickable_links() -> None:
    html = render_briefing_html(
        {
            OutputGroup.DIVISION: (selected(),),
            OutputGroup.REGION: (selected(title="양주 산불 대응", group=OutputGroup.REGION),),
            OutputGroup.DIPLOMACY_NORTH_KOREA: (
                selected(
                    title="북한 군사 동향",
                    group=OutputGroup.DIPLOMACY_NORTH_KOREA,
                ),
            ),
        },
        datetime(2026, 7, 17, 21, 30, tzinfo=UTC),
    )

    assert "■ [사단] 8사단 &lt;안전&gt; 점검 &amp; 교육 (공식 &amp; 뉴스)" in html
    assert (
        '<a href="https://news.example/a?x=1&amp;unsafe=&quot;yes&quot;">기사 링크 바로가기</a>'
    ) in html
    assert "■ [지역] 양주 산불 대응 (공식 &amp; 뉴스)" in html
    assert "■ [외교·북한] 북한 군사 동향 (공식 &amp; 뉴스)" in html
    assert "첫 문장에 &lt;점검&gt; 사실이 있다." in html
    assert "셋째 문장은 제외한다" not in html
    assert "<b>" not in html
    assert "출처:" not in html and "발행:" not in html and "원문 기사" not in html
    assert "1." not in html
    assert html.count("\n") == 10
    assert split_html_message(html)


def test_renderer_keeps_empty_groups_unambiguous_without_section_headings() -> None:
    html = render_briefing_html({}, datetime(2026, 7, 18, 6, tzinfo=KST))

    assert html == (
        "■ [사단] 관련 기사 없음\n\n■ [지역] 관련 기사 없음\n\n■ [외교·북한] 관련 기사 없음"
    )
