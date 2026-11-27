"""The live progress of an assessment in a real browser (FR-PRG1-AC-7): headless Chrome over the DevTools protocol.

A project mirrors the poor fixture repository (tests/fixtures/assess); one assessment with the panel ran before,
so the next is timed from it. The cockpit's panel model is scripted and slowed (each perspective answers after a
pause), so the test watches an assessment as it runs: a person signs in, opens the Assessment tab, ticks Ask the
panel too and presses Assess now. The progress view shows at once; the reading and rule tiles fill and carry
their findings, the panel's perspectives run one after another with the model named, pressing an area lists its
findings so far, the Overview carries the same tiles small, Ask Rihma answers how it is going with them, and when
the assessment ends the view hands over to the result. It is looked at dark and light, at 1440 and 390 px: no
console error, failed request or CSP violation, every control named, nothing scrolling sideways, and the marks'
colours pass the dataviz validator (tests/insights_palette.py) against the surface they are drawn on.
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

sys.path.insert(0, str(Path(__file__).parent))

from insights_palette import hex_of, validate  # noqa: E402
from test_assess import fixture_repo, mirrored, panel_script  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.progress_routes import history_path  # noqa: E402
from cockpit.server import make_server  # noqa: E402
from kernel import assess, progress  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
PAUSE_S = 1.6
NAMELESS = ("[...document.querySelectorAll('#main button, #main input, #main select, #main a[href]')]"
            ".filter((el) => el.getClientRects().length && !((el.getAttribute('aria-label') || '').trim()"
            " || (el.labels && [...el.labels].some((l) => l.textContent.trim())) || el.textContent.trim()"
            " || el.getAttribute('title'))).map((el) => el.outerHTML.slice(0, 120))")
SIDEWAYS = "document.documentElement.scrollWidth > window.innerWidth + 1"
TILES = ("(() => { const out = {}; document.querySelectorAll('#main .prg[data-control=\"assessment_progress\"] .prg-tile')"
         ".forEach((t) => { out[t.dataset.step] = {state: t.dataset.state, num: t.querySelector('.prg-num').textContent,"
         " label: t.getAttribute('aria-label')}; }); return out; })()")
# The progress hue and the failed mark as the page resolves them, the card's surface and every fill drawn.
COLOURS = ("(() => { const probe = document.createElement('span'); document.body.append(probe);"
           " const tone = (v) => { probe.style.color = 'var(' + v + ')'; return getComputedStyle(probe).color; };"
           " const slots = [tone('--series-1'), tone('--critical-mark')]; probe.remove();"
           " const card = document.querySelector('.prg');"
           " const marks = [...document.querySelectorAll('.prg .prg-tile:not([data-state=waiting]):not([data-state=skipped]) .prg-fill,"
           " .prg .prg-seg[data-state=done], .prg .prg-seg[data-state=failed]')].map((e) => getComputedStyle(e).backgroundColor)"
           ".filter((c) => c !== 'rgba(0, 0, 0, 0)');"
           " return {slots, surface: card ? getComputedStyle(card).backgroundColor : null, marks}; })()")


def slow(prompt: str, role: str) -> str:
    time.sleep(PAUSE_S)
    return panel_script(prompt, role)


class UiProgressTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for the fixture repository")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-progress-")).resolve()
        cls.lanes_env = os.environ.get("GF_LANES")
        os.environ["GF_LANES"] = str(cls.tmp / "lanes")
        cls.factory = Factory(cls.tmp / "home")
        cls.project = mirrored(cls.factory, "Orders", fixture_repo("poor", cls.tmp / "src"))
        # an earlier assessment with the panel, timed where the cockpit keeps the project's runs
        model = FakeModel(lambda p, r: (time.sleep(PAUSE_S * 0.8), panel_script(p, r))[1])
        model.name = "qwen3.6-35b"
        rep = progress.Reporter("assessment", history=progress.History(history_path(cls.factory.home, cls.project.pid)))
        assess.assess(cls.project, person=PERSON, persona="developer", model=model, which=lambda tool: None, progress=rep)
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        slowed = FakeModel(slow)
        slowed.name = "qwen3.6-35b"
        cls.server.assistant_model = slowed
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
        self.browser = Browser(self.chrome, self.tmp / "chrome-progress")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

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
        self.assertEqual(b.eval(NAMELESS), [], f"controls without an accessible name during '{b.step}'")
        self.assertFalse(b.eval(SIDEWAYS), f"the page scrolls sideways during '{b.step}'")
        self.shot()

    def shot(self, suffix: str = "") -> None:
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.browser.screenshot(self.shots / f"progress-{self.browser.step.replace(' ', '-')}{suffix}.png")

    def into_view(self, selector: str) -> None:
        self.browser.eval(f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block: 'start'}})")
        time.sleep(0.2)

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000 if px > 600 else 860,
                                                                "deviceScaleFactor": 1, "mobile": px < 600})

    def theme(self, word: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def colours(self, mode: str) -> None:
        got = self.browser.eval(COLOURS)
        slots = [hex_of(c) for c in got["slots"]]
        report = validate(slots, mode, hex_of(got["surface"]))
        self.assertTrue(report["ok"], f"{mode}: {report['fails']}")
        self.assertTrue(got["marks"], "no progress mark drawn")
        for mark in got["marks"]:
            self.assertIn(hex_of(mark), set(slots), f"{mode}: a progress mark in a colour outside the palette")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out')", "the signed-in cockpit")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def open_assessment(self) -> None:
        b = self.browser
        pid = self.project.pid
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{pid}/assessment"})
        b.wait("((document.querySelector('.view-body h2') || {}).textContent || '').endsWith(' · Assessment')"
               " && !!document.querySelector('[data-control=\"run_assessment\"]:not([disabled])')", "the Assessment view")

    def start(self) -> None:
        b = self.browser
        b.click('label.as-check', what="Ask the panel too")
        b.wait("document.querySelector('#as-panel').checked", "the panel ticked")
        b.click('[data-control="run_assessment"]', what="Assess now")
        b.wait("!!document.querySelector('.prg[data-control=\"assessment_progress\"]')", "the progress view at once", timeout=5)

    def running_panel(self, which: str) -> dict:
        return self.browser.wait(f"(() => {{ const t = {TILES}; return t[{json.dumps(which)}]"
                                 f" && t[{json.dumps(which)}].state === 'running' ? t : null; }})()",
                                 f"the {which} step running", timeout=40)

    def handed_over(self, aid: str) -> None:
        b = self.browser
        b.wait(f"(document.querySelector('#as-sum-h') || {{}}).textContent && document.querySelector('#as-sum-h')"
               f".textContent.startsWith({json.dumps(aid + ' of revision')})"
               " && !document.querySelector('.prg[data-control=\"assessment_progress\"]')", f"the hand-over to {aid}",
               timeout=60)

    def test_FR_PRG1_AC_7_a_person_watches_an_assessment_fill_area_by_area_and_hand_over_to_the_result(self):
        b = self.browser
        pid = self.project.pid
        self.step("sign in")
        self.width(1440)
        self.sign_in()
        self.theme("Dark")
        self.step("open the assessment")
        self.open_assessment()

        self.step("running dark 1440")
        self.start()
        tiles = self.running_panel("panel.end_user")
        for sid in ("read.mirror", "read.inventory", "rules.cicd", "rules.maintenance", "rules.redteam", "panel.business"):
            self.assertEqual(tiles[sid]["state"], "done", sid)
        self.assertEqual((tiles["rules.cicd"]["num"], tiles["rules.maintenance"]["num"]), ("5", "6"))
        self.assertEqual(tiles["panel.delivery"]["state"], "waiting")
        self.assertIn("qwen3.6-35b", tiles["panel.end_user"]["label"])
        now = b.eval("document.querySelector('.prg .prg-now').textContent")
        self.assertEqual(now, "The end user perspective is reading the inventory and the rules' results with qwen3.6-35b")
        meta = b.eval("document.querySelector('.prg .prg-meta').textContent")
        self.assertIn("of 14 steps", meta)
        self.assertIn("from 1 earlier run", meta)
        self.assertEqual(b.eval("document.querySelector('[data-control=\"cancel_assessment\"]').hidden"), False)
        self.colours("dark")

        self.step("an area s findings")
        b.click('.prg-tile[data-step="rules.cicd"]', what="the CI/CD governance tile")
        head = b.wait("(() => { const x = document.querySelector('.prg .prg-fh'); return x && x.textContent.startsWith('CI/CD')"
                      " ? x.textContent : null; })()", "the area's findings")
        self.assertEqual(head, "CI/CD governance: 5 findings so far")
        self.assertEqual(b.eval("document.querySelectorAll('.prg .prg-fl .prg-fi').length"), 5)
        self.assertEqual(b.eval("document.querySelector('.prg-tile[data-step=\"rules.cicd\"]').getAttribute('aria-pressed')"), "true")

        self.step("running light 390")
        self.theme("Light")
        self.width(390)
        self.running_panel("panel.operations")
        self.colours("light")
        self.into_view(".prg .prg-head")
        self.shot("-top")
        self.into_view('.prg .prg-group[data-group="panel"]')

        self.step("hand over")
        self.handed_over("AS-2")
        self.assertIn("prg-arrive", b.eval("document.querySelector('#as-sum-h').closest('section').className"))

        self.step("overview and chat light 1440")
        self.width(1440)
        self.open_assessment()
        self.start()
        self.running_panel("panel.business")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{pid}/overview"})
        b.wait("!!document.querySelector('[data-control=\"assessment_progress_card\"] .prg-tile')", "the Overview's card")
        self.assertIn("Open the assessment", b.eval("document.querySelector('[data-control=\"assessment_progress_card\"]').textContent"))
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "How is the assessment going?")
        b.click("#as-send", what="Send")
        said = b.wait("(() => { const m = [...document.querySelectorAll('#as-log .msg.bot')].pop();"
                      " return m && m.querySelector('.prg-compact') ? m.textContent : null; })()", "the answer with its tiles",
                      timeout=30)
        self.assertIn("The assessment is", said)
        self.shot("-chat")
        b.click("#as-log .msg.bot button", text="Take me there", what="Take me there")
        b.click("#as-close", what="Close the assistant")

        self.step("running dark 390")
        self.theme("Dark")
        self.width(390)
        b.wait("!!document.querySelector('.prg[data-control=\"assessment_progress\"] .prg-tile')", "the progress again")
        self.running_panel("panel.it_security")
        self.colours("dark")
        self.into_view('.prg .prg-group[data-group="rules"]')
        self.step("hand over again")
        self.handed_over("AS-3")


if __name__ == "__main__":
    unittest.main()
