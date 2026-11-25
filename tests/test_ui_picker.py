"""FR-PICK1-AC-5: choose a project's folder by browsing, in a real browser (headless Chrome).

New project > An existing project > Browse here: the folder browser opens on the places (a root, the home folder,
the drives), the person walks into the root, sees the git badge and the folded tool folders, filters, moves with the
keyboard into a repository and chooses it: the folder fills the field and the scan starts at once. Then Browse…
(the computer's own dialog, through the RIHMA_PICK_COMMAND stand-in) fills another folder and scans it, and the
folder chosen is offered as a recent place. Light at 1440 px (a dialog) and dark at 390 px (a full-screen sheet):
nothing scrolls sideways, and there is no console error, failed request or CSP violation.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary).
"""

import contextlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import rpj_fixture as fx  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import pick as kpick  # noqa: E402
from kernel import pick_native as knative  # noqa: E402
from kernel.pick_native import PICK_ENV  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402
from kernel.store import Factory  # noqa: E402

SUBMIT = "form.np-form button[type=submit]"
DLG = "dialog.pick-dlg[open]"


class UiPickerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-pick-")).resolve()
        cls.code = cls.tmp / "code"
        cls.repo = fx.repo(cls.code / "ledger-helper", {"README.md": "# Ledger helper\n\nBalances the books.\n",
                                                         "app.py": "print('ledger')\n"})
        cls.vault = fx.notes(cls.code / "vault")
        for name in ("alpha", "node_modules", ".cache"):
            (cls.code / name).mkdir()
        (cls.tmp / "me").mkdir()
        cls.need = cls.tmp / "me" / "need.md"
        cls.need.write_text("# Need\n\nBook a desk.\n", encoding="utf-8")
        cls.many = cls.tmp / "me" / "many"
        for i in range(20):
            (cls.many / f"f{i:03d}").mkdir(parents=True)
        # the stand-in for the computer's own dialog: a file dialog chooses need.md; a folder dialog the vault, or
        # stays open (as one opened on a computer nobody sits at) while the "slow" flag is there
        cls.slow = cls.tmp / "slow"
        dialog = cls.tmp / "dialog.py"
        dialog.write_text(f"import os, sys, time\nif sys.argv[1] == 'file':\n    print({str(cls.need)!r})\n"
                          f"elif os.path.exists({str(cls.slow)!r}):\n    time.sleep(120)\nelse:\n    print({str(cls.vault)!r})\n",
                          encoding="utf-8")
        cls.patches = [mock.patch.dict(os.environ, {ROOTS_ENV: str(cls.code), PICK_ENV: json.dumps([sys.executable, str(dialog)])}),
                       mock.patch("pathlib.Path.home", return_value=cls.tmp / "me")]
        for p in cls.patches:
            p.start()
        cls.factory = Factory(cls.tmp / "home")
        cls.project = cls.factory.new_project("Unsorted work")   # past the first run: the page opens on Home
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

    # -- helpers (as tests/test_ui_real_projects.py) ----------------------------------------------------------

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
        self.shot(b.step)

    def shot(self, name: str) -> None:
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.browser.screenshot(self.shots / f"pick-{name.replace(' ', '-')}.png")

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
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000 if px > 500 else 844,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})
        self.browser.wait(f"window.innerWidth === {px}", f"a {px} px wide page")

    def theme(self, word: str) -> None:
        b = self.browser
        if b.eval("!!document.querySelector('form.np-form')"):
            b.key("Escape", 27)
            b.wait("!document.querySelector('form.np-form')", "the dialog closed")
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def dialog(self, title: str) -> None:
        b = self.browser
        b.eval("location.hash = '#/projects'; true")
        b.click('[data-control="new_project"]', text="New project", what="New project")
        b.wait("!!document.querySelector('form.np-form')", "the New project dialog")
        b.click('[data-key="np-start:existing"]', what="Start from: An existing project")
        b.type('form.np-form input[aria-label="Title"]', title)

    def fits(self, px: int, sel: str) -> None:
        sizes = self.browser.eval(f"""(() => {{ const f = document.querySelector({json.dumps(sel)});
            return {{page: document.documentElement.scrollWidth, box: f ? [f.scrollWidth, f.clientWidth] : [0, 0],
                     rect: f ? f.getBoundingClientRect().width : 0}}; }})()""")
        self.assertLessEqual(sizes["page"], px, sizes)
        self.assertLessEqual(sizes["box"][0], sizes["box"][1], sizes)
        # nothing inside sticks out of it or is scrolled sideways (a focused field can scroll a clipped box); a
        # focused text field scrolling its own long path to the caret is not the layout scrolling
        out = self.browser.eval(f"""(() => {{ const d = document.querySelector({json.dumps(sel)}); if (!d) return [];
            const r = d.getBoundingClientRect();
            return [...d.querySelectorAll('*')].filter((e) => e.getClientRects().length).filter((e) => {{
              const q = e.getBoundingClientRect();
              return (e.scrollLeft > 0 && e.tagName !== 'INPUT') || q.left < r.left - 1 || q.right > r.right + 1; }})
              .map((e) => e.tagName + '.' + e.className).slice(0, 5); }})()""")
        self.assertEqual(out, [], f"sticking out sideways at {px} px")
        return sizes

    def rows(self) -> list:
        return self.browser.eval(f"[...document.querySelectorAll('{DLG} .pick-list [role=option]')]"
                                 ".filter((e) => e.getClientRects().length).map((e) => e.getAttribute('aria-label'))")

    # -- the walk -----------------------------------------------------------------------------------------

    def test_FR_PICK1_AC_5_new_project_existing_browse_here_navigate_choose_and_the_scan_starts(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("Light")
        self.browse_here(1440)
        self.theme("Dark")
        self.browse_here(390)
        self.width(1440)
        self.native_browse()
        self.file_or_folder()
        self.step("done")
        self.assertEqual(b.problems, [])

    def browse_here(self, px: int) -> None:
        b = self.browser
        self.step(f"browse here {px}")
        self.dialog("Ledger helper")
        if px != 1440:
            self.width(px)
        b.eval("document.querySelector('form.np-form [data-control=\"pick_here\"]').scrollIntoView({block: 'center'}); true")
        self.fits(px, "form.np-form")
        self.shot(f"field-{px}")
        b.click('form.np-form [data-control="pick_here"]', what="Browse here")
        b.wait(f"!!document.querySelector('{DLG} .pick-place')", "the folder browser and its places")
        places = b.eval(f"[...document.querySelectorAll('{DLG} .pick-place')].map((e) => e.getAttribute('aria-label'))")
        self.assertIn(str(self.code), places)
        self.assertIn("Home", places)
        b.click(f'{DLG} .pick-place[data-path={json.dumps(str(self.code))}]', what="the root place")
        b.wait(f"[...document.querySelectorAll('{DLG} .pick-crumbs [aria-current]')].some((e) => e.textContent === 'code')",
               "the root listed")
        rows = self.rows()
        self.assertEqual([r.split(",")[0] for r in rows], ["alpha", "ledger-helper", "vault"])     # tool folders folded
        self.assertIn("git repository", next(r for r in rows if r.startswith("ledger-helper")))
        self.assertIn("Show 2 hidden or tool folders", b.eval(f"document.querySelector('{DLG} .pick-more').textContent"))
        self.assertTrue(b.eval(f"document.querySelector('{DLG} .pick-state').textContent.includes('may read this folder')"))
        self.fits(px, DLG)
        if px < 500:                                                      # a full-screen sheet at phone width
            self.assertEqual(b.eval(f"Math.round(document.querySelector('{DLG}').getBoundingClientRect().width)"), px)
        self.shot(f"listing-{px}")
        b.type(f"{DLG} .pick-q", "ledg")                                  # filter as you type
        b.wait(f"document.querySelectorAll('{DLG} .pick-list [role=option]').length === 1", "the filtered list")
        b.key("ArrowDown", 40)                                            # into the list, then Enter opens the folder
        b.wait(f"document.activeElement && document.activeElement.matches('{DLG} [role=option]')", "a focused folder")
        b.key("Enter", 13)
        b.wait(f"[...document.querySelectorAll('{DLG} .pick-crumbs [aria-current]')].some((e) => e.textContent === 'ledger-helper')",
               "the repository opened by the keyboard")
        b.wait(f"!!(document.activeElement && document.activeElement.closest('{DLG} .pick-list'))",
               "the focus kept in the list after opening a folder with the keyboard")
        self.assertEqual(b.eval(f"document.querySelector('{DLG} .pick-sel').textContent"), str(self.repo))
        self.fits(px, DLG)
        self.shot(f"inside-{px}")
        b.click(f'{DLG} [data-control="pick_choose"]', what="Choose this folder")
        b.wait(f"!document.querySelector('{DLG}')", "the folder browser closed")
        self.assertEqual(b.eval("document.querySelector('[data-control=\"adopt_project\"]').value"), str(self.repo))
        self.assertTrue(b.eval("document.activeElement === document.querySelector('[data-control=\"adopt_project\"]')"),
                        f"the focus after Choose went to {b.active()}, not back to the field")
        b.wait("!!document.querySelector('.scan-step:not([hidden]) .scan-group')", "the scan, started at once")
        b.wait(f"document.querySelector('{SUBMIT}').textContent.trim() === 'Adopt the project'", "Adopt the project")
        self.fits(px, "form.np-form")
        self.shot(f"scanned-{px}")
        b.key("Escape", 27)
        b.wait("!document.querySelector('form.np-form')", "the New project dialog closed")
        if px != 1440:
            self.width(1440)

    def file_or_folder(self) -> None:
        """Add material takes a file or a folder: File… and Folder…, a dialog nobody sees, and a long folder."""
        b = self.browser
        self.step("add material")
        if b.eval("!!document.querySelector('form.np-form')"):
            b.key("Escape", 27)
            b.wait("!document.querySelector('form.np-form')", "the New project dialog closed")
        b.eval(f"location.hash = '#/p/{self.project.pid}/overview'; true")
        b.click('[data-control="project_settings"]', what="Project settings")
        b.click('[data-key="ps-material"]', what="Add material")
        b.wait("!!document.querySelector('#modal[open] #mt-path')", "Add material's path field")
        field = "#modal .pick-field:has(#mt-path)"
        labels = b.eval(f"[...document.querySelectorAll('{field} [data-control=pick_browse]')].map((e) => e.textContent.trim())")
        self.assertEqual(labels, ["File…", "Folder…"])                     # the computer's dialog picks one or the other
        self.step("a file by the computer's own dialog")
        b.click(f'{field} [data-control="pick_browse"][data-kind="file"]', what="File…")
        b.wait(f"document.querySelector('#mt-path').value === {json.dumps(str(self.need))}", "need.md, chosen in a file dialog")
        b.wait("document.activeElement === document.querySelector('#mt-path')", "the focus back on the field")
        self.step("a dialog where nobody sits")
        self.slow.write_text("1", encoding="utf-8")
        self.addCleanup(lambda: self.slow.unlink(missing_ok=True))
        b.click(f'{field} [data-control="pick_browse"][data-kind="folder"]', what="Folder…")
        said = b.wait("(document.querySelector('.pick-wait') || {}).textContent", "where the dialog opened")
        self.assertIn(socket.gethostname(), said)
        self.assertIn("SSH tunnel", said)
        end = time.monotonic() + 10
        while not knative.busy() and time.monotonic() < end:
            time.sleep(0.05)
        self.assertTrue(knative.busy())
        b.click(".pick-wait .pick-instead", what="Browse here instead")
        b.wait(f"!!document.querySelector('{DLG}') && !document.querySelector('.pick-wait')", "the folder browser instead")
        end = time.monotonic() + 10
        while knative.busy() and time.monotonic() < end:
            time.sleep(0.05)
        self.assertFalse(knative.busy(), "the dialog nobody sees was not closed")
        b.key("Escape", 27)
        b.wait(f"!document.querySelector('{DLG}')", "the folder browser closed")
        self.long_folder(field)

    def long_folder(self, field: str) -> None:
        b = self.browser
        self.step("a long folder")
        b.type("#mt-path", str(self.many))
        cap = mock.patch.object(kpick, "MAX_ROWS", 5)
        cap.start()
        self.addCleanup(cap.stop)
        b.click(f'{field} [data-control="pick_here"]', what="Browse here")
        b.wait(f"[...document.querySelectorAll('{DLG} .pick-crumbs [aria-current]')].some((e) => e.textContent === 'many')", "many")
        self.assertEqual(len(self.rows()), 5)
        self.assertIn("15 more not shown: type in the filter", b.eval(f"document.querySelector('{DLG} .pick-more').textContent"))
        b.type(f"{DLG} .pick-q", "f018")                                  # past the first five: found on the server
        b.wait(f"document.querySelectorAll('{DLG} .pick-list [role=option]:not([aria-disabled])').length === 1", "f018, found")
        self.assertEqual([r.split(",")[0] for r in self.rows()], ["f018"])
        b.key("ArrowDown", 40)
        b.key("Enter", 13)
        b.wait(f"[...document.querySelectorAll('{DLG} .pick-crumbs [aria-current]')].some((e) => e.textContent === 'f018')", "f018 opened")
        b.wait(f"!!(document.activeElement && document.activeElement.closest('{DLG} .pick-list'))", "the focus in the list")
        b.key("Backspace", 8)                                            # up again, and the focus stays in the list
        b.wait(f"[...document.querySelectorAll('{DLG} .pick-crumbs [aria-current]')].some((e) => e.textContent === 'many')", "many again")
        b.wait(f"document.activeElement && document.activeElement.matches('{DLG} .pick-list [role=option]')", "a focused folder")
        b.click(f'{DLG} [data-control="pick_choose"]', what="Choose this folder")
        b.wait(f"document.querySelector('#mt-path').value === {json.dumps(str(self.many))}", "many, chosen")
        b.wait("document.activeElement === document.querySelector('#mt-path')", "the focus back on the field")

    def native_browse(self) -> None:
        b = self.browser
        self.step("browse native")
        self.dialog("Vault")
        b.click('form.np-form [data-control="pick_browse"]', what="Browse…")
        b.wait(f"document.querySelector('[data-control=\"adopt_project\"]').value === {json.dumps(str(self.vault))}",
               "the folder the computer's own dialog chose")
        b.wait("!!document.querySelector('.scan-step:not([hidden]) .scan-group') && "
               "document.querySelector('.scan-step').textContent.includes('.obsidian/app.json')",
               "the scan of the chosen folder")
        b.key("Escape", 27)
        b.wait("!document.querySelector('form.np-form')", "the New project dialog closed")
        self.dialog("Again")
        b.click('form.np-form [data-control="pick_here"]', what="Browse here")
        b.wait(f"!!document.querySelector('{DLG} .pick-place')", "the places")
        recent = b.eval(f"[...document.querySelectorAll('{DLG} .pick-place')].map((e) => e.getAttribute('aria-label'))")
        self.assertIn("Recent: ledger-helper", recent)                   # chosen before: offered first
        b.key("Escape", 27)
        b.wait(f"!document.querySelector('{DLG}')", "the folder browser closed")
        self.assertTrue(b.eval("!!document.querySelector('form.np-form')"))   # Escape closed only the browser


if __name__ == "__main__":
    unittest.main()
