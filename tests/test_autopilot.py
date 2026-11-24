"""Delegated decisions and autopilot in a sandbox (FR-AP1, FR-AP2; D-0007, D-0017).

A person whose persona may decide a kind of card delegates it on one project, for a while, to one of the
factory's rules; the pipeline decides those cards by the rule in that person's name, with "by delegation
DL-n" on record, and nothing else. An autopilot run delegates and runs pass after pass, bound to a sandbox:
it delivers only to the local preview or a road marked sandbox, sends events only to sandbox receivers,
and a person stops it. Every receiver here is a local fake; no model, no network.
"""

import base64
import contextlib
import datetime as dt
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, lazy_cell, model, no_findings  # noqa: E402
from integration_fakes import Receiver  # noqa: E402

from kernel import access as kaccess  # noqa: E402
from kernel import autopilot, delegation, plan, relay, roads  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task, resolve_escalations  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.people import Identity  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import write_json  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
KEY = b"autopilot-test-signing-key-012345"
SIGNING = "whsec_" + base64.b64encode(KEY).decode("ascii")


class Case(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(roads.stop_started)

    def intake(self, maturity="explore", mode="mixed"):
        p = self.new(mode=mode, maturity=maturity)
        intake(p, IDEA, model=model(), requested_by="Aino")
        return p

    def run_kwargs(self, cell=generic_cell):
        return dict(lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=cell, verifier_runner=no_findings,
                    deliver_kwargs={})

    def compiled(self):
        p = self.intake(mode="assume")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def kinds(self, p, kind):
        return [r["event"]["payload"] for r in p.ledger().of_kind(kind)]


class DelegationTest(Case):
    def test_FR_AP1_AC_1_a_delegated_question_is_assumed_in_the_delegating_persons_name_and_the_run_goes_on(self):
        p = self.intake()
        d = delegation.grant(p, ["question"], person="Aino", persona="business_owner", until="8h",
                             reason="assume while I am away")
        self.assertEqual((d["id"], d["state"], d["rules"]), ("DL-001", "active", {"question": "assume"}))
        out = advance(p, model=model(), **self.run_kwargs())
        self.assertNotEqual(out["state"], "waiting", out)                 # it went past the blocking question
        q = Canon(p).question("Q-001")
        self.assertEqual(q["status"], "assumed")
        self.assertEqual(q["answer"]["chosen_by"], "Aino")
        dec = next(x for x in Canon(p).decisions() if x["card"] == q["card"])
        self.assertEqual((dec["person"], dec["persona"], dec["verdict"], dec["delegation"]),
                         ("Aino", "business_owner", "assume", "DL-001"))
        card = Canon(p).get_card(q["card"])
        self.assertEqual(card["decision"]["delegation"], "DL-001")         # the card's copy says so too
        logged = [x for x in self.kinds(p, "decision") if x["card"] == q["card"]][0]
        self.assertEqual(logged["delegation"], "DL-001")
        trace = self.kinds(p, "delegated_decision")[0]
        self.assertEqual((trace["delegation"], trace["rule"], trace["person"], trace["persona"]),
                         ("DL-001", "assume", "Aino", "business_owner"))
        self.assertEqual(trace["basis"]["assumed"], "the team lead approves")
        self.assertEqual(trace["why"], "Q-001 assumed as its business perspective proposed")
        self.assertTrue(p.path("spec.json").exists())                       # the run went on to the spec
        self.assertEqual(self.kinds(p, "delegation_granted")[0]["person"], "Aino")

    def test_FR_AP1_AC_1_the_decisions_reason_says_by_delegation(self):
        p = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        out = build_task(p, "T-001", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        delegation.grant(p, ["escalation"], person="Dev", persona="developer", until="1d")
        done = delegation.consult(p, [out["card"]])
        self.assertEqual([x["verdict"] for x in done], ["retry"])
        dec = Canon(p).get_card(out["card"])["decision"]
        self.assertTrue(dec["reason"].startswith("by delegation DL-001 (retry_once): "), dec["reason"])
        self.assertEqual((dec["person"], dec["persona"]), ("Dev", "developer"))

    def test_FR_AP1_AC_2_the_plan_is_approved_only_when_every_requirement_has_a_test_and_it_compiles(self):
        p = self.intake(maturity="pilot", mode="assume")
        make_spec(p, model=model())
        delegation.grant(p, ["approval"], person="Aino", persona="product_owner", until="2d")
        card = plan.gate(p, model=model())["waiting_on"][0]
        done = delegation.consult(p, [card])
        self.assertEqual([(x["card"], x["verdict"], x["rule"]) for x in done], [(card, "approve", "plan_when_tested")])
        basis = self.kinds(p, "delegated_decision")[0]["basis"]
        self.assertEqual((basis["requirements"], basis["criteria"], basis["test"]), (4, 6, 4))
        self.assertIsNone(plan.gate(p, model=model()))                    # the pipeline's own gate: approved
        self.assertEqual(p.meta["plan_approved"]["by"], "Aino")
        # a plan with a requirement that has no test waits for a person, and says why, once
        q = self.intake(maturity="pilot", mode="assume")
        make_spec(q, model=model())
        spec = q.read("spec.json")
        for c in spec["requirements"][2]["acceptance"]:
            c["kind"] = "probe"
        q.write("spec.json", spec)
        delegation.grant(q, ["approval"], person="Aino", persona="product_owner", until="2d")
        card = plan.gate(q, model=model())["waiting_on"][0]
        self.assertEqual(delegation.consult(q, [card]), [])
        self.assertEqual(delegation.consult(q, [card]), [])
        self.assertEqual(Canon(q).get_card(card)["state"], "open")
        declined = self.kinds(q, "delegation_declined")
        self.assertEqual(len(declined), 1)                                  # once, however often it is asked
        self.assertIn("R-3 has no test the gate runs", declined[0]["why"])
        # an approval that is not the plan's is never approved by the plan's rule
        other = Canon(q).card("approval", "Accept the demo?", refs={"scope": "release"})
        self.assertEqual(delegation.consult(q, [other["id"]]), [])
        self.assertIn("not the plan's approval", self.kinds(q, "delegation_declined")[-1]["why"])

    def test_FR_AP1_AC_2_an_escalation_is_retried_once_and_then_waits_for_a_person(self):
        p = self.compiled()
        lanes = Lanes(self.tmp / "lanes", size=1)
        first = build_task(p, "T-001", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        delegation.grant(p, ["escalation"], person="Dev", persona="developer", until="1d")
        self.assertEqual([x["verdict"] for x in delegation.consult(p, [first["card"]])], ["retry"])
        self.assertEqual(resolve_escalations(p), [first["card"]])
        again = build_task(p, "T-001", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        self.assertEqual(again["status"], "escalated")
        self.assertEqual(delegation.consult(p, [again["card"]]), [])       # the rule stops: a person decides
        self.assertEqual(Canon(p).get_card(again["card"])["state"], "open")
        self.assertIn("escalated again after the delegated retry", self.kinds(p, "delegation_declined")[0]["why"])
        self.assertFalse(p.meta.get("halted"))                              # it never stops the build itself
        verdicts = {x["verdict"] for x in Canon(p).decisions()}
        self.assertNotIn("accept_as_is", verdicts)

    def test_FR_AP1_AC_3_revoked_or_expired_delegations_and_undelegated_kinds_leave_cards_to_a_person(self):
        p = self.intake()
        canon = Canon(p)
        d = delegation.grant(p, ["question"], person="Aino", persona="business_owner", until="2h")
        change = canon.card("change", "Make the loan period longer", blocking=True)
        self.assertEqual(delegation.consult(p, [change["id"]]), [])          # not delegated: never decided
        self.assertEqual(canon.get_card(change["id"])["state"], "open")
        plan_only = delegation.grant(p, ["approval"], person="Aino", persona="business_owner", until="2h")
        with self.assertRaises(DecisionRefused):                            # only the delegator or a decider
            delegation.revoke(p, plan_only["id"], person="Sam", persona="stakeholder")
        delegation.revoke(p, plan_only["id"], person="Dev", persona="developer")
        revoked = delegation.revoke(p, d["id"], person="Ida", persona="product_owner", reason="I will answer")
        self.assertEqual(revoked["state"], "revoked")
        out = advance(p, model=model(), **self.run_kwargs())
        self.assertEqual(out["state"], "waiting")                           # revoked at once: the card waits
        self.assertEqual(canon.question("Q-001")["status"], "open")
        delegation.grant(p, ["question"], person="Aino", persona="business_owner", until="2h")
        self.clock.advance(hours=3)
        self.assertEqual([x["state"] for x in delegation.delegations(p)], ["revoked", "revoked", "expired"])
        self.assertEqual(advance(p, model=model(), **self.run_kwargs())["state"], "waiting")
        self.assertEqual(canon.question("Q-001")["status"], "open")
        now = self.factory.clock.now()
        for until, why in (("8d", "at most 7 days"), ((now - dt.timedelta(hours=1)).isoformat(), "has passed"),
                           ("soon", "is a time such as")):
            with self.assertRaises(ValueError) as caught:
                delegation.grant(p, ["question"], person="Aino", persona="business_owner", until=until)
            self.assertIn(why, str(caught.exception))
        with self.assertRaises(DecisionRefused):
            delegation.grant(p, ["question"], person="factory", persona="business_owner", until="2h")
        self.assertEqual(len(delegation.delegations(p)), 3)

    def test_FR_AP1_AC_4_kinds_never_delegated_and_kinds_the_persona_may_not_decide_are_refused_with_the_reason(self):
        p = self.intake()
        before = len(p.ledger().records())
        for kind, persona, why in (("deploy_gate", "it", "opens production"), ("trust", "it", "owner's own act"),
                                   ("holdout_ruling", "developer", "scenario is wrong"),
                                   ("connector", "it", "IT decides it"), ("road", "it", "configured by IT"),
                                   ("concept", "business_owner", "factory's own card"),
                                   ("validation", "business_owner", "no rule decides"),
                                   ("approval", "stakeholder", "may not decide a approval card"),
                                   ("escalation", "end_user", "may not decide a escalation card")):
            with self.assertRaises(DecisionRefused) as caught:
                delegation.grant(p, ["question", kind], person="Aino", persona=persona, until="2h")
            self.assertIn(why, str(caught.exception), kind)
        with self.assertRaises(ValueError):
            delegation.grant(p, ["question"], person="Aino", persona="business_owner", until="2h",
                             rules={"question": "approve_everything"})
        self.assertEqual(delegation.delegations(p), [])
        self.assertEqual(len(p.ledger().records()), before)                  # nothing was recorded

    def test_FR_AP1_AC_5_with_access_enforced_a_delegated_decision_names_the_identity_and_stops_when_its_grant_goes(self):
        from test_access import AINO, access_doc

        p = self.intake()
        path = kaccess.access_path(self.factory)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, access_doc())
        with self.assertRaises(DecisionRefused):                             # no verified identity: refused
            delegation.grant(p, ["question"], person="Aino Example", persona="business_owner", until="8h")
        with kaccess.signing(Identity(AINO, "Aino Example")):
            d = delegation.grant(p, ["question"], person="Aino Example", persona="business_owner", until="8h")
        self.assertEqual(d["identity"], AINO)
        card = Canon(p).question("Q-001")["card"]
        done = delegation.consult(p, [card])                                  # no one signed in: the delegation signs
        self.assertEqual([x["verdict"] for x in done], ["assume"])
        dec = Canon(p).get_card(card)["decision"]
        stored = next(x for x in Canon(p).decisions() if x["card"] == card)
        self.assertEqual((stored["identity"], stored["delegation"], dec["person"]), (AINO, "DL-001", "Aino Example"))
        # IT takes the grant away: the next delegated decision is refused, and its card waits
        doc = access_doc()
        doc["bindings"] = [b for b in doc["bindings"] if b.get("subject") != AINO]
        write_json(path, doc)
        q = Canon(p).add_question("Is a weekend loan allowed?", "business", blocking=True, opinions={"business": "yes"})
        Canon(p).ask(q["id"])
        late = Canon(p).question(q["id"])["card"]
        self.assertEqual(delegation.consult(p, [late]), [])
        self.assertEqual(Canon(p).get_card(late)["state"], "open")
        why = self.kinds(p, "delegation_declined")[-1]["why"]
        self.assertTrue(why.startswith("refused: ") and "Aino Example" in why, why)


class AutopilotTest(Case):
    def start(self, p, **kw):
        args = dict(until="8h", kinds=["question", "approval", "escalation"], person="Dev", persona="developer")
        return autopilot.start(p, **(args | kw))

    def test_FR_AP2_AC_1_an_autopilot_runs_an_explore_project_to_its_local_preview_and_records_every_step(self):
        p = self.intake()
        run = self.start(p, reason="try it overnight")
        self.assertEqual((run["id"], run["state"], run["delegation"]), ("AP-001", "running", "DL-001"))
        self.assertEqual(run["sandbox"], {"env": "preview", "road": "local-preview", "sandbox": True,
                                          "why": "preview on local-preview, a road marked as a sandbox"})
        out = autopilot.run(p, model=model(), **self.run_kwargs())
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(out["passes"][-1]["delegated"], [{"card": "C-0001", "verdict": "assume",
                                                           "delegation": "DL-001"}])
        status = autopilot.status(p)
        self.assertTrue(status["holding"])
        self.assertEqual([(x["card"], x["verdict"], x["person"]) for x in status["run"]["decided"]],
                         [("C-0001", "assume", "Dev")])
        self.assertEqual(status["delegations"][0]["run"], "AP-001")
        started = self.kinds(p, "autopilot_started")[0]
        self.assertEqual((started["person"], started["persona"], started["delegation"], started["reason"]),
                         ("Dev", "developer", "DL-001", "try it overnight"))
        self.assertEqual(self.kinds(p, "autopilot_pass")[-1]["state"], "done")
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_AP2_AC_1_the_command_line_starts_reports_and_stops_an_autopilot(self):
        p = self.intake()
        home = ["--home", str(self.factory.home)]
        base = ["autopilot", "start", p.pid, "--until", "4h", "--delegate", "question", "--person", "Dev",
                "--persona", "developer", "--arm-only"]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(home + base), 0)
        self.assertEqual(json.loads(out.getvalue())["state"], "running")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(home + ["autopilot", "status", p.pid]), 0)
        self.assertEqual(json.loads(out.getvalue())["run"]["kinds"], ["question"])
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            self.assertEqual(main(home + ["delegation", "grant", p.pid, "--kinds", "trust", "--until", "1h",
                                          "--person", "Ilkka", "--persona", "it"]), 2)
        self.assertIn("never delegated", err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(home + ["autopilot", "stop", p.pid, "--person", "Dev", "--persona", "developer"]), 0)
        self.assertEqual(json.loads(out.getvalue())["state"], "stopped")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(home + ["delegation", "list", p.pid]), 0)
        self.assertEqual(json.loads(out.getvalue())["delegations"][0]["state"], "revoked")

    def test_FR_AP2_AC_2_a_delivery_outside_the_sandbox_waits_for_a_person_and_a_marked_demo_road_is_delivered_to(self):
        p = self.intake(maturity="pilot")
        self.start(p)
        out = autopilot.run(p, model=model(), **self.run_kwargs())
        self.assertEqual(out["state"], "waiting", out)
        self.assertIn("bound to a sandbox", out["ended"])
        self.assertIn("staging, which is never a sandbox", out["ended"])
        self.assertTrue(p.meta.get("built"))                                 # it built, under the delegation
        self.assertFalse(p.path("releases").exists())                        # and deployed nothing
        self.assertEqual(Canon(p).cards(kind="road"), [])                    # nor asked IT for a road
        autopilot.run(p, model=model(), **self.run_kwargs())
        self.assertEqual(len(self.kinds(p, "autopilot_held")), 1)            # the hold is on record once
        # a demo road IT marked as a sandbox is one; the same road unmarked is not
        demo = self.intake(maturity="demo")
        cfg = {"schema": roads.SCHEMA, "maturity": {"demo": "test-demo"},
               "roads": {"test-demo": {"kind": "local-process", "configured": True, "environments": ["demo"],
                                       "sandbox": True}}}
        write_json(self.factory.paved_roads_path, cfg)
        self.start(demo)
        self.assertTrue(autopilot.sandbox_of(demo)["sandbox"])
        self.assertIsNone(autopilot.delivery_hold(demo))
        cfg["roads"]["test-demo"]["sandbox"] = False
        write_json(self.factory.paved_roads_path, cfg)
        self.assertIn("IT has not marked as a sandbox", autopilot.delivery_hold(demo)["why"])
        self.assertFalse(roads.is_sandbox({"sandbox": True}, "staging"))      # staging never is, whatever it says

    def test_FR_AP2_AC_3_the_relay_holds_events_from_receivers_outside_the_sandbox_until_a_person_stops_the_run(self):
        p = self.intake()
        rx = Receiver()
        self.addCleanup(rx.close)
        outside = relay.subscribe(self.factory, sink="webhook", url=rx.base + "/outside", secret_env="RELAY_SECRET",
                                  types=["rihma.*"], person="Ilkka", persona="it")
        inside = relay.subscribe(self.factory, sink="webhook", url=rx.base + "/inside", secret_env="RELAY_SECRET",
                                 types=["rihma.*"], person="Ilkka", persona="it")
        with self.assertRaises(DecisionRefused):
            relay.mark(self.factory, inside["id"], person="Dev", persona="developer", sandbox=True)
        relay.mark(self.factory, inside["id"], person="Ilkka", persona="it", sandbox=True)
        self.start(p)
        Canon(p).card("change", "A change while the autopilot runs")
        env = {"RELAY_SECRET": SIGNING}

        def kinds_at(path):
            bodies = [json.loads(r["body"])["data"] for r in rx.at(path)]
            return [b["ledger_kind"] for b in bodies if b["stream"]["project_id"] == p.pid]

        relay.run(self.factory, environ=env)
        relay.run(self.factory, environ=env)
        self.assertEqual(kinds_at("/outside"), [])                            # the project's events: held back
        self.assertIn("autopilot_started", kinds_at("/inside"))               # the sandbox receiver gets them
        held = [d for d in relay.deliveries(self.factory) if d["kind"] == "sandbox_held"]
        self.assertEqual([(d["subscription"], d["project"]) for d in held], [(outside["id"], p.pid)])
        self.assertIn("a person stops the run", held[0]["why"])
        self.assertIn("connectors read-only", autopilot.write_hold(p, "example", "create_issue"))
        autopilot.stop(p, person="Aino", persona="business_owner")
        relay.run(self.factory, environ=env)
        ids = kinds_at("/outside")
        self.assertEqual(ids[:2], ["delegation_granted", "autopilot_started"])   # in order, nothing lost
        self.assertIn("autopilot_stopped", ids)
        self.assertIsNone(autopilot.write_hold(p, "example", "create_issue"))

    def test_FR_AP2_AC_4_stopping_revokes_at_once_expiry_stops_passes_and_one_run_holds_at_a_time(self):
        p = self.intake()
        with self.assertRaises(DecisionRefused):
            self.start(p, persona="stakeholder", kinds=["question"])
        self.start(p, until="2h")
        with self.assertRaises(DecisionRefused):
            self.start(p)                                                     # one run holds at a time
        self.clock.advance(hours=3)
        out = autopilot.run(p, model=model(), **self.run_kwargs())
        self.assertEqual((out["passes"], out["ended"]), ([], "AP-001 is expired"))
        self.assertTrue(autopilot.status(p)["holding"])                       # the sandbox holds until a person
        with self.assertRaises(DecisionRefused):
            autopilot.stop(p, person="Sam", persona="end_user")
        stopped = autopilot.stop(p, person="Aino", persona="business_owner", reason="back at my desk")
        self.assertEqual((stopped["state"], stopped["stopped"]["was"]), ("stopped", "expired"))
        self.assertFalse(autopilot.status(p)["holding"])
        # a running one: stopping revokes its delegation at once
        self.start(p)
        stopped = autopilot.stop(p, person="Dev", persona="developer")
        self.assertEqual([d["state"] for d in delegation.delegations(p)], ["expired", "revoked"])
        self.assertEqual(advance(p, model=model(), **self.run_kwargs())["state"], "waiting")
        self.assertEqual(Canon(p).question("Q-001")["status"], "open")
        preset = autopilot.posture_preset()
        self.assertEqual((preset["id"], preset["autonomy_cap"], preset["connectors"]),
                         ("autopilot_sandbox", 3, "read only"))
        self.assertNotIn("deploy_gate", preset["delegable"])


if __name__ == "__main__":
    unittest.main()
