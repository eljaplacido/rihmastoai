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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_drive as ui  # noqa: E402  (headless Chrome over the DevTools protocol)
from factory_fakes import FactoryTestCase, model  # noqa: E402

from embed.server import make_server  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.embeds import (  # noqa: E402
    EMBED_BASE_ENV,
    LOCAL_EMBED_BASE,
    LOCAL_EMBED_PORT,
    THANKS,
    RateLimit,
    create,
    embed_base,
    embeds,
    revoke,
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

    def website(self) -> tuple[str, dict]:
        """A website on 127.0.0.1 that serves the pages put in the returned dict (path -> HTML)."""
        pages: dict = {}

        class Site(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = pages.get(self.path.split("?")[0])
                self.send_response(200 if body is not None else 204)
                if body is not None:
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body.encode("utf-8"))))
                self.end_headers()
                if body is not None:
                    self.wfile.write(body.encode("utf-8"))

            def log_message(self, fmt, *args) -> None:
                pass

        site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=site.serve_forever, daemon=True).start()
        self.addCleanup(site.server_close)
        self.addCleanup(site.shutdown)
        return f"http://127.0.0.1:{site.server_address[1]}", pages

    def test_FR_I1_AC_3_the_widget_speaks_its_kind_and_language_keeps_a_refused_message_and_shows_no_card_number(self):
        chrome = ui.find_chrome()
        if chrome is None:
            self.skipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        origin, pages = self.website()
        fb = create(self.factory, kind="feedback", origins=[origin], person="Aino", persona="product_owner",
                    project_id=self.p.pid)
        need = create(self.factory, kind="need", origins=[origin], person="Ilkka", persona="it", label="Needs")
        base = f"http://127.0.0.1:{self.serve(rate=RateLimit(self.clock, per_minute=2))}"

        def page(e: dict, lang: str, *, kind: str = "", key: str = "") -> str:
            attrs = f' data-kind="{kind}"' if kind else ""
            return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>Shop</title></head><body>'
                    f'<p>A shop.</p><script src="{base}/e/{e["id"]}/widget.js" data-rihma-embed="{e["id"]}" '
                    f'data-key="{key or e["key"]}" data-endpoint="{base}" data-lang="{lang}"{attrs} defer></script>'
                    f'</body></html>')

        pages.update({"/en.html": page(fb, "en"), "/fi.html": page(fb, "fi"), "/need.html": page(need, "en", kind="need"),
                      "/wrong-key.html": page(fb, "en", key="rk_not_this_one")})
        b = ui.Browser(chrome, (self.tmp / "chrome").resolve())
        self.addCleanup(b.close)
        shadow = "(() => {{ const r = document.querySelector('[data-rihma-embed-host]').shadowRoot; return {}; }})()"
        look = shadow.format(
            "({btn: r.querySelector('.btn').textContent, title: r.querySelector('#rihma-title').textContent,"
            " labelled: r.querySelector('label').control === r.querySelector('textarea'),"
            " input: r.querySelector('textarea').value, focused: r.activeElement === r.querySelector('textarea'),"
            " log: Array.from(r.querySelectorAll('.log > *'), (m) => [m.className, m.textContent]),"
            " bubble: (() => { const p = r.querySelector('.person'); return p && getComputedStyle(p).backgroundColor; })(),"
            " panel: getComputedStyle(r.querySelector('.panel')).backgroundColor})")

        def visit(path: str, theme: str = "light") -> dict:
            b.step = path
            b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": theme}]})
            b.cmd("Page.navigate", {"url": origin + path})
            b.wait("!!document.querySelector('[data-rihma-embed-host]') && document.readyState === 'complete'",
                   "the widget")
            b.eval(shadow.format("(r.querySelector('.btn').click(), true)"))
            return b.eval(look)

        def say(text: str) -> dict:
            b.eval(shadow.format("(r.querySelector('textarea').focus(), true)"))
            b.cmd("Input.insertText", {"text": text})
            for kind in ("keyDown", "keyUp"):
                b.cmd("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter",
                                                 "windowsVirtualKeyCode": 13, **({"text": "\r"} if kind == "keyDown" else {})})
            b.wait(shadow.format("r.querySelector('.send').getAttribute('aria-disabled') === 'false'"
                                 " && !!r.querySelector('.log > .note')"), "the answer to " + text)
            return b.eval(look)

        en = visit("/en.html")
        self.assertEqual((en["btn"], en["title"], en["labelled"]), ("Give feedback", "Tell us what you saw", True))
        out = say("The return button does nothing.")
        self.assertEqual(out["log"][:2], [["m person", "The return button does nothing."], ["m assistant", THANKS]])
        self.assertEqual(out["log"][2][0], "m note")
        filed = [c["id"] for c in Canon(self.p).cards(state=None) if "The return button does nothing." in json.dumps(c)]
        self.assertEqual(len(filed), 1)
        self.assertNotIn(filed[0], json.dumps(out["log"]))                    # the project's own number stays inside
        fi = visit("/fi.html")
        self.assertEqual((fi["btn"], fi["title"]), ("Anna palautetta", "Kerro, mitä huomasit"))
        out = say("Palautusnappi ei toimi.")
        self.assertEqual(out["log"][1], ["m assistant", "Kiitos. Viestisi on välitetty tiimille."])  # not THANKS in English
        dark = visit("/need.html", theme="dark")
        self.assertEqual((dark["btn"], dark["title"]), ("Share a need", "Tell us what you need"))
        out = say("We type invoice numbers by hand.")
        self.assertEqual(out["log"][1], ["m assistant", THANKS])
        self.assertNotEqual(out["bubble"], out["panel"])                      # the person's bubble shows in dark mode
        visit("/en.html")                                                     # the third message this minute
        out = say("A third one.")
        self.assertEqual((out["input"], out["focused"]), ("A third one.", True))   # kept, in the box, to send again
        self.assertEqual([m[0] for m in out["log"]], ["m note err"])          # no bubble says it was sent
        self.assertIn("Wait a minute", out["log"][0][1])
        visit("/wrong-key.html")
        out = say("This is not filed.")
        self.assertEqual(out["input"], "This is not filed.")
        self.assertIn("not set up correctly", out["log"][0][1])
        visit("/en.html")                                                     # open when the chat is revoked
        revoke(self.factory, fb["id"], person="Aino", persona="product_owner")
        b.step = "revoked"
        out = say("Is anyone there?")
        self.assertEqual((out["input"], out["focused"]), ("Is anyone there?", True))
        self.assertEqual([m[0] for m in out["log"]], ["m note err"])          # no bubble says it was sent
        self.assertIn("may be closed", out["log"][0][1])
        b.eval("1")
        refused = re.compile(r"status of (403|429)\b")
        closed = re.compile(r"blocked by CORS policy|net::ERR_FAILED")         # the revoked chat answers no CORS
        unexpected = [p for p in b.problems
                      if not (refused.search(str(p[2])) or (p[0] == "revoked" and closed.search(str(p[2]))))]
        self.assertEqual(unexpected, [])                                      # only the refusals the test asked for
        self.assertEqual(b.violations(), [])


if __name__ == "__main__":
    unittest.main()
