"""Agent operations' fixes in a real browser (FR-AOP2-AC-5 and AC-4): headless Chrome over the DevTools protocol, as
tests/test_ui_agentops.py drives it, on neutral projects with made-up agent runs (tests/agentops_fakes.py).

The builder ran on one day only: its tokens, the largest single value of "Tokens over time, by role", are drawn as a
dot instead of an invisible bare point. A model without a price is priced on the Prices card, signed, and its runs'
cost is then measured. No "how to measure" names a file of the installation. Dark and light, 1440 and 390 pixels
wide: nothing scrolls sideways and no step leaves a console error, a failed request or a CSP violation; a business
owner meets no unexplained jargon.

The cockpit listens on ``RIHMA_AOP2_PORT`` (8947) and Chrome's DevTools on ``RIHMA_AOP2_DEVTOOLS`` (9547).
``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
"""

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import agentops_fakes as fakes  # noqa: E402
import test_ui_agentops as ui  # noqa: E402
from test_ui_words import JARGON, VISIBLE  # noqa: E402

ui.PORT = int(os.environ.get("RIHMA_AOP2_PORT") or 8947)
ui.DEVTOOLS = int(os.environ.get("RIHMA_AOP2_DEVTOOLS") or 9547)
LONE = ("[...document.querySelectorAll('[aria-labelledby=\"aop-trend-h\"] .aol-pt[data-series=\"builder\"]')]"
        ".map((e) => { const r = e.getBoundingClientRect(); return [r.width, r.height, getComputedStyle(e).display]; })")


class UiAgentOpsFixTest(ui.UiAgentOpsTest):
    test_FR_AOP1_AC_9_the_ai_architect_reads_agent_operations_fit_dark_and_light_and_records_the_audit = None

    def setUp(self):
        super().setUp()
        from kernel import agentops_cache

        agentops_cache.forget()
        self.q.log("model_run", fakes.model_run("analyst", "example-large", 4000, 1000, 2.0)
                   | {"model": "example-new", "cost": {"measured": False, "why": "not in the price table"}})

    def test_FR_AOP2_AC_5_a_lone_value_is_a_dot_and_a_model_is_priced_on_the_prices_card(self):
        b = self.browser
        self.step("sign in as the AI architect")
        self.sign_in("ai_architect")
        self.step("the platform view")
        b.eval("location.hash = '#/agentops'; true")
        b.wait(ui.DRAWN + " && !!document.querySelector('#aop-prices-h')", "the platform view with its prices")
        dots = b.eval(LONE)
        self.assertEqual(len(dots), 1, dots)                 # the builder ran on one day: one dot
        self.assertGreater(dots[0][0], 0)
        self.assertNotEqual(dots[0][2], "none")
        text = b.eval("document.querySelector('.aop').textContent")
        self.assertNotRegex(text, r"kernel/|\.py\b|prices\.json")
        card = b.eval("document.querySelector('[aria-labelledby=\"aop-prices-h\"]').textContent")
        self.assertIn("example-new", card)
        self.assertIn("Not priced", card)
        b.eval("document.querySelector('#aop-trend-h').scrollIntoView(); true")     # the screenshot shows the dot
        self.step("price the model")
        self.assertEqual(b.eval("document.querySelector('#aop-pr-model').value"), "example-new")
        b.eval("document.querySelector('#aop-pr-in').value = '1.5'; document.querySelector('#aop-pr-out').value = '6';"
               " true")
        b.click('[data-key="aop-pr:save"]', what="Price the model")
        b.wait("(document.querySelector('#status') || {}).textContent.includes('is priced at 1.5 in and 6 out')",
               "the model priced")
        from kernel.learn import factory_project

        rec = factory_project(self.factory).ledger().of_kind("model_price_set")[-1]["event"]["payload"]
        self.assertEqual((rec["model"], rec["input"], rec["output"], rec["person"]), ("example-new", 1.5, 6.0,
                                                                                      ui.PERSON))
        b.wait("document.querySelector('[aria-labelledby=\"aop-prices-h\"]').textContent.includes('1.5 USD in')",
               "the price shown")
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"prices {scheme} {width}")
                self.look(scheme, width, "#/agentops")
                self.assertEqual(len(b.eval(LONE)), 1, (scheme, width))
                b.eval("document.querySelector('#aop-prices-h').scrollIntoView(); true")
        self.step("a business owner reads it in plain words")
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1,
                                                     "mobile": False})
        self.persona("business_owner")
        b.eval("location.hash = '#/home'; true")
        b.wait("!!document.querySelector('#grid')", "home")
        b.eval("location.hash = '#/agentops'; true")
        b.wait(ui.DRAWN + " && !!document.querySelector('#aop-prices-h')", "the view as a business owner")
        seen = b.eval(f"({VISIBLE})('.aop')")
        bad = sorted({(w, t) for t, _ in seen for w in JARGON if re.search(rf"\b{re.escape(w)}\b", t.lower())})
        self.assertEqual(bad, [], "jargon a business owner meets unexplained")
        b.eval("document.querySelector('#aop-prices-h').scrollIntoView(); true")
        self.check()


if __name__ == "__main__":
    unittest.main()
