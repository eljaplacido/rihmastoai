"""Set-up done right: verification on, timeouts set, debug behind a flag, loopback by default."""

import hashlib
import os

import requests
from flask import Flask

app = Flask(__name__)
VERIFY_SSL = True
CA_BUNDLE = "/etc/ssl/certs/team-ca.pem"


def fetch(url):
    session = requests.Session()
    session.verify = CA_BUNDLE
    return session.get(url, timeout=5, verify=VERIFY_SSL)


def cache_key(url):
    return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()


def main(args):
    if args.debug:
        app.debug = True
    app.run("127.0.0.1", 5000)


os.environ.setdefault("APP_MODE", "production")
