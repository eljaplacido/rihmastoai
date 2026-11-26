"""FR-ITD1-AC-8: Integrations and data in a real browser (headless Chrome over the DevTools protocol).

Over the stand-in home of tests/itdata_fixture.py (every check reaches loopback only), IT opens the platform's
Integrations and data page from the sidebar, checks the platform-wide webhook relay (it fails: its address is
outside) and sets a reminder to rotate its secret; then opens the Order desk's view in the Run capsule, picks a node
of the data-flow diagram and follows it to its connection, turns the desk's Teams channel off with a reason, and asks
Rihma which data leaves the machine; first in the dark theme at 1440 px, then in the light theme at 390 px. After
every step there is no console error, failed request or Content-Security-Policy violation, every control has a name
and nothing is wider than the screen. Skipped when Chrome is not installed (``RIHMA_CHROME`` names another binary).
``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import itdata_fixture as fx  # noqa: E402
from factory_fakes import isolated_routing  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import embeds, itdata_actions, relay  # noqa: E402
from kernel import itdata_project as views  # noqa: E402

UNNAMED = """[...document.querySelectorAll('#main button, #main a[href], #main input')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim() || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (el.tagName !== 'INPUT' && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


class _Cleanups:
    """What a class-wide fixture undoes at the end (isolated_routing asks a case for addCleanup)."""

    def __init__(self) -> None:
        self.undo: list = []

    def addCleanup(self, fn, *args) -> None:  # noqa: N802 - unittest's name
        self.undo.append((fn, args))

    def run(self) -> None:
        while self.undo:
            fn, args = self.undo.pop()
            with contextlib.suppress(Exception):
                fn(*args)


class ItDataUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-itd-")).resolve()
        cls.cleanups = _Cleanups()
        isolated_routing(cls.cleanups, cls.tmp)
        for name in fx.VARS:
            os.environ.pop(name, None)
        env = mock.patch.dict(os.environ, {"ORDERS_STAGING_TOKEN": fx.SECRET_VALUE, "HOOK_SIGNING_SECRET": fx.SECRET_VALUE})
        env.start()
        cls.cleanups.addCleanup(env.stop)
        cls.calls = []
        net = mock.patch.object(itdata_actions, "connect", fx.offline(cls.calls))
        net.start()
        cls.cleanups.addCleanup(net.stop)
        cls.listener = fx.Listener()
        w = fx.build(cls.tmp / "home", cls.listener.port)
        cls.factory, cls.project, cls.notes = w["factory"], w["project"], w["notes"]
        embeds.create(cls.factory, kind="feedback", origins=["https://shop.example.org"], person=fx.PERSON[0],
                      persona=fx.PERSON[1], project_id=cls.project.pid, label="Shop")      # FR-ITD2: its answers leave
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(5)
        cls.listener.stop()
        cls.cleanups.run()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-itd")
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
        self.assertEqual(b.eval("window.__itdErrors || []"), [], f"uncaught page errors during '{b.step}'")
        if os.environ.get("RIHMA_UI_SHOTS"):
            shots = Path(os.environ["RIHMA_UI_SHOTS"])
            shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(shots / f"itdata-{b.step.replace(' ', '-').replace(',', '')}.png")

    def fits_and_named(self) -> None:
        b = self.browser
        self.assertEqual(b.eval(UNNAMED), [], f"controls without a name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def sign_in(self, link: str | None = None) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={link or self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid .widget')",
               "the signed-in dashboard")
        # an uncaught error (a ResizeObserver loop too) is a window "error" event, never a console line: keep each
        b.eval("window.__itdErrors = []; window.addEventListener('error', (e) => window.__itdErrors.push(String(e.message)));"
               " window.addEventListener('unhandledrejection', (e) => window.__itdErrors.push(String(e.reason))); true")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-it"]', what="the IT persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def toast(self, words: str, what: str) -> None:
        b = self.browser
        b.wait(f"(document.querySelector('#status') || {{}}).textContent.includes({json.dumps(words)})", what)
        b.click("#status .toast .icon-btn", what="Dismiss on the message")
        b.wait("!document.querySelector('#status .toast')", "the message dismissed")

    def platform_page(self) -> None:
        b = self.browser
        b.click('#sb-nav a[href="#/connections"]', what="Integrations and data in the sidebar")
        b.wait("location.hash === '#/connections' && document.querySelectorAll('.itd-card').length >= 6",
               "the platform's connections")
        self.assertTrue(b.eval("!!document.querySelector('[data-control=\"itdata_stores\"] .itd-store')"))
        self.assertTrue(b.eval("!!document.querySelector('.itd-proj a[href$=\"/itdata\"]')"))
        self.fits_and_named()
        self.step("check the webhook relay")
        b.click('[data-key="itd-check:relay:SUB-002"]', what="Check now on the webhook relay")
        self.toast("Checked 1: 1 failing", "what the check found")
        b.wait("document.querySelector('.itd-card[data-id=\"relay:SUB-002\"]')?.dataset.state === 'failing'",
               "the relay failing")
        self.assertEqual(self.calls[-1], ("hooks.example.org", 443))
        self.step("rotation reminder")
        b.type('[data-cred="HOOK_SIGNING_SECRET"] .itd-days', "30")
        b.click('[data-key="itd-rot:HOOK_SIGNING_SECRET"]', what="Set reminder for HOOK_SIGNING_SECRET")
        self.toast("Rotate HOOK_SIGNING_SECRET by 2026-12-25", "the reminder's date")
        b.wait("(document.querySelector('[data-cred=\"HOOK_SIGNING_SECRET\"]') || {}).textContent"
               "?.includes('Rotate by 2026-12-25')", "the reminder beside the credential")

    def project_view(self) -> None:
        b, pid = self.browser, self.project.pid
        b.eval(f"location.hash = '#/p/{pid}/itdata'; true")
        b.wait("document.querySelectorAll('.itd-node').length >= 8 && document.querySelectorAll('.itd-card').length >= 5",
               "the project's data flow and connections")
        self.assertTrue(b.eval("!!document.querySelector('.caps-sub a[data-view=\"itdata\"]')"), "in the Run capsule")
        self.assertTrue(b.eval("!!document.querySelector('.itd-edge.leaves')"), "an edge that leaves is marked")
        self.fits_and_named()
        self.step("pick a node")
        b.click('[data-node="n:integration:orders_api"]', what="the orders_api node")
        b.wait("!document.querySelector('.itd-detail').hidden", "the node's detail")
        b.click('[data-key="itd-goto:integration:orders_api"]', what="Show the connection")
        b.wait("document.activeElement?.dataset.id === 'integration:orders_api'", "the connection in focus")
        self.step("turn the Teams channel off")
        b.click('[data-key="itd-off:relay:SUB-001"]', what="Turn off on the Teams channel")
        b.type(".itd-off input", "the desk moved to email")
        b.click('[data-key="itd-off-ok:relay:SUB-001"]', what="Turn off, confirmed")
        self.toast("is off", "the channel off")
        self.assertNotIn("SUB-001", [s["id"] for s in relay.subscriptions(self.factory)])
        rec = self.project.ledger().of_kind("itdata_disabled")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["reason"]), (PERSON, "the desk moved to email"))

    def test_FR_ITD1_AC_8_it_sees_every_connection_checks_reminds_and_turns_off_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("the platform's page")
        self.platform_page()
        self.step("the project's view")
        self.project_view()
        self.step("ask which data leaves")
        b.click('[data-key="itd-ask-leaves"]', what="Ask: which data leaves the machine")
        b.wait("(document.querySelector('#assistant') || {}).textContent?.includes('opencode.ai')", "Rihma's answer")
        b.click("#as-close", what="Close Ask Rihma")
        self.step("light and narrow")
        self.theme("light", "Light")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        b.wait("document.querySelector('.itd-flow-box')?.dataset.wide === '0'", "the diagram in rows")
        time.sleep(0.3)
        self.fits_and_named()
        self.step("the diagram, narrow")
        b.eval("document.querySelector('.itd-flow').scrollIntoView(); true")
        self.assertLessEqual(b.eval("document.querySelector('.itd-svg').getBoundingClientRect().right"), 390)
        self.step("the platform's page, narrow")
        b.eval("location.hash = '#/connections'; true")
        b.wait("!!document.querySelector('[data-control=\"itdata_stores\"] .itd-store') && !document.querySelector('.itd-node')",
               "the platform's connections and stores, narrow")
        self.fits_and_named()
        self.assertNotIn(fx.SECRET_VALUE, b.eval("document.body.innerText"))
        self.check()

    def own_truth(self, narrow: bool) -> None:
        """FR-ITD2: the caption counts the dashed lines, a wide Turn off warns first, blocked agents say so."""
        b, pid, n = self.browser, self.project.pid, len(views.project_view(self.project)["flow"]["leaving"])
        b.eval(f"location.hash = '#/p/{pid}/itdata'; true")
        b.wait("!!document.querySelector('.itd-node[data-item^=\"chat:\"]')", "the project's data flow with its chat")
        caption = b.eval("document.querySelector('[data-key=\"itd-flow-caption\"]').textContent")
        self.assertTrue(caption.startswith(f"{n} "), caption)     # IT reads the technical words; the count is one
        self.assertNotIn("edge target", caption)
        self.fits_and_named()
        self.step(f"a wide turn off warns first{', narrow' if narrow else ''}")
        b.click('[data-key="itd-off:relay:SUB-002"]', what="Turn off on the platform-wide relay")
        b.wait("(document.querySelector('.itd-off .itd-wide') || {}).textContent?.includes('every project')",
               "the warning before confirming")
        self.assertIn("all of them", b.eval("document.querySelector('[data-key=\"itd-off-ok:relay:SUB-002\"]').textContent"))
        self.fits_and_named()
        self.step(f"cancel the wide turn off{', narrow' if narrow else ''}")
        b.click(".itd-off .btn", text="Cancel", what="Cancel")
        self.assertIn("SUB-002", [s["id"] for s in relay.subscriptions(self.factory)])
        self.step(f"a confidential project's blocked agents{', narrow' if narrow else ''}")
        b.eval(f"location.hash = '#/p/{self.notes.pid}/itdata'; true")
        b.wait("document.querySelectorAll('.itd-agent [data-blocked]').length >= 4", "the blocked agents")
        self.assertFalse(b.eval("!!document.querySelector('.itd-agent[data-agent=\"analyst\"] .itd-top')"
                                ".textContent.includes('Stays here')"))
        self.assertTrue(b.eval("!!document.querySelector('.itd-agent[data-agent=\"analyst\"] a[href=\"#/models\"]')"))
        b.eval("document.querySelector('.itd-agents').scrollIntoView(); true")
        self.fits_and_named()

    def test_FR_ITD2_AC_5_each_project_its_own_truth_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in again")
        self.sign_in(self.server.issue_link())           # the first link was used by the test before
        self.theme("dark", "Dark")
        self.step("the caption counts the dashed lines")
        self.own_truth(narrow=False)
        self.step("light and narrow again")
        self.theme("light", "Light")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        self.step("the caption, narrow")
        self.own_truth(narrow=True)
        self.check()


if __name__ == "__main__":
    unittest.main()
