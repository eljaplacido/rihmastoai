"""FR-HITL2 in a real browser (headless Chrome over the DevTools protocol).

A business owner working alone: a legal decision is required before delivery and is on a link given to a person
outside a day and more ago; a security question waits on IT. The project's Inbox and the all-projects Inbox say
delivery waits on that answer; People in the loop says how to answer the IT question (switch persona); Nudge renews
the outside link and shows its new address once, warning that it points at this computer only; the link form warns
the same; and in Ask Rihma, confirming "give Sami Example a link for the security questions" shows the new link
once in the chat, never stored in the browser. Dark at 1440 px, then light at 390 px; after every step no console
error, failed request or CSP violation, every control named, nothing wider than the screen. Skipped without Chrome.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_hitl_ui  # noqa: E402  (its helpers; imported as a module so its own test is not run twice)

from kernel import hitl, hitl_links  # noqa: E402
from kernel.store import updating_json  # noqa: E402

AINO = {"person": "Aino Example", "persona": "business_owner"}


class LoopFixUiTest(test_hitl_ui.LoopUiTest):
    test_FR_HITL1_AC_8_one_asks_gives_a_link_and_the_person_outside_answers_dark_light_wide_narrow = None   # its own

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        p = cls.project
        hitl.ask(p, text="May we keep the loan history for two years?", kind="decision", family="legal",
                 options=["Yes", "No"], **AINO)
        hitl.ask(p, text="Is the admin page behind sign-in?", family="security", **AINO)
        hitl.set_level(p, "legal", "require", person="Kaisa Example", persona="compliance")
        hitl_links.create(p, name="Maria Example", persona="compliance", asks=["HQ-001"], person="Aino Example",
                          creator_persona="business_owner", role="External legal counsel")
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with updating_json(p.path(hitl.FILE), {}) as doc:       # asked a day and more ago
            doc["asks"][0]["at"] = old

    def test_FR_HITL2_AC_1_AC_7_AC_8_holds_hints_nudged_and_chat_links_shown_once_dark_light_wide_narrow(self):
        b, pid = self.browser, self.project.pid
        self.step("sign in")
        self.sign_in()
        self.theme("dark", "Dark")
        self.step("the project's Inbox says delivery waits on an answer")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{pid}/inbox"})
        held = b.wait("(document.querySelector('.hl-held[data-held] ') || {}).textContent", "what holds delivery")
        self.assertIn("HQ-001", held)
        self.assertIn("Maria Example (outside)", held)
        self.assertIn("Open People in the loop", held)
        self.assertNotIn("HQ-002", held)                                     # advised: not here
        self.fits()
        self.step("the all-projects Inbox says it too")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/inbox"})
        held = b.wait("(document.querySelector('.hl-held[data-held=\"all\"]') || {}).textContent", "across projects")
        self.assertIn("Tool loans: HQ-001", held)
        self.fits()
        self.step("an ask put to IT says how to answer it")
        self.open_loop()
        hint = b.wait("(document.querySelector('[data-ask-hint=\"HQ-002\"]') || {}).textContent", "the hint")
        self.assertIn("switch to it in the person menu", hint)
        self.assertIn("answers it on their own page", b.eval(
            "document.querySelector('[data-ask-hint=\"HQ-001\"]').textContent"))
        self.fits()
        self.step("nudge renews the outside link and shows it once")
        b.click('[data-control="hitl_nudge"]', what="Nudge now")
        url = b.wait("(document.querySelector('.hl-main .hl-once .hl-url') || {}).textContent", "the new link")
        self.assertIn("/r/#rv_", url)
        once = b.eval("document.querySelector('.hl-main .hl-once').textContent")
        self.assertIn("RL-002", once)
        self.assertIn("nobody outside can open it", once)
        self.toast("A new link for Maria Example (RL-002)", "the nudge's message")
        self.fits()
        self.step("the link form warns about this computer's address")
        b.click(".hl-more summary", text="Give someone a link", what="Give someone a link")
        self.assertIn("this computer only", b.wait("(document.querySelector('.hl-local') || {}).textContent", "the note"))
        self.fits()
        self.step("light and narrow, Ask Rihma makes a link and shows it once")
        self.theme("light", "Light")
        b.click("#assistant-fab", what="Ask Rihma")
        self.size(390, 844)
        b.type("#as-q", "give Sami Example a link for the security questions")
        b.click("#as-send", what="Send")
        b.wait("!!document.querySelector('#as-log .prop button')", "the proposal")
        self.assertIn("shown here once", b.eval("document.querySelector('#as-log').textContent"))
        b.click("#as-log .prop button", text="Confirm", what="Confirm")
        url = b.wait("(document.querySelector('#as-log .hl-once .hl-url') || {}).textContent", "the link in the chat")
        self.assertIn("/r/#rv_", url)
        token = url.split("#", 1)[1]
        self.assertTrue(b.eval("!!document.querySelector('#as-log .hl-once [data-control=\"hitl_link_copy\"]')"))
        stored = b.eval("JSON.stringify(Object.assign({}, localStorage)) + JSON.stringify(Object.assign({}, sessionStorage))")
        self.assertNotIn(token, stored)                                       # shown once, never kept
        self.assertIn("RL-003", b.eval("document.querySelector('#as-log .hl-once').textContent"))
        self.fits()
        self.assertEqual([r["id"] for r in hitl_links.links(self.factory)], ["RL-001", "RL-002", "RL-003"])
        self.check()


if __name__ == "__main__":
    unittest.main()
