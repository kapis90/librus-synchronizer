# -*- coding: utf-8 -*-
import os
from pathlib import Path
import pickle
from google.oauth2.credentials import Credentials

def create_token_pickle(destination: Path) -> None:
    """Create a token.pickle file with Google API credentials."""
    credentials = Credentials(
        token=os.getenv("G_TOKEN"),
        refresh_token=os.getenv("G_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("G_CLIENT_ID"),
        client_secret=os.getenv("G_CLIENT_SECRET"),
    )
    # Ensure the destination directory exists
    destination.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(credentials, destination.open("wb"))
