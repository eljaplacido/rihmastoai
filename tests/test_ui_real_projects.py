"""FR-RPJ1-AC-16: real projects of every shape fed in through New project, in a real browser (headless Chrome).

Neutral folders that mimic each shape (tests/rpj_fixture.py) go through New project > An existing project >
scan, as a person would: a documents-only experiment with a results.zip (tracked and evaluated), a repository
with uncommitted work and its AI tools' skills (the working copy instead of the last commit; confidential, with
the one-click local model), a workspace of two repositories and a copy (adopted each as its own project), a long
scan (its progress, then Cancel), a folder outside the allowed ones (Allow it, then the scan), and a game-like
repository adopted already (Open it, or adopt it again). Its project page shows the kind, the adopted state
instead of the stages, the failed baseline as health, the Areas card, the watch and the stated command. Light
and dark, 1440 and 390 px wide: nothing scrolls sideways, and there is no console error, failed request or CSP
violation.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary).
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import rpj_fixture as fx  # noqa: E402
from factory_fakes import isolated_routing  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import adopt, material  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402
from kernel.store import Factory  # noqa: E402

SUBMIT = "form.np-form button[type=submit]"
SLOW = 0.02          # seconds per file opened: a long scan has something to show


class UiRealProjectsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-rpj-")).resolve()
        inside = cls.tmp / "in"
        reading = material.Progress.reading

        def slow(self, rel):
            time.sleep(SLOW * (4 if rel.startswith("part-") else 1))      # the big folder: long enough to cancel
            return reading(self, rel)
        cls.patches = [mock.patch.dict(os.environ, {ROOTS_ENV: str(inside)}),
                       mock.patch("pathlib.Path.home", return_value=cls.tmp / "me"),
                       mock.patch.object(material.Progress, "reading", slow)]
        for p in cls.patches:
            p.start()
        cls.exp = fx.experiment(inside / "buoy-experiment")
        cls.ledger = fx.uncommitted(inside / "ledger-helper")
        cls.ws = fx.workspace(inside / "harbour")
        cls.big = inside / "big-archive"
        for n in range(400):
            fx._write(cls.big, {f"part-{n // 50}/note-{n}.md": f"# Note {n}\n\nA line about {n}.\n"})
        cls.outside = fx.notes(cls.tmp / "elsewhere" / "vault")
        cls.factory = Factory(cls.tmp / "home")
        cls.factory.new_project("Unsorted work")              # a project whose kind is not chosen yet
        cls.game_src = fx.game(inside / "lantern-isles")
        cls.game = adopt.adopt(cls.factory, "Lantern Isles", source=str(cls.game_src), intent="monitor",
                               person=PERSON, persona="developer", suite_timeout=120)
        cls.runner = QuietRunner()
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        for p in cls.patches:
            p.stop()
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        isolated_routing(self, self.tmp)               # the one-click local model writes a temp overlay
        self.browser = Browser(self.chrome, self.tmp / f"chrome-{int(time.time() * 1000)}")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    # -- the walk's helpers ------------------------------------------------------------------------------

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
        self.shot(b.step)

    def shot(self, name: str) -> None:
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.browser.screenshot(self.shots / f"rpj-{name.replace(' ', '-')}.png")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000 if px > 500 else 900,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})
        self.browser.wait(f"window.innerWidth === {px}", f"a {px} px wide page")

    def theme(self, word: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def dialog(self, title: str) -> None:
        b = self.browser
        if b.eval("!!document.querySelector('form.np-form')"):           # the last dialog, still open
            b.key("Escape", 27)
            b.wait("!document.querySelector('form.np-form')", "the dialog closed")
        b.eval("location.hash = '#/projects'; true")
        b.click('[data-control="new_project"]', text="New project", what="New project")
        b.wait("!!document.querySelector('form.np-form')", "the New project dialog")
        b.click('[data-key="np-start:existing"]', what="Start from: An existing project")
        b.type('form.np-form input[aria-label="Title"]', title)

    def scan(self, folder: Path, wait: str = ".scan-step:not([hidden]) .scan-group") -> None:
        b = self.browser
        b.type('[data-control="adopt_project"]', str(folder))
        b.wait(f"document.querySelector('{SUBMIT}').textContent.trim() === 'Scan the folder'", "Scan the folder")
        b.click(SUBMIT, what="Scan the folder")
        b.wait(f"!!document.querySelector({json.dumps(wait)})", "the scan's result")

    def text(self) -> str:
        return self.browser.eval("document.querySelector('.scan-step').textContent")     # closed groups too

    def label(self) -> str:
        return self.browser.eval(f"document.querySelector('{SUBMIT}').textContent.trim()")

    def fits(self, px: int, sel: str = "form.np-form") -> None:
        b = self.browser
        sizes = b.eval(f"""(() => {{ const f = document.querySelector({json.dumps(sel)});
            return {{page: document.documentElement.scrollWidth, box: f ? [f.scrollWidth, f.clientWidth] : [0, 0]}}; }})()""")
        self.assertLessEqual(sizes["page"], px, sizes)
        self.assertLessEqual(sizes["box"][0], sizes["box"][1], sizes)

    def both_widths(self, name: str, sel: str = "form.np-form", top: str = ".scan-step .feed-note, .scan-step") -> None:
        look = f"(() => {{ const el = document.querySelector({json.dumps(top)}); el && el.scrollIntoView({{block: 'start'}}); return true; }})()"
        self.fits(1440, sel)
        self.browser.eval(look)
        self.shot(name + "-1440")
        self.width(390)
        self.fits(390, sel)
        self.browser.eval(look)
        self.shot(name + "-390")
        self.width(1440)

    # -- the walk -----------------------------------------------------------------------------------------

    def test_FR_RPJ1_AC_16_real_projects_of_every_shape_through_new_project(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.theme("Light")
        self.documents_only()
        self.uncommitted_and_confidential()
        self.workspace()
        self.long_scan_and_cancel()
        self.theme("Dark")
        self.outside_allowed()
        self.adopted_already_and_its_page()
        self.step("done")
        self.assertEqual(b.problems, [])

    def documents_only(self) -> None:
        b = self.browser
        self.step("documents only")
        self.dialog("Buoy experiment")
        self.scan(self.exp)
        said = self.text()
        for words in ("This folder holds documents only.", "Track and evaluate this work",
                      "Build something from these documents", "8 housekeeping files", "results.zip!/results/report.md"):
            self.assertIn(words, said)
        self.assertNotIn(".gitattributes", said)                     # counted, never listed one by one as read
        self.assertTrue(b.eval(f"document.querySelector('{SUBMIT}').disabled"))
        b.click('[data-control="scan_track"]', what="Track and evaluate this work")
        b.wait(f"document.querySelector('{SUBMIT}').textContent.trim() === 'Track this work'", "Track this work")
        self.assertEqual(b.eval("document.querySelector('[data-key=\"np-usage:explore\"]').getAttribute('aria-checked')"),
                         "true")
        self.both_widths("documents")
        b.click(SUBMIT, text="Track this work", what="Track this work")
        b.wait("location.hash === '#/jobs'", "the Jobs page")
        args = self.runner.started[-1]
        self.assertIn("--documents", args)
        self.assertEqual(args[args.index("--intent") + 1], "monitor")
        self.assertEqual(args[args.index("--maturity") + 1], "explore")

    def uncommitted_and_confidential(self) -> None:
        b = self.browser
        self.step("uncommitted work")
        self.dialog("Ledger helper")
        b.click('label[for="np-confidential"]', what="Confidential")
        self.scan(self.ledger)
        said = self.text()
        self.assertIn("1 uncommitted change (and 2 untracked files) are not in the last commit", said)
        self.assertIn("They will not be included", said)
        self.assertNotIn("draft.md", said)
        self.assertIn("SKILL.md", said)
        self.assertIn("Adopting works (it calls no model). These roles would be refused until they use a local model",
                      said)
        self.both_widths("uncommitted")
        b.click('[data-key="np-take:working_copy"]', what="Adopt the working copy as it is now")
        b.wait("document.querySelector('.scan-step').innerText.includes('draft.md')", "the working copy's map")
        self.step("one-click local model")
        b.click('[data-control="use_local_model"]', what="Use my local model for these roles")
        b.wait("[...document.querySelectorAll('#status .toast')].some((t) => /now use/.test(t.textContent))",
               "the local model in use")
        b.wait("(() => { const t = document.querySelector('.scan-step').textContent;"
               " return t.includes('verifier (the hosted endpoint') && !t.includes('analyst (the hosted'); })()",
               "the scan again, with only the verifier left hosted")
        b.click(SUBMIT, text="Adopt the project", what="Adopt the project")
        b.wait("location.hash === '#/jobs'", "the Jobs page")
        args = self.runner.started[-1]
        self.assertIn("--working-copy", args)
        self.assertIn("--confidential", args)

    def workspace(self) -> None:
        b = self.browser
        self.step("a workspace")
        self.dialog("Harbour")
        self.scan(self.ws)
        said = self.text()
        self.assertIn("A workspace of 2 git repositories", said)
        self.assertIn("the same text as harbour-app/docs/plan.md: read once", said)
        b.click('[data-key="np-ws:each"]', what="Adopt each as its own project")
        b.wait("!!document.querySelector('input[data-repo=\"harbour-tools\"]')", "the repositories")
        b.wait(f"document.querySelector('{SUBMIT}').textContent.trim() === 'Adopt 2 projects'", "Adopt 2 projects")
        self.both_widths("workspace")
        before = len(self.runner.started)
        b.click(SUBMIT, text="Adopt 2 projects", what="Adopt 2 projects")
        b.wait("location.hash === '#/jobs'", "the Jobs page")
        started = self.runner.started[before:]
        self.assertEqual([a[3] for a in started], ["Harbour · harbour-app", "Harbour · harbour-tools"])

    def long_scan_and_cancel(self) -> None:
        b = self.browser
        self.step("a long scan")
        self.dialog("Big archive")
        b.type('[data-control="adopt_project"]', str(self.big))
        b.click(SUBMIT, text="Scan the folder", what="Scan the folder")
        b.wait("/files looked at/.test(document.querySelector('.scan-sum').textContent)", "the scan's progress")
        self.assertIn(" s", b.eval("document.querySelector('.scan-progress').textContent"))
        self.shot("long-scan-progress")
        b.click('[data-control="scan_cancel"]', what="Cancel the scan")
        b.wait("document.querySelector('.scan-step').innerText.includes('You cancelled the scan')", "the cancelled scan")
        self.shot("long-scan-cancelled")
        b.key("Escape", 27)
        b.wait("!document.querySelector('form.np-form')", "the dialog closed")

    def outside_allowed(self) -> None:
        b = self.browser
        self.step("a folder outside")
        self.dialog("Vault")
        self.scan(self.outside, wait=".scan-error")
        self.assertIn("The folder was not scanned", self.text())
        self.assertNotIn("Scanning the folder", b.eval("document.querySelector('.scan-sum').textContent"))
        self.both_widths("outside")
        b.click('[data-control="allow_root"]', what="Allow the folder")
        b.click('[data-control="allow_root_yes"]', what="Yes, allow it")
        b.wait("!!document.querySelector('.scan-step .scan-group')", "the scan, once allowed")
        self.assertIn("Not a git repository", self.text())

    def adopted_already_and_its_page(self) -> None:
        b = self.browser
        self.step("adopted already")
        self.dialog("Lantern Isles")
        self.scan(self.game_src)
        said = self.text()
        self.assertIn("Already adopted as Lantern Isles", said)
        self.assertIn("a game engine's or 3D tool's file", said)
        self.assertTrue(b.eval(f"document.querySelector('{SUBMIT}').disabled"))
        self.both_widths("adopted-already-said")
        b.click('[data-control="adopt_again"]', what="Adopt it again as a new project")
        b.wait(f"!document.querySelector('{SUBMIT}').disabled && document.querySelector('{SUBMIT}').textContent.trim()"
               " === 'Adopt it again'", "Adopt it again")
        self.both_widths("adopted-already")
        b.key("Escape", 27)
        b.wait("!document.querySelector('form.np-form')", "the dialog closed")
        self.step("the adopted project's page")
        b.eval(f"location.hash = '#/p/{self.game.pid}/overview'; true")
        b.wait("!!document.querySelector('.adopted-line') && !!document.querySelector('.areas-tbl')", "the adopted page")
        head = b.eval("document.querySelector('.proj-head').innerText")
        self.assertIn("Game", head)
        self.assertIn("Adopted: monitoring", head)
        self.assertNotIn("Stage 7 of 7", b.eval("document.body.innerText"))
        self.assertFalse(b.eval("!!document.querySelector('.proj-head .stepper')"))
        self.assertIn("existing tests fail at the baseline", b.eval(
            "[...document.querySelectorAll('.proj-head .chip')].map((c) => c.getAttribute('tip') || '').join(' ')"
            " + document.querySelector('.health').innerText"))
        self.assertIn("assets", b.eval("document.querySelector('.areas-tbl').innerText"))
        self.assertIn("python tools/pipeline/check.py test", b.eval("document.querySelector('#adopted-stated-h')"
                                                                    ".closest('.card').innerText"))
        b.click('[data-control="watch_setup"]', what="Set up the watch")
        b.wait("/Watching: new commits/.test(document.querySelector('#adopted-watch-h').closest('.card').innerText)",
               "the watch line")
        self.both_widths("adopted-page", "#main", ".proj-head")
        self.both_widths("adopted-areas", "#main", "#adopted-areas-h")
        self.theme("Light")
        self.both_widths("adopted-page-light", "#main", ".proj-head")
        self.width(390)
        b.eval("location.reload(); true")              # a page opened at phone width, not a desktop one narrowed
        b.wait("!!document.querySelector('.adopted-line') && !!document.querySelector('.areas-tbl')", "the page again")
        self.fits(390, "#main")
        self.shot("adopted-page-390-fresh")
        b.eval("document.querySelector('#adopted-areas-h').scrollIntoView({block: 'start'}); true")
        self.shot("adopted-areas-390-fresh")
        self.width(1440)
        self.step("a kind not chosen yet")
        unsorted = next(p for p in self.factory.projects() if p.meta.get("title") == "Unsorted work")
        b.eval(f"location.hash = '#/p/{unsorted.pid}/overview'; true")
        b.wait("!!document.querySelector('[data-control=\"kind_not_chosen\"]')", "Kind: not chosen yet")
        self.assertIn("Kind: not chosen yet", b.eval("document.querySelector('.proj-head').innerText"))


if __name__ == "__main__":
    unittest.main()
