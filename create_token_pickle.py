# -*- coding: utf-8 -*-
import os
from pathlib import Path
import pickle
from google.oauth2.credentials import Credentials

def create_token_pickle(destination: Path) -> None:
    """Create a token.pickle file with Google API credentials."""
    credentials = Credentials(
        token=os.getenv("G_TOKEN"),
    )
    pickle.dump(credentials, destination.open("wb"))
