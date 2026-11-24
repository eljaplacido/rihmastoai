"""FR-CHG1 in a real browser: headless Chrome over the DevTools protocol, as tests/test_ui_drive.py drives it.

A person opens a project whose intake asked a question, reads What's next on its overview and follows its
button to the question; opens Project settings, changes the kind of work, previews what that means for the
work done, and saves it with going back to the questions; adds material from the settings dialog (the panel
reads it in a run the cockpit starts); goes back a step; and presses What's next's Advance. Dark and light,
1440 and 390 pixels wide, the overview and the three dialogs fit with nothing scrolling sideways, every
control has a name a screen reader says, and no step leaves a console error, a failed request or a
Content-Security-Policy violation behind.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). Only scripted models
answer (tests/factory_fakes.py). ``RIHMA_UI_SHOTS=<folder>`` also saves a screenshot per step.
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
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
DESKS = "Desks in the open office can be booked too, by the half day."
NAMELESS = """(() => [...document.querySelectorAll(
  '#modal :is(button, a[href], input, select, textarea), .next-strip :is(button, a[href]), .chg-acts button')]
  .filter((el) => el.getClientRects().length).filter((el) => {
    const label = (el.labels ? [...el.labels].map((l) => l.textContent).join(' ') : '') || el.getAttribute('aria-label') || '';
    const own = /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) ? '' : el.textContent;
    return !(label + own).trim(); }).map((el) => el.outerHTML.slice(0, 120)))()"""


class ProjectChangeUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-change-")).resolve()
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
            b.screenshot(self.shots / f"change-{b.step.replace(' ', '-')}.png")

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

    def choose(self, selector: str, value: str) -> None:
        self.browser.eval(f"(() => {{ const s = document.querySelector({json.dumps(selector)}); s.value = {json.dumps(value)};"
                          " s.dispatchEvent(new Event('change')); return true; })()")

    def payloads(self, kind: str) -> list:
        return [r["event"]["payload"] for r in self.p.ledger().of_kind(kind)]

    def closed(self, what: str) -> None:
        self.browser.wait("!document.querySelector('#modal').open && !!document.querySelector('.next-strip')", what)

    # -- the tests -----------------------------------------------------------------------------------------

    def test_FR_CHG1_AC_9_a_person_changes_the_kind_adds_material_goes_back_and_follows_whats_next(self):
        b = self.browser
        self.step("what's next")
        self.sign_in()
        strip = self.overview()
        self.assertIn("Waits for 1 blocking question(s)", strip)
        b.click('[data-key="next:answer:Q-001"]', what="Answer Q-001 in What's next")
        b.wait(f"location.hash === '#/p/{self.p.pid}/questions/Q-001'", "the question, from What's next")
        self.step("settings preview")
        self.overview()
        b.click('[data-control="project_settings"]', what="Project settings")
        b.wait("document.querySelector('#modal').open && !!document.querySelector('#ps-kind')", "the settings dialog")
        self.assertEqual(b.eval("document.querySelector('#ps-kind').value"), "web_service")
        self.assertTrue(b.eval("document.querySelector('[data-slot=\"posture\"]') !== null"))   # the posture's place
        self.assertTrue(b.eval("document.querySelector('[data-key=\"ps-save\"]').disabled"))     # preview first
        self.choose("#ps-kind", "integration")
        b.type("#ps-reason", "it connects two systems, not a web app")
        b.click('[data-key="ps-preview"]', what="Preview the impact")
        said = b.wait("(document.querySelector('#ps-impact .chg-list') || {}).textContent", "the impact")
        self.assertIn("no longer fit", said)
        self.assertEqual(self.payloads("project_changed"), [])                  # the preview wrote nothing
        b.wait("!document.querySelector('.chg-redo').hidden && !document.querySelector('[data-key=\"ps-save\"]').disabled",
               "Save and the offer to go back")
        b.click('label[for="ps-redo"]', what="Also go back to the questions")
        self.step("settings saved")
        b.click('[data-key="ps-save"]', what="Save the settings")
        self.closed("the dialog closed")
        rec = self.payloads("project_changed")[-1]
        self.assertEqual((rec["person"], rec["persona"], rec["after"]), (PERSON, "product_owner", {"kind": "integration"}))
        self.assertEqual(self.p.meta["profile"], "integration")
        self.assertEqual(Canon(self.p).question("Q-001")["status"], "withdrawn")
        b.wait("document.querySelector('.next-strip').textContent.includes('Run the intake again')", "What's next anew")
        self.step("add material")
        b.click('[data-control="project_settings"]', what="Project settings")
        b.click('[data-key="ps-material"]', what="Add material")
        b.wait("document.querySelector('#modal').open && !!document.querySelector('#mt-text')", "the material dialog")
        b.type("#mt-text", DESKS)
        b.type("#mt-note", "desks")
        b.click('[data-key="mt-add"]', what="Add the material")
        self.closed("the material added")
        self.assertEqual([(r["n"], r["note"], r["person"]) for r in self.payloads("material_added")], [(1, "desks", PERSON)])
        self.assertIn(DESKS, self.p.read("source.json")["text"])
        self.assertEqual(self.runner.started[-1], ["-m", "kernel.cli", "run", self.p.pid])   # the panel reads it
        self.step("go back")
        b.click('[data-control="project_settings"]', what="Project settings")
        b.click('[data-key="ps-rewind"]', what="Go back a step")
        b.wait("document.querySelector('#modal').open && !!document.querySelector('.chg-steps')", "the steps")
        self.assertTrue(b.eval("document.querySelector('[data-key=\"rw:spec\"]').disabled"))   # no spec yet
        b.click('label[for="rw-material"]', what="Back to the material")
        b.type("#rw-reason", "the request was the wrong document")
        b.click('[data-key="rw:go"]', what="Go back")
        self.closed("gone back")
        rec = self.payloads("rewound")[-1]
        self.assertEqual((rec["to"], rec["person"], rec["reason"]), ("material", PERSON, "the request was the wrong document"))
        strip = b.wait("document.querySelector('.next-strip').textContent.includes('Waits for material')"
                       " && document.querySelector('.next-strip').textContent", "What's next: material")
        self.assertIn("Add material", strip)
        self.step("what's next adds material")
        b.click('[data-key="next:add_material"]', what="Add material in What's next")
        b.wait("document.querySelector('#modal').open && !!document.querySelector('#mt-text')", "the material dialog")
        b.type("#mt-text", IDEA + " " + DESKS)
        b.click('label[for="mt-reintake"]', what="no re-intake now")
        b.click('[data-key="mt-add"]', what="Add the material")
        self.closed("the request added")
        b.wait("document.querySelector('.next-strip').textContent.includes('Run the intake again')", "the intake waits")
        started = len(self.runner.started)
        b.click('[data-key="next:advance"]', what="Run the intake again")
        deadline = time.monotonic() + 10
        while len(self.runner.started) == started and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.runner.started[-1], ["-m", "kernel.cli", "run", self.p.pid])
        self.check()

    def test_FR_CHG1_AC_9_the_change_dialogs_fit_dark_and_light_at_1440_and_390_pixels(self):
        b = self.browser
        self.sign_in()
        fits = ("(() => { const m = document.querySelector('#modal .modal-in'); if (!m) return true;"
                " const r = m.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 1"
                " && [...m.querySelectorAll('input, select, textarea, button, label')]"
                ".every((e) => e.getBoundingClientRect().right <= r.right + 1); })()")
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"{scheme} {width}")
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                             "mobile": width < 500})
                self.overview()
                b.wait(f"document.documentElement.dataset.theme === '{scheme}'", f"the {scheme} theme")
                self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, (scheme, width))
                for opener, ready in (('[data-key="project-settings"]', "#ps-kind"), ('[data-key="ps-rewind"]', ".chg-steps"),
                                      ('[data-key="ps-material"]', "#mt-text")):
                    if opener != '[data-key="project-settings"]':
                        b.click('[data-key="project-settings"]', what="Project settings")
                        b.wait("document.querySelector('#modal').open && !!document.querySelector('#ps-kind')", "settings")
                    b.click(opener, what=opener)
                    b.wait(f"document.querySelector('#modal').open && !!document.querySelector('{ready}')", ready)
                    b.eval("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
                    self.assertTrue(b.eval(fits), (opener, scheme, width))
                    self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0,
                                         (opener, scheme, width))
                    self.check()
                    b.key("Escape", 27)
                    b.wait("!document.querySelector('#modal').open", "the dialog closed")
                self.check()
        with contextlib.suppress(OSError):
            shutil.rmtree(self.tmp / "chrome", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
