"""A developer's Advance opens the developer briefing, in a real browser (FR-DEV2): headless Chrome over the DevTools
protocol, as tests/test_ui_drive.py drives it, on the neutral fixture of tests/test_devboard.py.

A developer presses Advance in the project's header: the run starts and a dialog shows the briefing (the next step
with why, what blocks it, the latest sessions, Got it and a link to the Board); Got it in the dialog is recorded. A
business owner pressing Advance gets no dialog. Dark and light, 1440 and 390 pixels wide, nothing scrolls sideways
and no step leaves a console error, a failed request or a CSP violation.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary) or git is missing.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_devboard as dev  # noqa: E402  (the module, so its TestCase is not collected here again)
from test_devboard import DEV  # noqa: E402

from kernel import devsessions  # noqa: E402

DIALOG = "#modal[open] .dv-brief .dv-next-t"


class UiDevAdvanceTest(dev.UiDevBoardTest):
    test_FR_DEV1_AC_6_the_board_and_the_trace_for_a_developer_dark_and_light_at_1440_and_390 = None
    test_FR_DEV1_AC_6_a_business_owner_reads_plain_words_and_asks_rihma = None

    def check(self) -> None:
        b = self.browser
        b.eval("1")
        time.sleep(0.3)
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"devadvance-{b.step.replace(' ', '-')}.png")

    def advance(self) -> None:
        b = self.browser
        b.eval("document.querySelector('#modal[open]') && document.querySelector('#modal').close(); true")
        b.eval(f"location.hash = '#/p/{self.p.pid}/overview'; true")
        b.wait("!!document.querySelector('[data-key=\"advance\"]:not([disabled])')", "the Advance button")
        b.click('[data-key="advance"]', what="Advance")

    def test_FR_DEV2_AC_3_a_developer_pressing_advance_gets_the_briefing(self):
        b = self.browser
        self.step("the developer presses advance")
        self.sign_in("developer")
        self.advance()
        said = b.wait(f"(document.querySelector('{DIALOG}') || {{}}).textContent", "the briefing in a dialog",
                      timeout=30)
        self.assertIn("Decide C-0001", said)
        self.assertTrue(b.eval("!!document.querySelector('#modal [data-key=\"dev:adv-board\"]')"))
        self.assertTrue(b.eval("!!document.querySelector('#modal .dv-brief [data-key=\"dev:seen\"]')"))
        self.step("got it in the dialog")
        b.click('#modal [data-key="dev:seen"]', what="Got it")
        b.wait("(document.querySelector('#modal .dv-brief .card-tools') || {}).textContent.includes('your last look')",
               "the briefing from the look")
        self.assertEqual(self.p.ledger().of_kind(devsessions.LOOKED)[-1]["event"]["payload"]["person"], DEV)
        self.step("open the board from the dialog")
        b.click('#modal [data-key="dev:adv-board"]', what="Open the development board")
        b.wait("location.hash.endsWith('/board') && !document.querySelector('#modal[open]')", "the Board, dialog closed")
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"{scheme} {width}")
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                             "mobile": width < 500})
                b.eval("document.querySelector('#modal[open]') && document.querySelector('#modal').close(); true")
                b.eval("location.reload(); true")
                time.sleep(0.5)
                b.wait("!!document.querySelector('.view-body')", "the page")
                self.assertEqual(b.eval("document.documentElement.dataset.theme"), scheme)
                b.eval(f"(async () => {{ const m = await import('/static/devadvance.js'); "
                       f"return m.briefAfterAdvance({self.p.pid!r}, {DEV!r}); }})()")
                b.wait(f"!!document.querySelector('{DIALOG}')", "the dialog", timeout=30)
                b.eval("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
                self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, (scheme, width))
                spills = b.eval("[...document.querySelectorAll('#modal .card, #modal .dv-next')]"
                                ".filter((c) => c.scrollWidth > c.clientWidth + 1).map((c) => c.className)")
                self.assertEqual(spills, [], (scheme, width))
        self.check()

    def test_FR_DEV2_AC_3_another_persona_pressing_advance_gets_no_dialog(self):
        b = self.browser
        self.step("a business owner presses advance")
        self.sign_in("business_owner")
        self.advance()
        time.sleep(1.5)
        self.assertFalse(b.eval("!!document.querySelector('#modal[open]')"))
        self.check()


if __name__ == "__main__":
    unittest.main()
