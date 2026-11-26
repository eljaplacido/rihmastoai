"""FR-HMD1-AC-8: the coding agent you already have, in a real browser (headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py).

From Home's "Set up a model" card a person with no API key sees "No API key? Claude Code ... found: use it", answers
every text role with it in one click, and the card goes. In Models setup each role shows the harness that answers it,
Test sends a tiny prompt through it and shows the latency, and the card "Use the coding agent you already have" lists
the harnesses found with their versions and answers the verifier with Codex. Dark at 1440 px, then light at 390 px.
After every step there is no console error, failed request or Content-Security-Policy violation, every control has a
name, and nothing is wider than the screen. Every coding agent is a fake executable (tests/harness_fakes.py).
Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser).
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_shape_models as shaped  # noqa: E402  (a module: its own test class is not run from here)
from factory_fakes import isolated_routing  # noqa: E402
from harness_fakes import fake_agent  # noqa: E402
from runner_fakes import use  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import harness_model as hm  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import Factory, write_json  # noqa: E402


class HarnessModelsUiTest(unittest.TestCase):
    UI = shaped.ShapeModelsUiTest
    step, check, sign_in, theme, narrow = UI.step, UI.check, UI.sign_in, UI.theme, UI.narrow

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-harness-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.routing = isolated_routing(self, self.tmp)
        for kind in ("claude-code", "codex"):
            use(self, kind, fake_agent(self.tmp / "agents", kind))
        hm._FOUND.clear()
        self.addCleanup(hm._FOUND.clear)
        # the assistant's local server is not running here, whatever runs on this machine's port 8080
        write_json(self.routing / "routing.local.json", {
            "roles": {"assistant": {"model": "qwen3.6-35b", "endpoint": "nothing"}},
            "endpoints": {"nothing": {"kind": "openai", "url": "http://127.0.0.1:9/v1/chat/completions"}}})
        found = mock.patch("kernel.models_setup.gnomon_found", return_value=False)   # no Gnomon either
        found.start()
        self.addCleanup(found.stop)
        self.factory = Factory(self.tmp / "home")
        self.factory.new_project("Old intranet", maturity="demo", mode="mixed")   # not a first run: no welcome dialog
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def row(self, role: str) -> str:
        return f"(document.querySelector('[data-key=\"model:{role}\"]') || {{}}).textContent || ''"

    def test_FR_HMD1_AC_8_a_person_with_no_api_key_uses_claude_code_and_codex_in_chrome_dark_and_light_wide_and_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in("it")
        self.theme("dark", "Dark")
        self.step("home offers the coding agent found")
        b.wait("!!document.querySelector('.setup-card [data-key=\"home:hm-use\"]')", "No API key? on the card")
        text = b.eval("document.querySelector('.setup-card').textContent")
        self.assertIn("No API key?", text)
        self.assertIn("Claude Code 2.1.331", text)
        self.assertIn("found: use it", text)
        self.assertIn("slower than an API endpoint", text)
        self.step("use claude code for every text role")
        b.click('[data-key="home:hm-use"]', what="Use Claude Code (your login)")
        b.wait("!document.querySelector('.setup-card')", "Home without the card")
        used = factory_project(self.factory).ledger().of_kind("models_use")[-1]["event"]["payload"]
        self.assertEqual((used["person"], used["harness"], used["roles"]),
                         ("Aino Virtanen", "claude-code", ["analyst", "holdout_author", "verifier", "assistant"]))
        self.step("models setup shows it and tests it")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/models"})
        b.wait("location.hash === '#/models' && document.querySelectorAll('.mdl-row').length === 5", "the five roles")
        b.wait(f"({self.row('analyst')}).includes('Answered by Claude Code 2.1.331')", "the analyst's harness")
        self.assertNotIn("Answered by", b.eval(self.row("builder")))      # the builder is a cell runner's
        b.click('[data-key="mdl-test:analyst"]', what="Test on the analyst")
        b.wait("document.querySelector('#mdl-res-analyst').textContent.includes('Answered in')", "the latency")
        self.assertIn("It said: OK", b.eval("document.querySelector('#mdl-res-analyst').textContent"))
        listed = b.eval("document.querySelector('#mdl-harness-h').closest('.card').textContent")
        for words in ("Claude Code", "Found: 2.1.331", "Codex", "Found: 0.60.1", "OpenCode", "Not found"):
            self.assertIn(words, listed)
        self.assertTrue(b.eval("document.querySelector('[data-key=\"hm-use:opencode\"]').disabled"))
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        self.step("use codex for the verifier")
        b.eval("(() => { const s = document.querySelector('#hm-roles'); s.value = 'verifier';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.click('[data-key="hm-use:codex"]', what="Use Codex")
        b.wait(f"({self.row('verifier')}).includes('Answered by Codex 0.60.1')", "the verifier on Codex")
        self.assertIn("Answered by Claude Code", b.eval(self.row("analyst")))
        b.click('[data-key="mdl-test:verifier"]', what="Test on the verifier")
        b.wait("document.querySelector('#mdl-res-verifier').textContent.includes('Answered in')", "the latency")
        self.check()


if __name__ == "__main__":
    unittest.main()
