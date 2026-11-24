"""A small JSON helper copied from another project."""

import json


def dumps(value):
    return json.dumps(value, separators=(",", ":"))
