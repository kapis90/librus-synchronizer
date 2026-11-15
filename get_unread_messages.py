"""Fetch unread Librus messages and print them as JSON for webhook use.

Stdout contains ONLY the JSON payload (logs go to stderr), so a workflow
can safely redirect stdout to a file and POST it.

Unread detection uses the current Librus messages API
(``https://wiadomosci.librus.pl``), which reports the read state explicitly
with the ``readDate`` field. That makes the result authoritative: the script
first reads Librus' own unread counter, so an empty ``messages`` array means
Librus really has no unread messages. The legacy HTML inbox is only used as a
fallback when the new API is unavailable.

Fetching a message body (``GET /api/inbox/messages/<id>``) marks that message
as read in Librus, so every unread message is reported exactly once. Listing
messages and reading the unread counter have no side effects.

Environment:
    FETCH_MODE: "unread" (default) reports only unread messages; "last"
        reports the most recent inbox message regardless of read state
        (for testing webhook plumbing).
    MAX_PAGES: safety cap for paginated inbox listings (default 10).
    DEBUG, LOG_FILE: logging configuration.
"""

import base64
import html
import json
import logging
import os
import re
import sys
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag
from librus_apix import urls
from librus_apix.client import Client, Token, new_client
from librus_apix.exceptions import ParseError
from librus_apix.helpers import no_access_check
from librus_apix.messages import Message, get_max_page_number, message_content
from requests import Session
from retry import retry
from urllib3.exceptions import ConnectionError, MaxRetryError, ProtocolError

from logging_config import setup_logging

logger = logging.getLogger(__name__)

# Current Librus messages API. Cookies for wiadomosci.librus.pl are issued
# by the Synergia bootstrap page, so it has to be opened in the same session.
_BOOTSTRAP_URL = "https://synergia.librus.pl/wiadomosci3"
_API_BASE = "https://wiadomosci.librus.pl/api"
_UNREAD_COUNTS_URL = f"{_API_BASE}/inbox/unreadMessagesCount"
_INBOX_MESSAGES_URL = f"{_API_BASE}/inbox/messages"
_INBOX_MESSAGE_URL = _INBOX_MESSAGES_URL + "/{message_id}"

_REQUEST_TIMEOUT = 30  # seconds
_PAGE_SIZE = 100

# Matches "font-weight: bold" tolerating whitespace/case variants such as
# "font-weight:bold" or "FONT-WEIGHT: BOLD", which the upstream
# librus_apix parser misses (it uses an exact substring check).
# Only used by the legacy HTML fallback.
_UNREAD_STYLE_RE = re.compile(r"font-weight\s*:\s*bold", re.IGNORECASE)

# Safety cap for inbox pagination (overridable via MAX_PAGES env var).
_DEFAULT_MAX_PAGES = 10

# Librus inbox POST parameters (container id 105), same as upstream.
_PAGE_PARAM = "numer_strony105"
_PAGE_CONTAINER_PARAM = "porcjowanie_pojemnik105"
_PAGE_CONTAINER_ID = "105"

