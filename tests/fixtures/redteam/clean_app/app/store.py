"""Where the product keeps its data and its users."""

import hashlib
import json
import os
import tempfile

import yaml


def load_snapshot(blob):
    return json.loads(blob)


def load_settings(text):
    return yaml.load(text, Loader=yaml.SafeLoader)


def scratch_file():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    return path


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000).hex()


def cache_key(url):
    return hashlib.md5(url.encode("utf-8"), usedforsecurity=False).hexdigest()


def etag(body):
    return hashlib.sha1(body).hexdigest()
