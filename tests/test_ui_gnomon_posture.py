"""FR-GNP1-AC-7 in a real browser (headless Chrome over the DevTools protocol, as tests/test_ui_drive.py).

A project whose own Gnomon files leave shell commands uncontained (tests/gnomon_posture_fakes.py WEAK). Dark at
1440 px as a developer: the Gnomon posture view shows the score, the weakest dimensions and the suggestions with
their settings, and the first is filed as a change card. Then light at 390 px as IT: the score and the filed card
still read. After every step no console error, failed request or CSP violation, every control named, nothing wider
than the screen. Skipped without Chrome.
"""

import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_itops  # noqa: E402  (its persona switch; a module, so its own tests do not run here)
import test_ui_shape_models as shaped  # noqa: E402  (a module: its own test class is not run from here)
from factory_fakes import isolated_routing  # noqa: E402
from gnomon_posture_fakes import WEAK, project  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.store import Factory  # noqa: E402

CARD = "(document.querySelector('[data-control=gnomon_posture_card]') || {textContent: ''}).textContent"


class GnomonPostureUiTest(unittest.TestCase):
    UI = shaped.ShapeModelsUiTest
    step, sign_in, theme, narrow, check = UI.step, UI.sign_in, UI.theme, UI.narrow, UI.check
    persona = test_ui_itops.ItOpsUiTest.as_persona

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-gnomon-posture-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolated_routing(self, self.tmp)
        self.factory = Factory(self.tmp / "home")
        self.shop = project(self.factory, self.tmp, WEAK)
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def open_view(self, ready: str, what: str) -> None:
        self.browser.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.shop.pid}/gnomon_posture"})
        self.browser.wait(ready, what)

    def test_FR_GNP1_AC_7_the_gnomon_posture_view_in_chrome_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in as a developer")
        self.sign_in("developer")
        self.theme("dark", "Dark")
        self.step("the posture, dark, 1440")
        self.open_view(f"{CARD}.includes('/100')", "the posture's score")
        said = b.eval(CARD)
        for words in ("weakest:", "Containment & sandbox", "Contain shell commands", '[sandbox] exec = "os"',
                      "policy.toml", "the working copy at"):
            self.assertIn(words, said)
        self.step("file a suggestion, dark, 1440")
        b.click('[data-key="gp-file:GP-sandbox-exec"]', what="File as a change")
        b.wait(f"{CARD}.includes('Filed as C-')", "the filed change card")
        self.step("light, 390, as it")
        self.persona("it")
        self.theme("light", "Light")
        self.narrow()
        self.open_view(f"{CARD}.includes('/100')", "the posture, narrow")
        self.assertIn("Filed as C-", b.eval(CARD))
        self.step("done")


if __name__ == "__main__":
    unittest.main()
