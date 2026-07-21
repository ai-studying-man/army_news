from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from army_morning_brief import collector as collector_module
from army_morning_brief.collector import (
    MAX_FEED_BYTES,
    FeedParseError,
    FeedTooLargeError,
    collect_articles,
    parse_rss,
)
from army_morning_brief.config import BriefConfig, CollectionWindow, DivisionRule
from army_morning_brief.models import Source
from army_morning_brief.sources import (
    COLUMN_EDITORIAL_SEARCH_TERMS,
    DEFENSE_SECURITY_SEARCH_TERMS,
    DIPLOMACY_SECURITY_SEARCH_TERMS,
    NORTH_KOREA_SEARCH_TERMS,
    PUBLIC_RSS_SOURCES,
    build_google_news_sources,
    build_google_news_url,
    configured_sources,
)

KST = timezone(timedelta(hours=9))
FIXTURES = Path(__file__).parent / "fixtures"
WINDOW = CollectionWindow(
    start=datetime(2026, 7, 17, 14, 0, tzinfo=KST),
    end=datetime(2026, 7, 18, 5, 0, tzinfo=KST),
)
SOURCE = Source("fixture", "https://feeds.example.test/daily.xml", priority=10)


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_public_and_configured_sources_are_https_and_google_queries_are_encoded() -> None:
    config = BriefConfig(
        divisions=(DivisionRule("제8기동사단", ("8사단", "오뚜기부대"), ("양주", "동두천")),)
    )

    url = build_google_news_url(("8사단", "오뚜기 부대"))
    split = urlsplit(url)
    google_sources = build_google_news_sources(config)
    all_sources = configured_sources(config)

    assert split.scheme == "https"
    assert split.netloc == "news.google.com"
    assert parse_qs(split.query) == {
        "q": ['"8사단" OR "오뚜기 부대"'],
        "hl": ["ko"],
        "gl": ["KR"],
        "ceid": ["KR:ko"],
    }
    assert "%EC%98%A4%EB%9A%9C%EA%B8%B0%20%EB%B6%80%EB%8C%80" in url
    assert len(PUBLIC_RSS_SOURCES) >= 2
    assert len(google_sources) == 2
    assert len(all_sources) == len(PUBLIC_RSS_SOURCES) + 6
    assert all_sources[-4].url == build_google_news_url(NORTH_KOREA_SEARCH_TERMS)
    assert all_sources[-3].url == build_google_news_url(DIPLOMACY_SECURITY_SEARCH_TERMS)
    assert all_sources[-2].url == build_google_news_url(DEFENSE_SECURITY_SEARCH_TERMS)
    assert all_sources[-1].url == build_google_news_url(COLUMN_EDITORIAL_SEARCH_TERMS)
    assert all(source.url.startswith("https://") for source in all_sources)
    assert all_sources[: len(PUBLIC_RSS_SOURCES)] == PUBLIC_RSS_SOURCES


def test_daily_fixture_preserves_item_publisher_metadata() -> None:
    articles = parse_rss(_fixture("daily_feed.xml"), SOURCE, WINDOW)

    assert [article.title for article in articles] == [
        "25사단 장병 안전교육 실시",
        "양주시 군·관 재난대응 협력",
    ]
    assert [article.feed_rank for article in articles] == [0, 1]
    assert articles[0].published_at == WINDOW.start
    assert articles[1].published_at == WINDOW.end
    assert articles[0].description == "장병 대상 안전 교육 & 점검"
    assert articles[0].url == "https://news.example.test/division-safety"
    assert articles[0].source == Source(
        name="공개 언론사",
        url="https://publisher.example.test/",
        priority=SOURCE.priority,
    )
    assert articles[1].source is SOURCE


@pytest.mark.parametrize(
    "publisher",
    [
        "",
        '<source url="https://publisher.example.test/"></source>',
        '<source url="not-a-url">공개 언론사</source>',
        '<source url="http://publisher.example.test/">공개 언론사</source>',
    ],
)
def test_invalid_or_incomplete_item_publisher_falls_back_to_feed_source(
    publisher: str,
) -> None:
    document = f"""\
<rss version="2.0"><channel><item>
  <title>공개 기사</title>
  <link>https://news.google.com/rss/articles/public-test-token</link>
  <pubDate>Fri, 17 Jul 2026 08:00:00 GMT</pubDate>
  {publisher}
</item></channel></rss>
""".encode()

    articles = parse_rss(document, SOURCE, WINDOW)

    assert len(articles) == 1
    assert articles[0].source is SOURCE
    assert articles[0].url == "https://news.google.com/rss/articles/public-test-token"


