"""Core public domain models."""

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit


def _require_https_url(url: str, field_name: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute HTTPS URL")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Source:
    name: str
    url: str
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("source name must not be empty")
        _require_https_url(self.url, "source url")
        if self.priority < 0:
            raise ValueError("source priority must not be negative")


@dataclass(frozen=True, slots=True)
class Article:
    title: str
    description: str
    url: str
    published_at: datetime
    source: Source
    feed_rank: int = 0
    view_count: int | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("article title must not be empty")
        _require_https_url(self.url, "article url")
        _require_aware(self.published_at, "published_at")
        if self.feed_rank < 0:
            raise ValueError("feed rank must not be negative")
        if self.view_count is not None and self.view_count < 0:
            raise ValueError("view count must not be negative")
