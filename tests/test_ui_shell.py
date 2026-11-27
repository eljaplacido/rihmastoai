"""The shell after the owner's feedback of 2026-11-24/25 (FR-UXO1), in a real browser.

Scope is unmistakable (all projects, or one project with its accent, its name in the scope bar and its own sidebar);
a project's views are grouped into five capsules with their own short rows, opened per persona; an Inbox card says
what it wants, offers choices with their meanings, asks why only after a choice, and keeps commenting apart; the
Delivery square explains itself, switches between all projects and one, and its lane counts open their items; Ask
Rihma says what it talks about, switches when a question names another project, and answers a how-to with filled-in
steps and the action; Customize works on any view and on a capsule's tabs; and every top-level page and capsule fits
1440 and 390 pixels in dark and light with no console error and no sideways scroll.

It drives headless Chrome over the DevTools protocol on the demo home of ``test_ui_drive`` (skipped the same way when
Chrome or git is missing). ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_drive as drive  # noqa: E402  (the module, so its TestCase is not collected here again)

from kernel.canon import Canon  # noqa: E402

PERSON = drive.PERSON
HASH_VIEW = "location.hash.split('/')[3] || ''"
CAP_ON = "(document.querySelector('.cap-t.on') || {dataset: {}}).dataset.capsule"
FITS = "document.documentElement.scrollWidth <= innerWidth + 1 && document.body.scrollWidth <= innerWidth + 1"
PAGES = ["home", "square", "catalogue", "projects", "inbox", "insights", "floor", "jobs", "automations", "health",
         "review", "agents", "settings"]


class UiShellTest(unittest.TestCase):
    setUpClass = classmethod(drive.UiDriveTest.setUpClass.__func__)
    tearDownClass = classmethod(drive.UiDriveTest.tearDownClass.__func__)
    setUp = drive.UiDriveTest.setUp
    step = drive.UiDriveTest.step
    check = drive.UiDriveTest.check
    project = drive.UiDriveTest.project

    def sign_in(self, persona: str = "business_owner") -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.server.issue_link(600)}"})   # one link per test
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid .widget')",
               "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what=persona)
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def go(self, where: str, ready: str) -> None:
        self.browser.eval(f"location.hash = {json.dumps(where)}; true")
        self.browser.wait(ready, where)

    def open_project(self, pid: str, view: str = "") -> None:
        target = f"#/p/{pid}" + (f"/{view}" if view else "")
        if self.browser.eval(f"location.hash === {json.dumps(target)}"):
            self.go("#/projects", "!!document.querySelector('.proj-card')")   # the same address does not route again
        self.browser.eval("(() => { const v = document.querySelector('.view-body'); if (v) v.dataset.view = ''; return true; })()")
        shown = f"document.querySelector('.view-body').dataset.view === '{view}'" if view else "!!document.querySelector('.view-body').dataset.view"
        self.go(f"#/p/{pid}" + (f"/{view}" if view else ""),
                f"location.hash.startsWith('#/p/{pid}') && !!document.querySelector('.view-body') && {shown}"
                f" && document.documentElement.dataset.scope === 'project' && document.querySelector('#main').dataset.loaded === '1'")

    def test_FR_UXO1_AC_1_scope_and_capsules_make_one_project_unmistakable(self):
        b = self.browser
        webhook, loans = self.project("Shipment webhook to the stock system"), self.project("Equipment loans")
        self.step("all projects")
        self.sign_in()
        self.assertEqual(b.eval("document.querySelector('#scopebar .scope-t').textContent"), "All projects")
        self.assertEqual(b.eval("document.documentElement.dataset.scope"), "all")
        self.assertIn("all projects", b.eval("document.querySelector('#sb-nav a[href=\"#/inbox\"]').textContent"))
        self.step("open a project")
        self.go("#/projects", "!!document.querySelector('.proj-card')")
        b.click(".proj-card", text="Shipment webhook", what="the webhook project")
        b.wait(f"location.hash.startsWith('#/p/{webhook.pid}') && !!document.querySelector('.caps')", "the project")
        self.assertEqual(b.eval(CAP_ON), "now")                                  # the business owner opens in Now
        self.assertEqual(b.eval("document.querySelector('#scopebar .scope-t').textContent"), webhook.meta["title"])
        self.assertTrue(b.eval("!!document.documentElement.style.getPropertyValue('--proj-h')"))   # the accent
        self.assertIn(webhook.meta["title"], b.eval("document.querySelector('#sb-nav .sb-proj').textContent"))
        self.assertTrue(b.eval("!!document.querySelector('#sb-nav a[href=\"#/projects\"]')"))      # ← All projects
        self.assertFalse(b.eval(f"!!document.querySelector('#sidebar a[href^=\"#/p/{webhook.pid}/\"]')"))   # no 2nd copy
        self.assertFalse(b.eval("!!document.querySelector('.tabs-all')"))                         # no Show all views
        self.assertEqual(b.eval("[...document.querySelectorAll('.caps-top .cap-t:not(.pin)')].map((a) => a.dataset.capsule).join()"),
                         "now,build,run,govern,agents")
        self.assertIn(webhook.meta["title"] + " · ", b.eval("document.querySelector('.view-body .view-h').textContent"))
        self.step("a capsule")
        b.click('.cap-t[data-capsule="build"]', what="the Build capsule")
        b.wait(f"{CAP_ON} === 'build' && {HASH_VIEW} === 'spec'", "Build, Spec & contract")
        subs = b.eval("[...document.querySelectorAll('.caps-sub a')].map((a) => a.dataset.view).join()")
        # the graph beside the spec; a developer's Board (FR-DEV1) leads the capsule
        self.assertTrue(subs.removeprefix("board,").startswith("spec,graph,tasks,changes"), subs)
        self.step("an old link")
        self.open_project(webhook.pid, "releases")
        self.assertEqual(b.eval(CAP_ON), "run")                                  # #/p/<pid>/<view> still works
        self.step("switch project")
        b.click("#scope-switch", what="the scope switcher")
        b.click("#menu-pop .menu-item", text="Equipment loans", what="Equipment loans in the switcher")
        b.wait(f"location.hash === '#/p/{loans.pid}/releases' && document.querySelector('#scopebar .scope-t').textContent"
               f" === {json.dumps(loans.meta['title'])}", "the same view in the other project, named in the scope bar")
        b.click("#scope-switch", what="the scope switcher")
        b.click("#menu-pop .menu-item", text="All projects", what="← All projects")
        b.wait("location.hash === '#/projects' && document.documentElement.dataset.scope === 'all'", "all projects again")
        self.step("a developer opens in Build")
        b.click("#person-chip", what="the person chip")
        b.click('label[for="pp-developer"]', what="developer")
        b.click("#pp-done", what="Done")
        self.open_project(webhook.pid)
        self.assertEqual(b.eval(CAP_ON), "build")
        self.check()

    def test_FR_UXO1_AC_2_an_inbox_card_says_what_it_wants_and_commenting_is_apart(self):
        b = self.browser
        webhook = self.project("Shipment webhook to the stock system")
        self.sign_in()
        self.step("a project's inbox")
        self.open_project(webhook.pid, "inbox")
        card = b.wait("(document.querySelector('.card.decision:not(.plan-card) .dc-opt') || {dataset: {}}).dataset.key", "a card")
        cid, first = card.split(":")
        art = f'.card.decision[data-id="{cid}"]'
        self.assertTrue(b.eval(f"document.querySelector('{art} .decide-t').textContent.startsWith('Decide:')"))
        self.assertEqual(b.eval(f"document.querySelectorAll('{art} .dc-opt[aria-checked=\"true\"]').length"), 0)   # none chosen
        self.assertTrue(b.eval(f"document.querySelector('{art} .why-box').hidden"))                 # no Why before a choice
        self.assertTrue(b.eval(f"[...document.querySelectorAll('{art} .dc-m')].every((m) => m.textContent.length > 5)"))
        self.assertEqual(b.eval(f"document.querySelector('{art} .card-foot .comment-btn').textContent"), "Add a comment")
        self.step("comment apart")
        b.click(f"{art} .card-foot .comment-btn", what="Add a comment")
        b.wait("document.querySelector('#modal').open", "the comment thread")
        b.type("#modal textarea", "Please check with the warehouse first")
        b.click("#modal button[type=submit]", what="Comment")
        b.wait("document.querySelector('#modal .thread').textContent.includes('check with the warehouse')", "the comment")
        b.key("Escape", 27)
        b.wait("!document.querySelector('#modal').open", "the thread closed")
        self.assertEqual(Canon(webhook).get_card(cid)["state"], "open")                         # a comment decides nothing
        self.step("decide with a reason")
        b.wait(f"!!document.querySelector('[data-key=\"{cid}:defer\"]')", "Defer")
        b.click(f'[data-key="{cid}:defer"]', what="Defer")
        b.wait(f"!document.querySelector('{art} .why-box').hidden", "Why opens after the choice")
        self.assertIn("Why? (optional, saved with your decision)", b.eval(f"document.querySelector('{art} .why-box label').textContent"))
        b.type(f"#reason-{cid}", "Not before the stock system's own release")
        b.click(f'[data-key="{cid}:confirm"]', what="Confirm")
        b.wait(f"!document.querySelector('{art}')", f"{cid} decided")
        d = Canon(webhook).get_card(cid)["decision"]
        self.assertEqual((d["verdict"], d["person"], d["reason"]), ("defer", PERSON, "Not before the stock system's own release"))
        self.step("all projects, by project")
        self.go("#/inbox", "!!document.querySelector('.ib-group')")
        self.assertTrue(b.eval("!!document.querySelector('.ib-ph')"))                              # the project is the heading
        self.assertEqual(b.eval("document.querySelector('[data-key=\"inbox-group:project\"]').getAttribute('aria-checked')"), "true")
        key = b.wait("(document.querySelector('.inbox-card .dc-opt') || {dataset: {}}).dataset.key", "a card to decide")
        k, verdict = key.rsplit(":", 1)
        b.click(f'[data-key="{key}"]', what="a choice")
        b.click(f'[data-key="{k}:confirm"]', what="Confirm without a reason")
        b.wait(f"!document.querySelector('[data-key=\"{key}\"]')", "decided without a reason")
        self.check()

    def test_FR_UXO1_AC_3_the_square_explains_itself_and_FR_UXO1_AC_4_ask_rihma_says_what_it_talks_about(self):
        b = self.browser
        webhook, loans = self.project("Shipment webhook to the stock system"), self.project("Equipment loans")
        self.sign_in()
        self.step("the square")
        self.go("#/square", "document.querySelectorAll('.sq-lanes .sq-lane').length === 5")
        self.assertIn("How needs move from arriving to production", b.eval("document.querySelector('.page-head .lede').textContent"))
        b.click('[data-key="lane:needs"]', what="the Needs lane")
        b.wait("document.activeElement && document.activeElement.id === 'needs-h'", "the needs listed")
        self.step("the square for one project")
        b.eval(f"(() => {{ const s = document.querySelector('#sq-scope'); s.value = {json.dumps(webhook.pid)};"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("!!document.querySelector('.sq-one')", "one project's square")
        self.assertIn("Concepts are not a project yet", b.eval("document.querySelector('.sq-lanes').textContent"))
        self.step("ask rihma in a project")
        self.open_project(webhook.pid, "inbox")
        b.click("#assistant-fab", what="Ask Rihma")
        line = b.wait("(document.querySelector('#as-scope .as-scope-t') || {}).textContent", "the scope line")
        self.assertEqual(line, "Talking about: " + webhook.meta["title"] + " · Inbox")
        b.type("#as-q", "How do I export the evidence?")
        b.click("#as-send", what="Send")
        steps = b.wait("(document.querySelector('#as-log .as-steps') || {}).textContent", "the steps")
        self.assertIn(webhook.pid, steps)
        self.assertNotIn("<", steps)
        self.assertIn(webhook.meta["title"], b.eval("document.querySelector('#as-log .as-about').textContent"))
        self.assertTrue(b.eval("!!document.querySelector('#as-log .as-cmd button')"))               # Copy per command
        b.click("#as-log .as-steps button", text="Take me there", what="Take me there")
        b.wait(f"location.hash === '#/p/{webhook.pid}/evidence' && {CAP_ON} === 'govern'", "Govern, Evidence")
        self.step("the whole platform, and a named project")
        if b.eval("document.querySelector('#assistant').hidden"):
            b.click("#assistant-fab", what="Ask Rihma")
        b.eval("(() => { const s = document.querySelector('#as-scope-pick'); s.value = 'platform';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("document.querySelector('#as-scope .as-scope-t').textContent === 'Talking about: all projects'", "all projects")
        b.type("#as-q", "How is Equipment loans doing?")
        b.click("#as-send", what="Send")
        said = b.wait("(document.querySelector('#as-log .as-about.switched') || {}).textContent", "the switch said")
        self.assertIn(loans.meta["title"], said)
        self.check()

    def test_FR_UXO1_AC_6_customize_any_view_and_a_capsules_tabs(self):
        b = self.browser
        webhook = self.project("Shipment webhook to the stock system")
        self.sign_in()
        self.step("customize the overview")
        self.open_project(webhook.pid, "overview")
        b.click("#customize", what="Customize")
        b.wait("!!document.querySelector('#vcz-bar') && !!document.querySelector('.vcz-tools')", "Customize this view")
        hide = b.eval("[...document.querySelectorAll('.vcz-tools [data-key$=\":hide\"]')].map((x) => x.dataset.key).pop()")
        sec = hide.split(":")[1]
        b.click(f'[data-key="{hide}"]', what="Hide a section")
        b.wait(f"document.querySelector('[data-cz-key=\"{sec}\"]').classList.contains('cz-off')", "the section hidden")
        self.step("tabs")
        b.click('[data-key="tabhide:review"]', what="Hide the Review tab")
        b.click('[data-key="tabpin:questions"]', what="Pin Questions to the top row")
        # the Inbox tab cannot be hidden while a card waits on the person there
        self.assertTrue(b.eval("document.querySelector('[data-key=\"tabhide:inbox\"]').disabled"
                               " === !!document.querySelector('.cap-t[data-capsule=\"now\"] .count')"))
        b.click('[data-key="vcz:done"]', what="Done")
        b.wait("!document.querySelector('#vcz-bar')", "Customize done")
        self.assertTrue(b.eval(f"getComputedStyle(document.querySelector('[data-cz-key=\"{sec}\"]')).display === 'none'"))
        self.assertTrue(b.eval("!!document.querySelector('.vcz-hidden-note')"))
        self.assertFalse(b.eval("!!document.querySelector('.caps-sub a[data-view=\"review\"]')"))
        self.assertIn("1 tab hidden", b.eval("document.querySelector('.caps-sub').textContent"))
        b.click('.cap-t[data-capsule="build"]', what="the Build capsule")
        b.wait("!!document.querySelector('.caps-top .cap-t.pin[data-pin=\"questions\"]')", "Questions pinned beside the capsules")
        self.open_project(webhook.pid, "overview")
        self.step("ask rihma to show it again")
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", "show all sections")
        b.click("#as-send", what="Send")
        b.click('#as-log [data-key="vl:preview"]', what="Preview")
        b.wait(f"!document.querySelector('[data-cz-key=\"{sec}\"]').classList.contains('cz-off')", "shown in the preview")
        b.click('#as-log [data-key="vl:undo"]', what="Undo")
        b.wait(f"document.querySelector('[data-cz-key=\"{sec}\"]').classList.contains('cz-off')", "hidden again")
        b.click("#as-close", what="Close")
        self.step("reset")
        b.click("#customize", what="Customize")
        b.click('[data-key="vcz:reset"]', what="Reset")
        b.click('[data-key="vcz:done"]', what="Done")
        b.wait("!document.querySelector('.cz-off') && !!document.querySelector('.caps-sub a[data-view=\"review\"]')"
               " && !document.querySelector('.cap-t.pin')", "the default layout and tabs")
        self.step("a global page")
        self.go("#/projects", "!!document.querySelector('.proj-card')")
        b.click("#customize", what="Customize")
        b.wait("!!document.querySelector('#vcz-bar') && !!document.querySelector('#main .vcz-tools')", "Customize on Projects")
        b.click('[data-key="vcz:done"]', what="Done")
        self.check()

    def test_FR_UXO1_AC_7_every_page_and_capsule_fits_1440_and_390_in_dark_and_light(self):
        b = self.browser
        webhook = self.project("Shipment webhook to the stock system")
        self.sign_in()
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": width < 500})
                for page in PAGES:
                    self.step(f"{scheme} {width} {page}")
                    self.go(f"#/{page}", "document.querySelector('#main').dataset.loaded === '1' && !!document.querySelector('#main h1')")
                    time.sleep(0.2)
                    self.assertTrue(b.eval(FITS), f"{page} scrolls sideways at {width} in {scheme}")
                for cap in ("now", "build", "run", "govern", "agents"):
                    self.step(f"{scheme} {width} capsule {cap}")
                    self.open_project(webhook.pid, "overview")
                    b.click(f'.cap-t[data-capsule="{cap}"]', what=f"the {cap} capsule")
                    b.wait(f"{CAP_ON} === '{cap}' && document.querySelector('#main').dataset.loaded === '1'", cap)
                    time.sleep(0.2)
                    self.assertTrue(b.eval(FITS), f"capsule {cap} scrolls sideways at {width} in {scheme}")
                    if width == 390:
                        small = b.eval("[...document.querySelectorAll('.caps a, .dc-opt, #scopebar button, #scopebar a, .bottombar a')]"
                                       ".filter((e) => e.getClientRects().length && e.getBoundingClientRect().height < 39.5)"
                                       ".map((e) => e.className + ':' + e.textContent.trim().slice(0, 20))")
                        self.assertEqual(small, [], f"touch targets under 40 px in {cap}")
        self.step("words per persona")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        self.go("#/inbox", "!!document.querySelector('.inbox-card .dc-h')")
        self.assertEqual(b.eval("document.querySelector('.inbox-card .dc-h').textContent"), "Your choice")   # a business owner's
        meaning = b.eval("(document.querySelector('[data-key$=\":retry\"] .dc-m') || {}).textContent || ''")
        b.click("#person-chip", what="the person chip")
        b.click('label[for="pp-developer"]', what="developer")
        b.click("#pp-done", what="Done")
        self.go("#/projects", "!!document.querySelector('.proj-card')")
        self.go("#/inbox", "!!document.querySelector('.inbox-card .dc-h')")
        self.assertEqual(b.eval("document.querySelector('.inbox-card .dc-h').textContent"), "Verdict")   # a developer's
        tech = b.eval("(document.querySelector('[data-key$=\":retry\"] .dc-m') || {}).textContent || ''")
        if meaning and tech:
            self.assertNotEqual(meaning, tech)                                     # the same choice, said for each
        self.check()


if __name__ == "__main__":
    unittest.main()
