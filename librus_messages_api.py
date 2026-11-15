"""Client for the current Librus messages API (wiadomosci.librus.pl).

This module wraps the "new" Librus messaging system, which lives on a
separate domain and requires a session bootstrap through Synergia.
Listing messages and reading the unread counter have no side effects;
fetching a message body marks that message as read in Librus.

Example::

    from librus_apix.client import new_client
    from librus_messages_api import LibrusMessagesApi

    client = new_client()
    client.get_token(username, password)

    api = LibrusMessagesApi(client)
    counts = api.get_unread_counts()           # {"inbox": 2, ...}
    messages = api.list_inbox(unread_only=True)  # list of dicts
    content = api.get_message(message["messageId"])  # full message dict

"""

from __future__ import annotations

import base64
import html
import logging
import re
from typing import Any, Self

import requests
from librus_apix import urls
from librus_apix.client import Client

logger = logging.getLogger(__name__)

_BR_RE = re.compile(r"<\s*/?\s*br\s*/?\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

_BOOTSTRAP_URL = "https://synergia.librus.pl/wiadomosci3"
_API_BASE = "https://wiadomosci.librus.pl/api"
_UNREAD_COUNTS_URL = f"{_API_BASE}/inbox/unreadMessagesCount"
_INBOX_MESSAGES_URL = f"{_API_BASE}/inbox/messages"
_INBOX_MESSAGE_URL = _INBOX_MESSAGES_URL + "/{message_id}"

_REQUEST_TIMEOUT = 30
_PAGE_SIZE = 100


class LibrusMessagesApiError(RuntimeError):
    """Raised when the Librus messages API cannot be used or returns
    an unexpected/unusable response."""


def _decode_base64(value: Any) -> str:
    """Decode a base64 string; return "" for empty or malformed input."""
    if not isinstance(value, str) or not value.strip():
        return ""
    data = value.strip()
    padding = "=" * (-len(data) % 4)
    try:
        raw = base64.b64decode(data + padding, validate=False)
    except ValueError:
        logger.warning("Could not decode base64 message content")
        return ""
    return raw.decode("utf-8", errors="ignore")


def _html_to_text(value: str) -> str:
    """Convert Librus message HTML into plain text, keeping line breaks."""
    if not value:
        return ""
    text = _BR_RE.sub("\n", value)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


class LibrusMessagesApi:
    """Wrapper around the current Librus messages API.

    The constructor opens a session authorised for
    ``https://wiadomosci.librus.pl`` by bootstrapping cookies from Synergia.
    Use :meth:`close` to release the underlying session when done.
    """

    def __init__(self, client: Client) -> None:
        self._session = requests.Session()
        self._session.headers.update(urls.HEADERS)
        self._session.cookies.update(client.token.access_cookies())
        if client.proxy:
            self._session.proxies.update(client.proxy)
        try:
            response = self._session.get(_BOOTSTRAP_URL, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network-dependent
            self._session.close()
            raise LibrusMessagesApiError(
                f"messages API bootstrap failed: {exc}"
            ) from exc

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Low-level helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _raise_for_status(response: requests.Response, url: str) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise LibrusMessagesApiError(
                f"HTTP {response.status_code} from {url}"
            ) from exc

    def _get_json(self, url: str, params: dict[str, str] | None = None) -> dict:
        """GET a JSON object from the messages API or raise a clear error."""
        response = self._session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        self._raise_for_status(response, url)
        try:
            payload = response.json()
        except ValueError as exc:
            raise LibrusMessagesApiError(f"invalid JSON from {url}: {exc}") from exc
        if not isinstance(payload, dict):
            raise LibrusMessagesApiError(f"unexpected JSON payload from {url}")
        return payload

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_unread_counts(self) -> dict[str, int]:
        """Return Librus' unread counters (``{"inbox": N, ...}``).

        Does not mark anything read.
        """
        payload = self._get_json(_UNREAD_COUNTS_URL)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise LibrusMessagesApiError(
                "unread counters payload has no data object"
            )
        counts: dict[str, int] = {}
        for key, value in data.items():
            try:
                counts[key] = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                counts[key] = 0
        return counts

    def list_inbox(
        self,
        *,
        unread_only: bool = False,
        page_size: int = _PAGE_SIZE,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """List inbox messages page by page (newest first).

        Does not mark anything read.
        """
        page_limit = max_pages if max_pages is not None else 10
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        total: int | None = None
        for page in range(1, page_limit + 1):
            params: dict[str, str] = {
                "limit": str(page_size),
                "page": str(page),
            }
            if unread_only:
                params["unreadOnly"] = "1"
            payload = self._get_json(_INBOX_MESSAGES_URL, params)
            batch = payload.get("data")
            if not isinstance(batch, list):
                raise LibrusMessagesApiError(
                    "inbox listing payload has no data array"
                )
            if isinstance(payload.get("total"), int):
                total = payload["total"]
            if not batch:
                break
            added = 0
            for item in batch:
                if not isinstance(item, dict):
                    continue
                message_id = _text(item.get("messageId"))
                if not message_id or message_id in seen:
                    continue
                seen.add(message_id)
                items.append(item)
                added += 1
            if total is not None and len(items) >= total:
                break
            if added == 0:
                logger.info(
                    "Page %d repeats already-seen messages; stopping", page
                )
                break
        else:
            logger.warning(
                "Reached MAX_PAGES=%d while listing messages; results may be partial",
                page_limit,
            )
        return items

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Fetch the full body of a single inbox message.

        **Marks the message as read in Librus.** Returns the parsed
        ``data`` object from the API response.
        """
        payload = self._get_json(
            _INBOX_MESSAGE_URL.format(message_id=message_id)
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise LibrusMessagesApiError(
                f"unexpected payload for message {message_id}"
            )
        return data

    # ------------------------------------------------------------------ #
    # Convenience builders (legacy-compatible shapes)
    # ------------------------------------------------------------------ #

    def message_entry(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Build a webhook-compatible payload entry for one inbox item.

        Returns ``None`` when the message body cannot be fetched, so the
        caller can skip it.
        """
        message_id = _text(item.get("messageId"))
        if not message_id:
            logger.warning("Skipping inbox item without messageId: %r", item)
            return None
        try:
            data = self.get_message(message_id)
        except Exception:
            logger.warning(
                "Skipping message id=%s: failed to fetch content",
                message_id,
                exc_info=True,
            )
            return None

        date = _text(data.get("sendDate")) or _text(item.get("sendDate"))
        if "T" in date:
            date = date.replace("T", " ")
        sender_name = _text(data.get("senderName")) or _text(
            item.get("senderName")
        )
        group = _text(data.get("senderGroup"))
        author = f"{sender_name} ({sender_name}) [{group}]" if sender_name and group else sender_name
        return {
            "id": f"{message_id}/f0",
            "title": _text(data.get("topic")) or _text(item.get("topic")),
            "content": _html_to_text(_decode_base64(data.get("Message"))),
            "author": author,
            "date": date,
            "has_attachment": bool(data.get("attachments"))
            or bool(item.get("isAnyFileAttached")),
        }
