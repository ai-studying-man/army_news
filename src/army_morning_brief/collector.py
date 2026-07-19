"""Bounded, failure-isolated collection of public RSS documents."""

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit
from xml.etree import ElementTree
from xml.parsers import expat

import httpx

from army_morning_brief.config import CollectionWindow
from army_morning_brief.models import Article, Source

MAX_FEED_BYTES = 5 * 1024 * 1024
REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
USER_AGENT = "army-morning-brief/0.1 (+public-rss-collector)"
MAX_RETRIES = 2
MAX_SOURCE_SECONDS = 60.0
_RETRY_DELAYS = (0.5, 1.0)
_MAX_RETRY_DELAY_SECONDS = 5.0
_TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class FeedParseError(ValueError):
    """Raised when an RSS document cannot be parsed."""


class FeedTooLargeError(FeedParseError):
    """Raised when an RSS document exceeds the byte cap."""


class _UnsafeXmlDeclaration(Exception):
    """Raised by the Expat preflight parser for DTD/entity declarations."""


class _SourceTimeLimitExceeded(Exception):
    """Raised when a source exceeds its bounded collection time budget."""


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


def _item_publisher_source(item: ElementTree.Element, feed_source: Source) -> Source | None:
    publisher = next(
        (child for child in item if _local_name(child.tag) == "source"),
        None,
    )
    if publisher is None:
        return None
    name = _visible_text("".join(publisher.itertext()).strip())
    url = (publisher.get("url") or "").strip()
    if not name or not _is_https_url(url):
        return None
    try:
        return Source(name=name, url=url, priority=feed_source.priority)
    except ValueError:
        return None


def _normalize_title(title: str, item_source: Source | None) -> str:
    if item_source is None:
        return title
    suffix = f" - {item_source.name}"
    if not title.endswith(suffix):
        return title
    normalized = title[: -len(suffix)].rstrip()
    return normalized or title


def _reject_unsafe_xml_declaration(*_args: object) -> None:
    raise _UnsafeXmlDeclaration


def _preflight_xml(xml: bytes) -> None:
    """Validate XML syntax and reject declarations before ElementTree sees bytes."""
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _reject_unsafe_xml_declaration
    parser.EntityDeclHandler = _reject_unsafe_xml_declaration
    # Keep entity references as parser input; never ask Expat to expand them.
    parser.DefaultHandler = lambda _data: None
    try:
        parser.Parse(xml, True)
    except _UnsafeXmlDeclaration:
        raise FeedParseError("invalid RSS XML") from None
    except expat.ExpatError as error:
        raise FeedParseError("invalid RSS XML") from error


def parse_rss(xml: bytes, source: Source, window: CollectionWindow) -> tuple[Article, ...]:
    if len(xml) > MAX_FEED_BYTES:
        raise FeedTooLargeError("RSS document exceeds size limit")
    _preflight_xml(xml)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise FeedParseError("invalid RSS XML") from error

    articles: list[Article] = []
    items = (element for element in root.iter() if _local_name(element.tag) == "item")
    for feed_rank, item in enumerate(items):
        title = _visible_text(_child_text(item, "title"))
        item_source = _item_publisher_source(item, source)
        article_source = item_source or source
        title = _normalize_title(title, item_source)
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
                    source=article_source,
                    feed_rank=feed_rank,
                )
            )
        except ValueError:
            continue
    return tuple(articles)


def _read_response(response: httpx.Response, *, deadline: float | None = None) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_FEED_BYTES:
                raise FeedTooLargeError("RSS document exceeds size limit")
        except ValueError:
            pass

    if deadline is not None and time.monotonic() >= deadline:
        raise _SourceTimeLimitExceeded
    received = bytearray()
    for chunk in response.iter_bytes():
        if deadline is not None and time.monotonic() >= deadline:
            raise _SourceTimeLimitExceeded
        if len(received) + len(chunk) > MAX_FEED_BYTES:
            raise FeedTooLargeError("RSS document exceeds size limit")
        received.extend(chunk)
    if deadline is not None and time.monotonic() >= deadline:
        raise _SourceTimeLimitExceeded
    return bytes(received)


