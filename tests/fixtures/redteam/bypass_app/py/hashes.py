"""Weak hashes for credentials named briefly, and deserialisers outside the usual list."""

import hashlib
import io
import pickle

import cloudpickle
import jsonpickle
from Crypto.Hash import MD5


def login(user, pw):
    return hashlib.md5(pw.encode()).hexdigest() == user.pw_hash  # seeded: RT-PY-WEAKHASH


def check(user, passcode):
    return hashlib.sha1(passcode.encode()).hexdigest()  # seeded: RT-PY-WEAKHASH


def legacy(password):
    return MD5.new(password.encode()).hexdigest()  # seeded: RT-PY-WEAKHASH


def run_job(blob):
    return cloudpickle.loads(blob)()  # seeded: RT-PY-DESER


def restore(body):
    return jsonpickle.loads(body)  # seeded: RT-PY-DESER


def private_unpickler(blob):
    return pickle._Unpickler(io.BytesIO(blob)).load()  # seeded: RT-PY-DESER
