"""Small things: a single workflow, an automation, an agentic capability (an assistant, an ops
agent) and an integration (docs/acceptance.md, rows W, A, C1, C2 and I; FR-AM6).

Each is delivered today as an HTTP service on the paved road with its capability pack; the pack
says what kind of deliverable it is. The automation is proposed as a small capability and ships with
its faces (kernel/capability_template.py); faces for the others (an MCP tool, an A2A card, a chat
embed) are pending: docs/portability.md.
"""

from kernel import demo
from kernel.canon import Canon
from kernel.deliver import latest_release
from kernel.profiles import PROFILE_QUESTION, PROFILES

from .scripts import OWNER, AcceptanceCase, payloads


class SmallThingsTest(AcceptanceCase):
    def profile(self, p) -> dict:
        return payloads(p, "profile_chosen")[-1]

    def requirement_provenance(self, p) -> set:
        return {r["provenance"] for r in p.read("spec.json")["requirements"]}

    def test_FR_AM6_AC_1_a_single_workflow_is_proposed_as_an_agentic_workflow_and_delivered_with_its_pack(self):
        p = self.need("purchases", mode="mixed", maturity="explore")
        chosen = self.profile(p)
        self.assertEqual((chosen["profile"], chosen["basis"]["keywords"]), ("agentic_workflow", ["workflow"]))
        canon = Canon(p)
        seed = next(q for q in canon.questions() if q["text"].startswith("Which of the agent's actions need"))
        self.assertEqual(seed["status"], "assumed")                     # the profile's own question, assumed
        self.assertEqual([c["refs"]["question"] for c in canon.cards(kind="question")], ["Q-001"])
        self.answer_blocking(p)
        out, decided = self.ship(p)
        self.assertEqual(decided, [])
        pack = self.assertDelivered(p, out, "preview")
        self.assertEqual((pack["profile"], pack["deliverable"]), ("agentic_workflow", "capability_pack"))
        self.assertTraced(p, decided_by={OWNER})

    def test_FR_AM6_AC_2_an_automation_in_assume_mode_runs_to_a_release_with_no_person_and_says_what_it_assumed(self):
        p = self.need("invoices", mode="assume", maturity="explore")
        chosen = self.profile(p)
        self.assertEqual((chosen["profile"], chosen["basis"]["confidence"]), ("automation", "uncertain"))
        self.assertEqual(chosen["basis"]["why"], "only one keyword names it (automate)")
        self.assertEqual(Canon(p).cards(kind="question"), [])           # nothing goes to a person
        out, decided = self.ship(p)
        self.assertEqual(decided, [])
        self.assertIn("assumption", self.requirement_provenance(p))
        self.assertNotIn("customer-confirmed", self.requirement_provenance(p))
        pack = self.assertDelivered(p, out, "preview")
        self.assertEqual(pack["profile"], "automation")                 # a small capability, with its faces
        t = self.assertTraced(p, decided_by=set())
        self.assertEqual(len(t["assumed"]), len(Canon(p).questions()))  # every answer the run rests on, on record

    def test_FR_AM6_AC_3_an_assistant_waits_for_a_person_to_say_which_kind_of_work_it_is_then_ships_as_a_capability(self):
        p = self.need("travel", mode="mixed", maturity="demo")
        canon = Canon(p)
        which = next(q for q in canon.questions() if q["text"] == PROFILE_QUESTION)
        self.assertTrue(which["blocking"])
        self.assertEqual(which["options"][:2], ["Agent or assistant (agentic_workflow)",
                                                "Harness engineering (harness_engineering)"])
        waiting = self.run_chain(p)
        self.assertEqual((waiting["state"], waiting["stage"]), ("waiting", 2))
        out, decided = self.ship(p)
        self.assertEqual(decided, [("question", "business_owner"), ("approval", "business_owner")])
        self.assertEqual(self.profile(p)["basis"], {"by": "Aino", "question": which["id"]})
        pack = self.assertDelivered(p, out, "demo")
        self.assertEqual((pack["profile"], pack["deliverable"]), ("agentic_workflow", "capability_pack"))
        refusal = next(r for r in p.read("spec.json")["requirements"] if "only from the published" in r["statement"])
        self.assertEqual(refusal["acceptance"][0]["then"][:3], "422")  # it refuses what it may not answer
        self.assertTraced(p, decided_by={OWNER})

    def test_FR_AM6_AC_4_an_ops_agent_delivers_a_report_with_a_holdout_the_builder_never_saw(self):
        p = self.need("access", mode="assume", maturity="demo", requested_by="Sanna")
        chosen = self.profile(p)
        self.assertEqual(chosen["profile"], "ops_agent")
        own = {s["text"] for s in PROFILES["ops_agent"]["seed_questions"]}      # the framework, what it may read
        seeds = [q for q in Canon(p).questions() if q["text"] in own]
        self.assertEqual((len(seeds), {q["status"] for q in seeds}), (2, {"assumed"}))
        out, decided = self.ship(p)
        self.assertEqual(decided, [("approval", "business_owner")])
        results = latest_release(p)["holdouts"]["results"]
        self.assertEqual([(r["criterion"], r["verdict"]) for r in results], [("R-1-AC-2", "passed")])
        pack = self.assertDelivered(p, out, "demo")
        self.assertEqual((pack["profile"], pack["deliverable"]), ("ops_agent", "report"))
        self.assertTraced(p, decided_by={OWNER})

    def test_FR_AM6_AC_5_an_integration_is_built_by_its_own_code_and_tests_and_lands_on_the_preview(self):
        p = self.need("webhook", mode="assume", maturity="explore", requested_by="Pekka")
        self.assertEqual(self.profile(p)["profile"], "integration")
        canon = Canon(p)
        dead = next(q for q in canon.questions() if q["text"] == "What happens to a message that cannot be delivered?")
        self.assertEqual(dead["status"], "assumed")
        out, decided = self.ship(p, demo.ScriptedCell(demo.WEBHOOK, self.clock))
        self.assertEqual(decided, [])
        r3 = p.read("spec.json")["requirements"][2]
        self.assertEqual((r3["sources"], r3["provenance"]), ([dead["id"]], "assumption"))
        gates = payloads(p, "gate")
        self.assertEqual([(g["task"], g["verdict"]) for g in gates], [("T-001", "passed"), ("T-002", "passed"),
                                                                      ("T-003", "passed")])
        self.assertEqual({v for g in gates for v in g["signals"].values()}, {"passed"})
        pack = self.assertDelivered(p, out, "preview")
        self.assertEqual((pack["profile"], pack["deliverable"]), ("integration", "product"))
        self.assertTraced(p, decided_by=set())
