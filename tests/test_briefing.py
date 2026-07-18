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
) -> SelectedArticle:
    item = Article(
        title=title,
        description=description,
        url=url,
        published_at=datetime(2026, 7, 18, 6, 5, tzinfo=KST),
        source=Source(name=source, url="https://news.example/feed"),
    )
    return SelectedArticle(item, ClassificationResult(OutputGroup.DIVISION, "8사단"))


def test_extractive_summary_copies_only_first_two_description_sentences() -> None:
    item = selected()

    summary = extractive_summary(item)

    assert summary == "첫 문장에 <점검> 사실이 있다. 둘째 문장도 기사에 있다!"
    assert summary in item.article.description
    assert "실무" not in summary


def test_extractive_summary_falls_back_to_original_title() -> None:
    item = selected(title="원문 제목 그대로", description="   ")

    assert extractive_summary(item) == "원문 제목 그대로"


def test_renderer_has_kst_header_both_sections_traceability_and_escaped_html() -> None:
    html = render_briefing_html(
        {OutputGroup.DIVISION: (selected(),), OutputGroup.REGION: ()},
        datetime(2026, 7, 17, 21, 30, tzinfo=UTC),
    )

    assert "육군 출근길 오늘의 뉴스는? - 2026.07.18" in html
    assert "[사단]" in html and "[지역]" in html
    assert "관련 기사 없음" in html
    assert "8사단 &lt;안전&gt; 점검 &amp; 교육" in html
    assert "공식 &amp; 뉴스" in html
    assert "2026.07.18 06:05 KST" in html
    assert 'href="https://news.example/a?x=1&amp;unsafe=&quot;yes&quot;"' in html
    assert "첫 문장에 &lt;점검&gt; 사실이 있다." in html
    assert "셋째 문장은 제외한다" not in html
    assert split_html_message(html)


def test_renderer_always_includes_empty_literal_sections() -> None:
    html = render_briefing_html({}, datetime(2026, 7, 18, 6, tzinfo=KST))

    assert html.count("관련 기사 없음") == 2
    assert html.index("[사단]") < html.index("[지역]")