def _timeout_for_remaining(remaining: float) -> httpx.Timeout:
    def cap(value: float | None) -> float:
        return remaining if value is None else min(value, remaining)

    return httpx.Timeout(
        connect=cap(REQUEST_TIMEOUT.connect),
        read=cap(REQUEST_TIMEOUT.read),
        write=cap(REQUEST_TIMEOUT.write),
        pool=cap(REQUEST_TIMEOUT.pool),
    )


def _retry_delay(attempt: int, response: httpx.Response | None = None) -> float:
    if response is not None:
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            try:
                parsed = float(retry_after)
            except ValueError:
                parsed = math.nan
            if math.isfinite(parsed) and parsed >= 0:
                return min(parsed, _MAX_RETRY_DELAY_SECONDS)
    return _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]


def _fetch_source_document(
    source: Source,
    client: httpx.Client,
    *,
    sleep: Callable[[float], None],
    max_retries: int,
) -> tuple[bytes | None, str | None]:
    """Fetch one source with bounded retries and a source-wide time budget."""
    deadline = time.monotonic() + MAX_SOURCE_SECONDS
    for attempt in range(max_retries + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, "request_failed"
        retry_delay: float | None = None
        failure_code = "request_failed"
        document: bytes | None = None
        try:
            with client.stream(
                "GET",
                source.url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/rss+xml, application/xml",
                },
                timeout=_timeout_for_remaining(remaining),
                follow_redirects=True,
            ) as response:
                if response.url.scheme.lower() != "https":
                    return None, "non_https_redirect"
                if response.is_success:
                    document = _read_response(response, deadline=deadline)
                elif response.status_code in _TRANSIENT_STATUS_CODES:
                    failure_code = "http_status"
                    if attempt < max_retries:
                        retry_delay = _retry_delay(attempt, response)
                else:
                    return None, "http_status"
        except FeedTooLargeError:
            return None, "feed_too_large"
        except (httpx.HTTPError, _SourceTimeLimitExceeded):
            if attempt < max_retries:
                retry_delay = _retry_delay(attempt)

        if document is not None:
            return document, None
        if retry_delay is None:
            return None, failure_code
        if time.monotonic() + retry_delay >= deadline:
            return None, failure_code
        sleep(retry_delay)
    return None, "request_failed"


def _collect_with_client(
    sources: Sequence[Source],
    window: CollectionWindow,
    client: httpx.Client,
    *,
    sleep: Callable[[float], None],
    max_retries: int,
) -> CollectionResult:
    articles: list[Article] = []
    diagnostics: list[CollectionDiagnostic] = []
    for source in sources:
        document, diagnostic = _fetch_source_document(
            source,
            client,
            sleep=sleep,
            max_retries=max_retries,
        )
        if diagnostic is not None:
            diagnostics.append(CollectionDiagnostic(source.name, diagnostic))
            continue
        if document is None:
            diagnostics.append(CollectionDiagnostic(source.name, "request_failed"))
            continue
        try:
            articles.extend(parse_rss(document, source, window))
        except FeedTooLargeError:
            diagnostics.append(CollectionDiagnostic(source.name, "feed_too_large"))
        except FeedParseError:
            diagnostics.append(CollectionDiagnostic(source.name, "invalid_feed"))
    return CollectionResult(tuple(articles), tuple(diagnostics))


def collect_articles(
    sources: Sequence[Source],
    window: CollectionWindow,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] | None = None,
    max_retries: int = MAX_RETRIES,
) -> CollectionResult:
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")
    sleeper = time.sleep if sleep is None else sleep
    if client is not None:
        return _collect_with_client(
            sources,
            window,
            client,
            sleep=sleeper,
            max_retries=max_retries,
        )
    with httpx.Client() as owned_client:
        return _collect_with_client(
            sources,
            window,
            owned_client,
            sleep=sleeper,
            max_retries=max_retries,
        )
