"""FR-WLK1 in a real browser (headless Chrome over the DevTools protocol, tests/test_ui_drive.py): Plug in an
existing project, started from Home's first-run card, done in the Ask Rihma chat.

A person types the folder's path into the chat and sees the scan's counts there (with the AI-tool setup that
was found), answers with the option buttons (the keyboard's focus moves to them), presses Adopt, and the chat
waits on the real adoption job (the cockpit's own job runner) with its progress, then shows the result with
What's next and Open the project. Home's header carries Walkthroughs too. Dark and light, 1440 and 390 px:
nothing scrolls sideways, and no console error, failed request or CSP violation.

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

from test_ui_drive import PERSON, Browser, find_chrome  # noqa: E402
from test_walkthrough import code_folder  # noqa: E402

from cockpit.server import SubprocessRunner, make_server  # noqa: E402
from kernel import modules  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402
from kernel.store import Factory  # noqa: E402

FITS = ("(() => { const log = document.querySelector('#as-log');"
        " return document.documentElement.scrollWidth <= window.innerWidth"
        " && (!log || log.scrollWidth <= log.clientWidth + 1); })()")
LAST = "(() => { const m = [...document.querySelectorAll('#as-log .msg.bot')].pop(); return m ? m.textContent : ''; })()"


class UiWalkthroughTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-walk-")).resolve()
        cls.patch = mock.patch.dict(os.environ, {ROOTS_ENV: str(cls.tmp)})
        cls.patch.start()
        cls.repo = code_folder(cls.tmp / "orders", repo=True)
        cls.factory = Factory(cls.tmp / "home")
        modules.set_modules(cls.factory, person=PERSON, persona="it", preset="full")   # chosen: no first-run dialog
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=SubprocessRunner(cls.factory.home))
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
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
        self.assertTrue(b.eval(FITS), f"something scrolls sideways during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"walkthrough-{b.step.replace(' ', '-')}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000 if px > 500 else 900,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})
        self.browser.wait(f"window.innerWidth === {px}", f"a {px} px wide page")

    def theme(self, word: str) -> None:
        b = self.browser
        b.eval("document.querySelector('#assistant').hidden || document.querySelector('#as-close').click(); true")
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def sign_in(self, persona: str = "developer") -> None:
        """Sign in and say who decides: a persona that may have the cockpit read a folder."""
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.server.issue_link()}"})   # one link a test
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def says(self, text: str, timeout: float = 20.0) -> str:
        return self.browser.wait(f"(() => {{ const t = {LAST}; return t.includes({json.dumps(text)}) && t; }})()",
                                 f"Rihma saying {text}", timeout)

    def option(self, oid: str, what: str) -> None:
        sel = f'#as-log .msg.bot:last-of-type [data-key$=":opt:{oid}"]'
        self.browser.wait(f"!!document.querySelector({json.dumps(sel)}) && !document.querySelector({json.dumps(sel)}).disabled",
                          what)
        self.browser.click(sel, what=what)

    def test_FR_WLK1_AC_9_plug_in_an_existing_project_from_home_in_the_chat(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("Dark")
        self.step("home offers walkthroughs")
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('.page-head [data-control=\"walkthroughs\"]')", "Walkthroughs on Home's header")
        b.wait("!!document.querySelector('#home-walk [data-key=\"wk-start:home:plug_in\"]')", "the first-run card")
        b.click('#home-walk [data-key="wk-start:home:plug_in"]', what="Plug in an existing project")
        self.says("Which project?")
        self.step("the folder, typed into the chat")
        b.type("#as-q", str(self.repo))
        b.key("Enter", 13)
        said = b.wait("(() => { const t = document.querySelector('#as-log').textContent;"
                      " return t.includes('I scanned it') && t; })()", "the scan's summary in the chat")
        self.assertIn("AI-tool setup found: AGENTS.md", said)
        self.assertIn("Skipped as secret-looking, never opened or sent: .env", said)
        self.assertTrue(b.eval("!!document.querySelector('#as-log .wk-scan')"))
        self.assertTrue(b.eval("!!document.querySelector('#as-log [data-key$=\":map\"]')"))      # See the full map
        b.wait("(document.activeElement.getAttribute('data-key') || '').includes(':opt:')", "the focus on an option")
        self.step("the answers, with the buttons")
        self.option("default", "the title")
        self.says("confidential")
        self.option("no", "No, not confidential")
        self.says("What should Rihmasto do with it?")
        self.option("maintain", "Maintain")
        self.says("Which posture?")
        self.width(390)
        self.check()
        self.width(1440)
        self.option("none", "No posture")
        b.wait("!!document.querySelector('#as-log .msg.bot:last-of-type [data-key$=\":confirm\"]')", "the Adopt button")
        self.assertEqual([p.pid for p in self.factory.projects()], ["_factory"])       # nothing before Adopt
        self.step("adopt, and wait in the chat")
        b.click('#as-log .msg.bot:last-of-type [data-key$=":confirm"]', what="Adopt Orders")
        b.wait("document.querySelector('#as-log').textContent.includes('Adopting. I show the progress here')",
               "the chat waiting on the job")
        said = b.wait("(() => { const t = document.querySelector('#as-log').textContent;"
                      " return t.includes('Orders is adopted') && t; })()", "the adoption's result in the chat", 240)
        self.assertIn("Its baseline: passed", said)
        self.assertIn("What's next:", said)
        self.assertTrue(b.eval("[...document.querySelectorAll('#as-log .msg.bot button')]"
                               ".some((x) => x.textContent.includes('Open the project'))"))
        project = next(p for p in self.factory.projects() if p.pid != "_factory")
        self.assertEqual((project.meta["intent"], project.meta["title"]), ("maintain", "Orders"))
        self.step("narrow and light")
        self.width(390)
        b.wait("!document.querySelector('#assistant').hidden", "the chat at 390 px")
        self.check()
        self.width(1440)
        self.theme("Light")
        b.click("#assistant-fab", what="Ask Rihma")
        b.wait("!!document.querySelector('#as-log .wk')", "the walkthrough in the chat")
        self.check()
        self.width(390)
        b.wait("!!document.querySelector('#as-log .wk') && !document.querySelector('#assistant').hidden",
               "the walkthrough in the chat at 390 px, light")
        self.check()
        self.width(1440)
        self.step("open the project")
        b.click("#as-log .msg.bot button", text="Open the project", what="Open the project")
        b.wait(f"location.hash.startsWith('#/p/{project.pid}')", "the new project")
        self.check()

    def test_FR_WLK1_AC_9_the_tour_from_the_chat_s_walkthroughs_takes_you_to_each_stop(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.step("the walkthroughs in the chat")
        b.click("#assistant-fab", what="Ask Rihma")
        b.click("#as-walk", what="Walkthroughs in the chat's header")
        b.wait("!!document.querySelector('#as-log [data-control=\"walk_tour\"]')", "the walkthroughs listed")
        b.click('#as-log [data-control="walk_tour"]', what="Get started")
        self.says("1 of 5")
        b.wait("location.hash === '#/home'", "Home, the first stop")
        hashes = []
        for n in range(2, 6):
            self.option("next", f"Next to stop {n}")
            self.says(f"{n} of 5")
            time.sleep(0.4)
            hashes.append(b.eval("location.hash"))
        self.assertEqual(hashes[0], "#/inbox")
        self.assertTrue(hashes[1].startswith(("#/p/", "#/projects")), hashes)
        self.option("next", "Finish")
        self.says("That is the tour")
        self.check()


if __name__ == "__main__":
    unittest.main()
