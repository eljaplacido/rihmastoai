"""A precise assessment in a real browser (FR-ASP1-AC-7): headless Chrome over the DevTools protocol.

An invented adopted repository (tests/test_assess_precise.py) is assessed; the cockpit runs on this build's port
(9330) and Chrome's DevTools on RIHMA_DEVTOOLS_PORT when it is set. A developer reads the two lines on top, marks a
finding not relevant with a reason, marks a secret a fixture and maps the project's own test runner, each shown on
the page after it; the view is looked at in dark and light, at 1440 and 390 px, with every control named, nothing
scrolling sideways and no console error, failed request or CSP violation. Skipped when Chrome or pytest is missing.
"""

import contextlib
import importlib.util
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
from test_assess_precise import PORT, adopted, secrets  # noqa: E402
import test_ui_assess as ua  # noqa: E402  (the module, so its TestCase is not collected here again)
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import assess, roads  # noqa: E402
from kernel.store import Factory  # noqa: E402


class UiPreciseTest(unittest.TestCase):
    step, check, width, theme, sign_in = (ua.UiAssessTest.step, ua.UiAssessTest.check, ua.UiAssessTest.width,
                                          ua.UiAssessTest.theme, ua.UiAssessTest.sign_in)

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None or shutil.which("git") is None or importlib.util.find_spec("pytest") is None:
            raise unittest.SkipTest("Chrome, git and pytest are needed")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-precise-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.project = adopted(cls.factory, cls.tmp)
        cls.record = assess.assess(cls.project, person="Ida Example", persona="developer", which=no_scanner)
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
        self.browser = Browser(self.chrome, self.tmp / "chrome-precise")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def open_view(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.project.pid}/assessment"})
        b.wait("!!document.querySelector('#asp-head-h') && !!document.querySelector('#asp-tests-h')", "the two lines and Tests")

    def test_FR_ASP1_AC_7_a_person_reads_what_to_act_on_and_marks_noise_in_chrome(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.step("read the two lines")
        self.open_view()
        lines = b.eval("[...document.querySelectorAll('[aria-labelledby=\"asp-head-h\"] .asp-lines [data-ud]')].map((x) => x.textContent)")
        self.assertTrue(lines[0].startswith(("Worth acting on now:", "Nothing needs acting on now:")), lines)
        self.assertTrue(lines[-1].startswith("Probably noise:"), lines)     # after the gaps to close (FR-ASP2)
        self.assertTrue(b.eval("!!document.querySelector('[data-key=\"asp-next:map_runner\"]')"))

        found = secrets(self.record)
        url, real = found["packages/engine/attach.py"]["id"], found["packages/engine/settings.py"]["id"]
        self.step("mark a finding not relevant")
        b.click(f'[data-key="asp-nr:{url}"]', what="Not relevant here")
        b.type(f"#asp-why-{url}", "attachment paths are public by design")
        b.click(f'[data-key="asp-save:{url}"]', what="Save")
        b.wait(f"!!document.querySelector('[data-id=\"{url}\"] .asp-dismissed')", "the finding marked not relevant")
        self.assertIn("attachment paths are public by design",
                      b.eval(f"document.querySelector('[data-id=\"{url}\"] .asp-dismissed').textContent"))

        self.step("mark a secret a fixture")
        b.click(f'[data-key="asp-fix:{real}"]', what="Mark as fixture")
        b.wait(f"((document.querySelector('[data-id=\"{real}\"] .asp-likely') || {{}}).textContent || '')"
               ".includes('Marked as a fixture by')", "the secret marked a fixture")

        self.step("map the runner")
        b.type("#asp-run-command", "py -3 tools/gates.py test")
        b.type("#asp-run-results", "build/gates.xml")
        b.click('[data-key="asp-run-save"]', what="Map its test runner")
        b.wait("[...document.querySelectorAll('[role=\"status\"], .toast, #say')].some((x) =>"
               " x.textContent.includes('Mapped, signed by'))", "the runner mapped, said")
        self.assertEqual(self.project.read("assessments/runner.json")["command"], "py -3 tools/gates.py test")
        self.open_view()
        self.assertEqual(b.eval("document.querySelector('#asp-run-command').value"), "py -3 tools/gates.py test")
        for theme in ("Dark", "Light"):
            self.width(1440)
            self.theme(theme)
            for px in (1440, 390):
                self.step(f"look {theme.lower()} {px}")
                self.width(px)
                self.open_view()
                for part, sel in (("tests", "#asp-tests-h"), ("verdicts", f'[data-id="{url}"]')):
                    self.step(f"look {theme.lower()} {px} {part}")
                    b.eval(f"document.querySelector({json.dumps(sel)}).scrollIntoView({{block: 'start'}})")
        self.check()


if __name__ == "__main__":
    unittest.main()
