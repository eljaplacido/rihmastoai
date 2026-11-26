"""The cockpit as the owner starts it: ``python -m cockpit.server`` (FR-T1, FR-PPL1, FR-HEAL1).

Run that way the file is ``__main__``, while every route module imports ``cockpit.server``. Two copies would
mean two ApiError classes: a route's 404 became a 500 (and a false "the cockpit hit a bug" incident), and in
team mode a stale or missing session crashed the handler into an empty reply instead of a 401 the page can
answer with its sign-in. These tests start the real command in a child process, as the owner does, and read
its answers over HTTP; tests that build the server in-process with make_server cannot see this.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel import team as kteam  # noqa: E402
from kernel.store import Factory  # noqa: E402

AINO = "Aino Example"
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LINK = re.compile(r"Open this link once to sign in: (http://127\.0\.0\.1:\d+)/#k=(\S+)")


class CockpitAsMain(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-main-"))
        self.home = self.tmp / "home"
        self.factory = Factory(self.home)
        self.proc: subprocess.Popen | None = None

    def tearDown(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait(10)
            if self.proc.stdout:
                self.proc.stdout.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self) -> tuple[str, str]:
        """``python -m cockpit.server`` on a free port: its origin and the one-use sign-in link's bootstrap."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("RIHMA")}
        env["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "cockpit.server", "--home", str(self.home), "--port", "0", "--quiet",
             "--assistant", "map"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace")
        lines: queue.Queue = queue.Queue()

        def pump() -> None:
            for line in self.proc.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        seen = []
        while True:
            try:
                line = lines.get(timeout=60)
            except queue.Empty:
                self.fail("the cockpit printed no sign-in link within 60 s:\n" + "".join(seen))
            if line is None:
                self.fail("the cockpit stopped before printing its sign-in link:\n" + "".join(seen))
            seen.append(line)
            found = LINK.search(line)
            if found:
                return found.group(1), found.group(2)

    def send(self, origin: str, method: str, path: str, body: dict | None = None, *,
             headers: dict | None = None) -> tuple[int, dict]:
        """One request; an empty reply (the handler crashed) fails the test instead of raising."""
        sent = dict(headers or {})
        if method != "GET":
            sent["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            sent["Content-Type"] = "application/json"
        req = urllib.request.Request(origin + path, data=data, headers=sent, method=method)
        try:
            with _DIRECT.open(req, timeout=20) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"null")
        except (ConnectionError, urllib.error.URLError, OSError) as exc:
            self.fail(f"{method} {path}: the cockpit sent no answer ({type(exc).__name__}: {exc})")

    def test_FR_T1_a_route_module_s_404_stays_a_404_and_opens_no_incident(self):
        origin, bootstrap = self.start()
        status, out = self.send(origin, "POST", "/auth", {"bootstrap": bootstrap})
        self.assertEqual(status, 200, out)
        auth = {"Authorization": "Bearer " + out["token"]}
        status, out = self.send(origin, "GET", "/api/runners?project=gone-project-zz", headers=auth)
        self.assertEqual(status, 404, out)                      # runner_routes raises it: not a 500
        status, out = self.send(origin, "GET", "/api/incidents", headers=auth)
        self.assertEqual(status, 200, out)
        bugs = [i for i in out.get("incidents", []) if i.get("kind") == "server_error"
                or "hit a bug" in json.dumps(i)]
        self.assertEqual(bugs, [], "a 404 opened a false 'the cockpit hit a bug' incident")

    def test_FR_PPL1_team_mode_without_a_live_session_answers_401_not_an_empty_reply(self):
        kteam.name_solo(self.factory, AINO)
        kteam.set_mode(self.factory, "team", person=AINO, persona="it")
        origin, _ = self.start()
        for headers in ({}, {"X-Rihmasto-Session": "stale-session-from-before-the-restart",
                             "Authorization": "Bearer stale-session-from-before-the-restart"}):
            status, out = self.send(origin, "GET", "/api/meta", headers=headers)
            self.assertEqual(status, 401, out)                  # people_routes.team_identity raises it
            self.assertIn("team mode", out.get("error", ""))


if __name__ == "__main__":
    unittest.main()
