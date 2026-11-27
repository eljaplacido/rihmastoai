"""FR-LND2 in a real browser (headless Chrome over the DevTools protocol, as tests/test_ui_drive.py), on the demo home
(kernel/demo.py: built projects, an adopted service).

Entering the adopted project lands on its Board, or the view used last: Correct it takes the person to Overview and its
control; the Board's next development step is Start here's first. A status filter chosen on one project never hides
another project's tasks. A person's done has its own lane, a task that waits says what for and offers no Start, and the
marked-done chip stays in its lane. The cell that stopped keeps its whole log. Dark at 1440 px, then light at 390 px,
where Start here's first step is on the first screen; no console error, no CSP violation and nothing wider than the
screen after each step. The cockpit listens on port 9372 and Chrome's DevTools on 9872 only (RIHMA_LND2_PORT and
RIHMA_LND2_DEVTOOLS move them). Skipped when Chrome is not installed.
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
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads, task_detail, task_rules  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
PORT = int(os.environ.get("RIHMA_LND2_PORT") or 9372)
DEVTOOLS = int(os.environ.get("RIHMA_LND2_DEVTOOLS") or 9872)
OVERFLOW = "Math.max(document.documentElement.scrollWidth, window.innerWidth) - {device}"
REAL_POPEN = subprocess.Popen
# every chip of a task card inside its lane
CHIPS_IN_LANE = ("[...document.querySelectorAll('.tasks-board .tcard .chip')].filter((c) => !c.closest('details:not([open])')"
                 " && c.getBoundingClientRect().right > c.closest('.lane').getBoundingClientRect().right + 1).map((c) => c.textContent + ' '"
                 " + Math.round(c.getBoundingClientRect().right) + '>' + Math.round(c.closest('.lane')"
                 ".getBoundingClientRect().right))")


def pinned(args, **kw):
    return REAL_POPEN([a.replace("--remote-debugging-port=0", f"--remote-debugging-port={DEVTOOLS}") for a in args],
                      **kw)


class PinnedBrowser(Browser):
    def _devtools_port(self) -> tuple[int, str]:
        for _ in range(300):
            if self.proc.poll() is not None:
                raise RuntimeError(f"Chrome exited with {self.proc.returncode} (is port {DEVTOOLS} taken?)")
            try:
                return DEVTOOLS, urlsplit(test_ui_drive._get_json(DEVTOOLS, "/json/version")["webSocketDebuggerUrl"]).path
            except (OSError, ValueError, KeyError):
                time.sleep(0.1)
        raise RuntimeError(f"Chrome did not open its DevTools port {DEVTOOLS}")


class LandingFixUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-lnd2-")).resolve()
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
        cls.access = by["Access review check"]
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
            self.browser = PinnedBrowser(self.chrome, self.tmp / "chrome-landing-fix")
        self.addCleanup(self.browser.close)
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
        self.assertLessEqual(b.eval(OVERFLOW.format(device=device)), 0, f"wider than {device} px during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"lnd2-{b.step.replace(' ', '-')}.png")

    def sign_in(self) -> None:
        b = self.browser
        link = self.server.issue_link(ttl=None)
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={link}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the persona")
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

    def correct_it(self, label: str) -> None:
        """Entering the adopted project lands on another view than Overview: Correct it goes there."""
        b = self.browser
        pid = self.stock.pid
        self.step(f"enter adopted {label}")
        self.go(f"#/p/{pid}/assessment")                 # the view used last
        self.go("#/home")
        self.go(f"#/p/{pid}")
        b.wait("!!document.querySelector('.start-here .sh-step')", "Start here", timeout=30)
        self.assertNotEqual(b.eval("document.querySelector('.view-body').dataset.view"), "overview")
        if self.device == 390:
            b.wait("document.querySelector('.start-here .sh-step').getBoundingClientRect().top < 844 - 60",
                   "Start here's first step on the first screen at 390 px", timeout=5)
            if self.shots:
                b.screenshot(self.shots / "lnd2-first-screen-390-light.png")
        self.step(f"correct it {label}")
        b.click(".start-here [data-key='sh-correct']", what="Correct it")
        b.wait(f"location.hash === '#/p/{pid}/overview' && !!document.querySelector('[data-control=understood_correct]')",
               "Overview with Correct it's control", timeout=30)

    def board_agrees(self, label: str) -> None:
        b = self.browser
        self.step(f"board agrees {label}")
        self.go(f"#/p/{self.stock.pid}/board")              # the Board, the view used last, then entered again
        self.go("#/home")
        self.go(f"#/p/{self.stock.pid}")
        self.assertEqual(b.eval("document.querySelector('.view-body').dataset.view"), "board")
        b.wait("!!document.querySelector('.start-here .sh-step b') && !!document.querySelector('.dv-next-t')",
               "Start here and the briefing", timeout=30)
        self.assertEqual(b.eval("document.querySelector('.dv-next-t').textContent"),
                         b.eval("document.querySelector('.start-here .sh-step b').textContent"))

    def filters_per_project(self, label: str, done_tid: str) -> None:
        b = self.browser
        self.step(f"marked done lane {label}")
        self.go(f"#/p/{self.access.pid}/tasks")
        b.wait(f"!!document.querySelector('.tasks-board .lane.done .tcard[data-id=\"{done_tid}\"]')",
               "the marked-done task in its own lane", timeout=30)
        if self.shots:
            b.screenshot(self.shots / f"lnd2-done-lane-{label.replace(' ', '-')}.png")
        self.assertEqual(b.eval(CHIPS_IN_LANE), [], "a card's chip reaches past its lane")
        b.eval("(() => { const s = document.querySelector('#tl-status'); s.value = 'done';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("document.querySelector('#tl-status').value === 'done'", "the done filter", timeout=30)
        self.step(f"another project's tasks {label}")
        self.go(f"#/p/{self.webhook.pid}/tasks")
        b.wait("!!document.querySelector('.tl-n')", "the webhook project's board", timeout=30)
        shown = b.eval("document.querySelector('.tl-n').textContent")
        total = len(task_detail.rows(self.webhook)["tasks"])
        self.assertEqual(shown, f"{total} of {total} shown")
        self.assertEqual(b.eval("document.querySelector('#tl-status').value"), "")
        self.go(f"#/p/{self.access.pid}/tasks")               # the access review keeps its own
        b.wait("document.querySelector('#tl-status').value === 'done'", "the access review's own filter", timeout=30)
        b.eval("(() => { const s = document.querySelector('#tl-status'); s.value = '';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("document.querySelector('#tl-status').value === ''", "every status again", timeout=30)

    def waiting_task(self, label: str, tid: str, done_tid: str) -> None:
        b = self.browser
        self.step(f"task waits {label}")
        self.go(f"#/p/{self.access.pid}/tasks/{tid}")
        b.wait("!!document.querySelector('.task-panel .td-wait')", "what the task waits for", timeout=30)
        self.assertFalse(b.eval("!!document.querySelector('.task-panel [data-key=td-start]')"))
        self.assertFalse(b.eval("!!document.querySelector('.task-panel [data-key=td-done]')"))
        self.step(f"marked done note {label}")
        self.go(f"#/p/{self.access.pid}/tasks/{done_tid}")
        b.wait("!!document.querySelector('.task-panel .td-mark > span')", "the marked-done note", timeout=30)
        ratio = b.eval("(() => { const n = document.querySelector('.td-mark'); const s = n.querySelector(':scope > span');"
                       " return s.getBoundingClientRect().width / n.getBoundingClientRect().width; })()")
        self.assertGreater(ratio, 0.6, "the marked-done note breaks into narrow columns")

    def cell_log(self, label: str) -> None:
        b = self.browser
        self.step(f"finished cell log {label}")
        self.go(f"#/jobs/cell:{self.webhook.pid}")
        b.wait("/finished/.test((document.querySelector('.rl-state') || {}).textContent || '')"
               " && /app\\/h2\\.py/.test((document.querySelector('.rl-out') || {}).textContent || '')",
               "the finished cell's whole log", timeout=30)

    WAITING, DONE = "T-002", "T-003"

    @classmethod
    def fixtures(cls) -> None:
        """The access review: T-002 escalated to a decision still open, T-003 after it marked done by a person; the
        webhook's cell stopped, its trail left in a lane."""
        if getattr(cls, "_fixed", False):
            return
        cls._fixed = True
        task_detail.mark_done(cls.access, cls.DONE, person=PERSON, persona="developer",
                              evidence="the access list export was checked by hand against the quarterly report")
        cls.lanes = cls.tmp / "lanes-left"
        audit = cls.lanes / "lane-3" / ".gnomon-audit"
        audit.mkdir(parents=True)
        trail = [{"kind": "session_start", "role": "builder"}, {"kind": "model_call", "model": "demo-model"},
                 *[{"kind": "tool_call", "tool": "edit", "target": f"app/h{i}.py", "ts": "2026-11-26T10:00:0" + str(i)}
                   for i in range(3)], {"kind": "session_end"}]
        (audit / "task-ui-1.jsonl").write_text("\n".join(json.dumps(r) for r in trail) + "\n", encoding="utf-8")
        cls.webhook.log("gnomon_run", {"run": "task-ui-1", "task": cls.WAITING, "round": 0, "role": "builder"})

    def walk(self):
        """The fixtures, a stopped cell, and the person signed in."""
        self.fixtures()
        self.assertEqual(task_rules.waits(self.access, self.WAITING)["kind"], "decision")
        stopped = {"running": False, "why": "no lane is held for this project"}
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch("kernel.status.live", return_value=stopped))
        stack.enter_context(mock.patch("kernel.lanes.lanes_root", return_value=self.lanes))
        self.addCleanup(stack.close)
        self.sign_in()

    def test_FR_LND2_AC_2_correct_it_and_the_board_lead_to_start_heres_place(self):
        self.walk()
        self.theme("dark", "Dark")
        self.correct_it("1440 dark")
        self.board_agrees("1440 dark")
        self.theme("light", "Light")
        self.narrow()
        self.correct_it("390 light")
        self.check()

    def test_FR_LND2_AC_3_filters_per_project_the_done_lane_what_a_task_waits_for_and_the_cell_log(self):
        self.walk()
        self.theme("dark", "Dark")
        self.filters_per_project("1440 dark", self.DONE)
        self.waiting_task("1440 dark", self.WAITING, self.DONE)
        self.cell_log("1440 dark")
        self.theme("light", "Light")
        self.narrow()
        self.filters_per_project("390 light", self.DONE)
        self.waiting_task("390 light", self.WAITING, self.DONE)
        self.cell_log("390 light")
        self.check()

    def test_FR_LND2_AC_8_start_here_on_the_first_phone_screen_and_nothing_past_its_lane_or_in_columns(self):
        self.walk()
        self.theme("light", "Light")
        self.narrow()
        self.correct_it("390 light layout")                 # its first step on the first screen
        self.waiting_task("390 light layout", self.WAITING, self.DONE)   # the marked-done note one line of text
        self.device = None
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1,
                                                                "mobile": False})
        self.browser.wait("window.innerWidth === 1440", "the wide screen again")
        self.theme("dark", "Dark")
        self.filters_per_project("1440 dark layout", self.DONE)          # the chip inside its lane
        self.check()


if __name__ == "__main__":
    unittest.main()
