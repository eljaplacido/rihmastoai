"""Calls the product makes to other services."""

import json
import ssl
import urllib.request


def exchange_rates(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.load(resp)


def supplier_catalogue(url, ca_bundle):
    context = ssl.create_default_context(cafile=ca_bundle)
    with urllib.request.urlopen(url, context=context, timeout=10) as resp:
        return json.load(resp)
