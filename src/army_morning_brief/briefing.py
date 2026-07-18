"""Telegram-ready briefing rendering."""

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from html import escape

from army_morning_brief.classification import OutputGroup
from army_morning_brief.config import KST
from army_morning_brief.pipeline import SelectedArticle

_SENTENCE_PATTERN = re.compile(r".*?[.!?。！？](?=\s|$)|.+$", re.DOTALL)


def extractive_summary(selected: SelectedArticle) -> str:
    """Return up to two sentences copied from the selected article."""
    description = selected.article.description.strip()
    if not description:
        return selected.article.title.strip()
    sentences = [match.group(0).strip() for match in _SENTENCE_PATTERN.finditer(description)]
    return " ".join(sentences[:2])


def render_briefing_html(
    groups: Mapping[OutputGroup, Sequence[SelectedArticle]], run_at: datetime
) -> str:
    """Render a deterministic Korean HTML briefing."""
    if run_at.tzinfo is None or run_at.utcoffset() is None:
        raise ValueError("run_at must be timezone-aware")
    run_date = run_at.astimezone(KST).strftime("%Y.%m.%d")
    lines = [f"<b>육군 출근길 오늘의 뉴스는? - {run_date}</b>"]

    for group in (OutputGroup.DIVISION, OutputGroup.REGION):
        lines.extend(("", f"<b>[{escape(group.value)}]</b>"))
        items = groups.get(group, ())
        if not items:
            lines.append("관련 기사 없음")
            continue
        for index, selected in enumerate(items, start=1):
            article = selected.article
            published = article.published_at.astimezone(KST).strftime("%Y.%m.%d %H:%M KST")
            lines.extend(
                (
                    f"{index}. {escape(article.title)}",
                    f"출처: {escape(article.source.name)} | 발행: {published}",
                    f"요약: {escape(extractive_summary(selected))}",
                    f'<a href="{escape(article.url, quote=True)}">원문 기사</a>',
                )
            )
            if index != len(items):
                lines.append("")
    return "\n".join(lines)
