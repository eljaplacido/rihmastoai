"""The brief's sections R, S and T as the code has them (task V-73).

R. User validation: a tester's observation is signed, classified, linked to the requirements it
names and routed back (FR-R2); the business decides a release's validation with the holdout report
in front of it (FR-R3).
S. The canon: agents propose and people decide, nothing becomes true without the gate, and a
transcript is evidence, not truth (FR-S3).
T. The cockpit for every party: a customer's view (an embed) shows nothing internal and IT's inbox
holds environment and technical decisions only (FR-T2); the factory's reads reach other tools as
views, and everything another tool sends in ends as a proposal (FR-T3).

What the brief asks and the code does not do yet is recorded, with the reason, in
contract/deferred/rst.json. Every test drives the real kernel; the brief itself is one of the inputs.
The brief is private: in a checkout without intake/ (the public repository) the tests that take
its text as input skip, saying so, and the rest run.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, lazy_cell, model, no_findings, script  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_deliver import DeliveryTestCase  # noqa: E402

from adapters.gnomon_ingest import ingest  # noqa: E402
from kernel import embeds as kembeds  # noqa: E402
from kernel import signals as ksignals  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.change import apply_change, submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.deliver import deliver, latest_release  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.observations import observe  # noqa: E402
from kernel.roads import slot_state  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import evidence, health, now  # noqa: E402
from mcp.server import RihmaMCP  # noqa: E402

_cov = importlib.util.spec_from_file_location("spec_coverage", ROOT / "tools" / "spec_coverage.py")
spec_coverage = importlib.util.module_from_spec(_cov)
_cov.loader.exec_module(spec_coverage)

IDEA = "Our team keeps losing track of who borrowed the drills and laptops. We want a simple way to lend and return things."
GNOMON = Path(__file__).parent / "fixtures" / "gnomon"
# The factory's own brief, read by tools/spec_coverage.py and dogfooded as input. It is not shipped:
# without it, BRIEF is empty and the tests that need its text skip with the tool's own reason.
BRIEF_FILE = ROOT / "intake" / "gnomon-factory-brief.md"
BRIEF = ({r["id"]: r["text"] for r in spec_coverage.brief_requirements(BRIEF_FILE)} if BRIEF_FILE.is_file()
         else {})
needs_brief = unittest.skipUnless(BRIEF, spec_coverage.NO_BRIEF)
# Names that are not people: an agent, a model, the assistant, the factory and its harness.
AGENTS = ("agent", "model", "assistant", "factory", "claude", "gnomon", "kernel")


def seeded(test: FactoryTestCase, *, title="Equipment loans"):
    """A project taken from the idea to a compiled contract by the scripted analyst (assume mode)."""
    p = test.factory.new_project(title, mode="assume", maturity="demo")
    intake(p, IDEA, model=model(), requested_by="Aino")
    make_spec(p, model=model())
    compile_project(p)
    return p


def canon_state(p) -> tuple:
    """What a proposal must leave alone: the decisions, the questions, the assumptions, the spec and the contract."""
    canon = Canon(p)
    return (json.dumps(canon.decisions(), sort_keys=True), json.dumps(canon.questions(), sort_keys=True),
            json.dumps(canon.assumptions(), sort_keys=True), p.path("spec.json").read_bytes(),
            p.path("contract.json").read_bytes())


def tree_digest(root: Path) -> str:
    """Every file under ``root`` with its bytes: a read that writes anything changes it."""
    h = hashlib.sha256()
    for f in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(str(f.relative_to(root)).encode("utf-8"))
        h.update(f.read_bytes())
    return h.hexdigest()


def as_json(obj):
    """A read model as a client receives it: through JSON."""
    return json.loads(json.dumps(obj))


def mcp_call(server: RihmaMCP, name: str, **arguments) -> dict:
    out = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": name, "arguments": arguments}})
    result = out["result"]
    assert result["isError"] is False, result
    return result["structuredContent"]


# -- R. User validation ----------------------------------------------------------------------------

class ObservationRoutingTest(CockpitTestCase):
    def test_FR_R2_AC_1_a_testers_observation_is_signed_classified_and_given_its_way_back(self):
        p = self.built_project()
        observations = [
            ("Adding a drill with an empty name returns a 500 error", "defect", 5, False),
            ("The loan list should be sorted by the borrower's name instead", "change_request", 4, True),
            ("We also need a page that shows overdue loans", "new_requirement", 2, True),
            ("Can a loan be extended?", "question", 2, False),
        ]
        for text, cls, way_back, needs_decision in observations:
            status, body, _ = self.call("POST", f"/api/projects/{p.pid}/changes",
                                        {"persona": "end_user", "person": "Tiina", "text": text})
            self.assertEqual(status, 201, body)
            self.assertEqual((body["triage"]["class"], body["triage"]["way_back"], body["triage"]["needs_decision"]),
                             (cls, way_back, needs_decision), text)
            card = Canon(p).get_card(body["card"]["id"])
            self.assertEqual((card["kind"], card["state"]), ("change", "open"))
            self.assertEqual((card["payload"]["source"], card["payload"]["person"], card["payload"]["text"]),
                             ("end_user", "Tiina", text))
            self.assertEqual(card["payload"]["triage"]["class"], cls)
            self.assertEqual(card["deciders"], ["business_owner", "product_owner"])
        triaged = [r["event"]["payload"] for r in p.ledger().of_kind("change_triaged")]
        self.assertEqual([t["class"] for t in triaged], [o[1] for o in observations])
        # an observation is signed by a person: one with no person, or an agent's name, is refused
        for who in ("", "agent"):
            status, _, _ = self.call("POST", f"/api/projects/{p.pid}/changes",
                                     {"persona": "end_user", "person": who, "text": "it crashes"})
            self.assertEqual(status, 403, who)
        self.assertEqual(len(Canon(p).cards(kind="change")), len(observations))


def linking_script(prompt: str, role: str) -> str:
    """The analyst triages a tester's observation and names a requirement the spec does not have."""
    if prompt.startswith("Classify a piece of feedback"):
        return "```json\n" + json.dumps({"parts": [
            {"class": "defect", "requirements": ["R-1", "R-99"], "text": "an empty name crashes the add form",
             "summary": "crash on empty name",
             "regression": {"given": "-", "when": "POST /items with an empty name", "then": "400, not 500"}}]}) + "\n```"
    return script(prompt, role)


