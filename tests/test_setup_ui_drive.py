"""FR-SET1-AC-9: Set up this project, suggested and described automations, and archiving, in a real browser
(headless Chrome over the DevTools protocol, as tests/test_ui_drive.py).

A developer opens an attached project's Overview and does the first item of Set up this project with one click
(the secret scan enabled, signed), sets up a suggested automation on its Automations tab, describes one in words
("every night run the tests and tell me on Teams if they fail") and sets it up from its summary, archives a
duplicate from Projects, restores it, archives it again from its Project settings, and removes it after typing
its id. Dark and light, at 1440 and 390 pixels. After every step there is no console error, failed request or
Content-Security-Policy violation, every control has a name, and nothing is wider than the screen. Skipped when
Chrome or git is not installed.
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

from alignment_fixture import make_repo  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402
from test_ui_shape_models import NAMELESS, OVERFLOW  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
SAID = "every night run the tests and tell me on Teams if they fail"
CONFIGS = (("dark", "Dark", 1440), ("light", "Light", 390), ("dark", "Dark", 390), ("light", "Light", 1440))


class SetupUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for the attached repository")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def world(self, tmp: Path) -> None:
        self.factory = Factory(tmp / "home")
        self.repo = attach(self.factory, "Tool store", repo=make_repo(tmp / "repo"), person="Aino Example",
                           persona="developer")
        self.keep = self.factory.new_project("Loans", maturity="demo", mode="mixed")
        self.keep.log("note", {"text": "the one with more records stays"})
        self.copy = self.factory.new_project("Loans", maturity="demo", mode="mixed")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))

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
            b.screenshot(self.shots / f"setup-{b.step.replace(' ', '-')}.png")

    def go(self, hash_: str, ready: str, what: str) -> None:
        self.browser.eval(f"location.hash = {json.dumps(hash_)}; true")
        self.browser.wait(ready, what)

    def sign_in(self, mode: str, label: str, width: int) -> None:
        b = self.browser
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1,
                                                      "mobile": False})
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")
        if width != 1440:                          # the theme is chosen wide; then the screen narrows
            b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 844, "deviceScaleFactor": 1,
                                                          "mobile": True})
            b.wait(f"window.innerWidth === {width}", "the narrow screen")
            time.sleep(0.3)

    def flow(self, mode: str, label: str, width: int) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-setup-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.world(tmp)
        self.browser = Browser(self.chrome, tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        b, pid, copy = self.browser, self.repo.pid, self.copy.pid
        self.step(f"sign in {mode} {width}")
        self.sign_in(mode, label, width)
        self.step(f"set up {mode} {width}")
        self.go(f"#/p/{pid}/overview", "!!document.querySelector('[data-key=\"setup:checks\"]')", "Set up this project")
        b.click('[data-key="setup:checks"]', what="the checks item's one click")
        b.wait("(document.querySelector('[data-key=\"setup-item:checks\"]') || {dataset: {}}).dataset.state === 'set_up'",
               "the checks item set up")
        self.assertEqual(cstore.enabled(self.repo)["secrets"]["by"]["person"], PERSON)
        self.step(f"suggested {mode} {width}")
        self.go(f"#/p/{pid}/automations", "!!document.querySelector('[data-key=\"sug-ok:nightly_gate\"]')",
                "the suggestions")
        b.click('[data-key="sug-ok:nightly_gate"]', what="Set it up on the nightly gate")
        b.wait("(document.querySelector('[data-key=\"sug:nightly_gate\"]') || {dataset: {}}).dataset.state === 'set_up'",
               "the suggestion set up")
        self.step(f"describe it {mode} {width}")
        b.type("#amn-describe", SAID)
        b.click('[data-key="amn-describe-go"]', what="Read it")
        b.wait("(document.querySelector('#amn-describe-summary') || {textContent: ''}).textContent"
               ".includes('Every night at 02:00 UTC')", "the draft's summary")
        b.click('[data-key="amn-describe-save"]', what="Set it up from the summary")
        b.wait("!!document.querySelector('[data-key=\"auto:AU-002\"]')", "the described one set, in the list")
        made = au.automations(self.factory)
        self.assertEqual([(a["action"]["kind"], a["owner"]["person"]) for a in made],
                         [("gate", PERSON), ("command", PERSON)])
        self.archive_and_remove(mode, width, copy)

    def archive_and_remove(self, mode: str, width: int, copy: str) -> None:
        b = self.browser
        self.step(f"archive a duplicate {mode} {width}")
        self.go("#/projects", f"!!document.querySelector('[data-key=\"dup-archive:{copy}\"]')", "the duplicates")
        b.click(f'[data-key="dup-archive:{copy}"]', what="Archive this copy")
        b.wait(f"!!document.querySelector('[data-key=\"arc-restore:{copy}\"]')", "the copy archived")
        self.assertNotIn(copy, [p.pid for p in self.factory.projects()])
        self.step(f"restore {mode} {width}")
        b.click(f'[data-key="arc-restore:{copy}"]', what="Restore")
        b.wait(f"!document.querySelector('[data-key=\"arc:{copy}\"]')", "the copy restored")
        self.assertIn(copy, [p.pid for p in self.factory.projects()])
        self.step(f"archive from settings {mode} {width}")
        self.go(f"#/p/{copy}/overview", "!!document.querySelector('[data-key=\"project-settings\"]')", "the copy")
        b.click('[data-key="project-settings"]', what="Project settings")
        b.click('[data-key="ps-archive"]', what="Archive this project")
        b.type("#ar-reason", "a duplicate of Loans")
        b.click('[data-key="ar-go"]', what="Archive")
        b.wait(f"location.hash === '#/projects' && !!document.querySelector('[data-key=\"arc-remove:{copy}\"]')",
               "Projects, with the copy archived")
        self.step(f"remove {mode} {width}")
        b.click(f'[data-key="arc-remove:{copy}"]', what="Remove")
        b.type("#rm-confirm", copy)
        b.click('[data-key="rm-go"]', what="Remove for good")
        b.wait(f"!document.querySelector('#modal').open && !document.querySelector('[data-key=\"arc:{copy}\"]')",
               "the copy removed")
        self.assertFalse((self.factory.projects_dir / copy).exists())
        self.assertEqual(len(list((self.factory.home / "exports" / "removed").glob(f"{copy}-*.zip"))), 1)
        self.check()

    def test_FR_SET1_AC_9_set_up_suggest_describe_archive_and_remove_in_chrome_dark_and_light_wide_and_narrow(self):
        for mode, label, width in CONFIGS:
            with self.subTest(mode=mode, width=width):
                self.flow(mode, label, width)


if __name__ == "__main__":
    unittest.main()
