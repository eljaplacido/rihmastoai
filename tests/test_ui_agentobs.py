"""The Agent sessions view in a real browser (FR-OBS1): headless Chrome over the DevTools protocol, as
tests/test_ui_drive.py drives it, against a hub stand-in on 127.0.0.1 (tests/agentobs_hub_stub.py).

A developer opens an attached project whose module is on: the tab is there, the project is mapped to the hub's
project the page suggests, and the six sections show, each with a link into the hub. Dark and light, 1440 and
390 pixels wide, nothing scrolls sideways and no step leaves a console error, a failed request or a CSP violation.
A business owner sees no such tab; on a project with the module off, Ask Rihma proposes turning it on.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary) or git is missing.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agentobs_hub_stub import PROJECT, HubStub  # noqa: E402
from test_agentobs import DEV, IT, attached, turn_on  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import agentobs  # noqa: E402
from kernel.agentobs import mapping  # noqa: E402
from kernel.store import Factory  # noqa: E402

TABS = "[...document.querySelectorAll('.tabs a')].map((a) => a.getAttribute('href').split('/').pop())"


class UiAgentObsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for an attached repository")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-agentobs-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        self.hub = HubStub().__enter__()
        self.addCleanup(self.hub.__exit__)
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
            b.screenshot(self.shots / f"agentobs-{b.step.replace(' ', '-')}.png")

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
        b.type("#person", DEV)
        b.click(f'label[for="pp-{persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done in the person menu")

    def test_FR_OBS1_AC_10_developers_see_the_view_fit_dark_and_light_at_1440_and_390_and_map_it(self):
        b = self.browser
        p, _ = attached(self.factory, self.tmp)
        turn_on(p)
        agentobs.set_settings(self.factory, url=self.hub.url, person=IT, persona="it")
        self.step("map the project")
        self.sign_in("developer")
        b.eval(f"location.hash = '#/p/{p.pid}/agent_sessions'; true")
        b.wait("!!document.querySelector('#obs-map')", "the mapping card")
        self.assertIn("agent_sessions", b.eval(TABS))
        self.assertEqual(b.eval("document.querySelector('#obs-map').value"), PROJECT)     # suggested
        b.click('[data-key="obs:map-save"]', what="Map the project")
        b.wait("!!document.querySelector('#obs-sessions-h') && !!document.querySelector('.obs-grid .viz')", "the sections")
        self.assertEqual(mapping.current(p)["hub_project"], PROJECT)
        self.assertEqual(p.ledger().of_kind("agentobs_mapped")[-1]["event"]["payload"]["person"], DEV)
        text = b.eval("document.querySelector('.obs-view').textContent")
        for said in ("5 sessions", "Claude Code 3", "2 files", "Chain intact", "derived-on-load", "s-opencode-1",
                     "50%", "npm run cockpit -- install --project"):
            self.assertIn(said, text)
        links = b.eval("[...document.querySelectorAll('.obs-view a[target=_blank]')].map((a) => a.href)")
        self.assertTrue(links and all(h.startswith(self.hub.url) for h in links), links)
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"{scheme} {width}")
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                             "mobile": width < 500})
                b.eval("location.hash = '#/home'; true")
                b.wait("!!document.querySelector('#grid')", "home")
                b.eval(f"location.hash = '#/p/{p.pid}/agent_sessions'; true")
                b.wait(f"!!document.querySelector('.obs-grid .viz') && document.documentElement.dataset.theme === '{scheme}'",
                       f"the view in {scheme} at {width}")
                b.eval("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
                self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, (scheme, width))
                spills = b.eval("[...document.querySelectorAll('.obs-card')].filter((c) => c.scrollWidth > c.clientWidth + 1)"
                                ".map((c) => c.getAttribute('aria-labelledby'))")
                self.assertEqual(spills, [], (scheme, width))
        self.step("a business owner")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        self.persona("business_owner")
        b.eval(f"location.hash = '#/p/{p.pid}/overview'; true")
        b.wait(f"location.hash.includes('/overview') && !!document.querySelector('.tabs') && !{TABS}.includes('agent_sessions')",
               "the project's tabs without Agent sessions")
        b.eval(f"location.hash = '#/p/{p.pid}/agent_sessions'; true")               # its address still says why
        said = b.wait("(document.querySelector('.obs-view .empty') || {}).textContent", "the view's note")
        self.assertIn("for developers and IT", said)
        self.check()

    def test_FR_OBS1_AC_10_ask_rihma_proposes_turning_it_on_and_the_person_confirms(self):
        b = self.browser
        p, _ = attached(self.factory, self.tmp)
        self.step("ask")
        self.sign_in("developer")
        b.eval(f"location.hash = '#/p/{p.pid}/overview'; true")
        b.wait("!!document.querySelector('.tabs')", "the project")
        self.assertNotIn("agent_sessions", b.eval(TABS))                        # off by default
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "Show me the agent sessions")
        b.click("#as-send", what="Send")
        b.wait("!!document.querySelector('#as-log .prop button')", "the proposal")
        self.assertIn("Turn on Agent observability", b.eval("document.querySelector('#as-log .prop').textContent"))
        b.click("#as-log .prop button", text="Confirm", what="Confirm")
        b.wait("(document.querySelector('#as-log .prop') || {}).textContent.includes('Confirmed')", "confirmed")
        self.assertTrue(agentobs.module_on(p))
        self.check()

    def test_FR_OBS1_FR_PPL1_viewing_everything_the_solo_person_sees_the_view_and_sets_the_hub(self):
        """Solo mode, "Viewing as: everything" after business owner was the persona last named: the person holds
        every persona, so the tab, the view, the hub's address (signed as IT) and the mapping are theirs."""
        b = self.browser
        p, _ = attached(self.factory, self.tmp)
        turn_on(p)
        self.step("everything")
        self.sign_in("business_owner")
        self.persona("all")
        b.wait("document.querySelector('#pc-persona').textContent === 'Viewing as: everything'", "Viewing as: everything")
        b.eval(f"location.hash = '#/p/{p.pid}/agent_sessions'; true")
        said = b.wait("(document.querySelector('.obs-view .obs-grid') || document.querySelector('.obs-view .empty') || {}).textContent",
                      "the view")
        self.assertNotIn("switch persona", said)
        self.assertIn("no address is set", b.eval("document.querySelector('.obs-view').textContent"))
        self.assertIn("agent_sessions", b.eval(TABS))
        self.step("the hub's address in Settings")
        b.eval("location.hash = '#/settings'; true")
        b.wait("!!document.querySelector('[data-key=\"obs:save\"]')", "the hub's address card")
        self.assertFalse(b.eval("document.querySelector('[data-key=\"obs:save\"]').disabled"))
        self.assertNotIn("IT sets the hub's address", b.eval("document.querySelector('.obs-settings-holder').textContent"))
        b.eval(f"document.querySelector('#obs-url').value = {self.hub.url!r}; true")
        b.click('[data-key="obs:save"]', what="Save the hub's address")
        b.wait("(document.querySelector('.obs-settings-holder') || {}).textContent.includes('set by')", "the saved address")
        self.assertEqual((agentobs.settings(self.factory)["url"], agentobs.settings(self.factory)["set_by"]),
                         (self.hub.url, DEV))
        self.step("map the project")
        b.eval(f"location.hash = '#/p/{p.pid}/agent_sessions'; true")
        b.wait("!!document.querySelector('[data-key=\"obs:map-save\"]')", "Map the project")
        b.click('[data-key="obs:map-save"]', what="Map the project")
        b.wait("!!document.querySelector('.obs-grid .viz')", "the sections")
        self.assertEqual(mapping.current(p)["hub_project"], PROJECT)
        self.assertEqual(p.ledger().of_kind("agentobs_mapped")[-1]["event"]["payload"]["persona"], "developer")
        self.check()


if __name__ == "__main__":
    unittest.main()
