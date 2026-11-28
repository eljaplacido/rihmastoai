"""Teams, words and what applies where, after an independent check, in a real browser (FR-TM4, FR-TM6, FR-TM7): headless
Chrome over the DevTools protocol, as tests/test_ui_drive.py drives it. Fixtures are invented.

A person working alone meets no word about teams on Settings (their words, one closed list of kinds, one closed list of
where each setting applies, no Rihmasto-itself project to read it for) and their project's settings carry no Team line.
With two teams, a setting kept once per home reads "set for all teams" and a project with no embed says nothing is set
here yet. A requirement called a story reads so on the spec page, in the graph's issue lines and on the board; hiding a
kind leaves the graph whole and says what it left out; the graph across projects says which words it reads in. Every view
fits dark and light at 1440 and 390 pixels with nothing scrolling sideways. No step leaves a console error, a failed request
or a CSP violation. ``RIHMA_UI_SHOTS=<folder>`` keeps a screenshot per step; ``RIHMA_TEAMFIX_UI_PORT`` fixes the port.
"""

import json
import os
import re
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
from test_ui_words import visible  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from factory_fakes import no_local_routing  # noqa: E402
from kernel import structure_policy as sp  # noqa: E402
from kernel import team as kteam  # noqa: E402
from kernel import teams, vocab_edit  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

SETTLED = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"
THEMES = (("dark", 1440), ("dark", 390), ("light", 1440), ("light", 390))
IT = {"person": PERSON, "persona": "it"}


