"""FR-OUT5-AC-2: the Outputs view in a real browser (headless Chrome over the DevTools protocol).

Over a demo home, a person asks the assistant where the outputs are and is taken there, chooses the outputs by
keyboard, builds one output and then every chosen one, and downloads them, first in the dark theme at 1440 px,
then in the light theme at 390 px. After every step there is no console error, failed request or
Content-Security-Policy violation, every control has a name, and nothing is wider than the screen. Skipped when
Chrome is not installed (``RIHMA_CHROME`` names another browser binary) or git is missing for the demo.
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads  # noqa: E402
from kernel.store import Factory  # noqa: E402

# Every button, link, field and checkbox in the view, and those without a name a screen reader can say.
UNNAMED = """[...document.querySelectorAll('.view-body button, .view-body a[href], .view-body input, .view-body textarea')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim() || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (el.tagName !== 'INPUT' && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


class OutputsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-outputs-")).resolve()
        try:
            build_demo(cls.tmp / "demo", echo=lambda line: None)
        except Exception:
            roads.stop_started()
            roads.rmtree(cls.tmp)
            raise
        cls.factory = Factory(cls.tmp / "demo")
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        roads.stop_started()
        with contextlib.suppress(OSError):
            roads.rmtree(cls.tmp)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-outputs")
        self.addCleanup(self.browser.close)
        self.downloads = self.tmp / "downloads"
        self.downloads.mkdir(exist_ok=True)
        self.browser.cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(self.downloads)})

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
        if os.environ.get("RIHMA_UI_SHOTS"):                       # a screenshot per step, for a person to look at
            shots = Path(os.environ["RIHMA_UI_SHOTS"])
            shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(shots / f"outputs-{b.step.replace(' ', '-').replace(',', '')}.png")

    def press(self, key: str, code: str, vk: int, text: str = "") -> None:
        """A key pressed and released on whatever has the focus, as a keyboard sends it."""
        b = self.browser
        b.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                         "nativeVirtualKeyCode": vk, **({"text": text} if text else {})})
        b.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                         "nativeVirtualKeyCode": vk})

    def focus(self, selector: str) -> None:
        self.browser.wait(f"(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false;"
                          " el.focus(); return document.activeElement === el; })()", selector)

    def downloaded(self, before: set, what: str) -> Path:
        end = time.monotonic() + 20
        while time.monotonic() < end:
            new = {p for p in self.downloads.glob("*.zip")} - before
            if new:
                return new.pop()
            time.sleep(0.1)
        raise AssertionError(f"[{self.browser.step}] {what} was not downloaded")

    def assert_fits_and_named(self) -> None:
        b = self.browser
        self.assertEqual(b.eval(UNNAMED), [], f"controls without a name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid .widget')",
               "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-business_owner"]', what="the business owner persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def test_FR_OUT5_AC_2_a_person_chooses_builds_and_downloads_outputs_in_chrome_dark_and_light_wide_and_narrow(self):
        b = self.browser
        webhook = next(p for p in self.factory.projects() if p.meta.get("title") == "Shipment webhook to the stock system")
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("ask the assistant")
        b.click('#sb-nav a[href="#/projects"]', what="Projects in the sidebar")
        b.click(".proj-card", text="Shipment webhook", what="the webhook project")
        b.wait(f"location.hash.startsWith('#/p/{webhook.pid}')", "the project")
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "Where are the outputs?")
        b.click("#as-send", what="Send")
        b.click("#as-log .msg.bot button", text="Take me there", what="Take me there")
        b.wait(f"location.hash === '#/p/{webhook.pid}/outputs' && document.querySelectorAll('.out-card').length === 7",
               "the Outputs view with its seven targets")
        b.eval("document.querySelector('#assistant-fab').getAttribute('aria-expanded') === 'true'"
               " && document.querySelector('#assistant-fab').click(); true")   # close the assistant again
        self.assert_fits_and_named()
        ticked = b.eval("[...document.querySelectorAll('input[name=\"out-target\"]:checked')].map((x) => x.value)")
        self.assertEqual(sorted(ticked), ["api", "container", "report", "source"])   # the profile's proposal
        self.step("choose by keyboard")
        for target in ("evidence_pack", "source"):
            self.focus(f'[data-key="out-pick:{target}"]')
            self.press(" ", "Space", 32, " ")
        self.focus('[data-key="out-pick:login_web_app"]')
        b.type("#out-reason", "For the handover to the warehouse team")
        self.press("Tab", "Tab", 9)
        self.assertEqual(b.eval("document.activeElement.dataset.key"), "out-save")   # Tab reaches Save next
        self.press("Enter", "Enter", 13, "\r")
        b.wait(f"(document.querySelector('[aria-labelledby=\"out-choose-h\"]') || {{}}).textContent.includes("
               f"{json.dumps('Chosen by ' + PERSON)})", "the recorded choice")
        chosen = [r["event"]["payload"] for r in webhook.ledger().of_kind("outputs_chosen")][-1]
        self.assertEqual((chosen["by"], chosen["persona"], chosen["targets"]),
                         (PERSON, "business_owner", ["container", "api", "report", "evidence_pack"]))
        self.step("build one")
        before = set(self.downloads.glob("*.zip"))
        b.click('[data-key="out-build:report"]', what="Build and download on the report's card")
        report = self.downloaded(before, "the delivery report")
        self.assertIn("-report-", report.name)
        built = [r["event"]["payload"] for r in webhook.ledger().of_kind("output_built")][-1]
        self.assertEqual((built["target"], built["state"], built["by"]), ("report", "built", PERSON))
        self.step("build every chosen output")
        b.click('[data-key="out-all"]', what="Build every chosen output")
        b.wait("document.querySelectorAll('[data-control=\"download_output\"]').length >= 3", "the Download links")
        self.assert_fits_and_named()
        before = set(self.downloads.glob("*.zip"))
        b.click('[data-key="out-dl:container"]', what="Download on the container's card")
        self.assertIn("-container-", self.downloaded(before, "the container").name)
        b.wait("!document.querySelector('[data-key=\"out-dl:container\"]')", "the used link gone")
        self.step("light and narrow")
        self.theme("light", "Light")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        time.sleep(0.3)
        self.assert_fits_and_named()
        self.assertEqual(b.eval("new Set([...document.querySelectorAll('.out-card')].map((c) => c.getBoundingClientRect().left)).size"),
                         1)                                                           # one column of cards
        self.step("build by keyboard, narrow")
        before = set(self.downloads.glob("*.zip"))
        self.focus('[data-key="out-build:api"]')
        self.press("Enter", "Enter", 13, "\r")
        self.assertIn("-api-", self.downloaded(before, "the API description").name)
        self.step("a target that is not chosen, and one that is planned")
        records = len(webhook.ledger().records())
        b.click('[data-key="out-build:source"]', what="Build on the source's card")
        b.wait("(document.querySelector('#status') || {}).textContent.includes('Choose it first')", "the reason it waits")
        b.click("#status .toast .icon-btn", what="Dismiss on the warning")      # narrow, it can cover the next card
        b.wait("!document.querySelector('#status .toast')", "the warning dismissed")
        b.click('[data-key="out-build:mcp_server"]', what="Build on the MCP server's card")
        b.wait("(document.querySelector('#status') || {}).textContent.includes('Planned')", "the reason it is planned")
        self.assertEqual(len(webhook.ledger().records()), records)          # nothing was asked of the kernel
        self.check()


if __name__ == "__main__":
    unittest.main()
