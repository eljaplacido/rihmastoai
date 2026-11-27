"""FR-HITL1-AC-8: People in the loop in a real browser (headless Chrome over the DevTools protocol).

A business owner opens a project's People in the loop view (empty: it says what would appear and how), puts a legal
decision to compliance, gives a person outside a one-use link and copies it; that person opens the link in the same
browser and answers on the reviewer page; the view then shows the answer signed with their name. Dark at 1440 px,
then light at 390 px. After every step there is no console error, failed request or Content-Security-Policy
violation, every control has a name and nothing is wider than the screen. Skipped when Chrome is not installed.
"""

import contextlib
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

from test_ui_destinations import OVERFLOW, UNNAMED  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import hitl  # noqa: E402
from kernel.store import Factory  # noqa: E402


class LoopUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-hitl-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.project = cls.factory.new_project("Tool loans", mode="assume", maturity="demo")
        cls.other = cls.factory.new_project("Room bookings", mode="assume", maturity="demo")
        hitl.ask(cls.other, text="Room bookings' own question", family="legal", person="Aino", persona="business_owner")
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(5)
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-hitl")
        self.addCleanup(self.browser.close)
        if os.environ.get("RIHMA_UI_SHOTS"):
            self.browser.shots = Path(os.environ["RIHMA_UI_SHOTS"])

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
        if os.environ.get("RIHMA_UI_SHOTS"):
            shots = Path(os.environ["RIHMA_UI_SHOTS"])
            shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(shots / f"hitl-{b.step.replace(' ', '-').replace(',', '')}.png")

    def fits(self, named: bool = True) -> None:
        b = self.browser
        if named:
            self.assertEqual(b.eval(UNNAMED), [], f"controls without a name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def size(self, width: int, height: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride",
                         {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
        self.browser.wait(f"window.innerWidth === {width}", f"{width} px")
        time.sleep(0.3)

    def choose(self, selector: str, value: str) -> None:
        self.browser.eval(f"(() => {{ const s = document.querySelector({json.dumps(selector)});"
                          f" s.value = {json.dumps(value)}; s.dispatchEvent(new Event('change')); return true; }})()")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out')"
               " && !!document.querySelector('#grid .widget')", "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-business_owner"]', what="the business owner persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def toast(self, words: str, what: str) -> None:
        b = self.browser
        b.wait(f"(document.querySelector('#status') || {{}}).textContent.includes({json.dumps(words)})", what)
        b.click("#status .toast .icon-btn", what="Dismiss on the message")
        b.wait("!document.querySelector('#status .toast')", "the message dismissed")

    def open_loop(self) -> None:
        b, pid = self.browser, self.project.pid
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{pid}/loop"})
        b.wait("!!document.querySelector('.hl-view [data-control=\"hitl_ask\"]')", "People in the loop")

    def test_FR_HITL1_AC_8_one_asks_gives_a_link_and_the_person_outside_answers_dark_light_wide_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("empty, dark and wide")
        self.open_loop()
        b.wait("!!document.querySelector('[data-empty=\"loop\"]')", "the empty state")
        empty = b.eval("document.querySelector('[data-empty=\"loop\"]').textContent")
        self.assertIn("No question waits on anyone.", empty)
        self.assertIn("Ask Rihma how", empty)
        self.fits()
        self.step("ask a legal decision")
        b.type("#hl-text", "May we keep the loan history for two years?")
        self.choose("#hl-kind", "decision")
        self.choose("#hl-fam", "legal")
        self.assertEqual(b.eval("document.querySelector('#hl-to').value"), "compliance")
        b.type("#hl-opts", "Yes, No")
        b.click('[data-control="hitl_ask"]', what="Ask")
        self.toast("HQ-001 is put to", "the ask made")
        b.wait("!!document.querySelector('[data-ask=\"HQ-001\"][data-state=\"open\"]')", "the open ask")
        self.fits()
        self.step("give a person outside a link")
        b.click(".hl-more summary", text="Give someone a link", what="Give someone a link")
        b.type("#hl-ln", "Maria Example")
        b.type("#hl-lr", "External legal counsel")
        b.click('[data-control="hitl_link"]', what="Make the link")
        self.toast("RL-001 made for Maria Example", "the link made")
        url = b.wait("(document.querySelector('.hl-url') || {}).textContent", "the link shown once")
        self.assertIn("/r/#rv_", url)
        self.fits()
        self.step("the person outside answers")
        b.cmd("Page.navigate", {"url": url})
        b.wait("!!document.querySelector('[data-ask=\"HQ-001\"] input[type=radio]')", "the reviewer page's question")
        self.assertEqual(b.eval("location.hash"), "")                        # the token left the address bar
        text = b.eval("document.body.textContent")
        self.assertNotIn("Room bookings", text)
        self.assertNotIn("Tool loans", text)
        self.assertIn("Maria Example", text)
        self.fits(named=False)
        self.step("the person outside chooses and sends")
        b.click("[data-ask='HQ-001'] label", text="No", what="the No choice")
        b.click("[data-ask='HQ-001'] button", what="Send my answer")
        done = "(document.querySelector('[data-ask=\"HQ-001\"] .done') || {}).textContent === 'Answered: No'"
        b.wait(done, "answered")
        self.step("the reviewer page, narrow")
        self.size(390, 844)
        b.cmd("Page.navigate", {"url": url.split("#", 1)[0]})              # the session is this tab's
        b.wait(done, "the answer, kept for this tab")
        self.fits(named=False)
        self.step("light and narrow, the answer signed")
        self.size(1440, 1000)
        self.open_loop()
        self.theme("light", "Light")
        self.size(390, 844)
        b.click(".hl-more summary", text="Answered", what="Answered")
        b.wait("(document.querySelector('[data-ask=\"HQ-001\"][data-state=\"answered\"]') || {}).textContent"
               "?.includes('Maria Example as Compliance, from outside via RL-001')", "the signed answer")
        self.fits()
        self.assertEqual(hitl.get(self.project, "HQ-001")["answers"][0]["person"], "Maria Example")
        self.check()


if __name__ == "__main__":
    unittest.main()
