"""The Review in a real browser (FR-REV1): since you last looked, reviewed in place, by keyboard, on a desk and on
a phone.

Headless Chrome over the DevTools protocol, with the driver of ``test_ui_drive`` (skipped the same way when
Chrome or git is missing), on ``review_fixture``'s home. Home's first card says what happened; the Review page
lists it by group; j and k move, Enter opens the preview drawer with the diff, Esc closes it, r marks a merged
task reviewed, a approves a card, d overturns an assumption, o opens a record; a change is reported from a row;
Mark all reviewed moves the marker. Then dark and light, a project's Review tab, and the page at 390 px. After
every step there is no console error, uncaught exception, failed request or CSP violation, and nothing
scrolls sideways.
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import review_fixture  # noqa: E402
import test_ui_drive as drive  # noqa: E402  (the module, so its TestCase is not collected here again)
from review_fixture import AINO  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

SELECTED = "(document.querySelector('.rv-row.sel') || {dataset: {}}).dataset.id"
SIDEWAYS = "document.documentElement.scrollWidth - document.documentElement.clientWidth"
KEYS = {"j": 74, "k": 75, "a": 65, "d": 68, "r": 82, "o": 79, "Enter": 13, "Escape": 27}


class UiReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = drive.find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the review home")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-review-")).resolve()
        cls.factory = Factory(cls.tmp / "home", clock=FixedClock())
        cls.w = review_fixture.build(cls.factory, cls.tmp)
        cls.runner = drive.QuietRunner()
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        roads.stop_started()
        with contextlib.suppress(OSError):
            roads.rmtree(cls.tmp)

    setUp = drive.UiDriveTest.setUp
    step = drive.UiDriveTest.step

    def check(self) -> None:
        drive.UiDriveTest.check(self)
        self.assertLessEqual(self.browser.eval(SIDEWAYS), 0, f"the page scrolls sideways during '{self.browser.step}'")

    def press(self, key: str) -> None:
        self.browser.key(key, KEYS[key])

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", AINO)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(AINO)}", "the person chip")

    def select(self, suffix: str) -> None:
        """Press j until the row whose id ends with ``suffix`` is selected."""
        b = self.browser
        for _ in range(60):
            if str(b.eval(SELECTED) or "").endswith(suffix):
                return
            self.press("j")
        self.fail(f"no row {suffix}")

    def test_FR_REV1_AC_7_the_review_page_works_by_keyboard_with_a_drawer_in_dark_and_light_and_on_a_phone(self):
        b = self.browser
        loans = self.w["loans"].pid
        self.step("sign in")
        self.sign_in()

        self.step("home's first card")
        card = b.wait("(() => { const c = document.querySelector('#home-review .rv-card'); return c && c.textContent"
                      ".includes('Since you last looked: 2 shipped') && c.textContent; })()", "the review card")
        self.assertIn("1 waiting on you", card)
        self.assertEqual(b.eval("document.querySelector('#home-review').nextElementSibling.id"), "home-setup")
        self.assertEqual(b.eval("document.querySelector('#sb-nav a').getAttribute('href')"), "#/review")

        self.step("the review page")
        b.click('#sb-nav a[href="#/review"]', what="Review in the sidebar")
        b.wait("!!document.querySelector('#rv-root .rv-row.sel')", "the review with a row selected")
        self.assertEqual(b.eval("document.querySelector('#view-title').textContent"), "Review")
        self.assertTrue(b.eval("document.querySelector('.page-head .lede').textContent")
                        .startswith("Since you last looked: 2 shipped, 1 waiting on you"))
        self.assertEqual(b.eval("[...document.querySelectorAll('.rv-group')].map((g) => g.dataset.group).join()"),
                         "waiting,wrong,decided,shipped,ide,agents,cost")   # From agents: the channel
        self.assertTrue(b.eval(SELECTED).endswith("/card/C-0001"))
        self.assertIn("fake-builder", b.eval("document.querySelector('.rv-group[data-group=\"shipped\"]').textContent"))

        self.step("move by keyboard")
        self.press("j")
        self.assertIn("/ledger/", b.eval(SELECTED))                               # the first thing that went wrong
        self.press("k")
        self.assertTrue(b.eval(SELECTED).endswith("/card/C-0001"))
        self.select("/task/T-001")

        self.step("the preview drawer")
        self.press("Enter")
        b.wait("!document.querySelector('#rv-drawer').hidden && !!document.querySelector('#rv-drawer .rv-diffpre')",
               "the drawer with the diff")
        self.assertIn("diff --git", b.eval("document.querySelector('#rv-drawer .rv-diffpre').textContent"))
        self.assertTrue(b.eval("document.querySelectorAll('#rv-drawer .rv-diffpre .add').length > 0"))

        self.step("close the drawer")
        self.press("Escape")
        b.wait("document.querySelector('#rv-drawer').hidden && document.activeElement.classList.contains('rv-row')",
               "the drawer closed, the focus on the row")

        self.step("mark reviewed with r")
        self.press("r")
        b.wait(f"(document.querySelector('.rv-row[data-id=\"{loans}/task/T-001\"]') || {{classList: {{contains: () => false}}}})"
               ".classList.contains('done')", "the task marked reviewed")
        marks = [r["event"]["payload"] for r in self.w["loans"].ledger().of_kind("review_marked")]
        self.assertEqual([(m["item"], m["person"], m["persona"]) for m in marks], [(f"{loans}/task/T-001", AINO, "developer")])

        self.step("approve a card with a")
        b.eval("window.scrollTo(0, 0); true")
        self.select("/card/C-0001")
        self.press("a")
        b.wait("document.querySelector('.rv-group[data-group=\"waiting\"] .count').textContent === '0'",
               "nothing waits any more")
        decision = Canon(self.w["loans"]).get_card("C-0001")["decision"]
        self.assertEqual((decision["verdict"], decision["person"]), ("retry", AINO))

        self.step("overturn an assumption with d")
        self.select(f"{loans}/assumption/A-001")
        self.press("d")
        b.wait("document.querySelector('#modal').open && !!document.querySelector('#rv-text')", "the correction dialog")
        b.type("#rv-text", "only the team lead approves a loan")
        b.click('[data-key="rv-send"]', what="Send, signed")
        b.wait("!document.querySelector('#modal').open", "the dialog closed")
        refuted = next(a for a in Canon(self.w["loans"]).assumptions() if a["id"] == "A-001")
        self.assertEqual((refuted["status"], refuted["settled"]["by"]), ("refuted", AINO))

        self.step("report a change from a row")
        ide = f"{self.w['orders'].pid}/gate/"
        b.click(f'.rv-row[data-id^="{ide}"] [data-key="rv:change:Report a change"]', what="Report a change")
        b.wait("document.querySelector('#modal').open && document.querySelector('#rv-text').value.startsWith('About Commit')",
               "the change dialog, prefilled")
        b.eval("document.querySelector('#rv-text').focus(); true")
        b.cmd("Input.insertText", {"text": " count should skip cancelled orders"})
        b.click('[data-key="rv-send"]', what="Send, signed")
        b.wait("!document.querySelector('#modal').open", "the dialog closed")
        self.assertTrue(any("count should skip cancelled orders" in json.dumps(c)
                            for c in Canon(self.w["orders"]).cards(state=None, kind="change")))

        self.step("open a record with o")
        self.select(f"{loans}/release/1")
        self.press("o")
        b.wait(f"location.hash === '#/p/{loans}/releases'", "the release's view")
        b.click('#sb-nav a[href="#/review"]', what="Review in the sidebar")
        b.wait("!!document.querySelector('#rv-root .rv-row')", "the review again")

        backgrounds = {}
        for mode, label in (("dark", "Dark"), ("light", "Light")):
            self.step(f"{mode} theme")
            b.click("#theme", what="Theme")
            b.click(".menu-item", text=label, what=label)
            b.wait(f"document.documentElement.dataset.theme === '{mode}'", mode)
            backgrounds[mode] = b.eval("getComputedStyle(document.querySelector('.rv-group')).backgroundColor")
            self.assertNotEqual(backgrounds[mode], b.eval("getComputedStyle(document.querySelector('.rv-title')).color"))
        self.assertNotEqual(backgrounds["dark"], backgrounds["light"])           # the groups follow the theme

        self.step("mark all reviewed")
        b.click('[data-control="mark_all_reviewed"]', what="Mark all reviewed")
        b.wait("document.querySelector('.rv-period').textContent.includes('(last review)')", "the marker moved")
        done = factory_project(self.factory).ledger().of_kind("review_done")[-1]["event"]["payload"]
        self.assertEqual((done["person"], done["scope"]), (AINO, "all"))

        self.step("a project's review tab")
        b.eval(f"location.hash = '#/p/{loans}/review'; true")
        b.wait(f"!!document.querySelector('.tabs a[href=\"#/p/{loans}/review\"][aria-current=\"page\"]')"
               " && !!document.querySelector('#rv-root .rv-group')", "the project's Review tab")
        self.assertTrue(b.eval("!!document.querySelector('#rv-root [data-control=\"mark_all_reviewed\"]')"))
        b.eval("location.hash = '#/review'; true")
        b.wait("!!document.querySelector('#rv-root .rv-group') && !!document.querySelector('#view-title')", "the review")

        self.step("a phone at 390 px")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True})
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('#home-review .rv-card')", "the review card on the phone")
        self.check()
        b.eval("location.hash = '#/review'; true")
        b.wait("!!document.querySelector('#rv-root .rv-group')", "the review on the phone")
        b.click('[data-key="rv-since:7d"]', what="the last 7 days")                # after Mark all reviewed: look back
        b.wait("document.querySelectorAll('#rv-root .rv-row').length > 5", "the week's rows on the phone")
        self.step("the drawer on a phone")
        b.click(f'.rv-row[data-id="{loans}/task/T-001"] .rv-title', what="the merged task")
        b.wait("!document.querySelector('#rv-drawer').hidden && !!document.querySelector('#rv-drawer .rv-diffpre')",
               "the drawer on the phone")
        self.assertLessEqual(b.eval("document.querySelector('#rv-drawer').getBoundingClientRect().width"), 390)
        self.step("back from the drawer")
        self.press("Escape")
        b.wait("document.querySelector('#rv-drawer').hidden", "the drawer closed")
        b.click('[data-key="rv-since:"]', what="since my last review")
        self.check()
        self.assertEqual(self.runner.started, [])                                # the review started no job


if __name__ == "__main__":
    unittest.main()
