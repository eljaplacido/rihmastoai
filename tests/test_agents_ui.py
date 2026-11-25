"""FR-CPL1, FR-BRG1 and FR-CHN1 in a real browser: headless Chrome over the DevTools protocol, as tests/test_ui_drive.py
drives it.

A person asks Ask Rihma to hook a project to Google Drive, reads the plan with its gap and drafts the change it
proposes, filing it signed; opens a project whose coding agents posted progress, reads the Agents working on this
strip and hands the project off to an agent; opens the Agent channel, opens a Rihma answer's trace, asks @analyst,
confirms an agent's proposed answer, pauses and resumes the channel, filters it, and reads the Agent activity
monitor. Dark and light, 1440 and 390 pixels wide, nothing scrolls sideways, every control has a name, and no step
leaves a console error, a failed request or a Content-Security-Policy violation behind.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary). Only scripted models answer
(tests/factory_fakes.py); no coding agent runs. ``RIHMA_UI_SHOTS=<folder>`` also saves a screenshot per step.
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

from factory_fakes import model  # noqa: E402
from test_agent_bridge import planned  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import agent_bridge as bridge  # noqa: E402
from kernel import agent_channel as ch  # noqa: E402
from kernel import channel_rihma  # noqa: E402
from kernel.agent_writes import progress, propose_answer  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
DRIVE = "I want to hook this solution to Google Drive"
NAMELESS = """(() => [...document.querySelectorAll(
  '#modal :is(button, a[href], input, select, textarea), .agents-strip :is(button, a[href]), ' +
  '.ch-panel :is(button, select, textarea), .goal-plan button, .aa-list a, .ph-acts button')]
  .filter((el) => el.getClientRects().length).filter((el) => {
    const label = (el.labels ? [...el.labels].map((l) => l.textContent).join(' ') : '') || el.getAttribute('aria-label') || '';
    const own = /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) ? '' : el.textContent;
    return !(label + own).trim(); }).map((el) => el.outerHTML.slice(0, 120)))()"""
SCHEMES = [(s, w) for s in ("dark", "light") for w in (1440, 390)]


class AgentsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-agents-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots
        self.p = planned(self.factory, "Equipment loans")

    # -- helpers -------------------------------------------------------------------------------------------

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
        self.assertEqual(b.eval(NAMELESS), [], f"controls with no accessible name during '{b.step}'")
        self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, f"sideways in '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"agents-{b.step.replace(' ', '-')}.png")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-product_owner"]', what="the product owner persona")
        b.click("#pp-done", what="Done in the person menu")

    def go(self, hash_: str, ready: str, what: str):
        b = self.browser
        b.eval(f"location.hash = {json.dumps(hash_)}; true")
        return b.wait(ready, what)

    def scheme(self, scheme: str, width: int) -> None:
        b = self.browser
        b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                     "mobile": width < 500})

    def until(self, test, what: str, timeout: float = 15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = test()
            if got:
                return got
            time.sleep(0.1)
        raise AssertionError(f"timed out waiting for {what}")

    # -- the tests -----------------------------------------------------------------------------------------

    def test_FR_CPL1_AC_5_a_goal_in_ask_rihma_gets_a_plan_and_its_drafted_change_is_filed_signed(self):
        b = self.browser
        self.p.update_meta(source_kind="adopted")
        self.step("ask for a goal")
        self.sign_in()
        overview = f"#/p/{self.p.pid}/overview"
        self.go(overview, "!!document.querySelector('.next-strip')", "the overview")
        b.click("#assistant-fab", what="Ask Rihma")
        b.type("#as-q", DRIVE)
        b.click("#as-send", what="Send")
        plan = b.wait("(document.querySelector('#as-log .goal-plan') || {}).textContent", "the plan")
        self.assertIn("Declare the Google Drive integration", plan)      # the Drive kind is here (FR-GDR1)
        self.assertIn("Choose where it runs in production", plan)
        self.assertIn("Hand it to a coding agent", plan)
        self.assertEqual(Canon(self.p).cards(kind="change"), [])                  # the plan wrote nothing
        self.step("draft the change")
        b.click('[data-key="goal:S-1"]', what="Draft it")
        draft = b.wait("document.querySelector('#modal').open && (document.querySelector('#dc-text') || {}).value",
                       "the change form, prefilled")
        self.assertIn(DRIVE, draft)
        self.assertIn("Questions it raises", draft)
        b.click('[data-key="dc-file"]', what="File the change")
        b.wait("!document.querySelector('#modal').open", "the form closed")
        cards = self.until(lambda: Canon(self.p).cards(kind="change"), "the change card")
        self.assertEqual(cards[0]["payload"]["person"], PERSON)
        self.assertIn(DRIVE, cards[0]["payload"]["text"])
        for scheme, width in SCHEMES:
            self.step(f"plan {scheme} {width}")
            self.scheme(scheme, width)
            self.go(overview, "!!document.querySelector('.next-strip')", "the overview")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", f"the {scheme} theme")
            if b.eval("document.querySelector('#assistant').hidden"):
                b.click("#bb-ask" if width < 500 else "#assistant-fab", what="Ask Rihma")   # the bottom bar's Ask
            b.wait("!document.querySelector('#assistant').hidden"
                   " && !!document.querySelector('#as-log .goal-plan').getClientRects().length", "the plan in the drawer")
            self.check()
            b.key("Escape", 27)

    def test_FR_BRG1_AC_4_the_agents_strip_shows_agent_work_and_hand_off_gives_the_brief(self):
        b = self.browser
        agent = ch.agent("claude-code", "Tessa", "developer", "claude-code 2.1")
        progress(self.p, agent, "Sorted overdue loans first", files=["app/routes.py"], criteria=["R-1-AC-1"])
        ch.post(self.p, author=ch.SYSTEM, kind="gate_result", text="Gate on abc123: passed.",
                trace={"basis": "gate", "signals": [{"name": "tests", "verdict": "passed"}]})
        self.step("the agents strip")
        self.sign_in()
        overview = f"#/p/{self.p.pid}/overview"
        strip = self.go(overview, "(document.querySelector('.agents-strip .as-list') || {}).textContent", "the strip")
        self.assertIn("claude-code for Tessa", strip)
        self.assertIn("Sorted overdue loans first", strip)
        self.assertIn("1 gate result", b.eval("document.querySelector('.agents-strip').textContent"))
        self.step("hand off")
        handoffs = len(self.p.ledger().of_kind("agent_handoff"))
        b.click('[data-key="handoff"]', what="Hand off to an agent")
        brief = b.wait("document.querySelector('#modal').open && (document.querySelector('#ho-brief') || {}).textContent"
                       " .includes('# Hand-off') && document.querySelector('#ho-brief').textContent", "the brief")
        self.assertIn("R-1-AC-1", brief)
        self.assertIn("How to report back", brief)
        b.eval("(() => { const s = document.querySelector('#ho-to'); s.value = 'codex';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("document.querySelector('#ho-how').textContent.includes('codex exec')", "the Codex command")
        # the cell runners are in this Rihmasto: the project's builder runner (Gnomon by default) is offered
        self.assertIn("Run it with Gnomon", b.eval("document.querySelector('#ho-acts').textContent"))
        b.click('[data-key="ho-copy"]', what="Copy the brief")
        self.until(lambda: len(self.p.ledger().of_kind("agent_handoff")) > handoffs, "the hand-off recorded")
        rec = self.p.ledger().of_kind("agent_handoff")[-1]["event"]["payload"]
        self.assertEqual((rec["to"], rec["via"], rec["person"]), ("codex", "copy", PERSON))
        b.key("Escape", 27)
        b.wait("!document.querySelector('#modal').open", "the dialog closed")
        self.step("the channel beside the view")
        b.click('[data-key="channel-panel"]', what="Agent channel beside the view")
        b.wait("(document.querySelector('#chp-log') || {}).textContent.includes('Sorted overdue loans first')",
               "the channel panel")
        b.click('[data-key="agent-aside-close"]', what="Close the panel")
        for scheme, width in SCHEMES:
            self.step(f"strip {scheme} {width}")
            self.scheme(scheme, width)
            self.go(overview, "!!document.querySelector('.agents-strip .as-list')", "the strip")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", f"the {scheme} theme")
            self.check()
            b.click('[data-key="handoff"]', what="Hand off to an agent")
            b.wait("(document.querySelector('#ho-brief') || {}).textContent.includes('# Hand-off')", "the brief")
            self.check()
            b.key("Escape", 27)
            b.wait("!document.querySelector('#modal').open", "the dialog closed")

    def test_FR_CHN1_AC_6_a_person_watches_the_channel_steps_in_and_reads_the_agent_activity_monitor(self):
        b = self.browser
        rooms = self.factory.new_project("Room bookings", mode="socratic", maturity="demo")
        intake(rooms, IDEA, model=model(), requested_by="Aino")
        claude, codex = ch.agent("claude-code", "Tessa", "developer"), ch.agent("codex", "Pekka", "developer")
        progress(rooms, claude, "Drafted the booking form", files=["app/forms.py"])
        prop = propose_answer(rooms, codex, "Q-001", "the team lead approves")
        q = ch.post(rooms, author=claude, kind="question", text="What should I build next?", ask=True)
        answer = channel_rihma.reply(rooms, q)
        self.step("the channel")
        self.sign_in()
        view = f"#/p/{rooms.pid}/agents"
        self.go(view, "document.querySelectorAll('#ch-log .ch-msg').length >= 4", "the messages")
        self.assertTrue(b.eval("!!document.querySelector('#ch-log .ch-agent .ab-agent')"))
        self.assertTrue(b.eval("!!document.querySelector('#ch-log .ch-rihma .ab-rihma')"))
        self.assertIn("codex for Pekka", b.eval("document.querySelector('#ch-log').textContent"))
        self.step("the trace")
        b.click(f'[data-key="ch-trace:{answer["id"]}"]', what="the answer's Trace")
        trace = b.wait(f"(() => {{ const d = document.querySelector('[data-id=\"{answer['id']}\"] .ch-drawer');"
                       " return d && !d.hidden && d.textContent; })()", "the trace drawer")
        self.assertIn("the records, by rule", trace)
        self.assertIn("rests on", trace)
        self.step("ask the analyst")
        b.type("#ch-text", "@analyst is Q-002 still open?")
        b.click('[data-key="ch-send"]', what="Send")
        said = b.wait("(() => { const r = [...document.querySelectorAll('#ch-log .ch-rihma')];"
                      " return r.length >= 2 && r[r.length - 1].textContent; })()", "Rihma's answer")
        self.assertIn("Q-002 is open", said)
        mine = [m for m in ch.messages(rooms) if m["author"]["kind"] == "person"]
        self.assertEqual((mine[0]["author"]["name"], mine[0]["kind"]), (PERSON, "question"))
        self.step("confirm a proposal")
        b.click(f'[data-key="ch-confirm:{prop["id"]}"]', what="Confirm the answer")
        self.until(lambda: Canon(rooms).question("Q-001")["status"] == "answered", "the question answered")
        b.wait(f"document.querySelector('[data-id=\"{prop['id']}\"]').textContent.includes('proposal: confirmed')",
               "the proposal confirmed")
        self.step("pause and resume")
        b.click('[data-key="ch-pause"]', what="Pause the channel")
        b.wait("document.querySelector('.ch-pause').textContent.includes('Paused by')", "the paused chip")
        self.assertTrue(ch.read(rooms)["paused"])
        b.click('[data-key="ch-resume"]', what="Resume")
        b.wait("!!document.querySelector('[data-key=\"ch-pause\"]')", "resumed")
        self.step("filter")
        b.eval("(() => { const s = document.querySelector('#ch-kind'); s.value = 'proposal';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("document.querySelectorAll('#ch-log .ch-msg').length === 1", "only the proposal")
        b.eval("(() => { const s = document.querySelector('#ch-kind'); s.value = '';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        self.step("agent activity")
        rows = self.go("#/agents", "(document.querySelector('.aa-list') || {}).textContent", "the monitor")
        self.assertIn("Room bookings", rows)
        self.assertIn("Talking:", rows)
        for scheme, width in SCHEMES:
            self.step(f"channel {scheme} {width}")
            self.scheme(scheme, width)
            self.go(view, "document.querySelectorAll('#ch-log .ch-msg').length >= 5", "the messages")
            b.wait(f"document.documentElement.dataset.theme === '{scheme}'", f"the {scheme} theme")
            self.check()
            self.go("#/agents", "!!document.querySelector('.aa-list')", "the monitor")
            self.check()
        self.assertTrue(bridge.AGENTS)


if __name__ == "__main__":
    unittest.main()
