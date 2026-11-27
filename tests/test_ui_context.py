"""The Context view and the Data and context page in a real browser (FR-CTX1-AC-8): headless Chrome over the DevTools
protocol, as tests/test_ui_drive.py drives the cockpit.

A person opens a planned project's Context view: what Rihmasto knows (sources, records, freshness, what is kept on
disk), each agent's pack with its size against its budget, a pack opened part by part, and the compression
findings. As a developer the holdout author's content is withheld; as compliance it is shown. Then the Data and
context page: the Context health per role, the stores, every ledger intact, and a clean-up proposed with the
person's name. Each is checked dark and light at 1440 and 390 pixels: nothing scrolls sideways, every control has a
name, and no console error, failed request or Content-Security-Policy violation happens at any step.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). ``RIHMA_UI_SHOTS=<folder>``
saves a screenshot per step.
"""

import contextlib
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import model  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

PERSON = "Aino Virtanen"
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
FITS = "document.documentElement.scrollWidth <= window.innerWidth"
# Every control the Context view and the Data page draw has a name (the project page's own header is not theirs).
NAMED = ("(() => { const bad = []; const scope = document.querySelector('.cx-view') || document.querySelector('#main');"
         " scope.querySelectorAll('button, select, input, a[href], summary').forEach((el) => {"
         " if (!el.getClientRects().length) return;"
         " const name = el.getAttribute('aria-label') || el.textContent.trim() || el.title;"
         " if (!name) bad.push(el.outerHTML.slice(0, 90)); }); return bad; })()")
PACKS = "document.querySelectorAll('.cx-packs .cx-pack').length"
DETAIL = "(() => { const d = document.querySelector('#cx-detail .cx-detail'); return d && d.dataset.pack; })()"


class ContextUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-context-ui-")).resolve()
        cls.lanes_env = os.environ.get("GF_LANES")
        os.environ["GF_LANES"] = str(cls.tmp / "lanes")
        cls.factory = Factory(cls.tmp / "home", clock=FixedClock())
        cls.p = cls.factory.new_project("Equipment loans", mode="assume", maturity="demo")
        intake(cls.p, IDEA, model=model(), requested_by="Aino")
        make_spec(cls.p, model=model())
        compile_project(cls.p)
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        if cls.lanes_env is None:
            os.environ.pop("GF_LANES", None)
        else:
            os.environ["GF_LANES"] = cls.lanes_env
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-context")
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
            b.screenshot(self.shots / f"context-{b.step.replace(' ', '-')}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 900 if px > 500 else 800,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})
        time.sleep(0.3)

    def theme(self, mode: str) -> None:
        b = self.browser
        if b.eval(f"document.documentElement.dataset.theme === '{mode}'"):
            return
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=mode.capitalize(), what=f"{mode} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === '{mode}'", f"the {mode} theme")

    def persona(self, persona: str) -> None:
        b = self.browser
        b.click("#person-chip", what="the person chip")
        b.click(f'label[for="pp-{persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done")

    def readable(self, where: str) -> None:
        b = self.browser
        self.assertTrue(b.eval(FITS), f"{where} scrolls sideways")
        self.assertEqual(b.eval(NAMED), [], f"{where}: a control without a name")

    def context_view(self, where: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.p.pid}/context"})
        b.wait(f"{PACKS} === 10", "every agent's pack")
        b.wait("!!document.querySelector('[data-control=\"context_audit\"] .cx-list, [data-control=\"context_audit\"] p:not(.muted)')"
               " || document.querySelector('[data-control=\"context_audit\"]').textContent.includes('Nothing found')",
               "the compression findings")
        self.assertEqual(b.eval("document.querySelector('.cx-view h2').textContent"), "Context")
        b.click('[data-key="cx-open:verifier"]', what="Open the verifier's pack")
        self.assertEqual(b.wait(DETAIL, "the verifier's pack"), "verifier")
        b.eval("document.querySelectorAll('#cx-detail details')[1].open = true")
        self.assertIn("You review a change", b.eval("document.querySelectorAll('#cx-detail .cx-pre')[1].textContent"))
        self.readable(f"the Context view ({where})")

    def data_page(self, where: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/data"})
        b.wait("!!document.querySelector('[data-control=\"context_health\"] table') && "
               "!!document.querySelector('section[aria-labelledby=data-ledgers-h] table')", "the Data and context page")
        self.assertEqual(b.eval("document.querySelector('#view-title').textContent"), "Data and context")
        self.assertIn("intact", b.eval("document.querySelector('section[aria-labelledby=data-ledgers-h]').textContent"))
        self.readable(f"the Data and context page ({where})")

    def test_FR_CTX1_AC_8_the_context_view_and_the_data_page_in_both_themes_at_both_widths(self):
        b = self.browser
        self.step("sign in")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in cockpit")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done")
        self.theme("dark")

        self.step("context dark 1440")
        self.context_view("dark 1440")
        b.click('[data-key="cx-open:holdout_author"]', what="Open the holdout author's pack")
        b.wait(f"{DETAIL} === 'holdout_author'", "the holdout author's pack")
        self.assertIn("not shown to your persona", b.eval("document.querySelector('#cx-detail').textContent"))

        self.step("as compliance")
        self.persona("compliance")
        self.context_view("compliance")
        b.click('[data-key="cx-open:holdout_author"]', what="Open the holdout author's pack")
        b.wait(f"{DETAIL} === 'holdout_author'", "the holdout author's pack")
        self.assertFalse(b.eval("document.querySelector('#cx-detail').textContent.includes('not shown to your persona')"))

        self.step("data dark 1440")
        b.click('a.nav-i[href="#/data"]', what="Data and context in the sidebar")
        self.data_page("dark 1440")

        for mode in ("light", "dark"):
            for px in (390, 1440):
                self.step(f"{mode} {px}")
                self.width(1440)
                self.theme(mode)
                self.width(px)
                self.context_view(f"{mode} {px}")
                self.data_page(f"{mode} {px}")

        self.step("propose a clean-up")
        self.persona("it")
        b.click('[data-control="data_cleanup"]', what="Propose a clean-up")
        b.wait("(() => { const t = document.querySelector('#status .toast'); return t && t.textContent.includes('CU-0001'); })()",
               "the proposal's toast")
        b.wait("document.querySelector('section[aria-labelledby=data-clean-h]').textContent.includes('CU-0001')", "the proposal listed")
        b.click('[data-control="data_apply"]', what="Apply CU-0001")
        b.wait("(() => { const t = document.querySelector('#status .toast'); return t && t.textContent.includes('removed'); })()",
               "the applied toast")
        self.check()


if __name__ == "__main__":
    unittest.main()
