# -*- coding: utf-8 -*-
"""Fetch unread Librus messages and print them as JSON for webhook use.

Stdout contains ONLY the JSON payload (logs go to stderr), so a workflow
can safely redirect stdout to a file and POST it.
"""

import json
import logging
import os
import re
import sys
from typing import List

from bs4 import BeautifulSoup, Tag
from librus_apix.client import Client, Token, new_client
from librus_apix.exceptions import ParseError
from librus_apix.helpers import no_access_check
from librus_apix.messages import Message, get_max_page_number, message_content
from retry import retry
from urllib3.exceptions import MaxRetryError, ConnectionError, ProtocolError

from logging_config import setup_logging

logger = logging.getLogger(__name__)

# Matches "font-weight: bold" tolerating whitespace/case variants such as
# "font-weight:bold" or "FONT-WEIGHT: BOLD", which the upstream
# librus_apix parser misses (it uses an exact substring check).
_UNREAD_STYLE_RE = re.compile(r"font-weight\s*:\s*bold", re.IGNORECASE)

# Safety cap for inbox pagination (overridable via MAX_PAGES env var).
_DEFAULT_MAX_PAGES = 10

# Librus inbox POST parameters (container id 105), same as upstream.
_PAGE_PARAM = "numer_strony105"
_PAGE_CONTAINER_PARAM = "porcjowanie_pojemnik105"
_PAGE_CONTAINER_ID = "105"


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
    if title_cell.find(["b", "strong"]) is not None:
        return True
    return False


def _safe_href(raw_href: object) -> str:
    """Extract the message id from a link href without ever raising.

    Upstream takes ``href.split("/")[4]`` which raises IndexError on short
    hrefs and returns the wrong segment on longer ones; the id is simply
    the last path segment.
    """
    if not isinstance(raw_href, str) or not raw_href.strip():
        return ""
    cleaned = raw_href.strip().split("?")[0].split("#")[0].rstrip("/")
    if not cleaned:
        return ""
    return cleaned.split("/")[-1].strip()


def _parse_inbox(soup: BeautifulSoup) -> List[Message]:
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
    messages: List[Message] = []
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
        href = ""
        if isinstance(author_cell, Tag):
            author_link = author_cell.find("a")
            if isinstance(author_link, Tag):
                href = _safe_href(author_link.attrs.get("href", ""))
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


def _fetch_received_page(client: Client, page: int) -> List[Message]:
    """Fetch and parse one inbox page (1-based)."""
    payload = {
        _PAGE_PARAM: str(page),
        _PAGE_CONTAINER_PARAM: _PAGE_CONTAINER_ID,
    }
    response = client.post(client.MESSAGE_URL, data=payload)
    soup = no_access_check(BeautifulSoup(response.text, "lxml"))
    return _parse_inbox(soup)


def _page_cap() -> int:
    try:
        return max(1, int(os.getenv("MAX_PAGES", str(_DEFAULT_MAX_PAGES))))
    except ValueError:
        logger.warning("Invalid MAX_PAGES value; using default %d", _DEFAULT_MAX_PAGES)
        return _DEFAULT_MAX_PAGES


def fetch_all_received(client: Client) -> List[Message]:
    """Fetch all inbox pages, stopping early on the first empty page."""
    try:
        max_page_hint = get_max_page_number(client)
    except Exception:
        logger.warning(
            "Could not determine inbox page count; fetching until empty page",
            exc_info=True,
        )
        max_page_hint = None
    # Upstream get_max_page_number() returns N-1 for N pages, so probe a
    # couple of pages past the hint; the empty-page break keeps this cheap.
    cap = _page_cap()
    if max_page_hint is not None:
        cap = min(cap, max(1, max_page_hint + 2))
    all_messages: List[Message] = []
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
        logger.debug("Page %d: %d message(s)", page, len(messages))
        all_messages.extend(messages)
    return all_messages


def main():
    # configure logging early; allow DEBUG by environment flag
    debug = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
    log_file = os.getenv("LOG_FILE")
    setup_logging(debug=debug, log_file=log_file)

    username = _require_env("LIBRUS_USERNAME")
    password = _require_env("LIBRUS_PASSWORD")

    client: Client = new_client()
    __acquire_librus_token(client, username, password)

    messages = fetch_all_received(client)
    logger.info("Fetched %d message(s) from inbox", len(messages))

    unread = [m for m in messages if m.unread]
    logger.info("%d unread message(s) found", len(unread))

    unread_messages = []
    for message in unread:
        if not message.href:
            logger.warning(
                "Skipping unread message without link (title=%r author=%r)",
                message.title,
                message.author,
            )
            continue
        try:
            # NOTE: opening a message may mark it as read server-side,
            # so each unread message is typically reported only once.
            content = message_content(client, message.href)
        except Exception:
            logger.warning(
                "Skipping message id=%r: failed to fetch content",
                message.href,
                exc_info=True,
            )
            continue
        unread_messages.append(
            {
                "id": message.href,
                "title": content.title or message.title,
                "content": content.content,
                "author": content.author or message.author,
                "date": content.date or message.date,
                "has_attachment": message.has_attachment,
            }
        )

    logger.info("Reporting %d unread message(s) with content", len(unread_messages))
    # Output as JSON for webhook payload (stdout must stay pure JSON)
    payload = {"messages": unread_messages}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