class UiTeamFixTest(unittest.TestCase):
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
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-tf-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home", clock=FixedClock())
        kteam.name_solo(self.factory, PERSON)
        self.server, self.bootstrap = make_server(self.factory, int(os.environ.get("RIHMA_TEAMFIX_UI_PORT") or 0),
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
            b.screenshot(self.shots / f"teamfix-{b.step.replace(' ', '-')}.png")

    def sign_in(self, persona: str = "it") -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
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

    def size(self, scheme: str, width: int) -> None:
        b = self.browser
        b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                     "mobile": width < 500})

    def fits(self, root: str, what: str) -> None:
        b = self.browser
        b.eval(SETTLED)
        self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, what)
        spills = b.eval(f"[...document.querySelectorAll({json.dumps(root + ' .card')})].filter((c) => c.scrollWidth >"
                        " c.clientWidth + 1).map((c) => c.getAttribute('aria-labelledby'))")
        self.assertEqual(spills, [], (what, spills))

    def said(self, root: str) -> str:
        return " ".join(t for t, _ in visible(self.browser, root))

    def test_FR_TM7_AC_1_a_person_working_alone_meets_no_word_about_teams_on_settings_or_in_their_project(self):
        b = self.browser
        p = every_kind(self)
        factory_project(self.factory, True)                    # Rihmasto's own records exist, as in a home in use
        self.step("solo settings")
        self.sign_in("it")
        for scheme, width in THEMES:
            self.step(f"solo {scheme} {width}")
            self.size(scheme, width)
            self.go("#/settings", "!!document.querySelector('#set-vocab-h') && !!document.querySelector('[data-key=sc-fold]')",
                    "the Words card and the closed What applies where")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", scheme)
            self.assertEqual(b.eval("document.querySelector('[data-id=vocab_team] details.vc-part[data-part=kind]').open"), False)
            self.assertEqual(b.eval("document.querySelector('[data-key=sc-fold]').open"), False)
            self.assertIn("Your words", self.said("[data-id=vocab_team]"))
            self.assertNotRegex(self.said("[data-id=vocab_team]") + " " + self.said("[data-id=scope_view]"), r"(?i)\bteams?\b")
            self.fits("#main", f"solo settings {scheme} {width}")
            b.eval("document.querySelector('#set-vocab-h').scrollIntoView(); true")        # the card the screenshot is of
        self.step("solo what applies where open")
        self.size("dark", 1440)
        self.go("#/settings", "!!document.querySelector('[data-key=sc-fold]')", "What applies where")
        b.click("[data-key=sc-fold] summary", what="the closed list of where each setting applies")
        b.wait("document.querySelectorAll('[data-id=scope_view] .sc-row').length > 8", "the rows")
        text = self.said("[data-id=scope_view]")
        self.assertNotRegex(text, r"(?i)\bteams?\b")
        self.assertIn("all projects", text.lower())
        self.assertEqual(b.eval("[...document.querySelectorAll('[data-id=scope_view] .sc-row')].some((r) => r.dataset.surface === 'teams')"),
                         False)
        options = b.eval("[...document.querySelectorAll('[data-key=sc-project] option')].map((o) => o.value)")
        self.assertIn(p.pid, options)
        self.assertNotIn("_factory", options)                   # Rihmasto's own records are not a project to read it for
        b.eval("document.querySelector('#set-scope-h').scrollIntoView(); true")
        self.step("solo project settings")
        self.go(f"#/p/{p.pid}/overview", "!!document.querySelector('[data-control=project_settings]')", "the project")
        b.click("[data-control=project_settings]", what="Project settings")
        b.wait("!!document.querySelector('.chg-team')", "the Team field's place")
        b.wait("getComputedStyle(document.querySelector('.chg-team')).display === 'none'", "no Team line for one person")
        self.check()

    def test_FR_TM4_AC_8_with_two_teams_a_setting_kept_once_per_home_reads_all_teams_and_none_made_reads_none(self):
        b = self.browser
        p = every_kind(self)
        other = self.new(title="Orders")
        platform = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        teams.move_project(self.factory, other, platform, **IT)
        sp.set_levels(self.factory, None, {"layout": "off"}, reason="our layout", kind="built", **IT)
        self.sign_in("it")
        for scheme, width in THEMES:
            self.step(f"two teams {scheme} {width}")
            self.size(scheme, width)
            self.go("#/settings", "!!document.querySelector('#set-scope-h') && document.querySelectorAll('[data-id=scope_view] .sc-row').length > 8",
                    "What applies where")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", scheme)
            self.assertIsNone(b.eval("document.querySelector('[data-key=sc-fold]')"))        # more than one person: not folded
            chips = b.eval("Object.fromEntries([...document.querySelectorAll('[data-id=scope_view] .sc-row')].map((r) =>"
                           " [r.dataset.surface, r.querySelector('.chip').textContent.trim()]))")
            self.assertEqual(chips["structure"], "set for all teams")
            self.assertEqual(chips["embeds"], "made on each project")              # no project chosen: set on each
            self.fits("#main", f"two teams settings {scheme} {width}")
            b.eval("document.querySelector('#set-scope-h').scrollIntoView(); true")        # the card the screenshot is of
        self.step("a project in the second team")
        self.size("dark", 1440)
        self.go("#/settings", "!!document.querySelector('[data-key=sc-project]')", "the project chooser")
        b.eval(f"const s = document.querySelector('[data-key=sc-project]'); s.value = {json.dumps(other.pid)};"
               " s.dispatchEvent(new Event('change')); true")
        b.wait("document.querySelector('[data-id=scope_view] [data-surface=embeds] .chip').textContent.includes('nothing set here yet')",
               "the Orders project's rows")
        rows = b.eval("Object.fromEntries([...document.querySelectorAll('[data-id=scope_view] .sc-row')].map((r) =>"
                      " [r.dataset.surface, r.querySelector('.chip').textContent.trim()]))")
        self.assertEqual(rows["structure"], "set for all teams")                   # both teams share the one document
        self.assertEqual(rows["teams"], "this project is in Platform")
        self.assertEqual(rows["runners"], "shipped default")
        self.assertNotIn("from the team", json.dumps(rows))
        self.assertNotIn("overrides the team", self.said("[data-id=scope_view]"))
        b.eval("document.querySelector('#set-scope-h').scrollIntoView(); true")
        del p
        self.check()

    def test_FR_TM6_AC_11_the_word_in_force_reads_on_the_spec_the_graph_and_the_board_and_hiding_leaves_the_graph_whole(self):
        b = self.browser
        p = every_kind(self)
        other = self.new(title="Orders")
        for term, label in (("kind:requirement", "Story"), ("kind:test", "Check")):
            vocab_edit.set_term(self.factory, "project", p.pid, term=term, fields={"label": label}, **IT)
        self.sign_in("it")
        for scheme, width in THEMES:
            self.step(f"story {scheme} {width}")
            self.size(scheme, width)
            self.go(f"#/p/{p.pid}/spec", "!!document.querySelector('#view-title')", "the spec page")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", scheme)
            time.sleep(0.5)
            text = self.said("#main")
            self.assertRegex(text, r"(?i)\bstor(?:y|ies)\b")
            self.assertNotRegex(text, r"(?i)\brequirements?\b", "a view still says the shipped word for the kind")
            self.fits("#main", f"spec {scheme} {width}")
            self.go(f"#/p/{p.pid}/graph", "!!document.querySelector('.gv-sum')", "the graph")
            lines = self.said(".gv-sum")
            self.assertRegex(lines, r"(?i)\bstor(?:y|ies)\b")
            self.assertNotRegex(lines, r"(?i)\brequirements?\b")
            self.fits("#main", f"graph {scheme} {width}")
        self.step("the board filter")
        self.size("dark", 1440)
        self.go(f"#/p/{p.pid}/board", "!!document.querySelector('#view-title')", "the board")
        time.sleep(0.5)
        board = self.said("#main")
        self.assertRegex(board, r"(?i)\bstor(?:y|ies)\b")                      # the epics and the capsule say the kind
        self.assertNotRegex(board, r"(?i)\brequirements?\b")
        self.step("hidden kind")
        vocab_edit.set_term(self.factory, "project", p.pid, term="kind:requirement", fields={"hidden": True}, **IT)
        self.go(f"#/p/{p.pid}/graph", "!!document.querySelector('[data-key=gv-hidden]')", "the note on what the hidden kind left out")
        note = b.eval("document.querySelector('[data-key=gv-hidden]').textContent")
        self.assertIn("hidden kind", note)
        self.assertRegex(note, r"warning")
        counts = re.search(r"(\d+) nodes · (\d+) match · (\d+) shown", self.said(".gv-sum"))
        self.assertEqual(counts.group(1), counts.group(2))                          # what is counted is what is drawn
        self.assertEqual(counts.group(2), counts.group(3))
        self.step("the page across projects")
        vocab_edit.set_term(self.factory, "project", p.pid, term="kind:requirement", fields={"hidden": None, "label": "Story"},
                            **IT)
        self.go("#/graph", "!!document.querySelector('[data-key=gv-mixed]')", "the note on which words the page reads in")
        self.assertIn("say some words differently", b.eval("document.querySelector('[data-key=gv-mixed]').textContent"))
        del other
        self.check()


if __name__ == "__main__":
    unittest.main()
