"""Enforcement made right, in a real browser (FR-ENF2): headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py drives it. GitHub is tests/enforcement_fakes.py FakeGh with a ruleset on main.

A person working alone looks as business owner while a release waits on a card for IT. Both Inboxes say it waits
on a role they also hold and offer to show every role; the Enforcement view lets them decide it in place, signed
as IT, and refuses an approval without a reason. Reading the pipeline names the ruleset; a stage name is placed.
The view fits dark and light at 1440 and 390 pixels with nothing scrolling sideways, and a business owner meets
none of the words words.js keeps from them. No step leaves a console error, a failed request or a CSP violation.
``RIHMA_UI_SHOTS=<folder>`` keeps a screenshot per step.
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
from kernel.canon import Canon  # noqa: E402
from kernel.enforcement_guard import at_deploy  # noqa: E402
from kernel.store import Factory  # noqa: E402

SETTLED = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"


class UiEnforcementFixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-enf2-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        patcher = mock.patch.object(enforcement_pipeline, "gh", FakeGh(protected=False, rulesets=True))
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
            b.screenshot(self.shots / f"enforcement-fix-{b.step.replace(' ', '-')}.png")

    def sign_in(self, persona: str) -> None:
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
        b.eval(f"location.hash = '{route}'; true")
        b.wait(ready, what)

    def world(self):
        p = self.factory.new_project("Order desk")
        ke.set_levels(self.factory, p, levels={"prod": {"security": "enforce"}}, repo=REPO, person="Ilkka",
                      persona="it")
        held = at_deploy(p, "production", 7, {"blocking": ["SEC-1 a secret in the repository"]})
        return p, held["card"]

    def test_FR_ENF2_AC_9_a_solo_owner_finds_and_decides_the_it_card_reads_the_ruleset_and_places_a_name(self):
        b = self.browser
        p, cid = self.world()
        self.step("the project inbox")
        self.sign_in("business_owner")
        self.go(f"#/p/{p.pid}/inbox", "!!document.querySelector('[data-key=ib-elsewhere]')", "the note in the Inbox")
        self.assertIn(cid, b.eval("document.querySelector('[data-key=ib-elsewhere]').textContent"))
        self.assertTrue(b.eval("!!document.querySelector('[data-control=inbox_view_all]')"))
        self.step("all projects inbox")
        self.go("#/inbox", "!!document.querySelector('[data-key=ib-elsewhere]')", "the note in every project's Inbox")
        self.assertIn("IT", b.eval("document.querySelector('[data-key=ib-elsewhere]').textContent"))
        self.step("decide in place")
        self.go(f"#/p/{p.pid}/enforcement", f"!!document.querySelector('[data-key=\"enf-approve:{cid}\"]')",
                "the review waiting, with its decision")
        b.eval(f"document.querySelector('[data-card=\"{cid}\"]').scrollIntoView({{block: 'center'}}); true")
        self.step("decide it")
        b.click(f'[data-key="enf-approve:{cid}"]', what="Let it go on, without a reason")
        b.wait(f"document.querySelector('#enf-why-{cid}').getAttribute('aria-invalid') === 'true'", "the reason asked")
        self.assertEqual(Canon(p).get_card(cid)["state"], "open")
        b.type(f"#enf-why-{cid}", "the secret was rotated")
        b.click(f'[data-key="enf-approve:{cid}"]', what="Let it go on")
        b.wait(f"!document.querySelector('[data-card=\"{cid}\"]')", "the review decided")
        decision = Canon(p).get_card(cid)["decision"]
        self.assertEqual((decision["persona"], decision["person"], decision["reason"]),
                         ("it", PERSON, "the secret was rotated"))
        self.step("read the ruleset")
        b.click('[data-key="enf-read"]', what="Read from GitHub")
        b.wait("(document.querySelector('[data-key=enf-protection]') || {}).textContent", "the main line's protection")
        said = b.eval("document.querySelector('[data-key=enf-protection]').textContent")
        self.assertIn("ruleset Protect main", said)
        self.assertNotIn("none", said)
        self.step("place a name")
        b.type("#enf-name", "eu-west")
        b.eval("const s = document.querySelector('#enf-name-env'); s.value = 'test'; s.dispatchEvent(new Event('change'));"
               " true")
        b.type("#enf-places-reason", "our acceptance region")
        b.click('[data-key="enf-name-save"]', what="Place it")
        b.wait("!!document.querySelector('.enf-names li[data-name=\"eu-west\"]')", "the placed name")
        self.assertEqual(ke.place(self.factory, p, "eu-west")["env"], "test")
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"{scheme} {width}")
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                             "mobile": width < 500})
                self.go(f"#/p/{p.pid}/enforcement", "!!document.querySelector('#enf-places-h')", "the view")
                b.wait(f"document.documentElement.dataset.theme === '{scheme}'", scheme)
                b.eval("document.querySelector('#enf-places-h').scrollIntoView({block: 'start'}); true")
                b.eval(SETTLED)
                self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, (scheme, width))
                spills = b.eval("[...document.querySelectorAll('.enf-view .card')].filter((c) => c.scrollWidth >"
                                " c.clientWidth + 1).map((c) => c.getAttribute('aria-labelledby'))")
                self.assertEqual(spills, [], (scheme, width))
        self.step("words")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        self.go(f"#/p/{p.pid}/enforcement", "!!document.querySelector('#enf-places-h')", "the view")
        time.sleep(0.4)
        found = hits(visible(b, ".enf-view"), SLOP + JARGON)
        self.assertEqual(found, [], json.dumps(found[:10], indent=1))
        self.check()


if __name__ == "__main__":
    unittest.main()
