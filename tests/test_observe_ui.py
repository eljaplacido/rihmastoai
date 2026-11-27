"""FR-SHR1-AC-9: observer links in a real browser (headless Chrome over the DevTools protocol).

A product owner opens Share (empty: it says what would appear and how), makes an observer link to one project for a
named guest and sees it once; opens the project's plan (the page says where they are while sharing); the guest
opens the link in the same browser, follows to the plan, sees nothing of another project and comments; the sharer's
Share page shows who is watching and the guest's comment, and revokes the link; the guest's page then says sharing
stopped. The cockpit dark at 1440 px and light at 390 px; the guest's page dark wide and light narrow. After every
step there is no console error, failed request or Content-Security-Policy violation, every control has a name and
nothing is wider than the screen. The cockpit listens on 9530 and Chrome's DevTools on 10030 only. Skipped when
Chrome is not installed.
"""

import contextlib
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

import test_ui_drive  # noqa: E402
from test_ui_destinations import OVERFLOW  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import observe  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.store import Factory  # noqa: E402

PORT, DEVTOOLS = 9530, 10030
UNNAMED = """[...document.querySelectorAll('#main button, #main a[href], #main input, #main select, #main textarea')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim()
                    || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (!['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""


def _own_port(popen):
    """Chrome's DevTools on this test's own port, never a random one."""
    def start(args, *a, **kw):
        return popen([f"--remote-debugging-port={DEVTOOLS}" if x == "--remote-debugging-port=0" else x for x in args],
                     *a, **kw)
    return start


class OwnPortBrowser(Browser):
    """Chrome writes no DevToolsActivePort file for a fixed port: its browser endpoint is asked for instead."""

    def _devtools_port(self) -> tuple[int, str]:
        for _ in range(300):
            if self.proc.poll() is not None:
                raise RuntimeError(f"Chrome exited with {self.proc.returncode}")
            try:
                found = test_ui_drive._get_json(DEVTOOLS, "/json/version")
                return DEVTOOLS, urlsplit(found["webSocketDebuggerUrl"]).path
            except (OSError, ValueError, KeyError):
                time.sleep(0.1)
        raise RuntimeError("Chrome did not open its DevTools port")


class ObserveUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-obs-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.project = cls.factory.new_project("Tool loans", mode="assume", maturity="demo")
        cls.other = cls.factory.new_project("Room bookings", mode="assume", maturity="demo")
        Canon(cls.project).add_question("Who borrows the drills most?", "business")
        cls.server, cls.bootstrap = make_server(cls.factory, PORT, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(5)
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        with mock.patch.object(test_ui_drive.subprocess, "Popen", _own_port(subprocess.Popen)):
            self.browser = OwnPortBrowser(self.chrome, self.tmp / "chrome-obs")
        self.addCleanup(self.browser.close)
        if os.environ.get("RIHMA_UI_SHOTS"):
            self.browser.shots = Path(os.environ["RIHMA_UI_SHOTS"])

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
        if os.environ.get("RIHMA_UI_SHOTS"):
            shots = Path(os.environ["RIHMA_UI_SHOTS"])
            shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(shots / f"observe-{b.step.replace(' ', '-').replace(',', '')}.png")

    def fits(self) -> None:
        b = self.browser
        self.assertEqual(b.eval(UNNAMED), [], f"controls without a name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def scheme(self, mode: str) -> None:
        """The guest's page follows the system's light or dark."""
        self.browser.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": mode}]})

    def size(self, width: int, height: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride",
                         {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
        self.browser.wait(f"window.innerWidth === {width}", f"{width} px")
        time.sleep(0.3)

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out')"
               " && !!document.querySelector('#grid .widget')", "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-product_owner"]', what="the product owner persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def open_share(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/share"})
        b.wait("!!document.querySelector('[data-control=\"observe_link\"]') && !document.querySelector('[aria-busy]')",
               "the Share page")

    def test_FR_SHR1_AC_9_share_watch_comment_and_revoke_dark_light_wide_narrow(self):
        b = self.browser
        self.assertEqual(self.server.server_address[1], PORT)
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("Share, empty, dark and wide")
        self.open_share()
        empty = b.eval("document.querySelector('[data-empty=\"share\"]').textContent")
        self.assertIn("You are not sharing anything.", empty)
        self.assertIn("pass the link on yourself", empty)
        every = b.eval("document.querySelector('#sh-scope').options[1].textContent")
        self.assertEqual(every, "Every project (platform)")
        self.fits()
        self.step("make a link")
        b.eval(f"(() => {{ const s = document.querySelector('#sh-project'); s.value = {json.dumps(self.project.pid)};"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.type("#sh-guest", "Maria Example")
        b.click('[data-key="share-hours:24"]', what="A day")
        b.click('[data-control="observe_link"]', what="Make the link")
        url = b.wait("(document.querySelector('.sh-url') || {}).textContent", "the link shown once")
        self.assertIn("/o/#ob_", url)
        b.wait("!!document.querySelector('.sh-link[data-id=\"OL-001\"]')", "the link listed")
        self.assertIn("This project only", b.eval("document.querySelector('.sh-scope-note').textContent"))
        self.fits()
        self.step("the sharer works on the plan")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.project.pid}/plan"})
        b.wait("!!document.getElementById('obs-chip')", "the sharing chip")
        deadline = time.monotonic() + 15
        while (observe.presence(self.factory, PERSON) or {}).get("view") != "plan" and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertEqual(observe.presence(self.factory, PERSON)["view"], "plan")
        self.step("the guest watches, dark and wide")
        self.scheme("dark")
        b.cmd("Page.navigate", {"url": url})
        b.wait("!!document.querySelector('.ob-follow [data-state=\"here\"]')", "following the sharer")
        self.assertEqual(b.eval("location.hash"), "")                       # the token left the address bar
        b.wait("document.querySelector('[data-key=\"ob-tab:plan\"]').getAttribute('aria-selected') === 'true'",
               "the plan, followed")
        text = b.eval("document.body.textContent")
        self.assertNotIn("Room bookings", text)
        self.assertIn("Read only", text)
        self.assertIn("One project", text)
        self.fits()
        self.step("the guest comments")
        b.type("#ob-comment", "The plan reads well; who approves the loan limits?")
        b.click('[data-key="ob:comment"]', what="Comment")
        b.wait("document.querySelector('#main').textContent.includes('Sent, signed as Maria Example (guest)')",
               "the comment sent")
        self.step("the guest's page, light and narrow")
        self.scheme("light")
        self.size(390, 844)
        b.click('[data-key="ob:follow"]', what="Pause following")
        b.click('[data-key="ob-tab:channel"]', what="Agent channel")
        b.wait("!!document.querySelector('[data-empty=\"observer_channel\"]')", "the channel's empty state")
        self.fits()
        self.step("the sharer sees the guest, light and narrow")
        self.size(1440, 1000)
        self.open_share()
        self.theme("light", "Light")
        self.size(390, 844)
        b.wait("document.querySelector('.sh-comment') && document.querySelector('.sh-comment').textContent"
               ".includes('Maria Example')", "the guest's comment")
        self.fits()
        self.step("revoke")
        b.click('[data-control="observe_revoke"]', what="Revoke")
        b.wait("(document.querySelector('.sh-link[data-id=\"OL-001\"]') || {}).textContent?.includes('revoked')",
               "the link revoked")
        self.fits()
        self.step("the guest is refused")
        b.cmd("Page.navigate", {"url": url})
        b.wait("(document.querySelector('.ob-err') || {}).textContent?.includes('stopped sharing')", "sharing stopped")
        time.sleep(0.3)
        b.eval("1")
        refused = [p for p in b.problems if "status of 403" in str(p[2])]
        self.assertEqual(len(refused), 1, b.problems)                      # the open, refused: expected here
        b.problems = [p for p in b.problems if p not in refused]
        self.assertEqual(observe.state_of(self.factory, observe.find(self.factory, "OL-001")), "revoked")
        self.fits()
        self.check()


if __name__ == "__main__":
    unittest.main()
