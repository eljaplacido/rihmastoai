"""The Alignment view's origin, impact and triage in a real browser (FR-ORG1-AC-5): headless Chrome over the DevTools
protocol, as tests/test_ui_drive.py drives it.

A team's repository (tests/alignment_fixture.py: plans from January, code from March) is attached and read. A person
reads the head's "What to do with these", filters the items by origin, sees each item's origin and what Accept would
do, previews and confirms Accept all for the tasks, defers a gap and brings it back, and defers Rihmasto's convention
items and rejects the stale ones from the head, each after its impact. The view is looked at in dark and light, 1440
and 390 pixels wide: every control has a name a screen reader says, nothing scrolls sideways, and no step leaves a
console error, a failed request or a Content-Security-Policy violation behind. The repository is never written.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). ``RIHMA_UI_PORT`` fixes the
cockpit's port (any free one when unset); ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_alignment as base  # noqa: E402  (the module, so its TestCase is not collected here again)
from alignment_fixture import git  # noqa: E402

from kernel import alignment_records as ar  # noqa: E402
from kernel import alignment_triage as tri  # noqa: E402


class UiAlignmentOriginTest(base.UiAlignmentTest):
    def setUp(self):
        real = base.make_server
        port = int(os.environ.get("RIHMA_UI_PORT") or 0)       # the cockpit on a port of one's own, if named
        base.make_server = lambda factory, _port=0, **kw: real(factory, port, **kw)
        try:
            super().setUp()
        finally:
            base.make_server = real

    def test_FR_ALN1_AC_8_a_person_aligns_a_project_with_its_repository_in_chrome(self):
        self.skipTest("run in tests/test_ui_alignment.py")

    def rows(self, which: str = "") -> list:
        return self.browser.eval("[...document.querySelectorAll('.al-row')].filter((r) => r.getClientRects().length)"
                                 f".map((r) => r.dataset.o){which}")

    def test_FR_ORG1_AC_5_a_person_triages_with_origins_and_impact_in_chrome(self):
        b = self.browser
        pid = self.p.pid
        self.step("sign in")
        self.sign_in()
        self.step("read the repository")
        b.eval(f"location.hash = '#/p/{pid}/align'; true")
        b.wait("!!document.querySelector('[data-control=\"align_scan\"]')", "the Alignment view")
        b.click('[data-control="align_scan"]', what="Read the repository")
        said = b.wait("(document.querySelector('.al-triage-said') || {}).textContent", "the triage head", timeout=60)
        # what the current tests check is not an old plan; 2 conventions may be real risks (FR-ORG2)
        # an adopted project's conventions are Advise by default (FR-STR1): most are folded away, never counted
        self.assertEqual(said, "27 to decide: 21 taken from your project (6 may be from an old plan), 6 by "
                               "Rihmasto's convention (1 may be a real risk).")
        self.assertEqual(b.eval("document.querySelector('.al-triage-said').hasAttribute('data-ud')"), True)
        advice = b.eval("document.querySelector('.al-advice [data-about=\"defer_convention\"]').textContent")
        self.assertTrue(advice.startswith("Leave the 5 items of Rihmasto's convention for now"), advice)
        keys = ("[...document.querySelectorAll('.al-triage .al-acts [data-control=\"align_triage\"]')]"
                ".map((x) => x.dataset.key)")
        self.assertEqual(b.eval(keys), ["al-t:reject_stale", "al-t:defer_convention", "al-t:accept_current"])
        self.step("each item says its origin and impact")
        us1 = self.row("User Story 1")
        row = f".al-row[data-id=\"{us1}\"]"
        self.assertEqual(b.eval(f"document.querySelector('{row}').dataset.o"), "project current")
        self.assertIn("specs/001-loan-items/spec.md:7, last committed 2026-01-05; its file is 55 days older than the "
                      "code's latest change, but current tests check it",
                      b.eval(f"document.querySelector('{row} .al-origin').textContent"))
        self.assertIn("Accept adds US-1 with 2 criteria",
                      b.eval(f"document.querySelector('{row} .al-impact').textContent"))
        heads = b.eval("[...document.querySelectorAll('#al-g-gaps-h ~ .card-tools .chip')].map((x) => x.textContent)")
        self.assertIn("10 Rihmasto's convention", heads)
        self.step("filter by origin")
        b.click('[data-key="al-f:convention"]', what="Rihmasto's convention")
        shown = self.rows()
        self.assertEqual((len(shown), set(shown)), (13, {"convention"}))
        b.click('[data-key="al-f:old"]', what="May be an old plan")
        self.assertTrue(all("old" in x for x in self.rows()))
        b.click('[data-key="al-f:deferred"]', what="Deferred")
        b.wait("!!document.querySelector('[data-empty=\"align_filter\"]:not([hidden])')", "nothing deferred yet")
        b.click('[data-key="al-f:all"]', what="Everything")
        self.step("accept all tasks after their impact")
        b.click('[data-key="al-bulk:tasks"]', what="Accept all open tasks")
        text = b.wait("(document.querySelector('.al-group .al-confirm') || {}).textContent", "the impact of the tasks")
        self.assertIn("5 tasks kept in the project's records (3 done, 2 open)", text)
        self.assertIn("Your repository is never written", text)
        self.assertEqual(ar.accepted(self.p, "tasks"), [])                       # nothing before Confirm
        b.eval("document.querySelector('.al-group .al-confirm').scrollIntoView({block: 'center'}); true")
        self.step("confirm the tasks")
        b.click('.al-group [data-key="al-confirm-ok"]', what="Confirm")
        b.wait("!!document.querySelector('[aria-labelledby=\"al-g-tasks-h\"]') && ![...document.querySelectorAll("
               "'[aria-labelledby=\"al-g-tasks-h\"] .al-row')].some((r) => r.dataset.status !== 'accepted')",
               "tasks accepted")
        self.assertEqual(len(ar.accepted(self.p, "tasks")), 5)
        self.step("defer a gap and bring it back")
        gap = b.eval("document.querySelector('[aria-labelledby=\"al-g-gaps-h\"] .al-row').dataset.id")
        tags = f"(document.querySelector('.al-row[data-id=\"{gap}\"]') || {{dataset: {{}}}}).dataset.o"
        b.click(f'[data-key="al-defer:{gap}"]', what="Defer a gap")
        b.wait(f"{tags} === 'convention deferred'", "the gap deferred")
        self.assertEqual(list(tri.deferred(self.p)), [gap])
        b.click(f'[data-key="al-defer:{gap}"]', what="Bring back")
        b.wait(f"{tags} === 'convention'", "the gap back")
        self.step("defer the convention items from the head")
        b.click('[data-key="al-t:defer_convention"]', what="Defer convention items")
        text = b.wait("(document.querySelector('.al-triage .al-confirm') || {}).textContent", "its impact")
        self.assertIn("set aside as deferred", text)
        b.eval("document.querySelector('.al-triage .al-confirm').scrollIntoView({block: 'center'}); true")
        self.step("confirm the deferral")
        b.click('.al-triage [data-key="al-confirm-ok"]', what="Confirm the deferral")
        b.wait("(document.querySelector('.al-triage-said') || {textContent: ''}).textContent"
               ".includes('5 deferred')", "the convention items deferred")
        self.step("reject the stale items from the head")
        b.click('[data-key="al-t:reject_stale"]', what="Reject stale")
        b.click('.al-triage [data-key="al-confirm-ok"]', what="Confirm the rejection")
        b.wait("!document.querySelector('[data-key=\"al-t:reject_stale\"]')", "no stale item left")
        rejected = self.p.ledger().of_kind("alignment_rejected")[-1]["event"]["payload"]["items"]
        self.assertGreaterEqual(len(rejected), 4)                       # the stale tasks were accepted above
        for word in ("Light", "Dark"):
            self.step(f"{word.lower()} theme at 1440 px")
            self.width(1440)
            self.theme(word)
            b.wait("!!document.querySelector('#al-triage-h')", f"the head in the {word} theme at 1440 px")
            b.eval("document.querySelector('#al-triage-h').scrollIntoView(); true")
            self.step(f"{word.lower()} theme at 390 px")
            self.width(390)
            b.wait("!!document.querySelector('#al-triage-h') && window.innerWidth === 390", "the head at 390 px")
            b.eval("document.querySelector('#al-g-criteria-h').scrollIntoView(); true")
        self.check()
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)                    # never written
        self.assertEqual(git(self.repo, "status", "--porcelain", "--untracked-files=all"), "")


if __name__ == "__main__":
    unittest.main()