_BR_RE = re.compile(r"<\s*/?\s*br\s*/?\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


class _NewApiUnavailable(RuntimeError):
    """Raised when the current messages API cannot be used."""


@retry(exceptions=(MaxRetryError, ConnectionError, ProtocolError), tries=3, delay=2)
def __acquire_librus_token(client: Client, username: str, password: str) -> Token:
    """Acquire Librus token for the given credentials."""
    # Note: Client.get_token() also assigns client.token itself.
    return client.get_token(username, password)


def _require_env(name: str) -> str:
    """Return env var value or exit(1) with a clear error (no stdout payload)."""
    value = os.getenv(name)
    if not value:
        logger.error("Missing required environment variable: %s", name)
        sys.exit(1)
    return value


def _page_cap() -> int:
    try:
        return max(1, int(os.getenv("MAX_PAGES", str(_DEFAULT_MAX_PAGES))))
    except ValueError:
        logger.warning("Invalid MAX_PAGES value; using default %d", _DEFAULT_MAX_PAGES)
        return _DEFAULT_MAX_PAGES


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _decode_base64(value: object) -> str:
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


def _format_author(data: dict) -> str:
    """Build the author label in the format used by the legacy payload."""
    name = _text(data.get("senderName"))
    if not name:
        name = " ".join(
            part
            for part in (
                _text(data.get("senderFirstName")),
                _text(data.get("senderLastName")),
            )
            if part
        )
    group = _text(data.get("senderGroup"))
    if name and group:
        return f"{name} ({name}) [{group}]"
    return name


# ---------------------------------------------------------------------------
# Current messages API
# ---------------------------------------------------------------------------


def _open_messages_session(client: Client) -> Session:
    """Open a session authorised for the Librus messages API (with cookies)."""
    session = Session()
    session.headers.update(urls.HEADERS)
    session.cookies.update(client.token.access_cookies())
    if client.proxy:
        session.proxies.update(client.proxy)
    try:
        response = session.get(_BOOTSTRAP_URL, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        session.close()
        raise _NewApiUnavailable(f"messages API bootstrap failed: {exc}") from exc
    return session


@retry(
    exceptions=(requests.ConnectionError, requests.Timeout),
    tries=3,
    delay=2,
    backoff=2,
    logger=logger,
)
def _request_json(session: Session, url: str, params: dict | None = None) -> dict:
    """GET a JSON object from the messages API or raise a clear error."""
    response = session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise _NewApiUnavailable(
            f"HTTP {response.status_code} from {url}"
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise _NewApiUnavailable(f"invalid JSON from {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise _NewApiUnavailable(f"unexpected JSON payload from {url}")
    return payload


def _unread_counts(session: Session) -> dict:
    """Return Librus' unread counters (``{"inbox": N, ...}``)."""
    payload = _request_json(session, _UNREAD_COUNTS_URL)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise _NewApiUnavailable("unread counters payload has no data object")
    return data


def _list_inbox(
    session: Session,
    *,
    unread_only: bool,
    page_size: int = _PAGE_SIZE,
    max_pages: int | None = None,
) -> list[dict]:
    """List inbox messages page by page (newest first)."""
    page_limit = max_pages if max_pages is not None else _page_cap()
    items: list[dict] = []
    seen: set[str] = set()
    total: int | None = None
    for page in range(1, page_limit + 1):
        params: dict[str, str] = {"limit": str(page_size), "page": str(page)}
        if unread_only:
            params["unreadOnly"] = "1"
        payload = _request_json(session, _INBOX_MESSAGES_URL, params)
        batch = payload.get("data")
        if not isinstance(batch, list):
            raise _NewApiUnavailable("inbox listing payload has no data array")
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
            logger.info("Page %d repeats already-seen messages; stopping", page)
            break
    else:
        logger.warning(
            "Reached MAX_PAGES=%d while listing messages; results may be partial",
            page_limit,
        )
    return items


def _build_entry(session: Session, item: dict) -> dict | None:
    """Fetch one message body and build its webhook payload entry.

    Fetching the body marks the message as read in Librus, so the message is
    reported only once. Returns None (after logging) when the body cannot be
    fetched, so the caller can skip it.
    """
    message_id = _text(item.get("messageId"))
    if not message_id:
        logger.warning("Skipping inbox item without messageId: %r", item)
        return None
    try:
        payload = _request_json(
            session, _INBOX_MESSAGE_URL.format(message_id=message_id)
        )
    except Exception:
        logger.warning(
            "Skipping message id=%s: failed to fetch content",
            message_id,
            exc_info=True,
        )
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        logger.warning("Skipping message id=%s: unexpected payload", message_id)
        return None

    date = _text(data.get("sendDate")) or _text(item.get("sendDate"))
    if "T" in date:
        date = date.replace("T", " ")
    return {
        # Keep the legacy "<id>/f0" shape so downstream consumers that
        # already store message ids keep working.
        "id": f"{message_id}/f0",
        "title": _text(data.get("topic")) or _text(item.get("topic")),
        "content": _html_to_text(_decode_base64(data.get("Message"))),
        "author": _format_author(data) or _text(item.get("senderName")),
        "date": date,
        "has_attachment": bool(data.get("attachments"))
        or bool(item.get("isAnyFileAttached")),
    }


def _fetch_unread_new(session: Session) -> list[dict]:
    """Report unread messages using the current messages API."""
    counts = _unread_counts(session)
    inbox_count = max(0, _as_int(counts.get("inbox")))
    logger.info(
        "Librus reports %d unread message(s) in the inbox (counts=%s)",
        inbox_count,
        counts,
    )
    if inbox_count == 0:
        return []

    items = _list_inbox(session, unread_only=True)
    logger.info("Listed %d unread message(s)", len(items))
    if not items:
        # The unread counter was non-zero a moment ago; it can drop to zero if
        # somebody read the message in the Librus app in the meantime.
        latest = max(0, _as_int(_unread_counts(session).get("inbox")))
        if latest == 0:
            logger.info(
                "Unread messages were read elsewhere while this run was listing; "
                "reporting an empty list"
            )
            return []
        raise RuntimeError(
            f"Librus reports {latest} unread message(s), but the listing returned "
            "none; refusing to report an empty list"
        )
    if len(items) < inbox_count:
        logger.warning(
            "Unread counter reports %d message(s) but the listing returned %d",
            inbox_count,
            len(items),
        )

    entries: list[dict] = []
    seen_ids: set[str] = set()
    for item in items:
        entry = _build_entry(session, item)
        if entry is None:
            continue
        if entry["id"] in seen_ids:
            logger.warning("Skipping duplicate message id=%r", entry["id"])
            continue
        seen_ids.add(entry["id"])
        entries.append(entry)

    if not entries:
        # Never send an empty payload when Librus says there is something
        # unread: that is exactly the bug this check guards against.
        raise RuntimeError(
            f"Librus reports {inbox_count} unread message(s), but none could be "
            "fetched; refusing to report an empty list"
        )
    return entries


def _fetch_last_new(session: Session) -> list[dict]:
    """Return a one-item list with the most recent inbox message."""
    logger.warning(
        "FETCH_MODE=last: returning most recent message regardless of "
        "read state (testing only)"
    )
    items = _list_inbox(session, unread_only=False, page_size=1, max_pages=1)
    if not items:
        logger.info("Inbox is empty, nothing to report")
        return []
    entry = _build_entry(session, items[0])
    if entry is None:
        raise RuntimeError("Most recent message could not be fetched")
    return [entry]


# ---------------------------------------------------------------------------
# Legacy HTML inbox (fallback only)
# ---------------------------------------------------------------------------


def _is_unread(title_cell: Tag) -> bool:
    """Robust unread check for an inbox title <td>.

    Checks the cell's own style plus any descendant element styles, and
    falls back to <b>/<strong> markup (bold title == unread convention).
    """
    elements = [title_cell, *title_cell.find_all(style=True)]
    for el in elements:
        style = el.get("style", "")
        if isinstance(style, list):
            style = " ".join(style)
        if style and _UNREAD_STYLE_RE.search(str(style)):
            return True
    return title_cell.find(["b", "strong"]) is not None


def _raw_link(cell: Tag) -> str:
    """Return the first link href in a cell, or "" if there is none."""
    link = cell.find("a")
    if isinstance(link, Tag):
        href = link.attrs.get("href", "")
        if isinstance(href, str):
            return href.strip()
    return ""


def _legacy_content_ref(client: Client, raw_href: object) -> str:
    """Build the content reference for message_content() without ever raising.

    Real inbox links look like ``/wiadomosci/1/5/<msgId>/f0`` and
    message_content() appends its argument to MESSAGE_URL, so we return the
    href path relative to MESSAGE_URL's path (e.g. ``<msgId>/f0``). This
    preserves the exact server-issued path instead of guessing which
    segment is the id. Unknown shapes fall back to the last path segment;
    non-http(s) links (e.g. ``javascript:...``) and empty input yield "".
    """
    if not isinstance(raw_href, str) or not raw_href.strip():
        return ""
    parts = urlparse(raw_href.strip())
    if parts.scheme and parts.scheme not in ("http", "https"):
        return ""
    path = parts.path
    if not path or not path.strip("/"):
        return ""
    base_path = urlparse(client.MESSAGE_URL).path.rstrip("/")
    if path.startswith(base_path + "/"):
        return path[len(base_path) + 1 :].strip().strip("/")
    if path == base_path:
        return ""
    return path.rstrip("/").split("/")[-1].strip()


def _parse_inbox(soup: BeautifulSoup) -> list[Message]:
    """Parse an inbox page into Message objects, skipping malformed rows."""
    table = soup.find("table", attrs={"class": "decorated stretch"})
    if table is None:
        raise ParseError("Error in parsing messages.")
    tbody = table.find("tbody") if isinstance(table, Tag) else None
    if not isinstance(tbody, Tag):
        raise ParseError("Error in parsing messages (tbody).")
    rows = tbody.find_all("tr", attrs={"class": ["line0", "line1"]})
    if not rows:
        return []
    if len(rows) == 1 and rows[0].text.strip() == "Brak wiadomości":
        return []
    messages: list[Message] = []
    for row in rows:
        cells = row.find_all("td") if isinstance(row, Tag) else []
        if len(cells) < 6:
            logger.warning(
                "Skipping malformed message row with %d cells (expected >= 6)",
                len(cells),
            )
            continue
        _tick, attachment, author_cell, title_cell, date_cell, _trash = cells[:6]
        has_attachment = (
            attachment.find("img") is not None if isinstance(attachment, Tag) else False
        )
        unread = _is_unread(title_cell) if isinstance(title_cell, Tag) else False
        # Prefer the title-cell link (the message link); fall back to the
        # author-cell link. The raw href is stored; _build_entry_legacy()
        # resolves it against MESSAGE_URL when fetching content.
        href = ""
        if isinstance(title_cell, Tag):
            href = _raw_link(title_cell)
        if not href and isinstance(author_cell, Tag):
            href = _raw_link(author_cell)
        messages.append(
            Message(
                author=author_cell.text.strip(),
                title=title_cell.text.strip(),
                date=date_cell.text.strip(),
                href=href,
                unread=unread,
                has_attachment=has_attachment,
            )
        )
    return messages


def _fetch_received_page(client: Client, page: int) -> list[Message]:
    """Fetch and parse one inbox page (1-based)."""
    payload = {
        _PAGE_PARAM: str(page),
        _PAGE_CONTAINER_PARAM: _PAGE_CONTAINER_ID,
    }
    response = client.post(client.MESSAGE_URL, data=payload)
    soup = no_access_check(BeautifulSoup(response.text, "lxml"))
    return _parse_inbox(soup)


def _fetch_all_received(client: Client) -> list[Message]:
    """Fetch all inbox pages, stopping early on the first empty page."""
    try:
        max_page_hint = get_max_page_number(client)
    except Exception:
        logger.warning(
            "Could not determine inbox page count; fetching until empty page",
            exc_info=True,
        )
        max_page_hint = None
    # Upstream get_max_page_number() returns N-1 for N pages, so the last
    # real page is hint+1. Probing further is safe: out-of-range pages are
    # clamped by the server to the last page instead of coming back empty,
    # so the seen-href check below stops the loop on a repeated page.
    cap = _page_cap()
    if max_page_hint is not None:
        cap = min(cap, max(1, max_page_hint + 1))
    all_messages: list[Message] = []
    seen_hrefs: set[str] = set()
    for page in range(1, cap + 1):
        try:
            messages = _fetch_received_page(client, page)
        except Exception:
            if page == 1:
                raise
            logger.warning("Stopping pagination: page %d failed", page, exc_info=True)
            break
        if not messages:
            break
        fresh = [m for m in messages if not m.href or m.href not in seen_hrefs]
        if len(fresh) < len(messages):
            if not fresh:
                logger.info(
                    "Page %d repeats earlier messages (server clamped the "
                    "page); stopping pagination",
                    page,
                )
                break
            logger.warning(
                "Page %d contains %d already-seen message(s)",
                page,
                len(messages) - len(fresh),
            )
        seen_hrefs.update(m.href for m in fresh if m.href)
        logger.debug("Page %d: %d message(s)", page, len(fresh))
        all_messages.extend(fresh)
    return all_messages


def _build_entry_legacy(client: Client, message: Message) -> dict | None:
    """Fetch content for one message and build its payload dict."""
    ref = _legacy_content_ref(client, message.href)
    if not ref:
        logger.warning(
            "Skipping message without usable link (title=%r author=%r href=%r)",
            message.title,
            message.author,
            message.href,
        )
        return None
    try:
        # NOTE: opening a message may mark it as read server-side,
        # so each unread message is typically reported only once.
        content = message_content(client, ref)
    except Exception:
        logger.warning(
            "Skipping message ref=%r: failed to fetch content",
            ref,
            exc_info=True,
        )
        return None
    return {
        "id": ref,
        "title": content.title or message.title,
        "content": content.content,
        "author": content.author or message.author,
        "date": content.date or message.date,
        "has_attachment": message.has_attachment,
    }


def _fetch_unread_legacy(client: Client) -> list[dict]:
    """Report unread messages using the deprecated HTML inbox."""
    logger.warning(
        "Falling back to the legacy HTML inbox; unread detection may be less "
        "reliable than the messages API"
    )
    messages = _fetch_all_received(client)
    logger.info("Fetched %d message(s) from legacy inbox", len(messages))

    unread = [m for m in messages if m.unread]
    logger.info("%d unread message(s) found in legacy inbox", len(unread))

    entries: list[dict] = []
    seen_ids: set[str] = set()
    for message in unread:
        entry = _build_entry_legacy(client, message)
        if entry is None:
            continue
        entry_id = entry["id"]
        if entry_id in seen_ids:
            logger.warning("Skipping duplicate message id=%r", entry_id)
            continue
        seen_ids.add(entry_id)
        entries.append(entry)

    if unread and not entries:
        raise RuntimeError(
            f"Legacy inbox reports {len(unread)} unread message(s), but none "
            "could be fetched; refusing to report an empty list"
        )
    return entries


def _fetch_last_legacy(client: Client) -> list[dict]:
    """Return a one-item list with the most recent legacy inbox message."""
    logger.warning(
        "FETCH_MODE=last: returning most recent message regardless of "
        "read state (testing only)"
    )
    page = _fetch_received_page(client, 1)
    if not page:
        logger.info("Inbox is empty, nothing to report")
        return []
    for message in page:
        entry = _build_entry_legacy(client, message)
        if entry is not None:
            return [entry]
    raise RuntimeError("Most recent message could not be fetched")


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------


def fetch_unread(client: Client) -> list[dict]:
    """Return payload entries for unread messages.

    Falls back to the legacy HTML inbox only when the messages API cannot be
    reached or does not have the expected shape *before* any message body is
    fetched (so a partial run can never lose already-read messages).
    """
    try:
        session = _open_messages_session(client)
    except _NewApiUnavailable as exc:
        logger.warning("Messages API unavailable: %s", exc)
        return _fetch_unread_legacy(client)

    try:
        try:
            return _fetch_unread_new(session)
        except _NewApiUnavailable as exc:
            logger.warning("Messages API unavailable: %s", exc)
            return _fetch_unread_legacy(client)
    finally:
        session.close()


def fetch_last(client: Client) -> list[dict]:
    """Return a one-item payload with the most recent inbox message."""
    try:
        session = _open_messages_session(client)
    except _NewApiUnavailable as exc:
        logger.warning("Messages API unavailable: %s", exc)
        return _fetch_last_legacy(client)

    try:
        return _fetch_last_new(session)
    except _NewApiUnavailable as exc:
        logger.warning("Messages API unavailable: %s", exc)
        return _fetch_last_legacy(client)
    finally:
        session.close()


def main():
    # configure logging early; allow DEBUG by environment flag
    debug = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
    log_file = os.getenv("LOG_FILE")
    setup_logging(debug=debug, log_file=log_file)

    username = _require_env("LIBRUS_USERNAME")
    password = _require_env("LIBRUS_PASSWORD")
    mode = os.getenv("FETCH_MODE", "unread").strip().lower()
    if mode not in ("unread", "last"):
        logger.error("Invalid FETCH_MODE=%r (expected 'unread' or 'last')", mode)
        sys.exit(1)

    client: Client = new_client()
    __acquire_librus_token(client, username, password)

    if mode == "last":
        reported = fetch_last(client)
        logger.info("Reporting %d message(s) (FETCH_MODE=last)", len(reported))
    else:
        reported = fetch_unread(client)
        if reported:
            logger.info("Reporting %d unread message(s) with content", len(reported))
        else:
            logger.info("No unread messages; reporting an empty list")

    # Output as JSON for webhook payload (stdout must stay pure JSON)
    payload = {"messages": reported}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
