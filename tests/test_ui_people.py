"""Just me or a team, in a real browser (FR-PPL1): headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py drives it.

A new home's first visit asks who works here. "Just me": the person names themselves once, the person chip says
"Viewing as: everything", and the Inbox shows cards that need different personas, each saying which persona the
person decides it as; deciding the deploy gate is recorded as IT without switching. "A team": team mode turns on,
the tab stays signed in as the first user, and Settings, People and access says so in plain words, adds a person
and makes their one-use invite link. Dark and light, 1440 and 390 pixels wide: nothing spills sideways, every
control of the dialog and the card has a name, and no step leaves a console error, a failed request or a
Content-Security-Policy violation behind.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary).
``RIHMA_UI_SHOTS=<folder>`` also saves a screenshot per step.
"""

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

from cockpit.server import make_server  # noqa: E402
from kernel import team as kteam  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
NAMELESS = """(() => [...document.querySelectorAll(
  '#modal :is(button, a[href], input, select, textarea), .ppl-card :is(button, a[href], input, select, textarea)')]
  .filter((el) => el.getClientRects().length).filter((el) => {
    const label = (el.labels ? [...el.labels].map((l) => l.textContent).join(' ') : '') || el.getAttribute('aria-label') || '';
    const own = /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) ? '' : el.textContent;
    return !(label + own).trim(); }).map((el) => el.outerHTML.slice(0, 120)))()"""
SPILL = "document.documentElement.scrollWidth - window.innerWidth"


class UiPeopleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def start(self, width: int, mode: str) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-people-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome", width=width, height=900 if width > 600 else 800)
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.label = f"{width}-{mode}"
        if width < 600:
            self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 800,
                                                                    "deviceScaleFactor": 1, "mobile": True})
        self.browser.cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": f"try {{ localStorage.setItem('gf.theme', JSON.stringify({{mode: '{mode}'}})); }} catch (e) {{}}"})

    def step(self, name: str) -> None:
        if self.browser.step != "start":
            self.check()
        self.browser.step = name

    def check(self) -> None:
        b = self.browser
        b.eval("1")
        time.sleep(0.3)
        b.eval("1")
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}' ({self.label})")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}' ({self.label})")
        self.assertEqual(b.eval(NAMELESS), [], f"controls with no accessible name during '{b.step}' ({self.label})")
        self.assertLessEqual(b.eval(SPILL), 0, f"the page spills sideways during '{b.step}' ({self.label})")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"people-{self.label}-{b.step.replace(' ', '-')}.png")

    def first_run(self, choice: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!!document.querySelector('#modal[open] .fr-mode')", "the first-run choice with Who works here")
        self.assertEqual(b.eval("document.querySelector('#fr-mode-solo').checked"), True)     # Just me by default
        self.assertEqual(b.eval("document.querySelector('.fr-mode legend').textContent"), "Who works here")
        b.type("#fr-name", PERSON)
        if choice == "team":
            b.click('label[for="fr-mode-team"]', what="A team or an organisation")
            b.wait("document.querySelector('#fr-mode-d').textContent.includes('You become the first user')",
                   "what team mode means")
        self.check()
        b.click("#modal button", text="Start with this", what="Start with this")
        b.wait("!document.querySelector('#modal').open", "the dialog closed")

    def cards(self):
        p = self.factory.new_project("Equipment loans", mode="assume", maturity="explore")
        canon = Canon(p)
        return p, {k: canon.card(k, t)["id"] for k, t in (("change", "Show overdue loans first"),
                                                         ("deploy_gate", "Open production for release 1"))}

    def just_me(self, width: int, mode: str) -> None:
        self.start(width, mode)
        b = self.browser
        self.step("first run, just me")
        self.first_run("solo")
        self.assertEqual(kteam.solo_name(self.factory), PERSON)
        b.wait("document.querySelector('#pc-persona').textContent === 'Viewing as: everything'", "Viewing as: everything")
        p, made = self.cards()
        self.step("the inbox through every persona")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/inbox"})
        b.wait(f"!!document.querySelector('[data-id=\"{made['deploy_gate']}\"] .ib-as')", "the deploy gate's persona chip")
        chip = b.eval(f"document.querySelector('[data-id=\"{made['deploy_gate']}\"] .ib-as').textContent")
        self.assertEqual(chip, "You decide as it / partner")
        key = f"ib-{p.pid}-{made['deploy_gate']}:approve"
        b.click(f'[data-key="{key}"]', what="Approve the deploy gate")
        b.click(f'[data-key="{key.rsplit(":", 1)[0]}:confirm"]', what="Confirm: approve")   # choose, then confirm
        b.wait(f"!document.querySelector('[data-id=\"{made['deploy_gate']}\"]')", "the card decided and gone")
        decided = Canon(p).decisions()[-1]
        self.assertEqual((decided["person"], decided["persona"]), (PERSON, "it"))
        self.step("settings in solo mode")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/settings"})
        b.wait("(document.querySelector('.ppl-now') || {}).textContent", "People and access")
        self.assertTrue(b.eval("document.querySelector('.ppl-now').textContent").startswith("Solo mode. Just you"))
        self.check()

    def a_team(self, width: int, mode: str) -> None:
        self.start(width, mode)
        b = self.browser
        self.step("first run, a team")
        self.first_run("team")
        self.assertEqual(kteam.mode(self.factory), "team")
        self.step("settings in team mode")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/settings"})
        b.wait("((document.querySelector('.ppl-now') || {}).textContent || '').startsWith('Team mode.')",
               "Settings says team mode")
        self.assertIn(PERSON, b.eval("document.querySelector('.ppl-card .emb-list').textContent"))
        self.step("add a person and invite them")
        b.type("#ppl-new-name", "Bea Example")
        b.click('[data-key="people:add"]', what="Add the user")
        b.wait("document.querySelector('.ppl-card .emb-list').textContent.includes('Bea Example')", "Bea in the list")
        b.click('[data-key="user:U-002:link"]', what="Invite link for Bea")
        url = b.wait("(document.querySelector('#ppl-link-url') || {}).value", "the one-use link")
        self.assertIn("/#k=", url)
        self.assertNotIn(url.rpartition("#k=")[2], kteam.path(self.factory).read_text(encoding="utf-8"))
        self.check()

    def test_FR_PPL1_AC_7_just_me_at_1440_dark_and_390_light(self):
        self.just_me(1440, "dark")
        self.doCleanups()
        self.just_me(390, "light")

    def test_FR_PPL1_AC_7_a_team_at_390_dark_and_1440_light(self):
        self.a_team(390, "dark")
        self.doCleanups()
        self.a_team(1440, "light")


if __name__ == "__main__":
    unittest.main()
