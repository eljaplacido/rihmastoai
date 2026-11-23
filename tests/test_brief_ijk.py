"""The brief's sections I, J and K, measured against what the kernel really does (task V-68).

- FR-I4: the loops and who holds authority in each: operational healing with every model
  offline, engineering repair on the gate with a person only outside the pre-approved path,
  and product adaptation decided by the product's owners.
- FR-J1: the factory heals what it safely can (a release that cannot start in production is
  reverted to the last green release; a dead holder never strands a lane) and tells a person
  when it cannot (a revert that fails opens an incident instead of pretending).
- FR-K1: failures make the factory stronger: a lesson recurring across products becomes a check
  the next product's gate enforces, lessons are grouped by what they say rather than how, and
  a person's refusal of a factory proposal stands.

What is not built (paired evaluation, staggered impact estimates, restarting a crashed
production process, sweeps and eval cases) is recorded in contract/deferred/ijk.json, not tested.
Products here are real: they are built by the fake cells, judged by the real gate, and delivered
as local processes, which are stopped in cleanup.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import (GOOD_ROUTES, GOOD_TEST, FactoryTestCase, good_cell, lazy_cell, model,  # noqa: E402
                           no_findings)
from factory_fakes import script as base_script  # noqa: E402
from test_deliver import BAD_ROUTES  # noqa: E402
from test_operate import OperateTestCase  # noqa: E402

import kernel.model as kmodel  # noqa: E402
from kernel import operate  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.change import apply_change, submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.deliver import latest_release  # noqa: E402
from kernel.dispatch import build_task, envelope, resolve_escalations  # noqa: E402
from kernel.filelock import LockHeld  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.learn import apply_accepted, default_checks, factory_project, immune_memory, propose  # noqa: E402
from kernel.model import FakeModel, GnomonModel, ModelError  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
DEFECT = "Adding an item with an empty name crashes with 500"

# A repair that meets the regression criterion a defect left: an empty name is a 400, not a 500.
REPAIR_TEST = GOOD_TEST + '''
    def test_R_1_AC_3_an_empty_name_is_refused_with_400(self):
        status, body, _ = handle("POST", "/items", {"name": ""})
        self.assertEqual(status, 400)
'''

# The check another product's failure taught the factory, met by a builder that carries it.
LEARNED_TEST = '''import unittest

import app.routes  # noqa: F401
from app.server import handle


class LearnedCheckTest(unittest.TestCase):
    def test_FD_1_AC_1_an_empty_name_is_refused_with_400_not_500(self):
        status, body, _ = handle("POST", "/items", {"name": ""})
        self.assertEqual(status, 400)
'''

# Release 2's data migration trips on a legacy record that only production holds: it starts on
# fresh data (candidate, twin, staging) and cannot start on production's.
MIGRATING_ROUTES = GOOD_ROUTES + '''

if any(item.get("name") == "legacy-record" for item in load_data("items", [])):
    raise RuntimeError("the migration cannot read the legacy record")
'''
# A release that reads data format v1 only.
STRICT_ROUTES = GOOD_ROUTES + '''

if load_data("format", "v1") != "v1":
    raise RuntimeError("this release reads data format v1 only")
'''
# A migration that marks production's data as v2 and stops half-way: the last green release can
# no longer read what it left behind.
HALF_MIGRATING_ROUTES = GOOD_ROUTES + '''

if any(item.get("name") == "legacy-record" for item in load_data("items", [])):
    save_data("format", "v2")
    raise RuntimeError("the migration stopped half-way")
'''


def _write(lane_path, rel_path, text):
    Path(lane_path, rel_path).write_text(text, encoding="utf-8", newline="\n")


def _result(steps=5):
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": steps, "model": "fake-builder",
            "output": "done"}


def crashing_cell(lane_path, prompt):
    """Builds the product with a defect: an empty name crashes (500) instead of a 400."""
    _write(lane_path, "app/routes.py", BAD_ROUTES)
    _write(lane_path, "tests/test_items.py", GOOD_TEST)
    return _result()


def repair_cell(lane_path, prompt):
    _write(lane_path, "app/routes.py", GOOD_ROUTES)
    _write(lane_path, "tests/test_items.py", REPAIR_TEST)
    return _result()


def learned_cell(lane_path, prompt):
    _write(lane_path, "app/routes.py", GOOD_ROUTES)
    _write(lane_path, "tests/test_learned.py", LEARNED_TEST)
    return _result()


def worded(then: str) -> FakeModel:
    """The scripted model, except that triage words the defect's regression check as ``then``."""
    def answer(prompt, role):
        if "Classify a piece of feedback" in prompt:
            return "```json\n" + json.dumps({"class": "defect", "requirements": ["R-1"], "summary": "empty name",
                                              "regression": {"given": "-", "when": "POST /items with an empty name",
                                                             "then": then}}) + "\n```"
        return base_script(prompt, role)
    return FakeModel(answer)


