"""The brief's sections P and Q, measured against what the kernel does (task V-72).

FR-P2 (the concept stage), FR-P3 (the technical translation) and FR-Q3 (IT's requirements) are
partly built. These tests exercise the parts that exist, through the kernel's own APIs and the
cockpit's HTTP server, with the scripted model of `factory_fakes`. What is not built, and FR-P6 and
FR-Q1 (not built at all), is recorded in contract/deferred/pq.json.

The FR-Q3 delivery test runs a real product: built by a fake builder cell, delivered on a local
road to staging as a local process. Every process is stopped in cleanup, also when a test fails.
"""

import copy
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import GOOD_ROUTES, SPEC, FactoryTestCase, good_cell, model, no_findings, script  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.compile import author_holdouts, compile_project, contract_check  # noqa: E402
from kernel.deliver import deliver  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import GIT_ID, Lanes, _git  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import MATURITIES, write_json  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops. We want a simple way to lend and return things."
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a proxy


def fenced(obj) -> str:
    return "```json\n" + json.dumps(obj) + "\n```"


def scripted(**overrides) -> FakeModel:
    """The shared script, with some answers replaced. Each key names a prompt marker."""
    def answer(prompt, role):
        for marker, reply in overrides.items():
            if marker in prompt:
                return fenced(reply() if callable(reply) else reply)
        return script(prompt, role)
    return FakeModel(answer)


SPEC_PROMPT = "You turn a brief into a software specification"
HOLDOUT_PROMPT = "You write acceptance scenarios"
IT_PROMPT = "You are the **it_security** perspective"


class CockpitClient:
    """The real cockpit server on a free loopback port, signed in with its one-use bootstrap."""

    def __init__(self, case: unittest.TestCase, factory):
        server, bootstrap = make_server(factory, 0)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        case.addCleanup(thread.join, 5)
        case.addCleanup(server.server_close)
        case.addCleanup(server.shutdown)
        self.origin, self.token = server.origin, None
        status, body = self.call("POST", "/auth", {"bootstrap": bootstrap})
        case.assertEqual(status, 200, body)
        self.token = body["token"]

    def call(self, method, path, body=None):
        headers = {"Origin": self.origin} if method != "GET" else {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode("utf-8"), "application/json"
        req = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with _DIRECT.open(req, timeout=10) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"null")


# -- FR-P2: the concept stage -------------------------------------------------------------------

