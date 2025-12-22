# -*- coding: utf-8 -*-
import json
import logging
import os

from librus_apix.client import Client, Token, new_client
from retry import retry
from urllib3.exceptions import MaxRetryError, ConnectionError, ProtocolError

from logging_config import setup_logging
from librus_apix.messages import get_received, message_content

logger = logging.getLogger(__name__)


@retry(exceptions=(MaxRetryError, ConnectionError, ProtocolError), tries=3, delay=2)
def __aquire_librus_token(client: Client) -> Token:
    """Aquire Librus token using environment variables LIBRUS_USERNAME and LIBRUS_PASSWORD."""
    return client.get_token(
        str(os.getenv("LIBRUS_USERNAME")), str(os.getenv("LIBRUS_PASSWORD"))
    )


def main():
    # configure logging early; allow DEBUG by environment flag
    debug = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
    log_file = os.getenv("LOG_FILE")
    setup_logging(debug=debug, log_file=log_file)

    client: Client = new_client()
    _token: Token = __aquire_librus_token(client)
    client.token = _token

    messages = get_received(client, page=1)
    unread_messages = []
    for message in messages:
        if message.unread:
            content = message_content(client, message.href)
            unread_messages.append({"title": message.title, "content": content})

    # Output as JSON for webhook payload
    payload = {"messages": unread_messages}
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
