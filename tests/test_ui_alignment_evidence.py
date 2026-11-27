"""The Alignment view's numbers agree with the decisions, in a real browser (FR-ORG2-AC-7): headless Chrome over the
DevTools protocol, as tests/test_ui_drive.py drives it.

A team's repository (tests/alignment_fixture.py: plans from January, code from March) is attached and read. A person
reads the head (none of these decisions is development work; two conventions may be real risks), defers Rihmasto's
convention items, rejects a requirement and sees its gaps closed, and filters by origin: the summary's number to
decide is the head's, deferred and closed are counted apart, and each filter's count is the rows it shows. The view is
looked at in dark and light, 1440 and 390 pixels wide, with no console error, failed request or Content-Security-
Policy violation. The repository is never written.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). ``RIHMA_UI_PORT`` fixes the
cockpit's port (any free one when unset); ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_alignment_origin as origin  # noqa: E402  (the module, so its TestCase is not collected here again)
from alignment_fixture import git  # noqa: E402

from kernel import alignment_records as ar  # noqa: E402

SUMMARY = ("Object.fromEntries([...document.querySelectorAll('.al-sum [data-st]')]"
           ".map((c) => [c.dataset.st, parseInt(c.textContent, 10)]))")


class UiAlignmentEvidenceTest(origin.UiAlignmentOriginTest):
    """On a port of its own when RIHMA_UI_PORT names one, as the origin test's setUp starts the cockpit."""

    def test_FR_ORG1_AC_5_a_person_triages_with_origins_and_impact_in_chrome(self):
        self.skipTest("run in tests/test_ui_alignment_origin.py")

    def head_number(self) -> int:
        said = self.browser.eval("document.querySelector('.al-triage-said').textContent")
        return int(re.match(r"(\d+) to decide", said).group(1))

    def filters_agree(self) -> None:
        b = self.browser
        for f in ("project", "old", "convention", "deferred"):
            b.click(f'[data-key="al-f:{f}"]', what=f"the filter {f}")
            label = b.eval(f"document.querySelector('[data-key=\"al-f:{f}\"]').textContent")
            shown = b.eval("[...document.querySelectorAll('.al-row')].filter((r) => r.getClientRects().length "
                           "&& !r.closest('details:not([open])')).length")      # a folded suggestion is not shown
            self.assertEqual(int(re.search(r"\((\d+)\)", label).group(1)), shown, label)
        b.click('[data-key="al-f:all"]', what="Everything")

    def test_FR_ORG2_AC_7_the_views_numbers_agree_with_the_decisions_in_chrome(self):
        b = self.browser
        pid = self.p.pid
        self.step("sign in")
        self.sign_in()
        self.step("read the repository")
        b.eval(f"location.hash = '#/p/{pid}/align'; true")
        b.wait("!!document.querySelector('[data-control=\"align_scan\"]')", "the Alignment view")
        b.click('[data-control="align_scan"]', what="Read the repository")
        said = b.wait("(document.querySelector('.al-triage-said') || {}).textContent", "the triage head", timeout=60)
        self.assertIn("6 by Rihmasto's convention (1 may be a real risk)", said)
        about = b.eval("[...document.querySelectorAll('.al-advice li')].map((x) => x.dataset.about)")
        self.assertEqual(about[:2], ["development", "risk"])
        self.assertTrue(b.eval("document.querySelector('.al-advice [data-about=\"development\"]').textContent")
                        .startswith("None of these decisions is development work"))
        self.assertEqual(b.eval(SUMMARY)["open"], self.head_number())
        ci = self.row("The CI does not run")
        self.assertEqual(b.eval(f"document.querySelector('.al-row[data-id=\"{ci}\"] [data-origin]').dataset.origin"),
                         "risk")
        self.step("defer the convention items")
        b.click('[data-key="al-t:defer_convention"]', what="Defer convention items")
        b.wait("(document.querySelector('.al-triage .al-confirm') || {}).textContent", "its impact")
        b.eval("document.querySelector('.al-triage .al-confirm').scrollIntoView({block: 'center'}); true")
        b.click('.al-triage [data-key="al-confirm-ok"]', what="Confirm the deferral")
        b.wait("(document.querySelector('.al-triage-said') || {textContent: ''}).textContent.includes('5 deferred')",
               "the convention items deferred")
        counts = b.eval(SUMMARY)
        self.assertEqual((counts["open"], counts["deferred"]), (self.head_number(), 5))
        self.step("filters count what they show")
        self.filters_agree()
        self.step("reject a requirement and see its gaps closed")
        fr3 = self.row("FR-003")
        b.eval(f"document.querySelector('[data-key=\"al-reject:{fr3}\"]').scrollIntoView({{block: 'center'}}); true")
        b.click(f'[data-key="al-reject:{fr3}"]', what="Reject FR-003")
        b.wait(f"(document.querySelector('.al-row[data-id=\"{fr3}\"]') || {{dataset: {{}}}}).dataset.status "
               "=== 'rejected'", "FR-003 rejected")
        gap = next(i["id"] for g in ar.view(self.p)["groups"] for i in g["items"] if i["title"] == "FR-003 has no test")
        row = f".al-row[data-id=\"{gap}\"]"
        b.wait(f"(document.querySelector('{row}') || {{dataset: {{}}}}).dataset.status === 'closed'", "the gap closed")
        self.assertIn("Closed: it is about FR-003, which you rejected",
                      b.eval(f"document.querySelector('{row} .al-closed').textContent"))
        counts = b.eval(SUMMARY)
        self.assertEqual((counts["open"], counts["closed"]), (self.head_number(), 2))
        self.filters_agree()
        for word in ("Light", "Dark"):
            self.step(f"{word.lower()} theme at 1440 px")
            self.width(1440)
            self.theme(word)
            b.wait("!!document.querySelector('#al-triage-h')", f"the head in the {word} theme at 1440 px")
            b.eval("document.querySelector('.al-sum').scrollIntoView(); true")
            self.step(f"{word.lower()} theme at 390 px")
            self.width(390)
            b.wait("!!document.querySelector('#al-triage-h') && window.innerWidth === 390", "the head at 390 px")
            b.eval(f"document.querySelector('{row}').scrollIntoView({{block: 'center'}}); true")
        self.check()
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)                    # never written
        self.assertEqual(git(self.repo, "status", "--porcelain", "--untracked-files=all"), "")


if __name__ == "__main__":
    unittest.main()
