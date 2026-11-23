"""Calls the product makes to other services."""

import json
import ssl
import urllib.request


def exchange_rates(url):
    with urllib.request.urlopen(url) as resp:  # seeded: RT-PY-TIMEOUT
        return json.load(resp)


def supplier_catalogue(url):
    context = ssl._create_unverified_context()  # seeded: RT-PY-TLS
    with urllib.request.urlopen(url, context=context, timeout=10) as resp:
        return json.load(resp)
