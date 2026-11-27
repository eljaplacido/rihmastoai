"""FR-CHN3 in a real browser: headless Chrome over the DevTools protocol, as tests/test_ui_drive.py drives it.

A person on an adopted project's Agent channel presses Connect a coding agent and lands on the IDE setup card with
no warning; asks Rihma twice while the panel polls and gets one answer each, the buttons only on the latest; asks
Claude Code how to sync and presses Set up the watch, which lands on that button highlighted; and pastes a long log
for Claude Code, which is put to it while the channel keeps working. Dark and light, 1440 and 390 pixels wide:
nothing scrolls sideways, every control has a name, and no step leaves a console error, a failed request or a
Content-Security-Policy violation behind.

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
from test_channel_holds import long_question  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import agent_channel as ch  # noqa: E402
from kernel import channel_consult  # noqa: E402
from kernel.store import Factory  # noqa: E402

TOASTS = ("(() => { window.__toasts = []; const s = document.querySelector('#status');"
          " new MutationObserver(() => { if (s.textContent) window.__toasts.push(s.textContent); })"
          ".observe(s, { childList: true, subtree: true }); return true; })()")
RIHMA_COUNT = "document.querySelectorAll('#ch-log .ch-rihma.ch-msg').length"


class ChannelHoldsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-holds-")).resolve()
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
        self.p.write("adopted.json", {"intent": "maintain", "source": "a local folder"})
        self.p.write("baseline.json", {"verdict": "not measured", "reason": "not measured: no test ran",
                                       "command": "python -m unittest discover -v"})

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
            b.screenshot(self.shots / f"holds-{b.step.replace(' ', '-')}.png")

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

    def send(self, text: str, answers: int) -> str:
        b = self.browser
        b.eval(f"(() => {{ const t = document.querySelector('#ch-text'); t.value = {json.dumps(text)};"
               " t.dispatchEvent(new Event('input', { bubbles: true })); return true; })()")
        b.click('[data-key="ch-send"]', what="Send")
        return b.wait(f"{RIHMA_COUNT} >= {answers} && [...document.querySelectorAll('#ch-log .ch-rihma.ch-msg')]"
                      ".pop().textContent", "Rihma's answer")

    def scheme(self, scheme: str, width: int) -> None:
        b = self.browser
        b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                     "mobile": width < 500})

    def test_FR_CHN3_AC_11_the_channel_holds_up_in_a_browser(self):
        b = self.browser
        pid = self.p.pid
        view = f"#/p/{pid}/agents"
        self.step("connect lands")
        self.sign_in()
        b.eval(TOASTS)
        self.go(view, "!!document.querySelector('[data-key=\"ch-connect\"]')", "Connect a coding agent")
        b.click('[data-key="ch-connect"]', what="Connect a coding agent")
        b.wait("location.hash.endsWith('/aitools/ide_setup')", "the AI tools view")
        b.wait("!!document.querySelector('[data-id=\"ide_setup\"].focused')", "the IDE setup card, focused")
        self.assertFalse(any("is not shown" in t for t in b.eval("window.__toasts")), b.eval("window.__toasts"))

        self.step("one answer each")
        self.go(view, "!!document.querySelector('#ch-text')", "the channel")
        self.send("@analyst what should I do next?", 1)
        self.send("@analyst what are the requirements?", 2)
        time.sleep(3.5)                                             # the panel polls, and answers nothing twice
        self.assertEqual(b.eval(RIHMA_COUNT), 2)
        rihma = [m for m in ch.messages(self.p) if m["author"]["kind"] == "rihma"]
        self.assertEqual(len(rihma), 2)
        self.assertEqual(b.eval("document.querySelectorAll('#ch-log .ch-acts').length"), 1)
        self.assertIn(rihma[-1]["id"], b.eval("document.querySelector('#ch-log .ch-acts').closest('.ch-msg')"
                                              ".dataset.id"))

        self.step("a button lands on its control")
        said = self.send("Ask Claude Code: how should this project sync with Rihmasto, and what should I monitor?", 4)
        self.assertIn("I put your question", said)
        self.assertLess(len(said), 2200)
        self.assertIn("Baseline: not measured (tried python -m unittest discover -v)", said)
        b.wait("!!document.querySelector('#ch-log [data-lands=\"watch_setup\"]')", "Set up the watch")
        b.click('#ch-log [data-lands="watch_setup"]', what="Set up the watch")
        b.wait("location.hash.endsWith('/overview')", "the overview")
        b.wait("(() => { const a = document.activeElement; return !!a && !!a.closest('[data-control=\"watch_setup\"]')"
               " || !!document.querySelector('[data-control=\"watch_setup\"].flash'); })()",
               "Set up the watch highlighted")

        self.step("a long question")
        self.go(view, "!!document.querySelector('#ch-text')", "the channel")
        b.wait(f"{RIHMA_COUNT} >= 4", "the earlier answers")
        said = self.send(long_question(), 6)
        self.assertIn("I put your question", said)
        asked = channel_consult.waiting(self.p)
        self.assertEqual(len(asked), 2)
        self.assertLessEqual(len(asked[-1]["text"]), ch.MAX_TEXT)
        time.sleep(3.5)
        self.assertEqual(b.eval(RIHMA_COUNT), 6)

        for scheme, width in SCHEMES:
            self.step(f"channel {scheme} {width}")
            self.scheme(scheme, width)
            self.go(view, "document.querySelectorAll('#ch-log .ch-acts').length === 1", "the channel")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", f"the {scheme} theme")
            self.check()


if __name__ == "__main__":
    unittest.main()
