"""The holdout custody keeps what describes a holdout scenario: the scenarios, and the reasons people
give when they rule on one (FR-O3-AC-3). The holdout prompt says each of its rules once (FR-O3-AC-4)."""

import hashlib
import json
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.compile import author_holdouts, compile_project, holdout_prompt  # noqa: E402
from kernel.evidence_pack import export  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.rulings import CUSTODY_FILE, HELD_REASON, apply_rulings, held_reason, open_ruling  # noqa: E402
from kernel.spec import interface_of, make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
TOKEN = "zq-held-sprocket-77"           # a scenario's own value, which only the custody may hold
REASON = f"The scenario expected {TOKEN} on GET /items before any step created it."
FAILING = [{"criterion": "R-1-AC-2", "failed_step": 2, "request": {"method": "GET", "path": "/items"},
            "expected": {"expect_contains": "drill"}, "observed": {"status": 200, "body": []}}]


def project_files_text(project) -> str:
    return "".join(f.read_text(encoding="utf-8", errors="replace") for f in sorted(project.dir.rglob("*"))
                   if f.is_file() and ".git" not in f.parts and "repo.git" not in f.parts)


class CustodyCase(FactoryTestCase):
    def compiled(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        author_holdouts(p, model=model())
        return p

    def ruling(self, p) -> dict:
        release = {"revision": "0" * 40,
                   "steps": [{"step": "holdouts:demo", "outcome": "failed", "native": {"failing": FAILING}}]}
        return open_ruling(p, 1, release)


class RulingReasonCustodyTest(CustodyCase):
    def test_FR_O3_AC_3_a_rulings_reason_is_kept_in_the_custody_and_the_ledger_holds_its_hash_and_length(self):
        p = self.compiled()
        card = self.ruling(p)
        Canon(p).decide(card["id"], "scenario_defect", person="Dev", persona="developer", reason=REASON)
        prompts = []

        def recording(prompt, role):
            prompts.append(prompt)
            return model().ask(prompt, role=role)

        done = apply_rulings(p, model=FakeModel(recording))
        self.assertEqual(done[0]["reauthored"], ["R-1-AC-2"])
        self.assertIn(f"Their reason: {REASON}", prompts[0])           # the holdout author still hears it
        # the custody holds the reason, outside the project folder
        custody = p.holdouts_dir / CUSTODY_FILE
        self.assertFalse(custody.resolve().is_relative_to(p.dir.resolve()))
        self.assertIn(TOKEN, custody.read_text(encoding="utf-8"))
        # the ledger holds its sha256, its length and a pointer, on the decision and on the rewrite
        pointer = {"custody": "holdout", "file": CUSTODY_FILE,
                   "sha256": hashlib.sha256(REASON.encode("utf-8")).hexdigest(), "length": len(REASON)}
        decision = next(r["event"]["payload"] for r in p.ledger().of_kind("decision")
                        if r["event"]["payload"]["card"] == card["id"])
        self.assertEqual(decision["reason_custody"], pointer)
        authored = p.ledger().of_kind("holdouts_authored")[-1]["event"]["payload"]
        self.assertEqual((authored["reauthored_because"], authored["ruled_by"]), (pointer, "Dev"))
        self.assertEqual(held_reason(p, pointer["sha256"]), REASON)
        self.assertTrue(p.ledger().verify().intact)
        # neither the ledger, the canon nor anything else in the project folder holds the reason
        self.assertNotIn(TOKEN, p.path("ledger.jsonl").read_text(encoding="utf-8"))
        self.assertNotIn(TOKEN, project_files_text(p))
        decided = Canon(p).get_card(card["id"])["decision"]
        self.assertEqual((decided["reason"], decided["reason_custody"]), (HELD_REASON, pointer))
        # and so neither does the evidence pack, which exports the ledger whole
        pack = export(p, self.tmp / "pack", person="Cora", persona="compliance")
        with zipfile.ZipFile(pack) as z:
            text = "".join(z.read(n).decode("utf-8") for n in z.namelist())
        self.assertNotIn(TOKEN, text)
        self.assertIn(pointer["sha256"], text)

    def test_FR_O3_AC_3_a_reason_altered_in_the_custody_is_not_used(self):
        p = self.compiled()
        card = self.ruling(p)
        Canon(p).decide(card["id"], "scenario_defect", person="Dev", persona="developer", reason=REASON)
        custody = p.holdouts_dir / CUSTODY_FILE
        line = json.loads(custody.read_text(encoding="utf-8"))
        line["reason"] = "something else entirely"
        custody.write_text(json.dumps(line) + "\n", encoding="utf-8", newline="\n")
        prompts = []
        apply_rulings(p, model=FakeModel(lambda pr, role: prompts.append(pr) or model().ask(pr, role=role)))
        self.assertNotIn("something else entirely", prompts[0])
        self.assertIn(f"Their reason: scenario defect ruled on {card['id']}", prompts[0])

    def test_FR_O3_AC_3_decisions_on_every_other_card_kind_keep_their_reason_in_the_canon(self):
        p = self.compiled()
        canon = Canon(p)
        card = canon.card("approval", "Approve the plan")
        canon.decide(card["id"], "reject", person="Aino", persona="business_owner", reason=f"misses {TOKEN}")
        self.assertEqual(canon.get_card(card["id"])["decision"]["reason"], f"misses {TOKEN}")
        self.assertNotIn("reason_custody", canon.get_card(card["id"])["decision"])
        self.assertEqual(canon.decisions()[-1]["reason"], f"misses {TOKEN}")
        logged = p.ledger().of_kind("decision")[-1]["event"]["payload"]
        self.assertEqual(set(logged), {"id", "card", "kind", "verdict", "person", "persona", "refs"})
        self.assertFalse((p.holdouts_dir / CUSTODY_FILE).exists())


class HoldoutPromptTest(CustodyCase):
    RULES = ("You write acceptance scenarios", "The builder never sees them.",
             "Use exactly these methods and paths", "Write one scenario for each of these criteria",
             "All scenarios run one after another against ONE deployment", "never assume an empty store",
             "Create your own data with values unique to the scenario",
             "check for the presence or absence of *that* data, not for an empty list",
             "When a criterion speaks of seeded or existing data, never guess its ids: list it first with a GET "
             "step and reuse an id from that answer",
             "Each step has a method, a path, an optional JSON body, and the expectations",
             "- expect_status: an integer", "- expect_json: an optional object", "- expect_contains: an optional",
             "- expect_not_contains: an optional", "- max_ms: an optional latency limit, for probes",
             "in a step's path or body becomes that key's value in the previous step's JSON response",
             "a value in braces in the interface, such as {id}", '"{{prev.id}}"', '"{{prev.0.id}}"',
             "Answer with this JSON in a ```json block")

    def test_FR_O3_AC_4_the_holdout_prompt_explains_reusing_earlier_values_once_and_keeps_every_rule(self):
        p = self.compiled()
        spec = p.read("spec.json")
        rows = [r for r in p.read("checkplan.json")["checks"] if r["kind"] != "test"]
        ruling = {"reason": "the scenario guessed an id", "evidence": FAILING}
        for text in (holdout_prompt(spec, rows), holdout_prompt(spec, rows, ruling)):
            flat = " ".join(text.split())
            self.assertEqual(flat.count("{{prev.<key>}}"), 1)                  # one explanation of reuse
            self.assertEqual(flat.count("previous step's JSON response"), 1)
            self.assertEqual(flat.count("{{prev."), 3)                          # it, and its two examples
            self.assertNotIn("comes from an earlier step's response", flat)
            for rule in self.RULES:
                self.assertIn(rule, flat)
            for r in rows:
                self.assertIn(f"- {r['criterion']} ({r['kind']}): {r['then']}", text)
            for e in interface_of(spec):
                self.assertIn(f"- {e['method']} {e['path']}:", text)
        self.assertIn("Their reason: the scenario guessed an id", holdout_prompt(spec, rows, ruling))


if __name__ == "__main__":
    unittest.main()
