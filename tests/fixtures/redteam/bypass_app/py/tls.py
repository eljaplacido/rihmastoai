"""TLS verification turned off by assignment, by a global patch, by a constant, or in another library."""

import os
import ssl

import aiohttp
import requests

VERIFY_SSL = False


def session_verify():
    session = requests.Session()
    session.verify = False  # seeded: RT-PY-TLS
    return session


ssl._create_default_https_context = ssl._create_unverified_context  # seeded: RT-PY-TLS


def constant_verify(url):
    return requests.get(url, verify=VERIFY_SSL, timeout=5)  # seeded: RT-PY-TLS


def aiohttp_ssl():
    return aiohttp.TCPConnector(ssl=False)  # seeded: RT-PY-TLS


os.environ["CURL_CA_BUNDLE"] = ""  # seeded: RT-PY-TLS
