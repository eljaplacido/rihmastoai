"""The intake summary in a real browser (FR-IK1-AC-8): headless Chrome over the DevTools protocol.

A plan with three deliberate gaps (tests/fixtures/inputs/plan-full.md) is taken in by the real kernel with
a scripted panel. The cockpit serves it on 127.0.0.1, and the test drives the project's Questions view as a
person does: the summary sets "From your input", "Asked" and "Assumed" side by side at 1440 px and stacks
them at 390 px with no sideways scroll, in light and dark; its regions are named by their headings; Tab
reaches its first link and Enter opens that question; the facet checklist opens from the keyboard; and Ask
Rihma's Take me there brings a person to it from another view. After every step there is no console
error, no uncaught exception, no failed request and no Content-Security-Policy violation.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary).
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

from test_inputs import PLAN, PLAN_PANEL, scripted  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.store import Factory  # noqa: E402

COLUMNS = ("is-given-h", "is-asked-h", "is-assumed-h")


class UiInputsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-inputs-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.p = cls.factory.new_project("Visitor registration", mode="mixed", maturity="production",
                                        profile="web_service")
        intake(cls.p, str(PLAN), model=scripted(PLAN_PANEL), requested_by="Aino Example")
        cls.runner = QuietRunner()
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / f"chrome-{int(time.time() * 1000)}")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

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
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"inputs-{b.step.replace(' ', '-')}.png")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out')"
               " && !!document.querySelector('#grid .widget')", "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-product_owner"]', what="the product owner persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def open_questions(self) -> None:
        b = self.browser
        b.eval(f"location.hash = '#/p/{self.p.pid}/questions'; true")
        b.wait("!!document.querySelector('.intake-sum .is-cols')", "the intake summary")

    def layout(self) -> dict:
        return self.browser.eval("""(() => {
            const cols = [...document.querySelectorAll('.intake-sum .is-col')].map((c) => {
                const r = c.getBoundingClientRect(); return {top: Math.round(r.top), left: Math.round(r.left)}; });
            return {cols, scroll: document.documentElement.scrollWidth, width: window.innerWidth,
                    bg: getComputedStyle(document.querySelector('.intake-sum .is-col')).backgroundColor,
                    ink: getComputedStyle(document.querySelector('.intake-sum .is-quote')).color}; })()""")

    def enter(self) -> None:
        """Press Enter as a keyboard does, with the character it types (a key with no text activates nothing)."""
        for kind in ("keyDown", "keyUp"):
            self.browser.cmd("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "text": "\r",
                                                        "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000 if px > 500 else 900,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})
        self.browser.wait(f"window.innerWidth === {px}", f"a {px} px wide page")

    def theme(self, word: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def test_FR_IK1_AC_8_the_intake_summary_reads_side_by_side_in_chrome_by_keyboard_in_both_themes_and_widths(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.step("the summary at 1440")
        self.open_questions()
        names = b.eval("""(() => { const s = document.querySelector('.intake-sum');
            const name = (el) => document.getElementById(el.getAttribute('aria-labelledby')).textContent;
            return [name(s), ...[...s.querySelectorAll('.is-col')].map(name)]; })()""")
        self.assertEqual(names[0], "Intake summary")
        self.assertEqual(names[1:], ["From your input 14", "Asked 1", "Assumed 4"])   # each named, with its count
        counts = b.eval("[...document.querySelectorAll('.intake-sum .is-col')]"
                        ".map((c) => c.querySelectorAll('.is-item').length)")
        self.assertEqual(counts, [14, 1, 4])                    # 11 facts and 3 decisions; one asked; four assumed
        text = b.eval("document.querySelector('.intake-sum').textContent")
        for said in ("Read as a plan (by rule, certain), in English", "plan-full.md · lines 15–17", "decision D2",
                     "open · blocking", "Not asked, because your input already says it", "due 2026-"):
            self.assertIn(said, text)
        self.theme("Light")
        light = self.layout()
        self.assertEqual(len({c["top"] for c in light["cols"]}), 1)                     # side by side
        self.assertEqual([c["left"] for c in light["cols"]], sorted(c["left"] for c in light["cols"]))
        self.assertLessEqual(light["scroll"], light["width"])
        self.step("dark at 1440")
        self.theme("Dark")
        dark = self.layout()
        self.assertNotEqual((dark["bg"], dark["ink"]), (light["bg"], light["ink"]))
        self.assertEqual(len({c["top"] for c in dark["cols"]}), 1)
        self.step("keyboard")
        b.eval("document.querySelector('.intake-sum details > summary').focus(); true")
        self.enter()
        rows = b.wait("document.querySelector('.intake-sum details').open"
                      " && document.querySelectorAll('.is-facets tbody tr').length", "the facet checklist, opened")
        self.assertEqual(rows, 13)
        b.eval("document.getElementById('is-h').focus(); true")
        b.key("Tab", 9)
        link = b.wait("(() => { const a = document.activeElement;"
                      " return a && a.closest('.intake-sum') && a.tagName === 'A' && a.getAttribute('href'); })()",
                      "the summary's first link, by Tab")
        self.enter()
        b.wait(f"location.hash === {json.dumps(link)}", "the question the link opens")
        self.step("390 px, light and dark")
        for word in ("Light", "Dark"):          # the theme menu is in the top bar from 761 px up
            self.width(1440)
            self.theme(word)
            self.width(390)
            self.open_questions()
            narrow = b.wait("(() => { const c = [...document.querySelectorAll('.intake-sum .is-col')];"
                            " return c.length === 3 && c[0].getBoundingClientRect().width < 400"
                            " && c.map((x) => Math.round(x.getBoundingClientRect().top)); })()", "the stacked columns")
            self.assertEqual(narrow, sorted(narrow))
            self.assertEqual(len(set(narrow)), 3)                                       # one under another
            self.assertLessEqual(b.eval("document.documentElement.scrollWidth"), 390)   # no sideways scroll
        self.step("take me there")
        self.width(1440)
        b.eval(f"location.hash = '#/p/{self.p.pid}/overview'; true")
        b.wait("location.hash.endsWith('/overview') && !document.querySelector('.intake-sum')", "the overview")
        records = len(self.p.ledger().records())
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "Where is the intake summary?")
        b.click("#as-send", what="Send")
        b.click("#as-log .msg.bot button", text="Take me there", what="Take me there")
        b.wait(f"location.hash === '#/p/{self.p.pid}/questions'"
               " && !!document.activeElement && !!document.activeElement.closest('.intake-sum')",
               "the Questions view, with the focus in the intake summary")
        self.assertEqual(len(self.p.ledger().records()), records)                       # it read, and wrote nothing
        self.check()
        self.assertEqual(self.runner.started, [])


if __name__ == "__main__":
    unittest.main()
