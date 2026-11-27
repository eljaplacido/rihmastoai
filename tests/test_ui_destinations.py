"""FR-DST1-AC-4: the Destinations view in a real browser (headless Chrome over the DevTools protocol).

Over the destinations fixture (tests/destinations_fixture.py: staging and production behind a health server on
127.0.0.1, a fake gcloud and a fake docker on PATH), a person opens the project's overview, follows "Where this
goes" to Destinations, checks the destinations while production is down and sees it failing with the way to
investigate, publishes to a registry that is not ready and reads exactly what is missing, then publishes to the
test registry once its login's variables are set, first in the dark theme at 1440 px, then in the light theme at
390 px. After every step there is no console error, failed request or Content-Security-Policy violation, every
control has a name, and nothing is wider than the screen. Skipped when Chrome is not installed (``RIHMA_CHROME``
names another browser binary) or git is missing.
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import destinations_fixture as fx  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads  # noqa: E402

UNNAMED = """[...document.querySelectorAll('.view-body button, .view-body a[href], .view-body input')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim() || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (el.tagName !== 'INPUT' && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


class DestinationsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for the product repository")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-dst-")).resolve()
        cls.health = fx.Health()
        cls.docker = fx.FakeDocker(cls.tmp / "docker")
        path = os.pathsep.join([str(cls.tmp / "gcloud"), str(cls.tmp / "docker"), os.environ.get("PATH", "")])
        cls.env = mock.patch.dict(os.environ, {"PATH": path})
        cls.env.start()
        for name in ("GHCR_USER", "GHCR_TOKEN", "DESK_TEAMS_URL"):
            os.environ.pop(name, None)
        try:
            w = fx.build(cls.tmp / "home", cls.health, cls.tmp / "gcloud")
        except Exception:
            cls.tearDownClass()
            raise
        cls.factory, cls.project = w["factory"], w["project"]
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(5)
        cls.health.stop()
        cls.env.stop()
        roads.stop_started()
        with contextlib.suppress(OSError):
            roads.rmtree(cls.tmp)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-dst")
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
            b.screenshot(shots / f"destinations-{b.step.replace(' ', '-').replace(',', '')}.png")

    def fits_and_named(self) -> None:
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
        b.click('label[for="pp-it"]', what="the IT persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def toast(self, words: str, what: str) -> None:
        b = self.browser
        b.wait(f"(document.querySelector('#status') || {{}}).textContent.includes({json.dumps(words)})", what)
        b.click("#status .toast .icon-btn", what="Dismiss on the message")    # narrow, it can cover the next card
        b.wait("!document.querySelector('#status .toast')", "the message dismissed")

    def test_FR_DST1_AC_4_a_person_sees_where_it_goes_checks_and_publishes_dark_and_light_wide_and_narrow(self):
        b, pid = self.browser, self.project.pid
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("where this goes on the overview")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{pid}/overview"})
        b.wait("(document.querySelector('[data-control=\"destinations_where\"]') || {}).textContent"
               "?.includes('runs in staging')", "Where this goes, read")
        b.click('[data-key="dst-where-open"]', what="Open Destinations")
        b.wait(f"location.hash === '#/p/{pid}/destinations' && document.querySelectorAll('.dst-card').length >= 10",
               "the Destinations map with its cards")
        self.assertEqual(b.eval("[...document.querySelectorAll('.dst-group')].map((g) => g.dataset.group)"),
                         ["deployed", "data", "channels", "published"])
        self.assertEqual(b.eval("document.querySelector('[data-id=\"deployed:production\"]').dataset.state"), "delivered")
        self.fits_and_named()
        self.step("production goes down, check now")
        self.health.server.answers.pop("production")
        b.click('[data-key="dst-check"]', what="Check now")
        b.wait("document.querySelector('[data-id=\"deployed:production\"]')?.dataset.state === 'failing'",
               "production failing")
        self.toast("1 failing: Production on gcp", "what the round found")
        self.assertTrue(b.eval("!!document.querySelector('[data-key=\"dst-act:investigate:deployed:production\"]')"))
        failing = [r["event"]["payload"] for r in self.project.ledger().of_kind("destination_failing")]
        self.assertEqual((failing[-1]["destination"], failing[-1]["by"]), ("deployed:production", PERSON))
        self.fits_and_named()
        self.step("light and narrow")
        self.theme("light", "Light")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        time.sleep(0.3)
        self.fits_and_named()
        self.assertEqual(b.eval("new Set([...document.querySelectorAll('[data-group=\"deployed\"] .dst-card')]"
                                ".map((c) => c.getBoundingClientRect().left)).size"), 1)          # one column
        self.step("publish refused, narrow")
        b.click('[data-key="dst-act:publish:published:ghcr"]', what="Publish to production on ghcr")
        self.toast("publish release 1 to a test registry first", "the reason it is refused")
        self.assertEqual(self.docker.calls(), [])
        self.step("publish to test, narrow")
        os.environ.update(GHCR_USER="example-bot", GHCR_TOKEN=fx.TOKEN)
        b.eval(f"location.hash = '#/p/{pid}/overview'; true")
        b.wait("!!document.querySelector('[data-control=\"destinations_where\"]')", "the overview again")
        b.eval(f"location.hash = '#/p/{pid}/destinations'; true")
        b.wait("!!document.querySelector('[data-key=\"dst-act:publish:published:ghcr-test\"]:not([disabled])')",
               "Publish to test, ready")
        b.click('[data-key="dst-act:publish:published:ghcr-test"]', what="Publish to test on ghcr-test")
        self.toast("published as ghcr.io/example-org/test/", "the published image")
        b.wait("document.querySelector('[data-id=\"published:ghcr-test\"]')?.dataset.state === 'healthy'",
               "the test registry healthy")
        self.assertEqual([c["args"][0] for c in self.docker.calls()], ["build", "login", "tag", "push"])
        self.fits_and_named()
        self.check()


if __name__ == "__main__":
    unittest.main()
