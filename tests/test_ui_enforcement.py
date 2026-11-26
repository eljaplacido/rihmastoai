"""Enforcement levels in a real browser (FR-ENF1): headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py drives it. GitHub is tests/enforcement_fakes.py FakeGh, patched into the cockpit's process.

A compliance person opens a project's Enforcement view in the Govern capsule, sets production security to hold
until decided, previews and saves it (signed, recorded), reads the pipeline and takes its split into the editor.
The view fits dark and light at 1440 and 390 pixels with nothing scrolling sideways. A fresh project's empty parts
say what would appear and offer Ask Rihma; Settings shows the levels for all projects and the projects that set
their own. A business owner meets none of the words words.js keeps from them. No step leaves a console error, a
failed request or a CSP violation. ``RIHMA_UI_SHOTS=<folder>`` keeps a screenshot per step.
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from enforcement_fakes import REPO, FakeGh  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402
from test_ui_words import JARGON, SLOP, hits, visible  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import enforcement as ke  # noqa: E402
from kernel import enforcement_pipeline  # noqa: E402
from kernel.enforcement_guard import guard  # noqa: E402
from kernel.store import Factory  # noqa: E402

TABS = "[...document.querySelectorAll('.tabs a')].map((a) => a.getAttribute('href').split('/').pop())"
SETTLED = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"


class UiEnforcementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-enf-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        patcher = mock.patch.object(enforcement_pipeline, "gh", FakeGh())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)

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
            b.screenshot(self.shots / f"enforcement-{b.step.replace(' ', '-')}.png")

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

    def open_view(self, pid: str) -> None:
        b = self.browser
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('#grid')", "home")
        b.eval(f"location.hash = '#/p/{pid}/enforcement'; true")
        b.wait("!!document.querySelector('#enf-levels-h') && !!document.querySelector('#enf-outcomes-h')",
               "the Enforcement view")

    def world(self):
        p = self.factory.new_project("Order desk")
        ke.set_levels(self.factory, p, levels={"test": {"governance": "require_review"}}, repo=REPO, person="Ilkka",
                      persona="it")
        guard(p, env="staging", source="deploy", subject="release 1", found={f: [] for f in ke.FAMILIES})
        guard(p, env="production", source="deploy", subject="release 1",
              found={"quality": [], "security": ["check secrets: 1 secret found"], "legal": [], "governance": []})
        return p, self.factory.new_project("Fresh intake")

    def test_FR_ENF1_AC_9_a_person_sets_previews_and_saves_levels_and_reads_the_pipeline_in_chrome(self):
        b = self.browser
        p, fresh = self.world()
        self.step("set a level")
        self.sign_in("compliance")
        self.open_view(p.pid)
        self.assertIn("enforcement", b.eval(TABS))
        self.assertEqual(b.eval("document.querySelector('#enf-p-test-governance').closest('.enf-row')"
                                ".querySelector('[data-scope]').dataset.scope"), "project")
        self.assertEqual(b.eval("document.querySelector('#enf-p-prod-security').value"), "inherit")
        self.assertGreaterEqual(b.eval("document.querySelectorAll('.enf-recent li').length"), 3)
        self.assertEqual(b.eval("document.querySelectorAll('.enf-cards li').length"), 1)
        b.eval("const s = document.querySelector('#enf-p-prod-security'); s.value = 'enforce';"
               " s.dispatchEvent(new Event('change')); true")
        b.click('[data-key="enf-preview-btn"]', what="Preview")
        said = b.wait("(document.querySelector('[data-key=enf-preview]') || {}).textContent", "the preview")
        self.assertIn("1 setting would change.", said)
        b.click('[data-key="enf-save"]', what="Save")
        b.wait("(() => { const s = document.querySelector('#enf-p-prod-security'); return !!s && s.value === 'enforce'"
               " && s.closest('.enf-row').querySelector('[data-scope]').dataset.scope === 'project'; })()",
               "the saved level")
        self.assertEqual(ke.cell(self.factory, p, "prod", "security")["level"], "enforce")
        self.assertEqual(p.ledger().of_kind("enforcement_set")[-1]["event"]["payload"]["person"], PERSON)
        self.step("read the pipeline")
        b.click('[data-key="enf-read"]', what="Read from GitHub")
        b.wait("document.querySelectorAll('.enf-cmp li').length === 3", "the comparison")
        states = b.eval("Object.fromEntries([...document.querySelectorAll('.enf-cmp li')]"
                        ".map((li) => [li.dataset.env, li.dataset.state]))")
        self.assertEqual(states, {"dev": "pipeline_stricter", "test": "rihmasto_stricter", "prod": "agree"})
        b.click('[data-key="enf-take"]', what="Take the pipeline's split")
        b.wait("document.querySelector('#enf-p-dev-governance').value === 'enforce'"
               " && !!document.querySelector('[data-key=enf-preview]')", "the pipeline's split in the editor")
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"{scheme} {width}")
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                             "mobile": width < 500})
                self.open_view(p.pid)
                b.wait(f"document.documentElement.dataset.theme === '{scheme}'", scheme)
                b.eval(SETTLED)
                self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, (scheme, width))
                spills = b.eval("[...document.querySelectorAll('.enf-view .card')].filter((c) => c.scrollWidth >"
                                " c.clientWidth + 1).map((c) => c.getAttribute('aria-labelledby'))")
                wide = b.eval("[...document.querySelectorAll('.enf-view .card *')].filter((e) => e.getBoundingClientRect()"
                              ".right > e.closest('.card').getBoundingClientRect().right + 1).slice(0, 5)"
                              ".map((e) => e.tagName + '.' + e.className + ' ' + (e.id || e.textContent.slice(0, 40)))")
                self.assertEqual(spills, [], (scheme, width, wide))
        self.step("a fresh project")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        self.open_view(fresh.pid)
        for part in ("enforcement_recent", "enforcement_reviews", "enforcement_findings"):
            self.assertTrue(b.eval(f"!!document.querySelector('[data-empty={part}] .empty-how')"), part)
        self.assertEqual(b.eval("document.querySelectorAll('[data-control=enforcement_ask]').length"), 2)
        self.step("settings")
        b.eval("location.hash = '#/settings'; true")
        b.wait("!!document.querySelector('#enf-platform-h') && !!document.querySelector('[data-key=enf-own]')",
               "the platform's levels in Settings")
        self.assertIn("Order desk", b.eval("document.querySelector('[data-key=enf-own]').textContent"))
        self.step("a business owner")
        self.persona("business_owner")
        self.open_view(p.pid)
        time.sleep(0.4)
        found = hits(visible(b, ".enf-view"), SLOP + JARGON)
        b.eval("location.hash = '#/settings'; true")
        b.wait("!!document.querySelector('#enf-platform-h')", "Settings")
        found += hits(visible(b, "#enf-platform-h").copy() + visible(b, ".enf-settings-holder"), SLOP + JARGON)
        self.assertEqual(found, [], json.dumps(found[:10], indent=1))
        self.check()


if __name__ == "__main__":
    unittest.main()
