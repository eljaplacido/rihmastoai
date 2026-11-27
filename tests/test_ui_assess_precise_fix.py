"""A precise assessment checked again, in a real browser (FR-ASP2-AC-8): headless Chrome over the DevTools protocol.

The invented local project of tests/test_assess_precise_fix.py (no route, container or deploy file; unittest
packages with their own roots; requirements in tables and JSON; an issue log) is adopted and assessed; the cockpit
runs on this build's port (9342) and Chrome's DevTools on RIHMA_DEVTOOLS_PORT when it is set. A developer reads the
three lines on top (worth acting on now, gaps to close, probably noise), brings a finding put off for later back with
Relevant now, and opens the Board, whose briefing says what the assessment finds worth acting on; each is looked at in
dark and light, at 1440 and 390 px, with every control named, nothing scrolling sideways and no console error, failed
request or CSP violation. Skipped when Chrome or git is missing.
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

from test_assess import no_scanner  # noqa: E402
from test_assess_precise_fix import WHO, lantern  # noqa: E402
import test_ui_assess as ua  # noqa: E402  (the module, so its TestCase is not collected here again)
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import assess, roads  # noqa: E402
from kernel.adopt import adopt  # noqa: E402
from kernel.store import Factory  # noqa: E402

PORT = 9342


class UiPreciseFixTest(unittest.TestCase):
    step, check, width, theme, sign_in = (ua.UiAssessTest.step, ua.UiAssessTest.check, ua.UiAssessTest.width,
                                          ua.UiAssessTest.theme, ua.UiAssessTest.sign_in)

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None or shutil.which("git") is None:
            raise unittest.SkipTest("Chrome and git are needed")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-aspfix-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.project = adopt(cls.factory, "Lantern", source=str(lantern(cls.tmp / "lantern")), intent="monitor", **WHO,
                            suite_timeout=120)
        cls.record = assess.assess(cls.project, **WHO, which=no_scanner)
        cls.server, cls.bootstrap = make_server(cls.factory, PORT, runner=QuietRunner())
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

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-aspfix")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def open_view(self) -> None:
        self.browser.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.project.pid}/assessment"})
        self.browser.wait("!!document.querySelector('#asp-head-h') && !!document.querySelector('#asp-tests-h')",
                          "the lines on top and Tests")

    def open_board(self) -> None:
        self.browser.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.project.pid}/board"})
        self.browser.wait("!!document.querySelector('[data-id=\"dev_assessment\"]')", "the briefing's assessment line")

    def test_FR_ASP2_AC_8_a_person_reads_three_lines_brings_a_finding_back_and_lands_on_the_assessment(self):
        b = self.browser
        self.step("fix sign in")
        self.sign_in()
        self.step("fix read the three lines")
        self.open_view()
        lines = b.eval("[...document.querySelectorAll('[aria-labelledby=\"asp-head-h\"] .asp-lines [data-ud]')]"
                       ".map((x) => x.textContent)")
        self.assertTrue(lines[0].startswith("Worth acting on now:"), lines)
        self.assertTrue(lines[1].startswith("Gaps to close:"), lines)
        self.assertTrue(lines[2].startswith("Probably noise:"), lines)
        self.assertIn("for later", lines[2])
        later = next(c for c in self.record["checks"] if c["key"] == "security.policy")["id"]
        self.assertTrue(b.eval(f"!!document.querySelector('[data-id=\"{later}\"] .asp-later')"), later)

        self.step("fix ask rihma for the next steps")
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "In the assessment, what is worth acting on and what is noise?")
        b.click("#as-send", what="Send")
        b.wait("document.querySelectorAll('#as-log .msg.bot .as-steps [data-key^=\"step:\"]').length >= 2",
               "a button for each next step")
        self.step("fix ask rihma answered")
        b.click('#as-log .msg.bot .as-steps [data-key$=":map_runner"]', what="the step's own button")
        b.wait("document.activeElement && !!document.activeElement.closest('[aria-labelledby=\"asp-tests-h\"], "
               "[data-control=\"assessment_runner_map\"]')", "the runner's control, focused")
        b.eval("(document.querySelector('#as-close') || {click() {}}).click()")
        self.open_view()

        self.step("fix bring a finding back")
        b.click(f'[data-key="asp-now:{later}"]', what="Relevant now")
        b.wait(f"!document.querySelector('[data-id=\"{later}\"] .asp-later')", "the finding no longer for later")
        b.wait("[...document.querySelectorAll('[role=\"status\"], .toast, #say')].some((x) =>"
               f" x.textContent.includes({json.dumps(later + ': relevant, signed by')}))", "the verdict, said")
        kept = json.loads((self.factory.project(self.project.pid).path("assessments", "relevance.json"))
                          .read_text(encoding="utf-8"))
        self.assertEqual(kept["security.policy"]["verdict"], "relevant")

        self.step("fix land on the board")
        self.open_board()
        step = b.eval("document.querySelector('[data-id=\"dev_next\"]').textContent")
        self.assertIn("Act on the assessment", step)
        self.assertIn("Worth acting on now:", step)
        self.assertIn("Gaps to close:", b.eval("document.querySelector('[data-id=\"dev_assessment\"]').textContent"))
        self.assertTrue(b.eval("!!document.querySelector('[data-key=\"dev:assessment\"], [data-key=\"dev:next\"]"
                               "[href$=\"/assessment\"]')"), "a way to the assessment from the landing")
        for theme in ("Dark", "Light"):
            self.step(f"fix theme {theme.lower()}")
            self.width(1440)
            self.theme(theme)
            for px in (1440, 390):
                self.step(f"fix look {theme.lower()} {px} assessment")
                self.width(px)
                self.open_view()
                self.step(f"fix look {theme.lower()} {px} for later")
                b.eval("(document.querySelector('.asp-later') || document.body).scrollIntoView({block: 'center'})")
                self.step(f"fix look {theme.lower()} {px} board")
                self.open_board()
                b.eval("document.querySelector('[data-id=\"dev_assessment\"]').scrollIntoView({block: 'center'})")
        self.check()


if __name__ == "__main__":
    unittest.main()
