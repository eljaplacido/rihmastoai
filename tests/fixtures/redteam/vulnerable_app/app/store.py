"""Where the product keeps its data and its users."""

import hashlib
import pickle
import tempfile


def load_snapshot(blob):
    return pickle.loads(blob)  # seeded: RT-PY-DESER


def scratch_file():
    return tempfile.mktemp(suffix=".json")  # seeded: RT-PY-MKTEMP


def hash_password(password):
    return hashlib.md5(password.encode("utf-8")).hexdigest()  # seeded: RT-PY-WEAKHASH
