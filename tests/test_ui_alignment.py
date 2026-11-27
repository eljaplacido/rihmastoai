"""The Alignment tab in a real browser (FR-ALN1-AC-8): headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py drives it.

A team's repository (tests/alignment_fixture.py) is attached. A person opens the project's Overview and follows
the offer to align it, reads the repository from the Alignment tab, accepts a requirement, edits a criterion
and accepts it with the change, rejects one, accepts every open task at once, and copies and downloads a
suggested change for the repository. The view is looked at in dark and light, 1440 and 390 pixels wide: every
control has a name a screen reader says, nothing scrolls sideways, and no step leaves a console error, a
failed request or a Content-Security-Policy violation behind. The repository is never written.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). ``RIHMA_UI_SHOTS=<folder>``
also saves a screenshot per step.
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

from alignment_fixture import git, make_repo  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import alignment_records as ar  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
NAMELESS = ("[...document.querySelectorAll('#main button, #main input, #main select, #main textarea, #main a[href], #main pre')]"
            ".filter((el) => el.getClientRects().length && !((el.getAttribute('aria-label') || '').trim()"
            " || (el.labels && [...el.labels].some((l) => l.textContent.trim()))"
            " || (el.tagName !== 'PRE' && el.textContent.trim()) || el.getAttribute('title'))).map((el) => el.outerHTML.slice(0, 120))")
SIDEWAYS = "document.documentElement.scrollWidth > window.innerWidth + 1"


class UiAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for the repository")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-align-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = make_repo(self.tmp / "loans")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.factory = Factory(self.tmp / "home")
        self.p = attach(self.factory, "Tool store loans", repo=self.repo, person=PERSON, persona="developer")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.browser.cmd("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(self.tmp / "dl")})

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
        self.assertEqual(b.eval(NAMELESS), [], f"controls without an accessible name during '{b.step}'")
        self.assertFalse(b.eval(SIDEWAYS), f"the page scrolls sideways during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"align-{b.step.replace(' ', '-')}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000, "deviceScaleFactor": 1,
                                                                "mobile": px < 600})

    def theme(self, word: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def row(self, start: str) -> str:
        """The data-id of the first open row whose title starts with ``start``."""
        return self.browser.wait(
            f"(() => {{ const r = [...document.querySelectorAll('.al-row')].find((x) => x.querySelector('.al-t')"
            f".textContent.startsWith({json.dumps(start)})); return r ? r.dataset.id : ''; }})()", f"the row {start}")

    def status(self, iid: str) -> str:
        return self.browser.eval(f"(document.querySelector('.al-row[data-id=\"{iid}\"]') || {{dataset: {{}}}}).dataset.status")

    def test_FR_ALN1_AC_8_a_person_aligns_a_project_with_its_repository_in_chrome(self):
        b = self.browser
        pid = self.p.pid
        self.step("sign in")
        self.sign_in()
        self.step("the offer on the overview")
        b.eval(f"location.hash = '#/p/{pid}/overview'; true")
        b.wait("!!document.querySelector('.al-callout:not([hidden]) a')", "the offer to align")
        b.click(".al-callout a", what="Open Alignment")
        b.wait(f"location.hash === '#/p/{pid}/align'"
               " && !!document.querySelector('[data-control=\"align_scan\"]')", "the Alignment view")
        self.assertIn("Not aligned yet.", b.eval("document.querySelector('.view-body').textContent"))
        self.assertTrue(b.eval(f"!!document.querySelector('.tabs a[href=\"#/p/{pid}/align\"][aria-current=\"page\"]')"))
        self.step("read the repository")
        b.click('[data-control="align_scan"]', what="Read the repository")
        summary = b.wait("(document.querySelector('#al-sum-h') || {}).textContent", "the summary", timeout=60)
        # Tests trace to requirements is at Advise for an attached project: what was taken in leads (FR-STR2)
        self.assertEqual(summary, "Taken in from the project's own files: 7 requirements, 9 criteria, 5 tasks, "
                                  "2 decisions, 1 API contract. Tests tracing to criteria: Advise here (5 of 6 tests "
                                  "trace to a criterion).")
        groups = b.eval("[...document.querySelectorAll('.al-group .card-t')].map((x) => x.textContent)")
        self.assertEqual(groups, ["Requirements", "Criteria", "Tests trace", "Tasks", "Decisions", "API contracts", "Gaps"])
        self.assertEqual(self.p.ledger().of_kind("alignment_scanned")[-1]["event"]["payload"]["person"], PERSON)
        self.step("accept a requirement")
        us1 = self.row("User Story 1")
        b.click(f'[data-key="al-accept:{us1}"]', what="Accept User Story 1")
        b.wait(f"(document.querySelector('.al-row[data-id=\"{us1}\"]') || {{dataset: {{}}}}).dataset.status === 'accepted'",
               "User Story 1 accepted")
        self.assertIn("US-1", [r["id"] for r in self.p.read("contract.json")["requirements"]])
        self.step("edit a criterion")
        crit = self.row("REQ-1-AC-2")
        b.click(f'[data-key="al-edit:{crit}"]', what="Edit REQ-1-AC-2")
        then = f"#al-e-{crit}-then"
        b.wait(f"!!document.querySelector('{then}')", "the edit form")
        b.eval(f"(() => {{ const t = document.querySelector('{then}'); t.value = ''; return true; }})()")
        b.type(then, "overdue loans are listed before the others")
        b.click(f'[data-key="al-save:{crit}"]', what="Accept with changes")
        b.wait(f"(document.querySelector('.al-row[data-id=\"{crit}\"]') || {{dataset: {{}}}}).dataset.status === 'accepted'",
               "the edited criterion accepted")
        req1 = next(r for r in self.p.read("contract.json")["requirements"] if r["id"] == "REQ-1")
        self.assertIn("overdue loans are listed before the others", [c["then"] for c in req1["acceptance"]])
        self.step("reject a requirement")
        fr3 = self.row("FR-003")
        b.click(f'[data-key="al-reject:{fr3}"]', what="Reject FR-003")
        b.wait(f"(document.querySelector('.al-row[data-id=\"{fr3}\"]') || {{dataset: {{}}}}).dataset.status === 'rejected'",
               "FR-003 rejected")
        self.step("accept every open task")
        b.click('[data-key="al-bulk:tasks"]', what="Accept all open tasks")
        b.wait("!!document.querySelector('.al-group .al-confirm')", "the impact before accepting (FR-ORG1)")
        b.click('.al-group [data-key="al-confirm-ok"]', what="Confirm after the impact")
        tasks = "document.querySelector('[aria-labelledby=\"al-g-tasks-h\"]')"
        b.wait(f"!!{tasks} && {tasks}.querySelectorAll('.al-row').length === 5"
               f" && !{tasks}.querySelector('.al-row:not([data-status=\"accepted\"])')", "every task accepted")
        self.assertEqual(len(ar.accepted(self.p, "tasks")), 5)
        decided = [r["event"]["payload"] for r in self.p.ledger().of_kind("alignment_accepted")]
        self.assertTrue(all(d["person"] == PERSON for d in decided))
        self.step("copy and download a suggestion")
        b.wait("!!document.querySelector('#al-sug-h') && !!document.querySelector('[data-control=\"align_suggestions\"]')",
               "the suggested changes")
        self.assertIn("+def test_US_1_AC_1_borrow_marks_the_item_on_loan():",
                      b.eval("document.querySelector('[aria-labelledby=\"al-sug-h\"] .al-pre').textContent"))
        b.click('[data-control="align_suggestions"]', what="Copy a suggestion")
        b.click('[data-key^="al-dl:"]', what="Download the patch")
        patch = b.wait("(() => { const f = document.querySelector('[data-key^=\"al-dl:\"]'); return f ? f.textContent : ''; })()",
                       "the download button")
        self.assertEqual(patch, "Download the patch")
        for word in ("Light", "Dark"):
            self.step(f"{word.lower()} theme at 1440 px")
            self.width(1440)
            self.theme(word)
            b.wait("!!document.querySelector('#al-sum-h')", f"the view in the {word} theme at 1440 px")
            self.step(f"{word.lower()} theme at 390 px")
            self.width(390)
            b.wait("!!document.querySelector('#al-sum-h') && window.innerWidth === 390", "the view at 390 px")
        self.check()
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)                    # never written
        self.assertEqual(git(self.repo, "status", "--porcelain", "--untracked-files=all"), "")


if __name__ == "__main__":
    unittest.main()
