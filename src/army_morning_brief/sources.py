"""Small, explicit set of public HTTPS RSS sources."""

from urllib.parse import quote, urlencode

from army_morning_brief.config import BriefConfig
from army_morning_brief.models import Source

GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"

PUBLIC_RSS_SOURCES: tuple[Source, ...] = (
    Source(
        name="국방부 보도자료",
        url="https://www.mnd.go.kr/bbs/mnd/50719/rssList.do?row=50",
        priority=100,
    ),
    Source(
        name="국방부 공지사항",
        url="https://www.mnd.go.kr/bbs/mnd/11066/rssList.do?row=50",
        priority=80,
    ),
)


def build_google_news_url(terms: tuple[str, ...]) -> str:
    cleaned = tuple(term.strip() for term in terms if term.strip())
    if not cleaned:
        raise ValueError("Google News query terms must not be empty")
    query = " OR ".join(f'"{term}"' for term in dict.fromkeys(cleaned))
    parameters = urlencode(
        {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
        quote_via=quote,
    )
    return f"{GOOGLE_NEWS_RSS_ENDPOINT}?{parameters}"


def build_google_news_sources(config: BriefConfig) -> tuple[Source, ...]:
    sources: list[Source] = []
    for rule in config.divisions:
        sources.extend(
            (
                Source(
                    name=f"Google 뉴스: {rule.name} 별칭",
                    url=build_google_news_url(rule.aliases),
                    priority=60,
                ),
                Source(
                    name=f"Google 뉴스: {rule.name} 지역",
                    url=build_google_news_url(rule.regions),
                    priority=40,
                ),
            )
        )
    return tuple(sources)


def configured_sources(config: BriefConfig) -> tuple[Source, ...]:
    return PUBLIC_RSS_SOURCES + build_google_news_sources(config)
