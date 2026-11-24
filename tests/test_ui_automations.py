"""FR-AUT1-AC-15: automations in a real browser (headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py), with the cockpit's own scheduler ticking.

A person opens Automations from the sidebar, starts from the cross-project template (when Loans releases,
a change proposal on Bookings), reads the summary the kernel writes before saving, sets it up, runs a dry
run, runs it now (the scheduler carries it out and the change card waits on Bookings for people), pauses
and resumes it, filters the list, opens the project's Automations tab and tags the project, then sees on
Home the card of an automation the circuit breaker paused. Dark at 1440 px, then light at 390 px. After
every step there is no console error, failed request or Content-Security-Policy violation, every control
has a name, and nothing is wider than the screen. Skipped when Chrome is not installed.
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

from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402
from test_ui_shape_models import NAMELESS, OVERFLOW  # noqa: E402

from cockpit.automation_routes import Scheduler  # noqa: E402
from cockpit.server import make_server  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"


class AutomationsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-auto-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        self.loans = self.factory.new_project("Loans", maturity="demo", mode="mixed")
        self.bookings = self.factory.new_project("Bookings", maturity="demo", mode="mixed")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        self.server.automation_scheduler = Scheduler(self.factory, every=0.5).start()
        self.addCleanup(self.server.automation_scheduler.stop)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
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
        self.assertEqual(b.eval(NAMELESS), [], f"controls with no name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"automations-{b.step.replace(' ', '-')}.png")

    def sign_in(self, persona: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what="the persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def narrow(self) -> None:
        b = self.browser
        b.cmd("Emulation.setDeviceMetricsOverride",
              {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        time.sleep(0.3)

    def choose(self, selector: str, value: str) -> None:
        self.browser.eval(f"(() => {{ const s = document.querySelector({json.dumps(selector)});"
                          f" s.value = {json.dumps(value)};"
                          " s.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")

    def test_FR_AUT1_AC_15_a_person_sets_runs_pauses_and_filters_automations_in_chrome_dark_and_light(self):
        b = self.browser
        a, bk = self.loans.pid, self.bookings.pid
        self.step("sign in")
        b.cmd("Emulation.setDeviceMetricsOverride",
              {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        self.sign_in("product_owner")
        self.theme("dark", "Dark")
        self.step("open automations")
        b.click('#sb-nav a[href="#/automations"]', what="Automations in the sidebar")
        b.wait("location.hash === '#/automations' && !!document.querySelector('#amn-list')", "the Automations page")
        self.assertIn("No automation yet", b.eval("document.querySelector('#amn-list').textContent"))
        self.step("cross-project template")
        b.click('[data-key="amn-tpl:cross_project"]', what="the cross-project template")
        b.wait("!!document.querySelector('#modal[open] #amn-name')", "the builder")
        b.click(f'label[for="amn-p-{a}"]', what="Loans as the project it reacts to")
        self.choose("#amn-a-target", bk)
        b.wait(f"document.querySelector('#amn-summary').textContent.includes('When a release is done, for project {a}, "
               f"open a change proposal on {bk}')", "the summary the kernel writes")
        self.step("set it up")
        b.click('[data-key="amn-save"]', what="Set it up")
        b.wait("!document.querySelector('#modal').open && !!document.querySelector('[data-key=\"auto:AU-001\"]')",
               "the automation in the list")
        auto = au.get(self.factory, "AU-001")
        self.assertEqual((auto["owner"]["person"], auto["action"]["project"]), (PERSON, bk))
        self.step("dry run")
        b.click('[data-key="automations_dry_run:AU-001"]', what="Dry run")
        b.wait("document.querySelector('[data-key=\"auto:AU-001\"]').textContent.includes('Nothing would run')",
               "what it would do: nothing yet")
        self.step("it runs on a release")
        self.loans.log("release_done", {"release": 1})               # the scheduler ticks and reacts
        deadline = time.monotonic() + 15
        while not Canon(self.bookings).cards(kind="change") and time.monotonic() < deadline:
            time.sleep(0.2)
        cards = Canon(self.bookings).cards(kind="change")
        self.assertEqual([(c["state"], c["payload"]["person"]) for c in cards], [("open", PERSON)])   # for people
        self.step("run now")
        b.click('[data-key="automations_run:AU-001"]', what="Run now")
        b.wait(f"document.querySelector('[data-key=\"auto:AU-001\"]').textContent.includes('asked by {PERSON}')",
               "the run a person asked for, in its history")
        cards = Canon(self.bookings).cards(kind="change")
        self.assertEqual([c["state"] for c in cards], ["open", "open"])          # each one waits for people
        self.assertIn("run_now", cards[-1]["payload"]["text"])
        self.step("pause and resume")
        b.click('[data-key="automations_pause:AU-001"]', what="Pause")
        b.wait("document.querySelector('[data-key=\"auto:AU-001\"]').textContent.includes('Paused')", "paused")
        b.click('[data-key="amn-f-state:paused"]', what="the Paused filter")
        b.wait("!!document.querySelector('[data-key=\"auto:AU-001\"]')", "the paused one listed")
        b.click('[data-key="automations_resume:AU-001"]', what="Resume")
        b.wait("document.querySelector('#amn-list').textContent.includes('None matches')", "no paused one left")
        b.click('[data-key="amn-f-state:all"]', what="the All filter")
        self.step("the project's tab")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{a}/automations"})
        b.wait("!!document.querySelector('.amn-tab [data-key=\"auto:AU-001\"]')", "the project's Automations tab")
        b.type("#amn-tags", "ops, nightly")
        b.click('[data-key="amn-tags-save"]', what="Save tags")
        deadline = time.monotonic() + 10
        while self.factory.project(a).meta.get("tags") != ["nightly", "ops"] and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertEqual(self.factory.project(a).meta.get("tags"), ["nightly", "ops"])
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        b.click(f'[data-key="amn-new:{a}"]', what="New automation on the project's tab")
        b.wait("document.querySelector('#amn-summary').textContent.includes('Not yet: the name is empty')",
               "the builder, narrow, saying what is missing")
        self.check()
        if self.shots:
            b.screenshot(self.shots / "automations-builder-narrow.png")
        b.click("#modal .modal-head button", what="Close the builder")
        b.wait("!document.querySelector('#modal').open", "the builder closed")
        self.step("the breaker on home")
        au.add(self.factory, {"name": "Ask after a release", "trigger": {"kind": "event", "types": ["release_done"]},
                              "action": {"kind": "ask", "text": "What changed?"}, "limits": {"breaker": 1},
                              "scope": {"kind": "project", "projects": [a]}}, person=PERSON, persona="product_owner")
        self.loans.log("release_done", {"release": 2})
        deadline = time.monotonic() + 10
        while au.get(self.factory, "AU-002")["state"] != "paused" and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertEqual(au.get(self.factory, "AU-002")["paused_by"], "breaker")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/home"})
        b.wait("!!document.querySelector('#home-auto .card')", "the paused automation on Home")
        self.assertIn("circuit breaker", b.eval("document.querySelector('#home-auto .card').textContent"))
        b.click('[data-key="home:automations"]', what="Open Automations from Home")
        b.wait("location.hash === '#/automations' && !!document.querySelector('[data-key=\"auto:AU-002\"] .amn-why')",
               "why it paused")
        self.check()


if __name__ == "__main__":
    unittest.main()
