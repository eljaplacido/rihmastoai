"""Rihmasto's structure and Where the work went in a real browser (FR-STR1-AC-6): headless Chrome over the DevTools
protocol, as tests/test_ui_drive.py drives it.

A team's repository (tests/alignment_fixture.py) is attached and read; a code change was committed two days ago and
the trace links were accepted. A person opens the Alignment view: it says how much is taken in from the project's
own files and how much is Rihmasto's own conventions, folded as suggestions. They preview Off for tests trace to
requirements, save it with a reason and see the hidden count with why; then read Where the work went on the
Overview and across projects on Insights, and Rihmasto's structure for all projects in Settings. Each is looked at in
dark and light, 1440 and 390 pixels wide: every control has a name, nothing scrolls sideways, and no step leaves a
console error, a failed request or a Content-Security-Policy violation. The repository is never written.

``RIHMA_UI_COCKPIT_PORT`` and ``RIHMA_UI_DEVTOOLS_PORT`` pin the cockpit's and Chrome's ports (any free port by
default). Skipped when Chrome is not installed. ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_alignment as alignment_ui  # noqa: E402  (the module, so its TestCase is not collected here again)
from alignment_fixture import git, make_repo  # noqa: E402
from structure_fakes import recent_work  # noqa: E402
from test_ui_drive import Browser, QuietRunner  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import alignment_records as ar  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

PERSON = alignment_ui.PERSON
POPEN = subprocess.Popen


def _marker(port: int, profile: Path) -> None:
    """Chrome writes DevToolsActivePort only for a port it chose: for a pinned one, write it from /json/version."""
    for _ in range(300):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                url = json.loads(r.read().decode("utf-8"))["webSocketDebuggerUrl"]
            (profile / "DevToolsActivePort").write_text(f"{port}\n{url.split(str(port), 1)[1]}\n", encoding="utf-8")
            return
        except (OSError, ValueError, KeyError):
            time.sleep(0.1)


def _pinned_chrome(args, *a, **kw):
    """Chrome on the DevTools port named by RIHMA_UI_DEVTOOLS_PORT, when one is."""
    port = os.environ.get("RIHMA_UI_DEVTOOLS_PORT")
    if not (port and isinstance(args, list) and "--remote-debugging-port=0" in args):
        return POPEN(args, *a, **kw)
    args = [f"--remote-debugging-port={int(port)}" if x == "--remote-debugging-port=0" else x for x in args]
    profile = Path(next(x for x in args if x.startswith("--user-data-dir=")).split("=", 1)[1])
    proc = POPEN(args, *a, **kw)
    threading.Thread(target=_marker, args=(int(port), profile), daemon=True).start()
    return proc


class UiStructureTest(unittest.TestCase):
    # Chrome and git found, the steps, widths, themes and the sign-in: as the Alignment's own browser test has them.
    setUpClass = classmethod(alignment_ui.UiAlignmentTest.setUpClass.__func__)
    width = alignment_ui.UiAlignmentTest.width
    theme = alignment_ui.UiAlignmentTest.theme
    sign_in = alignment_ui.UiAlignmentTest.sign_in

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-structure-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = make_repo(self.tmp / "loans")
        recent_work(self.repo)
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.factory = Factory(self.tmp / "home", clock=FixedClock())
        self.p = attach(self.factory, "Tool store loans", repo=self.repo, person=PERSON, persona="developer")
        ar.scan(self.p, person=PERSON, persona="developer")
        trace = [i["id"] for g in ar.view(self.p)["groups"] if g["id"] == "trace" for i in g["items"]]
        ar.decide(self.p, trace, "accept", person=PERSON, persona="developer")
        port = int(os.environ.get("RIHMA_UI_COCKPIT_PORT") or 0)
        self.server, self.bootstrap = make_server(self.factory, port, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        with mock.patch("subprocess.Popen", _pinned_chrome):
            self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.steps: list[str] = []
        self.checked: list[str] = []

    def step(self, name: str) -> None:
        """Each step is checked when the next begins (FR-STR2-AC-12): no step is looked at only through the last."""
        if self.browser.step != "start":
            self.check()
        self.browser.step = name
        self.steps.append(name)

    def check(self) -> None:
        b = self.browser
        self.checked.append(b.step)
        b.eval("1")
        time.sleep(0.3)
        b.eval("1")
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        self.assertEqual(b.eval(alignment_ui.NAMELESS), [], f"controls without an accessible name during '{b.step}'")
        self.assertFalse(b.eval(alignment_ui.SIDEWAYS), f"the page scrolls sideways during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"structure-{b.step.replace(' ', '-')}.png")

    def go(self, where: str, ready: str, what: str) -> None:
        self.browser.eval(f"location.hash = {json.dumps(where)}; true")
        self.browser.wait(ready, what, timeout=30)

    def looks(self, where: str, ready: str, shown: str) -> None:
        """The view in both themes at both widths, ``shown`` scrolled into sight for the screenshot."""
        for word in ("Light", "Dark"):
            for px in (1440, 390):
                self.step(f"{where} {word.lower()} {px}")
                self.width(px)
                if self.browser.eval("document.documentElement.dataset.theme") != word.lower():
                    self.theme(word)
                self.browser.wait(f"window.innerWidth === {px}", f"the page at {px} px: nothing wider than it")
                self.browser.wait(ready, f"{where} at {px} px, {word}")
                self.browser.eval(f"document.querySelector({json.dumps(shown)}).scrollIntoView({{block: 'start'}}); true")

    def test_FR_STR1_AC_6_a_person_chooses_rihmastos_structure_and_sees_where_the_work_went_in_chrome(self):
        b = self.browser
        pid = self.p.pid
        self.step("sign in")
        self.sign_in()
        self.step("the alignment says what is taken in and what is Rihmasto's own")
        self.go(f"#/p/{pid}/align", "!!document.querySelector('#st-card-h') && !!document.querySelector('[data-key=\"st-line\"]')",
                "the Alignment view with Rihmasto's structure")
        line = b.eval("document.querySelector('[data-key=\"st-line\"]').textContent")
        self.assertIn("take in the project's own specs, tasks, decisions and contracts", line)
        self.assertIn("yours to decide", line)
        self.assertTrue(b.eval("!!document.querySelector('[data-key=\"al-folded:gaps\"]')"))
        rows = b.eval("[...document.querySelectorAll('#st-card-h ~ * .st-row, .st-row')].map((r) => r.dataset.convention)")
        self.assertEqual(len(rows), 7)
        self.step("preview off for tests trace to requirements")
        b.eval("(() => { const s = document.querySelector('#st-p-test_trace'); s.value = 'off';"
               " s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()")
        b.type("#st-reason-p", "our tests are named by feature")
        b.click('[data-key="st-preview-p"]', what="Preview")
        seen = b.wait("(document.querySelector('[data-key=\"st-preview\"]') || {}).textContent", "the preview")
        self.assertIn("Tests trace to requirements: Advise to Off for this project", seen)
        self.assertEqual(self.p.ledger().of_kind("structure_set"), [])
        self.step("save it")
        b.click('[data-key="st-save-p"]', what="Save")
        hidden = b.wait("(document.querySelector('[data-key=\"al-hidden:gaps\"]') || {}).textContent",
                        "the hidden count", timeout=30)
        self.assertIn("our tests are named by feature", hidden)
        logged = self.p.ledger().of_kind("structure_set")[-1]["event"]["payload"]
        self.assertEqual((logged["person"], logged["reason"]), (PERSON, "our tests are named by feature"))
        self.looks("alignment", "!!document.querySelector('#st-card-h')", "#al-sum-h")
        self.step("where the work went on the overview")
        self.width(1440)
        self.go(f"#/p/{pid}/overview", "!!document.querySelector('#wb-card-h') && !!document.querySelector('[data-key=\"wb-line\"]')",
                "Where the work went on the Overview")
        said = b.eval("document.querySelector('[data-key=\"wb-line\"]').textContent")
        self.assertIn("1 moved development", said)
        self.assertIn("conformed to Rihmasto's structure", said)
        self.assertTrue(b.eval("!!document.querySelector('[data-control=\"work_balance\"] .bar-list')"))
        b.click('[data-key="wb-conform"] summary', what="the items behind the conformance bar")
        self.assertGreater(b.eval("document.querySelectorAll('[data-side=\"conform\"] li').length"), 0)
        self.looks("overview", "!!document.querySelector('[data-key=\"wb-line\"]')", "#wb-card-h")
        self.step("across projects on insights")
        self.width(1440)
        self.go("#/insights", "!!document.querySelector('#wb-all-h') && !!document.querySelector('#wb-all-h') "
                "&& !!document.querySelector('[data-key=\"wb-line\"]')", "Where the work went on Insights")
        self.looks("insights", "!!document.querySelector('[data-key=\"wb-line\"]')", "#wb-all-h")
        self.step("rihmasto's structure for all projects in settings")
        self.width(1440)
        self.go("#/settings", "!!document.querySelector('#st-plat-h')", "Rihmasto's structure in Settings")
        self.assertEqual(b.eval("document.querySelectorAll('#st-platform .st-kind').length"), 2)
        self.looks("settings", "!!document.querySelector('#st-plat-h')", "#st-plat-h")
        self.check()
        self.assertEqual(self.checked, self.steps)                                          # every step was checked
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)                    # never written
        self.assertEqual(git(self.repo, "status", "--porcelain", "--untracked-files=all"), "")

    def test_FR_STR2_AC_12_each_item_says_what_it_is_and_a_save_waits_for_its_impact_and_reason_in_chrome(self):
        b = self.browser
        pid = self.p.pid
        tasks = [i["id"] for g in ar.view(self.p)["groups"] if g["id"] == "tasks" for i in g["items"]]
        self.step("sign in")
        self.sign_in()
        self.step("each item says what it counts as and how old its source is")
        self.go(f"#/p/{pid}/align", "!!document.querySelector('[data-key=\"st-line\"]') && "
                "!!document.querySelector('#al-g-tasks-h')", "the Alignment view")
        title = b.eval("document.querySelector('#al-sum-h').textContent")
        self.assertIn("Taken in from the project's own files", title)               # not Rihmasto's own measure first
        task = f"[data-id=\"{tasks[0]}\"]"
        self.assertEqual(b.eval(f"document.querySelector('{task} [data-counts-as]').dataset.countsAs"), "take_in")
        self.assertEqual(b.eval(f"document.querySelector('{task} .al-age').dataset.older"), "1")
        self.assertIn("days before the newest code", b.eval(f"document.querySelector('{task} .al-age').textContent"))
        self.assertIn("neither development nor conformance",
                      b.eval(f"document.querySelector('{task} [data-key^=\"al-side:\"]').textContent"))
        folded = "document.querySelectorAll('.al-folded .al-row')"
        self.assertGreater(b.eval(f"{folded}.length"), 0)
        self.assertEqual(b.eval(f"[...{folded}].filter((r) => /To decide/.test(r.querySelector('.as-h').textContent))"
                                ".length"), 0)                                     # a suggestion is never "to decide"
        self.assertEqual(b.eval(f"[...{folded}].filter((r) => r.dataset.status === 'open' && "
                                "!r.querySelector('[data-status-chip=\"suggestion\"]')).length"), 0)
        self.assertGreater(b.eval("document.querySelectorAll('.al-folded [data-status-chip=\"suggestion\"]')"
                                  ".length"), 0)
        self.step("a save without a reason is refused and records nothing")
        b.eval("(() => { const s = document.querySelector('#st-p-criteria'); s.value = 'off';"
               " s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()")
        b.click('[data-key="st-save-p"]', what="Save")
        b.wait("document.activeElement && document.activeElement.id === 'st-reason-p'", "the reason asked for")
        self.assertFalse(b.eval("!!document.querySelector('[data-key=\"st-preview\"]')"))
        self.assertEqual(self.p.ledger().of_kind("structure_set"), [])
        self.step("the first save shows the impact and records nothing")
        b.type("#st-reason-p", "criteria live in our own specs")
        b.click('[data-key="st-save-p"]', what="Save")
        seen = b.wait("(document.querySelector('[data-key=\"st-preview\"]') || {}).textContent", "the preview")
        self.assertIn("Advise to Off for this project", seen)
        self.assertEqual(self.p.ledger().of_kind("structure_set"), [])
        self.assertNotEqual(b.eval("document.querySelector('[data-key=\"st-save-p\"] .lbl').textContent"), "Save")
        self.step("a changed choice needs its own preview")
        b.eval("(() => { const s = document.querySelector('#st-p-test_trace'); s.value = 'off';"
               " s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()")
        self.assertFalse(b.eval("!!document.querySelector('[data-key=\"st-preview\"]')"))
        b.click('[data-key="st-save-p"]', what="Save")
        seen = b.wait("(document.querySelector('[data-key=\"st-preview\"]') || {}).textContent", "the new preview")
        self.assertIn("Tests trace to requirements: Advise to Off", seen)
        self.assertEqual(self.p.ledger().of_kind("structure_set"), [])
        self.step("the second save makes the change it showed")
        b.click('[data-key="st-save-p"]', what="Save this change")
        b.wait("!!document.querySelector('[data-key=\"al-hidden:gaps\"]')", "the hidden count", timeout=30)
        logged = self.p.ledger().of_kind("structure_set")[-1]["event"]["payload"]
        self.assertEqual((logged["reason"], sorted(c["convention"] for c in logged["changes"])),
                         ("criteria live in our own specs", ["criteria", "test_trace"]))
        self.assertIn("Off here", b.eval("document.querySelector('#al-sum-h').textContent"))
        self.looks("alignment items", "!!document.querySelector('#al-g-tasks-h')", "#al-g-tasks-h")
        self.step("taken in counts in neither bar")
        ar.decide(self.p, tasks, "accept", person=PERSON, persona="developer")
        self.width(1440)
        self.go(f"#/p/{pid}/overview", "!!document.querySelector('[data-key=\"wb-line\"]')", "Where the work went")
        said = b.eval("document.querySelector('[data-key=\"wb-line\"]').textContent")
        self.assertIn("5 records taken in from the project's own files", said)
        traced = len(self.p.ledger().of_kind("alignment_accepted")[0]["event"]["payload"]["items"])
        self.assertIn(f"and {traced} conformed to Rihmasto's structure", said)  # the traces only, not the tasks
        b.click('[data-key="wb-take_in"] summary', what="the items taken in")
        self.assertEqual(b.eval("document.querySelectorAll('[data-side=\"take_in\"] li').length"), 5)
        self.looks("overview taken in", "!!document.querySelector('[data-key=\"wb-take_in\"]')", "#wb-card-h")
        self.check()
        self.assertEqual(self.checked, self.steps)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)


if __name__ == "__main__":
    unittest.main()
