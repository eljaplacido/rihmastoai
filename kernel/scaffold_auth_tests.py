"""The road's checks of a product's sign-in (kernel/scaffold_auth.py): `tests/test_road_sign_in.py` in every
product that has one. They run with the product's whole suite at every gate, and no builder cell may change
them (kernel/lanes.py PROTECTED)."""

from __future__ import annotations

TEST_SIGN_IN_PY = r'''"""The paved road's sign-in. The road owns this file: no builder cell may edit or remove it, and
the factory's gate refuses a change that touches it. It runs with the product's whole suite at every gate."""

import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

import app.routes  # noqa: F401
from app import server, sign_in
from app.server import ROUTES, respond

DEFAULT_ITERATIONS = sign_in.ITERATIONS
PASSWORD = "correct horse battery"
PAGE = {"Accept": "text/html"}
SETTINGS = ("FIRST_ADMIN_USER", "FIRST_ADMIN_PASSWORD", "SIGN_IN_MODE", "SIGN_IN_PROXY_SECRET", "TRAFFIC_LOG",
            "PUBLIC_URL", "SIGN_IN_PROXY_ADMINS")


def cookie(headers, name):
    """The value a response sets for cookie ``name``, and that Set-Cookie line."""
    for key, value in headers:
        if key == "Set-Cookie" and value.startswith(name + "="):
            return value.split(";")[0].split("=", 1)[1], value
    return None, None


def location(headers):
    return dict(headers).get("Location")


class SignInTest(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("DATA_DIR",) + SETTINGS}
        self.data = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.data.name
        for name in SETTINGS:
            os.environ.pop(name, None)
        self.clock = (sign_in.ITERATIONS, sign_in.now)
        sign_in.ITERATIONS = 1000  # a fast hash for the tests; the default is checked below
        sign_in._SESSIONS.clear()

    def tearDown(self):
        sign_in.ITERATIONS, sign_in.now = self.clock
        sign_in._SESSIONS.clear()
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.data.cleanup()

    def sign_in_as(self, name, password, extra=None):
        status, body, _, headers = respond("GET", "/sign-in")
        form, _ = cookie(headers, sign_in.FORM_COOKIE)
        sent = {"Cookie": sign_in.FORM_COOKIE + "=" + form, **(extra or {})}
        return respond("POST", "/sign-in", {"username": name, "password": password, "csrf": body["csrf"]}, sent)

    def session(self, headers):
        token, _ = cookie(headers, sign_in.COOKIE)
        return {"Cookie": sign_in.COOKIE + "=" + token}

    def test_ROAD_SIGNIN_every_route_but_health_static_and_the_sign_in_page_needs_a_signed_in_person(self):
        for method, regex, _ in list(ROUTES):
            path = re.sub(r"\(\?P<\w+>\[\^/\]\+\)", "x", regex.pattern)[1:-1]
            if (method, path) in sign_in.OPEN or path.startswith("/static/"):
                continue
            with self.subTest(method=method, path=path):
                self.assertEqual(respond(method, path)[0], 401)
        self.assertEqual(respond("GET", "/no-such-page")[0], 401)
        status, _, _, headers = respond("GET", "/account", None, PAGE)
        self.assertEqual((status, location(headers)), (303, "/sign-in?next=/account"))
        self.assertEqual(respond("GET", "/health")[0], 200)
        self.assertEqual(respond("GET", "/static/product.css")[0], 200)

    def test_ROAD_SIGNIN_passwords_are_kept_as_salted_pbkdf2_sha256_hashes_only(self):
        self.assertGreaterEqual(DEFAULT_ITERATIONS, 600000)
        sign_in.add_account("ada", PASSWORD)
        sign_in.add_account("bob", PASSWORD)
        with open(os.path.join(self.data.name, "accounts.json"), encoding="utf-8") as fh:
            stored = fh.read()
        self.assertNotIn(PASSWORD, stored)
        hashes = [a["hash"] for a in json.loads(stored).values()]
        self.assertTrue(all(h.startswith("pbkdf2_sha256$") for h in hashes))
        self.assertNotEqual(hashes[0], hashes[1])
        self.assertTrue(sign_in.check_password(PASSWORD, hashes[0]))
        self.assertFalse(sign_in.check_password(PASSWORD + "x", hashes[0]))
        with self.assertRaises(ValueError):
            sign_in.add_account("cyd", "short")

    def test_ROAD_SIGNIN_the_session_cookie_is_httponly_samesite_lax_and_secure_over_tls(self):
        sign_in.add_account("ada", PASSWORD)
        status, body, _, headers = self.sign_in_as("ada", PASSWORD)
        self.assertEqual(status, 200)
        _, line = cookie(headers, sign_in.COOKIE)
        self.assertIn("HttpOnly", line)
        self.assertIn("SameSite=Lax", line)
        self.assertNotIn("Secure", line)
        _, _, _, headers = self.sign_in_as("ada", PASSWORD, {"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", cookie(headers, sign_in.COOKIE)[1])

    def test_ROAD_SIGNIN_a_session_token_sent_with_the_sign_in_is_never_kept(self):
        sign_in.add_account("ada", PASSWORD)
        sign_in.add_account("mallory", PASSWORD)
        _, _, _, theirs = self.sign_in_as("mallory", PASSWORD)
        mallory, _ = cookie(theirs, sign_in.COOKIE)
        for planted in ("planted-by-someone-else", mallory):     # a made-up token, and someone's live session
            with self.subTest(planted=planted[:8]):
                _, form, _, headers = respond("GET", "/sign-in")
                token, _ = cookie(headers, sign_in.FORM_COOKIE)
                sent = {"Cookie": "%s=%s; %s=%s" % (sign_in.COOKIE, planted, sign_in.FORM_COOKIE, token)}
                status, _, _, answer = respond("POST", "/sign-in", {"username": "ada", "password": PASSWORD,
                                                                    "csrf": form["csrf"]}, sent)
                issued, _ = cookie(answer, sign_in.COOKIE)
                self.assertEqual(status, 200)
                self.assertTrue(issued and issued != planted)          # a fresh token, never the one sent
                fixed = {"Cookie": sign_in.COOKIE + "=" + planted}
                seen = respond("GET", "/account", None, fixed)
                self.assertNotEqual((seen[0], seen[1].get("name")), (200, "ada"))   # it signs nobody in as ada
                ada = respond("GET", "/account", None, {"Cookie": sign_in.COOKIE + "=" + issued})
                self.assertEqual((ada[0], ada[1]["name"]), (200, "ada"))

    def test_ROAD_SIGNIN_every_state_changing_request_carries_the_csrf_token(self):
        sign_in.add_account("ada", PASSWORD)
        _, body, _, headers = self.sign_in_as("ada", PASSWORD)
        signed = self.session(headers)
        self.assertEqual(respond("POST", "/sign-out", None, signed)[0], 403)
        self.assertEqual(respond("POST", "/sign-out", None, {**signed, "X-CSRF-Token": "wrong"})[0], 403)
        self.assertEqual(respond("POST", "/sign-out", None, {**signed, "X-CSRF-Token": body["csrf"]})[0], 303)
        _, form, _, form_headers = respond("GET", "/sign-in")
        token, _ = cookie(form_headers, sign_in.FORM_COOKIE)
        no_form = respond("POST", "/sign-in", {"username": "ada", "password": PASSWORD, "csrf": "x"},
                          {"Cookie": sign_in.FORM_COOKIE + "=" + token})
        self.assertEqual(no_form[0], 403)
        no_cookie = respond("POST", "/sign-in", {"username": "ada", "password": PASSWORD, "csrf": form["csrf"]})
        self.assertEqual(no_cookie[0], 403)

    def test_ROAD_SIGNIN_repeated_failures_lock_the_account_and_say_nothing_more(self):
        sign_in.add_account("ada", PASSWORD)
        unknown = self.sign_in_as("nobody", PASSWORD)
        for _ in range(sign_in.MAX_FAILURES):
            wrong = self.sign_in_as("ada", "not the password")
        self.assertEqual((wrong[0], wrong[1]["error"]), (unknown[0], unknown[1]["error"]))
        locked = self.sign_in_as("ada", PASSWORD)
        self.assertEqual((locked[0], locked[1]["error"]), (401, sign_in.FAILED))
        later = sign_in.now() + sign_in.LOCK_MINUTES * 60 + 1
        sign_in.now = lambda: later
        self.assertEqual(self.sign_in_as("ada", PASSWORD)[0], 200)

    def test_ROAD_SIGNIN_the_first_admin_comes_from_the_environment_once(self):
        os.environ.update(FIRST_ADMIN_USER="admin", FIRST_ADMIN_PASSWORD=PASSWORD)
        self.assertEqual(sign_in.first_admin_from_env(), "admin")
        self.assertNotIn("FIRST_ADMIN_PASSWORD", os.environ)
        self.assertEqual(sign_in.accounts()["admin"]["role"], "admin")
        os.environ.update(FIRST_ADMIN_USER="other", FIRST_ADMIN_PASSWORD=PASSWORD)
        self.assertIsNone(sign_in.first_admin_from_env())
        self.assertEqual(sorted(sign_in.accounts()), ["admin"])
        self.assertNotIn("FIRST_ADMIN_PASSWORD", os.environ)

    def test_ROAD_SIGNIN_the_first_admin_sets_a_new_password_before_anything_else(self):
        os.environ.update(FIRST_ADMIN_USER="admin", FIRST_ADMIN_PASSWORD=PASSWORD)
        sign_in.first_admin_from_env()
        _, body, _, headers = self.sign_in_as("admin", PASSWORD)
        signed = self.session(headers)
        status, _, _, page = respond("GET", "/", None, {**signed, **PAGE})
        self.assertEqual((status, location(page)), (303, "/account"))
        change = {"current": PASSWORD, "new": "a much longer new password", "csrf": body["csrf"]}
        self.assertEqual(respond("POST", "/account/password", change, signed)[0], 200)
        self.assertFalse(sign_in.accounts()["admin"]["must_change"])
        self.assertEqual(respond("GET", "/account", None, signed)[0], 200)

    def test_ROAD_SIGNIN_the_proxy_mode_trusts_a_user_only_with_the_proxys_secret(self):
        os.environ.update(SIGN_IN_MODE="proxy")
        user = {"X-Forwarded-Email": "ada@example.org"}
        self.assertEqual(respond("GET", "/account", None, {**user, "X-Proxy-Secret": "anything"})[0], 401)
        os.environ["SIGN_IN_PROXY_SECRET"] = "the-proxys-secret"
        self.assertEqual(respond("GET", "/account", None, user)[0], 401)
        self.assertEqual(respond("GET", "/account", None, {**user, "X-Proxy-Secret": "wrong"})[0], 401)
        both = {"X-Forwarded-Email": "eve@example.org, ada@example.org", "X-Proxy-Secret": "the-proxys-secret"}
        self.assertEqual(respond("GET", "/account", None, both)[0], 401)
        status, body, _, _ = respond("GET", "/account", None, {**user, "X-Proxy-Secret": "the-proxys-secret"})
        self.assertEqual((status, body["name"]), (200, "ada@example.org"))

    def test_ROAD_SIGNIN_the_network_runs_the_guard_and_keeps_passwords_out_of_the_traffic_log(self):
        sign_in.add_account("ada", PASSWORD)
        log = os.path.join(self.data.name, "traffic.jsonl")
        os.environ["TRAFFIC_LOG"] = log
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            def call(method, path, body=None):
                conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
                conn.request(method, path, body=body)
                answer = conn.getresponse()
                answer.read()
                conn.close()
                return answer.status
            self.assertEqual(call("GET", "/account"), 401)
            self.assertEqual(call("GET", "/health"), 200)
            call("POST", "/sign-in", "username=ada&password=" + PASSWORD.replace(" ", "+"))
        finally:
            httpd.shutdown()
            httpd.server_close()
        recorded = ""
        for _ in range(50):  # the server writes its log line after it answered
            with open(log, encoding="utf-8") as fh:
                recorded = fh.read()
            if "/account" in recorded:
                break
            time.sleep(0.1)
        self.assertIn("/account", recorded)
        self.assertNotIn("correct", recorded)

    def test_ROAD_SIGNIN_sign_out_ends_the_session_and_no_sign_in_sends_a_person_elsewhere(self):
        sign_in.add_account("ada", PASSWORD)
        _, body, _, headers = self.sign_in_as("ada", PASSWORD)
        signed = self.session(headers)
        self.assertEqual(respond("GET", "/account", None, signed)[0], 200)
        respond("POST", "/sign-out", None, {**signed, "X-CSRF-Token": body["csrf"]})
        self.assertEqual(respond("GET", "/account", None, signed)[0], 401)
        for target in ("//evil.example", "/\t/evil.example", "https://evil.example", "/ok/page"):
            _, form, _, headers = respond("GET", "/sign-in")
            token, _ = cookie(headers, sign_in.FORM_COOKIE)
            sent = "username=ada&password=" + PASSWORD.replace(" ", "+") + "&csrf=" + form["csrf"] + "&next=" + target
            status, _, _, answer = respond("POST", "/sign-in", sent, {"Cookie": sign_in.FORM_COOKIE + "=" + token})
            self.assertEqual((status, location(answer)), (303, target if target == "/ok/page" else "/"))


if __name__ == "__main__":
    unittest.main()
'''
