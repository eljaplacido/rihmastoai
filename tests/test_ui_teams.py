"""Teams, their words and what applies where in a real browser (FR-TM1, FR-TM2, FR-TM3): headless Chrome over the
DevTools protocol, as tests/test_ui_drive.py drives it. Fixtures are invented.

A person working alone sees one calm line about the team made for them. IT makes a second team in Settings, moves a
project into it (preview first, then confirmed, signed), and the project's settings carry the same Team field. On the
project's Vocabulary view a requirement is called a story (preview, then saved), the Knowledge graph's legend reads
"Story" while no record changes, and Undo gives "Requirement" back. Settings shows the team's Vocabulary and What
applies where. Every view fits dark and light at 1440 and 390 pixels with nothing scrolling sideways; a business
owner meets none of the words words.js keeps from them. No step leaves a console error, a failed request or a CSP
violation. ``RIHMA_UI_SHOTS=<folder>`` keeps a screenshot per step; ``RIHMA_TEAMS_UI_PORT`` fixes the cockpit's port.
"""

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

from graph_view_fixture import every_kind  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402
from test_ui_words import JARGON, SLOP, hits, visible  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from factory_fakes import no_local_routing  # noqa: E402
from kernel import team as kteam  # noqa: E402
from kernel import teams, vocab  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

SETTLED = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"
THEMES = (("dark", 1440), ("dark", 390), ("light", 1440), ("light", 390))


class UiTeamsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        patcher = no_local_routing()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-tm-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home", clock=FixedClock())
        kteam.name_solo(self.factory, PERSON)
        self.server, self.bootstrap = make_server(self.factory, int(os.environ.get("RIHMA_TEAMS_UI_PORT") or 0),
                                                  runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def new(self, *, mode="mixed", maturity="demo", title="Equipment loans"):     # what every_kind asks of its case
        return self.factory.new_project(title, mode=mode, maturity=maturity)

    def step(self, name: str) -> None:
        if self.browser.step != "start":
            self.check()
        self.browser.step = name

    def check(self) -> None:
        b = self.browser
        b.eval("1")
        time.sleep(0.3)
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"teams-{b.step.replace(' ', '-')}.png")

    def sign_in(self, persona: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        self.persona(persona)

    def persona(self, persona: str) -> None:
        b = self.browser
        b.click("#person-chip", what="the person chip")
        b.eval("document.querySelector('#person').value = ''; true")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done in the person menu")

    def go(self, route: str, ready: str, what: str) -> None:
        b = self.browser
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('#grid')", "home")
        b.eval(f"location.hash = {json.dumps(route)}; true")
        b.wait(ready, what)

    def fits(self, root: str, what: str) -> None:
        b = self.browser
        b.eval(SETTLED)
        self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, what)
        spills = b.eval(f"[...document.querySelectorAll({json.dumps(root + ' .card')})].filter((c) => c.scrollWidth >"
                        " c.clientWidth + 1).map((c) => c.getAttribute('aria-labelledby'))")
        self.assertEqual(spills, [], (what, spills))

    def test_FR_TM1_AC_9_a_solo_person_sees_one_line_and_it_makes_a_team_and_moves_a_project_in_chrome(self):
        b = self.browser
        p = every_kind(self)
        self.step("solo settings")
        self.sign_in("it")
        self.go("#/settings", "!!document.querySelector('#set-teams-h')", "Teams in Settings")
        solo = b.eval("document.querySelector('[data-key=tm-solo]').textContent")
        self.assertIn(PERSON, solo)
        self.assertIn("second person", solo)               # joins the same team: nothing to set up or migrate
        self.assertEqual(b.eval("document.querySelectorAll('.tm-team').length"), 0)       # no team block for one person
        self.step("make a team")
        b.click("details.tm-more summary", what="Make another team")
        b.type("#tm-new", "Platform")
        b.click('[data-key="tm-create"]', what="Make the team")
        b.wait("document.querySelectorAll('.tm-team').length === 2", "two teams")
        platform = next(t for t in teams.all_teams(self.factory) if t["name"] == "Platform")
        self.step("move a project")
        b.eval(f"const s = document.querySelector('[data-key=\"tm-proj-sel:{p.pid}\"]'); s.value = {json.dumps(platform['id'])};"
               " s.dispatchEvent(new Event('change')); true")
        b.click(f'[data-key="tm-proj-move:{p.pid}"]', what="Move (preview)")
        said = b.wait(f"(document.querySelector('[data-project=\"{p.pid}\"] [data-key=tm-preview]') || {{}}).textContent",
                      "the preview of the move")
        self.assertIn("moves from", said)
        self.assertNotIn("team", p.meta)                                      # the preview wrote nothing
        b.click(f'[data-key="tm-proj-move:{p.pid}"]', what="Move (confirm)")
        b.wait(f"!!document.querySelector('[data-team=\"{platform['id']}\"] [data-project=\"{p.pid}\"]')",
               "the project in the platform team")
        self.assertEqual(teams.team_of(self.factory, p), platform["id"])
        self.assertEqual(p.ledger().of_kind("project_team_set")[-1]["event"]["payload"]["by"], PERSON)
        self.step("project settings team field")
        self.go(f"#/p/{p.pid}/overview", "!!document.querySelector('[data-control=project_settings]')", "the project")
        b.click("[data-control=project_settings]", what="Project settings")
        b.wait("!!document.querySelector('[data-key=tm-sel]')", "the Team field")
        self.assertEqual(b.eval("document.querySelector('[data-key=tm-sel]').value"), platform["id"])
        self.check()

    def test_FR_TM2_AC_9_a_requirement_is_called_a_story_the_graph_reads_it_and_undo_restores_it_in_chrome(self):
        b = self.browser
        p = every_kind(self)
        self.step("the vocabulary view")
        self.sign_in("it")
        self.go(f"#/p/{p.pid}/vocabulary", "!!document.querySelector('[data-term=\"kind:requirement\"]')", "the Vocabulary")
        row = '[data-term="kind:requirement"]'
        self.assertEqual(b.eval(f"document.querySelector('{row}').dataset.scope"), "shipped")
        b.click(f"{row} summary", what="the term's layers and edit")
        b.type("#vc-kind-requirement-l", "Story")
        b.type("#vc-kind-requirement-r", "we write stories")
        b.click('[data-key="vc-kind-requirement-save"]', what="Save (preview)")
        said = b.wait(f"(document.querySelector('{row} [data-key=tm-preview]') || {{}}).textContent", "the preview")
        self.assertIn("read as Story", said)
        self.assertIn("read differently", said)
        self.assertEqual(vocab.read_layer(self.factory, "project", p.pid), {})        # nothing is saved by a preview
        b.click('[data-key="vc-kind-requirement-save"]', what="Save (confirm)")
        b.wait(f"document.querySelector('{row}') && document.querySelector('{row}').dataset.scope === 'project'",
               "the term in force from the project")
        self.assertEqual(vocab.read_layer(self.factory, "project", p.pid)["kind:requirement"]["label"], "Story")
        self.assertIn("defined on 2026-", b.eval(f"document.querySelector('{row} [data-key=vc-since]').textContent").lower())
        self.step("the graph reads it")
        self.go(f"#/p/{p.pid}/graph", "!!document.querySelector('.gv-legend')", "the Knowledge graph's legend")
        b.wait("document.querySelector('.gv-legend').textContent.includes('Story')", "the legend in the project's word")
        self.assertIn("This project's words", b.eval("document.querySelector('[data-key=gv-words]').textContent"))
        self.step("undo")
        self.go(f"#/p/{p.pid}/vocabulary", "!!document.querySelector('[data-key=vc-undo]')", "the Vocabulary")
        b.click('[data-key="vc-undo"]', what="Undo")
        b.wait(f"document.querySelector('{row}').dataset.scope === 'shipped'", "the shipped word back")
        self.assertEqual(vocab.read_layer(self.factory, "project", p.pid), {})
        self.go(f"#/p/{p.pid}/graph", "!!document.querySelector('.gv-legend')", "the legend")
        self.assertNotIn("Story", b.eval("document.querySelector('.gv-legend').textContent"))
        self.check()

    def test_FR_TM3_AC_8_settings_show_the_teams_words_and_what_applies_where_in_both_themes_at_both_widths(self):
        b = self.browser
        p = every_kind(self)
        teams.create(self.factory, "Platform", person=PERSON, persona="it")
        self.sign_in("it")
        for scheme, width in THEMES:
            self.step(f"{scheme} {width}")
            b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
            b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                         "mobile": width < 500})
            self.go("#/settings", "!!document.querySelector('#set-teams-h') && !!document.querySelector('#set-vocab-h')"
                    " && document.querySelectorAll('.sc-row').length > 8", "Teams, Vocabulary and What applies where")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", scheme)
            self.fits("#main", f"settings {scheme} {width}")
            self.go(f"#/p/{p.pid}/vocabulary", "!!document.querySelector('#vc-scope-h') && document.querySelectorAll('.vc-row').length > 5",
                    "the project's Vocabulary")
            self.fits(".vc-view", f"vocabulary {scheme} {width}")
        self.step("what applies where")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        self.go(f"#/p/{p.pid}/vocabulary", "document.querySelectorAll('.sc-row').length > 8", "the table for the project")
        sources = b.eval("Object.fromEntries([...document.querySelectorAll('.sc-row')].map((r) => [r.dataset.surface, r.dataset.source]))")
        self.assertEqual(sources["structure"], "default")
        self.assertEqual(sources["teams"], "default")
        self.assertIn("vocabulary", sources)
        self.assertTrue(b.eval("!!document.querySelector('.sc-row a[href^=\"#/\"]')"))
        b.eval("document.querySelector('#vc-scope-h').scrollIntoView(); true")
        for part in ("set-teams", "set-vocab", "set-scope"):                  # each Settings card, on a phone
            self.step(f"settings {part} 390")
            b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 900, "deviceScaleFactor": 1, "mobile": True})
            self.go("#/settings", f"!!document.querySelector('#{part}-h')", part)
            b.eval(f"document.querySelector('#{part}-h').scrollIntoView(); true")
            b.eval(SETTLED)
        self.step("a business owner")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        self.persona("business_owner")
        self.go(f"#/p/{p.pid}/vocabulary", "!!document.querySelector('.vc-view .vc-row')", "the Vocabulary")
        time.sleep(0.4)
        found = hits(visible(b, ".vc-view"), SLOP + JARGON)
        self.go("#/settings", "!!document.querySelector('#set-teams-h')", "Settings")
        found += hits(visible(b, ".tm-holder") + visible(b, ".vc-holder") + visible(b, "#set-scope-h"), SLOP + JARGON)
        self.assertEqual(found, [], json.dumps(found[:10], indent=1))
        self.check()


if __name__ == "__main__":
    unittest.main()
