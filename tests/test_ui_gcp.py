"""FR-GCP1-AC-7 and FR-GDR1-AC-5: the paved roads, the Google Cloud road and the Drive connector in a real browser.

Over a demo home, IT opens Settings, reads the paved roads and configures a Google Cloud road (a scheduled
Cloud Run job), then opens a project's Releases view and chooses that road and its schedule; a person reads
the Google Drive connector in Settings' Integrations card. First in the dark theme at 1440 px, then in the
light theme at 390 px. After every step there is no console error, failed request or Content-Security-Policy
violation, every control has a name, and nothing is wider than the screen. Skipped when Chrome is not
installed (``RIHMA_CHROME`` names another browser binary) or git is missing for the demo. No gcloud runs:
the road says it is missing.
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

from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import Factory, read_json  # noqa: E402

IT_PERSON = "Ilkka Example"
UNNAMED = """[...document.querySelectorAll('#main button, #main a[href], #main input, #main textarea, #modal button, #modal input, #modal textarea')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim() || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA' && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"
FORM = {"#gcp-name": "company-gcp", "#gcp-test": "example-test-123", "#gcp-prod": "example-prod-123",
        "#gcp-repo": "europe-north1-docker.pkg.dev/example-build-123/rihmasto",
        "#gcp-who": "deployer@example-ops-123.iam.gserviceaccount.com",
        "#gcp-runtime": "transcriber@example-prod-123.iam.gserviceaccount.com",
        "#gcp-sched": "scheduler@example-prod-123.iam.gserviceaccount.com"}


class GcpUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-gcp-")).resolve()
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
        self.browser = Browser(self.chrome, self.tmp / f"chrome-{self._testMethodName[-12:]}")
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
            b.screenshot(shots / f"gcp-{b.step.replace(' ', '-')}.png")

    def assert_fits_and_named(self) -> None:
        b = self.browser
        self.assertEqual(b.eval(UNNAMED), [], f"controls without a name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def narrow(self) -> None:
        b = self.browser
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        time.sleep(0.3)

    def sign_in(self, person: str, persona: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.server.issue_link()}"})   # one link each
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid .widget')",
               "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", person)
        b.click(f'label[for="pp-{persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(person)}", "the person chip")

    def settings(self) -> None:
        b = self.browser
        b.eval("location.hash = '#/settings'; true")
        b.wait("!!document.querySelector('[data-control=\"paved_roads\"]') && !!document.querySelector("
               "'[data-control=\"drive_connector\"]')", "the paved roads and the integrations in Settings")

    def test_FR_GCP1_AC_7_it_configures_a_google_cloud_road_and_chooses_a_projects_road_in_chrome(self):
        b = self.browser
        stock = next(p for p in self.factory.projects() if p.meta.get("title") == "Stock levels service")
        self.step("sign in as IT")
        self.sign_in(IT_PERSON, "it")
        self.theme("dark", "Dark")
        self.step("the paved roads")
        self.settings()
        self.assertIn("local-preview", b.eval("document.querySelector('[data-control=\"paved_roads\"]').textContent"))
        self.assert_fits_and_named()
        self.step("configure a Google Cloud road")
        b.click('[data-key="road-gcp-new"]', what="Configure a Google Cloud road")
        b.wait("!!document.querySelector('#modal[open] #gcp-name')", "the road's form")
        for selector, value in FORM.items():
            b.type(selector, value)
        self.assert_fits_and_named()
        b.click('[data-key="gcp-save"]', what="Save the road")
        b.wait("!!document.querySelector('[data-key=\"road:company-gcp\"]')", "the new road in the list")
        row = b.eval("document.querySelector('[data-key=\"road:company-gcp\"]').textContent")
        self.assertIn("Google Cloud Run", row)
        self.assertIn("gcloud CLI is not on PATH", row)                       # it says what is missing
        saved = read_json(self.factory.paved_roads_path)["roads"]["company-gcp"]
        self.assertEqual((saved["workload"], saved["schedule"]["cron"], saved["projects"]["production"]),
                         ("job", "0 6 * * *", "example-prod-123"))
        rec = factory_project(self.factory).ledger().of_kind("road_configured")[-1]["event"]["payload"]
        self.assertEqual((rec["road"], rec["person"], rec["persona"]), ("company-gcp", IT_PERSON, "it"))
        self.step("choose the project's road")
        b.eval(f"location.hash = '#/p/{stock.pid}/releases'; true")
        b.click('[data-key="deploy-choose"]', what="Choose the road")
        b.wait("!!document.querySelector('#modal[open] #rd-road')", "the road choice")
        b.eval("(() => { const s = document.querySelector('#rd-road'); s.value = 'company-gcp';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.type("#rd-sched", FORM["#gcp-sched"])
        b.click('[data-key="rd-save"]', what="Choose")
        b.wait("(document.querySelector('#status') || {}).textContent.includes('now deploys on company-gcp')", "the choice")
        b.wait("(document.querySelector('[data-key=\"deploy-env:production\"]') || {}).textContent.includes('company-gcp')",
               "production on the new road")
        chosen = stock.ledger().of_kind("road_chosen")[-1]["event"]["payload"]
        self.assertEqual((chosen["road"], chosen["person"], chosen["choice"]["workload"]), ("company-gcp", IT_PERSON, "job"))
        self.assert_fits_and_named()
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        self.assert_fits_and_named()
        self.settings()
        self.assert_fits_and_named()
        self.check()

    def test_FR_GDR1_AC_5_the_google_drive_connector_is_in_settings_integrations_in_chrome(self):
        b = self.browser
        self.step("sign in")
        self.sign_in("Aino Virtanen", "business_owner")
        self.theme("dark", "Dark")
        self.step("the integrations")
        self.settings()
        card = b.eval("document.querySelector('[data-control=\"drive_connector\"]').textContent")
        for said in ("Google Drive", "drive.readonly", "drive.file", "app/gdrive.py", "<NAME>_TOKEN",
                     "runtime service account"):
            self.assertIn(said, card)
        self.assertIn("IT configures the roads", b.eval("document.querySelector('.roads-card').textContent"))
        self.assert_fits_and_named()
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        b.eval("document.querySelector('[data-control=\"drive_connector\"]').scrollIntoView(); true")
        self.assert_fits_and_named()
        self.check()


if __name__ == "__main__":
    unittest.main()