class _Compiled(FactoryTestCase):
    def compiled(self, title="Equipment loans"):
        p = self.new(mode="assume", title=title)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def defect(self, p, *, text=DEFECT, using=None):
        card = submit(p, persona="end_user", person="Tester", text=text)
        triage(p, card["id"], model=using or model())
        return apply_change(p, card["id"], model=using or model())

    def lanes(self, name="lanes"):
        return Lanes(self.tmp / name, size=1)


# -- FR-I4: four loops, separate authority ------------------------------------------------------------

class RepairLoopTest(_Compiled):
    def test_FR_I4_AC_2_a_defect_is_repaired_on_the_gate_with_no_decision_and_a_person_only_when_the_gate_refuses(self):
        p = self.compiled()
        lanes = self.lanes()
        first = build_task(p, "T-001", lanes=lanes, cell_runner=crashing_cell, verifier_runner=no_findings)
        self.assertEqual(first["status"], "merged")
        # A defect is a pre-approved class: it re-enters the contract without anyone's decision.
        out = self.defect(p)
        self.assertEqual((out["class"], out["changed"]), ("defect", ["R-1"]))
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "pending")
        self.assertEqual(Canon(p).decisions(), [])
        # A repair the gate does not warrant goes to a person.
        lazy = build_task(p, "T-001", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=0)
        self.assertEqual(lazy["status"], "escalated")
        card = Canon(p).get_card(lazy["card"])
        self.assertEqual(card["kind"], "escalation")
        self.assertIn("R-1-AC-3", card["body"])
        with self.assertRaises(DecisionRefused):           # not the operations loop's call
            Canon(p).decide(card["id"], "retry", person="Olli", persona="operations")
        Canon(p).decide(card["id"], "retry", person="Dev", persona="developer")
        self.assertEqual(resolve_escalations(p), [card["id"]])
        # A repair the gate warrants merges under the policy, with no person.
        fixed = build_task(p, "T-001", lanes=lanes, cell_runner=repair_cell, verifier_runner=no_findings)
        self.assertEqual(fixed["status"], "merged", fixed)
        self.assertEqual(fixed["permitted_by"], "policy:auto-merge-warranted")
        gate = fixed["rounds"][-1]["gate"]
        self.assertTrue(gate["warranted"])
        trace = next(s for s in gate["signals"] if s["name"] == "trace")
        self.assertIn("R-1-AC-3", trace["native"]["criteria"])
        merged = [r["event"]["payload"] for r in p.ledger().of_kind("merged")]
        self.assertEqual([m["permitted_by"] for m in merged], ["policy:auto-merge-warranted"] * 2)
        # The only decision a person took in the repair loop was the escalation.
        self.assertEqual([(d["kind"], d["persona"]) for d in Canon(p).decisions()], [("escalation", "developer")])


