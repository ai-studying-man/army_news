"""Telegram-ready briefing rendering."""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape

from army_morning_brief.classification import OutputGroup
from army_morning_brief.pipeline import SelectedArticle

_SENTENCE_PATTERN = re.compile(r".*?[.!?。！？](?=\s|$)|.+$", re.DOTALL)


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
    for group in (
        OutputGroup.DIVISION,
        OutputGroup.REGION,
        OutputGroup.DIPLOMACY_NORTH_KOREA,
    ):
        items = groups.get(group, ())
        if not items:
            blocks.append(f"■ [{escape(group.value)}] 관련 기사 없음")
            continue
        for selected in items:
            article = selected.article
            title = escape(" ".join(article.title.split()))
            source = escape(" ".join(article.source.name.split()))
            url = " ".join(article.url.split())
            escaped_url = escape(url, quote=True)
            summary = escape(" ".join(extractive_summary(selected).split()))
            blocks.append(
                "\n".join(
                    (
                        f"■ [{escape(group.value)}] {title} ({source})",
                        f'<a href="{escaped_url}">기사 링크 바로가기</a>',
                        f"- {summary}",
                    )
                )
            )
    return "\n\n".join(blocks)
