import contextlib
import http.client
import io
import json
import re
import shutil
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from embed.server import make_server  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.embeds import (  # noqa: E402
    EMBED_BASE_ENV,
    LOCAL_EMBED_BASE,
    LOCAL_EMBED_PORT,
    RateLimit,
    create,
    embed_base,
    embeds,
    snippet,
)
from kernel.intake import intake  # noqa: E402
from kernel.learn import FACTORY_PID  # noqa: E402
from kernel.store import Factory  # noqa: E402


class EmbedServerTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(mode="assume", title="Equipment loans")
        intake(self.p, "Our team keeps losing track of who borrowed the drills.", model=model(), requested_by="Aino")
        self.e = create(self.factory, kind="feedback", origins=["https://shop.example"], person="Aino",
                        persona="product_owner", project_id=self.p.pid)
        self.srv = make_server(self.factory, 0, rate=RateLimit(self.clock, per_minute=2))
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, method, path, body=None, origin="https://shop.example"):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if origin:
            req.add_header("Origin", origin)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers), e.read()

    def test_FR_I1_AC_3_the_embed_server_serves_the_widget_and_files_feedback_only_for_allowed_sites(self):
        eid = self.e["id"]
        status, headers, body = self.call("GET", f"/e/{eid}/widget.js", origin=None)
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers["Content-Type"])
        self.assertIn(b"attachShadow", body)
        self.assertNotIn(b"innerHTML", body)                                   # text is inserted as text
        status, headers, _ = self.call("OPTIONS", f"/e/{eid}/messages")
        self.assertEqual((status, headers.get("Access-Control-Allow-Origin")), (204, "https://shop.example"))
        status, headers, _ = self.call("OPTIONS", f"/e/{eid}/messages", origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        msg = {"key": self.e["key"], "history": [{"role": "person", "text": "The return button does nothing"}]}
        status, headers, body = self.call("POST", f"/e/{eid}/messages", msg)
        self.assertEqual(status, 200, body)
        out = json.loads(body)
        self.assertEqual(out["filed"]["kind"], "change")
        card = Canon(self.p).get_card(out["filed"]["ref"])
        self.assertEqual(card["payload"]["source"], "end_user")
        status, _, _ = self.call("POST", f"/e/{eid}/messages", msg, origin="https://evil.example")
        self.assertEqual(status, 403)
        status, _, _ = self.call("POST", f"/e/{eid}/messages", {**msg, "key": "rk_wrong"})
        self.assertEqual(status, 403)
        self.call("POST", f"/e/{eid}/messages", msg)
        status, _, _ = self.call("POST", f"/e/{eid}/messages", msg)
        self.assertEqual(status, 429)                                          # rate limited
        for path in ("/api/projects", f"/e/{eid}/../../canon", "/cockpit", f"/e/{eid}/ledger"):
            status, _, body = self.call("GET", path)
            self.assertEqual(status, 404)                                      # nothing else is served
            self.assertNotIn(b"R-1", body)

    def test_FR_I1_AC_3_the_embed_server_refuses_a_public_address_unless_behind_a_proxy(self):
        with self.assertRaises(ValueError):
            make_server(self.factory, 0, host="0.0.0.0")

    def serve(self, **kw):
        srv = make_server(self.factory, 0, **kw)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def test_FR_I1_AC_3_a_connection_that_stops_sending_is_closed_and_frees_its_thread(self):
        timeout = self.srv.RequestHandlerClass.timeout                        # the default server's
        self.assertTrue(timeout is not None and 0 < timeout <= 30, timeout)
        port = self.serve(timeout=0.5)
        head = (f"POST /e/{self.e['id']}/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nOrigin: https://shop.example\r\n"
                "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{").encode("ascii")
        for request in (head, b""):                                           # a body cut short; nothing at all
            with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
                s.sendall(request)
                start = time.monotonic()
                try:
                    data = s.recv(1024)                                       # the server hangs up
                except ConnectionResetError:
                    data = b""
                self.assertEqual(data, b"", request)
                self.assertLess(time.monotonic() - start, 5)

    def test_FR_I1_AC_3_the_widget_carries_one_cache_control_and_is_cached_for_five_minutes(self):
        with urllib.request.urlopen(f"{self.base}/e/{self.e['id']}/widget.js", timeout=10) as r:
            self.assertEqual(r.headers.get_all("Cache-Control"), ["public, max-age=300"])
        status, headers, _ = self.call("POST", f"/e/{self.e['id']}/messages",
                                       {"key": self.e["key"], "history": [{"role": "person", "text": "Broken"}]})
        self.assertEqual((status, headers.get("Cache-Control")), (200, "no-store"))

    def test_FR_I1_AC_3_a_malformed_request_gets_a_400_with_cors_never_a_reset(self):
        eid = self.e["id"]
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=10)
        self.addCleanup(conn.close)
        conn.putrequest("POST", f"/e/{eid}/messages")
        conn.putheader("Origin", "https://shop.example")
        conn.putheader("Content-Length", "2x")
        conn.endheaders()
        r = conn.getresponse()
        self.assertEqual((r.status, r.getheader("Access-Control-Allow-Origin")), (400, "https://shop.example"))
        r.read()
        for raw in (b"[1]", b'"x"', b"null", b"{not json", b"\xff\xfe"):
            req = urllib.request.Request(f"{self.base}/e/{eid}/messages", data=raw, method="POST",
                                         headers={"Origin": "https://shop.example", "Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError, msg=raw) as caught:
                urllib.request.urlopen(req, timeout=10)
            with caught.exception as e:
                self.assertEqual((e.code, e.headers.get("Access-Control-Allow-Origin")), (400, "https://shop.example"))
                self.assertIn("error", json.loads(e.read()))
        status, _, body = self.call("POST", f"/e/{eid}/messages", {"key": self.e["key"], "history": {"a": 1}})
        self.assertEqual(status, 400, body)

    def test_FR_I1_AC_3_an_internal_error_never_reaches_the_website(self):
        shutil.rmtree(self.p.dir)                                             # the project went away by hand
        msg = {"key": self.e["key"], "history": [{"role": "person", "text": "The return button does nothing"}]}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, headers, body = self.call("POST", f"/e/{self.e['id']}/messages", msg)
        self.assertEqual((status, headers.get("Access-Control-Allow-Origin")), (500, "https://shop.example"))
        self.assertEqual(json.loads(body), {"error": "the chat is not available just now"})
        for internal in (str(self.factory.home), self.factory.home.as_posix(), self.p.pid, "projects"):
            self.assertNotIn(internal.encode("utf-8"), body)
        self.assertIn(self.p.pid, err.getvalue())                             # the operator's log says what failed

    def test_FR_I1_AC_4_a_snippet_for_this_servers_address_loads_the_widget_and_files_from_here(self):
        eid = self.e["id"]
        snip = snippet(self.e, self.base + "/", key=self.e["key"])          # the address the cockpit is given
        src = re.search(r'src="([^"]+)"', snip).group(1)
        self.assertEqual(src, f"{self.base}/e/{eid}/widget.js")
        self.assertEqual(re.search(r'data-endpoint="([^"]+)"', snip).group(1), self.base)
        status, headers, body = self.call("GET", src[len(self.base):], origin=None)
        self.assertEqual(status, 200)
        self.assertIn(b"attachShadow", body)
        msg = {"key": self.e["key"], "history": [{"role": "person", "text": "The return button does nothing"}]}
        status, _, body = self.call("POST", f"/e/{eid}/messages", msg)
        self.assertEqual((status, json.loads(body)["filed"]["kind"]), (200, "change"))
        # with no address configured the snippet says so, and points at this server's default for testing
        local = snippet(self.e, None, key=self.e["key"])
        self.assertIn(f'src="{LOCAL_EMBED_BASE}/e/{eid}/widget.js"', local)
        self.assertEqual(LOCAL_EMBED_BASE, f"http://127.0.0.1:{LOCAL_EMBED_PORT}")
        for words in ("No embed server address is set", "--embed-base", EMBED_BASE_ENV):
            self.assertIn(words, local)
        for bad in ("http://shop.example", "ftp://shop.example", "https://shop.example/a b", "https://x@shop.example"):
            with self.assertRaises(ValueError, msg=bad):
                snippet(self.e, bad)
        self.assertEqual(embed_base("  https://Chat.Example:8443/rihma/ "), "https://chat.example:8443/rihma")
        self.assertIsNone(embed_base(""))

    def test_FR_I1_AC_4_reading_the_embeds_never_creates_the_factorys_own_canon(self):
        fresh = Factory(self.tmp / "fresh", clock=self.clock)
        self.assertEqual(embeds(fresh), [])
        self.assertFalse((fresh.projects_dir / FACTORY_PID).exists())
        srv = make_server(fresh, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/e/E-001/messages", method="OPTIONS",
                                     headers={"Origin": "https://shop.example"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=10)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)
        self.assertFalse((fresh.projects_dir / FACTORY_PID).exists())


if __name__ == "__main__":
    unittest.main()
