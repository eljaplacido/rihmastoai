"""FR-ITO1-AC-7: what IT checks, in a real browser (headless Chrome over the DevTools protocol).

Over the stand-ins of tests/itops_fixture.py (every check reaches this machine only), IT opens the Order service's
IT checks view in the Run capsule, turns the check set on, runs it, takes a check away for this project, runs an
assessment of the database family, turns an eval set on, sets up an automation IT's context suggests and asks Rihma
what IT should check; then sees the set's card on Health and on Integrations and data, the defaults per solution type
on the platform's Integrations and data page and the eval sets over time on Agent operations, and the documents-only
project saying plainly it has nothing to check; first in the dark theme at 1440 px, then in the light theme at 390
px. After every step there is no console error, failed request or Content-Security-Policy violation, every control
has a name and nothing is wider than the screen. Skipped when Chrome is not installed (``RIHMA_CHROME`` names another
binary). ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step; ``RIHMA_UI_PORT`` and ``RIHMA_DEVTOOLS_PORT`` fix
the cockpit's and Chrome's ports (any free one otherwise).
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

import itops_fixture as fx  # noqa: E402
from factory_fakes import isolated_routing  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, _get_json, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import automations  # noqa: E402
from kernel.checks import infra  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

UNNAMED = """[...document.querySelectorAll('#main button, #main a[href], #main input, #main select')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim()
                    || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (el.tagName !== 'INPUT' && el.tagName !== 'SELECT' && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


class _Cleanups:
    def __init__(self) -> None:
        self.undo: list = []

    def addCleanup(self, fn, *args) -> None:  # noqa: N802 - unittest's name
        self.undo.append((fn, args))

    def run(self) -> None:
        while self.undo:
            fn, args = self.undo.pop()
            with contextlib.suppress(Exception):
                fn(*args)


class _FixedPort(Browser):
    """Chrome on a port named beforehand: its browser endpoint is read from /json/version."""

    def _devtools_port(self) -> tuple[int, str]:
        port = int(os.environ["RIHMA_DEVTOOLS_PORT"])
        for _ in range(300):
            if self.proc.poll() is not None:
                raise RuntimeError(f"Chrome exited with {self.proc.returncode}")
            try:
                ws = _get_json(port, "/json/version")["webSocketDebuggerUrl"]
                return port, urlsplit(ws).path
            except (OSError, ValueError, KeyError, TypeError):
                time.sleep(0.1)
        raise RuntimeError("Chrome did not open its DevTools port")


def browser(chrome: str, profile: Path) -> Browser:
    """Chrome on RIHMA_DEVTOOLS_PORT when it is set, else on any free port."""
    port = os.environ.get("RIHMA_DEVTOOLS_PORT")
    if not port:
        return Browser(chrome, profile)
    real = subprocess.Popen

    def popen(argv, **kw):
        return real([a.replace("--remote-debugging-port=0", f"--remote-debugging-port={port}") for a in argv], **kw)
    with mock.patch.object(subprocess, "Popen", popen):
        return _FixedPort(chrome, profile)


class ItOpsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-ito-")).resolve()
        cls.cleanups = _Cleanups()
        isolated_routing(cls.cleanups, cls.tmp)
        cls.calls = []
        for name, fake in fx.guard(cls.calls).items():
            patcher = mock.patch.object(infra, name, fake)
            patcher.start()
            cls.cleanups.addCleanup(patcher.stop)
        cls.s = fx.Standins()
        cls.factory = Factory(cls.tmp / "home", clock=FixedClock("2026-11-25T09:00:00Z"))
        w = fx.populate(cls.factory, cls.s, cls.tmp / "data")
        cls.project, cls.docs = w["project"], w["docs"]
        for i, verdict in enumerate(("passed", "passed", "failed")):        # an eval set with a trend to draw
            cls.project.log("model_run", {"role": "assistant", "model": "local-a", "tool_calls": 4, "tool_errors": 0,
                                          "tokens": {"in": 100, "out": 20}})
            from kernel.store import updating_json

            with updating_json(cls.project.path("evals", "results.json"), {}) as kept:
                kept.setdefault("security", []).append({"eval": "security", "label": "Security posture",
                                                         "verdict": verdict, "summary": "surface read",
                                                         "at": f"2026-11-2{i + 2}T00:00:00Z", "scores": {},
                                                         "findings": [], "new_findings": 0, "issues": 0})
        with updating_json(cls.project.path("evals", "results.json"), {}) as kept:
            kept["compliance"] = [{"eval": "compliance", "label": "Compliance mapping", "verdict": "failed",
                                   "summary": "3 of 4 controls with evidence, 0 partial, 1 gap(s)",
                                   "at": "2026-11-25T00:00:00Z", "scores": {"evidence_pct": 75.0},
                                   "new_findings": 1, "issues": 1, "findings": [
                                       {"id": "F-aaaaaaa001", "title": "EU AI Act LOGGING: gap", "severity": "issue",
                                        "new": True, "evidence": ["fix: turn on the audit trail"]}]}]
            kept["dataflow"] = [{"eval": "dataflow", "label": "Data-flow register", "verdict": "passed",
                                 "summary": "2 destination(s), 1 hosted, 0 refused by the residency rule",
                                 "at": "2026-11-25T00:00:00Z", "scores": {"destinations": 2, "hosted": 1},
                                 "new_findings": 0, "issues": 0, "findings": [
                                     {"id": "F-bbbbbbb002", "title": "Hosted model sends prompts to api.example.org",
                                      "severity": "advice", "new": False,
                                      "evidence": ["locality hosted, region EU"]}]}]
        port = int(os.environ.get("RIHMA_UI_PORT") or 0)
        cls.server, cls.bootstrap = make_server(cls.factory, port, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "server", None):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(5)
        cls.s.stop()
        cls.cleanups.run()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = browser(self.chrome, self.tmp / "chrome-ito")
        self.addCleanup(self.browser.close)
        if os.environ.get("RIHMA_UI_SHOTS"):
            self.browser.shots = Path(os.environ["RIHMA_UI_SHOTS"])     # a timed-out wait leaves a screenshot

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
        self.assertEqual(b.eval("window.__itoErrors || []"), [], f"uncaught page errors during '{b.step}'")
        if os.environ.get("RIHMA_UI_SHOTS"):
            shots = Path(os.environ["RIHMA_UI_SHOTS"])
            shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(shots / f"itops-{b.step.replace(' ', '-').replace(',', '')}.png")

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
        b.wait("!document.documentElement.classList.contains('signed-out')"
               " && !!document.querySelector('#grid .widget')",
               "the signed-in dashboard")
        b.eval("window.__itoErrors = [];"
               " window.addEventListener('error', (e) => window.__itoErrors.push(String(e.message)));"
               " window.addEventListener('unhandledrejection', (e) => window.__itoErrors.push(String(e.reason))); true")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-it"]', what="the IT persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def toast(self, words: str, what: str) -> None:
        b = self.browser
        b.wait(f"(document.querySelector('#status') || {{}}).textContent.includes({json.dumps(words)})", what)
        b.click("#status .toast .icon-btn", what="Dismiss on the message")
        b.wait("!document.querySelector('#status .toast')", "the message dismissed")

    def open_view(self, pid: str, view: str, ready: str, what: str) -> None:
        b = self.browser
        b.eval(f"location.hash = '#/p/{pid}/{view}'; true")
        b.wait(ready, what)
        time.sleep(0.3)

    def the_view(self) -> None:
        b, pid = self.browser, self.project.pid
        self.open_view(pid, "itops", "document.querySelectorAll('#ito-checks .ito-row').length >= 6",
                       "the IT checks with why")
        self.assertTrue(b.eval("!!document.querySelector('.caps-sub a[data-view=\"itops\"]')"), "in the Run capsule")
        self.assertTrue(b.eval("document.querySelector('.ito-row[data-check=\"database\"]').textContent"
                               ".includes('Database-backed')"))
        self.assertTrue(b.eval("!!document.querySelector('.ito-row[data-check=\"app\"]"
                               " [data-scope=\"platform default\"]')"))
        self.fits_and_named()
        self.step("turn the set on")
        b.click('[data-key="ito-apply"]', what="Turn on the IT checks")
        self.toast("turned on", "the set turned on")
        self.assertIn("database", cstore.enabled(self.project))
        self.step("run the IT checks")
        b.click('[data-key="ito-run"]', what="Run the IT checks now")
        self.toast("ran", "the IT checks ran")
        b.wait("!!document.querySelector('.ito-row[data-check=\"database\"] [data-verdict=\"passed\"]')",
               "the database check passed")
        self.step("take dns away here")
        b.click('[data-key="ito-off:dns"]', what="Take away here on dns")
        self.toast("taken away", "dns taken away")
        b.wait("!!document.querySelector('[data-removed=\"dns\"]')", "dns among the ones taken away")
        self.step("run an assessment")
        b.eval("const s = document.querySelector('#ito-target'); s.value = 'family';"
               " s.dispatchEvent(new Event('change')); true")
        b.type("#ito-target-name", "database")
        b.click('[data-key="ito-assess"]', what="Run the assessment")
        b.wait("(document.querySelector('#ito-assess-out') || {}).textContent?.includes('family:database')",
               "the assessment's outcome")
        self.step("turn an eval set on")
        b.click('[data-key="ito-ev:role:ask_answers"]', what="Turn on Ask Rihma answers")
        self.toast("turned on", "the eval set on")
        b.wait("!!document.querySelector('.ito-row[data-set=\"gnomon:security\"] .hl-sq.bad')", "the security trend")
        self.step("read eval results and what needs action")
        compliance = '.ito-row[data-set="gnomon:compliance"]'
        dataflow = '.ito-row[data-set="gnomon:dataflow"]'
        self.assertIn("3 of 4 controls", b.eval(f'document.querySelector({json.dumps(compliance)}).textContent'))
        self.assertIn("2 destination(s)", b.eval(f'document.querySelector({json.dumps(dataflow)}).textContent'))
        b.click(compliance + " summary", what="the compliance result and findings")
        self.assertIn("Action needed", b.eval(f'document.querySelector({json.dumps(compliance)}).textContent'))
        self.assertIn("Suggested action: turn on the audit trail",
                      b.eval(f'document.querySelector({json.dumps(compliance)}).textContent'))
        b.click(dataflow + " summary", what="the data-flow result and findings")
        self.assertIn("For review", b.eval(f'document.querySelector({json.dumps(dataflow)}).textContent'))
        self.assertIn("do not fail the audit", b.eval(f'document.querySelector({json.dumps(dataflow)}).textContent'))
        b.click(compliance + ' [data-control="handoff"]', what="Hand the compliance finding to Claude Code")
        b.wait("document.querySelector('#modal').open && document.querySelector('#ho-to')?.options.length > 0",
               "the hand-off dialog")
        self.assertEqual(b.eval("document.querySelector('#ho-to').value"), "claude-code")
        b.key("Escape", 27)
        b.wait("!document.querySelector('#modal').open", "the hand-off dialog closed")
        b.click(compliance + ' [data-control="evals_make_change"]', what="Make the compliance finding a change")
        self.toast("filed", "the compliance finding filed")
        b.wait(f"!!document.querySelector({json.dumps(compliance)} + ' a[data-key^=\"ito-card:\"]')",
               "the compliance finding's change")
        self.step("set up a suggested automation")
        b.click('[data-key="ito-sg:it_db_nightly"]', what="Set it up on the nightly database probe")
        self.toast("set up", "the automation set up")
        self.assertTrue(any(a["action"] == {"kind": "run_check", "check": "database"}
                            for a in automations.automations(self.factory)))
        self.step("ask what IT should check")
        b.click('[data-key="ito-ask"]', what="Ask what IT should check")
        b.wait("(document.querySelector('#assistant') || {}).textContent?.includes('Database-backed')",
               "Rihma's answer")
        b.click("#as-close", what="Close Ask Rihma")

    def elsewhere(self) -> None:
        b, pid = self.browser, self.project.pid
        self.open_view(pid, "checks", "!!document.querySelector('#ito-mini-card-h')", "the IT checks card on Health")
        self.fits_and_named()
        self.step("on integrations and data")
        self.open_view(pid, "itdata", "!!document.querySelector('#ito-mini-card-h')",
                       "the card on Integrations and data")
        self.step("the defaults per type")
        b.eval("location.hash = '#/connections'; true")
        b.wait("document.querySelectorAll('[data-control=\"itops_defaults\"] .ito-row[data-type]').length >= 9",
               "the defaults per solution type")
        b.eval("document.querySelector('#ito-defaults-h').scrollIntoView(); true")
        self.fits_and_named()
        self.step("the eval sets over time")
        b.eval("location.hash = '#/agentops'; true")
        b.wait("!!document.querySelector('.ito-trends .ito-row[data-set=\"gnomon:security\"]')",
               "the eval sets over time")
        b.eval("document.querySelector('#ito-trends-h').scrollIntoView(); true")
        self.fits_and_named()
        self.step("documents only")
        self.open_view(self.docs.pid, "itops", "!!document.querySelector('.ito-view [data-empty=\"itops\"]')",
                       "the documents-only project's IT checks")
        said = b.eval("document.querySelector('.ito-view [data-empty=\"itops\"]').textContent")
        self.assertIn("runs nothing", said)
        self.fits_and_named()

    def test_FR_ITO1_AC_7_it_sees_and_runs_its_checks_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("the IT checks view")
        self.the_view()
        self.step("health")
        self.elsewhere()
        self.step("light and narrow")
        self.theme("light", "Light")
        b.cmd("Emulation.setDeviceMetricsOverride",
              {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        self.step("the IT checks view, narrow")
        self.open_view(self.project.pid, "itops", "document.querySelectorAll('#ito-checks .ito-row').length >= 6",
                       "the IT checks, narrow")
        self.fits_and_named()
        b.eval("document.querySelector('#ito-evals-h').scrollIntoView(); true")
        self.fits_and_named()
        self.step("the defaults, narrow")
        b.eval("location.hash = '#/connections'; true")
        b.wait("document.querySelectorAll('[data-control=\"itops_defaults\"] .ito-row[data-type]').length >= 9",
               "the defaults, narrow")
        self.fits_and_named()
        self.assertTrue(all(c[0] != "fetch" or "127.0.0.1" in c[1] for c in self.calls), "nothing left this machine")
        self.check()

    def assess(self, kind: str, name: str) -> None:
        b = self.browser
        b.eval(f"document.querySelector('#ito-target').value = {json.dumps(kind)};"
               " document.querySelector('#ito-target').dispatchEvent(new Event('change')); true")
        b.eval(f"document.querySelector('#ito-target-name').value = {json.dumps(name)}; true")
        b.click('[data-key="ito-assess"]', what="Run the assessment")

    def as_persona(self, persona: str) -> None:
        b = self.browser
        b.click("#person-chip", what="the person chip")
        b.click(f'label[for="pp-{persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done in the person menu")

    def failed_assessments(self) -> None:
        """FR-ITO2: an assessment that is refused never leaves the last result beside its error."""
        b = self.browser
        out = "(document.querySelector('#ito-assess-out') || {}).textContent || ''"
        self.assess("family", "database")
        b.wait(f"({out}).includes('family:database')", "the assessment's outcome")
        self.assess("family", "")
        b.wait(f"({out}).includes('Say which one')", "asked which one")
        self.assertNotIn("family:database", b.eval(out))
        self.assess("family", "database")
        b.wait(f"({out}).includes('family:database')", "the assessment's outcome again")
        self.assess("check", "nosuch")
        b.wait(f"({out}).includes('check:nosuch')", "the refusal in place of the last result")
        self.assertNotIn("family:database", b.eval(out))
        b.wait("!!document.querySelector('#status .toast')", "the refusal's message")
        b.click("#status .toast .icon-btn", what="Dismiss on the message")
        time.sleep(0.3)
        b.problems[:] = [p for p in b.problems if "400" not in str(p) and "nosuch" not in str(p)]

    def business_owner(self) -> None:
        """FR-ITO2: a business owner reads the set, but is told whose turning it on and running it is."""
        b = self.browser
        self.as_persona("business_owner")
        self.open_view(self.project.pid, "itops", "!!document.querySelector('.ito-whose')", "whose the set is")
        self.assertTrue(b.eval("document.querySelector('[data-key=\"ito-run\"]').disabled"))
        self.assertTrue(b.eval("document.querySelector('[data-key=\"ito-apply\"]').disabled"))
        self.fits_and_named()
        from kernel import itops_chat

        said = itops_chat.answer(self.factory, "run the IT checks", self.project, "business_owner")
        self.assertFalse([p for p in said["propose"] if p.get("action") == "act"])
        self.as_persona("it")

    def test_FR_ITO2_AC_9_a_refused_assessment_and_another_persona_are_said_dark_wide_and_light_narrow(self):
        b = self.browser
        if "database" not in cstore.enabled(self.project):
            cstore.enable(self.project, "database", person=PERSON, persona="it")
        server, boot = make_server(self.factory, 0, runner=QuietRunner())    # its own one-use sign-in link
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(5)))
        self.server, self.bootstrap = server, boot          # this test's own; the class's stay on the class
        self.step("sign in, wide and dark")
        self.sign_in()
        self.theme("dark", "Dark")
        self.open_view(self.project.pid, "itops", "!!document.querySelector('#ito-assess-card-h')", "the view")
        self.step("assessments, wide")
        self.failed_assessments()
        self.step("a business owner, wide")
        self.business_owner()
        self.step("light and narrow")
        self.theme("light", "Light")
        b.eval("location.hash = '#/home'; true")                # a phone opens the view, it is not resized onto it
        b.wait("!!document.querySelector('#grid .widget')", "home")
        b.cmd("Emulation.setDeviceMetricsOverride",
              {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        self.open_view(self.project.pid, "itops", "!!document.querySelector('#ito-assess-card-h')", "the view, narrow")
        self.step("assessments, narrow")
        self.failed_assessments()
        b.eval("document.querySelector('#ito-assess-card-h').scrollIntoView(); true")
        self.fits_and_named()
        self.step("a business owner, narrow")
        self.business_owner()
        self.check()


if __name__ == "__main__":
    unittest.main()
