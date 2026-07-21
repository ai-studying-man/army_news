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
    (OutputGroup.ARMY, "육군"),
    (OutputGroup.CORPS, "군단"),
    (OutputGroup.DIVISION, "사단"),
    (OutputGroup.REGION, "지역"),
    (OutputGroup.DEFENSE_SECURITY, "국방·안보"),
    (OutputGroup.DIPLOMACY_NORTH_KOREA, "외교·북한"),
    (OutputGroup.COLUMN_EDITORIAL, "칼럼·사설"),
)
_SUMMARY_LIMIT = 50
_FLOW_PHRASES = (
    "오늘은 관련 보도가 없습니다.",
    "한 분야의 주요 흐름을 확인합니다.",
    "여러 분야의 흐름을 차분히 살펴봅니다.",
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
    comparison_title = re.sub(r"[^0-9a-z가-힣]", "", title.casefold())
    comparison_description = re.sub(
        r"[^0-9a-z가-힣]", "", comparable_description.casefold()
    )
    if (
        comparison_description
        and comparison_title.startswith(comparison_description)
        and not re.search(r"[.!?。！？]", description)
    ):
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


def concise_summary(selected: SelectedArticle) -> str | None:
    extracted = extractive_summary(selected)
    if extracted is None:
        return None
    return _truncate_naturally(_normalized_text(extracted), _SUMMARY_LIMIT)


def _daily_phrase(groups: Mapping[OutputGroup, Sequence[SelectedArticle]]) -> str:
    populated_count = sum(
        bool(groups.get(group, ())) for group, _label in _GROUP_LABELS
    )
    return _FLOW_PHRASES[min(populated_count, len(_FLOW_PHRASES) - 1)]


def render_briefing_html(
    groups: Mapping[OutputGroup, Sequence[SelectedArticle]], run_at: datetime
) -> str:
    if run_at.tzinfo is None or run_at.utcoffset() is None:
        raise ValueError("run_at must be timezone-aware")
    run_date = _kst_date(run_at)
    header = (
        f"💡{run_date:%y}년 {run_date.month}월 {run_date.day}일"
        f"({_WEEKDAYS[run_date.weekday()]}) 육군 브리핑"
    )
    phrase = _daily_phrase(groups)
    empty_labels = [label for group, label in _GROUP_LABELS if not groups.get(group, ())]
    blocks: list[str] = []
    if empty_labels:
        blocks.append(f"※ {', '.join(empty_labels)} 관련 보도 없음")
    for group, label in _GROUP_LABELS:
        items = groups.get(group, ())
        if not items:
            continue
        item_lines = [f"[{label}]"]
        for number, selected in enumerate(items, start=1):
            article = selected.article
            title = escape(_normalized_text(article.title))
            source = escape(_normalized_text(article.source.name))
            url = _normalized_text(article.url)
            escaped_url = escape(url, quote=True)
            item_lines.extend(
                (
                    f"{number}. {title} ({source})",
                    f'<a href="{escaped_url}">기사 링크 바로가기</a>',
                )
            )
        blocks.append("\n".join(item_lines))
    body = "\n\n".join(blocks)
    return f"{header}\n💬오늘의 한마디 : {escape(phrase)}" + (f"\n\n{body}" if body else "")
