"""FR-CHN2 in a real browser: headless Chrome over the DevTools protocol, as tests/test_ui_drive.py drives it.

A person opens an adopted project's Agent channel, reads what it is for and what to expect, sees that no coding
agent is connected and where to connect one, presses Ask a coding agent and asks it how to sync with Rihmasto and
what to monitor. Rihma's answer says it put the question to Claude Code, how to connect one, and what the records
say now, with the next steps as buttons; a button opens its view. A coding agent then connects and the head names
it. Dark and light, 1440 and 390 pixels wide: nothing scrolls sideways, every control has a name, and no step leaves
a console error, a failed request or a Content-Security-Policy violation behind.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). No model and no coding agent
runs. ``RIHMA_UI_SHOTS=<folder>`` also saves a screenshot per step.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_agent_bridge import planned  # noqa: E402
from test_agents_ui import NAMELESS, PERSON, SCHEMES  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import agent_channel as ch  # noqa: E402
from kernel import channel_consult  # noqa: E402
from kernel.agent_writes import progress  # noqa: E402
from kernel.store import Factory  # noqa: E402

LAST_RIHMA = ("(() => { const r = [...document.querySelectorAll('#ch-log .ch-rihma.ch-msg')];"
              " return r.length ? r[r.length - 1].textContent : ''; })()")


class ChannelConsultUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-consult-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.p = planned(self.factory, "Equipment loans")
        self.p.update_meta(source_kind="adopted", intent="maintain")

    def step(self, name: str) -> None:
        if self.browser.step != "start":
            self.check()
        self.browser.step = name

    def check(self) -> None:
        b = self.browser
        b.eval("1")
        time.sleep(0.3)
        b.eval("1")
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        self.assertEqual(b.eval(NAMELESS), [], f"controls with no accessible name during '{b.step}'")
        self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, f"sideways in '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"consult-{b.step.replace(' ', '-')}.png")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")

    def go(self, hash_: str, ready: str, what: str):
        b = self.browser
        b.eval(f"location.hash = {json.dumps(hash_)}; true")
        return b.wait(ready, what)

    def scheme(self, scheme: str, width: int) -> None:
        b = self.browser
        b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                     "mobile": width < 500})

    def test_FR_CHN2_AC_7_a_person_reads_what_the_channel_is_for_asks_claude_code_and_follows_a_next_step(self):
        b = self.browser
        pid = self.p.pid
        view = f"#/p/{pid}/agents"
        self.step("the head")
        self.sign_in()
        head = self.go(view, "(document.querySelector('.ch-head') || {}).textContent", "the channel's head")
        self.assertIn("Claude Code, Cursor, Codex, any MCP client", head)
        self.assertEqual(b.eval("document.querySelectorAll('.ch-expect li').length"), 3)
        who = b.wait("(document.querySelector('#ch-who') || {}).textContent", "who is connected")
        self.assertIn("No coding agent has posted here yet", who)
        self.assertIn(f"#/p/{pid}/aitools/ide_setup", b.eval("document.querySelector('[data-key=\"ch-connect\"]').href"))
        self.step("ask claude code")
        b.click('[data-key="ch-ask-agent"]', what="Ask a coding agent")
        self.assertEqual(b.eval("document.querySelector('#ch-text').value"), "Ask Claude Code: ")
        b.cmd("Input.insertText", {"text": "how should this project sync with Rihmasto, and what should I monitor?"})
        b.click('[data-key="ch-send"]', what="Send")
        said = b.wait(f"(() => {{ const t = {LAST_RIHMA}; return t.includes('I put your question') && t; }})()",
                      "Rihma's answer")
        for part in ("No coding agent is connected", f"rihmasto ide {pid}", "Meanwhile, from the records:",
                     "Upstream changed: review"):
            self.assertIn(part, said)
        for never in ("can't consult", "cannot consult"):
            self.assertNotIn(never, said)
        asked = channel_consult.waiting(self.p)
        self.assertEqual([m["to"] for m in asked], [["claude-code"]])
        self.assertTrue(b.eval(f"document.querySelector('[data-id=\"{asked[0]['id']}\"]').textContent"
                               ".includes('@claude-code')"))
        acts = b.eval("[...document.querySelectorAll('#ch-log .ch-acts')].pop().textContent")
        self.assertIn("Connect a coding agent", acts)
        self.assertIn("Set up the watch", acts)
        self.step("an agent connects")
        progress(self.p, ch.agent("claude-code", "Tessa", "developer", "claude-code 2.1"), "Read the question")
        b.wait("document.querySelector('#ch-who').textContent.includes('claude-code for Tessa')", "the connected agent")
        b.wait("document.querySelector('#ch-who').textContent.includes('1 question(s) put to agents')",
               "the waiting count")
        self.step("follow a next step")
        answer = [m for m in ch.messages(self.p) if m["author"]["kind"] == "rihma" and m["kind"] == "answer"][-1]
        b.click(f'[data-key="ch-act:{answer["id"]}:1"]', what="the answer's second next step")
        b.wait("location.hash.includes('/overview')", "the overview opened")
        for scheme, width in SCHEMES:
            self.step(f"channel {scheme} {width}")
            self.scheme(scheme, width)
            self.go(view, "document.querySelectorAll('#ch-log .ch-acts').length >= 1", "the channel")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", f"the {scheme} theme")
            b.wait("document.querySelector('#ch-who').textContent.includes('claude-code for Tessa')", "the head")
            self.check()


if __name__ == "__main__":
    unittest.main()
