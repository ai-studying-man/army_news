"""Telegram-ready briefing rendering."""

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from html import escape

from army_morning_brief.classification import OutputGroup
from army_morning_brief.config import KST
from army_morning_brief.pipeline import SelectedArticle

_SENTENCE_PATTERN = re.compile(r".*?[.!?。！？](?=\s|$)|.+$", re.DOTALL)
_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
_DAILY_QUOTES = (
    "기본과 원칙이 현장의 안전을 지킵니다.",
    "정확한 확인이 안전한 임무를 만듭니다.",
    "함께 준비하고 함께 책임지는 하루를 만듭니다.",
)
_DIVIDER = "-" * 36
_SECTION_HEADINGS = (
    (OutputGroup.DIVISION, "🪖 육군&8사단 주요 뉴스"),
    (OutputGroup.REGION, "📍 지역 뉴스"),
    (OutputGroup.DIPLOMACY_NORTH_KOREA, "🌐 외교/북한 관련"),
)

_REDUNDANT_DESCRIPTION_SEPARATORS = (" - ", " – ", " — ", " | ", " · ", ": ", " / ", " ")


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _is_redundant_description(selected: SelectedArticle, description: str) -> bool:
    article = selected.article
    title = _normalized_text(article.title)
    source = _normalized_text(article.source.name)
    folded_description = description.casefold()
    comparable_description = folded_description.rstrip(".!?。！？")
    if comparable_description == title.casefold():
        return True
    if not source:
        return False
    for separator in _REDUNDANT_DESCRIPTION_SEPARATORS:
        if comparable_description == f"{title}{separator}{source}".casefold():
            return True
    return comparable_description in {
        f"{title} ({source})".casefold(),
        f"{title} [{source}]".casefold(),
    }


def _kst_date(run_at: datetime) -> date:
    return run_at.astimezone(KST).date()


def _daily_quote(run_date: date) -> str:
    return _DAILY_QUOTES[run_date.toordinal() % len(_DAILY_QUOTES)]


def extractive_summary(selected: SelectedArticle) -> str:
    description = _normalized_text(selected.article.description)
    if not description:
        return _normalized_text(selected.article.title)
    if _is_redundant_description(selected, description):
        return "세부 내용은 원문 기사에서 확인하세요."
    sentences = [match.group(0).strip() for match in _SENTENCE_PATTERN.finditer(description)]
    return sentences[0] if sentences else description


def render_briefing_html(
    groups: Mapping[OutputGroup, Sequence[SelectedArticle]], run_at: datetime
) -> str:
    if run_at.tzinfo is None or run_at.utcoffset() is None:
        raise ValueError("run_at must be timezone-aware")
    run_date = _kst_date(run_at)
    header = "\n".join(
        (
            "출근 길, 오늘의 뉴스는? 💡",
            f"{run_date:%Y.%m.%d}.({_WEEKDAYS[run_date.weekday()]})",
            "",
            "💬오늘의 한마디",
            f'"{escape(_daily_quote(run_date))}"',
        )
    )
    blocks: list[str] = []
    for group, heading in _SECTION_HEADINGS:
        items = groups.get(group, ())
        if not items:
            blocks.append(f"{_DIVIDER}\n{heading}\n관련 기사 없음")
            continue
        items_blocks: list[str] = []
        for number, selected in enumerate(items, start=1):
            article = selected.article
            title = escape(_normalized_text(article.title))
            url = _normalized_text(article.url)
            escaped_url = escape(url, quote=True)
            summary = escape(_normalized_text(extractive_summary(selected)))
            items_blocks.append(
                "\n".join(
                    (
                        f"{number}. {title}",
                        f"   ✅실무 참고 : {summary}",
                        f'   🔗<a href="{escaped_url}">뉴스 기사 링크 바로가기</a>',
                    )
                )
            )
        blocks.append(f"{_DIVIDER}\n{heading}\n{'\n\n'.join(items_blocks)}")
    return f"{header}\n\n{'\n\n'.join(blocks)}"
