"""Staying on track and the autopilot in a real browser (FR-AP2-AC-5, FR-AP3-AC-4): headless Chrome over the
DevTools protocol, on the demo home, dark at 1440 px and light at 390 px.

A business owner sees the Track widget on Home, opens a project's Track view from it, reads the header's
Track pill, starts an autopilot (its job is recorded, not run), revokes its delegation, stops it, sets a
checkpoint and records a look, all with the keyboard focus kept on the page and every control named. After
every step there is no console error, no failed request, no Content-Security-Policy violation and no
horizontal scroll. Skipped when Chrome or git is missing, as tests/test_ui_drive.py is.
"""

import contextlib
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import autopilot, delegation, roads  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
# Every button, field and link in the Track view has a name a screen reader says.
UNNAMED = ("Array.from(document.querySelectorAll('.tr-view button, .tr-view input, .tr-view select, .tr-view a,"
           " .tr-view summary')).filter((e) => e.getClientRects().length && !(e.getAttribute('aria-label')"
           " || (e.labels && e.labels.length) || e.textContent.trim())).map((e) => e.outerHTML.slice(0, 80))")


class AutopilotUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-track-")).resolve()
        try:
            build_demo(cls.tmp / "demo", echo=lambda line: None)
        except Exception:
            roads.stop_started()
            roads.rmtree(cls.tmp)
            raise
        cls.factory = Factory(cls.tmp / "demo")
        cls.runner = QuietRunner()
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        roads.stop_started()
        with contextlib.suppress(OSError):
            roads.rmtree(cls.tmp)

    def project(self, title):
        return next(p for p in self.factory.projects() if p.meta.get("title") == title)

    def open_browser(self, width, scheme):
        b = Browser(self.chrome, self.tmp / f"chrome-{width}-{scheme}", width=width, height=1000 if width > 600 else 844)
        b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
        return b

    def check(self, b, step):
        b.eval("1")
        time.sleep(0.3)
        b.eval("1")
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{step}'")
        self.assertFalse(b.eval("document.documentElement.scrollWidth > window.innerWidth + 1"), f"sideways scroll: {step}")

    def sign_in(self, b, link):
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={link}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid .widget')",
               "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-business_owner"]', what="the business owner persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def track_view(self, b, p):
        """From the Home widget to the project's Track view, and its header pill."""
        b.wait("!!document.querySelector('#grid .widget[data-type=\"track\"] .health-row')", "the Track widget")
        rows = b.eval("Array.from(document.querySelectorAll('#grid .widget[data-type=\"track\"] .health-row'))"
                      ".map((r) => r.textContent)")
        self.assertEqual(len(rows), 4)
        self.assertTrue(any("Access review check" in r and "At risk" in r for r in rows), rows)
        b.click(f'#grid .widget[data-type="track"] a[href="#/p/{p.pid}/track"]', what="the project in the widget")
        b.wait(f"location.hash === '#/p/{p.pid}/track' && !!document.querySelector('.tr-view [data-figure]')",
               "the Track view")
        self.assertTrue(b.eval("document.querySelector('.track-pill').textContent").startswith("Track: "))
        self.assertEqual(b.eval(UNNAMED), [])
        self.assertEqual(b.eval("document.querySelectorAll('.tr-view [data-figure]').length"), 9)

    def start_and_stop(self, b, p, *, revoke):
        b.click('[data-key="ap-open"]', what="Start an autopilot")
        b.click('[data-key="ap-start"]', what="Start the autopilot")
        b.wait("document.activeElement && document.activeElement.dataset.key === 'ap-stop'", "the focus on Stop")
        run = autopilot.status(p)["run"]
        self.assertEqual((run["state"], run["person"], run["persona"]), ("running", PERSON, "business_owner"))
        self.assertIn(["-m", "kernel.cli", "autopilot", "run", p.pid], self.runner.started)
        self.assertIn("autopilot running", b.eval("document.querySelector('.track-pill').textContent"))
        if revoke:
            did = run["delegation"]
            b.click(f'[data-key="revoke:{did}"]', what=f"Revoke {did}")
            b.wait(f"!document.querySelector('[data-key=\"revoke:{did}\"]')", f"{did} revoked")
            self.assertEqual(delegation.delegations(p)[-1]["state"], "revoked")
        b.type("#ap-stop-r", "back at my desk")
        b.click('[data-key="ap-stop"]', what="Stop the autopilot")
        b.wait("document.activeElement && document.activeElement.dataset.key === 'ap-open'", "the focus on Start")
        self.assertEqual(autopilot.status(p)["run"]["stopped"]["reason"], "back at my desk")

    def checkpoint(self, b, p, stage):
        b.click('[data-key="tr-open"]', what="Set checkpoints and a budget")
        b.click(f'label[for="tr-st-{stage}"]', what=f"stage {stage}")
        b.click('[data-key="tr-set"]', what="Save checkpoints and budget")
        b.wait(f"!!document.querySelector('[data-key=\"look:{stage}\"]')", "the checkpoint due")
        b.type(f"#tr-look-{stage}", "looked it over")
        b.click(f'[data-key="look:{stage}"]', what="I looked")
        b.wait(f"!document.querySelector('[data-key=\"look:{stage}\"]')", "the look recorded")
        looked = p.ledger().of_kind("checkpoint_looked")[-1]["event"]["payload"]
        self.assertEqual((looked["stage"], looked["person"], looked["note"]), (stage, PERSON, "looked it over"))

    def test_FR_AP2_AC_5_a_person_runs_and_stops_an_autopilot_and_looks_at_a_checkpoint_in_chrome_dark_and_light(self):
        for width, scheme, title, revoke in ((1440, "dark", "Shipment webhook to the stock system", False),
                                             (390, "light", "Equipment loans", True)):
            p = self.project(title)
            b = self.open_browser(width, scheme)
            try:
                self.sign_in(b, self.bootstrap if width == 1440 else self.server.issue_link(600))
                self.check(b, f"sign in {width}")
                self.assertEqual(b.eval("matchMedia('(prefers-color-scheme: dark)').matches"), scheme == "dark")
                self.track_view(b, p)
                self.check(b, f"the Track view {width}")
                self.start_and_stop(b, p, revoke=revoke)
                self.check(b, f"start and stop {width}")
                self.checkpoint(b, p, int(p.meta["stage"]))
                self.check(b, f"a checkpoint {width}")
                b.cmd("Page.navigate", {"url": "about:blank"})       # nothing in flight when it closes
            finally:
                b.close()

    def test_FR_AP4_AC_3_a_projects_header_shows_one_on_track_answer_and_its_health_card_the_same_one(self):
        answers = ("Array.from(document.querySelectorAll('.proj-head .chip')).map((e) => e.textContent.trim())"
                   ".filter((t) => /^(Track: )?(On track|At risk|Off track|Not measured)/.test(t))")
        for width, scheme in ((1440, "dark"), (390, "light")):
            p = self.project("Equipment loans")
            b = self.open_browser(width, scheme)
            try:
                self.sign_in(b, self.server.issue_link(600))
                b.eval(f"location.hash = '#/p/{p.pid}/overview'")
                b.wait("!!document.querySelector('.proj-head .track-pill') && !!document.querySelector('.health-st .chip')",
                       "the project header and its Health card")
                shown = b.eval(answers)
                self.assertEqual(len(shown), 1, shown)                        # one answer, never two that disagree
                self.assertTrue(shown[0].startswith("Track: "), shown)
                word = shown[0][len("Track: "):].split(" · ")[0]
                self.assertEqual(b.eval("document.querySelector('.health-st .chip').textContent.trim()"), word)
                self.assertEqual(b.eval("document.querySelector('.proj-head .track-pill').tagName"), "A")  # keyboard
                self.check(b, f"one answer {width}")
                b.cmd("Page.navigate", {"url": "about:blank"})
            finally:
                b.close()


if __name__ == "__main__":
    unittest.main()
