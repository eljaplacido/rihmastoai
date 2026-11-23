"""Brief section M, cockpit and observation (FR-M1, FR-M2, FR-M4, FR-M7), measured against the real kernel.

Every test drives the kernel the way the factory runs: a project is taken in, specified, compiled
and built by the scripted cells of ``factory_fakes``, or delivered on the local paved road, and the
read models and the cockpit are read afterwards. Only what the code does is claimed here. FR-M5
(replay a view to a past moment) is not built; it and the parts of FR-M2, FR-M4 and FR-M7 that are
not built are recorded with their reasons in ``contract/deferred/m.json``.
"""

import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, lazy_cell, model, no_findings  # noqa: E402
from test_cockpit import RedesignTestCase  # noqa: E402
from test_deliver import BAD_ROUTES  # noqa: E402
from test_operate import OperateTestCase  # noqa: E402

from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dashboard import activity, coverage, queue, timeline  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.projections import floor  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import health, now  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
T0, T30, T90 = "2026-11-22T12:00:00Z", "2026-11-22T12:30:00Z", "2026-11-22T13:30:00Z"


def _payloads(project, kind):
    return [r["event"]["payload"] for r in project.ledger().of_kind(kind)]


class AgentsAtWorkTest(FactoryTestCase):
    """Two projects. "Built" is taken in, a person answers its blocking question, and builder cells
    build two tasks: T-001 merges on its first round, T-002 fails its gate twice and goes to a
    person. "Later" is only taken in, an hour after."""

    def setUp(self):
        super().setUp()
        self.built = self.new(mode="mixed", title="Built")
        intake(self.built, IDEA, model=model(), requested_by="Aino")
        Canon(self.built).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(self.built, model=model())
        compile_project(self.built)
        lanes = Lanes(self.tmp / "lanes", size=1)
        self.assertEqual(build_task(self.built, "T-001", lanes=lanes, cell_runner=good_cell,
                                    verifier_runner=no_findings)["status"], "merged")
        self.clock.advance(minutes=30)
        self.assertEqual(build_task(self.built, "T-002", lanes=lanes, cell_runner=lazy_cell,
                                    verifier_runner=no_findings, max_rounds=1)["status"], "escalated")
        self.clock.advance(hours=1)
        self.later = self.new(mode="assume", title="Later")
        intake(self.later, IDEA, model=model(), requested_by="Aino")

    def test_FR_M1_AC_1_the_task_timeline_shows_each_round_with_its_model_times_and_the_gates_verdict(self):
        tl = timeline(self.built)
        tasks = {t["task"]: t for t in tl["tasks"]}
        self.assertEqual(sorted(tasks), ["T-001", "T-002"])
        titles = {t["id"]: t["title"] for t in self.built.read("contract.json")["tasks"]}
        self.assertEqual({k: v["title"] for k, v in tasks.items()}, {k: titles[k] for k in tasks})
        t1, t2 = tasks["T-001"], tasks["T-002"]
        self.assertEqual([(r["round"], r["model"], r["verdict"]) for r in t1["rounds"]], [(0, "fake-builder", "passed")])
        self.assertEqual(t1["rounds"][0]["signals"],
                         {"fail_first": "passed", "tests": "passed", "trace": "passed", "verifier": "passed"})
        self.assertEqual((t1["rounds"][0]["start"], t1["rounds"][0]["end"], t1["merged_at"]), (T0, T0, T0))
        self.assertNotIn("escalated_at", t1)
        self.assertEqual([(r["round"], r["model"], r["verdict"]) for r in t2["rounds"]],
                         [(0, "fake-builder", "failed"), (1, "fake-builder", "failed")])
        self.assertEqual({r["signals"]["trace"] for r in t2["rounds"]}, {"failed"})    # why the gate said no
        self.assertEqual((t2["rounds"][0]["start"], t2["escalated_at"]), (T30, T30))
        self.assertNotIn("merged_at", t2)
        self.assertEqual((tl["start"], tl["end"]), (T0, T30))
        # every round shown is a cell the ledger records and the gate's ruling on it, nothing else
        cells = {(p["task"], p["round"]): p["final_model"] for p in _payloads(self.built, "cell_ran")}
        gates = {(p["task"], p["round"]): p["verdict"] for p in _payloads(self.built, "gate")}
        shown = {(t, r["round"]): (r["model"], r["verdict"]) for t, v in tasks.items() for r in v["rounds"]}
        self.assertEqual(shown, {k: (cells[k], gates[k]) for k in gates})
        # a cell that has finished while its gate has not ruled yet: a round with no end and no verdict
        self.clock.advance(minutes=5)
        self.built.log("cell_ran", {"task": "T-003", "round": 0, "final_model": "fake-builder", "escalated": False})
        t3 = next(t for t in timeline(self.built)["tasks"] if t["task"] == "T-003")
        self.assertEqual([(r["round"], r["model"], r["start"], r["end"], r["verdict"]) for r in t3["rounds"]],
                         [(0, "fake-builder", "2026-11-22T13:35:00Z", None, None)])

    def test_FR_M1_AC_2_the_activity_view_shows_what_happened_in_every_project_newest_first(self):
        acts = activity(self.factory, limit=1000)
        self.assertEqual(acts, sorted(acts, key=lambda a: a["at"], reverse=True))
        self.assertEqual({a["project"] for a in acts}, {self.built.pid, self.later.pid})
        self.assertEqual((acts[0]["project"], acts[0]["kind"], acts[0]["at"]), (self.later.pid, "intake_done", T90))
        lines = [(a["kind"], a["summary"]) for a in acts if a["project"] == self.built.pid]
        for line in [("cell_ran", "T-001 round 0: cell finished (result)"), ("gate", "T-001 round 0: gate passed"),
                     ("merged", "T-001 merged"), ("gate", "T-002 round 0: gate failed"),
                     ("gate", "T-002 round 1: gate failed"), ("escalated", "T-002 escalated to a person"),
                     ("decision", "answer on C-0001")]:
            self.assertIn(line, lines)
        # one line per recorded event of the kinds it shows: counted from the ledger, nothing invented
        shown = Counter(a["kind"] for a in acts if a["project"] == self.built.pid)
        recorded = Counter(r["event"]["kind"] for r in self.built.ledger().records() if r["event"]["kind"] in shown)
        self.assertEqual(shown, recorded)
        self.assertEqual(shown["gate"], 3)
        # a shorter view keeps the newest
        self.assertEqual(activity(self.factory, limit=3), acts[:3])

    def test_FR_M2_AC_1_each_event_is_classed_by_who_decided_a_person_an_agent_in_a_role_or_the_kernel(self):
        esc = Canon(self.built).cards(kind="escalation")[0]
        self.clock.advance(minutes=1)
        Canon(self.built).decide(esc["id"], "stop", person="Dana", persona="developer")
        actors = defaultdict(list)
        for a in activity(self.factory, limit=1000):
            actors[a["kind"]].append(a["actor"])
        # a person: named, with the persona they acted as, read from the record
        self.assertEqual(actors["question_answered"], [{"type": "person", "name": "Aino", "persona": "business_owner"}])
        self.assertEqual(actors["decision"], [{"type": "person", "name": "Dana", "persona": "developer"},
                                              {"type": "person", "name": "Aino", "persona": "business_owner"}])
        # an agent: a model in a role, with the model the ledger records for each cell
        self.assertEqual({(a["type"], a["name"]) for a in actors["cell_ran"]}, {("agent", "builder")})
        self.assertEqual(sorted(a["model"] for a in actors["cell_ran"]),
                         sorted(p["final_model"] for p in _payloads(self.built, "cell_ran")))
        self.assertEqual(len(actors["cell_ran"]), 3)
        self.assertEqual({a["name"] for k in ("intake_done", "spec_written") for a in actors[k]}, {"analyst"})
        # the kernel: its deterministic rulings are its own, never a model's or a person's
        for kind in ("gate", "merged", "escalated", "contract_compiled"):
            self.assertTrue(actors[kind], kind)
            self.assertEqual({(a["type"], a["name"], a["model"]) for a in actors[kind]}, {("agent", "kernel", None)}, kind)
        people = [a for xs in actors.values() for a in xs if a["type"] == "person"]
        self.assertTrue(people)
        self.assertFalse([a for a in people if a["name"] in (None, "kernel", "builder", "analyst")])


