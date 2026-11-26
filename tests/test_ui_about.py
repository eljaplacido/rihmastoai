"""FR-PUB2-AC-2 and AC-3 in a real browser (headless Chrome over the DevTools protocol, as tests/test_ui_drive.py).

Settings shows About and help: the declared version, Check this machine (doctor, with Gnomon stubbed out), the
commands and the guides. Ask Rihma answers "what version of Rihmasto is this?" by rule, with Take me there landing
on that card. Dark at 1440 px, then light at 390 px; after every step no console error, failed request or CSP
violation, every control named, nothing wider than the screen. Skipped when Chrome is not installed.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_shape_models as shaped  # noqa: E402  (a module: its own test class is not run from here)
from factory_fakes import isolated_routing  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.store import Factory  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DECLARED = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
NO_GNOMON = {"found": False, "command": ["gnomon"], "raw": None, "version": None, "build": None}


class AboutUiTest(unittest.TestCase):
    UI = shaped.ShapeModelsUiTest
    step, sign_in, theme, narrow, check = UI.step, UI.sign_in, UI.theme, UI.narrow, UI.check

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-about-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolated_routing(self, self.tmp)
        for patcher in (mock.patch("kernel.doctor.gnomon_version", return_value=dict(NO_GNOMON)),
                        mock.patch("kernel.models_setup.gnomon_found", return_value=False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.factory = Factory(self.tmp / "home")
        self.factory.new_project("Old intranet", maturity="demo", mode="mixed")   # past the first-run choice
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def settings(self) -> str:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/settings"})
        b.wait("!!document.querySelector('#about-help [data-key=\"about:version\"]')", "About and help with its version")
        b.eval("document.querySelector('#about-help').scrollIntoView()")
        return b.eval("document.querySelector('#about-help').textContent")

    def machine_check(self) -> str:
        b = self.browser
        b.eval("document.querySelector('[data-key=\"about:check\"]').scrollIntoView({block: 'center'})")
        b.click('[data-key="about:check"]', what="Check this machine")
        b.wait("!!document.querySelector('#about-help .abt-tools')", "the machine check")
        return b.eval("document.querySelector('#about-help .abt-machine').textContent")

    def ask_version(self, opener: str = "#assistant-fab") -> str:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/home"})
        b.wait(f"!!document.querySelector('{opener}')", "Ask Rihma's button")
        b.click(opener, what="Ask Rihma")
        b.type("#as-q", "What version of Rihmasto is this?")
        b.click("#as-send", what="Send")
        b.wait("(document.querySelector('#as-log .msg.bot:last-of-type') || {textContent: ''}).textContent"
               f".includes({json.dumps(DECLARED)})", "the version in Rihma's answer")
        said = b.eval("document.querySelector('#as-log .msg.bot:last-of-type').textContent")
        b.click("#as-log .msg.bot button", text="Take me there", what="Take me there")
        b.wait("location.hash === '#/settings' && !!document.querySelector('#about-help [data-key=\"about:version\"]')", "Settings, About and help")
        return said

    def test_FR_PUB2_AC_2_about_and_help_and_ask_rihma_in_chrome_dark_wide_and_light_narrow(self):
        self.step("sign in")
        self.sign_in("developer")
        self.theme("dark", "Dark")
        self.step("settings about and help, dark, 1440")
        card = self.settings()
        for words in (DECLARED, "rihmasto --version", "rihmasto doctor", "Getting started", "Verify what you install",
                      "Contributing", "All documentation"):
            self.assertIn(words, card)
        self.assertEqual(self.browser.eval("document.querySelector('[data-key=\"about:version\"] [data-ud]') "
                                           "? 'marked' : 'unmarked'"), "marked")
        self.step("check this machine, dark, 1440")
        machine = self.machine_check()
        self.assertIn("Gnomon", machine)
        self.assertIn("Gnomon was not found", machine)
        self.step("ask rihma which version, dark, 1440")
        self.assertIn("Settings", self.ask_version())
        self.step("light, 390")
        self.browser.click("#as-close", what="Close the assistant")
        self.theme("light", "Light")
        self.narrow()
        self.assertIn(DECLARED, self.settings())
        self.machine_check()
        self.step("ask rihma which version, light, 390")
        self.ask_version("#bb-ask")                           # on a phone, Ask is in the bottom bar
        self.step("done")


if __name__ == "__main__":
    unittest.main()
