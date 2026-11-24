"""FR-MAT1-AC-9: New project's "Scan the folder" step in a real browser (headless Chrome, DevTools protocol).

A person opens New project, chooses "An existing project" and gives a folder of every format with a few
secret-looking files (tests/material_fixture.py, built in the test). Before anything is sent or created the
step shows the folder's material map grouped by what happens to each file; the person unticks a file, the
step scans again without it and the focus stays on that file; then Adopt starts the job, with the exclusion.
A folder of documents only is refused for adoption and offered as material for a new project, which the
person then creates from the same step. Light and dark, 1440 and 390 px wide: nothing scrolls sideways, no
secret appears on the page, and there is no console error, failed request or CSP violation.

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
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import material_fixture as mf  # noqa: E402
from test_material import SECRETS, SHIPPED  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402
from kernel.store import Factory  # noqa: E402


class UiMaterialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-material-")).resolve()
        cls.patches = [mock.patch.dict(os.environ, {ROOTS_ENV: str(cls.tmp)}),
                       mock.patch("kernel.confidential._routing", return_value=SHIPPED)]
        for p in cls.patches:
            p.start()
        cls.lobby = mf.build(cls.tmp / "lobby")
        cls.papers = cls.tmp / "papers"
        cls.papers.mkdir()
        (cls.papers / "README.md").write_text("# Visitor register\n\nThe lobby needs a register of its visitors.\n",
                                              encoding="utf-8")
        mf.docx(cls.papers / "brief.docx", [("Heading1", "Brief"), ("", "Hosts are told when a guest arrives.")])
        cls.factory = Factory(cls.tmp / "home")
        cls.factory.new_project("Earlier work")      # not a new home: no first-run choice over the page
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
        for p in cls.patches:
            p.stop()
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
            b.screenshot(self.shots / f"material-{b.step.replace(' ', '-')}.png")

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

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000 if px > 500 else 900,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})
        self.browser.wait(f"window.innerWidth === {px}", f"a {px} px wide page")

    def theme(self, word: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def open_dialog(self, existing: bool) -> None:
        b = self.browser
        b.eval("location.hash = '#/projects'; true")
        b.click('[data-control="new_project"]', text="New project", what="New project")
        b.wait("!!document.querySelector('form.np-form')", "the New project dialog")
        if existing:
            b.click('[data-key="np-start:existing"]', what="Start from: An existing project")
        b.type('form.np-form input[aria-label="Title"]', "Visitor register")

    def scan(self, field: str, folder: Path) -> None:
        b = self.browser
        b.type(field, str(folder))
        b.wait("document.querySelector('form.np-form button[type=submit]').textContent.trim() === 'Scan the folder'",
               "the submit button asking to scan first")
        b.click("form.np-form button[type=submit]", what="Scan the folder")
        b.wait("!!document.querySelector('.scan-step:not([hidden]) .scan-group')", "the material map")

    def fits(self, px: int) -> None:
        """Nothing scrolls sideways: not the page, not the dialog, not the map."""
        b = self.browser
        sizes = b.eval("""(() => { const f = document.querySelector('form.np-form');
            const s = document.querySelector('.scan-step');
            return {page: document.documentElement.scrollWidth, form: [f.scrollWidth, f.clientWidth],
                    step: [s.scrollWidth, s.clientWidth], width: window.innerWidth}; })()""")
        self.assertLessEqual(sizes["page"], px, sizes)
        self.assertLessEqual(sizes["form"][0], sizes["form"][1], sizes)
        self.assertLessEqual(sizes["step"][0], sizes["step"][1], sizes)
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            theme = b.eval("document.documentElement.dataset.theme")
            b.screenshot(self.shots / f"material-dialog-{px}-{theme}.png")

    def test_FR_MAT1_AC_9_the_scan_step_shows_the_map_untick_works_and_adopt_starts_the_job(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("Light")
        self.step("scan an existing folder")
        self.open_dialog(existing=True)
        self.scan('[data-control="adopt_project"]', self.lobby)
        groups = b.eval("[...document.querySelectorAll('.scan-group > summary')].map((s) => s.textContent)")
        self.assertEqual([g.rstrip("0123456789") for g in groups],
                         ["Read in full", "Summarised", "Listed only, not read", "Skipped"])
        text = b.eval("document.querySelector('.scan-step').textContent")
        for said in ("README.md", "brief or spec", "may hold secrets: never opened, by its name",
                     "may hold secrets: its text holds a credential", "3 code files: counted in the code inventory",
                     "characters would be sent to the analyst role's endpoint", "Nothing has been sent",
                     "Not a git repository: the files above that are not skipped are copied"):
            self.assertIn(said, text)
        page = b.eval("document.body.innerText")
        for secret in SECRETS:
            self.assertNotIn(secret, page)
        self.assertEqual(b.eval("document.querySelector('form.np-form button[type=submit]').textContent.trim()"),
                         "Adopt the project")
        self.fits(1440)
        self.step("untick a file")
        b.click('.scan-step input[data-path="slides/pilot-deck.pptx"]', what="the deck's checkbox")
        b.wait("!!document.querySelector('.scan-unticked input[data-path=\"slides/pilot-deck.pptx\"]')",
               "the deck under Unticked by you")
        self.assertFalse(b.eval("document.querySelector('.scan-unticked input').checked"))
        self.assertEqual(b.eval("document.activeElement.dataset.path"), "slides/pilot-deck.pptx")   # focus kept
        self.step("390 px light")
        self.width(390)
        self.fits(390)
        self.check()                      # its screenshot, at 390 px
        self.step("confidential and dark")
        self.width(1440)
        b.click('label[for="np-confidential"]', what="Confidential: keep on local models")
        b.key("Escape", 27)
        b.wait("!document.querySelector('form.np-form')", "the dialog closed")
        self.theme("Dark")
        self.open_dialog(existing=True)
        b.click('label[for="np-confidential"]', what="Confidential: keep on local models")
        self.scan('[data-control="adopt_project"]', self.lobby)
        self.assertIn("Confidential: a role's model is hosted.",
                      b.eval("document.querySelector('.scan-step').innerText"))
        b.click('label[for="np-confidential"]', what="Confidential, off again")
        b.click('.scan-step input[data-path="slides/pilot-deck.pptx"]', what="the deck's checkbox")
        b.wait("!!document.querySelector('.scan-unticked')", "the deck unticked")
        dark = b.eval("getComputedStyle(document.querySelector('.scan-step')).backgroundColor")
        self.fits(1440)
        self.step("390 px dark")
        self.width(390)
        self.fits(390)
        self.check()
        self.width(1440)
        self.step("adopt")
        b.click("form.np-form button[type=submit]", text="Adopt the project", what="Adopt the project")
        b.wait("location.hash === '#/jobs'", "the Jobs page")
        args = self.runner.started[-1]
        self.assertEqual(args[:5], ["-m", "kernel.cli", "adopt", "Visitor register", "--source"])
        self.assertIn("--exclude=slides/pilot-deck.pptx", args)
        self.assertNotIn("--confidential", args)
        self.step("a folder of documents only")
        self.theme("Light")
        light = None
        self.open_dialog(existing=True)
        self.scan('[data-control="adopt_project"]', self.papers)
        b.wait("!!document.querySelector('.scan-nocode')", "the no-code notice")
        light = b.eval("getComputedStyle(document.querySelector('.scan-step')).backgroundColor")
        self.assertNotEqual(light, dark)
        self.assertTrue(b.eval("document.querySelector('form.np-form button[type=submit]').disabled"))
        b.click('[data-control="scan_as_material"]', text="Start a new project from it", what="Start a new project")
        b.wait("document.querySelector('[data-key=\"np-start:need\"]').getAttribute('aria-checked') === 'true'"
               " && document.querySelector('form.np-form button[type=submit]').textContent.trim()"
               " === 'Create and start the intake' && !!document.querySelector('.scan-read')", "the need path, scanned")
        self.step("create from the material")
        # nothing is assumed about the kind of work: unless a person picks one, the intake proposes it by rule
        self.assertEqual(b.eval("[...document.querySelectorAll('form.np-form .prof-card[aria-checked=\"true\"]')]"
                                ".map((c) => c.dataset.key)"), ["profile:auto", "posture:"])   # and no posture
        b.click("form.np-form button[type=submit]", text="Create and start the intake", what="Create")
        b.wait("location.hash.startsWith('#/p/')", "the new project")
        project = self.factory.projects()[-1]
        self.assertIsNone(project.meta.get("profile"))
        self.assertEqual(project.ledger().of_kind("profile_chosen"), [])
        scanned = project.ledger().of_kind("material_scanned")[-1]["event"]["payload"]
        self.assertEqual((scanned["person"], scanned["confirmed"]), (PERSON, "in the cockpit's scan step"))
        self.assertEqual(self.runner.started[-1][2:4], ["intake", project.pid])
        self.check()


if __name__ == "__main__":
    unittest.main()
