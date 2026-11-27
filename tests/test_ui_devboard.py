"""The development board, its briefing and the trace in a real browser (FR-DEV1): headless Chrome over the DevTools
protocol, as tests/test_ui_drive.py drives it, on the neutral fixture of tests/test_devboard.py.

A developer opens the project: the Board is their first view in Build, with the briefing above the lanes; they filter
the board, open a card's details, press Got it (recorded, signed); the Trace shows the timeline, filters to agents,
expands a record, and offers the session hooks. Dark and light, 1440 and 390 pixels wide, nothing scrolls sideways
and no step leaves a console error, a failed request or a CSP violation. A business owner reads both views in plain
words, and Ask Rihma answers "what's next in development?" from the board's button.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary) or git is missing.
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

from test_devboard import DEV, world  # noqa: E402
import test_ui_agentobs as obs  # noqa: E402  (the module, so its TestCase is not collected here again)
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402
from test_ui_words import JARGON, SLOP, hits, visible  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import devsessions  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

READY = ("!!document.querySelector('.view-body') && document.querySelector('.view-body').dataset.view === '{v}'"
         " && !document.querySelector('.view-body [aria-busy=\"true\"]')")


class UiDevBoardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for the project's repository")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-dev-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.clock = FixedClock()
        self.factory = Factory(self.tmp / "home", clock=self.clock)
        self.p = world(self)
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)

    def step(self, name: str) -> None:
        if self.browser.step != "start":
            self.check()
        self.browser.step = name

    def check(self) -> None:
        b = self.browser
        b.eval("1")
        time.sleep(0.3)
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"devboard-{b.step.replace(' ', '-')}.png")

    sign_in = obs.UiAgentObsTest.sign_in    # signed in, then the persona chosen, named as DEV
    persona = obs.UiAgentObsTest.persona

    def open(self, view: str) -> None:
        b = self.browser
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('#grid')", "home")
        b.eval(f"location.hash = '#/p/{self.p.pid}/{view}'; true")
        b.wait(READY.format(v=view), view)
        time.sleep(0.3)

    def choose(self, key: str, value: str) -> None:
        """Choose ``value`` in the filter ``key``, as a person does."""
        self.browser.eval(f"(() => {{ const s = document.querySelector('[data-key=\"{key}\"]');"
                          f" s.value = {json.dumps(value)}; s.dispatchEvent(new Event('change')); return true; }})()")

    def fits(self, scheme: str, width: int) -> None:
        b = self.browser
        b.eval("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
        self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, (scheme, width))
        spills = b.eval("[...document.querySelectorAll('.dv-view .card, .dv-item, .dv-card')]"
                        ".filter((c) => c.scrollWidth > c.clientWidth + 1).map((c) => c.className)")
        self.assertEqual(spills, [], (scheme, width))

    def test_FR_DEV1_AC_6_the_board_and_the_trace_for_a_developer_dark_and_light_at_1440_and_390(self):
        b = self.browser
        self.step("the developer opens the project")
        self.sign_in("developer")
        b.eval(f"location.hash = '#/p/{self.p.pid}'; true")
        b.wait(READY.format(v="board"), "the Board, first in Build for a developer")
        b.wait("!!document.querySelector('.dv-brief .dv-next-t')", "the briefing")
        self.assertIn("Decide C-0001", b.eval("document.querySelector('.dv-next-t').textContent"))
        lanes = b.eval("Object.fromEntries([...document.querySelectorAll('[data-lane]')].map((l) => "
                       "[l.dataset.lane, [...l.querySelectorAll('[data-card]')].map((c) => c.dataset.card)]))")
        self.assertEqual((lanes["done"], lanes["blocked"], lanes["in_progress"]), (["T-001"], ["T-002"], ["T-003"]))
        self.step("filter and open a card")
        self.choose("dev:f:lane", "blocked")
        b.wait("[...document.querySelectorAll('[data-card]')].map((c) => c.dataset.card).join() === 'T-002'", "blocked")
        self.choose("dev:f:lane", "")
        b.eval("document.querySelector('[data-card=\"T-001\"] details').open = true; true")
        said = b.eval("document.querySelector('[data-card=\"T-001\"]').textContent")
        for text in ("test_R_1_AC_1_a_loan_is_recorded", "T-001 round 0: cell work", "round 0: passed",
                     "rule 1.1 holds"):
            self.assertIn(text, said)
        self.step("got it")
        b.click('[data-key="dev:seen"]', what="Got it")
        b.wait("(document.querySelector('.dv-brief .card-tools') || {}).textContent.includes('your last look')",
               "the briefing from the look")
        self.assertEqual(self.p.ledger().of_kind(devsessions.LOOKED)[-1]["event"]["payload"]["person"], DEV)
        self.step("the trace")
        self.open("trace")
        b.wait("document.querySelectorAll('.dv-item').length > 5 && !!document.querySelector('.dv-hooks')", "the trace")
        self.choose("trace:f:who", "agent")
        b.wait("[...document.querySelectorAll('.dv-item')].length > 0 && [...document.querySelectorAll('.dv-item')]"
               ".every((i) => i.dataset.who === 'agent')", "agents only")
        b.eval("document.querySelector('.dv-item details').open = true; true")
        self.assertIn('"kind"', b.eval("document.querySelector('.dv-item .dv-rec').textContent"))
        self.assertEqual(b.eval("document.querySelectorAll('.dv-file').length"), 3)
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"{scheme} {width}")
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                             "mobile": width < 500})
                for view in ("board", "trace"):
                    self.open(view)
                    self.assertEqual(b.eval("document.documentElement.dataset.theme"), scheme)
                    self.fits(scheme, width)
        self.check()

    def test_FR_DEV1_AC_6_a_business_owner_reads_plain_words_and_asks_rihma(self):
        b = self.browser
        self.step("business owner")
        self.sign_in("business_owner")
        found = []
        for view in ("board", "trace"):
            self.open(view)
            b.wait("!!document.querySelector('.dv-brief, .dv-item')", view)
            found += [(view,) + x for x in hits(visible(b, ".view-body"), SLOP + JARGON)]
        self.assertEqual(found, [], json.dumps(found[:20], indent=1))
        self.open("board")
        lane = b.eval("document.querySelector('[data-lane=\"blocked\"] .lane-h').textContent")
        self.assertIn("Waiting on a person", lane)
        self.step("ask rihma")
        b.click('[data-key="dev:ask-next"]', what="Ask Rihma on the briefing")
        said = b.wait("[...document.querySelectorAll('#as-log .a, #as-log .msg, #as-log p')].map((x) => x.textContent)"
                      ".find((t) => t.includes('Next in development'))", "Rihma's answer", timeout=30)
        self.assertIn("C-0001", said)
        self.check()


if __name__ == "__main__":
    unittest.main()
