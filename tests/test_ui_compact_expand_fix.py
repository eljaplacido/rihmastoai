"""Compact boxes stay open for review after a reload, a redraw and an action (FR-CMP2) in a real browser: headless
Chrome over the DevTools protocol, as tests/test_ui_drive.py drives it, on the demo home (``kernel.demo``, invented
projects).

The owner (2026-11-26): "When I change size of something to compact I guess I should be able to roll those compacted
boxes for review?" An independent check of FR-CMP1 found the boxes it opens could lose their Expand: a section whose
content arrives after it loads (Set up this project) after a reload, a head that kept clicking a removed button after
Customize, a side panel that went stale after a decision taken in it, two sections sharing one key, the Agents strip
with two Expand buttons, toasts under the panel, Expand on widgets that cut nothing, and Expand floating over the
section's own controls. Each step below is one of those, at 1440 and 390 px, dark and light; after every step no
console error, failed request or CSP violation, every control named, nothing wider than the screen.

The cockpit listens on ``RIHMA_CMP2_PORT`` (9530) and Chrome's DevTools on ``RIHMA_CMP2_DEVTOOLS`` (10030). Skipped
when Chrome or git is missing. ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
"""

import contextlib
import json
import os
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

import test_ui_drive as drive  # noqa: E402  (the module, so its TestCase is not collected here again)
import test_ui_shape_models as shaped  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads  # noqa: E402
from kernel.store import Factory  # noqa: E402

PORT = int(os.environ.get("RIHMA_CMP2_PORT") or 9530)
DEVTOOLS = int(os.environ.get("RIHMA_CMP2_DEVTOOLS") or 10030)
NAMELESS = shaped.NAMELESS.replace("#modal :is(button, input, textarea, select)",
                                   "#modal :is(button, input, textarea, select), #xp-sheet :is(button, a[href])")
SHEET_OPEN = "!!document.querySelector('#xp-sheet') && document.querySelector('#xp-sheet').open"
WEBHOOK = "Shipment webhook to the stock system"
SETUP = ".setup-box"
SETUP_BTN = ".setup-box > [data-control=\"expand_box\"]"
# a Expand whose name is junk: the button's own words read back as the section's name
JUNK = ("[...document.querySelectorAll('[data-control=\"expand_box\"]')].filter((b) => b.getClientRects().length)"
        ".map((b) => b.getAttribute('aria-label') || '').filter((n) => /^(Expand|Collapse) (Expand|Collapse|Section)\\b/.test(n))")
# eight posts on the Agents strip, more than the five it shows: the page's fetch answers them (invented)
FAKE_AGENTS = """(() => {
  if (window.__fakeAgents) return true;
  window.__fakeAgents = true;
  const real = window.fetch.bind(window);
  window.fetch = async (url, opts) => {
    const u = String(url);
    if (/\\/api\\/projects\\/[^/]+\\/agents$/.test(u) && (!opts || !opts.method || opts.method === 'GET')) {
      const items = Array.from({length: 8}, (_, i) => ({author_kind: i % 2 ? 'agent' : 'person', who: 'Agent ' + (i + 1),
        kind: 'progress', text: 'Invented post number ' + (i + 1), at: '2026-11-26T10:0' + i + ':00Z'}));
      return new Response(JSON.stringify({items, agents: ['Builder'], handoffs: 1, gates: 0, proposals_waiting: [], paused: false}),
        {status: 200, headers: {'Content-Type': 'application/json'}});
    }
    return real(url, opts);
  };
  return true; })()"""
# a running cell on the overview, its live view answered by the page's fetch (invented steps)
FAKE_LIVE = """((pid) => {
  if (window.__fakeLive) return true;
  window.__fakeLive = {n: 4};
  const real = window.fetch.bind(window);
  const steps = (n) => Array.from({length: n}, (_, i) => ({tool: i % 2 ? 'write' : 'bash', target: 'invented/step_' + (n - i) + '.py',
    at: '2026-11-26T10:00:' + String(10 + n - i).padStart(2, '0') + 'Z'}));
  window.fetch = async (url, opts) => {
    const u = String(url);
    if (u === '/api/projects/' + pid + '/live') {
      const recent = steps(window.__fakeLive.n);
      return new Response(JSON.stringify({running: true, task: 'T-001', role: 'builder', model: null, steps: recent.length,
        lane: 'lane-1', last: recent[0], recent, ended: false}), {status: 200, headers: {'Content-Type': 'application/json'}});
    }
    const res = await real(url, opts);
    if (u === '/api/projects/' + pid && res.ok && (!opts || !opts.method || opts.method === 'GET')) {
      const doc = await res.json();
      doc.running = true;
      return new Response(JSON.stringify(doc), {status: 200, headers: {'Content-Type': 'application/json'}});
    }
    return res;
  };
  return true; })"""


