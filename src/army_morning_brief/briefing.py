"""Telegram-ready briefing rendering."""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape

from army_morning_brief.classification import OutputGroup
from army_morning_brief.pipeline import SelectedArticle

_SENTENCE_PATTERN = re.compile(r".*?[.!?。！？](?=\s|$)|.+$", re.DOTALL)
_SECTION_HEADINGS = (
    (OutputGroup.DIVISION, "🪖 <b>8사단 주요 뉴스</b>"),
    (OutputGroup.REGION, "📍 <b>지역 뉴스</b>"),
    (OutputGroup.DIPLOMACY_NORTH_KOREA, "🌐 <b>외교·북한 관련</b>"),
)


def extractive_summary(selected: SelectedArticle) -> str:
    """Return up to two sentences copied from the selected article."""
    description = " ".join(selected.article.description.split())
    if not description:
        return " ".join(selected.article.title.split())
    sentences = [match.group(0).strip() for match in _SENTENCE_PATTERN.finditer(description)]
    return " ".join(sentences[:2])


def render_briefing_html(
    groups: Mapping[OutputGroup, Sequence[SelectedArticle]], run_at: datetime
) -> str:
    """Render deterministic three-line Korean HTML news items."""
    if run_at.tzinfo is None or run_at.utcoffset() is None:
        raise ValueError("run_at must be timezone-aware")
    blocks: list[str] = []
    for group, heading in _SECTION_HEADINGS:
        items = groups.get(group, ())
        if not items:
            blocks.append(f"{heading}\n관련 기사 없음")
            continue
        items_blocks: list[str] = []
        for number, selected in enumerate(items, start=1):
            article = selected.article
            title = escape(" ".join(article.title.split()))
            source = escape(" ".join(article.source.name.split()))
            url = " ".join(article.url.split())
            escaped_url = escape(url, quote=True)
            summary = escape(" ".join(extractive_summary(selected).split()))
            items_blocks.append(
                "\n".join(
                    (
                        f"{number}. {title} ({source})",
                        f'<a href="{escaped_url}">기사 링크 바로가기</a>',
                        f"- {summary}",
                    )
                )
            )
        blocks.append(f"{heading}\n{'\n\n'.join(items_blocks)}")
    return "\n\n".join(blocks)
