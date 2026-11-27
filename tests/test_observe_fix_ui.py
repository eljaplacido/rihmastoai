"""FR-SHR2-AC-2 and AC-6: observer links' fixes in a real browser (headless Chrome over the DevTools protocol).

A product owner makes a link and works on a project's plan: the chip saying who is watching sits in the top bar,
over nothing, and says a guest is watching within seconds of them opening the link; a pause made as Ask Rihma's
Confirm makes it stays paused through the page's heartbeat, and the page mirrors it. The guest's tab, refused after
a revoke, opens a new link pasted into it (only the hash changes) and clears it from the address bar. The cockpit
dark at 1440 px and light at 390 px; the guest's page dark wide and light narrow; after every step no console error,
failed request or Content-Security-Policy violation, every control named, nothing wider than the screen. The cockpit
listens on 9532 and Chrome's DevTools on 10032 only. Skipped when Chrome is not installed.
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
from test_observe_ui import UNNAMED  # noqa: E402
from test_ui_destinations import OVERFLOW  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import observe  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.store import Factory  # noqa: E402

PORT, DEVTOOLS = 9532, 10032
# the chip inside the top bar, and no element of the page's main area under it
COVERS = """(() => { const c = document.getElementById('obs-chip'); if (!c) return 'no chip';
  if (!document.getElementById('topbar').contains(c)) return 'not in the top bar';
  const r = c.getBoundingClientRect(); const m = document.getElementById('main').getBoundingClientRect();
  return r.bottom <= m.top + 1 ? '' : 'over the page: ' + JSON.stringify([r.top, r.bottom, m.top]); })()"""


def _own_port(popen):
    def start(args, *a, **kw):
        return popen([f"--remote-debugging-port={DEVTOOLS}" if x == "--remote-debugging-port=0" else x for x in args],
                     *a, **kw)
    return start


class OwnPortBrowser(Browser):
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


class ObserveFixUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-obsfix-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.project = cls.factory.new_project("Equipment loans", mode="assume", maturity="demo")
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
            self.browser = OwnPortBrowser(self.chrome, self.tmp / "chrome-obsfix")
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
        if os.environ.get("RIHMA_UI_SHOTS"):
            shots = Path(os.environ["RIHMA_UI_SHOTS"])
            shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(shots / f"observefix-{b.step.replace(' ', '-').replace(',', '')}.png")

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

    def link(self, guest: str) -> str:
        made = observe.create(self.factory, scope="project", project=self.project.pid, hours=24, guest=guest,
                              person=PERSON, persona="product_owner")
        return observe.url(self.server.origin, made["token"])

    def test_FR_SHR2_AC_6_the_watching_chip_sits_in_the_top_bar_and_a_pause_from_chat_holds(self):
        b = self.browser
        self.assertEqual(self.server.server_address[1], PORT)
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("sharing, the chip in the top bar, dark and wide")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/share"})
        b.wait("!!document.querySelector('[data-control=\"observe_link\"]') && !document.querySelector('[aria-busy]')",
               "the Share page")
        b.eval(f"(() => {{ const s = document.querySelector('#sh-project'); s.value = {json.dumps(self.project.pid)};"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.type("#sh-guest", "Maria Example")
        b.click('[data-control="observe_link"]', what="Make the link")
        first = b.wait("(document.querySelector('.sh-url') || {}).textContent", "the link shown once")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.project.pid}/plan"})
        b.wait("!!document.getElementById('obs-chip')", "the sharing chip")
        self.assertEqual(b.eval(COVERS), "")
        self.fits()
        self.step("a guest opens the link and the chip says so within seconds")
        session = observe.open_link(self.factory, first.split("#", 1)[1])["session"]
        observe.session(self.factory, session)                    # the guest's page asked: watching now
        opened = time.monotonic()
        deadline = opened + 12
        label = "document.getElementById('obs-chip').getAttribute('aria-label')"
        while time.monotonic() < deadline and "Maria Example" not in (b.eval(label) or ""):
            observe.session(self.factory, session)
            time.sleep(0.5)
        self.assertIn("Maria Example", b.eval(label), "the chip did not say a guest is watching within 12 seconds")
        self.assertNotEqual(b.eval("document.getElementById('obs-chip').dataset.watching"), "0")
        self.step("a pause confirmed in Ask Rihma holds through the heartbeat")
        observe.set_presence(self.factory, person=PERSON, persona="product_owner", project=None, view="paused",
                             paused=True)                         # what Confirm on Ask Rihma's proposal sends
        b.wait("(document.getElementById('obs-chip').getAttribute('aria-label') || '').includes('(paused)')",
               "the page mirrors the pause", timeout=15)
        time.sleep(9)                                             # a heartbeat later: still paused
        self.assertTrue(observe.presence(self.factory, PERSON)["paused"])
        self.step("the chip, light and narrow")
        self.theme("light", "Light")
        self.size(390, 844)
        b.wait("!!document.getElementById('obs-chip')", "the sharing chip, narrow")
        self.assertEqual(b.eval(COVERS), "")
        self.fits()
        self.check()
        observe.set_presence(self.factory, person=PERSON, persona="product_owner", project=None, view="",
                             paused=False)

    def test_FR_SHR2_AC_2_a_new_link_pasted_into_an_open_guest_tab_opens(self):
        b = self.browser
        self.step("the guest watches, dark and wide")
        self.scheme("dark")
        self.size(1440, 1000)
        old = self.link("Olli Example")
        b.cmd("Page.navigate", {"url": old})
        b.wait("!!document.querySelector('.ob-follow')", "the guest's page")
        self.fits()
        self.step("the link is revoked")
        observe.revoke(self.factory, observe.links(self.factory)[-1]["id"], person=PERSON, persona="product_owner")
        b.wait("(document.querySelector('.ob-err') || {}).textContent?.includes('stopped sharing')", "sharing stopped")
        b.problems = [p for p in b.problems if "status of 403" not in str(p[2])]    # the refusal: expected here
        self.step("a new link pasted into the same tab, light and narrow")
        self.scheme("light")
        self.size(390, 844)
        new = self.link("Olli Example")
        b.eval(f"(() => {{ location.hash = {json.dumps(new.split('#', 1)[1])}; return true; }})()")
        b.wait("!!document.querySelector('.ob-follow') && !document.querySelector('.ob-err')", "the new link opened")
        self.assertEqual(b.eval("location.hash"), "")                       # the token left the address bar
        self.assertIn("Equipment loans", b.eval("document.body.textContent"))
        self.fits()
        self.check()
        observe.revoke(self.factory, observe.links(self.factory)[-1]["id"], person=PERSON, persona="product_owner")


if __name__ == "__main__":
    unittest.main()
