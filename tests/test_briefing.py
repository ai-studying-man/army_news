from datetime import UTC, datetime, timedelta, timezone

import pytest

from army_morning_brief.briefing import extractive_summary, render_briefing_html
from army_morning_brief.classification import ClassificationResult, OutputGroup
from army_morning_brief.models import Article, Source
from army_morning_brief.pipeline import SelectedArticle
from army_morning_brief.telegram import split_html_message

KST = timezone(timedelta(hours=9))
DIVIDER = "-" * 36


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

    assert html.startswith('출근 길, 오늘의 뉴스는? 💡\n2026.07.19.(일)\n\n💬오늘의 한마디\n"')
    assert html.splitlines()[4].endswith('"')
    assert html.count(DIVIDER) == 3
    assert html.index("🪖 육군&8사단 주요 뉴스") < html.index("📍 지역 뉴스")
    assert html.index("📍 지역 뉴스") < html.index("🌐 외교/북한 관련")
    assert (
        "8사단 &lt;안전&gt; 점검 &amp; 교육\n"
        "✅실무 참고 : 첫 문장에 &lt;점검&gt; 사실이 있다.\n"
        '🔗<a href="https://news.example/a?x=1&amp;unsafe=&quot;yes&quot;">'
        "뉴스 기사 링크 바로가기</a>"
    ) in html
    assert "8사단 추가 소식\n" in html
    assert "양주 산불 대응\n" in html
    assert "동두천 협력 소식\n" in html
    assert "북한 군사 동향\n" in html
    assert " (공식 &amp; 뉴스)" not in html
    assert "[사단]" not in html and "[지역]" not in html and "[외교/북한]" not in html
    assert ">기사 링크 바로가기</a>" not in html
    assert "- 첫 문장" not in html
    assert split_html_message(html)


def test_renderer_quote_is_deterministic_and_changes_by_kst_date() -> None:
    sunday = render_briefing_html({}, datetime(2026, 7, 18, 21, 30, tzinfo=UTC))
    sunday_rerun = render_briefing_html({}, datetime(2026, 7, 18, 21, 30, tzinfo=UTC))
    monday = render_briefing_html({}, datetime(2026, 7, 19, 21, 30, tzinfo=UTC))

    assert sunday == sunday_rerun
    assert sunday.splitlines()[4] != monday.splitlines()[4]
    assert monday.startswith("출근 길, 오늘의 뉴스는? 💡\n2026.07.20.(월)\n")


def test_renderer_omits_note_when_description_only_repeats_title_and_source() -> None:
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

    assert "✅실무 참고" not in html
    assert "세부 내용은 원문 기사에서 확인하세요" not in html
    assert "8사단 훈련 소식\n🔗" in html


def test_renderer_keeps_empty_groups_with_headings_and_dividers() -> None:
    html = render_briefing_html({}, datetime(2026, 7, 19, 6, tzinfo=KST))

    assert html.startswith("출근 길, 오늘의 뉴스는? 💡\n2026.07.19.(일)\n")
    assert html.count("관련 기사 없음") == 3
    assert html.count(DIVIDER) == 3
    assert (
        f"{DIVIDER}\n🪖 육군&8사단 주요 뉴스\n관련 기사 없음\n\n"
        f"{DIVIDER}\n📍 지역 뉴스\n관련 기사 없음\n\n"
        f"{DIVIDER}\n🌐 외교/북한 관련\n관련 기사 없음"
    ) in html
