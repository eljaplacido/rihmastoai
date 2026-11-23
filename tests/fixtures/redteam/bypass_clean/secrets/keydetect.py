"""Code that looks for private keys holds the header, not a key."""

import os

PRIVATE_KEY_HEADER = "-----BEGIN RSA PRIVATE KEY-----"
cache_key = "user-profile-cache"
SECRET_KEY = os.environ["SECRET_KEY"]
API_TOKEN = os.environ.get("API_TOKEN", "")
digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def holds_key(text):
    return PRIVATE_KEY_HEADER in text
