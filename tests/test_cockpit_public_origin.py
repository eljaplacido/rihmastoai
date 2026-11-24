"""FR-T1-AC-2 with a trusted HTTPS front: the cockpit stays on loopback, and one declared https origin
(tailscale serve, a company reverse proxy) is accepted beside the loopback one; any other Host or
Origin is still refused, and a plain-http front is refused at start."""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from cockpit.server import main, make_server, public_origin_of  # noqa: E402

FRONT = "https://cockpit.example-tailnet.ts.net"


class PublicOriginTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.server, self.bootstrap = make_server(self.factory, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        super().tearDown()

    def send(self, method: str, path: str, *, host: str, origin: str | None = None, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        headers = {"Host": host}
        if origin:
            headers["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        out = (res.status, res.read())
        conn.close()
        return out

    def test_FR_T1_AC_2_without_a_declared_front_another_host_is_refused(self):
        host = FRONT.removeprefix("https://")
        self.assertEqual(self.send("GET", "/", host=host)[0], 403)
        self.assertEqual(self.send("POST", "/auth", host=host, origin=FRONT, body={"bootstrap": self.bootstrap})[0], 403)

    def test_FR_T1_AC_2_a_declared_https_front_reaches_the_loopback_cockpit_and_nothing_else_does(self):
        self.server.public_origin = public_origin_of(FRONT + "/")
        host = FRONT.removeprefix("https://")
        self.assertEqual(self.send("GET", "/", host=host)[0], 200)
        self.assertEqual(self.send("GET", "/", host="elsewhere.example")[0], 403)
        self.assertEqual(self.send("POST", "/auth", host=host, origin="https://elsewhere.example",
                                   body={"bootstrap": self.bootstrap})[0], 403)
        status, payload = self.send("POST", "/auth", host=host, origin=FRONT, body={"bootstrap": self.bootstrap})
        self.assertEqual(status, 200, payload)
        self.assertTrue(json.loads(payload)["token"])
        # the loopback origin still works beside the front
        loop = f"127.0.0.1:{self.server.port}"
        self.assertEqual(self.send("GET", "/", host=loop)[0], 200)

    def test_FR_T1_AC_2_a_front_is_https_and_an_origin_only(self):
        self.assertEqual(public_origin_of("https://Cockpit.Example.ts.net/"), "https://cockpit.example.ts.net")
        for bad in ("http://cockpit.example.ts.net", "https://", "https://x.example/path", "https://x.example/?q=1",
                    "https://user:pw@x.example", "ftp://x.example"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                public_origin_of(bad)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), "--port", "0", "--public-origin", "http://plain.example"])
        self.assertEqual(code, 2)
        self.assertIn("https://", err.getvalue())


if __name__ == "__main__":
    unittest.main()