class ObservationLinkTest(FactoryTestCase):
    def test_FR_R2_AC_2_the_analyst_links_an_observation_only_to_requirements_the_spec_holds(self):
        p = seeded(self)
        card = submit(p, persona="end_user", person="Tiina", text="The add form crashes when I leave the name empty")
        rules = triage(p, submit(p, persona="end_user", person="Tiina", text="It crashes on an empty name")["id"])
        self.assertEqual((rules["by"], rules["requirements"]), ("rules", []))      # no analyst, no link
        result = triage(p, card["id"], model=FakeModel(linking_script))
        self.assertEqual((result["by"], result["class"], result["requirements"]), ("analyst", "defect", ["R-1"]))
        self.assertEqual(Canon(p).get_card(card["id"])["payload"]["triage"]["requirements"], ["R-1"])
        logged = [r["event"]["payload"] for r in p.ledger().of_kind("change_triaged") if r["event"]["payload"]["card"] == card["id"]]
        self.assertEqual(logged[-1]["requirements"], ["R-1"])
        spec_ids = {r["id"] for r in p.read("spec.json")["requirements"]}
        self.assertNotIn("R-99", spec_ids)


class ObservationRouteTest(FactoryTestCase):
    def test_FR_R2_AC_3_a_defect_goes_back_to_build_at_once_and_a_requirement_change_waits_for_the_business(self):
        p = seeded(self)
        out = build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=generic_cell,
                         verifier_runner=no_findings)
        self.assertEqual(out["status"], "merged")
        canon = Canon(p)
        defect = submit(p, persona="end_user", person="Tiina", text="Adding a drill with an empty name gives a 500 crash")
        triage(p, defect["id"], model=model())
        done = apply_change(p, defect["id"], model=model())                         # no business decision needed
        self.assertEqual((done["class"], done["way_back"], done["changed"]), ("defect", 5, ["R-1"]))
        r1 = next(r for r in p.read("contract.json")["requirements"] if r["id"] == "R-1")
        regression = r1["acceptance"][-1]
        self.assertEqual((regression["id"], regression["then"]), ("R-1-AC-3", "400, not 500"))
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "pending")        # its task goes back to build
        self.assertEqual(p.read("tasks.json")["T-001"]["reopened_by"], ["R-1"])
        self.assertEqual(p.meta["stage"], 5)
        self.assertEqual(canon.get_card(defect["id"])["state"], "resolved")
        self.assertEqual(canon.decisions(), [])                                     # nobody had to decide
        # a requirement change waits for a business decision
        change = submit(p, persona="end_user", person="Tiina", text="The approver should be optional")
        self.assertEqual(triage(p, change["id"], model=model())["class"], "change_request")
        r2_before = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        with self.assertRaises(PermissionError):
            apply_change(p, change["id"], model=model())
        with self.assertRaises(DecisionRefused):
            canon.decide(change["id"], "accept", person="Tiina", persona="end_user")
        self.assertEqual(next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2"), r2_before)
        canon.decide(change["id"], "accept", person="Aino", persona="product_owner", reason="optional is fine")
        applied = apply_change(p, change["id"], model=model())
        self.assertEqual((applied["way_back"], applied["changed"]), (4, ["R-2"]))
        r2 = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        self.assertEqual((r2["statement"], r2["provenance"], r2["decided_by"]),
                         ("A loan records the approver if given.", "customer-confirmed", "Aino"))


class ValidationDecisionTest(DeliveryTestCase):
    maturity = "pilot"

    def test_FR_R3_AC_1_the_release_waits_on_a_validation_card_with_the_holdout_report_only_the_business_decides(self):
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual((card["kind"], card["state"]), ("validation", "open"))
        self.assertEqual(card["verdicts"], ["accept", "fix", "change", "keep"])
        self.assertEqual(card["deciders"], ["business_owner", "product_owner"])
        rel = latest_release(self.project)
        ho = rel["holdouts"]
        self.assertEqual((ho["environment"], ho["verdict"], ho["failed"]), ("staging", "passed", 0))
        self.assertGreater(ho["scenarios"], 0)
        report = card["payload"]["holdouts"]
        self.assertEqual({k: v for k, v in report.items() if k != "slot"},
                         {k: ho[k] for k in ("environment", "verdict", "scenarios", "passed", "failed")})
        self.assertEqual(report.get("slot"), "twin")                        # holdouts ran in a twin (FR-H9)
        staging = slot_state(self.project, "staging", "current")
        self.assertEqual((card["payload"]["environment"], card["payload"]["url"]), ("staging", staging["base_url"]))
        self.assertIn(f"{ho['passed']} of {ho['scenarios']} holdout scenarios passed", card["body"])
        self.assertIn(staging["base_url"], card["body"])
        self.assertEqual(card["refs"]["requirements"], [r["id"] for r in self.project.read("contract.json")["requirements"]])
        for persona in ("end_user", "developer", "it", "operations", "concept_evaluator", "stakeholder"):
            with self.assertRaises(DecisionRefused):
                self.decide(card["id"], "accept", persona, person="Tiina")
        for name in AGENTS:
            with self.assertRaises(DecisionRefused):
                self.decide(card["id"], "accept", "business_owner", person=name)
        self.assertEqual(self.canon.get_card(card["id"])["state"], "open")
        self.assertEqual(self.canon.decisions(), [])
        again = deliver(self.project)                                         # still waiting on the business
        self.assertEqual((again["state"], again["waiting_on"]), ("waiting", card["id"]))

    def test_FR_R3_AC_2_keep_stops_the_release_and_change_hands_it_to_the_change_loop_each_recorded_with_its_person(self):
        first = deliver(self.project)
        self.decide(first["waiting_on"], "keep", "business_owner", person="Aino", reason="the current way is enough")
        kept = deliver(self.project)
        self.assertEqual((kept["state"], kept["failed_step"], kept["release"]), ("failed", "user_validation", 1))
        self.assertNotIn("handoff", kept)
        self.assertIn("keep by Aino (business_owner)", kept["reason"])
        self.assertEqual(self.step(kept, "user_validation")["native"]["verdict"], "keep")
        self.assertEqual(latest_release(self.project)["cards"][-1]["decision"]["person"], "Aino")
        self.assertEqual(deliver(self.project)["release"], 1)                 # a kept-back release is not retried
        # the same revision tried again as a new release: this time the product owner asks for a change
        second = deliver(self.project, new=True)
        self.assertEqual((second["state"], second["release"]), ("waiting", 2))
        self.decide(second["waiting_on"], "change", "product_owner", person="Pekka", reason="sort by borrower")
        changed = deliver(self.project)
        self.assertEqual((changed["state"], changed["failed_step"]), ("failed", "user_validation"))
        self.assertEqual(changed["handoff"], {"to": "change", "card": second["waiting_on"], "verdict": "change"})
        self.assertEqual(changed["waiting_on"], second["waiting_on"])
        decided = latest_release(self.project)["cards"][-1]["decision"]
        self.assertEqual((decided["verdict"], decided["person"], decided["persona"]), ("change", "Pekka", "product_owner"))
        # and accepted, it goes on
        third = deliver(self.project, new=True)
        self.decide(third["waiting_on"], "accept", "business_owner", person="Aino")
        self.assertEqual(deliver(self.project)["state"], "done")
        self.assertEqual([(d["verdict"], d["person"]) for d in self.canon.decisions()],
                         [("keep", "Aino"), ("change", "Pekka"), ("accept", "Aino")])


# -- S. The canon ------------------------------------------------------------------------------------

class AgentsProposeTest(FactoryTestCase):
    @needs_brief
    def test_FR_S3_AC_1_what_agents_file_waits_in_the_inbox_and_only_named_people_empty_it(self):
        p = seeded(self)
        canon = Canon(p)
        self.assertEqual((canon.decisions(), canon.cards()), ([], []))            # the analyst decided nothing
        # a builder that fails its gate, an outside observation and a coding agent over MCP: each files a card
        build_task(p, "T-002", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=lazy_cell,
                   verifier_runner=no_findings, max_rounds=1)
        observe(self.factory, "model_release", facts={"project": p.pid, "model": "glm-6"}, source="release feed")
        mcp = RihmaMCP(self.factory, person="Aino", persona="developer")
        filed = mcp_call(mcp, "rihma_report_change", pid=p.pid, text=BRIEF["FR-S3"])
        inbox = canon.cards()
        self.assertEqual(sorted(c["kind"] for c in inbox), ["change", "escalation", "update"])
        self.assertIn(filed["card"], [c["id"] for c in inbox])
        self.assertTrue(all(c["state"] == "open" and c["decision"] is None for c in inbox))
        self.assertEqual(canon.decisions(), [])
        # no agent, model or harness can decide one
        for c in inbox:
            for name in AGENTS:
                with self.assertRaises(DecisionRefused):
                    canon.decide(c["id"], c["verdicts"][0], person=name, persona=c["deciders"][0])
        self.assertEqual(len(canon.cards()), 3)
        self.assertEqual(canon.decisions(), [])
        # people empty it
        verdict = {"escalation": ("stop", "developer", "Pekka"), "update": ("decline", "product_owner", "Aino"),
                   "change": ("reject", "product_owner", "Aino")}
        for c in inbox:
            v, persona, person = verdict[c["kind"]]
            canon.decide(c["id"], v, person=person, persona=persona, reason="decided by a person")
        self.assertEqual(canon.cards(), [])
        self.assertEqual(sorted((d["kind"], d["person"]) for d in canon.decisions()),
                         [("change", "Aino"), ("escalation", "Pekka"), ("update", "Aino")])

    def test_FR_S3_AC_2_nothing_becomes_true_without_the_gate_a_cell_saying_done_is_not_merged(self):
        p = seeded(self)
        repo = p.path("repo.git")
        base = _git(repo, "rev-parse", "main")
        lanes = Lanes(self.tmp / "lanes", size=1)
        claimed = build_task(p, "T-001", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        self.assertEqual(claimed["status"], "escalated")                         # the cell answered "done"
        self.assertEqual(_git(repo, "rev-parse", "main"), base)                  # main did not move
        gates = [r["event"]["payload"] for r in p.ledger().of_kind("gate") if r["event"]["payload"]["task"] == "T-001"]
        self.assertTrue(gates and all(g["verdict"] != "passed" for g in gates))
        self.assertEqual(p.ledger().of_kind("merged"), [])
        state = {e["criterion"]: e["state"] for e in evidence(p)}
        self.assertEqual(state["R-1-AC-1"], "not_measured")
        # the same factory, a builder whose tests fail first and pass after: the gate passes it and only then is it true
        proved = build_task(p, "T-002", lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        self.assertEqual(proved["status"], "merged")
        self.assertNotEqual(_git(repo, "rev-parse", "main"), base)
        state = {e["criterion"]: e["state"] for e in evidence(p)}
        self.assertEqual((state["R-1-AC-1"], state["R-2-AC-1"]), ("not_measured", "verified"))

    def test_FR_S3_AC_3_a_transcript_is_evidence_not_truth(self):
        p = seeded(self)
        record = json.loads((GNOMON / "analyst-run.record.json").read_text(encoding="utf-8"))
        claim = dict(record, role="builder", verify="passed")                   # a run that says it passed T-003
        before = (canon_state(p), json.dumps(Canon(p).cards(state=None), sort_keys=True),
                  json.dumps(p.read("tasks.json", {}), sort_keys=True), json.dumps(evidence(p), sort_keys=True))
        n = len(p.ledger().records())
        e = ingest(p, claim, GNOMON / "analyst-run.jsonl", task="T-003", round_no=0)
        self.assertEqual((e["verdict"], e["tampered"], e["task"]), ("passed", False, "T-003"))
        self.assertEqual(len(p.ledger().records()), n + 1)                     # recorded: one ledger event
        self.assertEqual([r["event"]["kind"] for r in p.ledger().records()[n:]], ["gnomon_run"])
        after = (canon_state(p), json.dumps(Canon(p).cards(state=None), sort_keys=True),
                 json.dumps(p.read("tasks.json", {}), sort_keys=True), json.dumps(evidence(p), sort_keys=True))
        self.assertEqual(after, before)                                         # and nothing became true
        self.assertEqual({x["criterion"]: x["state"] for x in evidence(p)}["R-3-AC-1"], "not_measured")
        # a transcript rewritten after the fact is not even evidence: not measured, whatever it claims
        lines = (GNOMON / "analyst-run.jsonl").read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["completion_tokens"] = 1
        lines[1] = json.dumps(rec)
        forged = self.tmp / "forged.jsonl"
        forged.write_text("\n".join(lines) + "\n", encoding="utf-8")
        e = ingest(p, claim, forged, task="T-003", round_no=1)
        self.assertEqual((e["verdict"], e["tampered"]), ("not measured", True))
        self.assertEqual(json.dumps(p.read("tasks.json", {}), sort_keys=True), before[2])


# -- T. The cockpit for every party ------------------------------------------------------------------

class CustomerViewTest(FactoryTestCase):
    def test_FR_T2_AC_1_an_embed_a_customers_users_see_carries_nothing_internal_or_commercial(self):
        p = seeded(self)
        canon = Canon(p)
        price = "fixed price 24 000 EUR at a 38 % margin"
        card = canon.card("approval", "Approve the commercial offer", body=f"Internal: {price}")
        canon.decide(card["id"], "approve", person="Aino", persona="business_owner", reason=price)
        canon.comment({"kind": "project", "id": p.pid}, "Internal estimate: 12 person-days", person="Aino",
                      persona="business_owner")
        record = json.loads((GNOMON / "analyst-run.record.json").read_text(encoding="utf-8"))
        run = ingest(p, record, GNOMON / "analyst-run.jsonl", prices={"currency": "EUR", "models": {
            "deepseek-v4-pro": {"input_per_mtok": 2.0, "output_per_mtok": 8.0}}})
        internal = [price, "12 person-days", run["surface_hash"], "deepseek-v4-pro"]
        internal += [r["statement"] for r in p.read("spec.json")["requirements"]]
        internal += [c["then"] for r in p.read("contract.json")["requirements"] for c in r["acceptance"]]
        internal += [q["text"] for q in canon.questions()] + [a["text"] for a in canon.assumptions()]
        seen = []

        def chat(prompt, role):
            seen.append((role, prompt))
            return '```json\n{"reply": "Thank you, it is passed on.", "ready": true, "summary": "the list is unsorted"}\n```'

        brief = "Lend and return the team's equipment."
        e = kembeds.create(self.factory, kind="feedback", origins=["https://loans.example"], person="Aino",
                           persona="product_owner", project_id=p.pid, label="Loans page", brief=brief)
        out = kembeds.converse(self.factory, e["id"], e["key"], "https://loans.example",
                               [{"role": "person", "text": "The list of drills is not sorted"}], model=FakeModel(chat))
        self.assertEqual(set(out), {"reply", "filed"})
        self.assertEqual(set(out["filed"]), {"kind", "id"})
        role, prompt = seen[0]
        self.assertEqual(role, "assistant")
        for public in ("Equipment loans", brief, "The list of drills is not sorted"):
            self.assertIn(public, prompt)
        for secret in internal:
            self.assertNotIn(secret, prompt)
            self.assertNotIn(secret, json.dumps(out))
        # the business-need embed sees even less: its own label and brief, never a project
        need = kembeds.create(self.factory, kind="need", origins=["https://intranet.example"], person="Aino",
                              persona="business_owner", label="Ops chat", brief="Tell us what slows you down.")
        kembeds.converse(self.factory, need["id"], need["key"], "https://intranet.example",
                         [{"role": "person", "text": "Matching invoices by hand takes hours"}], model=FakeModel(chat))
        prompt = seen[-1][1]
        self.assertIn("Ops chat", prompt)
        for secret in internal + ["Equipment loans"]:
            self.assertNotIn(secret, prompt)


class ItInboxTest(CockpitTestCase):
    def test_FR_T2_AC_2_its_inbox_holds_environment_and_technical_decisions_never_a_business_one(self):
        p = self.new()
        cards = self.all_kinds(p)
        status, body, _ = self.call("GET", f"/api/projects/{p.pid}/inbox?persona=it")
        self.assertEqual(status, 200, body)
        self.assertEqual({c["kind"] for c in body["cards"]},     # an enforcement review: its named reviewer (FR-ENF1)
                         {"road", "deploy_gate", "trust", "incident", "update", "connector", "runner", "enforcement",
                          "structure"})     # a structure review too (FR-STR1)
        business = ("approval", "validation", "change", "concept", "escalation", "holdout_ruling")
        status, body, _ = self.call("GET", "/api/inbox?persona=it")
        self.assertEqual(status, 200, body)
        self.assertFalse(any(c["kind"] in business for c in body["cards"]))
        for kind in business:
            if kind in cards:
                status, _, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{cards[kind]}/decide",
                                         {"verdict": CARD_VERDICT_OF[kind], "person": "Jaana", "persona": "it"})
                self.assertEqual(status, 403, kind)
        # and the business owner's inbox never holds IT's environment decisions
        status, body, _ = self.call("GET", f"/api/projects/{p.pid}/inbox?persona=business_owner")
        self.assertFalse({c["kind"] for c in body["cards"]} & {"road", "deploy_gate", "trust"})


CARD_VERDICT_OF = {"approval": "approve", "validation": "accept", "change": "accept", "concept": "validate",
                   "escalation": "retry", "holdout_ruling": "product_defect"}


class SyncEndsInProposalTest(FactoryTestCase):
    @needs_brief
    def test_FR_T3_AC_1_whatever_another_tool_sends_in_ends_as_an_open_card_never_in_the_canon(self):
        p = seeded(self)
        fp = factory_project(self.factory)
        before = canon_state(p), json.dumps(Canon(fp).decisions(), sort_keys=True)
        # a board sync names the project: a change card there
        s1 = ksignals.receive(self.factory, "Equipment loans: the drills list should say who has each drill",
                              channel="feed", source="Jira board sync")
        # a Teams chat carries a need no project has (the brief's own FR-T3): a concept card in the factory's Inbox
        s2 = ksignals.receive(self.factory, BRIEF["FR-T3"], channel="chat", source="Teams channel", person="Aino",
                              persona="business_owner")
        routed, concept = ksignals.triage(self.factory, s1["id"]), ksignals.triage(self.factory, s2["id"])
        self.assertEqual((routed["state"], routed["routed_to"]["project"]), ("routed", p.pid))
        self.assertEqual((concept["state"], concept["routed_to"]["project"]), ("concept", None))
        # a developer's coding agent over MCP, and a website's chat
        mcp = RihmaMCP(self.factory, person="Pekka", persona="developer")
        filed = mcp_call(mcp, "rihma_report_change", pid=p.pid, text="Return dates should be shown in the list")
        e = kembeds.create(self.factory, kind="feedback", origins=["https://loans.example"], person="Aino",
                           persona="product_owner", project_id=p.pid)
        chat = kembeds.converse(self.factory, e["id"], e["key"], "https://loans.example",
                                [{"role": "person", "text": "I cannot find the return button"}])
        cards = [Canon(p).get_card(routed["routed_to"]["card"]), Canon(fp).get_card(concept["routed_to"]["card"]),
                 Canon(p).get_card(filed["card"]), Canon(p).get_card(chat["filed"]["id"])]
        self.assertEqual([c["kind"] for c in cards], ["change", "concept", "change", "change"])
        self.assertTrue(all(c["state"] == "open" and c["decision"] is None for c in cards))
        self.assertEqual(cards[1]["payload"]["text"], BRIEF["FR-T3"])
        self.assertEqual((canon_state(p), json.dumps(Canon(fp).decisions(), sort_keys=True)), before)
        self.assertEqual([x.pid for x in self.factory.projects() if not x.pid.startswith("_")], [p.pid])

    def test_FR_T3_AC_2_the_factorys_reads_reach_a_coding_agent_over_mcp_as_views_that_write_nothing(self):
        p = seeded(self)
        lanes = Lanes(self.tmp / "lanes", size=1)
        build_task(p, "T-001", lanes=lanes, cell_runner=generic_cell, verifier_runner=no_findings)
        build_task(p, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        mcp = RihmaMCP(self.factory, person="Pekka", persona="developer")
        home = Path(self.factory.home)
        before = tree_digest(home)
        view = mcp_call(mcp, "rihma_project", pid=p.pid)
        ev = mcp_call(mcp, "rihma_evidence", pid=p.pid)
        waiting = mcp_call(mcp, "rihma_waiting")
        listed = mcp_call(mcp, "rihma_projects")
        self.assertEqual(tree_digest(home), before)                             # reading wrote nothing
        self.assertEqual(view["now"], as_json(now(p)))
        self.assertEqual(view["health"], as_json(health(p)))
        rows = evidence(p)
        self.assertEqual(view["evidence"], dict(Counter(e["state"] for e in rows)))
        self.assertEqual([(r["criterion"], r["state"]) for r in ev["criteria"]], [(r["criterion"], r["state"]) for r in rows])
        escalation = next(c for c in Canon(p).cards() if c["kind"] == "escalation")
        self.assertEqual([c["id"] for c in view["cards_you_may_decide"]], [escalation["id"]])
        self.assertEqual([i["card"] for i in waiting["items"]], [escalation["id"]])
        self.assertEqual([x["id"] for x in listed["projects"]], [p.pid])


# -- a checkout without the brief ------------------------------------------------------------------

class WithoutTheBriefTest(unittest.TestCase):
    """The public repository ships no intake/: spec coverage says so and claims no measurement."""

    def coverage_tool(self, *argv: str) -> tuple:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = spec_coverage.main(list(argv))
        return code, out.getvalue()

    def test_spec_coverage_without_the_brief_says_so_exits_0_and_claims_no_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "intake" / "gnomon-factory-brief.md")
            code, text = self.coverage_tool("--brief", missing)
            self.assertEqual(code, 0)
            self.assertIn("the brief is not in this checkout", text)
            self.assertNotIn("covered", text)
            code, text = self.coverage_tool("--brief", missing, "--json")
            report = json.loads(text)
            self.assertEqual((code, report["measured"], report["reason"]), (0, False, "the brief is not in this checkout"))
            self.assertNotIn("counts", report)
            self.assertEqual(self.coverage_tool("--brief", missing, "--gate")[0], 0)
        if BRIEF:                                                                  # with the brief, it measures
            self.assertTrue(spec_coverage.coverage(BRIEF_FILE)["measured"])

    def test_the_tests_that_take_the_briefs_text_skip_with_that_reason_only_when_it_is_absent(self):
        for case, prefix in ((AgentsProposeTest, "test_FR_S3_AC_1_"), (SyncEndsInProposalTest, "test_FR_T3_AC_1_")):
            test = next(getattr(case, name) for name in dir(case) if name.startswith(prefix))
            self.assertEqual(getattr(test, "__unittest_skip__", False), not BRIEF, test.__name__)
            if not BRIEF:
                self.assertEqual(test.__unittest_skip_why__, "the brief is not in this checkout")


if __name__ == "__main__":
    unittest.main()
