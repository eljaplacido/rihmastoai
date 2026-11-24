"""FR-HRN1-AC-10: Settings > Runners and the Project settings runner line in a real browser (headless Chrome over the
DevTools protocol, as tests/test_ui_drive.py).

A developer opens Runners from Settings, checks what is on this machine (a fake Claude Code written by the test: no
real harness runs), and chooses it for the builder; it waits on IT. An IT person approves it on the page, and from
then the factory's builder shows Claude Code with its pinned version and "Checked after the run", never Gnomon's
in-run assurance. Project settings shows the project's builder and verifier with their assurance and links to the
page. Dark at 1440 px, then light at 390 px. After every step there is no console error, failed request or
Content-Security-Policy violation, every control has a name, and nothing is wider than the screen. Skipped when
Chrome is not installed (``RIHMA_CHROME`` names another browser).
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

from factory_fakes import isolated_routing  # noqa: E402
from runner_fakes import fake_harness, use  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402
from test_ui_shape_models import NAMELESS, OVERFLOW  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.runners import choice  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Dana Developer"
IN_RUN, AFTER = "In-run policy enforced by Gnomon", "Checked after the run"
# Whether the element a selector names holds a text: a page expression for Browser.wait.
HAS = "((sel, text) => ((document.querySelector(sel) || {}).textContent || '').includes(text))"


class RunnersUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-runners-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolated_routing(self, self.tmp)
        for kind in ("gnomon", "codex", "opencode", "command"):              # never the real ones on this machine
            use(self, kind, [str(self.tmp / "nowhere" / kind)])
        use(self, "claude-code", fake_harness(self.tmp / "bin", "claude-code"))
        docker = mock.patch("kernel.runners.sandbox.docker_status",
                            return_value={"available": False, "version": None, "why": "Docker is not on this machine"})
        docker.start()
        self.addCleanup(docker.stop)
        self.factory = Factory(self.tmp / "home")
        self.p = self.factory.new_project("Old intranet", maturity="demo", mode="mixed")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
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
            b.screenshot(self.shots / f"runners-{b.step.replace(' ', '-')}.png")

    def persona(self, persona: str, *, first: bool = False) -> None:
        b = self.browser
        if first:
            b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
            b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
                   "the signed-in page")
        b.click("#person-chip", what="the person chip")
        if first:
            b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what="the persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def open_runners(self) -> None:
        b = self.browser
        b.eval("location.hash = '#/settings'; true")
        b.click('[data-key="set:runners"]', what="Open Runners in Settings")
        b.wait("location.hash === '#/runners' && !!document.querySelector('#rn-applies-factory-h')", "the Runners page")

    def text(self, selector: str) -> str:
        return self.browser.eval(f"(document.querySelector({json.dumps(selector)}) || {{}}).textContent || ''")

    def test_FR_HRN1_AC_10_a_runner_is_chosen_approved_by_it_and_shown_with_its_assurance_in_chrome(self):
        b = self.browser
        self.step("sign in")
        self.persona("developer", first=True)
        self.theme("dark", "Dark")
        self.step("runners")
        self.open_runners()
        self.assertIn(IN_RUN, self.text('#main [data-key="rn-applies:builder"]'))
        self.step("check this machine")
        b.click('[data-key="rn-check"]', what="Check")
        b.wait(f"{HAS}('[data-key=\"rn-found:claude-code\"]', 'Found 2.1.0')", "Claude Code found")
        self.assertIn("Not found", self.text('[data-key="rn-found:codex"]'))
        self.assertIn("Docker is not on this machine", self.text('[data-key="rn-docker"]'))
        self.step("choose claude code")
        b.click('[data-key="rn-choose"]', what="Choose a runner")
        b.wait("!!document.querySelector('#rn-runner')", "the form")
        b.eval("(() => { const s = document.querySelector('#rn-runner'); s.value = 'claude-code';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        self.assertEqual(b.eval("document.querySelector('#rn-version').placeholder"), "2.1.0")
        b.type("#rn-reason", "the team's standard harness")
        b.click('[data-key="rn-save"]', what="Choose this runner")
        b.wait(f"!document.querySelector('#modal').open && {HAS}('[data-key=\"rn-choice:RN-001\"]', 'Waiting on IT')",
               "the choice waiting on IT")
        self.assertIn(IN_RUN, self.text('#main [data-key="rn-applies:builder"]'))        # not yet: Gnomon still
        self.assertIn("IT decides", self.text('[data-key="rn-choice:RN-001"]'))
        self.step("it approves")
        self.persona("it")
        self.open_runners()
        b.click('[data-key="rn-approve:RN-001"]', what="Approve RN-001")
        b.wait(f"{HAS}('[data-key=\"rn-choice:RN-001\"]', 'In use')", "the choice in use")
        builder = self.text('#main [data-key="rn-applies:builder"]')
        self.assertIn("Claude Code 2.1.0", builder)
        self.assertIn(AFTER, builder)
        self.assertNotIn(IN_RUN, builder)                                                # never Gnomon's words
        self.assertIn(IN_RUN, self.text('#main [data-key="rn-applies:verifier"]'))
        self.step("light and narrow")
        self.theme("light", "Light")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1,
                                                      "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        time.sleep(0.3)
        self.step("project settings")
        b.eval(f"location.hash = '#/p/{self.p.pid}/overview'; true")
        b.click('[data-key="project-settings"]', what="Project settings")
        b.wait(f"{HAS}('[data-key=\"ps-runner:builder\"]', 'Claude Code 2.1.0')", "the project's runner line")
        self.assertIn(AFTER, self.text('[data-key="ps-runner:builder"]'))
        self.assertIn(IN_RUN, self.text('[data-key="ps-runner:verifier"]'))
        b.click('[data-key="ps-runners"]', what="Change in Settings > Runners")
        b.wait(f"location.hash === '#/runners/{self.p.pid}' && !!document.querySelector('#rn-applies-{self.p.pid}-h')",
               "the project's runners")
        self.check()
        fp = factory_project(self.factory)
        proposed = fp.ledger().of_kind("runner_proposed")[-1]["event"]["payload"]
        self.assertEqual([proposed[k] for k in ("person", "runner", "version")], [PERSON, "claude-code", "2.1.0"])
        decided = [r["event"]["payload"] for r in fp.ledger().of_kind("decision")]
        self.assertEqual([(d["persona"], d["verdict"]) for d in decided], [("it", "approve")])
        self.assertEqual(choice.effective(self.factory, self.p.pid, "builder")["runner"], "claude-code")


if __name__ == "__main__":
    unittest.main()
