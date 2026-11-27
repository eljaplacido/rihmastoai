"""FR-HEAL1-AC-8: never a dead end, in a real browser (headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py).

A view whose read fails with a 500 (a test route: the Track view's read raises) shows the incident panel in place of
an error: what happened in plain words, Try again, the remedies, Investigate with Rihma, and the incident's id; the
investigation opens with its diagnosis and trace. A view that breaks while drawing (the Outputs view given a read it
cannot draw, the owner's example) shows the same panel, and the page reports it as an incident signed with the person
chip. The Incidents page lists both with their states and remedies, What Rihmasto learned and the feedback; every view
ends with "Something's wrong here" and "This is unclear / this is wrong". Dark at 1440 px, then light at 390 px. After
every step there is no console error, failed request or Content-Security-Policy violation besides the 500 provoked on
purpose, every control has a name, and nothing is wider than the screen. Skipped when Chrome is not installed.
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_shape_models as shaped  # noqa: E402  (a module: its own test class is not run from here)
from factory_fakes import isolated_routing  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from cockpit.server import make_server  # noqa: E402
from kernel import incidents as inc  # noqa: E402
from kernel.store import Factory  # noqa: E402


def broken_track(api, **_):
    raise AttributeError("'NoneType' object has no attribute 'plan'")


def undrawable_outputs(api, **_):
    return 200, {}


class HealUiTest(unittest.TestCase):
    UI = shaped.ShapeModelsUiTest
    step, sign_in, theme, narrow = UI.step, UI.sign_in, UI.theme, UI.narrow

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-heal-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolated_routing(self, self.tmp)
        for patcher in (mock.patch.object(cockpit.Api, "get_track", broken_track),
                        mock.patch.object(cockpit.Api, "get_outputs", undrawable_outputs),
                        mock.patch("kernel.models_setup.gnomon_found", return_value=False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.factory = Factory(self.tmp / "home")
        self.project = self.factory.new_project("Old intranet", maturity="demo", mode="mixed")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def check(self) -> None:
        """No problem besides the 500 provoked on purpose (Chrome logs the failed request it answered)."""
        b = self.browser
        b.eval("1")
        b.problems = [p for p in b.problems if "status of 500" not in str(p[2])]
        self.UI.check(self)

    def go(self, view: str) -> None:
        self.browser.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.project.pid}/{view}"})

    def test_FR_HEAL1_AC_8_errors_show_the_incident_panel_and_the_incidents_page_in_chrome_dark_and_light(self):
        b = self.browser
        self.step("sign in")
        self.sign_in("developer")
        self.theme("dark", "Dark")
        self.step("a 500 shows the incident panel")
        self.go("track")
        b.wait("!!document.querySelector('.heal-panel[data-incident^=\"I-\"]')", "the incident panel with its id")
        panel = b.eval("document.querySelector('.heal-panel').textContent")
        self.assertIn("The cockpit hit a bug", panel)
        self.assertIn("Try again", panel)
        self.assertIn("Investigate with Rihma", panel)
        self.assertNotIn("internal error: AttributeError", panel)
        self.check()
        self.step("investigate with rihma")
        b.click('.heal-panel [data-control="investigate_incident"]', what="Investigate with Rihma")
        b.wait("!!document.querySelector('#modal .heal-found')", "the diagnosis")
        found = b.eval("document.querySelector('#modal .heal-found').textContent")
        self.assertIn("rihmasto bug", found)
        self.assertIn("Trace: By rule", found)
        b.click('#modal .modal-head .icon-btn', what="Close")
        self.step("a view that breaks while drawing")
        self.go("outputs")
        b.wait("((document.querySelector('.heal-panel[data-incident=\"I-0002\"]') || {}).textContent || '')"
               ".includes('A view could not be drawn')", "the panel for a render error, reported as I-0002")
        kinds = sorted(i["kind"] for i in inc.incidents(self.factory))
        self.assertEqual(kinds, ["server_error", "view_broken"])
        reported = [i for i in inc.incidents(self.factory) if i["kind"] == "view_broken"][0]
        self.assertEqual(reported["reported_by"]["person"], shaped.PERSON)
        self.step("the incidents page")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/incidents"})
        b.wait("document.querySelectorAll('.heal-card').length === 2", "both incidents")
        page = b.eval("document.querySelector('#main').textContent")
        for words in ("Investigating", "Open", "What Rihmasto learned", "Feedback", "Something's wrong here",
                      "This is unclear / this is wrong"):
            self.assertIn(words, page)
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        b.wait("document.querySelectorAll('.heal-card').length === 2", "the incidents at 390 px")
        b.click('[data-key="foot:feedback"]', what="This is unclear / this is wrong")
        b.wait("!!document.querySelector('#modal #fb-words')", "the feedback form")
        b.type("#fb-words", "What does learned mean here?")
        b.click('[data-key="fb:send"]', what="Send feedback")
        b.wait("!document.querySelector('#modal[open]')", "the form closed")
        self.check()

    def test_incidents_with_a_learned_remedy_wrap_within_390_px(self):
        """Acceptance (2026-11-26): the page scrolled sideways at 390 px, cutting the title and the remedy."""
        from kernel import immune

        b, pid = self.browser, self.project.pid
        long = ("failed: the custom check's command exited 3 after printing a very long line of output, "
                "/srv/shipment-webhook-to-the-stock-system/tests/integration/test_stock_levels_passed.py")
        first = inc.open_incident(self.factory, kind="check_failed", where="check:custom", message=long, project=pid)
        how = {"kind": "explain", "label": "Restarted the stock-system-integration-sandbox-container-and-reran",
               "text": "Restarted the sandbox container and ran the check again"}
        out = inc.resolve(self.factory, first["id"], how=how, person=shaped.PERSON, persona="developer",
                          note="restarted the sandbox")
        immune.approve(self.factory, out["remedy"]["id"], person=shaped.PERSON, persona="developer")
        inc.open_incident(self.factory, kind="check_failed", where="check:custom", message=long, project=pid)
        self.step("sign in, narrow")
        self.sign_in("developer")
        self.theme("light", "Light")
        self.narrow()
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/incidents"})
        b.wait("!!document.querySelector('.heal-card .heal-seen')", "the incident with what was learned")
        self.assertLessEqual(b.eval("document.documentElement.scrollWidth"), 390)
        self.check()

    def test_navigating_on_after_the_main_area_was_dropped_raises_nothing(self):
        """Acceptance (2026-11-26): Home ↔ Settings threw on a null #main (route's dataset, skeleton's isConnected)."""
        b = self.browser
        self.step("sign in")
        self.sign_in("it")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/settings"})
        b.wait("!!document.querySelector('#main [data-id=\"enforcement_platform\"]')", "the settings page")
        self.step("the main area is dropped, then Home and Settings")
        b.eval("document.getElementById('main').remove()")
        settings = "#main [data-id=\"enforcement_platform\"]"
        for where, ready in (("#/", "#main"), ("#/settings", settings), ("#/", "#main")):
            b.eval(f"location.hash = '{where}'")
            b.wait(f"!!document.querySelector('{ready}') && document.querySelector('#main').dataset.loaded === '1'",
                   f"{where} drawn")
        self.check()


if __name__ == "__main__":
    unittest.main()
