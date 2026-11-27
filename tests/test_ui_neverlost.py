"""FR-NVL1 in a real browser (headless Chrome over the DevTools protocol, as tests/test_ui_drive.py), on the demo home
(kernel/demo.py: a full project with a release, a project stuck at its questions, an adopted one) plus a brand-new
blank project.

AC-3: every page and every project view, as every persona, on the sparse and the full projects: no raw null,
undefined, NaN or [object Object]; no empty region without its explanation; every empty state carries "Why? Ask
Rihma"; and pressing one opens Ask Rihma with the reason and the step that fills it. No console error and nothing
wider than the screen. AC-8: Decide what matters (the blocking few, the proposal, its confirm), Who acted (every run,
Harness and enforcement with its opt-out) and Settings, dark at 1440 px and light at 390 px. Skipped when Chrome is
not installed.
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
from kernel.canon import Canon  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
ALL = ("business_owner", "product_owner", "stakeholder", "concept_evaluator", "end_user", "developer", "it",
       "operations", "compliance")
PERSONAS = tuple((os.environ.get("RIHMA_NVL_PERSONAS") or ",".join(ALL)).split(","))   # all, unless a run narrows
# How much wider than the device the page is. With mobile emulation a too-wide page grows the layout viewport
# (innerWidth 529 on a 390 px phone), so scrollWidth - innerWidth stays 0: the page is measured against the device's
# own width, which the test sets (FR-NVL2).
OVERFLOW = "Math.max(document.documentElement.scrollWidth, window.innerWidth) - {device}"
LAST = "((document.querySelector('#as-log .msg.bot:last-child .bub') || {}).textContent || '')"
# What a view must never show, and an empty region with nothing to say.
LOOK = r"""(() => {
  const main = document.querySelector('#main');
  const out = [];
  const raw = /(^|[^A-Za-z_-])(null|undefined|NaN)(?=$|[^A-Za-z_-])|\[object Object\]/;
  const skip = (el) => !el || !!el.closest('code, pre, textarea, script, style, [data-raw], .heal-log');
  const walk = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) {
    const t = walk.currentNode;
    const shown = !skip(t.parentElement) && t.parentElement.getClientRects().length;
    if (raw.test(t.nodeValue) && shown) out.push('raw: ' + t.nodeValue.trim().slice(0, 100));
  }
  main.querySelectorAll('section, .card, .widget, article, .cards, ul, ol, tbody, .tile').forEach((el) => {
    if (el.offsetHeight < 28 || !el.getClientRects().length) return;
    if (el.querySelector('svg:not(.ic), canvas, img, input, select, textarea, button, a, iframe, [role=img]')) return;
    if (!el.textContent.trim()) out.push('an empty region: ' + el.outerHTML.slice(0, 140));
  });
  main.querySelectorAll('.empty, [data-empty]').forEach((el) => {
    if (!el.getClientRects().length) return;
    if (!el.textContent.trim()) out.push('an empty state that says nothing: ' + el.outerHTML.slice(0, 120));
    const next = el.nextElementSibling;
    const said = el.textContent.trim().slice(0, 80);
    if (!(next && next.querySelector('.nvl-why'))) out.push('an empty state without Why? Ask Rihma: ' + said);
  });
  return out;
})()"""


class NeverLostUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-nvl-")).resolve()
        home = cls.tmp / "Rihmasto-home-folder-of-a-person"     # a long home path, as people keep them (FR-NVL2)
        try:
            build_demo(home, echo=lambda line: None)
        except Exception:
            roads.stop_started()
            roads.rmtree(cls.tmp)
            raise
        cls.factory = Factory(home)
        cls.blank = cls.factory.new_project("Blank one", maturity="demo", mode="mixed")
        by = {p.meta.get("title"): p for p in cls.factory.projects()}
        cls.full = by["Shipment webhook to the stock system"]
        cls.sparse = by["Equipment loans"]
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None
        views = json.loads((Path(__file__).parent.parent / "cockpit" / "ui_map.json").read_text(encoding="utf-8"))
        cls.pages = [v["route"] for v in views["views"] if "{pid}" not in v["route"]]
        cls.project_views = [v["id"] for v in views["views"] if "{pid}" in v["route"]]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        roads.stop_started()
        with contextlib.suppress(OSError):
            roads.rmtree(cls.tmp)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / f"chrome-{self.id().rsplit('.', 1)[-1][:12]}")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.device = None                   # the device's own width once narrow() emulates a phone

    # -- helpers ------------------------------------------------------------------------------------------------

    def step(self, name: str) -> None:
        if self.browser.step != "start":
            self.check()
        self.browser.step = name

    def check(self, shot: bool = True) -> None:
        b = self.browser
        b.eval("1")
        time.sleep(0.2)
        b.eval("1")
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        device = self.device or b.eval("window.innerWidth")
        self.assertLessEqual(b.eval(OVERFLOW.format(device=device)), 0,
                             f"the page is wider than the {device} px screen during '{b.step}'")
        if self.shots and shot:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"nvl-{b.step.replace(' ', '-')}.png")

    def sign_in(self, persona: str = "business_owner") -> None:
        b = self.browser
        link = self.server.issue_link(ttl=None)                     # each test signs in with its own link
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={link}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what="the persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def as_persona(self, persona: str) -> None:
        b = self.browser
        b.eval(f"sessionStorage.setItem('gf.persona', {json.dumps(persona)}); localStorage.setItem('gf.viewall', '0');"
               " location.hash = '#/home'; location.reload(); true")
        time.sleep(0.3)
        b.wait("!!document.querySelector('#grid') && document.querySelector('#main').dataset.loaded === '1'",
               f"Home as {persona}")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def narrow(self) -> None:
        b = self.browser
        b.cmd("Emulation.setDeviceMetricsOverride",
              {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.screen.width === 390", "the narrow screen")      # innerWidth grows with a too-wide page
        self.device = 390
        time.sleep(0.3)

    def go(self, route: str) -> None:
        b = self.browser
        r = json.dumps(route)
        b.eval(f"if (location.hash !== {r}) {{ document.querySelector('#main').dataset.loaded = '';"
               f" location.hash = {r}; }} true")
        b.wait("document.querySelector('#main').dataset.loaded === '1'"
               " && !document.querySelector('#main [aria-busy=\"true\"]')", route, timeout=30)
        time.sleep(0.15)                                       # the shell's sweep adds Why? Ask Rihma (60 ms)

    def starved(self) -> bool:
        """This machine ran out of socket buffers (WSAENOBUFS, many parallel suites): not the page's fault. The
        request is dropped from the problems and the view is read again after a pause."""
        b = self.browser
        before = len(b.problems)
        b.problems = [p for p in b.problems if "ERR_NO_BUFFER_SPACE" not in str(p[2])]
        return len(b.problems) != before

    def visit(self, route: str) -> list:
        b = self.browser
        self.go(route)
        for _ in range(3):
            if not self.starved():
                break
            time.sleep(3)
            b.eval("document.querySelector('#main').dataset.loaded = ''; location.reload(); true")
            time.sleep(0.5)
            b.wait("document.querySelector('#main').dataset.loaded === '1'"
                   " && !document.querySelector('#main [aria-busy=\"true\"]')", route, timeout=30)
            time.sleep(0.15)
        with contextlib.suppress(AssertionError):     # a part drawn late gets its button from the next sweep
            b.wait("![...document.querySelectorAll('#main .empty, #main [data-empty]')]"
                   ".some((e) => !e.dataset.nvl && e.getClientRects().length)", "the shell's sweep", timeout=3)
        found = b.eval(LOOK)
        for _ in range(2):          # a busy machine draws a part after the sweep: a real fault is still there after
            if not found:
                break
            time.sleep(1.5)
            found = b.eval(LOOK)
        return found

    def routes(self) -> list:
        out = list(self.pages)
        for p in (self.sparse, self.blank, self.full):
            out += [f"#/p/{p.pid}/{v}" for v in self.project_views]
        return out

    # -- AC-3 -----------------------------------------------------------------------------------------------------

    def test_FR_NVL1_AC_3_every_view_as_every_persona_explains_what_is_empty_and_shows_no_raw_value(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        found = []
        for persona in PERSONAS:
            self.step(f"walk as {persona}")
            self.as_persona(persona)
            for route in self.routes():
                found += [f"{persona} {route}: {x}" for x in self.visit(route)]
            self.check(shot=False)
        self.assertEqual(found, [], "views that show a raw value or an unexplained empty region")
        self.step("why on an empty view")
        self.as_persona("developer")
        self.go(f"#/p/{self.blank.pid}/releases")
        b.click("#main .nvl-row .nvl-why", what="Why? Ask Rihma under the empty state")
        b.wait("((document.querySelector('#as-log .msg.bot:last-child .bub') || {}).textContent || '')"
               ".includes('The step that fills it')", "Rihma's answer")
        said = b.eval("document.querySelector('#as-log .msg.bot:last-child .bub').textContent")
        self.assertIn("Releases is empty because a release is cut once the work passed its quality checks", said)
        self.assertIn('The record says: "No release yet.', said)
        self.step("why on a value not measured")
        b.click("#as-close", what="Close Ask Rihma")
        b.click("#main .chip[data-nvl-m] + .nvl-why", what="Why? Ask Rihma beside Track: Not measured")
        b.wait("((document.querySelector('#as-log .msg.bot:last-child .bub') || {}).textContent || '')"
               ".includes('is not measured because')", "Rihma's answer about the chip")
        said = b.eval("document.querySelector('#as-log .msg.bot:last-child .bub').textContent")
        self.assertIn("Track is not measured because", said)
        self.assertIn("progress is tracked against tasks, and there are none yet", said)   # the view it names
        self.assertNotIn("Maturity", said)                   # the chip's own words, never the whole row's
        self.step("why answered")
        self.go(f"#/p/{self.blank.pid}/releases")
        b.click("#main .nvl-row .nvl-why", what="Why? Ask Rihma under the empty state")
        b.wait("((document.querySelector('#as-log .msg.bot:last-child .bub') || {}).textContent || '')"
               ".includes('Releases is empty')", "Rihma's answer")
        self.assertIn("Ask Rihma", b.eval("document.querySelector('#as-log .msg.bot:last-child .nvl-who').textContent"))
        b.click("#as-log .msg.bot:last-child [data-key^='fill:']", what="the step that fills it")
        b.wait(f"location.hash === '#/p/{self.blank.pid}/tasks'", "the tasks view")
        self.check()

    # -- AC-8 -----------------------------------------------------------------------------------------------------

    def test_FR_NVL1_AC_8_triage_who_acted_and_enforcement_work_dark_wide_and_light_narrow(self):
        b = self.browser
        self.step("sign in")
        self.sign_in("product_owner")
        self.theme("dark", "Dark")
        self.step("decide what matters on the sparse project")
        self.go(f"#/p/{self.sparse.pid}/triage")
        b.wait("document.querySelectorAll('.nvl-rank').length >= 1", "the blocking decisions")
        self.assertIn("block", b.eval("document.querySelector('#main .lede[data-ud]').textContent"))
        self.step("decide what matters on the full project")
        self.go(f"#/p/{self.full.pid}/triage")
        b.wait("!!document.querySelector('[data-key=\"triage:assume\"]')", "the proposal")
        self.assertTrue(b.eval("document.querySelectorAll('.nvl-grew').length >= 1"))   # a released assumption grew
        b.click('[data-key="triage:assume"]', what="Assume the rest for me")
        b.wait("(document.querySelector('#status') || {}).textContent.includes('recorded as your delegated choice')",
               "the confirmation")
        recs = self.full.ledger().of_kind("triage_assumed")
        self.assertEqual(recs[-1]["event"]["payload"]["person"], PERSON)
        self.step("ask rihma to triage")
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "I have 50 decisions: what blocks work? assume the rest")
        b.key("Enter", 13)
        b.wait("(document.querySelector('#as-log .msg.bot:last-child [data-by=\"triage\"]') || {}).textContent",
               "the triage answer")
        self.assertIn("by rule", b.eval("document.querySelector('#as-log .msg.bot:last-child').textContent"))
        b.click("#as-close", what="Close Ask Rihma")
        self.step("who acted")
        self.go(f"#/p/{self.full.pid}/who")
        b.wait("document.querySelectorAll('.nvl-run').length >= 3", "the runs")
        runs = b.eval("document.querySelector('#nvl-runs-h').closest('section').textContent")
        self.assertIn("Gnomon", runs)
        self.assertIn("demo-builder", runs)
        self.assertIn("Gnomon enforces", b.eval("document.querySelector('.nvl-harness').textContent"))
        self.step("settings light and narrow")
        self.theme("light", "Light")
        self.narrow()
        self.go("#/settings")
        b.wait("!!document.querySelector('#nvl-enf-h')", "Harness and enforcement in Settings")
        self.assertTrue(b.eval("document.querySelector('[data-key=\"enf:set:platform\"]').disabled"))   # IT sets it
        self.step("who acted narrow")
        self.go(f"#/p/{self.full.pid}/who")
        b.wait("!!document.querySelector('[data-key^=\"enf:set:\"]')", "the project's enforcement")
        b.type(f"#enf-reason-{self.full.pid}", "trying Claude Code this week")
        b.click(f'[data-key="enf:set:{self.full.pid}"]', what="Opt out of Gnomon's enforcement")
        b.wait("(document.querySelector('.nvl-harness') || {}).textContent.includes('Opted out')", "the opt-out")
        rec = self.full.ledger().of_kind("enforcement_set")[-1]["event"]["payload"]
        self.assertEqual((rec["on"], rec["reason"], rec["person"]), (False, "trying Claude Code this week", PERSON))
        self.check()

    # -- FR-NVL2 AC-9 ----------------------------------------------------------------------------------------------

    def ask_typed(self, question: str, expect: str) -> str:
        b = self.browser
        if not b.eval("!!document.querySelector('#as-q') && !!document.querySelector('#as-q').offsetParent"):
            b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", question)
        b.key("Enter", 13)
        b.wait(f"{LAST}.includes({json.dumps(expect)})", f"Rihma's answer to {question}")
        return b.eval(LAST)

    def tile_and_typed(self) -> None:
        """A tile not measured is named by its label and follows its own hint; typed questions read their subject."""
        b = self.browser
        self.go(f"#/p/{self.full.pid}/insights")
        b.wait("!!document.querySelector('#main .kpi[data-nvl-m] .nvl-why')", "a tile's Why? Ask Rihma")
        label = b.eval("document.querySelector('#main .kpi[data-nvl-m] .kpi-h > span').textContent.trim()")
        b.click("#main .kpi[data-nvl-m] .nvl-why", what="Why? Ask Rihma on a tile not measured")
        b.wait(f"{LAST}.includes('is not measured because')", "Rihma's answer about the tile")
        said = b.eval(LAST)
        self.assertIn(label + " on Project insights is not measured because nothing has measured it yet: to measure "
                      "it,", said)
        self.assertNotIn("Pin to Home", said)
        self.assertNotIn("Go on with the project", said)          # never against the tile's own hint
        self.step("typed questions on a project with data")
        said = self.ask_typed("why is Insights empty?", "is not empty here")
        self.assertIn("Project insights is not empty here: it shows figures from", said)
        said = self.ask_typed("why is cost not measured?", "Cost is not measured because")
        self.assertNotIn("Floor", said)
        b.click("#as-close", what="Close Ask Rihma")

    def stakeholder_triage(self) -> None:
        b = self.browser
        self.as_persona("stakeholder")
        self.go(f"#/p/{self.full.pid}/triage")
        go = "document.querySelector('[data-key=\"triage:assume\"]')"
        b.wait(f"!!{go}", "the proposal's button")
        self.assertTrue(b.eval(f"{go}.disabled"))
        self.assertIn("Nothing you may assume here", b.eval(f"{go}.textContent"))
        self.assertIn("a stakeholder may not decide this", b.eval("document.querySelector('.nvl-refused').textContent"))

    def decide_all(self, changes: list) -> None:
        b = self.browser
        self.as_persona("business_owner")
        self.go("#/decide")
        b.wait("document.querySelectorAll('#main .nvl-rank').length >= 1", "the blocking decisions in every project")
        self.assertIn("Across", b.eval("document.querySelector('#main .lede[data-ud]').textContent"))
        b.wait("!!document.querySelector('[data-key=\"triage:assume:all\"]:not([disabled])')", "the one proposal")
        b.click('[data-key="triage:assume:all"]', what="Assume the rest across projects")
        b.wait("(document.querySelector('#status') || {}).textContent.includes('recorded as your delegated choice')",
               "the confirmation")
        rec = self.full.ledger().of_kind("triage_assumed")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"]), (PERSON, "business_owner"))
        self.assertTrue(set(changes) <= set(rec["deferred"]), rec)

    def settings_tap(self) -> None:
        """At 390 px, nothing is wider than the device and a real tap opts out of Gnomon's enforcement and back in."""
        b = self.browser
        self.as_persona("it")
        self.go("#/settings")
        b.wait("!!document.querySelector('[data-key=\"enf:set:platform\"]:not([disabled])')", "the platform's toggle")
        self.check()
        b.type("#enf-reason-platform", "a harness trial on one laptop")
        state = "(document.querySelector('.nvl-settings .nvl-harness .chip') || {}).textContent"
        b.click('[data-key="enf:set:platform"]', what="Opt out of Gnomon's enforcement (a real tap)")
        b.wait(f"{state} === 'Opted out'", "the opt-out")
        b.click('[data-key="enf:set:platform"]', what="Turn Gnomon's enforcement back on (a real tap)")
        b.wait(f"{state} === 'Gnomon enforces'", "back on")
        recs = [r["event"]["payload"]["on"] for r in factory_project(self.factory).ledger().of_kind("enforcement_set")]
        self.assertEqual(recs[-2:], [False, True])

    def test_FR_NVL2_AC_9_answers_tiles_triage_and_settings_hold_in_the_browser_dark_wide_and_light_narrow(self):
        # two changes on the full project: a business or product owner decides each, never a stakeholder
        changes = [Canon(self.full).card("change", title, refs={"requirements": ["R-1"]})["id"]
                   for title in ("Retry a failed shipment once", "Send a daily summary")]
        self.step("sign in")
        self.sign_in("developer")
        self.theme("dark", "Dark")
        self.step("a tile not measured on insights")
        self.tile_and_typed()
        self.step("a stakeholder is offered nothing to assume")
        self.stakeholder_triage()
        self.step("decide what matters across projects")
        self.decide_all(changes)
        self.step("settings light and narrow as it")
        self.theme("light", "Light")
        self.narrow()
        self.settings_tap()
        self.step("decide what matters narrow")
        self.go("#/decide")
        self.check()

if __name__ == "__main__":
    unittest.main()
