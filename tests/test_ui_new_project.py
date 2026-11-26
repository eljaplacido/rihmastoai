"""New project's parts working together, and the posture in Project settings, in a real browser
(headless Chrome over the DevTools protocol).

The dialog has Start from (A need or a spec, An existing project, Shape it in chat), the folder scan
step, Confidential and the postures' How it runs. No posture is chosen until a person picks one; How it
runs shows for a need and for an existing project and hides for Shape it in chat. A need given as a
folder is scanned first and then created with the posture the person picked; an existing project is
adopted with its posture. In a project, Project settings shows the posture's chip, which opens the
Posture dialog, and a maturity change's impact says that it tightens the posture. Light and dark, 1440
and 390 px: nothing scrolls sideways, and no console error, failed request or CSP violation.

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

from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402
from kernel.store import Factory  # noqa: E402

SECTION = ".pst-section"
SHOWN = "(() => { const s = document.querySelector('form.np-form .pst-section'); return !!s && !!s.getClientRects().length; })()"
FITS = ("(() => { const d = document.querySelector('#modal .modal-in');"
        " return document.documentElement.scrollWidth <= window.innerWidth"
        " && (!d || (d.scrollWidth <= d.clientWidth && d.getBoundingClientRect().right <= window.innerWidth + 1)); })()")


class UiNewProjectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-new-project-")).resolve()
        cls.patch = mock.patch.dict(os.environ, {ROOTS_ENV: str(cls.tmp)})
        cls.patch.start()
        cls.papers = cls.tmp / "papers"
        cls.papers.mkdir()
        (cls.papers / "README.md").write_text("# Tool loans\n\nWe lend drills and laptops and lose track of them.\n",
                                              encoding="utf-8")
        cls.code = cls.tmp / "orders"
        cls.code.mkdir()
        (cls.code / "README.md").write_text("# Orders\n\nA small order service.\n", encoding="utf-8")
        (cls.code / "app.py").write_text("print('orders')\n", encoding="utf-8")
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
        cls.patch.stop()
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
            b.screenshot(self.shots / f"new-project-{b.step.replace(' ', '-')}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000 if px > 500 else 900,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})
        self.browser.wait(f"window.innerWidth === {px}", f"a {px} px wide page")

    def theme(self, word: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-business_owner"]', what="the business owner persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def open_dialog(self, title: str) -> None:
        b = self.browser
        b.eval("location.hash = '#/projects'; true")
        b.click('[data-control="new_project"]', text="New project", what="New project")
        b.wait("!!document.querySelector('form.np-form')", "the New project dialog")
        b.type('form.np-form input[aria-label="Title"]', title)

    def start_from(self, key: str) -> None:
        self.browser.click(f'[data-key="np-start:{key}"]', what=f"Start from: {key}")

    def preview_says(self, text: str) -> str:
        return self.browser.wait(f"(() => {{ const t = (document.querySelector('{SECTION} .pst-out') || {{}}).textContent || '';"
                                 f" return t.includes({json.dumps(text)}) && t; }})()", f"the preview saying {text}")

    def scan_and_submit(self, field: str, folder: Path, then: str) -> None:
        b = self.browser
        b.type(field, str(folder))
        b.wait("document.querySelector('form.np-form button[type=submit]').textContent.trim() === 'Scan the folder'",
               "the submit button asking to scan first")
        b.click("form.np-form button[type=submit]", what="Scan the folder")
        b.wait("!!document.querySelector('.scan-step:not([hidden]) .scan-group')", "the material map")
        b.wait(f"document.querySelector('form.np-form button[type=submit]').textContent.trim() === {json.dumps(then)}",
               f"the submit button saying {then}")
        b.click("form.np-form button[type=submit]", what=then)

    def test_new_project_start_from_scan_confidential_and_how_it_runs_work_together(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("Dark")
        self.step("the dialog's parts")
        self.open_dialog("Tool loans")
        self.assertEqual(b.eval("[...document.querySelectorAll('[data-key^=\"np-start:\"]')].map((x) => x.textContent.trim())"),
                         ["A need or a spec", "An existing project", "Shape it in chat"])
        b.wait(f"!!document.querySelector('{SECTION} [data-key=\"posture:\"][aria-checked=\"true\"]')",
               "No posture chosen by default")
        self.preview_says("No posture")
        self.assertTrue(b.eval(SHOWN))
        self.assertTrue(b.eval("!!document.querySelector('#np-confidential').getClientRects().length"))
        self.assertTrue(b.eval(FITS))
        self.step("an existing project shows how it runs")
        self.start_from("existing")
        self.assertTrue(b.eval(SHOWN))
        self.assertTrue(b.eval("!!document.querySelector('[data-control=\"adopt_project\"]').getClientRects().length"))
        self.step("shape it in chat hides it")
        self.start_from("chat")
        self.assertFalse(b.eval(SHOWN))
        self.assertFalse(b.eval("!!document.querySelector('#np-confidential').getClientRects().length"))
        self.assertTrue(b.eval("!!document.querySelector('[data-control=\"shape_open\"]').getClientRects().length"))
        self.step("a need from a folder with Balanced")
        self.start_from("need")
        self.assertTrue(b.eval(SHOWN))
        b.click(f'{SECTION} [data-key="posture:balanced"]', what="Balanced")
        self.preview_says("What Balanced will do")
        self.width(390)
        b.wait(FITS, "the dialog within 390 pixels")
        self.width(1440)
        self.scan_and_submit('textarea[aria-label="The need"]', self.papers, "Create and start the intake")
        b.wait("location.hash.startsWith('#/p/')", "the new project")
        project = next(p for p in self.factory.projects() if p.meta.get("title") == "Tool loans")
        self.assertEqual((project.meta["posture"]["name"], project.meta["posture"]["chosen_by"]), ("balanced", PERSON))
        self.assertTrue(project.path("material.json").exists())                    # the scan step's map, kept
        self.assertEqual(self.runner.started[-1][:4], ["-m", "kernel.cli", "intake", project.pid])

        self.step("adopt with a posture")
        self.theme("Light")
        self.open_dialog("Orders")
        self.start_from("existing")
        b.click(f'{SECTION} [data-key="posture:production"]', what="Production")
        self.preview_says("What Production will do")
        self.scan_and_submit('[data-control="adopt_project"]', self.code, "Adopt the project")
        b.wait("location.hash === '#/jobs'", "the jobs page")
        args = self.runner.started[-1]
        self.assertEqual(args[:3], ["-m", "kernel.cli", "adopt"])
        self.assertEqual(args[args.index("--posture") + 1], "production")
        self.assertEqual(args[args.index("--maturity") + 1], "production")         # Production's own maturity

        self.step("the posture in project settings")
        b.eval(f"location.hash = '#/p/{project.pid}/overview'; true")
        b.click('[data-control="project_settings"]', what="Project settings")
        b.wait("!!document.querySelector('#modal [data-slot=\"posture\"] .pst-chip')", "the posture's chip in settings")
        self.assertEqual(b.eval("document.querySelector('#modal [data-slot=\"posture\"] .pst-chip').textContent"),
                         "Working rules: Balanced")   # the posture, in a business owner's words (words.js)
        b.eval("document.querySelector('#ps-maturity').value = 'pilot';"
               " document.querySelector('#ps-maturity').dispatchEvent(new Event('change')); true")
        b.click('[data-key="ps-preview"]', what="Preview the impact")
        said = b.wait("(document.querySelector('#ps-impact [data-what=\"posture\"]') || {}).textContent",
                      "the posture's line in the impact")
        self.assertIn("This also tightens the Balanced posture: maturity demo to pilot", said)
        self.width(390)
        b.wait(FITS, "the settings within 390 pixels")
        self.width(1440)
        b.click('#modal [data-slot="posture"] .pst-chip', what="the posture's chip")
        b.wait("document.querySelector('#modal').open && document.querySelector('#modal-h').textContent.startsWith('Posture')",
               "the Posture dialog in place of the settings")
        self.assertIn("Change the posture", b.eval("document.querySelector('#modal').textContent"))
        self.check()


if __name__ == "__main__":
    unittest.main()