class ConceptStageTest(FactoryTestCase):
    def test_FR_P2_AC_1_every_requirement_keeps_its_state_and_sources_and_outside_content_is_never_confirmed(self):
        spec = copy.deepcopy(SPEC)
        spec["requirements"] += [
            # Content from a consultant's notes, not from the business: not a source the kernel keeps.
            {"statement": "Loans are exported to the consultant's reporting tool.", "priority": "could",
             "sources": ["workshop notes by the consultant"],
             "acceptance": [{"given": "-", "when": "GET /export", "then": "200 with every loan", "kind": "test"}]},
            # The request, plus a slide nobody in the business wrote: the request is what carries.
            {"statement": "Each item shows who has it now.", "priority": "should",
             "sources": ["consultant slide 4", "request"],
             "acceptance": [{"given": "a lent item", "when": "GET /items", "then": "the borrower is listed",
                             "kind": "test"}]},
        ]
        m = scripted(**{SPEC_PROMPT: spec})
        p = self.new(mode="mixed", maturity="pilot")
        intake(p, IDEA, model=m, requested_by="Aino")
        Canon(p).answer("Q-001", "the team lead approves", person="Pekka", persona="business_owner")
        out = make_spec(p, model=m)
        rows = {r["id"]: (r["provenance"], r.get("decided_by"), r["sources"]) for r in out["requirements"]}
        self.assertEqual(rows, {
            "R-1": ("customer-endorsed", "Aino", ["request"]),        # the request, by the person who made it
            "R-2": ("customer-confirmed", "Pekka", ["Q-001"]),       # a question a person answered
            "R-3": ("assumption", None, ["Q-002"]),                   # a question the factory assumed
            "R-4": ("vendor-proposed", None, ["proposed"]),           # the analyst's own proposal
            "R-5": ("vendor-proposed", None, ["proposed"]),           # the consultant's notes are not a source
            "R-6": ("customer-endorsed", "Aino", ["request"]),        # the slide is dropped, the request stays
        })
        # The package as written carries each requirement's state and sources.
        text = p.path("spec.md").read_text(encoding="utf-8")
        self.assertIn("## R-2 (must, customer-confirmed, decided by Pekka)", text)
        self.assertIn("## R-5 (could, vendor-proposed)", text)
        self.assertNotIn("consultant", json.dumps([r["sources"] for r in out["requirements"]]))

    def test_FR_P2_AC_2_the_cockpit_shows_each_requirements_state_and_sources_and_each_questions_state(self):
        p = self.new(mode="socratic", maturity="pilot")
        intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        canon.answer("Q-001", "the team lead approves", person="Pekka", persona="business_owner")
        canon.assume("Q-002", "fewer lost items per month", chosen_by="Aino", persona="business_owner")
        waiting = advance(p, model=model())
        self.assertEqual((waiting["state"], waiting["stage"]), ("waiting", 4))   # the package waits on a person
        cockpit = CockpitClient(self, self.factory)

        status, plan = cockpit.call("GET", f"/api/projects/{p.pid}/plan")
        self.assertEqual(status, 200, plan)
        card = plan["card"]
        self.assertEqual(card["id"], waiting["waiting_on"][0])
        self.assertEqual(card["deciders"], ["business_owner", "product_owner", "developer"])
        # An SME (a concept evaluator) may look at the package, but not approve it.
        status, refused = cockpit.call("POST", f"/api/projects/{p.pid}/cards/{card['id']}/decide",
                                       {"verdict": "approve", "person": "Sanna", "persona": "concept_evaluator"})
        self.assertEqual(status, 403, refused)
        self.assertEqual(Canon(p).get_card(card["id"])["state"], "open")
        reqs = {r["id"]: (r["provenance"], r["decided_by"], r["sources"]) for r in plan["spec"]["requirements"]}
        self.assertEqual(reqs, {"R-1": ("customer-endorsed", "Aino", ["request"]),
                                "R-2": ("customer-confirmed", "Pekka", ["Q-001"]),
                                "R-3": ("assumption", None, ["Q-002"]),
                                "R-4": ("vendor-proposed", None, ["proposed"])})
        self.assertIn("R-2 (customer-confirmed)", card["body"])
        self.assertIn("R-3 (assumption)", card["body"])

        status, view = cockpit.call("GET", f"/api/projects/{p.pid}")
        self.assertEqual(status, 200, view)
        questions = {q["id"]: q for q in view["questions"]}
        self.assertEqual((questions["Q-001"]["status"], questions["Q-001"]["answer"]["by"]), ("answered", "Pekka"))
        assumed = questions["Q-002"]
        self.assertEqual((assumed["status"], assumed["answer"]["chosen_by"]), ("assumed", "Aino"))
        assumption = next(a for a in view["assumptions"] if a["id"] == assumed["answer"]["assumption"])
        self.assertEqual((assumption["due"], assumption["status"]), ("2026-12-06", "open"))
        still_open = sorted(q for q, v in questions.items() if v["status"] == "open")
        self.assertEqual(still_open, ["Q-003", "Q-004", "Q-005", "Q-006", "Q-007"])
        self.assertTrue(all(questions[q]["card_state"] == "open" and questions[q]["blocking"] is False
                            for q in still_open))
        self.assertTrue(questions["Q-001"]["blocking"])


# -- FR-P3: the technical translation -----------------------------------------------------------