@pytest.mark.parametrize(
    ("title", "publisher_markup", "expected_title", "expected_source"),
    [
        (
            "Article - News",
            '<source url="https://publisher.example.test/">News</source>',
            "Article",
            "News",
        ),
        (
            "Article - Newswire",
            '<source url="https://publisher.example.test/">News</source>',
            "Article - Newswire",
            "News",
        ),
        (
            "Article — News",
            '<source url="https://publisher.example.test/">News</source>',
            "Article — News",
            "News",
        ),
        (
            "Article - News",
            "",
            "Article - News",
            SOURCE.name,
        ),
        (
            "Article - News",
            '<source url="http://publisher.example.test/">News</source>',
            "Article - News",
            SOURCE.name,
        ),
    ],
)
def test_item_publisher_suffix_normalization_requires_exact_valid_source(
    title: str,
    publisher_markup: str,
    expected_title: str,
    expected_source: str,
) -> None:
    document = f"""\
<rss version="2.0"><channel><item>
  <title>{title}</title>
  <link>https://news.google.com/rss/articles/title-source-test</link>
  <pubDate>Fri, 17 Jul 2026 08:00:00 GMT</pubDate>
  {publisher_markup}
</item></channel></rss>
""".encode()

    articles = parse_rss(document, SOURCE, WINDOW)

    assert len(articles) == 1
    assert articles[0].title == expected_title
    assert articles[0].source.name == expected_source
    assert articles[0].source.priority == SOURCE.priority
    assert articles[0].url == "https://news.google.com/rss/articles/title-source-test"


def test_adversarial_items_are_isolated_without_filtering_valid_homonyms_or_duplicates() -> None:
    articles = parse_rss(_fixture("adversarial_feed.xml"), SOURCE, WINDOW)

    assert [article.title for article in articles] == [
        "중복 사건 첫 보도",
        "중복 사건 재전재",
        "양주 가격 상승",
        "정상 별도 기사 <확인>",
    ]
    assert articles[-1].description == "공개 자료 <검토> & 후속 발표"
    assert all(article.url.startswith("https://") for article in articles)


def test_oversize_and_bad_xml_are_rejected() -> None:
    with pytest.raises(FeedTooLargeError, match="size limit"):
        parse_rss(b"x" * (MAX_FEED_BYTES + 1), SOURCE, WINDOW)

    with pytest.raises(FeedParseError, match="invalid RSS XML"):
        parse_rss(b"<rss><channel><item></rss>", SOURCE, WINDOW)


def test_ascii_dtd_and_entity_declarations_are_rejected_before_elementtree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = b"""<!DOCTYPE rss [<!ENTITY expanded "unsafe">]>
<rss><channel><item>
  <title>&expanded;</title>
  <link>https://news.example.test/entity</link>
  <pubDate>Fri, 17 Jul 2026 08:00:00 GMT</pubDate>
</item></channel></rss>
"""

    def unexpected_elementtree_parse(_xml: bytes) -> object:
        raise AssertionError("unsafe XML reached ElementTree")

    monkeypatch.setattr(collector_module.ElementTree, "fromstring", unexpected_elementtree_parse)

    with pytest.raises(FeedParseError, match="invalid RSS XML"):
        parse_rss(document, SOURCE, WINDOW)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_dtd_and_entity_declarations_are_rejected_for_utf16_before_expansion(
    encoding: str,
) -> None:
    document = (
        """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE rss [<!ENTITY expanded "8사단 장병 안전교육 실시">]>
<rss><channel><item>
  <title>&expanded;</title>
  <link>https://news.example.test/utf16-entity</link>
  <pubDate>Fri, 17 Jul 2026 08:00:00 GMT</pubDate>
</item></channel></rss>
"""
    ).encode(encoding)

    with pytest.raises(FeedParseError, match="invalid RSS XML"):
        parse_rss(document, SOURCE, WINDOW)


def test_utf16_without_declarations_remains_supported() -> None:
    document = (
        """<?xml version="1.0" encoding="UTF-16"?>
<rss><channel><item>
  <title>UTF-16 정상 기사</title>
  <link>https://news.example.test/utf16-valid</link>
  <pubDate>Fri, 17 Jul 2026 08:00:00 GMT</pubDate>
</item></channel></rss>
"""
    ).encode("utf-16")

    articles = parse_rss(document, SOURCE, WINDOW)

    assert [article.title for article in articles] == ["UTF-16 정상 기사"]


