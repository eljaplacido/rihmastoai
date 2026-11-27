"""What the developer acceptance test (2026-11-26) found in the browser, fixed and kept fixed: headless Chrome over the
DevTools protocol (tests/test_ui_drive.py) on a copy of the demo home (tests/acc_fakes.py).

- the briefing's next step that waits on another persona says who, offers Nudge them and Switch to the persona, and
  never "Nothing waits on a decision"; a note about a card not in the view leaves with the view;
- Everything mode: the project Inbox holds every card the person may decide with the change batch bar, and the Inbox
  across projects has the batch bar too; an update card reads as a sentence, its payload under Details;
- the board's filters are per project and say how many cards they hide, with Clear;
- the hand-off dialog says an unknown change in words and keeps the brief; Ask Rihma's "hand off T-002 to Claude Code"
  opens it with both chosen; "generate an automation ..." lands in Describe it, read;
- the assessment's Select buttons replace what is ticked;
- at 390 px the theme is in the person menu and Settings fits the screen;
- the Board shows the epics above the lanes, and a product owner creates one there.

No step leaves a console error, a failed request or a CSP violation. Skipped when Chrome or git is missing.
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from acc_fakes import STOCK, WEBHOOK, copy_home, demo_home, pid_of  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.store import Factory  # noqa: E402

NAME = "Dev Tester"
READY = ("!!document.querySelector('.view-body') && document.querySelector('.view-body').dataset.view === '{v}'"
         " && !document.querySelector('.view-body [aria-busy=\"true\"]')")


class UiAccDeveloperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        demo_home()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-acc-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes"),
                                               "GNOMON_CMD": str(self.tmp / "no-such-gnomon")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.factory = Factory(copy_home(self.tmp))
        self.webhook, self.stock = pid_of(self.factory, WEBHOOK), pid_of(self.factory, STOCK)
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)

    def step(self, name: str) -> None:
        b = self.browser
        if b.step != "start":
            b.eval("1")
            time.sleep(0.3)
            self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
            self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        b.step = name

    def sign_in(self, persona: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        self.persona(persona, name=True)

    def persona(self, persona: str, *, name: bool = False) -> None:
        b = self.browser
        b.click("#person-chip", what="the person chip")
        if name:
            b.eval("document.querySelector('#person').value = ''; true")
            b.type("#person", NAME)
        b.click(f'label[for="pp-{"all" if persona == "*" else persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done in the person menu")

    def go(self, hash_: str, ready: str, what: str) -> None:
        self.browser.eval(f"location.hash = {json.dumps(hash_)}; true")
        self.browser.wait(ready, what)
        time.sleep(0.3)

    def text(self, selector: str) -> str:
        return self.browser.eval(f"(document.querySelector({json.dumps(selector)}) || {{}}).textContent || ''")

    def test_FR_DEV1_AC_6_the_briefing_says_who_decides_and_the_filters_are_per_project(self):
        b = self.browser
        self.step("the developer's briefing")
        self.sign_in("developer")
        self.go(f"#/p/{self.webhook}/board", READY.format(v="board"), "the Board")
        b.wait("!!document.querySelector('.dv-brief .dv-next-t')", "the briefing")
        self.assertEqual(self.text(".dv-next-t"), "C-0002 waits on the Business owner or Product owner")
        brief = self.text(".dv-brief")
        self.assertNotIn("Nothing waits on a decision", brief)
        self.assertIn("decided by Business owner or Product owner", brief)
        self.assertTrue(b.eval("!!document.querySelector('[data-control=\"dev_nudge\"]')"))
        self.assertFalse(b.eval("!!document.querySelector('[data-key=\"dev:next\"]')"))     # no "Decide it"
        self.step("a card not in this view: the note leaves with the view")
        self.go(f"#/p/{self.webhook}/inbox/C-0002", READY.format(v="inbox"), "the developer's Inbox")
        b.wait("document.querySelector('#status').textContent.includes('C-0002 is not shown in this view')", "the note")
        self.go(f"#/p/{self.webhook}/board", READY.format(v="board"), "the Board again")
        self.assertNotIn("is not shown in this view", self.text("#status"))
        self.step("switch to the persona that decides it")
        b.wait("!!document.querySelector('[data-control=\"dev_switch_persona\"]')", "Switch to")
        label = self.text('[data-control="dev_switch_persona"]')
        self.assertRegex(label, r"^Switch to (Business owner|Product owner) to decide it$")
        b.click('[data-control="dev_switch_persona"]', what="Switch to the persona that decides it")
        b.wait("location.hash.endsWith('/inbox/C-0002') && !!document.querySelector('.view-body [data-id=\"C-0002\"]')",
               "C-0002 in the deciding persona's Inbox")
        self.assertEqual(self.text("#pc-persona"), label[len("Switch to "):-len(" to decide it")])
        self.step("the filters are per project, and say what they hide")
        self.persona("developer")
        self.go(f"#/p/{self.webhook}/board", READY.format(v="board"), "the webhook Board")
        b.wait("!!document.querySelector('#dv-mine')", "the filters")
        b.click("#dv-mine", what="Waiting on me")
        b.wait("!!document.querySelector('.dv-hidden')", "the hidden-cards note")
        self.assertRegex(self.text(".dv-hidden"), r"^\s*\d+ cards? hidden by the filters")
        self.go(f"#/p/{self.stock}/board", READY.format(v="board"), "the stock Board")
        b.wait("!!document.querySelector('#dv-mine')", "the stock filters")
        self.assertFalse(b.eval("document.querySelector('#dv-mine').checked"))
        self.assertGreater(b.eval("document.querySelectorAll('[data-card]').length"), 0)
        self.go(f"#/p/{self.webhook}/board", READY.format(v="board"), "the webhook Board again")
        b.wait("!!document.querySelector('#dv-mine')", "the webhook filters")
        b.click("#dv-mine", what="Waiting on me again")
        b.wait("!!document.querySelector('[data-key=\"dev:f:clear\"]')", "Clear the filters")
        b.click('[data-key="dev:f:clear"]', what="Clear the filters")
        b.wait("!document.querySelector('.dv-hidden') && !document.querySelector('#dv-mine').checked", "cleared")
        self.step("done")

    def test_FR_PPL1_AC_7_everything_holds_every_card_with_the_batch_bar_and_an_update_reads_as_words(self):
        b = self.browser
        self.step("everything")
        self.sign_in("*")
        self.go(f"#/p/{self.webhook}/inbox", READY.format(v="inbox"), "the project Inbox")
        b.wait("document.querySelectorAll('.view-body [data-id^=\"C-\"]').length >= 3", "every card held")
        ids = b.eval("[...document.querySelectorAll('.view-body article[data-id]')].map((a) => a.dataset.id)")
        self.assertTrue({"C-0002", "C-0003", "C-0004"} <= set(ids), ids)
        b.eval("document.querySelector('.ib-later') && (document.querySelector('.ib-later').open = true); true")
        self.assertTrue(b.eval("!!document.querySelector('[data-control=\"inbox_batch_decide\"]')"))
        self.step("the Inbox across projects")
        self.go("#/inbox", "!!document.querySelector('.inbox-card')", "the Inbox across projects")
        self.assertTrue(b.eval("!!document.querySelector('[data-control=\"inbox_batch_decide\"]')"))
        b.click('[data-key="ib-all"]', what="Select all")
        self.assertRegex(self.text("#ib-count"), r"^[2-9]\d* selected$")
        update = f'.inbox-card[data-project="{self.webhook}"][data-id="C-0004"]'
        b.wait(f"!!document.querySelector({json.dumps(update)})", "the update card")
        body = b.eval(f"[...document.querySelector({json.dumps(update)}).children].filter((x) => "
                      "!x.matches('details')).map((x) => x.textContent).join(' ')")
        self.assertNotIn('"trigger"', body)
        self.assertIn("demo-model-2", body)
        self.assertIn('"trigger"', self.text(update + " details"))
        self.step("done")

    def test_FR_CPL1_AC_5_the_hand_off_and_the_automation_open_with_what_was_asked(self):
        b = self.browser
        self.step("the hand-off dialog")
        self.sign_in("developer")
        self.go(f"#/p/{self.webhook}/board", READY.format(v="board"), "the Board")
        b.click('[data-control="handoff"]', what="Hand off to an agent")
        b.wait("(document.querySelector('#ho-brief') || {}).textContent.startsWith('# Hand-off')", "the brief")
        before = self.text("#ho-brief")
        b.eval("const c = document.querySelector('#ho-change'); c.value = 'C-9999';"
               " c.dispatchEvent(new Event('change')); true")
        b.wait("document.querySelector('#ho-change-msg').textContent.includes('No change C-9999 in this project')",
               "the unknown change said")
        self.assertEqual(self.text("#ho-brief"), before)
        b.problems.clear()                                              # the 400 the dialog said in words
        b.eval("document.querySelector('#modal [data-close], #modal .modal-x, #modal button[aria-label^=\"Close\"]')"
               ".click(); true")
        self.step("Ask Rihma: hand off T-002 to Claude Code")
        self.ask("hand off T-002 to Claude Code")
        b.click('.msg.bot:last-child [data-key^="go:"]', what="Take me there")
        b.wait("document.querySelector('#ho-change') && document.querySelector('#ho-change').value === 'T-002'"
               " && document.querySelector('#ho-to').value === 'claude-code'"
               " && document.querySelector('#ho-brief').textContent.includes('## The task T-002')", "the dialog")
        b.eval("document.querySelector('#modal [data-close], #modal .modal-x, #modal button[aria-label^=\"Close\"]')"
               ".click(); true")
        self.step("Ask Rihma: generate an automation")
        self.ask("Generate an automation that runs the tests every night")
        b.wait("!!document.querySelector('.msg.bot:last-child [data-key=\"goal:S-1\"]')", "the plan")
        b.click('.msg.bot:last-child [data-key="goal:S-1"]', what="Set up the automation")
        b.wait("(document.querySelector('#amn-describe') || {}).value === "
               "'Generate an automation that runs the tests every night'", "Describe it prefilled")
        b.wait("!!document.querySelector('#amn-describe-summary') || !!document.querySelector('.amn-described .note')",
               "the read draft")
        self.step("done")

    def ask(self, question: str) -> None:
        b = self.browser
        if not b.eval("!document.querySelector('#assistant').hidden"):
            b.click("#assistant-fab", what="Ask Rihma")
        n = b.eval("document.querySelectorAll('.msg.bot').length")
        b.eval(f"document.querySelector('#as-q').value = {json.dumps(question)}; true")
        b.eval("document.querySelector('#as-form').requestSubmit(); true")
        b.wait(f"document.querySelectorAll('.msg.bot').length > {n}"
               " && !document.querySelector('.msg.bot:last-child .thinking')", "the answer")

    def test_FR_BA1_AC_10_a_select_button_replaces_what_is_ticked(self):
        b = self.browser
        self.step("assess")
        self.sign_in("developer")
        status = b.eval(f"""fetch('/api/projects/{self.stock}/assessment', {{method: 'POST', headers: {{
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + sessionStorage.getItem('gf.token')}},
            body: JSON.stringify({{person: '{NAME}', persona: 'developer'}})}}).then((r) => r.status)""")
        if status not in (201, 202):        # the page keeps its token elsewhere: assess through the button
            self.go(f"#/p/{self.stock}/assessment", "!!document.querySelector('[data-control=\"run_assessment\"]')",
                    "the Assessment view")
            b.click('[data-control="run_assessment"]', what="Assess now")
        self.go(f"#/p/{self.stock}/assessment", "!!document.querySelector('#as-sum-h')", "the assessment")
        b.wait("!!document.querySelector('[data-key=\"as-severe\"]')", "the selections")
        severe = int(b.eval("(document.querySelector('[data-key=\"as-severe\"]').textContent.match(/\\((\\d+)\\)/)"
                            " || [0, 0])[1]"))
        b.click('[data-key="as-top"]', what="Select the top")
        b.click('[data-key="as-severe"]', what="Select critical and high")
        b.wait(f"document.querySelector('.as-prio [role=\"status\"]').textContent.startsWith('{severe} ')",
               "only the severe ticked")
        self.assertEqual(b.eval("document.querySelectorAll('input[data-key^=\"pick:\"]:checked').length"), severe)
        self.step("done")

    def test_FR_UXO1_AC_7_at_390_the_theme_is_in_the_person_menu_and_settings_fits(self):
        b = self.browser
        self.step("phone width")
        self.sign_in("developer")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1,
                                                     "mobile": True})
        self.go("#/settings", "!!document.querySelector('#main [data-cz], #main .card')", "Settings")
        time.sleep(1.0)
        self.assertLessEqual(b.eval("document.documentElement.scrollWidth"), 390)
        b.click("#person-chip", what="the person chip")
        b.click('[data-key="pp-theme:dark"]', what="Dark")
        b.wait("document.documentElement.getAttribute('data-theme') === 'dark'", "dark")
        b.click('[data-key="pp-theme:light"]', what="Light")
        b.wait("document.documentElement.getAttribute('data-theme') === 'light'"
               " && document.querySelector('[data-key=\"pp-theme:light\"]').getAttribute('aria-pressed') === 'true'",
               "light")
        self.step("done")

    def test_FR_S2_AC_3_the_board_shows_the_epics_and_a_product_owner_creates_one(self):
        b = self.browser
        self.step("a product owner creates an epic")
        self.sign_in("product_owner")
        self.go(f"#/p/{self.webhook}/board", READY.format(v="board") + " && !!document.querySelector('.ep-card')",
                "the Board's epics")
        self.assertIn("No epic yet", self.text(".ep-card"))
        b.click('[data-key="ep-new"]', what="New epic")
        b.type("#ep-title", "Incoming stock is always right")
        b.type("#ep-owner", "Olli Owner")
        b.type("#ep-criterion", "the counts match the dock")
        b.click('[data-key="ep-req:R-1"]', what="R-1")
        b.click('[data-key="ep-req:R-2"]', what="R-2")
        b.click('[data-key="ep-save"]', what="Create the epic")
        b.wait("!!document.querySelector('.ep-epic[data-epic=\"E-1\"]')", "E-1 on the Board")
        epic = self.text('.ep-epic[data-epic="E-1"]')
        for said in ("Qualifies", "Olli Owner", "R-1", "T-001", "Done", "R-2", "T-002"):
            self.assertIn(said, epic)
        self.assertIn("R-3", self.text(".ep-loose"))
        self.step("a developer reads it on the cards")
        self.persona("developer")
        self.go(f"#/p/{self.webhook}/board", READY.format(v="board") + " && !!document.querySelector('.ep-epic')",
                "the developer's Board")
        self.assertFalse(b.eval("!!document.querySelector('[data-key=\"ep-new\"]')"))     # not theirs to make
        self.assertIn("E-1", self.text('[data-card="T-001"]'))
        self.assertTrue(b.eval("!!document.querySelector('[data-key=\"dev:f:epic\"]')"))
        self.step("done")


if __name__ == "__main__":
    unittest.main()