class AdaptationLoopTest(_Compiled):
    def test_FR_I4_AC_3_a_change_to_the_product_takes_effect_only_when_its_business_or_product_owner_accepts_it(self):
        p = self.compiled()
        canon = Canon(p)
        spec_before = p.read("spec.json")
        change = submit(p, persona="product_owner", person="Pekka", text="The approver should be optional")
        self.assertEqual(triage(p, change["id"], model=model())["class"], "change_request")
        new = submit(p, persona="end_user", person="Tester",
                     text="We also want a new feature: export the loans as a spreadsheet")
        self.assertEqual(triage(p, new["id"])["class"], "new_requirement")
        for card in (change, new):
            with self.assertRaises(PermissionError):
                apply_change(p, card["id"], model=model())
            for persona in ("developer", "operations", "it", "end_user"):
                with self.assertRaises(DecisionRefused):
                    canon.decide(card["id"], "accept", person="Someone", persona=persona)
        canon.decide(new["id"], "reject", person="Pekka", persona="product_owner", reason="not now")
        with self.assertRaises(PermissionError):           # a rejected change is never applied
            apply_change(p, new["id"], model=model())
        self.assertEqual(p.read("spec.json"), spec_before)
        canon.decide(change["id"], "accept", person="Pekka", persona="product_owner", reason="optional is fine")
        out = apply_change(p, change["id"], model=model())
        self.assertEqual(out["changed"], ["R-2"])
        r2 = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        self.assertEqual((r2["provenance"], r2["decided_by"]), ("customer-confirmed", "Pekka"))
        self.assertNotEqual(p.read("spec.json"), spec_before)


class OperationalLoopTest(OperateTestCase):
    def test_FR_I4_AC_1_with_models_offline_a_bad_release_is_rolled_back_and_a_failing_probe_opens_an_incident(self):
        missing = (Path(tempfile.gettempdir()) / "no-gnomon-anywhere" / "gnomon").as_posix()
        attempts = []
        real = kmodel.run_gnomon_task

        def counted(*args, **kwargs):
            attempts.append(kwargs.get("role"))
            return real(*args, **kwargs)

        with mock.patch.dict(os.environ, {kmodel.GNOMON_CMD_ENV: missing}), \
                mock.patch("kernel.model.run_gnomon_task", counted), \
                mock.patch("kernel.dispatch.run_gnomon_task", counted), \
                mock.patch("kernel.gate.run_gnomon_task", counted):
            with self.assertRaises(ModelError):              # every model is offline
                GnomonModel(self.tmp / "analyst-lane").ask("Are you there?", role="analyst")
            self.assertEqual(attempts, ["analyst"])
            attempts.clear()
            self.assertEqual(self.ship()["state"], "done")
            rev1 = self.main()
            self.traffic()
            self.commit_routes(BAD_ROUTES, "Empty names crash")
            out = self.ship()
            self.crash("production")
            tick = operate.tick(self.project)
        self.assertEqual(attempts, [])                        # the loop never reached for a model
        self.assertEqual((out["state"], out["failed_step"]), ("failed", "canary:production"))
        self.assertEqual(latest_release(self.project)["rollback"]["kept"], {"release": 1, "revision": rev1})
        self.assertIsNone(roadmod.slot_state(self.project, "production", "candidate"))
        self.assertFalse(tick["probes"][0]["ok"])
        incidents = sorted(c["refs"]["release"] for c in self.canon.cards(kind="incident"))
        self.assertEqual(incidents, [1, 2])                   # the probe's (release 1) and the rollback's
        kinds = [r["event"]["kind"] for r in self.project.ledger().records()]
        self.assertIn("rolled_back", kinds)
        self.assertIn("probe_failed", kinds)
        # People approved the releases; nobody decided the abort, the rollback or the incidents.
        self.assertEqual([d["kind"] for d in self.canon.decisions()], ["validation", "deploy_gate"] * 2)


# -- FR-J1: heals what it safely can --------------------------------------------------------------------