def test_out_of_window_items_are_excluded_but_both_edges_are_inclusive() -> None:
    articles = parse_rss(_fixture("daily_feed.xml"), SOURCE, WINDOW)

    assert len(articles) == 2
    assert WINDOW.start in {article.published_at for article in articles}
    assert WINDOW.end in {article.published_at for article in articles}


def test_partial_source_failure_continues_with_safe_diagnostics_and_request_policy() -> None:
    good = Source("good", "https://feeds.example.test/good.xml")
    failed = Source("failed", "https://feeds.example.test/private-token-value.xml")
    broken = Source("broken", "https://feeds.example.test/broken.xml")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("good.xml"):
            return httpx.Response(200, content=_fixture("daily_feed.xml"))
        if request.url.path.endswith("broken.xml"):
            return httpx.Response(200, content=b"<rss>")
        return httpx.Response(503, content=b"PRIVATE RESPONSE BODY")

    with _client(handler) as client:
        result = collect_articles(
            (failed, good, broken),
            WINDOW,
            client=client,
            sleep=lambda _delay: None,
        )

    assert len(result.articles) == 2
    assert [(item.source_name, item.code) for item in result.diagnostics] == [
        ("failed", "http_status"),
        ("broken", "invalid_feed"),
    ]
    rendered = repr(result.diagnostics)
    assert "private-token-value" not in rendered
    assert "PRIVATE RESPONSE BODY" not in rendered
    assert len(requests) == 5
    assert all(
        request.headers["user-agent"].startswith("army-morning-brief/") for request in requests
    )
    assert all(
        request.extensions["timeout"] == {"connect": 5.0, "read": 15.0, "write": 15.0, "pool": 5.0}
        for request in requests
    )


def test_transient_statuses_retry_with_bounded_backoff_and_recover() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        if attempts == 2:
            return httpx.Response(429)
        return httpx.Response(200, content=_fixture("daily_feed.xml"))

    with _client(handler) as client:
        result = collect_articles((SOURCE,), WINDOW, client=client, sleep=delays.append)

    assert attempts == 3
    assert delays == [0.5, 1.0]
    assert len(result.articles) == 2
    assert result.diagnostics == ()


def test_retry_after_delay_is_capped() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"retry-after": "9999"})
        return httpx.Response(200, content=_fixture("daily_feed.xml"))

    with _client(handler) as client:
        result = collect_articles((SOURCE,), WINDOW, client=client, sleep=delays.append)

    assert attempts == 2
    assert delays == [5.0]
    assert len(result.articles) == 2
    assert result.diagnostics == ()


def test_transport_failures_retry_without_leaking_error_details() -> None:
    attempts = 0
    delays: list[float] = []
    leaked_url = "https://feeds.example.test/private-token-value.xml"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ReadTimeout(f"timeout at {leaked_url}", request=request)
        return httpx.Response(200, content=_fixture("daily_feed.xml"))

    with _client(handler) as client:
        result = collect_articles((SOURCE,), WINDOW, client=client, sleep=delays.append)

    assert attempts == 3
    assert delays == [0.5, 1.0]
    assert len(result.articles) == 2
    assert result.diagnostics == ()
    assert leaked_url not in repr(result.diagnostics)


def test_permanent_client_error_is_not_retried() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, content=b"PRIVATE RESPONSE BODY")

    with _client(handler) as client:
        result = collect_articles((SOURCE,), WINDOW, client=client, sleep=delays.append)

    assert attempts == 1
    assert delays == []
    assert [(item.source_name, item.code) for item in result.diagnostics] == [
        (SOURCE.name, "http_status")
    ]
    assert "PRIVATE RESPONSE BODY" not in repr(result.diagnostics)


def test_network_oversize_is_isolated_per_source() -> None:
    large = Source("large", "https://feeds.example.test/large.xml")
    good = Source("good", "https://feeds.example.test/good.xml")

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            b"x" * (MAX_FEED_BYTES + 1)
            if request.url.path.endswith("large.xml")
            else _fixture("daily_feed.xml")
        )
        return httpx.Response(200, content=body)

    with _client(handler) as client:
        result = collect_articles((large, good), WINDOW, client=client)

    assert len(result.articles) == 2
    assert [(item.source_name, item.code) for item in result.diagnostics] == [
        ("large", "feed_too_large")
    ]