class TimelineRouteTest(RedesignTestCase):
    def test_FR_M1_AC_3_the_cockpit_returns_a_projects_task_timeline_and_reading_it_records_nothing(self):
        p = self.built_project()                                              # T-001 merged by a good cell
        build_task(p, "T-002", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=lazy_cell,
                   verifier_runner=no_findings, max_rounds=1)
        before = self.ledgers()
        status, tl, _ = self.call("GET", f"/api/projects/{p.pid}/timeline")
        self.assertEqual(status, 200, tl)
        self.assertEqual(tl, self.as_json(timeline(p)))
        self.assertEqual([(t["task"], [r["verdict"] for r in t["rounds"]]) for t in tl["tasks"]],
                         [("T-001", ["passed"]), ("T-002", ["failed", "failed"])])
        self.assertTrue(tl["tasks"][0]["merged_at"])
        self.assertTrue(tl["tasks"][1]["escalated_at"])
        self.assert_no_ledger_writes(before)                                  # a read records nothing
        self.assertEqual(self.call("GET", "/api/projects/no-such-project/timeline")[0], 404)
        quiet = self.new(title="Quiet")                                       # no work yet: empty, not an error
        self.assertEqual(self.call("GET", f"/api/projects/{quiet.pid}/timeline")[:2],
                         (200, {"tasks": [], "start": None, "end": None}))
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/timeline", token=None)[0], 401)


