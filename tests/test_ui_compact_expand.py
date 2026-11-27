"""Compact boxes open for review (FR-CMP1-AC-5) in a real browser: headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py drives it, on the demo home (``kernel.demo``, invented projects).

The owner (2026-11-26): "When I change size of something to compact I guess I should be able to roll those compacted
boxes for review?" A person makes a Home widget Small with its widget menu and opens it in full by Expand, by its
head, by the menu and by the keyboard, then by asking Rihma; makes a project section compact with Customize and
expands it in place; widens the agent channel beside the view; and unfolds the live view's last-action box. Dark at
1440 px, light at 390 px (where the side panel is a sheet from the bottom). After every step: no console error,
failed request or CSP violation, every control named, nothing wider than the screen.

The cockpit listens on ``RIHMA_CMP_PORT`` (9510) and Chrome's DevTools on ``RIHMA_CMP_DEVTOOLS`` (10010). Skipped when
Chrome or git is missing. ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
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

PORT = int(os.environ.get("RIHMA_CMP_PORT") or 9510)
DEVTOOLS = int(os.environ.get("RIHMA_CMP_DEVTOOLS") or 10010)
NAMELESS = shaped.NAMELESS.replace("#modal :is(button, input, textarea, select)",
                                   "#modal :is(button, input, textarea, select), #xp-sheet :is(button, a[href])")
SHEET_OPEN = "!!document.querySelector('#xp-sheet') && document.querySelector('#xp-sheet').open"
WEBHOOK = "Shipment webhook to the stock system"


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


class CompactExpandUiTest(unittest.TestCase):
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

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-cmp-")).resolve()
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
            self.browser = FixedPortBrowser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

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
        self.assertLessEqual(b.eval(shaped.OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"cmp-{b.step.replace(' ', '-')}.png")

    # -- helpers --------------------------------------------------------------------------------------------

    def snap(self, what: str) -> None:
        """A screenshot while a box is open (RIHMA_UI_SHOTS), beside the one each step ends with."""
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.browser.screenshot(self.shots / f"cmp-open-{what}.png")

    def home(self) -> None:
        b = self.browser
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('#grid .widget') && location.hash === '#/home'", "Home's widgets")
        time.sleep(0.3)

    def xp(self, wid: str) -> str:
        return f'#grid [data-wid="{wid}"] [data-control="expand_box"]'

    def sheet_closes(self, how: str, wid: str) -> None:
        b = self.browser
        if how == "escape":
            b.key("Escape", 27)
        else:
            b.click('#xp-sheet [data-key="xp-close"]', what="Collapse in the side panel")
        b.wait(f"!({SHEET_OPEN}) && {q(self.xp(wid))}.getAttribute('aria-expanded') === 'false'"
               f" && document.activeElement.dataset.key === {json.dumps(f'xp:w:{wid}')}",
               "the side panel closed, Expand back to false and the focus back on it")

    def sheet_shows(self, name: str) -> dict:
        b = self.browser
        b.wait(SHEET_OPEN + " && !!document.querySelector('#xp-sheet .xp-sheet-body .widget.size-XL')", "the side panel")
        self.assertEqual(b.eval(f"{q('#xp-h')}.textContent"), name)
        self.assertEqual(b.eval("document.activeElement.dataset.key"), "xp-close", "the focus is in the side panel")
        return b.eval("(() => { const r = document.querySelector('#xp-sheet').getBoundingClientRect();"
                      " return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width,"
                      " w: innerWidth, h: innerHeight}; })()")

    def ask(self, text: str, opener: str) -> str:
        b = self.browser
        b.click(opener, what="Ask Rihma")
        b.type("#as-q", text)
        b.click("#as-send", what="Send")
        b.wait(SHEET_OPEN, "the box Rihma opened")
        self.snap(f"ask-{b.eval('innerWidth')}")
        return b.eval("document.querySelector('#as-log .msg.bot:last-of-type').textContent")

    # -- the drive ------------------------------------------------------------------------------------------

    def test_FR_CMP1_AC_5_compact_boxes_open_for_review_in_chrome_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.home()

        self.step("a widget made small with its menu, dark 1440")
        wid = b.eval("(document.querySelector('#grid .widget.size-M') || document.querySelector('#grid .widget.size-L')).dataset.wid")
        name = b.eval(f"{q(f'#grid [data-wid={json.dumps(wid)}] .card-t')}.textContent")
        b.click(f'#grid [data-wid="{wid}"] [data-fk="menu"]', what="the widget menu")
        b.click("#menu-pop .menu-item", text="Small (S)", what="Small in the widget menu")
        b.wait(f"!!{q(f'#grid [data-wid={json.dumps(wid)}].size-S')} && !!{q(self.xp(wid))}", "the small widget with Expand")
        self.assertEqual(b.eval(f"{q(self.xp(wid))}.getAttribute('aria-expanded')"), "false")
        self.assertEqual(b.eval(f"{q(self.xp(wid))}.getAttribute('aria-controls')"), "xp-sheet")

        self.step("expand the small widget, dark 1440")
        b.click(self.xp(wid), what="Expand on the small widget")
        r = self.sheet_shows(name)
        self.snap("widget-panel")
        self.assertEqual(b.eval(f"{q(self.xp(wid))}.getAttribute('aria-expanded')"), "true")
        self.assertLess(r["width"], r["w"])                                   # a side panel, from the right
        self.assertGreaterEqual(r["right"], r["w"] - 1)
        self.sheet_closes("escape", wid)
        self.assertTrue(b.eval(f"!!{q(f'#grid [data-wid={json.dumps(wid)}].size-S')}"), "the size stays as set")

        self.step("its head, the menu and the keyboard, dark 1440")
        b.click(f'#grid [data-wid="{wid}"] .card-t', what="the widget's head")
        self.sheet_shows(name)
        self.sheet_closes("collapse", wid)
        b.click(f'#grid [data-wid="{wid}"] [data-fk="menu"]', what="the widget menu")
        b.click("#menu-pop .menu-item", text="Expand", what="Expand in the widget menu")
        self.sheet_shows(name)
        self.sheet_closes("escape", wid)
        for key, code, text in (("Enter", 13, "\r"), (" ", 32, " ")):        # Enter, then Space, on Expand
            b.eval(f"{q(self.xp(wid))}.focus(); true")
            for kind in ("keyDown", "keyUp"):
                b.cmd("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": "Enter" if code == 13 else "Space",
                                                 "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code,
                                                 **({"text": text} if kind == "keyDown" else {})})
            self.sheet_shows(name)
            self.sheet_closes("escape", wid)
        self.assertTrue(b.eval(f"!!{q(f'#grid [data-wid={json.dumps(wid)}].size-S')}"))

        self.step("ask rihma to expand it, dark 1440")
        said = self.ask(f"Expand the {name}", "#assistant-fab")
        self.assertIn(name, said)
        self.assertEqual(b.eval(f"{q('#xp-h')}.textContent"), name)
        b.key("Escape", 27)
        b.wait(f"!({SHEET_OPEN})", "the side panel closed")
        if b.eval("!!document.querySelector('#as-close') && document.querySelector('#as-close').getClientRects().length > 0"):
            b.click("#as-close", what="Close the assistant")

        self.step("a compact section in a project, dark 1440")
        webhook = next(p for p in self.factory.projects() if p.meta.get("title") == WEBHOOK)
        b.eval(f"location.hash = {json.dumps(f'#/p/{webhook.pid}/overview')}; true")
        b.wait("!!document.querySelector('.view-body') && document.querySelector('#main').dataset.loaded === '1'", "the overview")
        time.sleep(0.8)
        b.click("#customize", what="Customize")
        b.wait("!!document.querySelector('.vcz-sec')", "the sections to customize")
        key = b.eval("[...document.querySelectorAll('.vcz-sec')].filter((e) => e.getClientRects().length)"
                     ".sort((a, c) => c.scrollHeight - a.scrollHeight)[0].dataset.czKey")
        b.click(f'[data-key="vcz:{key}:size"]', what="the section's size")
        b.wait(f"!!{q(f'[data-cz-key={json.dumps(key)}].cz-compact')}", "the compact section")
        b.click('[data-key="vcz:done"]', what="Done")
        sec = f'[data-cz-key="{key}"]'
        btn = f'{sec} > [data-control="expand_box"]'
        b.wait(f"!!{q(btn)} && !{q(btn)}.hidden", "Expand on the compact section")
        self.step("expand the compact section in place, dark 1440")
        b.click(btn, what="Expand on the compact section")
        b.wait(f"{q(sec)}.classList.contains('xp-open')", "the section in full")
        self.snap("section")
        self.assertEqual(b.eval(f"{q(btn)}.getAttribute('aria-expanded')"), "true")
        self.assertEqual(b.eval(f"{q(btn)}.getAttribute('aria-controls')"), b.eval(f"{q(sec)}.id"))
        self.assertEqual(b.eval("document.activeElement.dataset.control"), "expand_box", "the focus stays on it")
        self.assertGreaterEqual(b.eval(f"{q(sec)}.clientHeight + 2"), b.eval(f"{q(sec)}.scrollHeight"))
        b.click(btn, text="Collapse", what="Collapse on the section")
        b.wait(f"!{q(sec)}.classList.contains('xp-open') && {q(sec)}.classList.contains('cz-compact')", "the section folded back")
        b.wait(f"{q(sec)}.scrollTop === 0", "the folded section showing its top again")

        self.step("the agent channel beside the view, dark 1440")
        b.click('[data-key="channel-panel"]', what="Agent channel")
        b.wait("!!document.querySelector('#agent-aside [data-control=\"expand_box\"]')", "the channel panel")
        narrow_w = b.eval("document.querySelector('#agent-aside').getBoundingClientRect().width")
        b.click('#agent-aside [data-control="expand_box"]', what="Expand on the channel panel")
        b.wait("document.querySelector('#agent-aside').classList.contains('xp-open')"
               f" && document.querySelector('#agent-aside').getBoundingClientRect().width > {narrow_w + 100}", "the wide channel")
        self.snap("channel-wide")
        b.click('#agent-aside [data-control="expand_box"]', text="Collapse", what="Collapse on the channel panel")
        b.wait("!document.querySelector('#agent-aside').classList.contains('xp-open')", "the channel folded back")
        b.click('[data-key="agent-aside-close"]', what="Close the channel panel")

        self.step("the last-action box, dark 1440")
        b.eval("""(async () => {
            const m = await import('/static/expand.js');
            const c = await import('/static/core.js');
            const last = c.h('div', {class: 'live-last'}, c.h('span', {class: 'label'}, 'Last action'), c.h('span', {class: 'mono'}, 'bash'));
            const box = m.lastActionBox(last, [{tool: 'bash', target: 'run the tests'}, {tool: 'write', target: 'app/routes.py'},
                                               {tool: 'read', target: 'README.md'}], 'live-last:drive');
            box.dataset.drive = '1';
            document.querySelector('.view-body').prepend(box);
            return true; })()""")
        lb = '[data-drive="1"] > [data-control="expand_box"]'
        self.assertFalse(b.eval("[...document.querySelectorAll('[data-drive=\"1\"] .live-recent li')].some((e) => e.getClientRects().length)"))
        b.click(lb, what="Expand on the last action")
        b.wait("[...document.querySelectorAll('[data-drive=\"1\"] .live-recent li')].filter((e) => e.getClientRects().length).length === 2",
               "the steps before it")
        self.snap("last-action")
        b.click(lb, text="Collapse", what="Collapse on the last action")
        b.wait("!document.querySelector('[data-drive=\"1\"]').classList.contains('xp-open')", "the box folded back")
        b.eval("document.querySelector('[data-drive=\"1\"]').remove(); true")

        self.step("light 390 the widget as a sheet")
        self.theme("light", "Light")
        self.narrow()
        self.home()
        b.wait(f"!!{q(self.xp(wid))}", "Expand on the small widget at 390")
        b.click(self.xp(wid), what="Expand on the small widget")
        r = self.sheet_shows(name)
        self.snap("widget-sheet-390")
        self.assertAlmostEqual(r["width"], r["w"], delta=1)                 # a sheet: the whole width
        self.assertAlmostEqual(r["bottom"], r["h"], delta=1)                # from the bottom
        self.sheet_closes("collapse", wid)

        self.step("light 390 ask rihma")
        said = self.ask(f"Expand the {name}", "#bb-ask")
        self.assertIn(name, said)
        b.click('#xp-sheet [data-key="xp-close"]', what="Collapse in the sheet")
        b.wait(f"!({SHEET_OPEN})", "the sheet closed")
        if b.eval("!!document.querySelector('#as-close') && document.querySelector('#as-close').getClientRects().length > 0"):
            b.click("#as-close", what="Close the assistant")

        self.step("light 390 the compact section and the channel")
        b.eval(f"location.hash = {json.dumps(f'#/p/{webhook.pid}/overview')}; true")
        b.wait(f"!!{q(btn)}", "the compact section at 390")
        time.sleep(0.5)
        if not b.eval(f"{q(btn)}.hidden"):
            b.click(btn, what="Expand on the compact section")
            b.wait(f"{q(sec)}.classList.contains('xp-open')", "the section in full at 390")
            b.click(btn, text="Collapse", what="Collapse on the section")
        if b.eval("!!document.querySelector('[data-key=\"channel-panel\"]') && document.querySelector('[data-key=\"channel-panel\"]').getClientRects().length > 0"):
            b.click('[data-key="channel-panel"]', what="Agent channel")
            b.click('#agent-aside [data-control="expand_box"]', what="Expand on the channel panel")
            b.wait("document.querySelector('#agent-aside').classList.contains('xp-open')"
                   " && Math.abs(document.querySelector('#agent-aside').getBoundingClientRect().width - innerWidth) < 2", "the channel on the whole screen")
            self.snap("channel-390")
            b.click('#agent-aside [data-control="expand_box"]', text="Collapse", what="Collapse on the channel panel")
            b.click('[data-key="agent-aside-close"]', what="Close the channel panel")
        self.step("done")


if __name__ == "__main__":
    unittest.main()
