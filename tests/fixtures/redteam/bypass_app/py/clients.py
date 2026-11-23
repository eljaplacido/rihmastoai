"""Network calls through session and pool clients, with no timeout."""

import requests
import urllib3
from requests import Session


def session_get(url):
    s = requests.Session()
    return s.get(url).json()  # seeded: RT-PY-TIMEOUT


def session_post(url):
    return Session().post(url, json={})  # seeded: RT-PY-TIMEOUT


def pool(url):
    return urllib3.PoolManager().request("GET", url)  # seeded: RT-PY-TIMEOUT