class FigureProvenanceTest(RedesignTestCase):
    KPIS = {"in_flight", "decisions", "first_round", "proven", "in_use"}

    def kpis(self) -> dict:
        status, d, _ = self.call("GET", "/api/dashboard")
        self.assertEqual(status, 200, d)
        self.assertEqual(d["problems"], [])
        return d

    def test_FR_M4_AC_1_each_headline_figure_carries_its_provenance_method_and_the_counts_it_came_from(self):
        p = self.built_project()                       # T-001 merged on its first round
        self.intake_project()                          # a second project, whose blocking question waits on a person
        d = self.kpis()
        k = d["kpis"]
        self.assertEqual(set(k), self.KPIS)
        for name, fig in k.items():
            self.assertIn(fig["provenance"], ("observed", "derived"), name)
            self.assertTrue(fig["basis"].strip(), name)                   # the method, in words
        # derived figures: a ratio, with the numerator and denominator it was computed from
        gates, cov = floor(self.factory)["gates"], coverage(self.factory)
        fr = k["first_round"]
        self.assertEqual((fr["provenance"], fr["num"], fr["of"], fr["value"]), ("derived", 1, 1, 1.0))
        self.assertEqual((fr["num"], fr["of"]), (gates["first_round_passed"], gates["tasks_gated"]))
        pr = k["proven"]
        self.assertEqual(pr["provenance"], "derived")
        self.assertEqual((pr["num"], pr["of"]),
                         (cov["total"].get("verified", 0) + cov["total"].get("held_out", 0), sum(cov["total"].values())))
        self.assertGreater(pr["of"], pr["num"])
        self.assertGreater(pr["num"], 0)
        self.assertAlmostEqual(pr["value"], pr["num"] / pr["of"])
        # observed figures: a count of records, with what it is counted out of
        self.assertEqual((k["in_flight"]["provenance"], k["in_flight"]["value"], k["in_flight"]["of"]), ("observed", 2, 2))
        self.assertEqual((k["in_use"]["provenance"], k["in_use"]["value"], k["in_use"]["of"]), ("observed", 0, 2))
        self.assertEqual(k["decisions"]["provenance"], "observed")
        self.assertEqual(k["decisions"]["value"], len(d["decisions"]))
        open_ids = {(x.pid, c["id"]) for x in self.factory.projects() for c in Canon(x).cards()}
        self.assertTrue({(i["project"], i["card"]) for i in d["decisions"]} <= open_ids)
        # the figures are counted afresh from the records: a task that fails its first round moves them
        build_task(p, "T-002", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=lazy_cell,
                   verifier_runner=no_findings, max_rounds=1)
        k2 = self.kpis()["kpis"]
        self.assertEqual((k2["first_round"]["num"], k2["first_round"]["of"], k2["first_round"]["value"]), (1, 2, 0.5))
        self.assertEqual(k2["decisions"]["value"], k["decisions"]["value"] + 1)   # the escalation now waits too

    def test_FR_M4_AC_2_a_derived_figure_with_nothing_to_count_is_null_never_zero(self):
        k = self.kpis()["kpis"]                                                 # an empty factory
        for name in ("first_round", "proven"):
            self.assertEqual(k[name]["provenance"], "derived", name)
            self.assertIsNone(k[name]["value"], name)
            self.assertEqual((k[name]["num"], k[name]["of"]), (0, 0), name)
        self.assertEqual((k["in_flight"]["value"], k["in_flight"]["of"]), (0, 0))  # a count of nothing is 0
        self.assertEqual(k["decisions"]["value"], 0)
        # a project taken in but never gated still leaves the gate's figure with nothing to count
        self.intake_project()
        k = self.kpis()["kpis"]
        self.assertIsNone(k["first_round"]["value"])
        self.assertEqual(k["first_round"]["of"], 0)
        self.assertIsNone(k["proven"]["value"])                                 # no contract compiled yet
        self.assertEqual((k["in_flight"]["value"], k["in_flight"]["of"]), (1, 1))


