"""Safe, deterministic Telegram Bot API delivery."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import cast

import httpx

_SEND_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
_MAX_RETRY_DELAY_SECONDS = 60.0


class TelegramDeliveryError(RuntimeError):
    """A Telegram delivery failure whose message contains no request secrets."""


@dataclass(frozen=True, slots=True)
class _Token:
    raw: str
    visible: bool = False
    entity: bool = False
    starts: tuple[str, str] | None = None
    ends: str | None = None


class _HTMLTokenizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.tokens: list[_Token] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        raw = self.get_starttag_text() or f"<{tag}>"
        self.tokens.append(_Token(raw, starts=(tag, raw)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.tokens.append(_Token(self.get_starttag_text() or f"<{tag}/>"))

    def handle_endtag(self, tag: str) -> None:
        self.tokens.append(_Token(f"</{tag}>", ends=tag))

    def handle_data(self, data: str) -> None:
        if data:
            self.tokens.append(_Token(data, visible=True))

    def handle_entityref(self, name: str) -> None:
        self.tokens.append(_Token(f"&{name};", visible=True, entity=True))

    def handle_charref(self, name: str) -> None:
        self.tokens.append(_Token(f"&#{name};", visible=True, entity=True))


def parse_chat_ids(value: str) -> tuple[str, ...]:
    """Parse comma-separated identifiers without converting their representation."""
    chat_ids = tuple(part.strip() for part in value.split(",") if part.strip())
    if not chat_ids:
        raise ValueError("at least one Telegram chat ID is required")
    return chat_ids


def split_html_message(text: str, *, limit: int = 4096) -> tuple[str, ...]:
    """Split HTML on visible characters while closing and reopening active tags."""
    if limit < 1:
        raise ValueError("message limit must be positive")
    if not text:
        raise ValueError("Telegram message text cannot be empty")

    parser = _HTMLTokenizer()
    parser.feed(text)
    parser.close()

    chunks: list[str] = []
    current: list[str] = []
    open_tags: list[tuple[str, str]] = []
    visible_count = 0

    def flush() -> None:
        nonlocal current, visible_count
        current.extend(f"</{name}>" for name, _raw in reversed(open_tags))
        chunks.append("".join(current))
        current = [raw for _name, raw in open_tags]
        visible_count = 0

    for token in parser.tokens:
        if token.starts is not None:
            current.append(token.raw)
            open_tags.append(token.starts)
            continue
        if token.ends is not None:
            current.append(token.raw)
            if open_tags and open_tags[-1][0] == token.ends:
                open_tags.pop()
            continue
        if not token.visible:
            current.append(token.raw)
            continue

        remaining = token.raw
        while remaining:
            capacity = limit - visible_count
            if capacity == 0:
                flush()
                capacity = limit

            # Entity tokens represent one visible character and must stay atomic.
            if token.entity:
                current.append(remaining)
                visible_count += 1
                remaining = ""
                continue

            cut = min(capacity, len(remaining))
            if len(remaining) > capacity:
                newline = remaining.rfind("\n", 0, capacity + 1)
                if newline >= 0:
                    cut = newline + 1
            current.append(remaining[:cut])
            visible_count += cut
            remaining = remaining[cut:]

    if current:
        current.extend(f"</{name}>" for name, _raw in reversed(open_tags))
        chunks.append("".join(current))
    return tuple(chunks)


def _response_data(response: httpx.Response) -> dict[str, object]:
    try:
        value = response.json()
    except ValueError:
        raise TelegramDeliveryError("Telegram returned an invalid response") from None
    if not isinstance(value, dict):
        raise TelegramDeliveryError("Telegram returned an invalid response")
    return cast(dict[str, object], value)


def _parameters(data: dict[str, object]) -> dict[str, object]:
    value = data.get("parameters")
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _retry_delay(data: dict[str, object]) -> float:
    value = _parameters(data).get("retry_after", 1.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1.0
    return min(max(float(value), 0.0), _MAX_RETRY_DELAY_SECONDS)


def _migrated_chat_id(data: dict[str, object]) -> str | None:
    value = _parameters(data).get("migrate_to_chat_id")
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value)


def _send_one(
    *,
    client: httpx.Client,
    url: str,
    chat_id: str,
    text: str,
    sleep: Callable[[float], None],
    max_retries: int,
) -> None:
    retries = 0
    migrated = False
    destination = chat_id
    while True:
        try:
            response = client.post(
                url,
                json={
                    "chat_id": destination,
                    "text": text,
                    "parse_mode": "HTML",
                    "link_preview_options": {"is_disabled": True},
                },
                timeout=_SEND_TIMEOUT,
            )
        except httpx.HTTPError:
            if retries < max_retries:
                sleep(min(2.0**retries, 8.0))
                retries += 1
                continue
            raise TelegramDeliveryError("Telegram request failed") from None

        data = _response_data(response)
        if response.status_code == 429 and retries < max_retries:
            sleep(_retry_delay(data))
            retries += 1
            continue
        if 200 <= response.status_code < 300 and data.get("ok") is True:
            return

        migrated_destination = _migrated_chat_id(data)
        if migrated_destination is not None and not migrated:
            destination = migrated_destination
            migrated = True
            continue
        if response.status_code == 429:
            raise TelegramDeliveryError("Telegram rate limit exceeded")
        if not 200 <= response.status_code < 300:
            raise TelegramDeliveryError("Telegram request failed")
        raise TelegramDeliveryError("Telegram rejected the message")


def send_telegram_message(
    *,
    token: str,
    chat_ids: str | Sequence[str],
    text: str,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] | None = None,
    max_retries: int = 2,
) -> None:
    """Send HTML chunks to recipients in the supplied deterministic order."""
    if not token:
        raise ValueError("Telegram bot token is required")
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")
    recipients = parse_chat_ids(chat_ids) if isinstance(chat_ids, str) else tuple(chat_ids)
    if not recipients or any(not recipient for recipient in recipients):
        raise ValueError("at least one Telegram chat ID is required")

    chunks = split_html_message(text)
    sleeper = sleep if sleep is not None else time.sleep
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    owned_client = client is None
    session = client if client is not None else httpx.Client(timeout=_SEND_TIMEOUT)
    try:
        for recipient in recipients:
            for chunk in chunks:
                _send_one(
                    client=session,
                    url=url,
                    chat_id=recipient,
                    text=chunk,
                    sleep=sleeper,
                    max_retries=max_retries,
                )
    finally:
        if owned_client:
            session.close()
