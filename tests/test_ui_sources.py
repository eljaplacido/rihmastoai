"""FR-SRC1-AC-7: a project's own sources in a real browser (headless Chrome over the DevTools protocol).

Over tests/native_fixture.py's repository, adopted: a developer opens the Overview, where What Rihmasto understood
shows the Project's own sources with What to do next; maps the rule files from the first step, opens the folded
panel, uses the old requirements document anyway, imports a gate's results produced on a build host, and sees each
requirement's result in the trace; then in Project settings changes the source's schedule without submitting the
settings. First in the dark theme at 1440 px, then in the light theme at 390 px. After every step there is no
console error, failed request or CSP violation, every control has a name and nothing is wider than the screen. The
cockpit listens on port 9310 and Chrome's DevTools on 9810 (``RIHMA_SRC_PORT``, ``RIHMA_SRC_DEVTOOLS``). Skipped
when Chrome is not installed. ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
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
from kernel import native_sources, native_tests  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Example"
PORT = int(os.environ.get("RIHMA_SRC_PORT") or 9310)
DEVTOOLS = int(os.environ.get("RIHMA_SRC_DEVTOOLS") or 9810)
UNNAMED = """[...document.querySelectorAll('#main button, #main a[href], #main input, #main textarea, #modal button, #modal input')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim() || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA' && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


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


class UiSourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = drive.find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        from kernel.adopt import adopt

        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-src-")).resolve()
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
            b.screenshot(self.shots / f"sources-{b.step.replace(' ', '-')}.png")

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
        b.wait("!!document.querySelector('#ov-understood-h') && !!document.querySelector('.src-panel .src-next')",
               "What Rihmasto understood with the project's own sources")
        first = b.eval("document.querySelector('[data-key=\"src-next:0\"]').textContent")
        self.assertIn("Use rules/* as requirements", first)
        self.assertTrue(b.eval("!!document.querySelector('.src-item.stale[data-path=\"docs/requirements.md\"]')"))
        self.assertIn("Platform-wide", b.eval("document.querySelector('.src-scope').textContent"))
        self.fits_and_named()

    def map_and_trace(self) -> None:
        b = self.browser
        b.click('[data-key="src-next:0"]', what="Use rules/* as requirements")
        self.toast("Mapped as SRC-1", "the rule files mapped")
        b.wait("(document.querySelector('#ov-understood') || document.body).textContent.includes('Its own sources')",
               "the understanding with its own sources")
        b.wait("!!document.querySelector('.src-fold[open] .src-item[data-source=\"SRC-1\"]')",
               "the mapped source, the fold kept open while next steps remain (FR-SRC2)")
        self.step("use the old plan anyway")
        b.click('[data-key="src-anyway:docs/requirements.md"]', what="Use it anyway")
        self.toast("is used anyway", "the old plan used")
        self.assertEqual(native_sources.use_anyway_paths(self.p), ["docs/requirements.md"])
        self.step("import results from elsewhere")
        if not b.eval("!!document.querySelector('.src-fold[open]')"):
            b.click('[data-key="ov-sources"]', what="Project's own sources, folded")
        b.click('[data-key="src-import"]', what="Import results")
        b.type('[data-key="src-import-text"]', fx.JUNIT)
        b.type('[data-key="src-import-when"]', "2026-11-26T03:00:00Z")
        b.type('[data-key="src-import-where"]', "the build host")
        b.click('[data-key="src-import-ok"]', what="Import results, confirmed")
        self.toast("Imported: failed", "the import")
        if not b.eval("!!document.querySelector('.src-fold[open]')"):
            b.click('[data-key="ov-sources"]', what="Project's own sources, folded")
        b.wait("(document.querySelector('.src-trace tr[data-ref=\"RULE-004\"]') || {}).textContent?.includes('failed')",
               "RULE-004 failed in the trace")
        self.assertIn("passed", b.eval("document.querySelector('.src-trace tr[data-ref=\"RULE-001\"]').textContent"))
        run = native_tests.runs(self.p)[-1]
        self.assertEqual((run["machine"], run["by"]["person"]), ("the build host", PERSON))
        self.fits_and_named()

    def settings(self) -> None:
        b = self.browser
        b.click('[data-key="project-settings"]', what="Project settings")
        b.wait("!!document.querySelector('#modal .chg-sources .src-item[data-source=\"SRC-1\"]')",
               "the project's own sources in Project settings")
        b.click('#modal [data-key="src-change:SRC-1"]', what="Change on SRC-1")
        b.wait("!!document.querySelector('#modal [data-key=\"src-SRC-1-every\"]')", "the change form")
        b.eval("const s = document.querySelector('#modal [data-key=\"src-SRC-1-every\"]'); s.value = 'daily';"
               " s.dispatchEvent(new Event('change', {bubbles: true})); true")
        b.click('#modal [data-key="src-save:SRC-1"]', what="Save the change")
        b.wait("(document.querySelector('#status') || {}).textContent.includes('SRC-1 changed')", "the change saved")
        self.assertTrue(b.eval("document.querySelector('#modal').open"), "the settings dialog stays open")
        self.assertEqual(native_sources.active(self.p)[0]["every"], "daily")
        self.assertEqual(self.p.ledger().of_kind("settings_changed"), [], "the settings were not submitted")
        self.fits_and_named()
        self.step("settings closed")          # the dialog's own step is checked (and shot) while it is open
        b.key("Escape", 27)
        b.wait("!document.querySelector('#modal').open", "the dialog closed")

    def test_FR_SRC1_AC_7_a_developer_maps_uses_an_old_plan_imports_results_and_changes_it_dark_wide_light_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("the overview")
        self.overview()
        self.step("map the rule files")
        self.map_and_trace()
        self.step("project settings")
        self.settings()
        self.step("light and narrow")
        self.theme("light", "Light")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        b.eval(f"location.hash = '#/p/{self.p.pid}/overview'; true")
        b.wait("!!document.querySelector('#ov-understood-h') && !!document.querySelector('.src-panel .src-bar')",
               "the overview, narrow")
        if not b.eval("!!document.querySelector('.src-fold[open]')"):
            b.click('[data-key="ov-sources"]', what="Project's own sources, folded")
        b.wait("!!document.querySelector('.src-fold[open] .src-trace')", "the trace, narrow")
        time.sleep(0.3)
        self.fits_and_named()
        b.eval("document.querySelector('.src-trace').scrollIntoView(); true")
        self.check()


if __name__ == "__main__":
    unittest.main()