class CanaryAlertTest(OperateTestCase):
    """A real product in production; its next revision crashes on an empty name."""

    def test_FR_M7_AC_1_a_canary_abort_raises_a_blocking_incident_card_for_the_people_who_run_production(self):
        self.assertEqual(self.ship()["state"], "done")
        self.traffic()
        self.commit_routes(BAD_ROUTES, "Empty names crash")
        decided_before = len(self.canon.decisions())
        out = self.ship()
        self.assertEqual((out["state"], out["release"], out["failed_step"]), ("failed", 2, "canary:production"))
        self.assertEqual(_payloads(self.project, "canary")[-1]["decision"], "abort")
        card = self.canon.get_card(out["incident"])
        self.assertEqual((card["kind"], card["state"], card["blocking"]), ("incident", "open", True))
        self.assertEqual(card["refs"], {"release": 2, "environment": "production"})
        self.assertEqual(card["deciders"], ["operations", "it", "developer"])
        self.assertEqual(_payloads(self.project, "incident_opened"),
                         [{"card": card["id"], "release": 2, "environment": "production"}])
        # the alert was raised with no person involved: the only decisions are the release's own approvals
        self.assertEqual([d["kind"] for d in self.canon.decisions()[decided_before:]], ["validation", "deploy_gate"])
        # it reaches the people who run production, and only them
        for persona in ("operations", "it", "developer"):
            self.assertIn(card["id"], [c["id"] for c in self.canon.cards(persona=persona)], persona)
        for persona in ("business_owner", "product_owner", "end_user", "stakeholder"):
            self.assertNotIn(card["id"], [c["id"] for c in self.canon.cards(persona=persona)], persona)
        with self.assertRaises(DecisionRefused):
            self.canon.decide(card["id"], "acknowledge", person="Aino", persona="product_owner")
        # the decision queue lists it, the project's now line counts it, and health names the stopped release
        item = next(i for i in queue(self.factory)["items"] if i["card"] == card["id"])
        self.assertEqual((item["project"], item["kind"], item["deciders"]),
                         (self.project.pid, "incident", ["operations", "it", "developer"]))
        n = now(self.project)
        self.assertEqual(n["state"], "waiting_on_you")
        self.assertIn(card["id"], n["cards"])
        hl = health(self.project)
        self.assertEqual(hl["status"], "at_risk")
        self.assertIn("release 2 stopped", hl["reasons"])
        # operations acknowledges it, and it leaves the queue
        d = self.canon.decide(card["id"], "acknowledge", person="Olli", persona="operations")
        self.assertEqual((d["kind"], d["person"], d["persona"]), ("incident", "Olli", "operations"))
        self.assertNotIn(card["id"], [i["card"] for i in queue(self.factory)["items"]])


if __name__ == "__main__":
    unittest.main()
