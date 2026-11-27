"""Agent operations in a real browser (FR-AOP1-AC-9): headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py drives it, on a home of neutral projects with made-up agent runs (tests/agentops_fakes.py).

The AI architect opens Agent operations in the sidebar and in a project's Agents capsule: key figures, bars, lines,
a heatmap and tables are drawn; a figure opens the runs behind it; the Optimise audit is recorded and signed. Dark
and light, 1440 and 390 pixels wide: nothing scrolls sideways and no step leaves a console error, a failed request
or a CSP violation. A business owner reads the view with no unexplained jargon.

The cockpit listens on ``RIHMA_AOP_PORT`` (8941) and Chrome's DevTools on ``RIHMA_AOP_DEVTOOLS`` (9541). Skipped
when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). ``RIHMA_UI_SHOTS=<folder>`` saves a
screenshot per step.
"""

import json
import os
import re
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

import agentops_fakes as fakes  # noqa: E402
import test_ui_drive as drive  # noqa: E402
from test_ui_words import JARGON, VISIBLE  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
PORT = int(os.environ.get("RIHMA_AOP_PORT") or 8941)
DEVTOOLS = int(os.environ.get("RIHMA_AOP_DEVTOOLS") or 9541)
SIDEWAYS = "document.documentElement.scrollWidth - innerWidth"
DRAWN = ("!!document.querySelector('.aop-tiles') && !!document.querySelector('#aop-roles-h')"
         " && !!document.querySelector('.aol svg path') && !!document.querySelector('.aoh-grid .aoh-cell')")


def _popen(real):
    """Chrome's DevTools on the port this test was given, never a random one."""
    def start(args, *a, **kw):
        return real([f"--remote-debugging-port={DEVTOOLS}" if str(x).startswith("--remote-debugging-port=") else x
                     for x in args], *a, **kw)
    return start


class FixedPortBrowser(drive.Browser):
    """test_ui_drive's Browser on a fixed DevTools port: Chrome writes no DevToolsActivePort file then, so the port
    is asked for its browser endpoint instead."""

    def _devtools_port(self) -> tuple[int, str]:
        for _ in range(300):
            if self.proc.poll() is not None:
                raise RuntimeError(f"Chrome exited with {self.proc.returncode}")
            try:
                ws = drive._get_json(DEVTOOLS, "/json/version")["webSocketDebuggerUrl"]
                return DEVTOOLS, urlsplit(ws).path
            except (OSError, ValueError, KeyError):
                time.sleep(0.1)
        raise RuntimeError(f"Chrome did not open its DevTools port {DEVTOOLS}")


class UiAgentOpsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = drive.find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-agentops-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        self.p = self.factory.new_project("Order intake", mode="assume", maturity="demo")
        self.q = self.factory.new_project("Room bookings", mode="assume", maturity="demo")
        fakes.seed(self.p)
        self.q.log("model_run", fakes.model_run("assistant", "example-small", 2000, 200, 1.2))
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        fakes.trail(self.tmp / "lanes")
        self.server, self.bootstrap = make_server(self.factory, PORT, runner=drive.QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        with mock.patch.object(drive.subprocess, "Popen", _popen(subprocess.Popen)):
            self.browser = FixedPortBrowser(self.chrome, self.tmp / "chrome")
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
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"agentops-{b.step.replace(' ', '-')}.png")

    def persona(self, persona: str) -> None:
        b = self.browser
        b.click("#person-chip", what="the person chip")
        b.eval("document.querySelector('#person').value = ''; true")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done in the person menu")

    def sign_in(self, persona: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        self.persona(persona)

    def look(self, scheme: str, width: int, route: str) -> None:
        b = self.browser
        b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 1000, "deviceScaleFactor": 1,
                                                     "mobile": width < 500})
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('#grid')", "home")
        b.eval(f"location.hash = {json.dumps(route)}; true")
        b.wait(f"{DRAWN} && document.documentElement.dataset.theme === '{scheme}'", f"{route} in {scheme} at {width}")
        b.eval("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
        self.assertLessEqual(b.eval(SIDEWAYS), 0, (route, scheme, width))
        spills = b.eval("[...document.querySelectorAll('.aop-grid > .card, .aop-tiles .kpi')]"
                        ".filter((c) => c.scrollWidth > c.clientWidth + 1).map((c) => c.getAttribute('aria-labelledby')"
                        " || c.getAttribute('aria-label'))")
        self.assertEqual(spills, [], (route, scheme, width))

    def test_FR_AOP1_AC_9_the_ai_architect_reads_agent_operations_fit_dark_and_light_and_records_the_audit(self):
        b = self.browser
        self.step("sign in as the AI architect")
        self.sign_in("ai_architect")
        b.wait("document.querySelector('#pc-persona').textContent === 'AI architect'", "the persona chip")
        self.step("the sidebar page")
        b.click('#sb-nav a[href="#/agentops"]', what="Agent operations in the sidebar")
        b.wait(DRAWN, "the platform view")
        text = b.eval("document.querySelector('.aop').textContent")
        for said in ("Order intake", "Room bookings", "run_tests", "T-009 needed 3 rounds", "Expected saving"):
            self.assertIn(said, text)
        self.step("drill down from a figure")
        b.click('[aria-labelledby="aop-roles-h"] .bar-row', what="the first bar")
        rows = b.wait("document.querySelectorAll('#modal .aop-drill tbody tr').length", "the runs behind it")
        self.assertGreater(rows, 0)
        b.key("Escape", 27)
        b.wait("!document.querySelector('#modal .aop-drill')", "the runs closed")
        self.step("record the audit")
        b.click('[data-key="aop-audit"]', what="Record the audit")
        b.wait("(document.querySelector('#status') || {}).textContent.includes('Optimise audit is recorded')",
               "the audit recorded")
        from kernel.learn import factory_project

        rec = factory_project(self.factory).ledger().of_kind("agent_ops_audited")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"]), (PERSON, "ai_architect"))
        self.step("the project opens on Agent operations")
        b.eval(f"location.hash = '#/p/{self.p.pid}'; true")
        b.wait("!!document.querySelector('.cap-t.on[data-capsule=\"agents\"]')"
               " && !!document.querySelector('a[data-view=\"agentops\"][aria-current=\"page\"]')",
               "the project in the Agents capsule, on Agent operations")
        b.wait(DRAWN + " && !!document.querySelector('.vh-scope')", "the project's view")
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"platform {scheme} {width}")
                self.look(scheme, width, "#/agentops")
                self.step(f"project {scheme} {width}")
                self.look(scheme, width, f"#/p/{self.p.pid}/agentops")
        self.step("a business owner reads it in plain words")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        self.persona("business_owner")
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('#grid')", "home")
        b.eval("location.hash = '#/agentops'; true")
        b.wait(DRAWN, "the view as a business owner")
        seen = b.eval(f"({VISIBLE})('.aop')")
        bad = sorted({(w, t) for t, _ in seen for w in JARGON if re.search(rf"\b{re.escape(w)}\b", t.lower())})
        self.assertEqual(bad, [], "jargon a business owner meets unexplained")
        self.check()


if __name__ == "__main__":
    unittest.main()
