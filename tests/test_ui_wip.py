"""FR-WIP1-AC-6 in a real browser (headless Chrome over the DevTools protocol, as tests/test_ui_drive.py).

An adopted project whose working copy holds old uncommitted work and a build folder of generated output: its Overview
shows the Work in progress card with the work by area, the generated pile and the nudge, and Start here's step to
commit it; a file changed meanwhile shows after Refresh. Dark at 1440 px, then light at 390 px; after every step no
console error, failed request or CSP violation, every control named, nothing wider than the screen. Skipped when
Chrome is not installed.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_shape_models as shaped  # noqa: E402  (a module: its own test class is not run from here)
from alignment_fixture import write  # noqa: E402
from factory_fakes import isolated_routing  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402
from test_wip import working_copy  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import wip  # noqa: E402
from kernel.store import Factory  # noqa: E402

CARD = "document.querySelector('.wip-card')"


class WipUiTest(unittest.TestCase):
    UI = shaped.ShapeModelsUiTest
    step, sign_in, theme, narrow, check = UI.step, UI.sign_in, UI.theme, UI.narrow, UI.check

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-wip-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        isolated_routing(self, self.tmp)
        wip._cache.clear()
        self.factory = Factory(self.tmp / "home")
        self.factory.new_project("Old intranet", maturity="demo", mode="mixed")   # past the first-run choice
        self.repo = working_copy(self.tmp / "work", old=True)
        self.project = self.factory.new_project("Parcel rules")
        self.project.update_meta(source_kind="adopted", intent="maintain", upstream=str(self.repo))
        self.project.write("adopted.json", {"source": str(self.repo), "source_kind": "path", "intent": "maintain",
                                            "default_branch": "main"})
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def overview(self) -> str:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.project.pid}/overview"})
        b.wait(f"!!{CARD} && !!document.querySelector('.start-here')", "the Work in progress card and Start here")
        b.eval(f"{CARD}.scrollIntoView({{block: 'center'}})")
        return b.eval(f"{CARD}.textContent")

    def test_FR_WIP1_AC_6_the_work_in_progress_card_in_chrome_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in("developer")
        self.theme("dark", "Dark")
        self.step("overview, dark, 1440")
        card = self.overview()
        for words in ("Work in progress", "commit what is ready", "5 changed files not committed", "build",
                      "looks generated", "add build/ to .gitignore", "src", "docs", "never their contents"):
            self.assertIn(words, card)
        here = b.eval("document.querySelector('.start-here').textContent")
        self.assertIn("Commit your work in progress (5 files)", here)
        self.assertEqual(b.eval(f"{CARD}.closest('[data-control]').dataset.control"), "wip_card")
        self.step("refresh, dark, 1440")
        write(self.repo, {"src/another.py": "Z = 3\n"})                   # a file changed meanwhile
        b.click('[data-key="wip-refresh"]', what="Refresh")
        b.wait(f"{CARD} && {CARD}.textContent.includes('6 changed files not committed')", "the reading again")
        self.step("light, 390")
        self.theme("light", "Light")
        self.narrow()
        card = self.overview()
        self.assertIn("6 changed files not committed", card)
        self.assertIn("looks generated", card)
        self.step("done")
        self.assertEqual(json.loads(json.dumps(b.problems)), [])


if __name__ == "__main__":
    unittest.main()