class HealingTest(OperateTestCase):
    def test_FR_J1_AC_1_a_release_that_cannot_start_in_production_is_reverted_to_the_last_green_release(self):
        self.assertEqual(self.ship()["state"], "done")
        rev1 = self.main()
        self.assertEqual(self.send("production", "POST", "/items", {"name": "legacy-record"})["status"], 201)
        self.commit_routes(MIGRATING_ROUTES, "Migrate the items")
        out = self.ship()
        self.assertEqual((out["state"], out["release"], out["failed_step"]), ("failed", 2, "promote:production"))
        canary = self.step(out, "canary:production")
        self.assertEqual(canary["native"]["decision"], "promote")       # it looked healthy until it met real data
        rel = latest_release(self.project)
        self.assertEqual(rel["rollback"]["restored"], {"release": 1, "revision": rev1})
        self.assertTrue(rel["rollback"]["current_health"]["ok"])
        self.assertIn("no person involved", rel["rollback"]["by"])
        self.assertEqual(self.health("production")["version"], rev1[:12])
        self.assertEqual(roadmod.slot_state(self.project, "production")["release"], 1)
        names = [i["name"] for i in self.send("production", "GET", "/items")["json"]]
        self.assertIn("legacy-record", names)                            # served again, on the same data
        incident = self.canon.get_card(out["incident"])
        self.assertEqual((incident["kind"], incident["state"], incident["refs"]["release"]), ("incident", "open", 2))
        self.assertEqual([d["kind"] for d in self.canon.decisions()], ["validation", "deploy_gate"] * 2)

    def test_FR_J1_AC_3_when_the_revert_itself_fails_a_person_is_told_and_nothing_claims_to_serve(self):
        self.commit_routes(STRICT_ROUTES, "Read data format v1 only")
        self.assertEqual(self.ship()["state"], "done")
        self.assertEqual(self.send("production", "POST", "/items", {"name": "legacy-record"})["status"], 201)
        self.commit_routes(HALF_MIGRATING_ROUTES, "Migrate the items to format v2")
        out = self.ship()
        self.assertEqual((out["state"], out["release"], out["failed_step"]), ("failed", 2, "promote:production"))
        rel = latest_release(self.project)
        self.assertIn("error", rel["rollback"])
        self.assertNotIn("restored", rel["rollback"])
        incident = self.canon.get_card(out["incident"])
        self.assertEqual(incident["title"], "Rollback of release 2 failed")
        self.assertTrue(incident["blocking"])
        self.assertEqual(incident["state"], "open")
        self.assertIn("operations", incident["deciders"])
        self.assertIn("The rollback failed", incident["body"])
        self.assertIsNone(roadmod.slot_state(self.project, "production"))   # nothing pretends to serve
        data = self.project.path("envs", "production", "data", "format.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(data), "v2")                              # why the revert was not safe
        self.assertNotIn("rolled_back", [r["event"]["kind"] for r in self.project.ledger().records()])
        failed = [r["event"]["payload"] for r in self.project.ledger().of_kind("release_failed")]
        self.assertEqual(failed[-1]["incident"], incident["id"])


class DeadHolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-lanes-"))
        self.addCleanup(roadmod.rmtree, self.tmp)

    def test_FR_J1_AC_2_a_lane_whose_holder_died_is_free_again_without_anyone_releasing_it(self):
        root = self.tmp / "lanes"
        child = (f"import sys, time\nsys.path.insert(0, {str(REPO)!r})\nfrom pathlib import Path\n"
                 f"from kernel.lanes import Lanes\n"
                 f"with Lanes(Path({str(root)!r}), size=1).lease('crashed:T-001'):\n"
                 f"    print('held', flush=True)\n    time.sleep(120)\n")
        proc = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.assertEqual(proc.stdout.readline().strip(), "held")
        proc.stdout.close()
        with self.assertRaises(LockHeld):                    # a living holder's lane is never shared
            with Lanes(root, size=1).lease("next:T-002", wait=0):
                pass
        proc.kill()                                          # the holder dies mid-task, releasing nothing
        proc.wait(10)
        started = time.monotonic()
        with Lanes(root, size=1).lease("next:T-002", wait=10, poll=0.05) as lane:
            self.assertEqual(lane.name, "lane-1")
            lease = json.loads((root / ".lane-1.lease.json").read_text(encoding="utf-8"))
            self.assertEqual(lease["holder"], "next:T-002")
        self.assertLess(time.monotonic() - started, 10)


# -- FR-K1: stronger from failures ----------------------------------------------------------------------

class AntifragileTest(_Compiled):
    def accept_the_lesson(self):
        a, b = self.compiled("Loans A"), self.compiled("Loans B")
        self.defect(a)
        self.defect(b)
        [card] = propose(self.factory)
        Canon(factory_project(self.factory)).decide(card["id"], "approve", person="Aino", persona="business_owner")
        self.assertEqual(len(apply_accepted(self.factory)), 1)
        return a, b

    def test_FR_K1_AC_1_a_lesson_two_products_paid_for_is_enforced_by_the_next_products_gate(self):
        a, b = self.accept_the_lesson()
        c = self.compiled("Loans C")
        contract = c.read("contract.json")
        task = next(t for t in contract["tasks"] if "FD-1-AC-1" in t["criteria"])
        text = envelope(c, contract, task["id"], base="0" * 40)
        self.assertIn("**FD-1-AC-1**", text)                  # the builder is told about it
        self.assertIn("400, not 500", text)
        fd = next(r for r in contract["requirements"] if r["id"] == "FD-1")
        self.assertIn(a.pid, fd["statement"])
        self.assertIn(b.pid, fd["statement"])
        lanes = self.lanes()
        forgetful = build_task(c, task["id"], lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings,
                               max_rounds=0)
        self.assertEqual(forgetful["status"], "escalated")    # the gate refuses work that skips the lesson
        trace = next(s for s in forgetful["rounds"][-1]["gate"]["signals"] if s["name"] == "trace")
        self.assertEqual((trace["verdict"], trace["native"]["unnamed"]), ("failed", ["FD-1-AC-1"]))
        Canon(c).decide(forgetful["card"], "retry", person="Dev", persona="developer")
        resolve_escalations(c)
        careful = build_task(c, task["id"], lanes=lanes, cell_runner=learned_cell, verifier_runner=no_findings)
        self.assertEqual(careful["status"], "merged", careful)
        ff = next(s for s in careful["rounds"][-1]["gate"]["signals"] if s["name"] == "fail_first")
        self.assertEqual(ff["verdict"], "passed")             # its test failed before the behaviour existed

    def test_FR_K1_AC_2_lessons_are_one_class_whatever_their_word_order_or_case(self):
        a, b, c = self.compiled("Loans A"), self.compiled("Loans B"), self.compiled("Loans C")
        self.defect(a, using=worded("An empty name is refused with 400"))
        self.defect(b, using=worded("Refused with 400: the name is EMPTY"))
        self.defect(c, using=worded("The loan list shows who approved each loan"))
        memory = {m["class"]: m["projects"] for m in immune_memory(self.factory)}
        self.assertEqual(len(memory), 2)
        self.assertIn(sorted([a.pid, b.pid]), memory.values())
        self.assertIn([c.pid], memory.values())
        cards = propose(self.factory)
        self.assertEqual(len(cards), 1)                       # only the class two products share
        self.assertEqual(sorted(cards[0]["payload"]["projects"]), sorted([a.pid, b.pid]))

    def test_FR_K1_AC_3_a_change_the_factory_proposes_to_itself_is_promoted_only_by_a_person_and_a_refusal_stands(self):
        a, b = self.compiled("Loans A"), self.compiled("Loans B")
        self.defect(a)
        self.defect(b)
        [card] = propose(self.factory)
        self.assertEqual(apply_accepted(self.factory), [])    # proposed is not promoted
        fp = factory_project(self.factory)
        with self.assertRaises(DecisionRefused):
            Canon(fp).decide(card["id"], "approve", person="factory", persona="business_owner")
        Canon(fp).decide(card["id"], "reject", person="Aino", persona="business_owner", reason="too strict for now")
        self.assertEqual(apply_accepted(self.factory), [])
        self.assertEqual(default_checks(self.factory), [])
        self.defect(self.compiled("Loans D"))                 # the lesson recurs in a third product
        self.assertEqual(propose(self.factory), [])           # the refusal is remembered
        later = self.compiled("Loans E")
        self.assertFalse(any(r["id"].startswith("FD-") for r in later.read("contract.json")["requirements"]))


if __name__ == "__main__":
    unittest.main()
