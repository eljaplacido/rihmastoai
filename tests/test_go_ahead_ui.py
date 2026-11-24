"""The owner's decisions of 2026-11-24 in a real browser (FR-CHG1-AC-13): headless Chrome over the DevTools
protocol, as tests/test_ui_drive.py drives it.

A person ticks "Build without waiting for me" in New project and the project is made so; on a demo project
whose spec waits for a look, What's next shows "Look at the spec before building" with Go and Skip, and Go
lands signed; Project settings shows the option, and a new kind's preview counts what a person chose (kept)
and what the factory assumed on its own (withdrawn). Dark and light, 1440 and 390 pixels wide: nothing scrolls
sideways, every control has a name, and no step leaves a console error, a failed request or a
Content-Security-Policy violation.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). Only scripted models
answer (tests/factory_fakes.py).
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

from factory_fakes import model  # noqa: E402
from test_project_change_ui import NAMELESS  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import go_ahead  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class GoAheadUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-go-ahead-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        self.runner = QuietRunner()
        self.server, self.bootstrap = make_server(self.factory, 0, runner=self.runner)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.p = self.factory.new_project("Equipment loans", mode="mixed", maturity="demo")
        intake(self.p, IDEA, model=model(), requested_by=PERSON)
        Canon(self.p).answer("Q-001", "the team lead approves", person=PERSON, persona="product_owner")
        make_spec(self.p, model=model())
        go_ahead.choose(self.p, wait=True, person=PERSON, persona="product_owner", where="New project")
        self.card = go_ahead.gate(self.p)["waiting_on"][0]

    # -- helpers -------------------------------------------------------------------------------------------

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
            b.screenshot(self.shots / f"go-ahead-{b.step.replace(' ', '-')}.png")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-product_owner"]', what="the product owner persona")
        b.click("#pp-done", what="Done in the person menu")

    def overview(self) -> str:
        b = self.browser
        b.eval(f"location.hash = '#/p/{self.p.pid}/overview'; true")
        return b.wait("(document.querySelector('.next-strip') || {}).textContent", "What's next on the overview")

    def settings(self) -> None:
        b = self.browser
        b.click('[data-key="project-settings"]', what="Project settings")
        b.wait("document.querySelector('#modal').open && !!document.querySelector('#ps-nowait')", "the settings dialog")

    def new_project(self) -> None:
        """New project, opened from the sidebar at full width (a phone opens it from the menu), then back at the
        width the page had."""
        b = self.browser
        width = b.eval("innerWidth")
        b.eval("location.hash = '#/projects'; true")
        if width < 500:
            b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1,
                                                         "mobile": False})
            b.wait("innerWidth === 1440", "a wide page")
        b.click('[data-control="new_project"]', text="New project", what="New project")
        b.wait("!!document.querySelector('form.np-form') && !!document.querySelector('#np-nowait')", "New project")
        if width < 500:
            b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                         "mobile": True})
            b.wait(f"innerWidth === {width}", "the narrow page again")

    # -- the tests -----------------------------------------------------------------------------------------

    def test_FR_CHG1_AC_13_go_on_the_look_the_option_in_new_project_and_the_kind_preview(self):
        b = self.browser
        self.step("what's next shows the look")
        self.sign_in()
        strip = self.overview()
        self.assertIn("a look at the spec before the first build", strip)
        for key in (f"next:go_ahead_go:{self.card}", f"next:go_ahead_skip:{self.card}", "next:look_spec"):
            self.assertTrue(b.eval(f"!!document.querySelector('[data-key=\"{key}\"]')"), key)
        self.step("the kind preview counts what is kept")
        self.settings()
        self.assertFalse(b.eval("document.querySelector('#ps-nowait').checked"))          # it waits for a look
        b.eval("(() => { const s = document.querySelector('#ps-kind'); s.value = 'integration';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.type("#ps-reason", "it connects two systems")
        b.click('[data-key="ps-preview"]', what="Preview the impact")
        keeps = b.wait("(document.querySelector('[data-key=\"ps-keeps\"]') || {}).textContent", "kept and withdrawn")
        self.assertIn("Kept: 1 answer and 0 assumptions a person chose.", keeps)
        self.assertIn("the factory made on its own, made for the old kind", keeps)
        b.key("Escape", 27)
        b.wait("!document.querySelector('#modal').open", "the dialog closed")
        self.step("go")
        b.click(f'[data-key="next:go_ahead_go:{self.card}"]', what="Go: build it")
        deadline = time.monotonic() + 10
        while Canon(self.p).get_card(self.card)["state"] == "open" and time.monotonic() < deadline:
            time.sleep(0.1)
        decision = Canon(self.p).get_card(self.card)["decision"]
        self.assertEqual((decision["verdict"], decision["person"], decision["persona"]),
                         ("go", PERSON, "product_owner"))
        b.wait("!document.querySelector('[data-key^=\"next:go_ahead_go\"]')", "What's next without the look")
        self.step("new project without waiting")
        self.new_project()
        b.type('form.np-form input[aria-label="Title"]', "Bike loans")
        b.type('textarea[aria-label="The need"]', "We lend bikes to the team and lose track of them.")
        b.click('label[for="np-nowait"]', what="Build without waiting for me")
        b.click("form.np-form button[type=submit]", what="Create and start the intake")
        b.wait("location.hash.startsWith('#/p/') && !location.hash.includes('" + self.p.pid + "')", "the new project")
        made = next(p for p in self.factory.projects() if p.meta.get("title") == "Bike loans")
        self.assertFalse(go_ahead.waits_for_me(made))
        said = [r["event"]["payload"] for r in made.ledger().of_kind("go_ahead_set")]
        self.assertEqual([(s["wait"], s["person"], s["where"]) for s in said], [(False, PERSON, "New project")])
        self.check()

    def test_FR_CHG1_AC_13_the_card_and_the_option_fit_dark_and_light_at_1440_and_390_pixels(self):
        b = self.browser
        self.sign_in()
        fits = ("(() => { const m = document.querySelector('#modal .modal-in'); if (!m) return true;"
                " const r = m.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 1; })()")
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"{scheme} {width}")
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                             "mobile": width < 500})
                self.overview()
                b.wait(f"document.documentElement.dataset.theme === '{scheme}'", f"the {scheme} theme")
                self.assertTrue(b.eval(f"!!document.querySelector('[data-key=\"next:go_ahead_go:{self.card}\"]')"))
                self.check()
                for opener in (self.settings, self.new_project):
                    opener()
                    b.eval("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
                    self.assertTrue(b.eval(fits), (opener.__name__, scheme, width))
                    self.check()
                    b.key("Escape", 27)
                    b.wait("!document.querySelector('#modal').open", "the dialog closed")
                b.eval(f"location.hash = '#/p/{self.p.pid}/inbox'; true")
                b.wait(f"!!document.querySelector('[data-key=\"{self.card}:go\"]')", "the card's Go in the Inbox")
                self.assertTrue(b.eval(f"!!document.querySelector('[data-key=\"{self.card}:skip\"]')"))
                self.check()
        with contextlib.suppress(OSError):
            shutil.rmtree(self.tmp / "chrome", ignore_errors=True)
        self.assertEqual(json.loads(json.dumps(Canon(self.p).get_card(self.card)["state"])), "open")


if __name__ == "__main__":
    unittest.main()
