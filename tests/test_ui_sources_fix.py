"""FR-SRC2-AC-9: a project's own sources said truly, in a real browser (headless Chrome over the DevTools protocol).

Over tests/native_fixture.py's repository, adopted: a developer maps the rule files from What to do next and the
panel stays open with the next steps, among them Review 4 requirements to import and Set up the watch; maps the
issues file, stops it and resumes it from Stopped; asks Rihma where the project keeps its requirements and reads the
answer line by line; sees the issues file's open findings in Health, each at its place in the code; imports results
and sees its own tests in the header instead of the root's baseline; and opens Alignment from the review step. First
in the dark theme at 1440 px, then in the light theme at 390 px, where each trace row stacks with its result first.
After every step there is no console error, failed request or CSP violation, every control has a name and nothing
is wider than the screen. The cockpit listens on port 9312 and Chrome's DevTools on 9812 (``RIHMA_SRC2_PORT``,
``RIHMA_SRC2_DEVTOOLS``). Skipped when Chrome is not installed. ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per
step.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).parent))

import native_fixture as fx  # noqa: E402
import test_ui_drive as drive  # noqa: E402
from factory_fakes import FixedClock  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import native_sources  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Example"
PORT = int(os.environ.get("RIHMA_SRC2_PORT") or 9312)
DEVTOOLS = int(os.environ.get("RIHMA_SRC2_DEVTOOLS") or 9812)
UNNAMED = """[...document.querySelectorAll('#main button, #main a[href], #main input, #main textarea, #modal button, #modal input')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim() || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA' && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"
STEPS = "[...document.querySelectorAll('.src-fold[open] .src-steps li button')].map((x) => x.textContent)"


def _popen(real):
    def start(args, *a, **kw):
        return real([f"--remote-debugging-port={DEVTOOLS}" if str(x).startswith("--remote-debugging-port=") else x
                     for x in args], *a, **kw)
    return start


class FixedPortBrowser(drive.Browser):
    """test_ui_drive's Browser on its own fixed DevTools port."""

    def _devtools_port(self) -> tuple[int, str]:
        for _ in range(300):
            if self.proc.poll() is not None:
                raise RuntimeError(f"Chrome exited with {self.proc.returncode}")
            try:
                ws = drive._get_json(DEVTOOLS, "/json/version")["webSocketDebuggerUrl"]
                return DEVTOOLS, urlsplit(ws).path
            except (OSError, ValueError, KeyError):
                time.sleep(0.1)
        raise RuntimeError(f"Chrome did not open its DevTools port {DEVTOOLS}")


class UiSourcesSaidTrulyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = drive.find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        from kernel.adopt import adopt

        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-src2-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        repo = fx.make_repo(self.tmp / "repo")
        self.factory = Factory(self.tmp / "home", clock=FixedClock())
        self.p = adopt(self.factory, "Board engine", source=str(repo), intent="maintain", person=PERSON,
                       persona="developer", suite_timeout=60)
        self.server, self.bootstrap = make_server(self.factory, PORT, runner=drive.QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        with mock.patch.object(drive.subprocess, "Popen", _popen(subprocess.Popen)):
            self.browser = FixedPortBrowser(self.chrome, self.tmp / "chrome")
        self.browser.shots = self.shots
        self.addCleanup(self.browser.close)

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
        self.assertEqual(b.eval("window.__srcErrors || []"), [], f"uncaught page errors during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"sources2-{b.step.replace(' ', '-')}.png")

    def fits_and_named(self) -> None:
        b = self.browser
        self.assertEqual(b.eval(UNNAMED), [], f"controls without a name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def toast(self, words: str, what: str) -> None:
        b = self.browser
        b.wait(f"(document.querySelector('#status') || {{}}).textContent.includes({json.dumps(words)})", what)
        b.click("#status .toast .icon-btn", what="Dismiss on the message")
        b.wait("!document.querySelector('#status .toast')", "the message dismissed")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid .widget')",
               "the signed-in dashboard")
        b.eval("window.__srcErrors = []; window.addEventListener('error', (e) => window.__srcErrors.push(String(e.message)));"
               " window.addEventListener('unhandledrejection', (e) => window.__srcErrors.push(String(e.reason))); true")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def overview(self) -> None:
        b = self.browser
        b.eval(f"location.hash = '#/p/{self.p.pid}/overview'; true")
        b.wait("!!document.querySelector('.src-fold[open] .src-panel .src-next')", "the project's own sources, open")

    def map_keeps_the_fold_open(self) -> None:
        b = self.browser
        b.click('[data-key="src-next:0"]', what="Use rules/* as requirements")
        self.toast("Next: Review 4 requirements to import in Alignment", "mapped, with the next step said")
        b.wait("!!document.querySelector('.src-fold[open] .src-item[data-source=\"SRC-1\"]')",
               "the fold still open after the card drew again")
        steps = b.eval(STEPS)
        self.assertIn("Review 4 requirements to import", steps)
        self.assertIn("Set up the watch", steps)
        self.assertIn("not watched yet", b.eval("document.querySelector('.src-item[data-source=\"SRC-1\"]').textContent"))
        self.fits_and_named()

    def stop_and_resume(self) -> None:
        b = self.browser
        b.click('[data-key="src-map:findings:evidence/issues.jsonl"]', what="Map the issues file")
        self.toast("Mapped as SRC-2", "the issues file mapped")
        b.click('[data-key="src-stop:SRC-2"]', what="Stop on SRC-2")
        b.type('[data-key="src-reason:SRC-2"]', "moved to the tracker")
        b.click('[data-key="src-stop-ok:SRC-2"]', what="Stop reading it")
        self.toast("no longer read", "SRC-2 stopped")
        b.wait("!!document.querySelector('.src-item.stopped[data-source=\"SRC-2\"]')", "SRC-2 under Stopped")
        self.assertIn("moved to the tracker", b.eval("document.querySelector('.src-item.stopped').textContent"))
        self.assertFalse(b.eval("!!document.querySelector('[data-key=\"src-map:findings:evidence/issues.jsonl\"]')"),
                         "a stopped source is not offered again as found")
        self.assertNotIn("Use evidence/issues.jsonl as findings", b.eval(STEPS))
        self.fits_and_named()
        b.eval("document.querySelector('.src-item.stopped').scrollIntoView({block: 'center'}); true")
        self.step("resume the issues file")
        b.click('[data-key="src-resume:SRC-2"]', what="Resume SRC-2")
        self.toast("SRC-2 is read again", "SRC-2 resumed")
        self.assertEqual([s["id"] for s in native_sources.active(self.p)], ["SRC-1", "SRC-2"])

    def ask_rihma(self) -> None:
        b = self.browser
        b.click('[data-key="src-ask"]', what="Ask Rihma in the panel")
        b.wait("!!document.querySelector('#assistant .bub > p.ans') && document.querySelector('#assistant')"
               ".textContent.includes('keeps its own')", "Rihma's answer")
        p = "[...document.querySelectorAll('#assistant .bub > p.ans')].pop()"
        self.assertEqual(b.eval(f"getComputedStyle({p}).whiteSpace"), "pre-line")
        self.assertGreater(b.eval(f"{p}.getClientRects()[0].height / parseFloat(getComputedStyle({p}).lineHeight || 20)"),
                           3, "the answer is drawn line by line, not as one paragraph")
        self.fits_and_named()
        b.eval(f"{p}.scrollIntoView(); true")
        self.step("close ask rihma")         # the answer is checked (and shot) while the drawer is open
        b.click("#as-close", what="Close Ask Rihma")

    def health(self) -> None:
        b = self.browser
        b.eval(f"location.hash = '#/p/{self.p.pid}/checks'; true")
        b.wait("!!document.querySelector('#ev-own-findings [data-key=\"own-finding:ISS-1\"]')",
               "the project's own findings in Health")
        row = b.eval("document.querySelector('[data-key=\"own-finding:ISS-1\"]').textContent")
        self.assertIn("engine/core_3.py (evidence/issues.jsonl:1)", row)
        self.assertFalse(b.eval("!!document.querySelector('[data-key=\"own-finding:ISS-3\"]')"), "closed: not shown")
        self.fits_and_named()
        b.eval("document.querySelector('[data-control=\"evals_own_findings\"]').scrollIntoView(); true")

    def own_tests_in_the_header(self) -> None:
        b = self.browser
        self.overview()
        b.click('[data-key="src-import"]', what="Import results")
        b.type('[data-key="src-import-text"]', fx.JUNIT)
        b.type('[data-key="src-import-when"]', "2026-11-26T03:00:00Z")
        b.type('[data-key="src-import-where"]', "the build host")
        b.click('[data-key="src-import-ok"]', what="Import results, confirmed")
        self.toast("Imported: failed", "the import")
        b.wait("(document.querySelector('.adopted-line') || {}).textContent?.includes('its own tests')",
               "its own tests in the header")
        line = b.eval("document.querySelector('.adopted-line').textContent")
        self.assertNotIn("not measured (", line)
        self.assertIn("its own tests: imported results from the build host failed", line)
        self.fits_and_named()
        b.eval("document.querySelector('.adopted-line').scrollIntoView(); true")

    def review(self) -> None:
        b = self.browser
        b.click('.src-steps [data-control="sources_review"]', what="Review 4 requirements to import")
        b.wait(f"location.hash === '#/p/{self.p.pid}/align'", "Alignment opened")

    def test_FR_SRC2_AC_9_the_sources_are_said_truly_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("the overview")
        self.overview()
        self.fits_and_named()
        self.step("map keeps the fold open")
        self.map_keeps_the_fold_open()
        self.step("stop the issues file")
        self.stop_and_resume()
        self.step("ask rihma")
        self.ask_rihma()
        self.step("findings in health")
        self.health()
        self.step("own tests in the header")
        self.own_tests_in_the_header()
        self.step("light and narrow")
        self.theme("light", "Light")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        self.overview()
        b.wait("!!document.querySelector('.src-fold[open] .src-trace tr[data-ref=\"RULE-004\"]')", "the trace, narrow")
        time.sleep(0.3)
        self.fits_and_named()
        wrap = "document.querySelector('.src-table-wrap')"
        self.assertLessEqual(b.eval(f"{wrap}.scrollWidth - {wrap}.clientWidth"), 0, "no sideways scroll in the trace")
        row = "document.querySelector('.src-trace tr[data-ref=\"RULE-004\"]')"
        self.assertLess(b.eval(f"{row}.querySelector('.src-res').getBoundingClientRect().top"),
                        b.eval(f"{row}.querySelector('.src-req').getBoundingClientRect().top"), "the result comes first")
        self.assertLessEqual(b.eval(f"{row}.querySelector('.src-res').getBoundingClientRect().right"), 390)
        b.eval(f"{row}.scrollIntoView(); true")
        self.step("the trace, narrow")
        self.step("review in alignment")
        self.review()
        self.check()


if __name__ == "__main__":
    unittest.main()
