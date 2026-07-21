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

NORTH_KOREA_SEARCH_TERMS = (
    "북한",
    "북핵",
    "김정은",
    "평양",
    "조선노동당",
    "북한군",
    "북중",
    "북러",
    "북중러",
    "DMZ",
    "비무장지대",
    "대남",
    "방사포",
)

DIPLOMACY_SECURITY_SEARCH_TERMS = (
    "한미동맹",
    "한미일",
    "국방수권법",
    "NATO",
    "나토",
    "호르무즈",
    "이란 공습",
    "군사 협력",
    "안보 협력",
    "K방산",
    "방산 수출",
    "핵심광물 공급망",
)

DEFENSE_SECURITY_SEARCH_TERMS = (
    "국방부",
    "합동참모본부",
    "국방 안보",
    "방산",
    "방위사업",
)

COLUMN_EDITORIAL_SEARCH_TERMS = (
    "군사 칼럼",
    "국방 칼럼",
    "안보 칼럼",
    "북한 사설",
    "외교 사설",
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
    diplomacy_sources = (
        Source(
            name="Google 뉴스: 북한",
            url=build_google_news_url(NORTH_KOREA_SEARCH_TERMS),
            priority=50,
        ),
        Source(
            name="Google 뉴스: 외교·안보",
            url=build_google_news_url(DIPLOMACY_SECURITY_SEARCH_TERMS),
            priority=50,
        ),
        Source(
            name="Google 뉴스: 국방·안보",
            url=build_google_news_url(DEFENSE_SECURITY_SEARCH_TERMS),
            priority=50,
        ),
        Source(
            name="Google 뉴스: 칼럼·사설",
            url=build_google_news_url(COLUMN_EDITORIAL_SEARCH_TERMS),
            priority=30,
        ),
    )
    return PUBLIC_RSS_SOURCES + build_google_news_sources(config) + diplomacy_sources
