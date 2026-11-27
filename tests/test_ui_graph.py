"""The Knowledge graph in a real browser (FR-GRV1-AC-8): headless Chrome over the DevTools protocol.

Over a project whose graph holds every kind the ontology defines (tests/graph_view_fixture.py), a person opens a
project's Knowledge graph and the page across projects, asks Rihma how requirements trace to tests and follows Take
me there, filters by kind, opens a node's details and focuses on it, moves between nodes with the keyboard,
switches to the table, saves a view and makes it the default, pins a slice to Home, and resets. It is checked dark
and light at 1440 and 390 pixels: the graph or the table renders, the table is the default on a phone with the
filters in a sheet, nothing scrolls sideways, every control has a name, the marks' colours pass the dataviz
validator (tests/insights_palette.py) for every pair against the surface they are drawn on, and no console error,
failed request or Content-Security-Policy violation happens at any step.

It reuses the browser driver of tests/test_ui_drive.py, and is skipped when Chrome or git is missing.
``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
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
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import model  # noqa: E402
from graph_view_fixture import IDEA, every_kind  # noqa: E402
from insights_palette import hex_of, validate  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

PERSON = "Aino Virtanen"
FITS = "document.documentElement.scrollWidth <= window.innerWidth"
NAMED = ("(() => { const bad = []; document.querySelectorAll('#main button, #main select, #main input, #main a[href]')"
         ".forEach((el) => { if (!el.getClientRects().length) return;"
         " const name = el.getAttribute('aria-label') || el.textContent.trim() || el.title"
         " || (el.labels && el.labels[0] && el.labels[0].textContent.trim()) || el.placeholder;"
         " if (!name) bad.push(el.outerHTML.slice(0, 90)); }); return bad; })()")
NODES = "[...document.querySelectorAll('#graph .gv-n')].map((g) => g.dataset.kind)"
# the family colours as the page resolves them on the marks, and the surface they are drawn on
COLOURS = ("(() => { const c = document.querySelector('#graph .gv-canvas'); const probe = document.createElement('span');"
           " document.body.append(probe); const slots = [1, 2, 3].map((n) => { probe.style.color = 'var(--series-' + n + ')';"
           " return getComputedStyle(probe).color; }); probe.remove();"
           " return {surface: c ? getComputedStyle(c).backgroundColor : null, slots,"
           " marks: [...document.querySelectorAll('#graph .gv-mark')].map((m) => getComputedStyle(m).fill)}; })()")


class GraphUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the project's main")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-graph-ui-")).resolve()
        cls.factory = Factory(cls.tmp / "home", clock=FixedClock())
        case = SimpleNamespace(tmp=cls.tmp, new=lambda mode="mixed", title="Equipment loans": cls.factory.new_project(
            title, mode=mode, maturity="demo"))
        cls.p = every_kind(case)
        cls.other = case.new(title="Room bookings")
        intake(cls.other, IDEA, model=model(), requested_by="Aino")
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-graph")
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
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"graph-{b.step.replace(' ', '-')}.png")

    def shot(self, name: str) -> None:
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.browser.screenshot(self.shots / f"graph-{name}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 900 if px > 500 else 800,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})

    def theme(self, mode: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=mode.capitalize(), what=f"{mode} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === '{mode}'", f"the {mode} theme")

    def drawn(self) -> int:
        return int(self.browser.eval("Number((document.querySelector('#graph') || {dataset: {}}).dataset.drawn || 0)"))

    def open(self, route: str, scope: str = "project") -> None:
        """A route opened fresh: Home first, so the graph is mounted again as a person arriving would see it."""
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/home"})
        b.wait("!document.querySelector('#graph') && !!document.querySelector('#grid')", "Home")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/{route}"})
        b.wait(f"!!document.querySelector('#graph[data-scope={scope}][data-drawn]')", f"the graph at {route}")

    def after(self, before: int, what: str) -> None:
        self.browser.wait(f"Number(document.querySelector('#graph').dataset.drawn) > {before}"
                          " && !document.querySelector('#graph.gv-busy')", what)

    def readable(self, where: str, mode: str) -> None:
        b = self.browser
        self.assertTrue(b.eval(FITS), f"scrolls sideways ({where}, {mode})")
        self.assertEqual(b.eval(NAMED), [], f"a control without a name ({where}, {mode})")
        got = b.eval(COLOURS)
        if not got["marks"]:
            return                                                # the table: no marks to check
        slots = [hex_of(s) for s in got["slots"]]                 # the three families: asked, decided, built
        surface = hex_of(got["surface"])
        for pair in ([slots[0], slots[1]], [slots[1], slots[2]], [slots[0], slots[2]]):   # every pair: a graph is a scatter
            report = validate(pair, mode, surface)
            self.assertTrue(report["ok"], f"{where} ({mode}): {report['fails']}")
        self.assertTrue({hex_of(m) for m in got["marks"]} <= set(slots), f"a mark outside the palette ({where}, {mode})")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in cockpit")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done")

    def test_FR_GRV1_AC_8_a_person_filters_focuses_saves_and_pins_the_graph_in_both_themes_at_both_widths(self):
        b, pid = self.browser, self.p.pid
        self.step("sign in")
        self.sign_in()
        self.theme("dark")

        self.step("ask rihma and take me there")
        b.click('#sb-nav a[href="#/projects"]', what="Projects in the sidebar")
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "Show me how requirements trace to tests in Equipment loans")
        b.click("#as-send", what="Send")
        by = b.wait("(document.querySelector('#as-log .msg.bot p.by[data-by=\"graph\"]') || {}).textContent",
                    "the answer's provenance")
        self.assertEqual(by, "From the knowledge graph, by rules")     # no model here: never "From the model"
        b.click("#as-log .msg.bot button", text="Take me there", what="Take me there")
        b.wait(f"location.hash === '#/p/{pid}/graph?kinds=criterion,requirement,test'"
               " && !!document.querySelector('#graph[data-scope=project][data-drawn]')", "the graph with those filters")
        self.assertEqual(set(b.eval(NODES)), {"requirement", "criterion", "test"})
        self.readable("trace 1440", "dark")
        b.click("#as-close", what="Close the assistant")
        b.wait("document.querySelector('#assistant').hidden", "the assistant closed")

        self.step("filter by kind")
        self.open(f"#/p/{pid}/graph")
        total = len(b.eval(NODES))
        self.assertIn("question", b.eval(NODES))
        before = self.drawn()
        b.click('#graph .gv-panel input[data-key="gvk:question"]', what="the Question kind")
        self.after(before, "the graph without questions")
        self.assertNotIn("question", b.eval(NODES))
        self.assertLess(len(b.eval(NODES)), total)
        self.assertIn("kinds=", b.eval("location.hash"))
        self.readable("filtered 1440", "dark")

        self.step("details and focus")
        b.click(f'#graph .gv-n[data-id="R-1@v2"] .gv-mark', what="R-1 in the graph")
        b.wait("(document.querySelector('#gv-d-h') || {}).textContent === 'R-1 v2'", "R-1's details")
        self.assertIn("has criterion", b.eval("document.querySelector('.gv-details').textContent"))
        before = self.drawn()
        b.click('.gv-details button[data-control="graph_focus"]', what="Focus here")
        self.after(before, "the focused graph")
        self.assertIn("focus=R-1", b.eval("location.hash"))
        self.assertIn("Focus: R-1 v2", b.eval("document.querySelector('#graph .gv-sum').textContent"))
        self.assertLess(len(b.eval(NODES)), total)

        self.step("keyboard")
        b.eval("document.querySelector('#graph .gv-n[tabindex=\"0\"]').focus()")
        first = b.eval("document.activeElement.dataset.id")
        b.key("ArrowDown", 40)
        b.key("ArrowRight", 39)
        moved = b.eval("document.activeElement.dataset.id")
        self.assertTrue(moved and moved != first, (first, moved))
        b.key("Enter", 13)
        b.wait(f"!!document.querySelector('#gv-d-h') && document.querySelector('.gv-n.on').dataset.id === {json.dumps(moved)}",
               "the details of the node the keyboard reached")

        self.step("table mode")
        b.click('#graph [data-control="graph_mode"] .seg-b', text="Table", what="Table")
        b.wait("!!document.querySelector('#graph .gv-tbl table')", "the table")
        rows = b.eval("document.querySelectorAll('#graph .gv-tbl')[0].querySelectorAll('tbody tr').length")
        shown = b.eval("document.querySelector('#graph .gv-sum p').textContent")
        self.assertIn(f"· {rows} shown ·", shown)                     # the table holds the same slice
        self.assertGreater(rows, 0)
        self.readable("table 1440", "dark")

        self.step("save a view and open it by default")
        self.open(f"#/p/{pid}/graph?kinds=requirement,criterion,test&states=open")
        b.click('#graph [data-control="graph_presets"]', what="Saved views")
        b.click("#menu-pop .menu-item", text="Save this view", what="Save this view")
        b.type('#modal input[type="text"]', "Open requirements and their tests")
        b.click("#modal button.primary", what="Save view")
        b.wait("(document.querySelector('#status .toast') || {}).textContent.includes('Saved')", "the saved toast")
        b.click('#graph [data-control="graph_presets"]', what="Saved views")
        b.click("#menu-pop .menu-item", text="by default", what="Open it by default")
        b.wait("(document.querySelector('#status .toast') || {}).textContent.includes('opens first')", "the default toast")
        self.open(f"#/p/{pid}/graph")
        b.wait("location.hash.includes('kinds=requirement,criterion,test&states=open')", "the default view in the route")
        self.assertEqual(set(b.eval(NODES)), {"requirement", "criterion", "test"})

        self.step("pin to home")
        b.click('#graph [data-control="graph_pin"]', what="Pin to Home")
        b.wait("(document.querySelector('#status .toast') || {}).textContent.includes('pinned')", "the pinned toast")
        b.click('a.nav-i[href="#/home"]', what="Home in the sidebar")
        pinned = b.wait("(() => { const w = document.querySelector('#grid .widget[data-type=\"graph\"] .gv-widget');"
                        " return w && w.textContent.includes('Open in the Knowledge graph') && w.textContent; })()",
                        "the pinned slice on Home")
        self.assertIn("Open requirements and their tests", pinned)

        self.step("reset to default")
        self.open(f"#/p/{pid}/graph")
        b.click('#graph [data-control="graph_presets"]', what="Saved views")
        b.click("#menu-pop .menu-item", text="Reset to default", what="Reset to default")
        b.wait("(document.querySelector('#status .toast') || {}).textContent.includes('default view')", "the reset toast")
        b.wait("!location.hash.includes('?')", "the route without filters")
        self.open(f"#/p/{pid}/graph")
        self.assertIn("question", b.eval(NODES))

        self.step("light 1440 and the page across projects")
        self.theme("light")
        self.open("#/graph?kinds=requirement,criterion,test", scope="factory")
        self.assertEqual(set(b.eval(NODES)), {"requirement", "criterion", "test"})
        self.assertIn("· Equipment lo", b.eval("document.querySelector('#graph .gv-svg').textContent"))   # its project
        self.readable("factory 1440", "light")
        self.open(f"#/p/{pid}/graph")
        self.readable("project 1440", "light")

        for mode in ("light", "dark"):
            self.step(f"{mode} 390")
            if mode == "dark":
                self.theme("dark")
            self.width(390)
            self.open(f"#/p/{pid}/graph")
            b.wait("!!document.querySelector('#graph .gv-tbl table')", "the table, the default on a phone")
            self.assertEqual(b.eval("document.querySelector('#graph .gv-panel').getClientRects().length"), 0)
            self.readable("390", mode)
            self.shot(f"{mode}-390-table")
            b.click('#graph [data-control="graph_filters"].gv-sheet-btn', what="Filters")
            b.wait("!!document.querySelector('#modal .gv-sheet input[data-key=\"gvk:requirement\"]')", "the filters sheet")
            self.assertTrue(b.eval(FITS))
            b.key("Escape", 27)
            b.wait("!document.querySelector('#modal').open", "the sheet closed")
            b.click('#graph [data-control="graph_mode"] .seg-b', text="Graph", what="Graph")
            b.wait("!!document.querySelector('#graph .gv-svg .gv-n')", "the graph on a phone")
            self.readable("390 graph", mode)
            self.shot(f"{mode}-390-graph")
            self.width(1440)
        self.check()


if __name__ == "__main__":
    unittest.main()
