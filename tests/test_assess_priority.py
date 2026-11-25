"""Which assessment findings to fix first, and why, by rule (FR-BA1-AC-18; kernel/assess_priority.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory_fakes import FactoryTestCase
from test_assess import by_key, fixture_repo, mirrored, no_scanner

from kernel import assess, assess_cards
from kernel.assess_priority import asks_priorities, ranked, suggest_class
from kernel.assistant import ask

SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class PriorityTest(FactoryTestCase):
    def test_FR_BA1_AC_18_open_findings_come_in_order_with_why_and_ask_rihma_answers_by_rule(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        record = assess.assess(project, person="Aino", persona="developer", which=no_scanner)
        order = ranked(assess_cards.view(project))
        failed = [c for c in record["checks"] if c["verdict"] == "failed"]
        self.assertEqual(len(order), len(failed))
        self.assertTrue(all(r["why"] for r in order))
        sev = [SEV.get(r["severity"], 5) for r in order]
        self.assertEqual(sev, sorted(sev), "severity first")
        self.assertEqual(assess_cards.view(project)["priority"], order)

        filed = by_key(record)["security.policy"]["id"]
        assess_cards.to_changes(project, [filed], person="Aino", persona="developer")
        self.assertNotIn(filed, [r["id"] for r in ranked(assess_cards.view(project))], "an open change is in hand")

        for q in ("What fixes should I prioritise and why?", "which findings matter most", "mitä korjaan ensin?",
                  "What should I fix first?"):
            self.assertTrue(asks_priorities(q), q)
        self.assertFalse(asks_priorities("How is the project going?"))
        out = ask(self.factory, "What fixes should I prioritize, and why?", persona="developer", project_id=project.pid)
        self.assertEqual(out["by"], "rule")
        self.assertEqual(out["navigate"]["route"], f"#/p/{project.pid}/assessment")
        self.assertIn("Fix these first", out["answer"])
        self.assertIn(order[0]["id"] if order[0]["id"] != filed else order[1]["id"], out["answer"])

    def test_FR_BA1_AC_18_before_an_assessment_rihma_says_to_run_one(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        out = ask(self.factory, "what should I fix first?", persona="developer", project_id=project.pid)
        self.assertIn("not been assessed yet", out["answer"])

    def test_FR_BA1_AC_18_each_finding_has_a_suggested_kind_with_why_and_is_filed_as_its_own_kind(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        assess.assess(project, person="Aino", persona="developer", which=no_scanner)
        order = ranked(assess_cards.view(project))
        self.assertTrue(all(r["suggested"] and r["suggested_why"] for r in order))
        self.assertEqual(suggest_class({"perspective": "security", "severity": "critical"})[0], "defect")
        self.assertEqual(suggest_class({"perspective": "compliance", "severity": "low"})[0], "new_requirement")
        self.assertEqual(suggest_class({"perspective": "architecture", "severity": "medium"})[0], "infra_change")
        self.assertEqual(suggest_class({"by": "model_proposed", "perspective": "security"})[0], "new_requirement")
        a, b = order[0]["id"], order[1]["id"]
        out = assess_cards.to_changes(project, [a, b], person="Aino", persona="developer",
                                      classes={a: "defect", b.lower(): "infra_change"})
        self.assertEqual([c["class"] for c in out["opened"]], ["defect", "infra_change"])
        with self.assertRaises(assess_cards.AssessmentRefused):
            assess_cards.to_changes(project, [order[2]["id"]], person="Aino", persona="developer",
                                    classes={order[2]["id"]: "wish"})


if __name__ == "__main__":
    unittest.main()