class TranslationTest(FactoryTestCase):
    def test_FR_P3_AC_1_only_a_named_person_settles_a_question_put_to_them_and_no_spec_is_written_before(self):
        p = self.new(mode="socratic", maturity="demo")
        intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        q1 = canon.question("Q-001")
        first = advance(p, model=model())
        self.assertEqual((first["state"], first["stage"], first["waiting_on"]), ("waiting", 2, [q1["card"]]))
        proposed = q1["opinions"]["business"]
        with self.assertRaises(DecisionRefused):           # the factory may not settle it on its own
            canon.assume("Q-001", proposed)
        with self.assertRaises(DecisionRefused):           # nor in a non-person's name
            canon.assume("Q-001", proposed, chosen_by="factory", persona="business_owner")
        with self.assertRaises(DecisionRefused):
            canon.answer("Q-001", proposed, person="model", persona="business_owner")
        self.assertEqual(Canon(p).question("Q-001")["status"], "open")
        self.assertEqual(Canon(p).get_card(q1["card"])["state"], "open")
        self.assertEqual(Canon(p).decisions(), [])
        self.assertEqual(Canon(p).assumptions(), [])
        again = advance(p, model=model())
        self.assertEqual(again["waiting_on"], first["waiting_on"])
        self.assertFalse(p.path("spec.json").exists())     # nothing translated while it is open

        Canon(p).answer("Q-001", "the team lead approves", person="Pekka", persona="business_owner")
        after = advance(p, model=model(), max_steps=1)
        self.assertEqual(after["history"], ["spec"])
        decided = Canon(p).decisions()
        self.assertEqual([(d["card"], d["person"], d["persona"]) for d in decided],
                         [(q1["card"], "Pekka", "business_owner")])
        r2 = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        self.assertEqual((r2["sources"], r2["provenance"], r2["decided_by"]), (["Q-001"], "customer-confirmed", "Pekka"))


# -- FR-Q3: IT's requirements in the contract ---------------------------------------------------

IT_QUESTION = {"text": "Which network and security rules must the deployed service keep?",
               "why": "IT runs it and answers for it", "blocking": True,
               "proposed_answer": "no debug or admin endpoint is reachable once deployed",
               "options": ["no debug or admin endpoint is reachable once deployed", "IT reviews it after go-live"]}
IT_ANSWER = "No debug or admin endpoint may be reachable on a deployed service."
IT_PROBE = "R-2-AC-2"
LOCAL_ROADS = {
    "schema": roadmod.SCHEMA,
    "roads": {"local": {"kind": "local-process", "configured": True, "environments": list(roadmod.ENVIRONMENTS),
                        "rules": {"tls": "none: loopback only", "egress": "none"}}},
    "maturity": {m: "local" for m in MATURITIES},
}
# A product revision that opens a debug endpoint: it breaks IT's rule.
DEBUG_ROUTES = GOOD_ROUTES + '''

@route("GET", "/debug")
def debug(req):
    return 200, {"debug": True}
'''


def it_spec(it_question: str) -> dict:
    return {"title": "Equipment loans", "summary": "Track which team equipment is lent to whom.",
            "users": ["team members"],
            "interface": [{"method": "POST", "path": "/items", "purpose": "add an item"},
                          {"method": "GET", "path": "/items", "purpose": "list the items"}],
            "requirements": [
                {"statement": "A team member can add an item with a name.", "sources": ["request"], "priority": "must",
                 "acceptance": [{"given": "no items", "when": "POST /items with a name",
                                 "then": "201 and the item has an id", "kind": "test"}]},
                {"statement": "The deployed service exposes no debug or admin endpoint.", "sources": [it_question],
                 "priority": "must",
                 "acceptance": [{"given": "the service", "when": "GET /debug", "then": "404", "kind": "test"},
                                {"given": "the deployed service", "when": "GET /debug",
                                 "then": "404: no debug endpoint is reachable", "kind": "probe"}]}],
            "out_of_scope": []}


class ITRequirementTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(roadmod.rmtree, self.tmp)   # last: after every process is stopped

    def tearDown(self):
        """The temp folder goes in cleanup, after the products' processes are stopped."""

    def it_model(self, state: dict) -> FakeModel:
        panel_it = {"reading": "IT reading", "questions": [IT_QUESTION]}
        probe = {"scenarios": [{"criterion": IT_PROBE, "steps": [{"method": "GET", "path": "/debug",
                                                                  "expect_status": 404}]}]}
        return scripted(**{IT_PROMPT: panel_it, SPEC_PROMPT: lambda: it_spec(state["it_question"]),
                           HOLDOUT_PROMPT: probe})

    def it_project(self, *, it_answers: bool = True):
        state = {}
        m = self.it_model(state)
        p = self.new(mode="mixed", maturity="pilot")
        intake(p, IDEA, model=m, requested_by="Aino")
        canon = Canon(p)
        q = next(q for q in canon.questions() if q["perspective"] == "it_security")
        self.assertTrue(q["card"])                       # put to a person, not assumed
        state["it_question"] = q["id"]
        canon.answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        if it_answers:
            canon.answer(q["id"], IT_ANSWER, person="Jaana", persona="it")
        else:
            canon.assume(q["id"], IT_QUESTION["proposed_answer"], chosen_by="Aino", persona="business_owner")
        make_spec(p, model=m)
        return p, m, q["id"]

    def test_FR_Q3_AC_1_an_it_persons_answer_enters_the_contract_confirmed_and_decided_by_that_person(self):
        p, _, qid = self.it_project()
        answer = Canon(p).question(qid)["answer"]
        self.assertEqual((answer["by"], answer["persona"], answer["text"]), ("Jaana", "it", IT_ANSWER))
        contract = compile_project(p)
        reqs = {r["id"]: r for r in contract["requirements"]}
        self.assertEqual((reqs["R-2"]["provenance"], reqs["R-2"]["decided_by"], reqs["R-2"]["decided_on"]),
                         ("customer-confirmed", "Jaana", "2026-11-22"))
        self.assertEqual((reqs["R-1"]["provenance"], reqs["R-1"]["decided_by"]), ("customer-endorsed", "Aino"))
        self.assertEqual(next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")["sources"], [qid])
        report, _ = contract_check().check(contract)
        self.assertEqual(report.violations, [])
        # Had nobody from IT answered (the question assumed instead), the requirement would not be confirmed.
        p2, _, _ = self.it_project(it_answers=False)
        r2 = next(r for r in compile_project(p2)["requirements"] if r["id"] == "R-2")
        self.assertEqual((r2["provenance"], r2.get("decided_by")), ("assumption", None))

    def test_FR_Q3_AC_2_its_probe_runs_against_the_release_on_staging_and_stops_a_release_that_breaks_it(self):
        p, m, _ = self.it_project()
        contract = compile_project(p)
        crit = next(c for r in contract["requirements"] for c in r["acceptance"] if c["id"] == IT_PROBE)
        self.assertEqual(crit["check"], {"kind": "probe", "command": f"probe {IT_PROBE}"})
        row = next(r for r in p.read("checkplan.json")["checks"] if r["criterion"] == IT_PROBE)
        self.assertEqual((row["requirement"], row["kind"]), ("R-2", "probe"))
        built = build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=good_cell,
                           verifier_runner=no_findings)
        self.assertEqual(built["status"], "merged")
        self.assertEqual(author_holdouts(p, model=m), [IT_PROBE])
        self.assertTrue((p.holdouts_dir / f"{IT_PROBE}.json").exists())   # in the holdout custody, like any other
        write_json(self.factory.paved_roads_path, LOCAL_ROADS)
        self.addCleanup(roadmod.stop_started)            # runs second: anything left over
        self.addCleanup(roadmod.stop_all, p, LOCAL_ROADS)  # runs first: every slot

        first = deliver(p)
        self.assertEqual(first["state"], "waiting", first)  # the probe passed; user validation waits
        rel = p.read(f"releases/{first['release']}.json")
        result = next(r for r in rel["holdouts"]["results"] if r["criterion"] == IT_PROBE)
        self.assertEqual((rel["holdouts"]["environment"], result["kind"], result["verdict"]),
                         ("staging", "probe", "passed"))

        work = Path(tempfile.mkdtemp(prefix="edit-", dir=self.tmp))
        _git(work, "clone", "-q", str(p.path("repo.git")), "w")
        (work / "w" / "app" / "routes.py").write_text(DEBUG_ROUTES, encoding="utf-8", newline="\n")
        _git(work / "w", *GIT_ID, "commit", "-q", "-am", "A debug endpoint")
        _git(work / "w", "push", "-q", "origin", "main")

        second = deliver(p)
        self.assertEqual((second["state"], second["failed_step"]), ("failed", "holdouts:staging"), second)
        self.assertIn(f"holdout {IT_PROBE} failed at step 1", second["reason"])
        rel2 = p.read(f"releases/{second['release']}.json")
        failing = next(r for r in rel2["holdouts"]["results"] if r["criterion"] == IT_PROBE)
        self.assertEqual((failing["verdict"], failing["observed"]["status"]), ("failed", 200))
        self.assertNotIn("user_validation", [s["step"] for s in second["steps"]])   # the release stopped there


if __name__ == "__main__":
    unittest.main()
