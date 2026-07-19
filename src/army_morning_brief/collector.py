"""Bounded, failure-isolated collection of public RSS documents."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

from army_morning_brief.config import CollectionWindow
from army_morning_brief.models import Article, Source

MAX_FEED_BYTES = 5 * 1024 * 1024
REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
USER_AGENT = "army-morning-brief/0.1 (+public-rss-collector)"


class FeedParseError(ValueError):
    """Raised when an RSS document cannot be parsed."""


class FeedTooLargeError(FeedParseError):
    """Raised when an RSS document exceeds the byte cap."""


@dataclass(frozen=True, slots=True)
class CollectionDiagnostic:
    source_name: str
    code: str


@dataclass(frozen=True, slots=True)
class CollectionResult:
    articles: tuple[Article, ...]
    diagnostics: tuple[CollectionDiagnostic, ...]


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style"}:
            self.hidden_depth += 1
        elif not self.hidden_depth and normalized_tag in {"br", "div", "li", "p"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif not self.hidden_depth and normalized_tag in {"div", "li", "p"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _visible_text(value: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, TypeError):
        return " ".join(value.split())
    return " ".join("".join(parser.parts).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(item: ElementTree.Element, *names: str) -> str:
    accepted = set(names)
    for child in item:
        if _local_name(child.tag) in accepted:
            return "".join(child.itertext()).strip()
    return ""


def _published_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _is_https_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.lower() == "https" and bool(parsed.netloc)


def _article_source(item: ElementTree.Element, feed_source: Source) -> Source:
    publisher = next(
        (child for child in item if _local_name(child.tag) == "source"),
        None,
    )
    if publisher is None:
        return feed_source
    name = _visible_text("".join(publisher.itertext()).strip())
    url = (publisher.get("url") or "").strip()
    if not name or not _is_https_url(url):
        return feed_source
    try:
        return Source(name=name, url=url, priority=feed_source.priority)
    except ValueError:
        return feed_source


def parse_rss(xml: bytes, source: Source, window: CollectionWindow) -> tuple[Article, ...]:
    if len(xml) > MAX_FEED_BYTES:
        raise FeedTooLargeError("RSS document exceeds size limit")
    lowered = xml.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FeedParseError("invalid RSS XML")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise FeedParseError("invalid RSS XML") from error

    articles: list[Article] = []
    items = (element for element in root.iter() if _local_name(element.tag) == "item")
    for feed_rank, item in enumerate(items):
        title = _visible_text(_child_text(item, "title"))
        description = _visible_text(_child_text(item, "description", "summary"))
        url = _child_text(item, "link")
        published_at = _published_at(_child_text(item, "pubDate", "published", "updated"))
        if (
            not title
            or not _is_https_url(url)
            or published_at is None
            or not window.contains(published_at)
        ):
            continue
        try:
            articles.append(
                Article(
                    title=title,
                    description=description,
                    url=url,
                    published_at=published_at,
                    source=_article_source(item, source),
                    feed_rank=feed_rank,
                )
            )
        except ValueError:
            continue
    return tuple(articles)


def _read_response(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_FEED_BYTES:
                raise FeedTooLargeError("RSS document exceeds size limit")
        except ValueError:
            pass

    received = bytearray()
    for chunk in response.iter_bytes():
        if len(received) + len(chunk) > MAX_FEED_BYTES:
            raise FeedTooLargeError("RSS document exceeds size limit")
        received.extend(chunk)
    return bytes(received)


def _collect_with_client(
    sources: Sequence[Source], window: CollectionWindow, client: httpx.Client
) -> CollectionResult:
    articles: list[Article] = []
    diagnostics: list[CollectionDiagnostic] = []
    for source in sources:
        try:
            with client.stream(
                "GET",
                source.url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/xml",
                },
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
            ) as response:
                if response.url.scheme.lower() != "https":
                    diagnostics.append(CollectionDiagnostic(source.name, "non_https_redirect"))
                    continue
                if not response.is_success:
                    diagnostics.append(CollectionDiagnostic(source.name, "http_status"))
                    continue
                document = _read_response(response)
            articles.extend(parse_rss(document, source, window))
        except FeedTooLargeError:
            diagnostics.append(CollectionDiagnostic(source.name, "feed_too_large"))
        except FeedParseError:
            diagnostics.append(CollectionDiagnostic(source.name, "invalid_feed"))
        except httpx.HTTPError:
            diagnostics.append(CollectionDiagnostic(source.name, "request_failed"))
    return CollectionResult(tuple(articles), tuple(diagnostics))


def collect_articles(
    sources: Sequence[Source],
    window: CollectionWindow,
    *,
    client: httpx.Client | None = None,
) -> CollectionResult:
    if client is not None:
        return _collect_with_client(sources, window, client)
    with httpx.Client() as owned_client:
        return _collect_with_client(sources, window, owned_client)
