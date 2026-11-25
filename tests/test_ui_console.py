"""FR-CON1-AC-8 and FR-CHK1-AC-9: the Console tab and Health in a real browser (headless Chrome over the
DevTools protocol, as tests/test_ui_drive.py).

A developer opens a project's Console tab, runs a command and watches its output stream in, runs a long one
and stops it, and opens a terminal here (a stand-in launcher: no window opens). On the project's Health tab
they enable the secret scan and run it (passed), enable a custom check whose command fails (failed, and the
project's line says so), then see the failing check on the Health page and on Home. Dark at 1440 px, then
light at 390 px. After every step there is no console error, failed request or Content-Security-Policy
violation, every control has a name, and nothing is wider than the screen. Skipped when Chrome is not
installed.
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

from console_fakes import PERSON, Launcher, attached, fake_tool, git_repo  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402
from test_ui_shape_models import NAMELESS, OVERFLOW  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.store import Factory  # noqa: E402


class ConsoleUiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-console-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bin_dir = self.tmp / "bin"
        fake_tool(bin_dir, "smoke-test", "import sys\nprint('smoke: 2 endpoints answer 500')\nsys.exit(1)\n")
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes"),
                                               "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.factory = Factory(self.tmp / "home")
        repo = git_repo(self.tmp / "orders", {"README.md": "# Orders\n", "Makefile": "build:\n\techo built\n",
                                              "tests/test_ok.py": "import unittest\n\n\nclass T(unittest.TestCase):\n"
                                                                  "    def test_ok(self):\n        self.assertTrue(True)\n"})
        self.p = attached(self.factory, repo)
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        self.launcher = Launcher()
        self.server.terminal_launcher = self.launcher
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

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
        self.assertEqual(b.eval(NAMELESS), [], f"controls with no name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"console-{b.step.replace(' ', '-')}.png")

    def sign_in(self, persona: str = "developer") -> None:
        b = self.browser
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what="the persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def narrow(self) -> None:
        b = self.browser
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        time.sleep(0.3)

    def open(self, route: str, ready: str, what: str) -> None:
        self.browser.cmd("Page.navigate", {"url": f"{self.server.origin}/{route}"})
        self.browser.wait(ready, what)

    def state_is(self, state: str) -> str:
        return f"document.querySelector('#con-state [data-state]')?.dataset.state === {json.dumps(state)}"


class ConsoleUiTest(ConsoleUiCase):
    def test_FR_CON1_AC_8_a_developer_runs_streams_stops_and_opens_a_terminal_in_chrome_dark_and_light(self):
        b, pid = self.browser, self.p.pid
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("the console tab")
        self.open(f"#/p/{pid}/console", "!!document.querySelector('#con-line')", "the Console tab")
        self.assertIn("make build", b.eval("document.querySelector('.con-offers').textContent"))
        self.assertIn("full-screen program belongs in a real terminal", b.eval("document.querySelector('.q').textContent"))
        self.step("run a command")
        b.type("#con-line", "python -c \"print('hello from the console')\"")
        b.click('[data-key="console-run"]', what="Run")
        b.wait("document.querySelector('#con-out').textContent.includes('hello from the console') && "
               + self.state_is("done"), "the output and Done", timeout=30)
        self.assertIn("Done", b.eval("document.querySelector('#con-state').textContent"))
        self.step("an offered command")
        b.click('[data-key="console-offer:0"]', what="the first offered command")
        b.wait("document.querySelector('#con-out').textContent.includes('$ ')", "its output", timeout=30)
        b.wait(f"!({self.state_is('running')})", "it ended", timeout=60)
        self.step("stop a long run")
        b.type("#con-line", "python -c \"import time; print('waiting', flush=True); time.sleep(30)\"")
        b.click('[data-key="console-run"]', what="Run")
        b.wait("document.querySelector('#con-out').textContent.includes('waiting') && "
               "!document.querySelector('[data-key=\"console-stop\"]').disabled", "the long run streaming", timeout=30)
        b.click('[data-key="console-stop"]', what="Stop")
        b.wait(self.state_is("stopped"), "Stopped", timeout=30)
        self.assertIn("stopped by a person", b.eval("document.querySelector('#con-out').textContent"))
        ran = [r["event"]["payload"] for r in self.p.ledger().of_kind("console_ran")]
        self.assertEqual([r["state"] for r in ran][-1], "stopped")
        self.assertEqual({r["person"] for r in ran}, {PERSON})
        self.step("open a terminal here")
        b.click('[data-key="console-terminal"]', what="Open a terminal here")
        deadline = time.monotonic() + 10
        while not self.launcher.calls and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(len(self.launcher.calls), 1)
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        self.open(f"#/p/{pid}/console", "!!document.querySelector('#con-line') && "
                  "document.querySelector('#con-out').textContent.length > 0", "the Console tab, narrow")
        self.check()


class HealthUiTest(ConsoleUiCase):
    def enable(self, kind: str, name: str = "", **options) -> None:
        b = self.browser
        b.eval(f"(() => {{ const s = document.querySelector('#hl-kind'); s.value = {json.dumps(kind)};"
               " s.dispatchEvent(new Event('change', {bubbles: true})); return true; })()")
        if name:
            b.type("#hl-name", name)
        for key, value in options.items():
            b.type(f"#hl-o-{key}", value)
        b.click('[data-key="health-enable"]', what="Enable the check")

    def test_FR_CHK1_AC_9_health_per_project_across_the_factory_and_on_home_in_chrome_dark_and_light(self):
        b, pid = self.browser, self.p.pid
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("the health tab")
        self.open(f"#/p/{pid}/checks", "!!document.querySelector('#hl-kind')", "the Health tab")
        self.assertIn("No check enabled yet", b.eval("document.querySelector('#hl-list').textContent"))
        self.step("enable and run the secret scan")
        self.enable("secrets")
        b.wait("!!document.querySelector('[data-key=\"check:secrets\"]')", "the secret scan listed")
        self.assertIn("Not run yet", b.eval("document.querySelector('[data-key=\"check:secrets\"]').textContent"))
        b.click('[data-key="health-run:secrets"]', what="Run now")
        b.wait("document.querySelector('[data-key=\"check:secrets\"] [data-verdict]').dataset.verdict === 'passed'",
               "Passed", timeout=60)
        self.step("a failing custom check")
        self.enable("custom", "smoke", command="smoke-test")
        b.wait("!!document.querySelector('[data-key=\"check:custom:smoke\"]')", "the custom check listed")
        b.click('[data-key="health-run:custom:smoke"]', what="Run now")
        b.wait("document.querySelector('[data-key=\"check:custom:smoke\"] [data-verdict]').dataset.verdict === 'failed'",
               "Failed", timeout=60)
        b.wait("document.querySelector('#hl-line').textContent.includes('1 check failing')", "the project's line")
        self.assertIn("2 endpoints answer 500", b.eval("document.querySelector('[data-key=\"check:custom:smoke\"]').textContent"))
        self.step("the health page")
        b.click('#sb-nav a[href="#/health"]', what="Health in the sidebar")
        b.wait("location.hash === '#/health' && !!document.querySelector('#hl-failing-list')", "the Health page")
        self.assertIn("Custom check (smoke)", b.eval("document.querySelector('#hl-failing-list').textContent"))
        self.assertIn("Passed", b.eval("document.querySelector('#main .tbl').textContent"))
        self.step("home")
        self.open("#/home", "!!document.querySelector('#home-health .card')", "the health card on Home")
        self.assertIn("1 check failing", b.eval("document.querySelector('#home-health .card').textContent"))
        b.click('[data-key="home:health"]', what="Open Health from Home")
        b.wait("location.hash === '#/health'", "the Health page from Home")
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        b.wait("!!document.querySelector('#hl-failing-list')", "the Health page, narrow")
        self.check()
        self.open(f"#/p/{pid}/checks", "!!document.querySelector('[data-key=\"check:custom:smoke\"]')",
                  "the Health tab, narrow")
        self.check()


class HealthAndInsightsUiTest(ConsoleUiCase):
    """Health (the checks) and Insights (the dimensions) side by side: each once in the sidebar, a failing check
    said once on Home, and measured in Insights' health from the check's own record."""

    def test_FR_INS1_AC_10_health_and_insights_are_each_once_in_the_sidebar_and_home_says_a_failing_check_once(self):
        from kernel.checks import store as cstore

        b = self.browser
        cstore.enable(self.p, "custom:smoke", person=PERSON, persona="developer", config={"command": "smoke-test"})
        self.assertEqual(cstore.run(self.p, "custom:smoke", person=PERSON, persona="developer")["verdict"], "failed")
        self.step("sign in")
        self.sign_in()
        self.step("the sidebar")
        hrefs = b.eval("[...document.querySelectorAll('#sb-nav a')].map((a) => a.getAttribute('href'))")
        labels = b.eval("[...document.querySelectorAll('#sb-nav a')].map((a) => a.textContent.trim())")
        self.assertEqual((hrefs.count("#/health"), hrefs.count("#/insights")), (1, 1), hrefs)
        self.assertEqual(len(labels), len(set(labels)), f"a sidebar label twice: {labels}")
        self.step("home")
        self.open("#/home", "!!document.querySelector('#home-health .card')", "the health card on Home")
        said = b.eval("(document.querySelector('#main').textContent.match(/Custom check \\(smoke\\)/g) || []).length")
        self.assertEqual(said, 1, "Home says the failing check once")
        self.step("insights")
        b.click('#sb-nav a[href="#/insights"]', what="Insights in the sidebar")
        b.wait("!!document.querySelector('#insights .ins-tile[data-tile=\"checks\"]')", "the checks tile in Insights")
        tile = b.eval("document.querySelector('#insights .ins-tile[data-tile=\"checks\"]').textContent")
        self.assertNotIn("not measured", tile.lower())
        self.assertIn("1 check failed its last run", tile)
        self.check()


if __name__ == "__main__":
    unittest.main()
