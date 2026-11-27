"""FR-BIZ1 in a real browser (headless Chrome over the DevTools protocol), on the demo home the business acceptance
test used. A business owner reads Home's project health and track rows (one Why per row, the row whole, a project
in shaping not "all build work done"); the webhook's Evidence controls name the scan; its People in the loop keeps
a level set for all projects in that scope and says a link meant for email was copied by hand, in local time; its
Inbox never says nothing blocks while an answer holds delivery; Home's activity shows the answer from outside; as
Compliance, Home lists the ask waiting on them; Decide what matters lands on the assumption, which shows its weight;
the adopted service's business lens says its risks are not assessed, and at 390 px nothing scrolls sideways; team
mode shows at once, and a start that cannot read the cockpit says so with Try again. Dark at 1440 px, light at
390 px; after every step no console error, failed request or CSP violation. Skipped without Chrome or git."""

import contextlib
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_hitl_ui  # noqa: E402  (its helpers; imported as a module so its own test is not run twice)
from test_ui_drive import PERSON, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import hitl, hitl_links, roads  # noqa: E402
from kernel.store import Factory  # noqa: E402

AINO = {"person": "Aino Example", "persona": "business_owner"}


class BusinessUiTest(test_hitl_ui.LoopUiTest):
    test_FR_HITL1_AC_8_one_asks_gives_a_link_and_the_person_outside_answers_dark_light_wide_narrow = None   # its own

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-biz-")).resolve()
        try:
            build_demo(cls.tmp / "demo", echo=lambda line: None)
        except Exception:
            roads.stop_started()
            roads.rmtree(cls.tmp)
            raise
        cls.factory = Factory(cls.tmp / "demo")
        by = {p.meta.get("title"): p for p in cls.factory.projects()}
        cls.webhook, cls.stock = by["Shipment webhook to the stock system"], by["Stock levels service"]
        cls.project = cls.webhook
        p = cls.webhook
        hitl.set_level(p, "governance", "require", **AINO)
        hitl.ask(p, text="May the pilot start on Monday?", kind="decision", family="governance",
                 options=["Yes", "No"], **AINO)
        hitl.ask(p, text="May we keep the loan history for two years?", family="legal", **AINO)
        hitl_links.create(p, name="Maria Example", persona="compliance", asks=["HQ-002"], person="Aino Example",
                          creator_persona="business_owner", channel="email", address="maria@example.org")
        hitl.ask(p, text="Is the retry window right?", family="quality", to_persona="compliance", **AINO)
        link = hitl_links.create(p, name="Olli Example", persona="compliance", asks=["HQ-003"],
                                 person="Aino Example", creator_persona="business_owner")
        hitl_links.answer(cls.factory, next(r for r in hitl_links.links(cls.factory) if r["id"] == link["id"]),
                          "HQ-003", "Yes, five minutes is right")
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        roads.stop_started()

    def go(self, hash_: str, ready: str, what: str) -> None:
        self.browser.cmd("Page.navigate", {"url": f"{self.server.origin}/{hash_}"})
        self.browser.wait(ready, what)

    def persona(self, pid: str) -> None:
        b = self.browser
        b.click("#person-chip", what="the person chip")
        b.click(f'label[for="pp-{pid}"]', what=pid)
        b.click("#pp-done", what="Done in the person menu")

    def rows(self, widget: str) -> list:
        return self.browser.eval(
            f"[...document.querySelectorAll('.widget[data-type=\"{widget}\"] .health-row')].map((r) => ({{"
            " t: r.textContent, why: r.querySelectorAll('.nvl-why').length, cols: r.children.length }))")

    @contextlib.contextmanager
    def part(self, name: str):
        """One finding's check: a failure is reported and the next part still runs, from its own page."""
        with self.subTest(name):
            self.step(name)
            yield

    def test_FR_BIZ1_AC_11_what_the_business_acceptance_test_found_in_the_browser_dark_light_wide_narrow(self):
        b, pid = self.browser, self.webhook.pid
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        with self.part("Home: one Why per health and track row, the row whole, shaping not done"):
            b.wait("document.querySelectorAll('.widget .health-row .nvl-why').length > 0", "the Why buttons")
            for widget in ("health", "track"):
                rows = self.rows(widget)
                self.assertTrue(rows, widget)
                for r in rows:
                    self.assertLessEqual(r["why"], 1, (widget, r["t"]))
                    self.assertEqual(r["cols"], 3, (widget, r["t"]))
            loans = next(r for r in self.rows("health") if "Equipment loans" in r["t"])
            self.assertNotIn("All build work is done", loans["t"])
            self.assertIn("Nothing to build yet", loans["t"])
        with self.part("Home: the activity shows the answer from outside"):
            act = b.wait("(document.querySelector('.widget[data-type=\"activity\"]') || {}).textContent", "activity")
            self.assertIn("answered HQ-003, from outside via RL-002", act)
            self.assertIn("Compliance, from outside", act)
            self.fits()
        with self.part("Evidence: the controls name the scan the pack names"):
            self.go(f"#/p/{pid}/evidence", "!!document.querySelector('.controls table')", "the Controls table")
            controls = b.eval("document.querySelector('.controls').textContent")
            self.assertIn("the latest scan by", controls)
            self.assertNotIn("no security scan yet", controls)
            self.fits()
        with self.part("the Inbox never says nothing blocks while an answer holds delivery"):
            self.go(f"#/p/{pid}/inbox", "!!document.querySelector('.hl-held')", "what holds delivery")
            body = b.eval("document.querySelector('.view-body').textContent")
            self.assertNotIn("Nothing blocks work right now.", body)
            self.fits()
        with self.part("People in the loop: a level for all projects keeps its scope; a link not emailed says so"):
            self.open_loop()
            self.choose("#hl-lv-legal", "require")
            self.choose("#hl-sc-legal", "platform")
            b.click('[data-control="hitl_enforce"][aria-label="Set Legal"]', what="Set Legal")
            b.wait("(document.querySelector('#hl-sc-legal') || {}).value === 'platform' && document.querySelector"
                   "('#hl-sc-legal').closest('li').textContent.includes('Set for all projects')",
                   "the scope, where the level lives")
            row = b.wait("(document.querySelector('[data-link=\"RL-001\"]') || {}).textContent", "the link row")
            self.assertIn("email not sent: copied by hand", row)
            self.assertNotIn("by email", row)
            self.assertNotRegex(row, r"until \d{4}-\d\d-\d\d \d\d:\d\d")          # no bare UTC stamp
            self.fits()
        with self.part("Decide what matters lands on the assumption, which shows its weight"):
            self.go(f"#/p/{pid}/triage", "!!document.querySelector('.nvl-view .card')", "Decide what matters")
            grew = b.wait("(document.querySelector('[data-control=\"assumption_grew\"]') || {getAttribute: () => ''})"
                          ".getAttribute('href')", "an assumption that grew in importance")
            aid = grew.rsplit("/", 1)[-1]
            self.assertRegex(aid, r"^A-\d+$")                                   # the link names the assumption
            b.click('[data-control="assumption_grew"]', what="Confirm or correct it")
            b.wait(f"(document.querySelector('tr[data-id=\"{aid}\"]') || {{classList: {{contains: () => false}}}})"
                   ".classList.contains('focused')", "the assumption, focused")
            weight = b.eval(f"document.querySelector('[data-weight=\"{aid}\"]').textContent")
            self.assertRegex(weight, r"^\d+")
            self.assertTrue("Grew in importance" in weight or "Blocks the next step" in weight, weight)
            self.fits()
        with self.part("Home as Compliance lists the ask waiting on them"):
            self.go("#/home", "!!document.querySelector('#grid .widget')", "Home")
            self.persona("compliance")
            dec = b.wait("(document.querySelector('.widget[data-type=\"decisions\"]') || {}).textContent", "Decisions")
            self.assertIn("May we keep the loan history for two years?", dec)
            self.assertIn("May the pilot start on Monday?", dec)
            self.fits()
        with self.part("the adopted service's business lens: risks not assessed; narrow, light, nothing sideways"):
            self.persona("business_owner")
            self.theme("light", "Light")
            self.size(390, 844)
            self.go(f"#/p/{self.stock.pid}/overview", "!!document.querySelector('[data-lens=\"biz\"]')", "the lenses")
            b.click('[data-lens="biz"]', what="Goal and business impact")
            said = b.wait("(document.querySelector('[data-lens-risks=\"not-assessed\"]') || {}).textContent", "risks")
            self.assertIn("Not assessed yet", said)
            self.assertNotIn("No serious finding", b.eval("document.querySelector('.lens-body').textContent"))
            self.fits()
            self.size(1440, 1000)
        with self.part("team mode shows at once"):
            self.go("#/settings", "!!document.querySelector('[data-control=\"people_mode\"]')", "People and access")
            b.click('[data-control="people_mode"]', what="Turn on team mode")
            b.wait("document.querySelector('#access-note-text').textContent.startsWith('team: signed in as')",
                   "the top bar, at once")
        with self.part("a start that cannot read the cockpit says so, with Try again"):
            b.cmd("Network.enable")
            b.cmd("Network.setBlockedURLs", {"urls": ["*/api/personas*"]})
            b.cmd("Page.reload")
            b.wait("!!document.querySelector('[data-start-failed]')", "the start failure, said")
            b.cmd("Network.setBlockedURLs", {"urls": []})
            b.problems.clear()                                    # the blocked requests were this step's own doing
            b.click('[data-key="start-again"]', what="Try again")
            b.wait("!document.querySelector('[data-start-failed]')"
                   " && document.querySelectorAll('#sidebar a').length > 0"
                   " && !!document.querySelector('[data-control=\"people_mode\"]')", "the cockpit, signed in")
            self.assertEqual(b.eval("document.querySelector('#pc-name').textContent"), PERSON)
        self.check()


if __name__ == "__main__":
    unittest.main()
