"""Insights in a real browser (FR-INS1-AC-6): headless Chrome over the DevTools protocol.

A person opens Insights from the sidebar over a fixture home (tests/insights_fixture.py) and switches every
dimension, the window and the scope, turns a chart into its table, opens a project's Insights tab, pins a tile
to Home and sees it there, and exports. Every dimension is checked dark and light at 1440 and 390 pixels:
tiles and charts render or say not measured, nothing scrolls sideways, every control has a name, the chart
colours pass the dataviz validator (tests/insights_palette.py) against the surface they are drawn on, and no
console error, failed request or Content-Security-Policy violation happens at any step.

It reuses the browser driver of tests/test_ui_drive.py, and is skipped when Chrome is not installed
(``RIHMA_CHROME`` names another browser binary). ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
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

from insights_fixture import build  # noqa: E402
from insights_palette import hex_of, validate  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

PERSON = "Aino Virtanen"
DIMENSIONS = ("Health", "Compliance", "Governance", "Security", "Context drift", "QA", "Usage")
FITS = "document.documentElement.scrollWidth <= window.innerWidth"
NAMED = ("(() => { const bad = []; document.querySelectorAll('#main button, #main select, #main input, #main a[href]')"
         ".forEach((el) => { if (!el.getClientRects().length) return;"
         " const name = el.getAttribute('aria-label') || el.textContent.trim() || el.title;"
         " if (!name) bad.push(el.outerHTML.slice(0, 90)); });"
         " document.querySelectorAll('#main [role=group]').forEach((g) => { if (!g.getAttribute('aria-label')) bad.push('group'); });"
         " return bad; })()")
DRAWN = ("(() => { const m = document.querySelector('#insights .ins-model'); if (!m) return null;"
         " const charts = [...m.querySelectorAll('.ins-chart')];"
         " return {dimension: m.dataset.dimension, tiles: m.querySelectorAll('.ins-tile').length, charts: charts.length,"
         " empty: charts.filter((c) => !c.querySelector('.viz, .nm-box, .viz-none, table')).map((c) => c.dataset.chart),"
         " lines: [...m.querySelectorAll('.ins-tile .ins-line, .ins-chart .ins-line')].filter((p) => !p.textContent.trim()).length};"
         " })()")
# The categorical slots as the page resolves them, the surface the charts are drawn on, and every mark's colour.
COLOURS = ("(() => { const probe = document.createElement('span'); document.body.append(probe);"
           " const slots = [1, 2, 3, 4, 5, 6].map((n) => { probe.style.color = 'var(--series-' + n + ')';"
           " return getComputedStyle(probe).color; }); probe.remove();"
           " const card = document.querySelector('#insights .ins-chart');"
           " const marks = [...document.querySelectorAll('#insights .cseg, #insights .bar, #insights .part:not(.hatch)')]"
           ".map((e) => getComputedStyle(e).backgroundColor);"
           " return {slots, surface: card ? getComputedStyle(card).backgroundColor : null, marks}; })()")


class InsightsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-insights-ui-")).resolve()
        cls.lanes_env = os.environ.get("GF_LANES")
        os.environ["GF_LANES"] = str(cls.tmp / "lanes")
        cls.clock = FixedClock()
        cls.factory = Factory(cls.tmp / "home", clock=cls.clock)
        cls.fx = build(cls.factory, cls.clock, cls.tmp / "lanes")
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        if cls.lanes_env is None:
            os.environ.pop("GF_LANES", None)
        else:
            os.environ["GF_LANES"] = cls.lanes_env
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-insights")
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
            b.screenshot(self.shots / f"insights-{b.step.replace(' ', '-')}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 900 if px > 500 else 800,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})

    def theme(self, mode: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=mode.capitalize(), what=f"{mode} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === '{mode}'", f"the {mode} theme")

    def pick(self, group: str, text: str) -> None:
        b = self.browser
        b.click(f'#insights [data-control="{group}"] .seg-b', text=text, what=f"{text} in {group}")
        b.wait(f"(() => {{ const on = document.querySelector('#insights [data-control=\"{group}\"] .seg-b.on');"
               f" return !!on && on.textContent === {json.dumps(text)} && !document.querySelector('#insights.ins-busy'); }})()",
               f"{text} chosen")

    def scope(self, pid: str, shows: str) -> None:
        """Choose the scope in its select, as a keyboard or a pointer does, and wait for the insights it shows."""
        b = self.browser
        b.eval(f"(() => {{ const s = document.querySelector('#insights select[data-control=\"insights_scope\"]');"
               f" s.value = {json.dumps(pid)}; s.dispatchEvent(new Event('change')); }})()")
        b.wait(f"(() => {{ const s = document.querySelector('#insights .ins-sum');"
               f" return s && s.textContent.includes({json.dumps(shows)}) && !document.querySelector('#insights.ins-busy'); }})()",
               f"the insights of {shows}")

    def every_dimension(self, where: str, mode: str) -> None:
        b = self.browser
        for label in DIMENSIONS:
            self.pick("insights_dimension", label)
            drawn = b.wait(DRAWN, f"the {label} insights")
            self.assertGreater(drawn["tiles"], 2, label)
            self.assertGreater(drawn["charts"], 0, label)
            self.assertEqual(drawn["empty"], [], f"{label}: a chart drew nothing at all")
            self.assertEqual(drawn["lines"], 0, f"{label}: a tile or chart without its line")
            self.assertTrue(b.eval(FITS), f"{label} scrolls sideways ({where}, {mode})")
            self.assertEqual(b.eval(NAMED), [], f"{label}: a control without a name ({where}, {mode})")
            self.colours(label, mode)

    def colours(self, label: str, mode: str) -> None:
        got = self.browser.eval(COLOURS)
        slots = [hex_of(c) for c in got["slots"]]
        report = validate(slots, mode, hex_of(got["surface"]))
        self.assertTrue(report["ok"], f"{label} ({mode}): {report['fails']}")
        allowed = set(slots) | {hex_of(self.browser.eval(
            f"(() => {{ const p = document.createElement('span'); document.body.append(p); p.style.color = 'var(--{v})';"
            f" const c = getComputedStyle(p).color; p.remove(); return c; }})()")) for v in
            ("good-mark", "warning-mark", "serious-mark", "critical-mark", "neutral-mark")}
        for mark in got["marks"]:
            self.assertIn(hex_of(mark), allowed, f"{label} ({mode}): a mark in a colour outside the palette")

    def test_FR_INS1_AC_6_every_dimension_renders_readably_in_both_themes_at_both_widths(self):
        b = self.browser
        self.step("sign in")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in cockpit")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-business_owner"]', what="the business owner persona")
        b.click("#pp-done", what="Done")
        self.theme("dark")

        self.step("open insights from the sidebar")
        b.click('a.nav-i[href="#/insights"]', what="Insights in the sidebar")
        b.wait(DRAWN, "the insights")
        self.assertEqual(b.eval("document.querySelector('#view-title').textContent"), "Insights")

        self.step("every dimension dark 1440")
        self.every_dimension("1440", "dark")

        self.step("usage over all records")
        self.pick("insights_dimension", "Usage")
        self.pick("insights_window", "All")
        tokens = b.wait("(() => { const t = document.querySelector('#insights [data-tile=\"tokens\"] .kpi-v');"
                        " return t && t.textContent; })()", "the tokens tile")
        self.assertTrue(tokens.startswith("12.0K"), tokens)
        nm = b.eval("document.querySelector('#insights [data-tile=\"skills_accepted\"] .kpi-v').textContent")
        self.assertIn("Not measured", nm)

        self.step("a chart as its table")
        b.click('#insights [data-chart="by_model"] button[aria-label^="Table view"]', what="the table view of tokens by model")
        cells = b.wait("(() => { const t = document.querySelector('#insights [data-chart=\"by_model\"] table');"
                       " return t && [...t.querySelectorAll('tbody tr')].map((r) => r.textContent); })()", "the table")
        self.assertTrue(any("hosted-large" in c and "8,400" in c for c in cells), cells)

        self.step("one project in scope")
        self.scope(self.fx["quiet"].pid, "Quiet idea")
        self.assertIn("Not measured", b.eval("document.querySelector('#insights [data-tile=\"tokens\"]').textContent"))

        self.step("the project tab")
        loans = self.fx["loans"].pid
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{loans}/insights"})
        b.wait("(() => { const s = document.querySelector('#insights .ins-sum');"
               " return s && s.textContent.includes('Equipment loans'); })()", "the project's Insights tab")
        self.assertTrue(b.eval("!!document.querySelector('.tabs a[aria-current=page][href$=\"/insights\"]')"))
        self.assertFalse(b.eval("!!document.querySelector('#insights select[data-control=\"insights_scope\"]')"))

        self.step("light 390")
        self.width(1440)
        self.theme("light")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/insights"})
        b.wait(DRAWN, "the insights")
        self.scope("", "the whole factory")                          # the scope chosen before is kept: back to all
        self.width(390)
        time.sleep(0.3)
        self.every_dimension("390", "light")

        self.step("dark 390 and light 1440")
        self.width(1440)
        self.theme("dark")
        self.width(390)
        self.every_dimension("390", "dark")
        self.width(1440)
        self.theme("light")
        self.every_dimension("1440", "light")

        self.step("pin a tile to home")
        self.pick("insights_dimension", "QA")
        b.click('#insights [data-tile="pass_rate"] [data-control="insights_pin"]', what="Pin the gate pass rate")
        b.wait("(() => { const t = document.querySelector('#status .toast'); return t && t.textContent.includes('pinned'); })()",
               "the pinned toast")
        b.click('a.nav-i[href="#/home"]', what="Home in the sidebar")
        pinned = b.wait("(() => { const w = document.querySelector('#grid .widget[data-type=\"insight\"] .ins-tile');"
                        " return w && w.textContent; })()", "the pinned tile on Home")
        self.assertIn("Gate pass rate", pinned)
        self.assertTrue(b.eval(FITS))

        self.step("export")
        b.click('a.nav-i[href="#/insights"]', what="Insights in the sidebar")
        b.wait(DRAWN, "the insights")
        b.click('#insights [data-control="insights_export"]', what="Export")
        b.click("#menu-pop .menu-item", text="CSV", what="CSV in the export menu")
        b.wait("(() => { const t = document.querySelector('#status .toast'); return t && t.textContent.includes('Nothing was sent'); })()",
               "the export toast")
        self.check()


if __name__ == "__main__":
    unittest.main()
