"""FR-XAG1-AC-6 in a real browser (headless Chrome over the DevTools protocol, as tests/test_ui_drive.py).

Settings' Machines: a laptop is added, Test connection says its key is refused, gives the fix and drafts the ask, and
Send puts it in a project. The project's agent channel shows the ask waiting; a second ask is put to another agent,
copied for it and its answer pasted back. Home shows what waits on other agents. Dark at 1440 px, then light at
390 px; after every step no console error, failed request or CSP violation, every control named, nothing wider than
the screen. No real ssh runs: the doctor's ssh test is patched. Skipped when Chrome is not installed.
"""

import json
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
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import asks, reach  # noqa: E402
from kernel.store import Factory  # noqa: E402

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleOnlyNotARealKey0000000000000000 dana@workstation"


def has(selector: str, text: str) -> str:
    return f"(document.querySelector({json.dumps(selector)}) || {{}}).textContent?.includes({json.dumps(text)})"


class AsksUiTest(unittest.TestCase):
    UI = shaped.ShapeModelsUiTest
    step, sign_in, theme, narrow, check = UI.step, UI.sign_in, UI.theme, UI.narrow, UI.check

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-asks-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolated_routing(self, self.tmp)
        self.factory = Factory(self.tmp / "home")
        self.project = self.factory.new_project("Webshop", maturity="demo", mode="mixed")
        for patch in (mock.patch.object(reach, "test_ssh", return_value="auth_denied"),
                      mock.patch.object(reach, "public_key", return_value=("/k.pub", KEY))):
            patch.start()
            self.addCleanup(patch.stop)
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def go(self, route: str, ready: str, what: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/{route}"})
        b.wait(ready, what)

    def choose(self, selector: str, value: str) -> None:
        self.browser.eval(f"(() => {{ const s = document.querySelector({json.dumps(selector)}); s.value = "
                          f"{json.dumps(value)}; s.dispatchEvent(new Event('change', {{bubbles: true}})); return true; }})()")

    def settings(self) -> None:
        self.go("#/settings", "!!document.querySelector('#set-machines-h')", "the Machines card")
        self.browser.eval("document.querySelector('#set-machines-h').scrollIntoView({block: 'center'})")

    def channel(self) -> None:
        self.go(f"#/p/{self.project.pid}/agents", "!!document.querySelector('#ak-h')", "the asks on the agent channel")

    def test_FR_XAG1_AC_6_machines_asks_and_test_connection_in_chrome_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in("developer")
        self.theme("dark", "Dark")
        self.step("machines, dark, 1440")
        self.settings()
        self.assertIn("All projects", b.eval("document.querySelector('.mc-holder').textContent"))   # its scope
        b.type("#mc-name", "laptop")
        self.choose("#mc-reach", "ssh")
        b.type("#mc-address", "me@laptop")
        self.choose("#mc-os", "windows")
        b.type("#mc-agents", "claude-code")
        b.click('[data-key="mc-add"]', what="Add the machine")
        b.wait(has(".mc-list", "laptop"), "the laptop in the list")
        self.step("test connection, dark, 1440")
        b.click('[data-key="reach:laptop"]', what="Test connection")
        b.wait(has(".rc-result", "refuses this machine's key"), "the verdict")
        result = b.eval("document.querySelector('.rc-result').textContent")
        for words in ("not reachable", "administrators_authorized_keys", KEY, "Ask the agent on laptop"):
            self.assertIn(words, result)
        self.choose("#rc-project", self.project.pid)
        b.click('[data-key="rc-send"]', what="Send to the agent on laptop")
        b.wait(has("body", "AK-0001 asked claude-code on laptop"), "the ask, sent")
        self.assertEqual([a["machine"] for a in asks.listed(self.project)], ["laptop"])
        self.step("asks, dark, 1440")
        self.channel()
        b.wait(has(".ak-list", "AK-0001"), "the drafted ask, waiting")
        self.assertIn("waiting", b.eval("document.querySelector('[data-key=\"ask:AK-0001\"]').textContent"))
        b.type("#ak-to", "codex")
        b.type("#ak-text", "Do the tests pass on main?")
        b.click('[data-key="ak-put"]', what="Put the ask")
        b.wait(has(".ak-list", "AK-0002"), "the second ask")
        b.click('[data-key="ak-copy:AK-0002"]', what="Copy for the other agent")
        b.wait(has('[data-key="ask:AK-0002"]', "How to answer"), "the message for the other agent")
        b.wait(has('[data-key="ask:AK-0002"]', "delivered"), "delivered by copy")
        b.type("#ak-paste-AK-0002", "Yes: 214 passed.")
        b.click('[data-key="ak-answer:AK-0002"]', what="File the answer")
        b.wait(has('[data-key="ask:AK-0002"]', "Yes: 214 passed."), "the answer back")
        self.assertIn("answered", b.eval("document.querySelector('[data-key=\"ask:AK-0002\"]').textContent"))
        self.step("home, dark, 1440")
        self.go("#/home", "!!document.querySelector('#home-asks-h')", "Waiting on other agents")
        home = b.eval("document.querySelector('#home-asks').textContent")
        self.assertIn("AK-0001", home)
        self.assertNotIn("AK-0002", home)                                   # answered: no longer waiting
        self.step("light, 390")
        self.theme("light", "Light")
        self.narrow()
        self.channel()
        b.wait(has(".ak-list", "AK-0002"), "the asks, narrow")
        self.step("machines, light, 390")
        self.settings()
        b.wait(has(".mc-list", "laptop"), "the machines, narrow")
        self.step("done")
        self.assertEqual(b.problems, [])


if __name__ == "__main__":
    unittest.main()
