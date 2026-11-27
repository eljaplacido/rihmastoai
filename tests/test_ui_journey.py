"""FR-JRN1 in a real browser: an Overview's next step becomes a persistent guided journey.

The person starts the guide, carries out Set up the watch through its real signed route, sees the measured result
and the following step, reloads without losing the guide, and stops it. Dark and light, wide and phone-sized:
no horizontal overflow, console error, failed request or CSP violation. Uses tests/test_ui_drive.py's Chrome
harness and is skipped when Chrome is not installed.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import modules  # noqa: E402
from kernel.store import Factory  # noqa: E402

FITS = ("(() => { const panel = document.querySelector('#as-guide');"
        " return document.documentElement.scrollWidth <= window.innerWidth"
        " && (!panel || panel.hidden || panel.scrollWidth <= panel.clientWidth + 1); })()")


class UiJourneyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-journey-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        modules.set_modules(cls.factory, person=PERSON, persona="it", preset="full")
        cls.project = cls.factory.new_project("Orders")
        cls.project.update_meta(source_kind="adopted", intent="maintain")
        cls.project.write("adopted.json", {"source": "C:/example/orders"})
        cls.project.write("baseline.json", {"verdict": "passed"})
        cls.project.write("contract.json", {"requirements": [{"id": "R-1", "statement": "Existing behaviour stays.",
                                                              "acceptance": []}]})
        cls.project.write("assessments/index.json", [{"id": "AS-1", "at": cls.factory.clock.stamp(),
                                                      "counts": {"findings": 2}}])
        cls.project.log("adopted", {"source": "C:/example/orders", "person": PERSON})
        cls.project.log("alignment_scanned", {"person": PERSON})
        cls.runner = QuietRunner()
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-journey")
        self.addCleanup(self.browser.close)

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
        self.assertTrue(b.eval(FITS), f"something scrolls sideways during '{b.step}'")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def test_FR_JRN1_AC_7_a_person_follows_a_measured_journey_in_chrome_and_resumes_after_a_reload(self):
        b = self.browser
        self.step("sign in and the Overview's next step")
        self.sign_in()
        b.eval(f"location.hash = '#/p/{self.project.pid}/overview'; true")
        b.wait("(() => { const c = document.querySelector('.jr-card');"
               " return c && c.textContent.includes('Set up the watch'); })()", "the Next step card")
        self.assertIn("7 of 11 steps done", b.eval("document.querySelector('.jr-card').textContent"))
        b.click('.jr-card [data-control="journey_guide"]', what="Guide me step by step")
        b.wait("(() => { const g = document.querySelector('#as-guide'); return g && !g.hidden"
               " && g.textContent.includes('Set up the watch'); })()", "the guided panel")

        self.step("do the step through its signed route")
        b.click('#as-guide [data-control="journey_do"]', what="Set up the watch")
        b.wait("(() => { const g = document.querySelector('#as-guide'); return g.textContent.includes('Report a change')"
               " && !!g.querySelector('.jr-result'); })()", "the measured watch and the next step")
        self.assertIn("The watch is set", b.eval("document.querySelector('#as-guide .jr-result').textContent"))
        watch = self.project.read("watch.json")
        self.assertEqual(watch["by"], {"person": PERSON, "persona": "developer"})
        self.assertTrue(watch["parts"])
        events = [r["event"] for r in self.project.ledger().records() if r["event"]["kind"] == "watch_set"]
        self.assertEqual([(e["payload"]["person"], e["payload"]["persona"]) for e in events],
                         [(PERSON, "developer")])
        self.assertEqual(self.runner.started, [])                    # setting the watch starts no job

        self.step("the active guide survives a reload")
        b.cmd("Page.reload", {"ignoreCache": True})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the reloaded page")
        b.click("#assistant-fab", what="Ask Rihma after the reload")
        b.wait("(() => { const g = document.querySelector('#as-guide'); return g && !g.hidden"
               " && g.textContent.includes('Report a change'); })()", "the same active guide after the reload")

        self.step("light on a phone")
        b.click("#as-close", what="close Ask Rihma")
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text="Light", what="Light in the theme menu")
        b.wait("document.documentElement.dataset.theme === 'light'", "the light theme")
        b.click("#assistant-fab", what="the guided panel in the light theme")
        b.wait("!document.querySelector('#as-guide').hidden", "the guide in the light theme")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 900, "deviceScaleFactor": 1,
                                                     "mobile": True})
        b.wait("window.innerWidth === 390 && !document.querySelector('#as-guide').hidden", "the guide at 390 px")
        self.check()
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1,
                                                     "mobile": False})
        b.wait("window.innerWidth === 1440", "the wide page again")

        self.step("stop and reload")
        b.click('#as-guide [data-control="journey_stop"]', what="Stop guiding")
        b.wait("document.querySelector('#as-guide').hidden", "the stopped guide")
        b.cmd("Page.reload", {"ignoreCache": True})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the page after stopping")
        b.click("#assistant-fab", what="Ask Rihma after stopping")
        b.wait("!!document.querySelector('#as-guide') && document.querySelector('#as-guide').hidden",
               "no stopped guide reopened")
        self.check()


if __name__ == "__main__":
    unittest.main()
