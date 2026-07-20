import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from html import escape

from army_morning_brief.classification import OutputGroup
from army_morning_brief.config import KST
from army_morning_brief.pipeline import SelectedArticle

_SENTENCE_PATTERN = re.compile(r".*?[.!?。！？](?=\s|$)|.+$", re.DOTALL)
_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
_GROUP_LABELS = (
    (OutputGroup.DIVISION, "사단"),
    (OutputGroup.REGION, "지역"),
    (OutputGroup.DIPLOMACY_NORTH_KOREA, "외교/북한"),
)
_SUMMARY_LIMIT = 50

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


def extractive_summary(selected: SelectedArticle) -> str | None:
    description = _normalized_text(selected.article.description)
    if not description:
        return None
    if _is_redundant_description(selected, description):
        return None
    sentences = [match.group(0).strip() for match in _SENTENCE_PATTERN.finditer(description)]
    return sentences[0] if sentences else description


def _truncate_naturally(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    shortened = value[: limit - 1].rstrip()
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return f"{shortened.rstrip(',.…')}…"


def concise_summary(selected: SelectedArticle) -> str:
    extracted = extractive_summary(selected)
    if extracted is not None:
        return _truncate_naturally(_normalized_text(extracted), _SUMMARY_LIMIT)
    title = _normalized_text(selected.article.title).rstrip(".!?。！？")
    suffix = " 관련 소식임"
    title_part = _truncate_naturally(title, _SUMMARY_LIMIT - len(suffix))
    return f"{title_part}{suffix}"


def render_briefing_html(
    groups: Mapping[OutputGroup, Sequence[SelectedArticle]], run_at: datetime
) -> str:
    if run_at.tzinfo is None or run_at.utcoffset() is None:
        raise ValueError("run_at must be timezone-aware")
    run_date = _kst_date(run_at)
    header = (
        f"['{run_date:%y}.{run_date.month}.{run_date.day}."
        f"({_WEEKDAYS[run_date.weekday()]}), 아침 언론 모니터 결과]"
    )
    empty_labels = [label for group, label in _GROUP_LABELS if not groups.get(group, ())]
    blocks: list[str] = []
    if empty_labels:
        blocks.append(f"※ {', '.join(empty_labels)} 관련 보도 없음")
    for group, label in _GROUP_LABELS:
        items = groups.get(group, ())
        for selected in items:
            article = selected.article
            title = escape(_normalized_text(article.title))
            source = escape(_normalized_text(article.source.name))
            url = _normalized_text(article.url)
            escaped_url = escape(url, quote=True)
            summary = escape(concise_summary(selected))
            blocks.append(
                "\n".join(
                    (
                        f"■ [{label}] {title} ({source})",
                        f'<a href="{escaped_url}">기사 링크 바로가기</a>',
                        f"- {summary}",
                    )
                )
            )
    return f"{header}\n\n{'\n\n'.join(blocks)}"
