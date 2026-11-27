"""Agent operations and Who acted after the AI architect's acceptance test, in a real browser (FR-AOP3-AC-14 and the
drawn side of AC-1, AC-3, AC-8 to AC-12): headless Chrome over the DevTools protocol, as tests/test_ui_agentops.py
drives it, on neutral projects with made-up agent runs (tests/agentops_fakes.py, tests/test_agentops_arch.py).

The builder's rounds are rows of their own; a run's call outcome and the gate it fed are separate columns, and a
stand-in's zero seconds read "not timed"; runs that recorded no tokens are said apart from a model without a price;
Optimise totals its saving over the period; Who acted marks each failed round; Home's Spend counts the runs Agent
operations counts; Ask Rihma suggests the AI architect's own questions, labels a price for every project and says
in its footer that Confirm is what changes anything. No step leaves a console error, a failed request or a CSP
violation, and nothing scrolls sideways at 390 pixels.

The cockpit listens on ``RIHMA_AOP3_PORT`` (8953) and Chrome's DevTools on ``RIHMA_AOP3_DEVTOOLS`` (9553).
``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import agentops_fakes as fakes  # noqa: E402
import test_ui_agentops as ui  # noqa: E402
from test_agentops_arch import rounds  # noqa: E402

ui.PORT = int(os.environ.get("RIHMA_AOP3_PORT") or 8953)
ui.DEVTOOLS = int(os.environ.get("RIHMA_AOP3_DEVTOOLS") or 9553)
TEXT = "(document.querySelector({0}) || {{textContent: ''}}).textContent"


class UiAgentOpsArchTest(ui.UiAgentOpsTest):
    test_FR_AOP1_AC_9_the_ai_architect_reads_agent_operations_fit_dark_and_light_and_records_the_audit = None

    def setUp(self):
        super().setUp()
        from kernel import agentops_cache

        agentops_cache.forget()
        rounds(self.p)
        self.p.log("model_run", fakes.model_run("analyst", "example-large", 4000, 1000, 2.0)
                   | {"model": "example-new", "cost": {"measured": False, "why": "not in the price table"}})

    def text(self, selector: str) -> str:
        return self.browser.eval(TEXT.format(repr(selector)))

    def ask(self, question: str) -> None:
        b = self.browser
        b.eval("document.querySelector('#as-q').value = ''; true")
        b.type("#as-q", question)
        b.click("#as-send", what="Send")

    def test_FR_AOP3_AC_14_the_ai_architect_reads_every_agent_and_gets_their_own_next_questions(self):
        from kernel import agentops

        b = self.browser
        runs = agentops.build(self.factory, window="30d", context=False)["totals"]["runs"]
        self.step("sign in as the AI architect")
        self.sign_in("ai_architect")
        self.step("Home's Spend counts the runs Agent operations counts")
        b.eval("location.hash = '#/home'; true")
        spend = b.wait(TEXT.format(repr('#grid [data-type="spend"] .card-body')) + ".includes('over ')",
                       "the Spend widget with its runs")
        self.assertTrue(spend)
        said = self.text('#grid [data-type="spend"] .card-body')
        self.assertIn(f"over {runs} runs", said)
        self.assertNotIn("No Gnomon run yet", said)
        self.step("the platform view")
        b.eval("location.hash = '#/agentops'; true")
        b.wait(ui.DRAWN + " && !!document.querySelector('#aop-prices-h')", "the platform view")
        roles = self.text('[aria-labelledby="aop-roles-h"]')
        self.assertIn("example-builder", roles)
        self.assertIn("scripted", roles)
        self.assertIn("the gate failed 6 of 8 rounds fed", self.text(".aop-tiles"))
        self.assertTrue(b.eval("!!document.querySelector("
                               "'[aria-labelledby=\"aop-prices-h\"] [data-lede=\"no-tokens\"]')"))
        self.assertIn("over the period", self.text('[aria-labelledby="aop-optimise-h"]'))
        self.step("the runs behind a figure")
        b.click(".aop-tiles .kpi", what="the Runs tile")
        b.wait("document.querySelectorAll('#modal .aop-drill tbody tr').length > 0", "the runs")
        heads = b.eval("[...document.querySelectorAll('#modal .aop-drill thead th')].map((x) => x.textContent)")
        self.assertIn("Call outcome", heads)
        self.assertIn("Gate", heads)
        drill = self.text("#modal .aop-drill")
        self.assertIn("stand-in, not timed", drill)
        self.assertIn("failed", drill)
        b.key("Escape", 27)
        b.wait("!document.querySelector('#modal .aop-drill')", "the runs closed")
        self.step("Ask Rihma suggests the AI architect's questions")
        b.click("#assistant-fab", what="Ask Rihma")
        b.wait(TEXT.format(repr("#as-suggest")) + ".includes('What do my agents cost?')",
               "the AI architect's questions")
        chips = self.text("#as-suggest")
        for q in ("Optimise my agents", "How are my agents performing?"):
            self.assertIn(q, chips)
        self.assertNotIn("Where do I approve the plan?", chips)
        self.assertIn("waits for your Confirm", self.text("#assistant .dr-note"))
        self.step("a price is for every project")
        b.eval(f"location.hash = '#/p/{self.p.pid}/agentops'; true")
        b.wait(ui.DRAWN, "the project's view")
        if not b.eval("!document.querySelector('#assistant').hidden"):
            b.click("#assistant-fab", what="Ask Rihma")
        self.ask("set the price of example-new to 1 and 3 per million tokens")
        b.wait("!!document.querySelector('#as-log .prop .prop-on')", "the proposal")
        self.assertEqual(b.eval("[...document.querySelectorAll('#as-log .prop .prop-on')].pop().textContent"),
                         "on Rihmasto · every project")
        self.step("Who acted marks each failed round")
        b.eval(f"location.hash = '#/p/{self.p.pid}/who'; true")
        b.wait("document.querySelectorAll('.nvl-run').length > 0", "the runs")
        self.assertEqual(b.eval("document.querySelectorAll('.nvl-run[data-gate=\"failed\"]').length"), 6)
        self.assertIn("Build T-002, attempt 4", self.text('[data-control="who_acted"]'))
        self.step("the drill fits a phone")
        b.click("#as-close", what="Close the assistant")
        self.look("dark", 390, "#/agentops")
        b.click(".aop-tiles .kpi", what="the Runs tile")
        b.wait("document.querySelectorAll('#modal .aop-drill tbody tr').length > 0", "the runs on a phone")
        self.assertLessEqual(b.eval(ui.SIDEWAYS), 0)
        self.check()


if __name__ == "__main__":
    unittest.main()