def _popen(real):
    """Chrome's DevTools on the port this test was given, never a random one."""
    def start(args, *a, **kw):
        return real([f"--remote-debugging-port={DEVTOOLS}" if str(x).startswith("--remote-debugging-port=") else x
                     for x in args], *a, **kw)
    return start


class FixedPortBrowser(drive.Browser):
    """test_ui_drive's Browser on a fixed DevTools port, asked for its browser endpoint."""

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


def q(sel: str) -> str:
    return f"document.querySelector({json.dumps(sel)})"


class CompactExpandFixUiTest(unittest.TestCase):
    sign_in = drive.UiDriveTest.sign_in
    theme, narrow = shaped.ShapeModelsUiTest.theme, shaped.ShapeModelsUiTest.narrow

    @classmethod
    def setUpClass(cls):
        cls.chrome = drive.find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if drive.shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-cmp2-")).resolve()
        try:
            build_demo(cls.tmp / "demo", echo=lambda line: None)
        except Exception:
            roads.stop_started()
            roads.rmtree(cls.tmp)
            raise
        cls.factory = Factory(cls.tmp / "demo")
        cls.server, cls.bootstrap = make_server(cls.factory, PORT, runner=drive.QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None
        cls.webhook = next(p for p in cls.factory.projects() if p.meta.get("title") == WEBHOOK).pid

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        roads.stop_started()
        with contextlib.suppress(OSError):
            roads.rmtree(cls.tmp)

    def setUp(self):
        with mock.patch.object(drive.subprocess, "Popen", _popen(subprocess.Popen)):
            self.browser = FixedPortBrowser(self.chrome, self.tmp / ("chrome-" + self._testMethodName[-12:]))
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.bootstrap = self.server.issue_link()        # each test signs in with a link of its own

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
        self.assertEqual(b.eval(NAMELESS), [], f"controls with no name during '{b.step}'")
        self.assertEqual(b.eval(JUNK), [], f"an Expand named by its own words during '{b.step}'")
        self.assertLessEqual(b.eval(shaped.OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")
        self.shot(b.step)

    def shot(self, what: str) -> None:
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.browser.screenshot(self.shots / f"cmp2-{what.replace(' ', '-')}.png")

    # -- helpers --------------------------------------------------------------------------------------------

    def overview(self, reload: bool = False) -> None:
        b = self.browser
        if reload:
            b.eval("location.reload(); true")
            time.sleep(0.5)
        else:
            b.eval(f"location.hash = {json.dumps(f'#/p/{self.webhook}/overview')}; true")
        b.wait("!!document.querySelector('.view-body') && document.querySelector('#main').dataset.loaded === '1'"
               " && !!document.querySelector('#setup-card-h')", "the overview with Set up this project")
        time.sleep(0.6)

    def set_size(self, sel: str, want: str) -> str:
        """Customize: the section that holds ``sel`` to ``want`` (normal, compact, wide), then Done. Its key."""
        b = self.browser
        b.click("#customize", what="Customize")
        b.wait("!!document.querySelector('.vcz-sec')", "the sections to customize")
        key = b.eval(f"{q(sel)}.dataset.czKey")
        sec = f'[data-cz-key="{key}"]'
        has = (f"{q(sec)}.classList.contains('cz-{want}')" if want != "normal"
               else f"!{q(sec)}.classList.contains('cz-compact') && !{q(sec)}.classList.contains('cz-wide')")
        for _ in range(3):
            if b.eval(has):
                break
            b.click(f'[data-key="vcz:{key}:size"]', what="the section's size")
            time.sleep(0.3)
        b.wait(has, f"the section {want}")
        b.click('[data-key="vcz:done"]', what="Done")
        b.wait("!document.documentElement.classList.contains('vcz')", "Customize done")
        time.sleep(0.6)
        return key

    def label(self, sel: str) -> str:
        return self.browser.eval(f"{q(sel)} && {q(sel)}.querySelector('.lbl').textContent")

    def close_assistant(self) -> None:
        b = self.browser
        if b.eval("!!document.querySelector('#as-close') && document.querySelector('#as-close').getClientRects().length > 0"):
            b.click("#as-close", what="Close the assistant")

    # -- the blocker: a section filled after it loads ---------------------------------------------------------

    def test_FR_CMP2_AC_1_a_compact_section_filled_after_it_loads_keeps_expand_after_a_reload(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.overview()

        self.step("set up made compact, dark 1440")
        key = self.set_size(SETUP, "compact")
        self.assertNotEqual(key, b.eval("(document.querySelector('.prg-slot') || {dataset: {}}).dataset.czKey"),
                            "Set up this project and the empty progress slot share no key")
        self.assertFalse(b.eval("!!document.querySelector('.prg-slot.cz-compact')"), "the progress slot keeps its size")

        self.step("after a reload, dark 1440")
        self.overview(reload=True)
        b.wait(f"!!{q(SETUP_BTN)}", "Expand on Set up this project after a reload")
        self.assertEqual(b.eval(f"{q(SETUP_BTN)}.getAttribute('aria-label')"), "Expand Set up this project")
        self.assertEqual(b.eval(f"[...{q(SETUP)}.querySelectorAll('[data-control=\"expand_box\"]')].length"), 1)
        self.assertFalse(b.eval("[...document.querySelectorAll('.prg-slot [data-control=\"expand_box\"], .prg-slot.xp-box')]"
                                ".some((e) => e.getClientRects().length)"), "no stray Expand on the empty progress slot")
        # Expand comes before the section's own controls, and is a bar at the cut, over none of them
        self.assertTrue(b.eval(f"""(() => {{ const btn = {q(SETUP_BTN)}, sec = {q(SETUP)};
            const first = [...sec.querySelectorAll('button, a[href], summary, input, select, textarea')].find((e) => e !== btn);
            return !!first && !!(btn.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING); }})()"""),
                        "Expand is first in the tab order")
        bar = b.eval(f"""(() => {{ const r = {q(SETUP_BTN)}.getBoundingClientRect(), s = {q(SETUP)}.getBoundingClientRect();
            return {{width: r.width, sw: s.width, bottom: r.bottom, sb: s.bottom}}; }})()""")
        self.assertAlmostEqual(bar["width"], bar["sw"], delta=2, msg="Expand is the cut line, the section's whole width")
        self.assertAlmostEqual(bar["bottom"], bar["sb"], delta=2)
        self.shot("setup-compact-1440")

        self.step("its head opens it, dark 1440")
        b.click(".setup-box .card-t", what="the title of Set up this project")
        b.wait(f"{q(SETUP)}.classList.contains('xp-open')", "Set up this project in full")
        self.assertEqual(b.eval(f"{q(SETUP_BTN)}.getAttribute('aria-expanded')"), "true")
        self.assertEqual(self.label(SETUP_BTN), "Collapse")
        self.shot("setup-open-1440")
        b.click(".setup-box .card-t", what="the title again")
        b.wait(f"!{q(SETUP)}.classList.contains('xp-open')", "folded back")
        self.assertEqual(self.label(SETUP_BTN), "Expand")

        self.step("a clipped control that takes the focus opens it, dark 1440")
        b.eval(f"""(() => {{ const sec = {q(SETUP)}, btn = {q(SETUP_BTN)}, top = btn.getBoundingClientRect().top;
            const cut = [...sec.querySelectorAll('button, a[href], summary')].find((e) => e !== btn && e.getBoundingClientRect().bottom > top);
            cut.focus(); return true; }})()""")
        b.wait(f"{q(SETUP)}.classList.contains('xp-open') && {q(SETUP_BTN)}.getAttribute('aria-expanded') === 'true'",
               "the section opened for the focused control")
        b.click(SETUP_BTN, text="Collapse", what="Collapse")
        b.wait(f"!{q(SETUP)}.classList.contains('xp-open')", "folded back")

        self.step("ask rihma to expand it, dark 1440")
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "expand set up this project")
        b.click("#as-send", what="Send")
        b.wait(f"{q(SETUP)}.classList.contains('xp-open')", "the section Rihma opened")
        self.assertIn("Set up this project", b.eval("document.querySelector('#as-log .msg.bot:last-of-type').textContent"))
        self.close_assistant()
        b.click(SETUP_BTN, text="Collapse", what="Collapse")

        self.step("light 390 after a reload")
        self.theme("light", "Light")
        self.narrow()
        self.overview(reload=True)
        b.wait(f"!!{q(SETUP_BTN)} && {q(SETUP_BTN)}.getClientRects().length > 0", "Expand at 390")
        b.click(SETUP_BTN, what="Expand at 390")
        b.wait(f"{q(SETUP)}.classList.contains('xp-open')", "the section in full at 390")
        self.assertEqual(self.label(SETUP_BTN), "Collapse")
        self.assertTrue(b.eval(f"{q(SETUP_BTN)}.getClientRects().length > 0"), "Collapse is shown")
        self.shot("setup-open-390")
        b.click(SETUP_BTN, text="Collapse", what="Collapse at 390")
        b.wait(f"!{q(SETUP)}.classList.contains('xp-open')", "folded back at 390")
        self.set_size(SETUP, "normal")
        self.step("done")

    # -- the head after the layout is applied again --------------------------------------------------------------

    def test_FR_CMP2_AC_2_the_head_and_expand_agree_after_customize_and_stop_when_normal(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("light", "Light")
        self.overview()

        self.step("compact, then customize again, light 1440")
        self.set_size(SETUP, "compact")
        b.click("#customize", what="Customize")
        b.wait("!!document.querySelector('.vcz-sec')", "the sections to customize")
        b.click('[data-key="vcz:done"]', what="Done")
        time.sleep(0.8)
        b.wait(f"!!{q(SETUP_BTN)}", "Expand on the section")
        self.assertEqual(b.eval(f"[...{q(SETUP)}.querySelectorAll('[data-control=\"expand_box\"]')].length"), 1, "one Expand")

        self.step("the head toggles and the button says so, light 1440")
        b.click(".setup-box .card-t", what="the title")
        b.wait(f"{q(SETUP)}.classList.contains('xp-open')", "open")
        self.assertEqual(b.eval(f"{q(SETUP_BTN)}.getAttribute('aria-expanded')"), "true")
        self.assertEqual(self.label(SETUP_BTN), "Collapse")
        b.click(".setup-box .card-t", what="the title again")
        b.wait(f"!{q(SETUP)}.classList.contains('xp-open')", "closed")
        self.assertEqual(b.eval(f"{q(SETUP_BTN)}.getAttribute('aria-expanded')"), "false")
        self.assertEqual(self.label(SETUP_BTN), "Expand")

        self.step("back to normal, the head is plain again, light 1440")
        self.set_size(SETUP, "normal")
        self.assertFalse(b.eval(f"!!{q(SETUP_BTN)}"))
        b.click(".setup-box .card-t", what="the title of a normal section")
        time.sleep(0.3)
        self.assertFalse(b.eval(f"{q(SETUP)}.classList.contains('xp-open')"), "a normal section's head opens nothing")
        self.assertFalse(b.eval("!!document.querySelector('.setup-box .xp-head')"), "nor shows a hand over it")

        self.step("dark 390 the same")
        self.theme("dark", "Dark")
        self.narrow()
        self.overview()
        self.set_size(SETUP, "compact")
        b.click("#customize", what="Customize")
        b.click('[data-key="vcz:done"]', what="Done")
        time.sleep(0.8)
        b.click(".setup-box .card-t", what="the title at 390")
        b.wait(f"{q(SETUP)}.classList.contains('xp-open')", "open at 390")
        self.assertEqual(self.label(SETUP_BTN), "Collapse")
        b.click(SETUP_BTN, text="Collapse", what="Collapse at 390")
        self.set_size(SETUP, "normal")
        self.step("done")

    # -- the side panel follows what is done in it ---------------------------------------------------------------

    def test_FR_CMP2_AC_3_the_side_panel_follows_a_decision_taken_in_it_and_shows_its_toasts(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        b.wait("!!document.querySelector('#grid [data-type=\"decisions\"]')", "the decisions widget")
        wid = b.eval("document.querySelector('#grid [data-type=\"decisions\"]').dataset.wid")
        xp = f'#grid [data-wid="{wid}"] [data-control="expand_box"]'

        self.step("the decisions widget made small, dark 1440")
        b.click(f'#grid [data-wid="{wid}"] [data-fk="menu"]', what="the widget menu")
        b.click("#menu-pop .menu-item", text="Small (S)", what="Small")
        b.wait(f"!!{q(xp)}", "Expand on the small decisions widget")
        total = b.eval(f"Number(({q(f'#grid [data-wid={json.dumps(wid)}] .w-sum .muted')}.textContent.match(/(\\d+) waiting/) || [])[1])")
        b.click(xp, what="Expand")
        b.wait(SHEET_OPEN + " && document.querySelectorAll('#xp-sheet .dec-row').length > 0", "the side panel")
        self.assertEqual(b.eval("document.querySelectorAll('#xp-sheet .dec-row').length"), total, "every waiting decision")

        self.step("defer one in the side panel, dark 1440")
        target = b.eval("(document.querySelector('#xp-sheet [data-control=\"decide\"][data-key$=\":defer\"]') || {dataset: {}}).dataset.key")
        self.assertTrue(target, "a decision that can be deferred")
        card = target.split(":")[0]
        b.click(f'#xp-sheet [data-key="{target}"]', what="Defer in the side panel")
        b.wait(f"{SHEET_OPEN} && document.querySelectorAll('#xp-sheet .dec-row').length === {total - 1}"
               f" && ![...document.querySelectorAll('#xp-sheet [data-control=\"decide\"]')].some((e) => e.dataset.key.startsWith({json.dumps(card + ':')}))",
               "the side panel without the decided card")
        b.wait(f"!!{q(xp)} && {q(xp)}.getAttribute('aria-expanded') === 'true'", "the grid's Expand says the panel is open")
        self.assertTrue(b.eval("document.querySelector('#xp-sheet').contains(document.activeElement)"), "the focus stays in the panel")
        b.wait("!!document.querySelector('#status .toast')", "the toast")
        self.assertTrue(b.eval("""(() => { const t = document.querySelector('#status .toast button'), r = t.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!hit && t.contains(hit); })()"""),
                        "the toast shows above the side panel")
        self.shot("panel-after-defer-1440")
        b.key("Escape", 27)
        b.wait(f"!({SHEET_OPEN}) && document.activeElement === {q(xp)} && {q(xp)}.getAttribute('aria-expanded') === 'false'",
               "the panel closed, the focus on the grid's Expand")

        self.step("a medium widget that cuts nothing has no expand, dark 1440")
        widths = b.eval("""[...document.querySelectorAll('#grid .widget.size-M, #grid .widget.size-S')].map((w) => ({
            wid: w.dataset.wid, has: !!w.querySelector('[data-control="expand_box"]')}))""")
        for w in widths:
            if not w["has"]:
                continue
            b.click(f'#grid [data-wid="{w["wid"]}"] [data-control="expand_box"]', what="Expand on " + w["wid"])
            b.wait(SHEET_OPEN, "the side panel")
            more = b.eval(f"""(() => {{ const t = (e) => e.textContent.replace(/\\s+/g, ' ').trim();
                return t(document.querySelector('#xp-sheet .xp-sheet-body')).length > t({q(f'#grid [data-wid="{w["wid"]}"] .card-body')}).length; }})()""")
            self.assertTrue(more, f"the side panel of {w['wid']} shows more than its card")
            b.key("Escape", 27)
            b.wait(f"!({SHEET_OPEN})", "closed")
        self.assertTrue(any(not w["has"] for w in widths), "a widget that cuts nothing carries no Expand")

        self.step("light 390 a toast from the sheet")
        self.theme("light", "Light")
        self.narrow()
        b.eval("location.hash = '#/home'; true")
        b.wait(f"!!{q(xp)}", "Expand at 390")
        b.click(xp, what="Expand at 390")
        b.wait(SHEET_OPEN + " && document.querySelectorAll('#xp-sheet .dec-row').length > 0", "the sheet")
        park = b.eval("(document.querySelector('#xp-sheet [data-control=\"decide\"][data-key$=\":park\"], "
                      "#xp-sheet [data-control=\"decide\"][data-key$=\":defer\"]') || {dataset: {}}).dataset.key")
        self.assertTrue(park)
        b.click(f'#xp-sheet [data-key="{park}"]', what="a decision in the sheet")
        b.wait("!!document.querySelector('#status .toast')", "the toast at 390")
        self.assertTrue(b.eval("""(() => { const t = document.querySelector('#status .toast button'), r = t.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!hit && t.contains(hit); })()"""),
                        "the toast shows above the sheet at 390")
        self.shot("sheet-toast-390")
        b.key("Escape", 27)
        b.wait(f"!({SHEET_OPEN})", "the sheet closed")
        b.wait("document.querySelector('#status').parentElement !== document.querySelector('#xp-sheet')",
               "the toasts go back to the page")      # the dialog's close event comes a moment after it closes
        self.step("done")

    # -- the Agents strip, compact, and the live view ----------------------------------------------------------

    def test_FR_CMP2_AC_4_one_expand_on_the_agents_strip_and_the_live_last_action_keeps_open(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("light", "Light")
        b.eval(FAKE_AGENTS)
        b.eval(FAKE_LIVE + f"({json.dumps(self.webhook)})")
        self.overview()
        strip = ".agents-strip"
        btns = f"[...{q(strip)}.querySelectorAll('[data-control=\"expand_box\"]')]"

        self.step("the strip with eight posts, normal, after customize, light 1440")
        b.wait(f"{btns}.length === 1", "the strip's own Expand")
        b.click("#customize", what="Customize")
        b.click('[data-key="vcz:done"]', what="Done")
        time.sleep(0.8)
        b.wait(f"{btns}.length === 1", "the strip keeps its own Expand after Customize")

        self.step("the strip made compact, light 1440")
        self.set_size(strip, "compact")
        b.wait(f"{btns}.length === 1", "one Expand on the compact strip")
        time.sleep(0.5)
        self.assertEqual(b.eval(f"{btns}.length"), 1, "one Expand on the compact strip")
        b.click(f'{strip} [data-control="expand_box"]', what="Expand on the strip")
        b.wait(f"{q(strip)}.classList.contains('xp-open')"
               f" && [...{q(strip)}.querySelectorAll('.as-list li')].filter((e) => e.getClientRects().length).length === 8",
               "every post")
        self.assertEqual(b.eval(f"{btns}.map((x) => x.getAttribute('aria-expanded'))"), ["true"])
        self.shot("strip-open-1440")
        b.click(f'{strip} [data-control="expand_box"]', text="Collapse", what="Collapse")
        b.wait(f"!{q(strip)}.classList.contains('xp-open')", "folded back")
        self.set_size(strip, "normal")
        b.wait(f"{btns}.length === 1", "the strip's own Expand once it is normal again")

        self.step("the live view's last action, light 1440")
        lb = '.live .live-lastbox > [data-control="expand_box"]'
        b.wait(f"!!{q(lb)}", "Expand on the last action")
        b.click(lb, what="Expand on the last action")
        b.wait("[...document.querySelectorAll('.live .live-recent li')].filter((e) => e.getClientRects().length).length === 3",
               "the steps before it")
        self.assertEqual(b.eval("document.activeElement.dataset.control"), "expand_box")
        b.eval("window.__fakeLive.n = 6; true")                   # the cell takes two more steps: the live view redraws
        b.wait("[...document.querySelectorAll('.live .live-recent li')].filter((e) => e.getClientRects().length).length === 5",
               "the redrawn box still open", timeout=20)
        self.assertEqual(b.eval(f"{q(lb)}.getAttribute('aria-expanded')"), "true")
        self.assertEqual(b.eval("document.activeElement.dataset.control"), "expand_box", "the focus kept on it")
        self.shot("live-open-1440")
        b.click(lb, text="Collapse", what="Collapse on the last action")

        self.step("dark 390 the strip")
        self.theme("dark", "Dark")
        self.narrow()
        self.overview()
        b.wait(f"{btns}.length === 1", "the strip's Expand at 390")
        b.click(f'{strip} [data-control="expand_box"]', what="Expand at 390")
        b.wait(f"[...{q(strip)}.querySelectorAll('.as-list li')].filter((e) => e.getClientRects().length).length === 8", "every post at 390")
        self.shot("strip-open-390")
        b.click(f'{strip} [data-control="expand_box"]', text="Collapse", what="Collapse at 390")
        self.step("done")


if __name__ == "__main__":
    unittest.main()
