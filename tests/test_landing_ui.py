"""FR-LND1-AC-9 in a real browser (headless Chrome over the DevTools protocol, as tests/test_ui_drive.py), on the demo
home (kernel/demo.py: a built project with a release, an adopted service, a project at its questions).

Entering the adopted project opens on Start here (what Rihmasto understood, the steps as buttons, Hide and Show again);
a task opens from the board into its panel (criteria, tests, history, actions) and Start it is signed; the board
filters by status; a job's whole log opens at #/jobs/<id> with Follow and Copy and, once it ended, what it changed; Agent
activity lists the runs to open. Dark at 1440 px, then light at 390 px; no console error, no CSP violation and nothing
wider than the screen after each step. The cockpit listens on port 9370 and Chrome's DevTools on 9870 only
(RIHMA_LND_PORT and RIHMA_LND_DEVTOOLS move them). Skipped when Chrome is not installed.
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
from urllib.parse import urlsplit
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_drive  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads, task_detail  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
PORT = int(os.environ.get("RIHMA_LND_PORT") or 9370)
DEVTOOLS = int(os.environ.get("RIHMA_LND_DEVTOOLS") or 9870)
OVERFLOW = "Math.max(document.documentElement.scrollWidth, window.innerWidth) - {device}"
WIDE = ("[...document.querySelectorAll('#main *')].filter((e) => e.getBoundingClientRect().right > {device} + 1 && !e.closest('.caps'))"
        ".slice(0, 6).map((e) => e.tagName + '.' + e.className + '<' + (e.parentElement ? e.parentElement.className : '')"
        " + ' ' + Math.round(e.getBoundingClientRect().right))")
REAL_POPEN = subprocess.Popen


def pinned(args, **kw):
    """Chrome on the DevTools port this test may use, never a random one."""
    return REAL_POPEN([a.replace("--remote-debugging-port=0", f"--remote-debugging-port={DEVTOOLS}") for a in args],
                      **kw)


class PinnedBrowser(Browser):
    """test_ui_drive's Browser on a fixed DevTools port: Chrome writes no DevToolsActivePort file for one, so the
    browser's own endpoint is read from /json/version."""

    def _devtools_port(self) -> tuple[int, str]:
        for _ in range(300):
            if self.proc.poll() is not None:
                raise RuntimeError(f"Chrome exited with {self.proc.returncode} (is port {DEVTOOLS} taken?)")
            try:
                return DEVTOOLS, urlsplit(test_ui_drive._get_json(DEVTOOLS, "/json/version")["webSocketDebuggerUrl"]).path
            except (OSError, ValueError, KeyError):
                time.sleep(0.1)
        raise RuntimeError(f"Chrome did not open its DevTools port {DEVTOOLS}")


class LandingUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-lnd-")).resolve()
        home = cls.tmp / "home"
        try:
            build_demo(home, echo=lambda line: None)
        except Exception:
            roads.stop_started()
            roads.rmtree(cls.tmp)
            raise
        cls.factory = Factory(home)
        by = {p.meta.get("title"): p for p in cls.factory.projects()}
        cls.stock = by["Stock levels service"]
        cls.webhook = by["Shipment webhook to the stock system"]
        cls.server, cls.bootstrap = make_server(cls.factory, PORT, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        roads.stop_started()
        with contextlib.suppress(OSError):
            roads.rmtree(cls.tmp)

    def setUp(self):
        with mock.patch.object(test_ui_drive.subprocess, "Popen", pinned):
            self.browser = PinnedBrowser(self.chrome, self.tmp / "chrome-landing")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.device = None

    # -- helpers ------------------------------------------------------------------------------------------------

    def step(self, name: str) -> None:
        if self.browser.step != "start":
            self.check()
        self.browser.step = name

    def check(self) -> None:
        b = self.browser
        b.eval("1")
        time.sleep(0.2)
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        device = self.device or b.eval("window.innerWidth")
        self.assertLessEqual(b.eval(OVERFLOW.format(device=device)), 0,
                             f"the page is wider than the {device} px screen during '{b.step}': "
                             f"{b.eval(WIDE.format(device=device))}")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"lnd-{b.step.replace(' ', '-')}.png")

    def sign_in(self, persona: str) -> None:
        b = self.browser
        link = self.server.issue_link(ttl=None)
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={link}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what="the persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def narrow(self) -> None:
        b = self.browser
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1,
                                                     "mobile": True})
        b.wait("window.screen.width === 390", "the narrow screen")
        self.device = 390
        time.sleep(0.3)

    def go(self, route: str) -> None:
        b = self.browser
        r = json.dumps(route)
        b.eval(f"if (location.hash !== {r}) {{ document.querySelector('#main').dataset.loaded = '';"
               f" location.hash = {r}; }} true")
        b.wait("document.querySelector('#main').dataset.loaded === '1'", route, timeout=30)
        time.sleep(0.2)

    # -- the walk -----------------------------------------------------------------------------------------------

    def landing(self, label: str) -> None:
        b = self.browser
        self.step(f"start here {label}")
        b.eval("location.hash = '#/home'; true")
        b.wait("document.querySelector('#main').dataset.loaded === '1'", "Home")
        self.go(f"#/p/{self.stock.pid}")
        b.wait("!!document.querySelector('.start-here .sh-step')", "Start here with its steps", timeout=30)
        said = b.eval("document.querySelector('.start-here .sh-u').innerText")
        self.assertIn("Stock levels service", said)
        steps = b.eval("[...document.querySelectorAll('.start-here .sh-step b')].map((e) => e.textContent)")
        self.assertTrue(1 <= len(steps) <= 3, steps)
        self.assertTrue(b.eval("!!document.querySelector('.start-here .sh-mw')"))
        self.assertTrue(b.eval("document.querySelector('.view-body').firstElementChild.classList.contains('sh-box')"))
        self.step(f"start here hidden {label}")
        b.click(".start-here [data-key='sh-hide']", what="Hide")
        b.wait("!!document.querySelector('.sh-hidden')", "the hidden line")
        b.click(".sh-hidden [data-key='sh-show']", what="Show Start here")
        b.wait("!!document.querySelector('.start-here .sh-step')", "Start here again")

    def task_panel(self, label: str, tid: str) -> None:
        b = self.browser
        self.step(f"tasks board {label}")
        self.go(f"#/p/{self.webhook.pid}/tasks")
        b.wait("!!document.querySelector('.tl-bar') && !!document.querySelector('.tc-open')", "the board's filters")
        b.click(f".tc-open[data-key='tc-open:{tid}']", what=f"Open on {tid}")
        b.wait(f"location.hash.endsWith('/tasks/{tid}') && !!document.querySelector('.task-panel .td-acts')",
               "the task's panel", timeout=30)
        self.step(f"task panel {label}")
        heads = b.eval("[...document.querySelectorAll('.task-panel .td-s h4')].map((e) => e.textContent)")
        self.assertGreaterEqual(len(heads), 4, heads)
        self.assertTrue(b.eval("!!document.querySelector('.task-panel [data-control=task_handoff]')"))

    def test_FR_LND1_AC_9_start_here_a_task_panel_filters_and_the_whole_log_in_the_browser(self):
        b = self.browser
        rows = task_detail.rows(self.webhook)["tasks"]
        self.assertTrue(rows, "the demo's built project has tasks")
        opened = rows[0]["id"]
        pending = next((r["id"] for r in rows if r["status"] == "pending"), None)
        job = self.server.start_job("run", self.webhook.pid, ["-m", "kernel.cli", "run", self.webhook.pid],
                                    {"person": PERSON, "persona": "developer"})
        log = Path(job["log"])
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(("\n".join(f"step {i}: checked the stock feed" for i in range(400)) + "\nthe run ended\n")
                        .encode("utf-8"))
        self.sign_in("developer")
        self.theme("dark", "Dark")
        self.landing("1440 dark")
        self.task_panel("1440 dark", opened)
        if pending:
            self.go(f"#/p/{self.webhook.pid}/tasks/{pending}")
            b.wait("!!document.querySelector('.task-panel [data-key=td-start]')", "Start it")
            self.step("task started 1440 dark")
            b.click(".task-panel [data-key=td-start]", what="Start it")
            b.wait("!!document.querySelector('.task-panel') && document.querySelector('.task-panel .td-st')"
                   " && /started/.test(document.querySelector('.task-panel .td-st').textContent)", "started", timeout=30)
            self.assertTrue(self.webhook.ledger().of_kind("task_started"))
        self.step("filter 1440 dark")
        b.eval("(() => { const s = document.querySelector('#tl-status'); s.value = 'merged';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("/ of /.test((document.querySelector('.tl-n') || {}).textContent || '')"
               " && document.querySelector('#tl-status').value === 'merged'", "the filtered board", timeout=30)
        shown = b.eval("[...document.querySelectorAll('.board .tcard')].length")
        merged = sum(1 for r in task_detail.rows(self.webhook)["tasks"] if r["status"] == "merged")
        self.assertEqual(shown, merged)
        b.eval("(() => { const s = document.querySelector('#tl-status'); s.value = '';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("document.querySelector('#tl-status').value === ''", "every status again", timeout=30)
        self.step("whole log 1440 dark")
        self.go(f"#/jobs/{job['id']}")
        b.wait("/the run ended/.test((document.querySelector('.rl-out') || {}).textContent || '')", "the whole log")
        self.assertTrue(b.eval("!!document.querySelector('[data-control=run_log_copy]')"))
        self.assertTrue(b.eval("document.querySelector('#rl-follow').checked"))
        b.wait("!!document.querySelector('#rl-changed-h')", "what the job changed", timeout=30)
        self.step("activity runs 1440 dark")
        self.go("#/agents")
        b.wait(f"!!document.querySelector('[aria-labelledby=aa-runs-h] a[href=\"#/jobs/{job['id']}\"]')", "the run in Agent activity")
        # light, on a phone
        self.theme("light", "Light")
        self.narrow()
        self.landing("390 light")
        self.task_panel("390 light", opened)
        self.step("whole log 390 light")
        self.go(f"#/jobs/{job['id']}")
        b.wait("/the run ended/.test((document.querySelector('.rl-out') || {}).textContent || '')", "the whole log")
        self.check()


if __name__ == "__main__":
    unittest.main()
