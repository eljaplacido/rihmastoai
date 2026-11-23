import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import (FactoryTestCase, TRIVIAL_TEST, generic_cell, lazy_cell, model,  # noqa: E402
                           no_findings)

from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task, resolve_escalations  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


def eager_cell(lane_path, prompt):
    """Builds its own criteria and, ahead of time, R-2-AC-1's behaviour (without a test for it)."""
    out = generic_cell(lane_path, prompt)
    routes = Path(lane_path, "app", "routes.py")
    routes.write_text(routes.read_text(encoding="utf-8")
                      + '\n\n@route("GET", "/criteria/R-2-AC-1")\ndef early(req):\n    return 200, {}\n',
                      encoding="utf-8", newline="\n")
    return out


def vacuous_cell(lane_path, prompt):
    Path(lane_path, "tests", "test_vacuous.py").write_text(
        TRIVIAL_TEST.replace("R_1_AC_1", "R_2_AC_1"), encoding="utf-8", newline="\n")
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "model": "fake-builder", "output": "done"}


class GateRulesTest(FactoryTestCase):
    def compiled(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def test_FR_O6_AC_2_a_criterion_already_met_passes_only_if_its_tests_fail_on_the_template(self):
        p = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        self.assertEqual(build_task(p, "T-001", lanes=lanes, cell_runner=eager_cell,
                                    verifier_runner=no_findings)["status"], "merged")
        out = build_task(p, "T-002", lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertEqual(out["status"], "merged")
        ff = {s["name"]: s for s in out["rounds"][-1]["gate"]["signals"]}["fail_first"]
        self.assertEqual(ff["verdict"], "passed")
        self.assertEqual(ff["native"]["already_met_at_base"], ["R-2-AC-1"])

    def test_FR_O6_AC_2_a_test_that_passes_even_on_the_template_is_refused(self):
        p = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        build_task(p, "T-001", lanes=lanes, cell_runner=eager_cell, verifier_runner=no_findings)
        out = build_task(p, "T-002", lanes=lanes, cell_runner=vacuous_cell, verifier_runner=no_findings,
                         max_rounds=0)
        self.assertEqual(out["status"], "escalated")
        ff = {s["name"]: s for s in out["rounds"][-1]["gate"]["signals"]}["fail_first"]
        self.assertEqual(ff["verdict"], "failed")
        self.assertIn("bare template", ff["detail"])

    def test_FR_G8_AC_2_a_persons_decision_on_an_escalation_is_carried_out(self):
        p = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        esc = build_task(p, "T-001", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=0)
        canon = Canon(p)
        canon.decide(esc["card"], "retry", person="Dev", persona="developer")
        self.assertEqual(resolve_escalations(p), [esc["card"]])
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "pending")
        self.assertEqual(resolve_escalations(p), [])                     # carried out once
        esc2 = build_task(p, "T-001", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=0)
        Canon(p).decide(esc2["card"], "accept_as_is", person="Aino", persona="business_owner", reason="good enough")
        resolve_escalations(p)
        state = p.read("tasks.json")["T-001"]
        self.assertEqual((state["status"], state["accepted_as_is_by"]), ("merged", "Aino"))
        merged = [r["event"]["payload"] for r in p.ledger().of_kind("merged")][-1]
        self.assertEqual(merged["warranted"], "not warranted")
        self.assertTrue(merged["permitted_by"].startswith("person:Aino"))
        self.assertEqual(_git(p.path("repo.git"), "rev-parse", "main"), merged["revision"])
        esc3 = build_task(p, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=0)
        Canon(p).decide(esc3["card"], "stop", person="Aino", persona="business_owner")
        resolve_escalations(p)
        self.assertEqual(p.read("tasks.json")["T-002"]["status"], "stopped")
        self.assertTrue(p.meta["halted"])

    def test_FR_J2_AC_1_an_apparatus_failure_is_retried_with_pauses_before_anyone_is_asked(self):
        p = self.compiled()
        calls = []

        def flaky(lane_path, prompt):
            calls.append(1)
            if len(calls) < 3:
                return {"bucket": "apparatus_failure", "code": 10, "stop_reason": "endpoint_error"}
            return generic_cell(lane_path, prompt)

        out = build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=flaky,
                         verifier_runner=no_findings, reflex_backoff=(0, 0))
        self.assertEqual(out["status"], "merged")
        retries = [r["event"]["payload"] for r in p.ledger().of_kind("reflex_retry")]
        self.assertEqual([r["attempt"] for r in retries], [1, 2])
        always = build_task(p, "T-002", lanes=Lanes(self.tmp / "lanes", size=1), verifier_runner=no_findings,
                            cell_runner=lambda lp, pr: {"bucket": "apparatus_failure", "code": 10, "stop_reason": "endpoint_error"},
                            reflex_backoff=(0, 0))
        self.assertEqual(always["status"], "escalated")
        card = Canon(p).get_card(always["card"])
        self.assertIn("an apparatus failure, not the work", card["body"])


if __name__ == "__main__":
    unittest.main()
