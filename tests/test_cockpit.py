"""The cockpit: the real server on a free loopback port, in a thread, against a temp factory."""

import contextlib
import io
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, good_cell, lazy_cell, model, no_findings  # noqa: E402

from adapters.gnomon_ingest import ingest  # noqa: E402
from cockpit import server as cockpit  # noqa: E402
from cockpit.server import SubprocessRunner, make_server  # noqa: E402
from kernel.canon import CARD_DECIDERS, CARD_VERDICTS, Canon  # noqa: E402
from kernel.change import WAY_BACK, submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task, resolve_escalations  # noqa: E402
from kernel.insight import alignment, change_impact, impact  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.learn import FACTORY_PID, apply_accepted, factory_project  # noqa: E402
from kernel.people import PERSONAS  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.plan import gate as plan_gate  # noqa: E402
from kernel.projections import cell, floor  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import evidence, health, live, now, try_it  # noqa: E402
from kernel.store import STAGES, write_json  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops. We want a simple way to lend and return things."
FIX = Path(__file__).parent / "fixtures" / "gnomon"
UNPRICED = {"models": {}}  # a price table that prices nothing: every run's cost is not measured
_DEFAULT = object()
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never through a proxy


class FakeRunner:
    """Records the jobs it is asked to start; their state is whatever the test sets."""

    def __init__(self):
        self.started = []
        self.states = {}

    def start(self, args, log_path):
        assert isinstance(args, list) and all(isinstance(a, str) for a in args), args
        job_id = f"J-{len(self.started) + 1:04d}"
        self.started.append((job_id, list(args), Path(log_path)))
        self.states[job_id] = "running"
        return job_id

    def status(self, job_id):
        return {"state": self.states.get(job_id, "unknown"), "code": None}


class CockpitTestCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.runner = FakeRunner()
        self.server, self.bootstrap = make_server(self.factory, 0, runner=self.runner)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.origin = self.server.origin
        status, body, _ = self.call("POST", "/auth", {"bootstrap": self.bootstrap}, token=None)
        self.assertEqual(status, 200, body)
        self.token = body["token"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        super().tearDown()

    def call(self, method, path, body=None, *, token=_DEFAULT, origin=_DEFAULT, raw=False):
        headers = {}
        token = self.token if token is _DEFAULT else token
        origin = self.origin if origin is _DEFAULT else origin
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if origin and method != "GET":
            headers["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with _DIRECT.open(req, timeout=10) as res:
                payload, status, hdrs = res.read(), res.status, res.headers
        except urllib.error.HTTPError as exc:
            with exc:
                payload, status, hdrs = exc.read(), exc.code, exc.headers
        if raw:
            return status, payload, hdrs
        return status, (json.loads(payload) if payload else None), hdrs

    def intake_project(self, mode="mixed"):
        p = self.new(mode=mode)
        intake(p, IDEA, model=model(), requested_by="Aino")
        return p

    def built_project(self, mode="assume"):
        """Intake, spec and contract, then T-001 built and merged by a good cell (as in test_insight)."""
        p = self.intake_project(mode=mode)
        if mode == "mixed":
            Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=model())
        compile_project(p)
        build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=good_cell,
                   verifier_runner=no_findings)
        return p

    def page_js(self) -> str:
        """Every script the page loads (its ES modules), as served."""
        names = sorted(p.name for p in cockpit.STATIC_DIR.glob("*.js"))
        self.assertIn("app.js", names)
        out = []
        for name in names:
            status, payload, _ = self.call("GET", "/static/" + name, token=None, raw=True)
            self.assertEqual(status, 200, name)
            out.append(payload.decode("utf-8"))
        return chr(10).join(out)

    @staticmethod
    def as_json(obj):
        return json.loads(json.dumps(obj))

    def snapshot(self, p):
        """What a refused write must leave untouched: decisions, the inbox and the ledger."""
        inbox = {c["id"]: c["state"] for c in Canon(p).cards(state=None)}
        return (json.dumps(Canon(p).decisions(), sort_keys=True), inbox, len(p.ledger().records()))

    def all_kinds(self, p):
        canon = Canon(p)
        return {kind: canon.card(kind, f"a {kind} card", refs={"requirements": ["R-1"]})["id"]
                for kind in CARD_VERDICTS if kind != "question"}


class InboxByPersonaTest(CockpitTestCase):
    def test_FR_T1_AC_1_each_persona_sees_only_the_cards_it_may_decide_with_their_verdicts(self):
        p = self.intake_project(mode="socratic")  # question cards, open to every persona
        cards = self.all_kinds(p)
        for persona in PERSONAS:
            status, body, _ = self.call("GET", f"/api/projects/{p.pid}/inbox?persona={persona}")
            self.assertEqual(status, 200, body)
            kinds = {c["kind"] for c in body["cards"]}
            expected = {k for k, who in CARD_DECIDERS.items() if persona in who}
            self.assertEqual(kinds, expected, persona)
            for c in body["cards"]:
                self.assertEqual(c["verdicts"], list(CARD_VERDICTS[c["kind"]]), (persona, c["id"]))
            ids = {c["id"] for c in body["cards"]}
            for kind, cid in cards.items():
                self.assertEqual(cid in ids, persona in CARD_DECIDERS[kind], (persona, kind))

    def test_FR_T1_AC_1_a_persona_that_may_not_decide_is_refused_and_nothing_is_recorded(self):
        p = self.new()
        cards = self.all_kinds(p)
        before = self.snapshot(p)
        refused = [("deploy_gate", "approve", "end_user"), ("validation", "accept", "it"),
                   ("change", "accept", "developer"), ("road", "configured", "business_owner"),
                   ("incident", "approve", "operations"),  # a verdict the kind does not take
                   ("approval", "approve", "operations")]
        for kind, verdict, persona in refused:
            status, body, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{cards[kind]}/decide",
                                        {"verdict": verdict, "person": "Aino", "persona": persona, "reason": "x"})
            self.assertEqual(status, 403, (kind, verdict, persona, body))
            self.assertIn("error", body)
        self.assertEqual(self.snapshot(p), before)

    def test_FR_T1_AC_1_an_unknown_persona_gets_no_inbox(self):
        p = self.new()
        status, _, _ = self.call("GET", f"/api/projects/{p.pid}/inbox?persona=factory")
        self.assertEqual(status, 400)


class SignInTest(CockpitTestCase):
    def test_FR_T1_AC_2_the_server_binds_to_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.origin.startswith("http://127.0.0.1:"))
        for host in ("0.0.0.0", "", "::", "192.0.2.10", "localhost"):
            with self.assertRaises(ValueError):
                make_server(self.factory, 0, runner=self.runner, host=host)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cockpit.main(["--home", str(self.tmp / "home"), "--host", "0.0.0.0", "--port", "0"])
        self.assertEqual(code, 2)
        self.assertIn("127.0.0.1 only", err.getvalue())

    def test_FR_T1_AC_2_the_bootstrap_works_once(self):
        status, body, _ = self.call("POST", "/auth", {"bootstrap": self.bootstrap}, token=None)
        self.assertEqual(status, 401, body)
        status, body, _ = self.call("POST", "/auth", {"bootstrap": "guess"}, token=None)
        self.assertEqual(status, 401)
        # the session from the first use works
        status, _, _ = self.call("GET", "/api/projects")
        self.assertEqual(status, 200)
        # a signed-in page can ask for a fresh one-use link for another tab; it also works once
        status, body, _ = self.call("POST", "/api/links", {})
        self.assertEqual(status, 201)
        fresh = body["url"].split("#k=", 1)[1]
        self.assertTrue(body["url"].startswith(self.origin + "/#k="))
        self.assertEqual(self.call("POST", "/auth", {"bootstrap": fresh}, token=None)[0], 200)
        self.assertEqual(self.call("POST", "/auth", {"bootstrap": fresh}, token=None)[0], 401)

    def test_FR_T1_AC_2_writes_without_a_valid_token_or_with_a_foreign_origin_are_refused(self):
        p = self.new()
        cid = Canon(p).card("validation", "Accept the demo?")["id"]
        Canon(p).add_question("Who approves?", "business", opinions={"business": "the lead"})
        Canon(p).add_assumption("office hours", "operations")
        before = self.snapshot(p)
        decide = {"verdict": "accept", "person": "Aino", "persona": "business_owner", "reason": "ok"}
        writes = [(f"/api/projects/{p.pid}/cards/{cid}/decide", decide),
                  (f"/api/projects/{p.pid}/questions/Q-001/answer",
                   {"text": "the lead", "person": "Aino", "persona": "business_owner"}),
                  (f"/api/projects/{p.pid}/questions/Q-001/assume", {"person": "Aino", "persona": "business_owner"}),
                  (f"/api/projects/{p.pid}/assumptions/A-001/settle",
                   {"confirmed": True, "person": "Aino", "persona": "business_owner"}),
                  (f"/api/projects/{p.pid}/changes", {"text": "it crashes", "person": "Aino", "persona": "end_user"}),
                  (f"/api/projects/{p.pid}/advance", {}),
                  ("/api/projects", {"title": "x", "source": "y", "requested_by": "Aino"}),
                  ("/api/links", {})]
        for path, body in writes:
            self.assertEqual(self.call("POST", path, body, token=None)[0], 401, path)
            self.assertEqual(self.call("POST", path, body, token="not-a-session")[0], 401, path)
            self.assertEqual(self.call("POST", path, body, origin="http://evil.example")[0], 403, path)
            self.assertEqual(self.call("POST", path, body, origin=None)[0], 403, path)
            self.assertEqual(self.call("POST", path, body, origin="http://localhost:%d" % self.server.port)[0], 403)
        self.assertEqual(self.call("GET", "/api/projects", token=None)[0], 401)
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}", token="nope")[0], 401)
        # a body that is not even JSON is still refused as unauthenticated first
        junk = urllib.request.Request(self.origin + f"/api/projects/{p.pid}/cards/{cid}/decide", data=b"{not json",
                                      headers={"Origin": self.origin, "Content-Type": "text/plain"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _DIRECT.open(junk, timeout=10)
        with ctx.exception:
            self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(self.snapshot(p), before)
        self.assertEqual(self.runner.started, [])
        self.assertEqual(len(self.factory.projects()), 1)
        self.assertEqual(Canon(p).question("Q-001")["status"], "open")
        self.assertEqual(Canon(p).assumptions()[0]["status"], "open")

    def test_FR_T1_AC_2_static_files_carry_no_data_and_a_strict_policy(self):
        p = self.new(title="Secret project name")
        for path in ("/", "/static/app.js", "/static/app.css"):
            status, payload, headers = self.call("GET", path, token=None, raw=True)
            self.assertEqual(status, 200, path)
            self.assertNotIn(b"Secret project name", payload)
            self.assertNotIn(p.pid.encode(), payload)
            csp = headers["Content-Security-Policy"]
            self.assertIn("script-src 'self'", csp)
            self.assertIn("style-src 'self'", csp)
            self.assertNotIn("unsafe-inline", csp)
            self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
            self.assertIsNone(headers.get("Set-Cookie"))
        index = self.call("GET", "/", token=None, raw=True)[1].decode("utf-8")
        self.assertNotIn("<script>", index)
        self.assertNotIn("<style", index)
        self.assertNotIn("style=", index)
        self.assertNotIn("http://", index.replace("http://www.w3.org/2000/svg", ""))
        self.assertEqual(self.call("GET", "/static/../kernel/store.py", token=None, raw=True)[0], 404)
        self.assertEqual(self.call("GET", "/static/server.py", token=None, raw=True)[0], 404)
        status, _, headers = self.call("GET", "/api/projects")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(headers.get("Set-Cookie"))


class DecisionsTest(CockpitTestCase):
    def test_FR_M6_AC_3_a_cockpit_decision_carries_its_person_and_persona_in_canon_and_ledger(self):
        p = self.new()
        cid = Canon(p).card("validation", "Accept the demo?", refs={"requirements": ["R-1"]})["id"]
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{cid}/decide",
                                    {"verdict": "accept", "person": "Aino", "persona": "business_owner",
                                     "reason": "it works"})
        self.assertEqual(status, 200, body)
        d = Canon(p).decisions()[-1]
        self.assertEqual((d["card"], d["verdict"], d["person"], d["persona"], d["reason"]),
                         (cid, "accept", "Aino", "business_owner", "it works"))
        self.assertEqual(Canon(p).get_card(cid)["state"], "decided")
        events = [r["event"] for r in p.ledger().records()]
        logged = [e["payload"] for e in events if e["kind"] == "decision"]
        self.assertEqual((logged[-1]["person"], logged[-1]["persona"], logged[-1]["card"]),
                         ("Aino", "business_owner", cid))
        via = [e["payload"] for e in events if e["kind"] == "cockpit_write"]
        self.assertEqual((via[-1]["action"], via[-1]["person"], via[-1]["persona"]), ("decide", "Aino", "business_owner"))
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_M6_AC_3_settling_an_assumption_is_signed_by_person_and_persona(self):
        p = self.new()
        canon = Canon(p)
        canon.add_assumption("office hours are enough", "operations")
        canon.add_assumption("no single sign-on", "it_security")
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/assumptions/A-001/settle",
                                    {"confirmed": True, "person": "Pekka", "persona": "concept_evaluator"})
        self.assertEqual(status, 200, body)
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/assumptions/A-002/settle",
                                    {"confirmed": False, "person": "Pekka", "persona": "it",
                                     "correction": "single sign-on is required"})
        self.assertEqual(status, 200, body)
        a1, a2 = Canon(p).assumptions()
        self.assertEqual((a1["status"], a1["settled"]["by"], a1["settled"]["persona"]),
                         ("confirmed", "Pekka", "concept_evaluator"))
        self.assertEqual((a2["status"], a2["settled"]["persona"]), ("refuted", "it"))
        self.assertEqual(len(Canon(p).cards(kind="change")), 1)  # a refuted assumption opens a change
        via = [r["event"]["payload"] for r in p.ledger().records() if r["event"]["kind"] == "cockpit_write"]
        self.assertEqual([(v["target"], v["person"], v["persona"]) for v in via],
                         [("A-001", "Pekka", "concept_evaluator"), ("A-002", "Pekka", "it")])
        # a refutation without the correction, or by no one, is refused and changes nothing
        canon.add_assumption("English only", "end_user")
        before = self.snapshot(p)
        self.assertEqual(self.call("POST", f"/api/projects/{p.pid}/assumptions/A-003/settle",
                                   {"confirmed": False, "person": "Pekka", "persona": "it"})[0], 400)
        self.assertEqual(self.call("POST", f"/api/projects/{p.pid}/assumptions/A-003/settle",
                                   {"confirmed": True, "person": "factory", "persona": "it"})[0], 403)
        self.assertEqual(self.snapshot(p), before)


class QuestionsTest(CockpitTestCase):
    def test_FR_A6_AC_4_a_person_answers_an_open_question_and_the_brief_is_regenerated(self):
        p = self.intake_project(mode="mixed")
        q = Canon(p).question("Q-001")
        self.assertEqual(q["status"], "open")
        self.assertNotIn("## Answers", Canon(p).brief)
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/questions/Q-001/answer",
                                    {"text": "the team lead approves every loan", "person": "Aino",
                                     "persona": "concept_evaluator"})
        self.assertEqual(status, 200, body)
        q = Canon(p).question("Q-001")
        self.assertEqual((q["status"], q["answer"]["by"], q["answer"]["persona"]),
                         ("answered", "Aino", "concept_evaluator"))
        self.assertEqual(Canon(p).get_card(q["card"])["state"], "decided")
        brief = Canon(p).brief
        self.assertIn("## Answers [owner]", brief)
        self.assertIn("the team lead approves every loan", brief)
        self.assertEqual(body["brief"], brief)
        self.assertEqual(Canon(p).decisions()[-1]["person"], "Aino")
        # answering again is refused: the question is no longer open
        again = self.call("POST", f"/api/projects/{p.pid}/questions/Q-001/answer",
                          {"text": "someone else", "person": "Aino", "persona": "concept_evaluator"})
        self.assertEqual(again[0], 403)

    def test_FR_A6_AC_4_let_the_factory_assume_takes_the_asking_perspectives_proposal(self):
        p = self.intake_project(mode="socratic")
        q = Canon(p).question("Q-003")
        proposed = q["opinions"][q["perspective"]]
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/questions/Q-003/assume",
                                    {"person": "Aino", "persona": "concept_evaluator"})
        self.assertEqual(status, 200, body)
        q = Canon(p).question("Q-003")
        self.assertEqual((q["status"], q["answer"]["chosen_by"]), ("assumed", "Aino"))
        a = Canon(p).assumptions()[-1]
        self.assertEqual((a["text"], a["question"], a["perspective"]), (proposed, "Q-003", q["perspective"]))
        self.assertTrue(a["due"])
        card = Canon(p).get_card(q["card"])
        self.assertEqual((card["state"], card["decision"]["verdict"], card["decision"]["person"],
                          card["decision"]["persona"]), ("decided", "assume", "Aino", "concept_evaluator"))
        self.assertIn(f"{a['id']} ({q['perspective']}, due {a['due']}, open): {proposed} [assumed]", Canon(p).brief)

    def test_FR_A6_AC_4_a_question_card_decided_from_the_inbox_moves_the_question(self):
        p = self.intake_project(mode="socratic")
        card = Canon(p).question("Q-002")["card"]
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{card}/decide",
                                    {"verdict": "answer", "reason": "lost items per month", "person": "Aino",
                                     "persona": "business_owner"})
        self.assertEqual(status, 200, body)
        self.assertEqual(Canon(p).question("Q-002")["status"], "answered")
        self.assertIn("lost items per month", Canon(p).brief)
        card = Canon(p).question("Q-004")["card"]
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{card}/decide",
                                    {"verdict": "assume", "person": "Aino", "persona": "business_owner"})
        self.assertEqual(status, 200, body)
        self.assertEqual(Canon(p).question("Q-004")["status"], "assumed")

    def test_FR_A6_AC_4_assume_without_a_person_or_a_proposal_is_refused(self):
        p = self.new(mode="socratic")
        Canon(p).add_question("Who pays?", "business")  # nobody proposed an answer
        Canon(p).add_question("Which browsers?", "end_user", opinions={"end_user": "current ones"})
        before = self.snapshot(p)
        self.assertEqual(self.call("POST", f"/api/projects/{p.pid}/questions/Q-001/assume",
                                   {"person": "Aino", "persona": "business_owner"})[0], 409)
        self.assertEqual(self.call("POST", f"/api/projects/{p.pid}/questions/Q-002/assume",
                                   {"person": "model", "persona": "business_owner"})[0], 403)
        self.assertEqual(self.call("POST", f"/api/projects/{p.pid}/questions/Q-002/assume",
                                   {"person": "Aino", "persona": "robot"})[0], 403)
        self.assertEqual(self.snapshot(p), before)
        # a question that was never put to a person becomes a card, so the choice is a signed decision
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/questions/Q-002/assume",
                                    {"person": "Aino", "persona": "end_user"})
        self.assertEqual(status, 200, body)
        d = Canon(p).decisions()[-1]
        self.assertEqual((d["verdict"], d["person"], d["persona"]), ("assume", "Aino", "end_user"))


class ChangesTest(CockpitTestCase):
    def test_FR_I1_AC_1_an_end_user_tester_submits_feedback_and_it_becomes_a_triaged_change_card(self):
        p = self.intake_project(mode="assume")
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/changes",
                                    {"persona": "end_user", "person": "Tiina",
                                     "text": "Adding an item with an empty name crashes with 500"})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["triage"]["class"], "defect")
        self.assertEqual(body["triage"]["way_back"], WAY_BACK["defect"])
        card = Canon(p).get_card(body["card"]["id"])
        self.assertEqual(card["kind"], "change")
        self.assertEqual((card["payload"]["source"], card["payload"]["person"]), ("end_user", "Tiina"))
        self.assertEqual(card["payload"]["triage"]["class"], "defect")
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        self.assertIn("change_submitted", kinds)
        self.assertIn("change_triaged", kinds)
        # the project view lists it with its class and way back
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertEqual([(c["id"], c["payload"]["triage"]["class"]) for c in view["changes"]],
                         [(card["id"], "defect")])
        # a hint from the tester's observation kind is kept
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/changes",
                                    {"persona": "end_user", "person": "Tiina", "hint": "new_requirement",
                                     "text": "We would like to see the loan history of one item"})
        self.assertEqual((status, body["triage"]["class"]), (201, "new_requirement"))
        self.assertTrue(body["triage"]["needs_decision"])

    def test_FR_I1_AC_1_feedback_without_a_person_or_text_is_refused(self):
        p = self.new()
        before = self.snapshot(p)
        url = f"/api/projects/{p.pid}/changes"
        self.assertEqual(self.call("POST", url, {"persona": "end_user", "person": "bot", "text": "x"})[0], 403)
        self.assertEqual(self.call("POST", url, {"persona": "end_user", "person": "Tiina", "text": " "})[0], 400)
        self.assertEqual(self.call("POST", url, {"persona": "end_user", "person": "Tiina", "text": "x",
                                                 "hint": "whatever"})[0], 400)
        self.assertEqual(self.snapshot(p), before)


class ViewsAndJobsTest(CockpitTestCase):
    def test_personas_and_projects_list(self):
        p = self.intake_project(mode="socratic")
        status, personas, _ = self.call("GET", "/api/personas")
        self.assertEqual(status, 200)
        self.assertEqual([x["id"] for x in personas], list(PERSONAS))
        self.assertTrue(all(x["label"] for x in personas))
        it = next(x for x in personas if x["id"] == "it")
        self.assertIn("deploy_gate", it["decides"])
        status, projects, _ = self.call("GET", "/api/projects")
        self.assertEqual(status, 200)
        row = projects[0]
        self.assertEqual((row["id"], row["mode"], row["stage"], row["stage_name"]),
                         (p.pid, "socratic", 2, "concept"))
        self.assertEqual(row["open_cards"], len(Canon(p).cards()))
        self.assertEqual(self.call("GET", "/api/projects/no-such-project")[0], 404)

    def test_project_view_shows_opinions_overdue_assumptions_and_ledger_status(self):
        p = self.intake_project(mode="mixed")
        status, view, _ = self.call("GET", f"/api/projects/{p.pid}")
        self.assertEqual(status, 200, view)
        q1 = next(q for q in view["questions"] if q["id"] == "Q-001")
        side = {o["perspective"]: o for o in q1["opinions_side_by_side"]}
        self.assertTrue(side["business"]["asked"])
        self.assertIn("audit", side["it_security"]["opinion"])
        self.assertIsNone(side["operations"]["opinion"])
        self.assertEqual(q1["proposed"], "the team lead approves")
        self.assertFalse(any(a["overdue"] for a in view["assumptions"]))
        self.assertTrue(view["ledger"]["intact"])
        self.assertEqual(view["ledger"]["records"], len(p.ledger().records()))
        self.assertEqual(view["meta"]["stage_name"], "concept")
        self.assertIn("# Brief: Equipment loans", view["brief"])
        self.clock.advance(days=30)
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertTrue(all(a["overdue"] for a in view["assumptions"]))
        self.assertTrue(view["ledger"]["tail_checked"])
        # cutting the ledger's last record is caught against the head the cockpit kept
        lines = p.path("ledger.jsonl").read_text(encoding="utf-8").splitlines()
        p.path("ledger.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8", newline="\n")
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertFalse(view["ledger"]["intact"])

    def test_tasks_and_releases_are_listed_as_they_are(self):
        p = self.new()
        p.write("tasks.json", {"T-001": {"status": "merged", "rounds": [{"round": 0, "cell": {"model": "m"}, "gate": {
            "verdict": "passed", "warranted": True, "objections": [],
            "signals": [{"name": "tests", "verdict": "passed", "native": {}, "detail": "3 ran"},
                        {"name": "fail_first", "verdict": "passed", "native": {}, "detail": ""}]}}]}})
        p.write("releases/1.json", {"environment": "demo", "steps": ["build", "deploy"], "canary": {"share": 10}})
        p.write("releases/2.json", {"environment": "staging"})
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertEqual(view["tasks"][0]["rounds"][0]["gate"]["signals"][1],
                         {"name": "fail_first", "verdict": "passed", "detail": ""})
        self.assertEqual([r["name"] for r in view["releases"]], ["1", "2"])
        self.assertEqual(view["releases"][0]["data"]["canary"], {"share": 10})

    def test_a_new_project_starts_an_intake_job_and_advance_starts_a_run(self):
        status, body, _ = self.call("POST", "/api/projects", {
            "title": "Equipment loans", "source": IDEA, "mode": "socratic", "maturity": "explore",
            "requested_by": "Aino"})
        self.assertEqual(status, 201, body)
        pid = body["project"]["id"]
        p = self.factory.project(pid)
        self.assertEqual((p.meta["mode"], p.meta["maturity"]), ("socratic", "explore"))
        job_id, args, log = self.runner.started[0]
        self.assertEqual(args[:4], ["-m", "kernel.cli", "intake", pid])
        self.assertEqual(args[4], "--source-file")
        self.assertEqual(Path(args[5]).read_text(encoding="utf-8").strip(), IDEA)
        self.assertEqual(args[6:], ["--requested-by", "Aino"])
        self.assertEqual(log.parent, self.factory.home / "jobs")
        jobs = self.call("GET", "/api/jobs")[1]
        self.assertEqual([(j["id"], j["kind"], j["state"]) for j in jobs], [(job_id, "intake", "running")])
        # one job at a time per project
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/advance", {})[0], 409)
        self.runner.states[job_id] = "done"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("line 1\nintake done\n", encoding="utf-8")
        status, body, _ = self.call("POST", f"/api/projects/{pid}/advance", {"person": "Aino", "persona": "developer"})
        self.assertEqual(status, 202, body)
        self.assertEqual(self.runner.started[1][1], ["-m", "kernel.cli", "run", pid])
        jobs = self.call("GET", f"/api/jobs?project={pid}")[1]
        self.assertEqual([j["kind"] for j in jobs], ["run", "intake"])
        self.assertEqual(jobs[1]["log_tail"], ["line 1", "intake done"])
        # bad input is refused before anything is created
        for bad in ({"title": "x", "source": "y", "mode": "yolo", "requested_by": "Aino"},
                    {"title": "x", "source": "y", "maturity": "beta", "requested_by": "Aino"},
                    {"title": "", "source": "y", "requested_by": "Aino"},
                    {"title": "x", "source": "y", "requested_by": "autopilot"}):
            self.assertIn(self.call("POST", "/api/projects", bad)[0], (400, 403), bad)
        self.assertEqual(len(self.factory.projects()), 1)

    def test_the_default_runner_runs_an_argument_list_without_a_shell(self):
        runner = SubprocessRunner(self.factory.home)
        with self.assertRaises(TypeError):
            runner.start("-c print('hi')", self.tmp / "x.log")
        log = self.tmp / "jobs" / "j.log"
        job = runner.start(["-c", "import os; print('home=' + os.environ['GNOMONFACTORY_HOME'])"], log)
        deadline = time.monotonic() + 30
        while runner.status(job)["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(runner.status(job), {"state": "done", "code": 0})
        self.assertIn(f"home={self.factory.home}", log.read_text(encoding="utf-8"))
        self.assertEqual(runner.status("J-nope")["state"], "unknown")


class StageSummaryTest(CockpitTestCase):
    def test_FR_T1_AC_3_the_stage_summary_counts_each_stage_and_groups_them_in_four_bands(self):
        p = self.built_project(mode="mixed")                     # demo maturity: stages 1 to 5 run
        Canon(p).card("validation", "Accept the demo?", refs={"requirements": ["R-1"]})
        p.write("releases/1.json", {"release": 1, "state": "done"})
        status, view, _ = self.call("GET", f"/api/projects/{p.pid}")
        self.assertEqual(status, 200, view)
        s = view["stage_summary"]
        self.assertEqual([(b["id"], b["label"], b["stages"]) for b in s["bands"]],
                         [("decide", "Decide", [1, 2]), ("shape", "Shape", [3, 4]), ("deliver", "Deliver", [5, 6]),
                          ("run", "Run", [7])])
        self.assertEqual([(x["stage"], x["name"], x["band"]) for x in s["stages"]],
                         [(n, STAGES[n], b) for n, b in zip(range(1, 8), ["decide", "decide", "shape", "shape",
                                                                          "deliver", "deliver", "run"])])
        questions = Canon(p).questions()
        blocking = [q for q in questions if q["blocking"]]
        contract = p.read("contract.json")
        counts = {x["stage"]: (x["count"]["value"], x["count"]["total"], x["count"]["label"]) for x in s["stages"]}
        self.assertEqual(counts, {
            1: (sum(q["status"] == "open" for q in blocking), len(blocking), "blocking open"),
            2: (sum(q["status"] == "open" for q in questions), len(questions), "questions open"),
            3: (len(contract["requirements"]), None, "requirements"),
            4: (sum(len(r["acceptance"]) for r in contract["requirements"]), None, "criteria"),
            5: (1, len(contract["tasks"]), "tasks merged"),
            6: (1, 1, "validations open"),
            7: (1, None, "releases"),
        })
        self.assertEqual((counts[3][0], counts[4][0], counts[5][1]), (4, 6, 4))   # the fake spec's 4 requirements
        self.assertEqual(s["current"], 5)
        self.assertEqual([x["state"] for x in s["stages"]], ["done"] * 4 + ["now", "off", "off"])
        # the page gets the same four bands with the meta, for every project
        meta = self.call("GET", "/api/meta")[1]
        self.assertEqual(meta["bands"], s["bands"])
        self.assertEqual(meta["maturity_last_stage"]["demo"], 5)


class ImpactAndAlignmentTest(CockpitTestCase):
    def test_FR_P5_AC_3_a_change_cards_impact_comes_before_the_decision_and_showing_it_changes_nothing(self):
        p = self.built_project()
        canon = Canon(p)
        acc = canon.card("validation", "Accept the pilot?", refs={"requirements": ["R-1"]})
        canon.decide(acc["id"], "accept", person="Aino", persona="business_owner")
        card = submit(p, persona="end_user", person="Tiina", text="Adding an item with an empty name crashes with 500")
        triage(p, card["id"], model=model())
        before = self.snapshot(p)
        status, inbox, _ = self.call("GET", f"/api/projects/{p.pid}/inbox?persona=business_owner")
        self.assertEqual(status, 200, inbox)
        shown = next(c for c in inbox["cards"] if c["id"] == card["id"])
        self.assertEqual((shown["state"], shown["verdicts"]), ("open", ["accept", "reject", "defer"]))
        im = shown["impact"]
        self.assertEqual(im, self.as_json(change_impact(p, card["id"])))
        self.assertEqual(im["requirements"], ["R-1"])
        self.assertEqual(im["criteria"], ["R-1-AC-1", "R-1-AC-2"])
        self.assertEqual(im["tests"]["R-1-AC-1"], ["test_R_1_AC_1_post_item_returns_201_with_id"])
        self.assertEqual(im["tasks_reopened"], ["T-001"])
        self.assertEqual([(a["card"], a["kind"], a["person"]) for a in im["approvals_going_stale"]],
                         [(acc["id"], "validation", "Aino")])
        # the Changes view carries the same impact, and the impact route answers for any requirements
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertEqual(next(c for c in view["changes"] if c["id"] == card["id"])["impact"], im)
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/impact?requirements=R-1")[:2], (200, im))
        status, other, _ = self.call("GET", f"/api/projects/{p.pid}/impact?requirements=R-2,R-9")
        self.assertEqual((status, other), (200, self.as_json(impact(p, ["R-2", "R-9"]))))
        self.assertEqual(other["unknown_requirements"], ["R-9"])
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/impact")[0], 400)
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/impact?requirements=../x")[0], 400)
        # showing it changed nothing: no decision, no stale approval, the card still open, no ledger event
        self.assertEqual(self.snapshot(p), before)
        self.assertEqual(Canon(p).decisions(stale=True), [])
        self.assertEqual(Canon(p).get_card(card["id"])["state"], "open")
        # a change that triage has not tied to requirements has no impact yet: null, not a guess
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/changes",
                                    {"persona": "end_user", "person": "Tiina", "text": "The list looks cramped"})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["triage"]["requirements"], [])
        self.assertIsNone(body["card"]["impact"])

    def test_FR_S6_AC_2_the_canons_alignment_findings_are_returned_and_an_empty_list_without_contradictions(self):
        calm = self.intake_project(mode="mixed")
        self.assertEqual(self.call("GET", f"/api/projects/{calm.pid}/alignment")[:2], (200, []))
        p = self.new(title="Repairs")
        canon = Canon(p)
        q = canon.add_question("Who repairs broken items?", "operations",
                               opinions={"operations": "the IT desk", "business": "the team itself"})
        canon.assume(q["id"], "the IT desk")
        before = self.snapshot(p)
        status, found, _ = self.call("GET", f"/api/projects/{p.pid}/alignment")
        self.assertEqual(status, 200, found)
        self.assertEqual(found, self.as_json(alignment(p)))
        self.assertEqual([(f["kind"], f["refs"]["question"], f["refs"]["dissent"]) for f in found],
                         [("assumed_over_dissent", q["id"], ["business"])])
        self.assertEqual(self.snapshot(p), before)                  # listed, not resolved
        self.assertEqual(self.call("GET", "/api/projects/no-such-project/alignment")[0], 404)


class CellAndFloorTest(CockpitTestCase):
    def test_FR_M3_AC_3_the_cell_and_floor_projections_are_returned_and_unmeasured_cost_is_null_never_zero(self):
        record = json.loads((FIX / "analyst-run.record.json").read_text(encoding="utf-8"))
        trail = FIX / "analyst-run.jsonl"
        p = self.built_project()                                     # stage 5; T-001's cell ran on fake-builder
        ingest(p, dict(record, verify="passed"), trail, task="T-001", round_no=0, prices=UNPRICED)
        ingest(p, dict(record, verify="failed"), trail, task="T-001", round_no=1, prices=UNPRICED)
        ingest(p, dict(record, bucket="apparatus_failure", code=10), trail, task="T-001", round_no=2, prices=UNPRICED)
        factory_project(self.factory)                                # Rihma's own canon is not a product
        status, rows, _ = self.call("GET", f"/api/projects/{p.pid}/cell")
        self.assertEqual(status, 200, rows)
        self.assertEqual(rows, self.as_json(cell(p)))
        self.assertEqual([(r["role"], r["model"], r["verdict"], r["apparatus_failure"]) for r in rows],
                         [("analyst", "deepseek-v4-pro", "passed", False), ("analyst", "deepseek-v4-pro", "failed", False),
                          ("analyst", "deepseek-v4-pro", "not measured", True)])
        self.assertEqual((rows[0]["native"]["bucket"], rows[0]["native"]["code"]), ("result", 0))
        self.assertTrue(all(r["chain"]["intact"] for r in rows))
        self.assertEqual((rows[0]["tokens"]["in"], rows[0]["tokens"]["out"]), (2366, 7564))
        for r in rows:
            self.assertFalse(r["cost"]["measured"])
            self.assertIsNone(r["cost"]["amount"])                    # not measured, never 0
        status, f, _ = self.call("GET", "/api/floor")
        self.assertEqual(status, 200, f)
        self.assertEqual(f["by_phase"], {"5 build and verify": {"passed": 1, "failed": 1, "not measured": 1}})
        self.assertEqual((f["overall"]["rate"], f["overall"]["measured"], f["overall"]["apparatus_failures"]),
                         (0.5, 2, 1))
        self.assertIsNone(f["spend"]["cloud"])                         # not measured, never 0
        self.assertEqual((f["spend"]["unmeasured_runs"], f["spend"]["cloud_measured_part"]), (3, 0))
        self.assertEqual([x["id"] for x in f["projects"]], [p.pid])
        builder = f["model_reliability"]["fake-builder"]
        self.assertEqual((builder["cells"], builder["first_round_warranted_rate"], builder["mean_rounds_to_pass"]),
                         (1, 1.0, 1.0))
        self.assertEqual(f["immune_memory"], [])
        # a project without runs has an empty Cell, and its stage adds nothing to the Floor
        q = self.new(title="Quiet")
        self.assertEqual(self.call("GET", f"/api/projects/{q.pid}/cell")[:2], (200, []))
        self.assertEqual(set(self.call("GET", "/api/floor")[1]["by_phase"]), {"5 build and verify"})


class EvidenceNowAndHealthTest(CockpitTestCase):
    """Where a project stands (kernel/status.py), as the cockpit serves it."""

    def test_FR_O6_AC_4_the_cockpit_returns_every_criterions_evidence_and_the_project_view_counts_each_state(self):
        p = self.built_project()                                     # T-001 merged through a passing gate
        p.write("releases/1.json", {"number": 1, "state": "done", "steps": [
            {"step": "holdouts:demo", "outcome": "failed",
             "native": {"ran": ["R-1-AC-2", "R-4-AC-2"], "failing": [{"criterion": "R-4-AC-2"}]}}]})
        before = self.snapshot(p)
        status, rows, _ = self.call("GET", f"/api/projects/{p.pid}/evidence")
        self.assertEqual(status, 200, rows)
        self.assertEqual(rows, self.as_json(evidence(p)))
        contract = p.read("contract.json")
        self.assertEqual([r["criterion"] for r in rows],
                         [c["id"] for r in contract["requirements"] for c in r["acceptance"]])   # every criterion
        states = {r["criterion"]: r["state"] for r in rows}
        self.assertEqual(states, {"R-1-AC-1": "verified", "R-1-AC-2": "held_out", "R-2-AC-1": "not_measured",
                                  "R-3-AC-1": "not_measured", "R-4-AC-1": "not_measured", "R-4-AC-2": "failing"})
        verified = next(r for r in rows if r["criterion"] == "R-1-AC-1")["evidence"][0]
        self.assertEqual((verified["task"], verified["round"], verified["tests"]),
                         ("T-001", 0, ["test_R_1_AC_1_post_item_returns_201_with_id"]))
        # the project view carries the same rows and the counts per state, for the project and each requirement
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertEqual(view["evidence"], rows)
        summary = view["evidence_summary"]
        self.assertEqual(summary["counts"], {"verified": 1, "held_out": 1, "claimed": 0, "failing": 1, "not_measured": 3})
        self.assertEqual(summary["total"], 6)
        self.assertEqual(summary["by_requirement"]["R-1"],
                         {"verified": 1, "held_out": 1, "claimed": 0, "failing": 0, "not_measured": 0})
        self.assertEqual(summary["by_requirement"]["R-4"]["failing"], 1)
        stage5 = next(s for s in view["stage_summary"]["stages"] if s["stage"] == 5)
        self.assertEqual(stage5["evidence"], {"verified": 1, "claimed": 0})      # the rail's "1 verified · 0 claimed"
        # a criterion a test only names, merged without a passing gate, is "claimed", never counted as verified
        q = self.intake_project(mode="assume")
        make_spec(q, model=model())
        compile_project(q)
        esc = build_task(q, "T-001", lanes=Lanes(self.tmp / "lanes-q", size=1), cell_runner=lazy_cell,
                         verifier_runner=no_findings, max_rounds=0)
        Canon(q).decide(esc["card"], "accept_as_is", person="Aino", persona="business_owner")
        resolve_escalations(q)
        qv = self.call("GET", f"/api/projects/{q.pid}")[1]
        self.assertEqual(next(r for r in qv["evidence"] if r["criterion"] == "R-1-AC-1")["state"], "claimed")
        self.assertEqual((qv["evidence_summary"]["counts"]["verified"], qv["evidence_summary"]["counts"]["claimed"]), (0, 1))
        self.assertEqual(next(s for s in qv["stage_summary"]["stages"] if s["stage"] == 5)["evidence"],
                         {"verified": 0, "claimed": 1})
        # reading the evidence changed nothing
        self.assertEqual(self.snapshot(p), before)
        self.assertEqual(self.call("GET", "/api/projects/no-such-project/evidence")[0], 404)

    def test_FR_A6_AC_6_question_options_come_with_the_proposal_first_and_an_option_is_recorded_as_the_signed_answer(self):
        p = self.intake_project(mode="mixed")                        # Q-001 blocks and is put to a person
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        q1 = next(q for q in view["questions"] if q["id"] == "Q-001")
        options = ["the team lead approves", "any team member", "the IT desk", "a fourth"]
        self.assertEqual((q1["options"], q1["recommended"], q1["proposed"]), (options, options[0], options[0]))
        for q in view["questions"]:                                  # the panel's proposal first, two to four at most
            self.assertLessEqual(len(q["options"]), 4, q["id"])
            if q["proposed"]:
                self.assertEqual(q["options"][0], q["proposed"], q["id"])
        inbox = self.call("GET", f"/api/projects/{p.pid}/inbox?persona=end_user")[1]
        card = next(c for c in inbox["cards"] if c["kind"] == "question")
        self.assertEqual((card["question"]["id"], card["question"]["options"]), ("Q-001", options))
        # answering with an option records that option's text, signed with person and persona
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/questions/Q-001/answer",
                                    {"text": options[1], "person": "Tiina", "persona": "end_user"})
        self.assertEqual(status, 200, body)
        q = Canon(p).question("Q-001")
        self.assertEqual((q["status"], q["answer"]["text"], q["answer"]["by"], q["answer"]["persona"]),
                         ("answered", "any team member", "Tiina", "end_user"))
        d = Canon(p).decisions()[-1]
        self.assertEqual((d["card"], d["verdict"], d["person"], d["persona"], d["reason"]),
                         (card["id"], "answer", "Tiina", "end_user", "any team member"))
        via = [r["event"]["payload"] for r in p.ledger().records() if r["event"]["kind"] == "cockpit_write"][-1]
        self.assertEqual((via["action"], via["target"], via["person"], via["persona"], via["option"]),
                         ("answer", "Q-001", "Tiina", "end_user", 1))
        self.assertIn("any team member", Canon(p).brief)
        # the recommended option chosen from the Inbox card is recorded as option 0; one's own words carry no option
        s = self.intake_project(mode="socratic")
        cid = Canon(s).question("Q-001")["card"]
        status, body, _ = self.call("POST", f"/api/projects/{s.pid}/cards/{cid}/decide",
                                    {"verdict": "answer", "reason": options[0], "person": "Aino",
                                     "persona": "business_owner"})
        self.assertEqual(status, 200, body)
        self.assertEqual(Canon(s).question("Q-001")["answer"]["text"], options[0])
        self.call("POST", f"/api/projects/{s.pid}/questions/Q-002/answer",
                  {"text": "fewer lost items, counted monthly", "person": "Aino", "persona": "business_owner"})
        writes = [r["event"]["payload"] for r in s.ledger().records() if r["event"]["kind"] == "cockpit_write"]
        self.assertEqual([(w["target"], w.get("option")) for w in writes], [("Q-001", 0), ("Q-002", None)])
        # a question kept from before options existed offers its proposal alone; with no proposal, none
        o = self.new(title="Older")
        Canon(o).add_question("Which browsers?", "end_user", opinions={"end_user": "current ones"})
        Canon(o).add_question("Who pays?", "business")
        older = {q["id"]: q for q in self.call("GET", f"/api/projects/{o.pid}")[1]["questions"]}
        self.assertEqual((older["Q-001"]["options"], older["Q-001"]["recommended"]), (["current ones"], "current ones"))
        self.assertEqual((older["Q-002"]["options"], older["Q-002"]["recommended"]), ([], None))

    def test_FR_T1_AC_6_the_projects_list_and_view_carry_now_and_the_view_carries_health(self):
        waiting = self.intake_project(mode="mixed")                  # a blocking question is open
        built = self.built_project(mode="mixed")                     # Q-001 answered, T-001 merged
        before = (self.snapshot(waiting), self.snapshot(built))
        status, projects, _ = self.call("GET", "/api/projects")
        self.assertEqual(status, 200, projects)
        rows = {r["id"]: r for r in projects}
        self.assertEqual(rows[waiting.pid]["now"], self.as_json(now(waiting)))
        self.assertEqual(rows[built.pid]["now"], self.as_json(now(built)))
        self.assertEqual(rows[waiting.pid]["now"]["state"], "waiting_on_you")
        self.assertIn("question", rows[waiting.pid]["now"]["line"])
        self.assertEqual(rows[built.pid]["now"]["state"], "working")
        for p in (waiting, built):
            view = self.call("GET", f"/api/projects/{p.pid}")[1]
            self.assertEqual(view["now"], self.as_json(now(p)))
            self.assertEqual(view["health"], self.as_json(health(p)))
            self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/now")[:2], (200, view["now"]))
            self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/health")[:2], (200, view["health"]))
            self.assertEqual(set(view["health"]), {"status", "reasons", "forecast"})
            self.assertEqual(set(view["health"]["forecast"]),
                             {"tasks_left", "median_task_minutes", "eta_minutes", "basis"})
        self.assertEqual((before[0], before[1]), (self.snapshot(waiting), self.snapshot(built)))   # reads only
        # with no merged task the forecast says "not measured", never a number
        h = self.call("GET", f"/api/projects/{waiting.pid}")[1]["health"]
        self.assertEqual((h["status"], h["forecast"]["median_task_minutes"], h["forecast"]["eta_minutes"]),
                         ("on_track", None, None))
        self.assertIn("not measured", h["forecast"]["basis"])
        h = self.call("GET", f"/api/projects/{built.pid}")[1]["health"]
        self.assertEqual((h["forecast"]["tasks_left"], h["forecast"]["basis"]), (3, "1 merged task(s) in this project"))
        # an escalation puts it at risk, with a reason naming the card, and the project waits on a person
        esc = Canon(built).card("escalation", "T-002 did not pass its gate", refs={"task": "T-002"}, blocking=True)
        view = self.call("GET", f"/api/projects/{built.pid}")[1]
        self.assertEqual(view["health"]["status"], "at_risk")
        self.assertTrue(any(r.startswith(esc["id"] + ":") for r in view["health"]["reasons"]))
        self.assertEqual((view["now"]["state"], view["now"]["cards"]), ("waiting_on_you", [esc["id"]]))
        listed = {r["id"]: r for r in self.call("GET", "/api/projects")[1]}
        self.assertEqual(listed[built.pid]["now"]["state"], "waiting_on_you")
        for route in ("now", "health"):
            self.assertEqual(self.call("GET", f"/api/projects/no-such-project/{route}")[0], 404)

    def test_the_ledger_marks_who_acted_a_person_or_an_agent_with_its_model(self):
        p = self.built_project(mode="mixed")
        recent = self.call("GET", f"/api/projects/{p.pid}")[1]["ledger"]["recent"]
        first = {}
        for e in recent:
            first.setdefault(e["kind"], e["actor"])
        self.assertEqual(first["decision"], {"type": "person", "name": "Aino", "persona": "business_owner"})
        self.assertEqual(first["cell_ran"], {"type": "agent", "name": "builder", "model": "fake-builder"})
        self.assertEqual(first["spec_written"], {"type": "agent", "name": "analyst", "model": None})
        self.assertEqual(first["gate"], {"type": "agent", "name": "the kernel", "model": None})
        self.assertEqual(first["merged"]["name"], "the kernel")
        self.assertTrue(all(e["actor"]["type"] in ("person", "agent") for e in recent))

    def test_the_page_carries_a_labelled_palette_dialog_and_no_data(self):
        index = self.call("GET", "/", token=None, raw=True)[1].decode("utf-8")
        self.assertIn('<dialog id="palette"', index)
        self.assertIn('aria-labelledby="pal-h"', index)
        self.assertIn('role="combobox"', index)
        self.assertIn('role="listbox"', index)


class FactoryInboxTest(CockpitTestCase):
    def test_rihmas_own_proposals_are_listed_as_rihma_itself_and_decided_like_any_card(self):
        p = self.new()
        fp = factory_project(self.factory)
        card = Canon(fp).card("approval", "Add a default check to every project: 400, not 500",
                              body="Seen in 2 projects: a, b.", refs={"scope": "factory", "kind": "default_check"},
                              payload={"class": "400 500 empty name", "given": "-", "when": "POST /items with an empty name",
                                       "then": "400, not 500", "projects": ["a", "b"]})
        projects = self.call("GET", "/api/projects")[1]
        self.assertEqual([(r["id"], r["title"], r["factory"]) for r in projects],
                         [(FACTORY_PID, "Rihma itself", True), (p.pid, "Equipment loans", False)])
        self.assertEqual(projects[0]["open_by_kind"], {"approval": 1})
        status, view, _ = self.call("GET", f"/api/projects/{FACTORY_PID}")
        self.assertEqual(status, 200, view)
        self.assertEqual((view["meta"]["title"], view["meta"]["factory"]), ("Rihma itself", True))
        inbox = self.call("GET", f"/api/projects/{FACTORY_PID}/inbox?persona=product_owner")[1]
        self.assertEqual([c["id"] for c in inbox["cards"]], [card["id"]])
        self.assertEqual(self.call("GET", f"/api/projects/{FACTORY_PID}/inbox?persona=end_user")[1]["cards"], [])
        # refused like any card: a persona that may not decide it, or no person
        before = self.snapshot(fp)
        for who in ({"person": "Aino", "persona": "end_user"}, {"person": "factory", "persona": "product_owner"}):
            self.assertEqual(self.call("POST", f"/api/projects/{FACTORY_PID}/cards/{card['id']}/decide",
                                       dict(who, verdict="approve"))[0], 403)
        self.assertEqual(self.snapshot(fp), before)
        status, body, _ = self.call("POST", f"/api/projects/{FACTORY_PID}/cards/{card['id']}/decide",
                                    {"verdict": "approve", "person": "Aino", "persona": "product_owner",
                                     "reason": "seen twice"})
        self.assertEqual(status, 200, body)
        d = Canon(fp).decisions()[-1]
        self.assertEqual((d["card"], d["verdict"], d["person"], d["persona"]),
                         (card["id"], "approve", "Aino", "product_owner"))
        self.assertEqual(apply_accepted(self.factory)[0]["accepted_by"], "Aino")   # the kernel applies it, not the cockpit


class PlanTest(CockpitTestCase):
    """Approve the plan before building (kernel/plan.py), through the cockpit."""

    def pilot(self):
        p = self.new(mode="assume", maturity="pilot")
        intake(p, IDEA, model=model(), requested_by="Aino")
        first = advance(p, model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=generic_cell,
                        verifier_runner=no_findings)
        self.assertEqual((first["state"], first["stage"]), ("waiting", 4))
        return p, first["waiting_on"][0]

    def test_FR_P7_AC_4_the_cockpit_returns_the_plan_and_a_persons_edit_makes_them_the_owner(self):
        p, cid = self.pilot()
        before = self.snapshot(p)
        status, plan, _ = self.call("GET", f"/api/projects/{p.pid}/plan")
        self.assertEqual(status, 200, plan)
        self.assertTrue(plan["required"])
        self.assertIsNone(plan["approved"])
        self.assertFalse(plan["compiled"])
        self.assertEqual((plan["card"]["id"], plan["card"]["kind"], plan["card"]["refs"]["scope"]), (cid, "approval", "plan"))
        self.assertEqual(plan["card"]["verdicts"], ["approve", "reject"])
        spec = p.read("spec.json")
        self.assertEqual([r["id"] for r in plan["spec"]["requirements"]], [r["id"] for r in spec["requirements"]])
        r2 = next(r for r in plan["spec"]["requirements"] if r["id"] == "R-2")
        self.assertEqual([c["id"] for c in r2["acceptance"]], ["R-2-AC-1"])
        self.assertEqual(r2["acceptance"][0]["then"], "400 with an error")
        self.assertEqual(plan["editors"], ["business_owner", "product_owner", "developer"])
        self.assertEqual(self.snapshot(p), before)                    # reading the plan opened nothing
        # a non-person, or a persona that may not edit the plan, is refused and nothing is recorded
        url = f"/api/projects/{p.pid}/plan/requirements/R-2"
        edit = {"statement": "A loan records who approved it.",
                "acceptance": [{"given": "an item", "when": "POST /items/{id}/loan with approver",
                                "then": "201 and the approver is stored", "kind": "test"}]}
        for who in ({"person": "factory", "persona": "product_owner"}, {"person": "Ilkka", "persona": "it"},
                    {"person": "Tiina", "persona": "end_user"}, {"person": "Aino", "persona": "robot"}):
            status, body, _ = self.call("POST", url, dict(edit, **who))
            self.assertEqual(status, 403, (who, body))
            self.assertIn("error", body)
        self.assertEqual(self.call("POST", url, dict(edit, person="Pekka", persona="product_owner"), token=None)[0], 401)
        self.assertEqual(self.call("POST", url, dict(edit, person="Pekka", persona="product_owner"),
                                   origin="http://evil.example")[0], 403)
        self.assertEqual(self.snapshot(p), before)
        self.assertEqual(p.read("spec.json"), spec)
        # bad input is refused before the kernel sees it
        who = {"person": "Pekka", "persona": "product_owner"}
        self.assertEqual(self.call("POST", url, who)[0], 400)                                   # nothing to change
        self.assertEqual(self.call("POST", url, dict(who, acceptance=[{"given": "x", "then": ""}]))[0], 400)
        self.assertEqual(self.call("POST", url, dict(who, acceptance=[{"then": "x", "kind": "vibes"}]))[0], 400)
        self.assertEqual(self.call("POST", url, dict(who, acceptance="all of them"))[0], 400)
        self.assertEqual(self.call("POST", f"/api/projects/{p.pid}/plan/requirements/R-99", dict(edit, **who))[0], 404)
        self.assertEqual(self.snapshot(p), before)
        # a person's edit is recorded, makes them the requirement's owner, and the card is reissued
        status, body, _ = self.call("POST", url, dict(edit, **who))
        self.assertEqual(status, 200, body)
        req = next(r for r in p.read("spec.json")["requirements"] if r["id"] == "R-2")
        self.assertEqual((req["statement"], req["provenance"], req["decided_by"]),
                         ("A loan records who approved it.", "customer-confirmed", "Pekka"))
        self.assertIn("edit:Pekka", req["sources"])
        self.assertEqual([(c["id"], c["then"]) for c in req["acceptance"]], [("R-2-AC-1", "201 and the approver is stored")])
        self.assertEqual(body["requirement"]["decided_by"], "Pekka")
        self.assertEqual(Canon(p).get_card(cid)["state"], "withdrawn")
        new = body["plan"]["card"]
        self.assertNotEqual(new["id"], cid)
        self.assertIn("A loan records who approved it.", new["body"])
        self.assertEqual(new["refs"]["spec_version"], p.meta["spec_version"])
        self.assertEqual([(h["card"], h["state"]) for h in body["plan"]["history"]], [(cid, "withdrawn")])
        events = [r["event"] for r in p.ledger().records()]
        edited = [e["payload"] for e in events if e["kind"] == "plan_edited"]
        self.assertEqual((edited[-1]["requirement"], edited[-1]["by"], edited[-1]["persona"]), ("R-2", "Pekka", "product_owner"))
        via = [e["payload"] for e in events if e["kind"] == "cockpit_write"][-1]
        self.assertEqual((via["action"], via["target"], via["person"], via["persona"]),
                         ("edit_requirement", "R-2", "Pekka", "product_owner"))
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/plan")[1]["card"]["id"], new["id"])
        # approving through the Inbox route lets the pipeline go on; the plan then says who approved it
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{new['id']}/decide",
                                    {"verdict": "approve", "person": "Aino", "persona": "business_owner", "reason": "go"})
        self.assertEqual(status, 200, body)
        self.assertIsNone(plan_gate(p, model=model()))
        approved = self.call("GET", f"/api/projects/{p.pid}/plan")[1]
        self.assertEqual((approved["card"], approved["approved"]["by"], approved["approved"]["card"]),
                         (None, "Aino", new["id"]))
        # once compiled, a change goes through the change loop: an edit is refused and nothing is recorded
        compile_project(p)
        before = self.snapshot(p)
        self.assertEqual(self.call("POST", url, dict(edit, **who))[0], 403)
        self.assertEqual(self.snapshot(p), before)
        self.assertEqual(self.call("GET", "/api/projects/no-such-project/plan")[0], 404)

    def test_a_project_without_a_plan_says_so_and_a_demo_needs_no_approval(self):
        p = self.intake_project(mode="mixed")                        # demo, no spec yet
        status, plan, _ = self.call("GET", f"/api/projects/{p.pid}/plan")
        self.assertEqual(status, 200, plan)
        self.assertEqual((plan["required"], plan["card"], plan["spec"]), (False, None, None))
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/plan/requirements/R-1",
                                    {"statement": "x", "person": "Pekka", "persona": "product_owner"})
        self.assertEqual(status, 409, body)


class PauseTest(CockpitTestCase):
    def test_FR_J3_AC_2_pause_and_resume_are_signed_refused_for_a_persona_that_may_not_and_now_says_paused(self):
        p = self.new()
        before = self.snapshot(p)
        url = f"/api/projects/{p.pid}"
        for who in ({"person": "Tiina", "persona": "end_user"}, {"person": "Pekka", "persona": "stakeholder"},
                    {"person": "factory", "persona": "operations"}, {"person": "Olli", "persona": "robot"}):
            status, body, _ = self.call("POST", url + "/pause", dict(who, reason="x"))
            self.assertEqual(status, 403, (who, body))
        self.assertEqual(self.call("POST", url + "/pause", {"person": "Olli", "persona": "operations"}, token=None)[0], 401)
        self.assertEqual(self.call("POST", url + "/pause", {"person": "Olli", "persona": "operations"},
                                   origin="http://evil.example")[0], 403)
        self.assertEqual(self.call("POST", url + "/resume", {"person": "Olli", "persona": "operations"})[0], 409)
        self.assertEqual(self.snapshot(p), before)
        self.assertIsNone(p.meta.get("pause"))
        status, body, _ = self.call("POST", url + "/pause",
                                    {"person": "Olli", "persona": "operations", "reason": "the GPU box is being patched"})
        self.assertEqual(status, 200, body)
        self.assertEqual((p.meta["pause"]["requested_by"], p.meta["pause"]["persona"], p.meta["pause"]["reason"]),
                         ("Olli", "operations", "the GPU box is being patched"))
        self.assertEqual(body["now"]["state"], "paused")
        status, n, _ = self.call("GET", url + "/now")
        self.assertEqual((status, n["state"]), (200, "paused"))
        self.assertIn("Paused by Olli", n["line"])
        self.assertEqual(n, self.as_json(now(p)))
        listed = {r["id"]: r for r in self.call("GET", "/api/projects")[1]}
        self.assertEqual(listed[p.pid]["now"]["state"], "paused")
        self.assertEqual(self.call("GET", url)[1]["meta"]["pause"]["requested_by"], "Olli")
        events = [r["event"] for r in p.ledger().records()]
        asked = [e["payload"] for e in events if e["kind"] == "pause_requested"][-1]
        self.assertEqual((asked["by"], asked["persona"]), ("Olli", "operations"))
        via = [e["payload"] for e in events if e["kind"] == "cockpit_write"][-1]
        self.assertEqual((via["action"], via["person"], via["persona"]), ("pause", "Olli", "operations"))
        # a second pause is refused; a persona that may not resume is refused and it stays paused
        self.assertEqual(self.call("POST", url + "/pause", {"person": "Aino", "persona": "business_owner"})[0], 409)
        before = self.snapshot(p)
        self.assertEqual(self.call("POST", url + "/resume", {"person": "Tiina", "persona": "end_user"})[0], 403)
        self.assertEqual(self.call("POST", url + "/resume", {"person": "kernel", "persona": "it"})[0], 403)
        self.assertEqual(self.snapshot(p), before)
        self.assertEqual(now(p)["state"], "paused")
        status, body, _ = self.call("POST", url + "/resume", {"person": "Pekka", "persona": "product_owner"})
        self.assertEqual(status, 200, body)
        self.assertNotEqual(body["now"]["state"], "paused")
        self.assertIsNone(p.meta.get("pause"))
        events = [r["event"] for r in p.ledger().records()]
        back = [e["payload"] for e in events if e["kind"] == "resumed"][-1]
        self.assertEqual((back["by"], back["persona"]), ("Pekka", "product_owner"))
        self.assertEqual(self.call("GET", "/api/meta")[1]["may_pause"],
                         ["business_owner", "product_owner", "developer", "operations", "it"])
        self.assertEqual(self.call("POST", f"/api/projects/{FACTORY_PID}/pause",
                                   {"person": "Olli", "persona": "operations"})[0], 404)


class LiveTest(CockpitTestCase):
    def test_FR_T1_AC_8_the_cockpit_returns_the_running_cells_live_view_from_a_gnomon_audit_trail(self):
        p = self.new()
        other = self.new(title="Other loans")
        root = self.tmp / "gf-lanes"
        root.mkdir()
        with mock.patch.dict(os.environ, {"GF_LANES": str(root)}):
            status, body, _ = self.call("GET", f"/api/projects/{p.pid}/live")
            self.assertEqual(status, 200, body)
            self.assertFalse(body["running"])
            self.assertIn("no lane", body["why"])
            lane = root / "lane-1"
            (lane / ".gnomon-audit").mkdir(parents=True)
            write_json(root / ".lane-1.lease.json", {"holder": f"{p.pid}:T-001"})
            trail = [{"seq": 0, "kind": "session_start", "role": "builder"},
                     {"seq": 1, "kind": "model_call", "model": "deepseek-v4-pro"},
                     {"seq": 2, "kind": "tool_call", "tool": "write", "target": "app/routes.py", "ts": "2026-11-22T10:00:01Z"},
                     {"seq": 3, "kind": "tool_call", "tool": "bash", "target": "python3 -m unittest discover -s tests",
                      "ts": "2026-11-22T10:00:09Z", "bucket": "result"}]
            (lane / ".gnomon-audit" / "task-1.jsonl").write_text("\n".join(json.dumps(r) for r in trail) + "\n",
                                                                 encoding="utf-8", newline="\n")
            status, body, _ = self.call("GET", f"/api/projects/{p.pid}/live")
            self.assertEqual(status, 200, body)
            self.assertEqual(body, self.as_json(live(p)))
            self.assertEqual((body["running"], body["task"], body["lane"], body["role"], body["model"], body["steps"]),
                             (True, "T-001", "lane-1", "builder", "deepseek-v4-pro", 2))
            self.assertEqual((body["last"]["tool"], body["last"]["target"]), ("bash", "python3 -m unittest discover -s tests"))
            self.assertFalse(body["ended"])
            # another project holds no lane: none runs for it
            self.assertFalse(self.call("GET", f"/api/projects/{other.pid}/live")[1]["running"])
            self.assertEqual(self.call("GET", "/api/projects/no-such-project/live")[0], 404)


class TryItTest(CockpitTestCase):
    def test_FR_R1_AC_2_the_cockpit_returns_the_try_it_checklist_and_a_testers_report_names_the_criterion(self):
        p = self.built_project()                                     # T-001 merged through a passing gate
        status, tr, _ = self.call("GET", f"/api/projects/{p.pid}/try")
        self.assertEqual(status, 200, tr)
        self.assertIsNone(tr["url"])                                  # nothing deployed yet
        write_json(p.path("releases", "1.json"), {"number": 1, "state": "waiting", "steps": [
            {"step": "deploy:demo", "outcome": "passed", "native": {"base_url": "http://127.0.0.1:32774"}}]})
        before = self.snapshot(p)
        status, tr, _ = self.call("GET", f"/api/projects/{p.pid}/try")
        self.assertEqual(status, 200, tr)
        self.assertEqual(tr, self.as_json(try_it(p)))
        self.assertEqual((tr["release"], tr["env"], tr["url"]), (1, "demo", "http://127.0.0.1:32774"))
        contract = p.read("contract.json")
        self.assertEqual([i["criterion"] for i in tr["items"]], [c["id"] for r in contract["requirements"] for c in r["acceptance"]])
        first = tr["items"][0]
        self.assertTrue(first["text"].startswith("Given no items, when POST /items with a name, check that"))
        self.assertEqual((first["criterion"], first["evidence"]), ("R-1-AC-1", "verified"))
        self.assertEqual(self.snapshot(p), before)                    # reading it changed nothing
        # a tester's report on one item is a change card that names the criterion, signed by the tester
        status, body, _ = self.call("POST", f"/api/projects/{p.pid}/changes",
                                    {"persona": "end_user", "person": "Tiina", "hint": "defect",
                                     "text": "[R-1-AC-1] Adding a drill returned 201, but the item had no id"})
        self.assertEqual(status, 201, body)
        card = Canon(p).get_card(body["card"]["id"])
        self.assertEqual(card["kind"], "change")
        self.assertTrue(card["title"].startswith("[R-1-AC-1] "))
        self.assertIn("[R-1-AC-1]", card["payload"]["text"])
        self.assertEqual((card["payload"]["source"], card["payload"]["person"], card["payload"]["triage"]["class"]),
                         ("end_user", "Tiina", "defect"))
        listed = self.call("GET", f"/api/projects/{p.pid}")[1]["changes"]
        self.assertTrue(any(c["id"] == card["id"] and c["title"].startswith("[R-1-AC-1]") for c in listed))
        self.assertEqual(self.call("GET", "/api/projects/no-such-project/try")[0], 404)


class FloorGatesTest(CockpitTestCase):
    def test_FR_M3_AC_5_the_cockpits_floor_returns_the_gate_headline_with_the_harness_outcomes_and_their_note(self):
        p = self.intake_project(mode="assume")
        make_spec(p, model=model())
        compile_project(p)
        lanes = Lanes(self.tmp / "lanes", size=1)
        build_task(p, "T-001", lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings)
        build_task(p, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=1)
        record = json.loads((FIX / "analyst-run.record.json").read_text(encoding="utf-8"))
        ingest(p, dict(record), FIX / "analyst-run.jsonl", prices=UNPRICED)   # a harness outcome: not measured
        status, f, _ = self.call("GET", "/api/floor")
        self.assertEqual(status, 200, f)
        expected = self.as_json(floor(self.factory))
        self.assertEqual(f["gates"], expected["gates"])
        g = f["gates"]
        self.assertEqual((g["tasks_gated"], g["first_round_passed"], g["first_round_rate"]), (2, 1, 0.5))
        self.assertEqual((g["merged"], g["escalated"]), (1, 1))
        self.assertGreaterEqual(g["rounds"], 2)
        # the harness outcomes stay beside the headline, with their note verbatim
        self.assertEqual(f["overall"], expected["overall"])
        self.assertEqual(f["harness_note"], expected["harness_note"])
        self.assertIn("the gate judges the work", f["harness_note"])
        self.assertEqual(f["overall"]["not_measured"], 1)
        self.assertEqual([x["gates"]["tasks_gated"] for x in f["projects"]], [2])
        # the page puts the gate first and labels the harness outcomes as each run's
        js = self.page_js()
        self.assertIn("Harness outcomes (each Gnomon run)", js)
        self.assertIn("passed their gate on the first round", js)
        self.assertLess(js.index("passed their gate on the first round"), js.index("Harness outcomes (each Gnomon run)"))

class RedesignTestCase(CockpitTestCase):
    """Helpers for the redesigned cockpit's routes (FR-T1-AC-11 to AC-15, FR-V1-AC-5)."""

    def ledgers(self):
        """Every project's ledger length, the factory's own canon included, less the usage metadata of a model's
        run (model_run, FR-INS1-AC-9): that says a model answered, never what; it is no write of the route's."""
        return {p.pid: len([r for r in p.ledger().records() if r["event"]["kind"] != "model_run"])
                for p in self.factory.projects()}

    def assert_no_ledger_writes(self, before):
        """No ledger that existed got a record; one created meanwhile (the factory's own canon, made on
        first use) holds none."""
        after = self.ledgers()
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)
        self.assertEqual({k: v for k, v in after.items() if k not in before and v}, {})

    def put(self, path, body, **kw):
        return self.call("PUT", path, body, **kw)

    def start_server(self, **kw):
        """A second cockpit over the same factory (for an injected assistant model)."""
        server, bootstrap = make_server(self.factory, 0, runner=FakeRunner(), **kw)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(5)
        self.addCleanup(stop)
        return server, bootstrap


# Which read model of GET /api/dashboard each widget of the library draws from.
WIDGET_MODEL = {"kpi_strip": "kpis", "square": "square", "pipeline": "pipeline", "decisions": "decisions",
                "catalogue": "catalogue", "live": "projects", "timeline": "timelines", "gate_trend": "gate_trend",
                "coverage": "coverage", "activity": "activity", "models": "models", "health": "projects",
                "updates": "updates", "autonomy": "autonomy", "evidence_packs": "evidence_packs", "spend": "spend",
                "feed_health": "feed_health", "eval_trend": "eval_trend", "try_it": "try_it", "track": "track",
                "insight": "insights"}


class DashboardLayoutTest(RedesignTestCase):
    def test_FR_T1_AC_11_the_dashboard_returns_every_widgets_read_model_and_writes_nothing(self):
        from kernel.dashboard import coverage, gate_trend, pipeline, timeline

        p = self.built_project()
        before = self.ledgers()
        status, d, _ = self.call("GET", "/api/dashboard")
        self.assertEqual(status, 200, d)
        self.assertEqual(set(WIDGET_MODEL), set(cockpit.WIDGETS))           # every widget has its read model
        for widget, key in WIDGET_MODEL.items():
            self.assertIn(key, d, widget)
            self.assertIsNotNone(d[key], widget)
        self.assertEqual(d["problems"], [])
        self.assertEqual(d["gate_trend"], self.as_json(gate_trend(self.factory)))
        self.assertEqual(d["coverage"], self.as_json(coverage(self.factory)))
        self.assertEqual(d["gates"], self.as_json(floor(self.factory)["gates"]))
        self.assertEqual(d["timelines"][p.pid]["tasks"], self.as_json(timeline(p)["tasks"]))
        self.assertEqual(d["pipeline"]["total"], pipeline(self.factory)["total"])
        chip = d["pipeline"]["bands"][2]["stages"][0]["projects"][0]        # stage 5, with its work profile
        self.assertEqual((chip["id"], chip["profile"]), (p.pid, "web_service"))
        k = d["kpis"]
        self.assertEqual((k["first_round"]["num"], k["first_round"]["of"]), (1, 1))
        self.assertEqual(k["first_round"]["provenance"], "derived")
        self.assertEqual(k["in_flight"]["of"], 1)
        self.assertIsNone(d["spend"]["cloud"] if d["spend"]["unmeasured_runs"] else None)  # never 0 for unmeasured
        self.assertFalse(d["feed_health"]["measured"])
        self.assertTrue(d["feed_health"]["why"])
        self.assertIn(d["evidence_packs"][0]["verdict"], ("attestable", "chain broken", "insufficient evidence"))
        self.assert_no_ledger_writes(before)                             # a read records nothing

    def test_FR_T1_AC_11_a_layout_with_its_theme_is_kept_per_person_persona_and_lens_within_its_bounds(self):
        p = self.built_project()
        before = self.ledgers()
        q = "/api/layout?persona=developer&lens=delivery&person=Dev"
        status, out, _ = self.call("GET", q)
        self.assertEqual(status, 200, out)
        self.assertTrue(out["preset"])
        self.assertEqual([w["type"] for w in out["layout"]["widgets"]],
                         [t for t, _ in cockpit.LENS_DEFAULTS["delivery"]])
        layout = {"v": 1, "lens": "delivery", "widgets": [
            {"id": "gt", "type": "gate_trend", "size": "XL", "view": "table", "filter": {}},
            {"id": "lv", "type": "live", "size": "M", "view": "chart", "filter": {"project": p.pid}}],
            "theme": {"accent": "teal", "density": "compact", "mode": "dark", "radius": "crisp", "font_scale": 1.1}}
        status, out, _ = self.put(q, {"person": "Dev", "layout": layout})
        self.assertEqual(status, 200, out)
        status, out, _ = self.call("GET", q)
        self.assertFalse(out["preset"])
        self.assertEqual(out["layout"], layout)
        # per person, per persona and per lens
        self.assertTrue(self.call("GET", "/api/layout?persona=developer&lens=delivery&person=Olli")[1]["preset"])
        self.assertTrue(self.call("GET", "/api/layout?persona=operations&lens=delivery&person=Dev")[1]["preset"])
        self.assertTrue(self.call("GET", "/api/layout?persona=developer&lens=insight&person=Dev")[1]["preset"])
        # a persona's own lens is the default when none is named
        self.assertEqual(self.call("GET", "/api/layout?persona=developer&person=Dev")[1]["layout"], layout)
        files = list((self.factory.home / "_cockpit" / "layouts").rglob("*.json"))
        self.assertEqual(len(files), 1)
        # refused: unknown widget types, more than 24 widgets, theme values outside the fixed sets, a non-person
        many = dict(layout, widgets=[{"id": f"w{i}", "type": "activity", "size": "S"} for i in range(25)])
        bad = [dict(layout, widgets=[{"id": "x", "type": "rm_rf_widget", "size": "M"}]), many,
               dict(layout, theme={"accent": "neon"}), dict(layout, theme={"font_scale": 3}),
               dict(layout, theme={"css": "body{display:none}"}), dict(layout, theme={"mode": "sepia"}),
               dict(layout, widgets=[{"id": "x", "type": "activity", "size": "XXL"}]),
               dict(layout, widgets=[{"id": "x", "type": "activity"}, {"id": "x", "type": "spend"}]),
               dict(layout, widgets=[{"id": "x", "type": "activity", "view": "pie"}]),
               dict(layout, v=2), dict(layout, lens="insight")]
        for b in bad:
            status, err, _ = self.put(q, {"person": "Dev", "layout": b})
            self.assertEqual(status, 400, (b, err))
        for who in ("assistant", "", "factory"):
            self.assertEqual(self.put(q, {"person": who, "layout": layout})[0], 403, who)
        self.assertEqual(self.put("/api/layout?persona=nobody&lens=delivery", {"person": "Dev", "layout": layout})[0], 400)
        self.assertEqual(self.put(q, {"person": "Dev", "layout": layout}, origin="http://evil.example")[0], 403)
        self.assertEqual(self.put(q, {"person": "Dev", "layout": layout}, token=None)[0], 401)
        self.assertEqual(self.call("GET", q)[1]["layout"], layout)                # nothing refused was kept
        self.assert_no_ledger_writes(before)                                  # never in a project ledger
        self.assertEqual(self.call("DELETE", q)[0], 405)


class ContextTest(RedesignTestCase):
    def test_FR_T1_AC_12_the_context_gives_the_personas_lens_and_the_stage_ordered_views_with_the_profile(self):
        from kernel.lenses import project_context

        p = self.built_project()
        base = f"/api/projects/{p.pid}/context"
        status, ctx, _ = self.call("GET", base + "?persona=developer")
        self.assertEqual(status, 200, ctx)
        self.assertEqual((ctx["lens"], ctx["default_lens"]), ("delivery", "delivery"))
        self.assertEqual(ctx["stage"], 5)
        self.assertEqual(ctx["views"][:2], ["tasks", "live"])              # stage 5 brings the run forward
        self.assertEqual(ctx["views"], project_context(p, "developer")["views"])
        self.assertEqual(ctx["profile"]["id"], "web_service")
        self.assertEqual(self.call("GET", base + "?persona=business_owner")[1]["lens"], "business")
        self.assertEqual(self.call("GET", base + "?persona=compliance")[1]["lens"], "compliance")
        status, ctx, _ = self.call("GET", base + "?persona=developer&lens=business")   # an explicit lens wins
        self.assertEqual((ctx["lens"], ctx["default_lens"]), ("business", "delivery"))
        self.assertEqual(ctx["views"], project_context(p, "developer", "business")["views"])
        self.assertEqual(self.call("GET", base + "?persona=nobody")[0], 400)
        self.assertEqual(self.call("GET", base + "?persona=developer&lens=no-such")[0], 400)
        self.assertEqual(self.call("GET", "/api/projects/no-such-project/context?persona=developer")[0], 404)


class CommentsTest(RedesignTestCase):
    def test_FR_T1_AC_13_comments_are_signed_listed_by_target_and_only_an_owner_promotes_one_into_a_change(self):
        p = self.built_project()
        base = f"/api/projects/{p.pid}/comments"
        cards_before = len(Canon(p).cards(state=None))
        status, out, _ = self.call("POST", base, {"target": {"kind": "requirement", "id": "R-1"},
                                                  "text": "Could small items skip the approval?",
                                                  "person": "Sanna", "persona": "stakeholder"})
        self.assertEqual(status, 201, out)
        self.assertEqual((out["comment"]["id"], out["comment"]["person"], out["comment"]["persona"]),
                         ("CM-001", "Sanna", "stakeholder"))
        self.assertEqual(self.call("POST", base, {"target": {"kind": "task", "id": "T-001"}, "text": "Looks right",
                                                  "person": "Dev", "persona": "developer"})[0], 201)
        status, listed, _ = self.call("GET", base + "?kind=requirement&id=R-1")
        self.assertEqual([c["id"] for c in listed["comments"]], ["CM-001"])
        self.assertEqual(len(self.call("GET", base)[1]["comments"]), 2)
        self.assertEqual(len(Canon(p).cards(state=None)), cards_before)       # a comment decides nothing
        writes = [r["event"]["payload"] for r in p.ledger().of_kind("cockpit_write")]
        self.assertIn({"action": "comment", "target": "CM-001", "person": "Sanna", "persona": "stakeholder"}, writes)
        # refused: a bad target, empty text, a non-person
        for body, code in (({"target": {"kind": "nothing", "id": "x"}, "text": "t"}, 400),
                           ({"target": {"kind": "requirement", "id": "R-1"}, "text": "  "}, 400),
                           ({"target": "R-1", "text": "t"}, 400)):
            self.assertEqual(self.call("POST", base, dict(body, person="Sanna", persona="stakeholder"))[0], code, body)
        self.assertEqual(self.call("POST", base, {"target": {"kind": "requirement", "id": "R-1"}, "text": "t",
                                                  "person": "assistant", "persona": "stakeholder"})[0], 403)
        # a stakeholder may comment but not promote; nothing is recorded when refused
        snap = self.snapshot(p)
        self.assertEqual(self.call("POST", base + "/CM-001/promote", {"person": "Sanna", "persona": "stakeholder"})[0], 403)
        self.assertEqual(self.call("POST", base + "/CM-001/promote", {"person": "assistant",
                                                                       "persona": "product_owner"})[0], 403)
        self.assertEqual(self.snapshot(p), snap)
        self.assertEqual(self.call("POST", base + "/CM-099/promote", {"person": "Pekka", "persona": "product_owner"})[0], 404)
        status, out, _ = self.call("POST", base + "/CM-001/promote", {"person": "Pekka", "persona": "product_owner"})
        self.assertEqual(status, 201, out)
        self.assertEqual(out["card"]["kind"], "change")
        self.assertIn("[requirement R-1]", out["card"]["payload"]["text"])
        self.assertIn("comment by Sanna", out["card"]["payload"]["text"])
        self.assertTrue(out["triage"])
        self.assertEqual(Canon(p).comments()[0]["promoted_to"], out["card"]["id"])
        self.assertEqual(self.call("POST", base + "/CM-001/promote", {"person": "Pekka", "persona": "product_owner"})[0], 403)


class SquareCatalogueTest(RedesignTestCase):
    def test_FR_T1_AC_15_a_signal_is_triaged_into_a_concept_an_owner_validates_into_a_project_in_square_and_catalogue(self):
        status, out, _ = self.call("POST", "/api/signals", {
            "text": "Warehouse staff need a way to report damaged pallets from a phone", "channel": "meeting",
            "source": "ops weekly", "person": "Sanna", "persona": "stakeholder"})
        self.assertEqual(status, 201, out)
        sid = out["signal"]["id"]
        self.assertEqual((out["signal"]["state"], out["signal"]["person"]), ("new", "Sanna"))
        self.assertEqual(self.call("GET", "/api/square")[1]["signals"]["new"], 1)
        self.assertEqual(self.call("POST", "/api/signals", {"text": "x", "channel": "carrier pigeon",
                                                            "person": "Sanna", "persona": "stakeholder"})[0], 400)
        self.assertEqual(self.call("POST", "/api/signals", {"text": "x", "person": "bot", "persona": "stakeholder"})[0], 403)
        status, out, _ = self.call("POST", f"/api/signals/{sid}/triage", {"person": "Sanna", "persona": "stakeholder"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["signal"]["state"], "concept")
        cid = out["signal"]["routed_to"]["card"]
        self.assertEqual(self.call("POST", f"/api/signals/{sid}/triage", {"person": "Sanna", "persona": "stakeholder"})[0], 409)
        sq = self.call("GET", "/api/square")[1]
        self.assertEqual([c["card"] for c in sq["concepts_waiting"]], [cid])
        self.assertEqual([c["card"] for c in sq["concepts"]], [cid])
        cat = self.call("GET", "/api/catalogue")[1]
        self.assertEqual([(i["state"], i.get("card")) for i in cat["items"]], [("proposed", cid)])
        # only a business owner or product owner edits and validates a concept
        edit = f"/api/concepts/{cid}/edit"
        self.assertEqual(self.call("POST", edit, {"maturity": "pilot", "person": "Dev", "persona": "developer"})[0], 403)
        self.assertEqual(self.call("POST", edit, {"maturity": "huge", "person": "Aino", "persona": "business_owner"})[0], 400)
        status, out, _ = self.call("POST", edit, {"title": "Damaged pallet reports", "profile": "mobile_prototype",
                                                  "person": "Aino", "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["card"]["payload"]["profile"], "mobile_prototype")
        decide = f"/api/projects/{FACTORY_PID}/cards/{cid}/decide"
        for persona in ("developer", "stakeholder", "it"):
            self.assertEqual(self.call("POST", decide, {"verdict": "validate", "person": "Dev",
                                                        "persona": persona})[0], 403, persona)
        self.assertEqual(len(self.factory.projects()), 1)                     # only the factory's own canon
        status, out, _ = self.call("POST", decide, {"verdict": "validate", "reason": "worth a demo",
                                                    "person": "Aino", "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        pid = out["project"]                                                   # created in the same request
        self.assertEqual(out["applied"], [{"card": cid, "verdict": "validate", "project": pid}])
        new = self.factory.project(pid)
        applied = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("concept_applied")]
        self.assertEqual([(a["card"], a["project"], a["person"]) for a in applied], [(cid, pid, "Aino")])
        self.assertEqual((new.meta["title"], new.meta["profile"]), ("Damaged pallet reports", "mobile_prototype"))
        sq = self.call("GET", "/api/square")[1]
        self.assertEqual(sq["concepts_waiting"], [])
        self.assertEqual(sq["pipeline"]["total"], 1)
        self.assertEqual(next(s for s in sq["signals_list"] if s["id"] == sid)["state"], "validated")
        cat = self.call("GET", "/api/catalogue")[1]
        self.assertEqual([(i["project"], i["state"]) for i in cat["items"]], [(pid, "shaping")])
        self.assertIn(pid, [x["id"] for x in self.call("GET", "/api/projects")[1]])

    def test_FR_T1_AC_15_an_embeds_key_is_returned_once_never_listed_and_the_embed_is_revoked(self):
        p = self.new()
        body = {"kind": "feedback", "origins": ["https://shop.example"], "project": p.pid, "label": "Shop feedback",
                "brief": "The equipment loans app", "person": "Pekka", "persona": "product_owner"}
        self.assertEqual(self.call("POST", "/api/embeds", dict(body, persona="end_user"))[0], 403)
        self.assertEqual(self.call("POST", "/api/embeds", dict(body, origins=["javascript:alert(1)"]))[0], 400)
        self.assertEqual(self.call("POST", "/api/embeds", dict(body, project="no-such-project"))[0], 404)
        status, out, _ = self.call("POST", "/api/embeds", body)
        self.assertEqual(status, 201, out)
        key, eid = out["key"], out["embed"]["id"]
        self.assertTrue(key.startswith("rk_"))
        self.assertIn(key, out["snippet"])
        self.assertIn(eid, out["snippet"])
        self.assertNotIn("key", out["embed"])
        self.assertNotIn("key_sha256", out["embed"])
        status, raw, _ = self.call("GET", "/api/embeds", raw=True)
        self.assertEqual(status, 200)
        self.assertNotIn(key.encode(), raw)                                    # shown once, never listed
        self.assertNotIn(b"key_sha256", raw)
        listed = json.loads(raw)["embeds"]
        self.assertEqual((listed[0]["id"], listed[0]["state"], listed[0]["messages"]), (eid, "active", 0))
        self.assertEqual(self.call("POST", f"/api/embeds/{eid}/revoke", {"person": "Sanna", "persona": "stakeholder"})[0], 403)
        self.assertEqual(self.call("POST", "/api/embeds/E-099/revoke", {"person": "Pekka", "persona": "it"})[0], 404)
        status, out, _ = self.call("POST", f"/api/embeds/{eid}/revoke", {"person": "Pekka", "persona": "it"})
        self.assertEqual((status, out["embed"]["state"]), (200, "revoked"))
        self.assertEqual(self.call("GET", "/api/embeds")[1]["embeds"][0]["state"], "revoked")

    def test_FR_T1_AC_15_the_autonomy_cap_is_set_only_by_an_allowed_persona_with_a_reason(self):
        p = self.new()
        ok = {"level": 3, "reason": "a defence customer: nothing reaches staging alone", "person": "Aino",
              "persona": "business_owner"}
        for body, code in ((dict(ok, persona="developer"), 403), (dict(ok, person="assistant"), 403),
                           (dict(ok, reason=""), 400), (dict(ok, level=9), 400), (dict(ok, level="3"), 400),
                           (dict(ok, level=True), 400)):
            self.assertEqual(self.put("/api/autonomy", body)[0], code, body)
        self.assertEqual(self.call("GET", "/api/autonomy")[1]["factory"]["cap"], 4)
        status, out, _ = self.put("/api/autonomy", ok)
        self.assertEqual((status, out["cap"]), (200, 3))
        base = f"/api/projects/{p.pid}/autonomy"
        self.assertEqual(self.put(base, dict(ok, level=4, person="Kaisa", persona="compliance"))[0], 403)  # above the factory
        status, out, _ = self.put(base, dict(ok, level=2, person="Kaisa", persona="compliance", reason="answers only"))
        self.assertEqual((status, out["cap"]), (200, 2))
        a = self.call("GET", "/api/autonomy")[1]
        self.assertEqual(a["factory"]["cap"], 3)
        self.assertEqual(a["projects"][0]["cap"], 2)
        self.assertEqual({(h["scope"], h["to"], h["reason"], h["by"]) for h in a["history"]},
                         {("factory", 3, ok["reason"], "Aino"), ("project", 2, "answers only", "Kaisa")})
        self.assertEqual(self.put("/api/autonomy", ok, origin=None)[0], 403)

    def test_FR_T1_AC_15_an_evidence_pack_is_exported_and_downloadable_once_only_from_the_exports_folder(self):
        import zipfile

        p = self.built_project()
        base = f"/api/projects/{p.pid}"
        self.assertEqual(self.call("GET", base + "/pack")[0], 404)            # no release yet
        status, att, _ = self.call("GET", base + "/attestation")
        self.assertIn(att["verdict"], ("attestable", "chain broken", "insufficient evidence"))
        self.assertNotIn("compliant", att["verdict"])
        self.assertTrue(any(c["status"] == "no" for c in att["controls"]))
        self.assertEqual(self.call("POST", base + "/evidence", {"person": "Sanna", "persona": "stakeholder"})[0], 403)
        status, out, _ = self.call("POST", base + "/evidence", {"person": "Kaisa", "persona": "compliance"})
        self.assertEqual(status, 201, out)
        exports = self.factory.home / "_cockpit" / "exports"
        self.assertTrue((exports / out["file"]).is_file())
        self.assertTrue(out["download"].startswith("/api/exports/"))
        self.assertEqual(self.call("GET", out["download"], token=None, raw=True)[0], 401)
        status, payload, headers = self.call("GET", out["download"], raw=True)
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn(out["file"], headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            self.assertIn("MANIFEST.json", z.namelist())
        self.assertEqual(self.call("GET", out["download"], raw=True)[0], 404)    # once
        self.assertEqual(self.call("GET", "/api/exports/" + "A" * 32, raw=True)[0], 404)
        self.assertEqual(self.call("GET", "/api/exports/..%2F..%2Fprojects", raw=True)[0], 404)
        # a link can only name a file in the exports folder
        stray = self.factory.home / "stray.zip"
        stray.write_bytes(b"not an export")
        token = self.server.offer_download("../stray.zip")
        self.assertEqual(self.call("GET", f"/api/exports/{token}", raw=True)[0], 404)
        self.assertIn("evidence_exported", [r["event"]["kind"] for r in p.ledger().records()])
        # with a release, the capability pack is built by a signed POST and shown with its YAML
        write_json(p.path("releases", "1.json"), {"release": 1, "maturity": "demo", "state": "done",
                                                    "revision": "abc123", "steps": []})
        status, out, _ = self.call("POST", base + "/pack/build", {"person": "Kaisa", "persona": "compliance"})
        self.assertEqual(status, 200, out)
        self.assertEqual((out["pack"]["version"], out["pack"]["release"]), ("1.0.0", 1))
        self.assertIn("rihma.capability-pack.v1", out["yaml"])
        self.assertEqual(self.call("GET", base + "/pack")[1]["pack"]["version"], "1.0.0")   # same content

    def test_FR_T1_AC_15_an_update_is_decided_through_the_inbox_route_and_recorded_for_a_trial(self):
        from kernel.observations import observe

        p = self.built_project()
        obs = observe(self.factory, "model_release", facts={"project": p.pid, "model": "qwen3-coder-next",
                                                            "eval_delta": "+6%"}, source="release feed")
        cid = obs["touched"][0]["card"]
        d = self.call("GET", "/api/dashboard")[1]
        update = next(u for u in d["updates"] if u["card"] == cid)
        self.assertEqual(set(update["views"]), {"developer", "expert", "business"})
        self.assertIn(cid, [i["card"] for i in d["decisions"]])
        inbox = self.call("GET", "/api/inbox?persona=compliance")[1]
        self.assertIn(cid, [c["id"] for c in inbox["cards"]])
        decide = f"/api/projects/{p.pid}/cards/{cid}/decide"
        self.assertEqual(self.call("POST", decide, {"verdict": "trial", "person": "Sanna", "persona": "stakeholder"})[0], 403)
        status, out, _ = self.call("POST", decide, {"verdict": "trial", "person": "Pekka", "persona": "developer"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["applied"], [{"card": cid, "verdict": "trial", "trigger": "model_release"}])
        self.assertEqual(p.meta["trial"]["approved_by"], "Pekka")                # applied in the same request
        self.assertEqual([r["event"]["payload"]["card"] for r in p.ledger().of_kind("update_applied")], [cid])
        self.assertNotIn("project", out)

    def test_FR_T1_AC_15_a_refusal_is_a_403_or_a_400_never_a_500_and_autonomy_capped_is_a_403(self):
        from kernel.autonomy import AutonomyCapped
        from kernel.canon import DecisionRefused
        from kernel.embeds import EmbedRefused

        p = self.built_project()
        write_json(p.path("releases", "1.json"), {"release": 1, "maturity": "demo", "state": "done", "steps": []})
        url = f"/api/projects/{p.pid}/pack/build"
        who = {"person": "Kaisa", "persona": "compliance"}
        refusals = [(AutonomyCapped(4, 3, "delivering to staging"), 403, "needs autonomy level 4"),
                    (EmbedRefused("this website is not allowed to use the embed"), 403, "not allowed"),
                    (PermissionError("re-authoring a holdout needs a person's ruling and a reason"), 403, "ruling"),
                    (DecisionRefused("a stakeholder may not decide"), 403, "may not decide"),
                    (ValueError("the level is one of [1, 2, 3, 4]"), 400, "the level")]
        for exc, code, words in refusals:
            with mock.patch.object(cockpit.kpacks, "build_pack", side_effect=exc):
                status, body, _ = self.call("POST", url, who)
            self.assertEqual(status, code, (type(exc).__name__, body))
            self.assertIn(words, body["error"])
        with mock.patch.object(cockpit.kpacks, "build_pack", side_effect=RuntimeError("a bug")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.call("POST", url, who)[0], 500)        # a bug stays a 500, never a verdict


class ScreensTest(RedesignTestCase):
    """The square, the catalogue, the Inbox across projects and Settings, as the routes behind them say."""

    def signal(self, text, persona="stakeholder", person="Sanna"):
        status, out, _ = self.call("POST", "/api/signals", {"text": text, "channel": "monitoring", "source": "probe",
                                                            "person": person, "persona": persona})
        self.assertEqual(status, 201, out)
        return out["signal"]

    def concept(self, text="Warehouse staff need a way to report damaged pallets from a phone"):
        sid = self.signal(text)["id"]
        out = self.call("POST", f"/api/signals/{sid}/triage", {"person": "Sanna", "persona": "stakeholder"})[1]
        self.assertEqual(out["signal"]["state"], "concept", out)
        return out["signal"]["routed_to"]["card"]

    def writes(self, kind):
        return [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind(kind)]

    def test_FR_I3_AC_1_a_signal_keeps_its_signers_persona_and_the_change_it_routes_is_triaged_at_once(self):
        p = self.new()
        s = self.signal(f"{p.pid}: the TLS certificate must be rotated on the firewall before Friday", persona="it",
                        person="Ilkka")
        self.assertEqual(s["persona"], "it")
        self.assertEqual(self.call("GET", "/api/signals")[1]["signals"][0]["persona"], "it")
        status, out, _ = self.call("POST", f"/api/signals/{s['id']}/triage", {"person": "Ilkka", "persona": "it"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["signal"]["state"], "routed")
        cid = out["signal"]["routed_to"]["card"]
        card = Canon(p).get_card(cid)
        self.assertEqual(card["payload"]["source"], "it")                    # IT's need, not a stakeholder's
        self.assertEqual(card["payload"]["triage"]["class"], "infra_change")  # triaged when it was routed
        self.assertEqual(out["triage"]["class"], "infra_change")
        view = next(c for c in self.call("GET", f"/api/projects/{p.pid}")[1]["changes"] if c["id"] == cid)
        self.assertIsNotNone(view["payload"]["triage"])
        needs = self.call("GET", "/api/square")[1]["people"]["needs"]
        self.assertEqual(needs, [{"name": "Ilkka", "persona": "it"}])             # the corner says who raised it

    def test_FR_T1_AC_15_the_square_lists_every_new_signal_and_lists_the_rest_on_request(self):
        from kernel.store import updating_json

        for i in range(58):
            self.signal(f"Need number {i}: a better label printout for pallets")
        with updating_json(factory_project(self.factory).path("signals.json"), []) as items:
            for s in items[3:]:
                s["state"] = "parked"                 # only S-001 to S-003 are still new, and they are the oldest
        before = self.ledgers()
        sq = self.call("GET", "/api/square")[1]
        listed = [s["id"] for s in sq["signals_list"]]
        self.assertEqual(sq["signals"], {"new": 3, "total": 58})
        self.assertEqual(len(listed), cockpit.SQUARE_SIGNALS + 3)
        self.assertEqual(listed[0], "S-058")                                    # newest first
        self.assertTrue({"S-001", "S-002", "S-003"} <= set(listed))            # a new signal can always be triaged
        self.assertFalse(sq["signals_all"])
        every = self.call("GET", "/api/square?signals=all")[1]
        self.assertEqual((len(every["signals_list"]), every["signals_all"]), (58, True))
        self.assert_no_ledger_writes(before)

    def test_FR_T1_AC_15_a_concept_edit_records_only_what_changed_and_its_title_reaches_every_decision_view(self):
        cid = self.concept()
        edit = f"/api/concepts/{cid}/edit"
        card = Canon(factory_project(self.factory)).get_card(cid)
        same = {k: card["payload"][k] for k in ("profile", "maturity", "mode")}
        status, out, _ = self.call("POST", edit, dict(same, title="Damaged pallet reports", person="Aino",
                                                      persona="business_owner"))
        self.assertEqual((status, out["changed"]), (200, ["title"]), out)
        self.assertEqual([w["fields"] for w in self.writes("concept_edited")], [["title"]])
        self.assertEqual([w["fields"] for w in self.writes("cockpit_write") if w["action"] == "edit_concept"], [["title"]])
        # nothing changed: nothing is written or recorded; another persona is still refused
        status, out, _ = self.call("POST", edit, dict(same, title="Damaged pallet reports", person="Aino",
                                                      persona="business_owner"))
        self.assertEqual((status, out["changed"]), (200, []))
        self.assertEqual(len(self.writes("concept_edited")), 1)
        self.assertEqual(self.call("POST", edit, dict(same, person="Dev", persona="developer"))[0], 403)
        title = cockpit.CONCEPT_PREFIX + "Damaged pallet reports"
        inbox = self.call("GET", "/api/inbox?persona=business_owner")[1]["cards"]
        self.assertEqual([c["title"] for c in inbox if c["id"] == cid], [title])
        decisions = self.call("GET", "/api/dashboard")[1]["decisions"]
        self.assertEqual([d["title"] for d in decisions if d["card"] == cid], [title])
        self.assertEqual([c["card_title"] for c in self.call("GET", "/api/square")[1]["concepts"]], [title])
        # validated, the project knows who asked for it (its need), though project.json does not say
        out = self.call("POST", f"/api/projects/{FACTORY_PID}/cards/{cid}/decide",
                        {"verdict": "validate", "reason": "worth a demo", "person": "Aino", "persona": "business_owner"})[1]
        meta = self.call("GET", f"/api/projects/{out['project']}")[1]["meta"]
        self.assertEqual((meta["title"], meta["requested_by"]), ("Damaged pallet reports", "Aino"))
        self.assertEqual(self.runner.started, [])                  # validating starts no job: Advance runs the intake

    def test_FR_T1_AC_15_no_feedback_embed_on_rihma_itself_and_a_second_revoke_records_nothing(self):
        p = self.new()
        body = {"kind": "feedback", "origins": ["http://localhost:5501"], "person": "Ilkka", "persona": "it"}
        status, out, _ = self.call("POST", "/api/embeds", dict(body, project=FACTORY_PID))
        self.assertEqual(status, 400, out)
        self.assertIn("Rihma itself", out["error"])
        self.assertEqual(self.call("GET", "/api/embeds")[1]["embeds"], [])
        eid = self.call("POST", "/api/embeds", dict(body, project=p.pid))[1]["embed"]["id"]
        revoke = f"/api/embeds/{eid}/revoke"
        self.assertEqual(self.call("POST", revoke, {"person": "Ilkka", "persona": "it"})[0], 200)
        self.assertEqual(self.call("POST", revoke, {"person": "Sanna", "persona": "stakeholder"})[0], 403)
        status, out, _ = self.call("POST", revoke, {"person": "Ilkka", "persona": "it"})
        self.assertEqual(status, 409, out)
        self.assertEqual(len(self.writes("embed_revoked")), 1)
        self.assertEqual(len([w for w in self.writes("cockpit_write") if w["action"] == "revoke_embed"]), 1)

    def test_FR_T1_AC_14_a_proposed_agent_is_a_capability_pack_and_a_release_without_a_pack_is_named(self):
        cid = self.concept("We need an assistant agent that drafts replies to supplier emails for the buyers")
        p = self.new()
        write_json(p.path("releases", "1.json"), {"release": 1, "maturity": "demo", "state": "done", "steps": []})
        before = self.ledgers()
        items = self.call("GET", "/api/catalogue")[1]["items"]
        proposed = next(i for i in items if i.get("card") == cid)
        self.assertEqual((proposed["profile"], proposed["deliverable"]), ("agentic_workflow", "capability_pack"))
        built = next(i for i in items if i["project"] == p.pid)
        self.assertEqual((built["pack"], built["releases"], built["latest_release"]), (None, 1, 1))
        dash = self.call("GET", "/api/dashboard")[1]["catalogue"]["items"]
        self.assertEqual(next(i for i in dash if i.get("card") == cid)["deliverable"], "capability_pack")
        self.assert_no_ledger_writes(before)                      # a read builds no pack and records nothing
        self.assertFalse(p.path("packs.json").exists())

    def test_FR_T1_AC_11_no_read_route_creates_the_factory_canon(self):
        p = self.new()
        for path in ("/api/dashboard", "/api/catalogue", "/api/square", "/api/inbox?persona=business_owner",
                     "/api/embeds", "/api/autonomy", f"/api/projects/{p.pid}", "/api/projects"):
            self.assertEqual(self.call("GET", path)[0], 200, path)
            self.assertFalse((self.factory.projects_dir / FACTORY_PID).exists(), path)   # reading never creates it

    def test_FR_K4_AC_1_a_run_the_autonomy_cap_stopped_shows_as_capped_with_the_kernels_reason(self):
        p = self.new()
        why = "delivering to preview needs autonomy level 3 (prepare); the cap is 2 (suggest)"
        outcomes = ({"state": "capped", "stage": 5, "why": why, "history": ["spec", "compile"]},
                    {"state": "waiting", "stage": 2, "why": "blocking questions are open", "waiting_on": ["C-0001"]})
        for result in outcomes:
            job = self.call("POST", f"/api/projects/{p.pid}/advance", {"person": "Dev", "persona": "developer"})[1]["job"]
            _, _, log = next(s for s in self.runner.started if s[0] == job["id"])
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("starting\n" + json.dumps(result, indent=2) + "\n", encoding="utf-8")
            self.runner.states[job["id"]] = "done"
        jobs = {j["id"]: j for j in self.call("GET", "/api/jobs")[1]}
        capped, waiting = (jobs[s[0]] for s in self.runner.started)
        self.assertEqual((capped["state"], capped["outcome"]["state"], capped["outcome"]["why"]), ("capped", "capped", why))
        self.assertEqual((waiting["state"], waiting["outcome"]["state"]), ("done", "waiting"))

    def test_FR_T1_AC_11_the_decisions_widget_lists_every_open_change_the_inbox_lists(self):
        p = self.new()
        s = self.signal(f"{p.pid}: the TLS certificate was rotated on the webhook endpoint", persona="it", person="Ilkka")
        infra = self.call("POST", f"/api/signals/{s['id']}/triage", {"person": "Ilkka", "persona": "it"})[1]
        cid = infra["signal"]["routed_to"]["card"]
        self.assertEqual((infra["triage"]["class"], infra["triage"]["needs_decision"]), ("infra_change", False))
        status, report, _ = self.call("POST", f"/api/projects/{p.pid}/changes",
                                      {"text": "The order page should also show the parcel weight", "person": "Eetu",
                                       "persona": "end_user"})
        self.assertEqual(status, 201, report)
        self.concept()
        before = self.ledgers()
        d = self.call("GET", "/api/dashboard")[1]
        item = next(i for i in d["decisions"] if (i["project"], i["card"]) == (p.pid, cid))
        self.assertEqual((item["kind"], item["payload"]["class"], item["payload"]["needs_decision"]),
                         ("change", "infra_change", False))        # listed though no business decision gates it
        self.assertEqual(d["kpis"]["decisions"]["value"], len(d["decisions"]))
        for persona in ("product_owner", "business_owner"):
            inbox = self.call("GET", f"/api/inbox?persona={persona}")[1]
            mine = {(i["project"], i["card"]) for i in d["decisions"] if persona in i["deciders"]}
            self.assertEqual(mine, {(c["project"], c["id"]) for c in inbox["cards"]}, persona)   # the same cards
        self.assert_no_ledger_writes(before)

    def test_FR_T1_AC_15_the_end_user_corner_counts_every_open_report_as_waiting(self):
        p = self.new()
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/changes",
                                   {"text": "[R-1-AC-1] The stock system should also get the parcel weight.",
                                    "person": "Eetu", "persona": "end_user"})
        self.assertEqual(status, 201, out)                       # filed in the cockpit: triaged at once
        self.assertEqual(cockpit.ksignals.square(self.factory)["end_user_feedback_waiting"], 0)   # the kernel: not triaged
        sq = self.call("GET", "/api/square")[1]
        counts = ("end_user_feedback_waiting", "end_user_feedback_open", "end_user_feedback_untriaged")
        self.assertEqual(tuple(sq[k] for k in counts), (1, 1, 0))
        self.assertEqual([(f["state"], f["triaged"]) for f in sq["feedback"]], [("open", True)])
        dash = self.call("GET", "/api/dashboard")[1]["square"]
        self.assertEqual((dash["end_user_feedback_waiting"], dash["end_user_feedback_untriaged"]), (1, 0))
        Canon(p).decide(out["card"]["id"], "defer", person="Aino", persona="business_owner", reason="next release")
        self.assertEqual(self.call("GET", "/api/square")[1]["end_user_feedback_waiting"], 0)   # decided: no longer waits

    def test_FR_T1_AC_15_a_signal_triaged_beyond_the_newest_stays_listed_when_the_page_names_it(self):
        from kernel.store import updating_json

        for i in range(60):
            self.signal(f"Need number {i}: a better label printout for pallets")
        with updating_json(factory_project(self.factory).path("signals.json"), []) as items:
            for s in items[8:]:
                s["state"] = "parked"                 # S-001 to S-008 stay new, beyond the newest 50
        status, out, _ = self.call("POST", "/api/signals/S-003/triage", {"person": "Sanna", "persona": "stakeholder"})
        self.assertEqual((status, out["signal"]["state"]), (200, "concept"), out)
        before = self.ledgers()
        plain = self.call("GET", "/api/square")[1]
        self.assertNotIn("S-003", [s["id"] for s in plain["signals_list"]])       # no longer new nor among the newest
        self.assertEqual(plain["signals_shown"], [])
        named = self.call("GET", "/api/square?show=S-003,S-004,../x,S-1234567890,S-055")[1]
        listed = [s["id"] for s in named["signals_list"]]
        self.assertIn("S-003", listed)
        self.assertEqual(named["signals_shown"], ["S-003"])        # S-004 is new, S-055 among the newest anyway
        self.assertEqual(next(s for s in named["signals_list"] if s["id"] == "S-003")["routed_to"]["card"],
                         out["signal"]["routed_to"]["card"])
        self.assertEqual(len(listed), len(plain["signals_list"]) + 1)
        self.assertFalse(named["signals_all"])
        self.assert_no_ledger_writes(before)

    def test_FR_T1_AC_1_a_concept_is_parked_or_rejected_only_with_the_reason_and_a_refusal_records_nothing(self):
        fp = factory_project(self.factory)
        for verdict in ("park", "reject"):
            cid = self.concept(f"Need to {verdict}: a shared calendar for the loading bays")
            url = f"/api/projects/{FACTORY_PID}/cards/{cid}/decide"
            before = self.ledgers()
            for reason in (None, "", "   "):
                body = {"verdict": verdict, "person": "Aino", "persona": "business_owner"}
                if reason is not None:
                    body["reason"] = reason
                status, out, _ = self.call("POST", url, body)
                self.assertEqual(status, 400, out)
                self.assertIn(f"Say why you {verdict} {cid}", out["error"])
            self.assertEqual(Canon(fp).get_card(cid)["state"], "open")
            self.assert_no_ledger_writes(before)                     # nothing is recorded without the reason
            status, out, _ = self.call("POST", url, {"verdict": verdict, "reason": "the bays have one already",
                                                     "person": "Aino", "persona": "business_owner"})
            self.assertEqual((status, out["decision"]["reason"]), (200, "the bays have one already"), out)
        # validating needs no reason, as before
        cid = self.concept("Need to validate: a phone form for damaged pallets")
        status, out, _ = self.call("POST", f"/api/projects/{FACTORY_PID}/cards/{cid}/decide",
                                   {"verdict": "validate", "person": "Aino", "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        self.assertIn("project", out)


class PackReadTest(RedesignTestCase):
    """FR-T1-AC-16: reading a capability pack never writes; building one is an explicit, signed POST."""

    RELEASE = {"release": 1, "maturity": "demo", "state": "done", "revision": "abc123", "steps": []}

    def assert_read_only(self, base, before):
        for _ in range(2):
            status, out, _ = self.call("GET", base + "/pack")
            self.assertEqual(status, 200, out)
        self.assertEqual(self.call("GET", base + "/attestation")[0], 200)
        self.assert_no_ledger_writes(before)
        return out

    def test_FR_T1_AC_16_reading_a_pack_never_builds_one_and_building_is_a_signed_post(self):
        p = self.built_project()
        base, build = f"/api/projects/{p.pid}", f"/api/projects/{p.pid}/pack/build"
        write_json(p.path("releases", "1.json"), self.RELEASE)
        before = self.ledgers()
        out = self.assert_read_only(base, before)
        self.assertEqual((out["pack"], out["yaml"], out["current"], out["latest_release"]), (None, None, False, 1))
        self.assertIn("no capability pack yet", out["note"])
        self.assertIn("compliance", out["builders"])
        self.assertFalse(p.path("packs.json").exists())                      # no version recorded
        self.assertFalse(p.path("releases", "1", "capability-pack.json").exists())
        self.assertFalse((self.factory.projects_dir / FACTORY_PID).exists())  # nor the factory's canon made
        # refused: a persona that does not export evidence, a non-person, a foreign origin, a GET
        for body in ({"person": "Sanna", "persona": "stakeholder"}, {"person": "assistant", "persona": "compliance"},
                     {"person": "Kaisa", "persona": "nobody"}):
            self.assertEqual(self.call("POST", build, body)[0], 403, body)
        self.assertEqual(self.call("POST", build, {"person": "Kaisa", "persona": "compliance"},
                                   origin="http://evil.example")[0], 403)
        self.assertEqual(self.call("GET", build)[0], 405)
        self.assert_no_ledger_writes(before)
        self.assertFalse(p.path("packs.json").exists())
        status, out, _ = self.call("POST", build, {"person": "Kaisa", "persona": "compliance"})
        self.assertEqual(status, 200, out)
        self.assertEqual((out["pack"]["version"], out["pack"]["release"], out["current"]), ("1.0.0", 1, True))
        self.assertEqual([r["event"]["payload"]["version"] for r in p.ledger().of_kind("pack_versioned")], ["1.0.0"])
        writes = [r["event"]["payload"] for r in p.ledger().of_kind("cockpit_write")
                  if r["event"]["payload"]["action"] == "build_pack"]
        self.assertEqual([(w["person"], w["persona"], w["version"]) for w in writes], [("Kaisa", "compliance", "1.0.0")])
        # the written pack is what a read shows, and the read still records nothing
        out = self.assert_read_only(base, self.ledgers())
        self.assertEqual((out["pack"]["version"], out["current"], out["note"]), ("1.0.0", True, None))
        self.assertIn("rihma.capability-pack.v1", out["yaml"])
        self.assertEqual([h["version"] for h in out["history"]], ["1.0.0"])
        # the same content keeps its version; a newer release leaves the written pack not current
        self.assertEqual(self.call("POST", build, {"person": "Pekka", "persona": "product_owner"})[1]["pack"]["version"],
                         "1.0.0")
        self.assertEqual(len(p.read("packs.json")), 1)
        write_json(p.path("releases", "2.json"), dict(self.RELEASE, release=2))
        out = self.assert_read_only(base, self.ledgers())
        self.assertEqual((out["latest_release"], out["current"]), (2, False))
        self.assertIn((out["pack"] or {}).get("release"), (1, None))          # the older pack, or none
        self.assertFalse(p.path("releases", "2", "capability-pack.json").exists())

    def test_FR_T1_AC_16_the_read_uses_the_kernels_latest_pack_when_it_has_one_and_never_build_pack(self):
        p = self.built_project()
        write_json(p.path("releases", "1.json"), self.RELEASE)
        written = {"format": "rihma.capability-pack.v1", "version": "1.0.0", "release": 1, "acceptance": {}}
        with mock.patch.object(cockpit.kpacks, "build_pack", side_effect=AssertionError("a read built a pack")), \
                mock.patch.object(cockpit.kpacks, "latest_pack", create=True, return_value=written) as latest:
            status, out, _ = self.call("GET", f"/api/projects/{p.pid}/pack")
            self.assertEqual(status, 200, out)
            self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/attestation")[0], 200)
            self.assertEqual(self.call("GET", "/api/dashboard")[0], 200)
        self.assertEqual((out["pack"], out["current"]), (written, True))
        self.assertTrue(latest.called)
        self.assertEqual(self.call("GET", f"/api/projects/{self.new(title='No release').pid}/pack")[0], 404)

    def test_FR_T1_AC_16_the_releases_view_shows_the_written_pack_and_offers_build_only_as_its_own_action(self):
        js = self.page_js()
        self.assertIn('api("GET", base + "/pack")', js)
        self.assertIn('"/pack/build", signed())', js)
        self.assertIn('"data-control": "build_pack"', js)
        ui = self.call("GET", "/api/ui-map")[1]
        self.assertIn("build_pack", [c["id"] for c in ui["controls"]])
        self.assertEqual(self.call("GET", "/api/meta")[1]["pack_builders"], list(cockpit.PACK_BUILDERS))


class EmbedBaseTest(RedesignTestCase):
    """FR-I1-AC-4: an embed's snippet points at the embed server, never at the cockpit."""

    BODY = {"kind": "need", "origins": ["https://intranet.example"], "label": "Ideas", "brief": "Tell us a need",
            "person": "Pekka", "persona": "it"}

    def signed_in(self, server, bootstrap):
        """A call function for a second cockpit, signed in with its bootstrap."""
        def call(method, path, body=None):
            headers = {"Origin": server.origin, "Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            data = None if body is None else json.dumps(body).encode("utf-8")
            req = urllib.request.Request(server.origin + path, data=data, headers=headers, method=method)
            try:
                with _DIRECT.open(req, timeout=10) as res:
                    return res.status, json.loads(res.read() or b"null")
            except urllib.error.HTTPError as exc:
                with exc:
                    return exc.code, json.loads(exc.read() or b"null")
        token = None
        token = call("POST", "/auth", {"bootstrap": bootstrap})[1]["token"]
        return call

    def test_FR_I1_AC_4_with_an_embed_base_the_snippet_names_the_embed_server_and_never_the_cockpit(self):
        server, bootstrap = self.start_server(embed_base="https://Feedback.Example/")
        self.assertEqual(server.embed_base, "https://feedback.example")
        call = self.signed_in(server, bootstrap)
        status, out = call("POST", "/api/embeds", self.BODY)
        self.assertEqual(status, 201, out)
        snip = out["snippet"]
        self.assertIn(f'src="https://feedback.example/e/{out["embed"]["id"]}/widget.js"', snip)
        self.assertIn('data-endpoint="https://feedback.example"', snip)
        self.assertIn(out["key"], snip)
        for never in (server.origin, "127.0.0.1", "<!--"):
            self.assertNotIn(never, snip)
        self.assertEqual(out["embed_base"], "https://feedback.example")
        self.assertEqual(call("GET", "/api/embeds")[1]["embed_base"], "https://feedback.example")
        self.assertEqual(call("GET", "/api/meta")[1]["embed_base"], "https://feedback.example")
        # the cockpit serves no widget and no chat turn: a website only ever reaches the embed server
        for path in (f"/e/{out['embed']['id']}/widget.js", f"/e/{out['embed']['id']}/messages"):
            self.assertEqual(call("GET", path)[0], 404, path)
            self.assertEqual(call("POST", path, {"key": out["key"], "history": []})[0], 404, path)

    def test_FR_I1_AC_4_without_one_the_snippet_says_to_set_it_and_shows_the_local_embed_server(self):
        self.assertEqual(self.call("GET", "/api/embeds")[1]["embeds"], [])
        self.assertFalse((self.factory.projects_dir / FACTORY_PID).exists())  # a read never makes the canon
        meta = self.call("GET", "/api/meta")[1]
        self.assertEqual((meta["embed_base"], meta["embed_base_local"]), (None, "http://127.0.0.1:8790"))
        status, out, _ = self.call("POST", "/api/embeds", self.BODY)
        self.assertEqual(status, 201, out)
        snip = out["snippet"]
        self.assertIn(f'src="http://127.0.0.1:8790/e/{out["embed"]["id"]}/widget.js"', snip)
        self.assertIn('data-endpoint="http://127.0.0.1:8790"', snip)
        for words in ("No embed server address is set", "for testing only", "--embed-base", "RIHMA_EMBED_BASE"):
            self.assertIn(words, snip)
        self.assertNotIn(self.server.origin + "/e/", snip)
        self.assertIsNone(out["embed_base"])
        js = self.page_js()
        self.assertIn("No embed server address is set. ", js)                 # Settings and the key box say so

    def test_FR_I1_AC_4_a_bad_embed_base_or_one_naming_the_cockpit_is_refused_and_the_env_is_read(self):
        import socket

        for bad in ("http://evil.example", "javascript:alert(1)", "https://a.example/?x=1", "https://u@a.example",
                    'https://a.example/"x', "https://a.example:99999"):
            with self.assertRaises(ValueError, msg=bad):
                make_server(self.factory, 0, runner=FakeRunner(), embed_base=bad)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with self.assertRaises(ValueError) as caught:
            make_server(self.factory, port, runner=FakeRunner(), embed_base=f"http://127.0.0.1:{port}")
        self.assertIn("embed server", str(caught.exception))
        env = {"RIHMA_EMBED_BASE": "https://chat.example/"}
        self.assertEqual(cockpit.configured_embed_base(None, env), "https://chat.example")
        self.assertEqual(cockpit.configured_embed_base("https://flag.example", env), "https://flag.example")
        self.assertIsNone(cockpit.configured_embed_base(None, {}))
        with self.assertRaises(ValueError):
            cockpit.configured_embed_base(None, {"RIHMA_EMBED_BASE": "http://evil.example"})
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch.object(cockpit, "make_server") as made:
            code = cockpit.main(["--home", str(self.tmp / "home"), "--embed-base", "http://evil.example"])
        self.assertEqual(code, 2)
        self.assertIn("refused", err.getvalue())
        made.assert_not_called()
        self.assertIn("local embed server", cockpit.embed_base_note(None))
        self.assertIn("https://chat.example", cockpit.embed_base_note("https://chat.example"))


class AssistantRouteTest(RedesignTestCase):
    def test_FR_V1_AC_5_where_is_is_answered_from_the_cockpit_map_without_a_model(self):
        p = self.built_project()
        before = self.ledgers()
        status, out, _ = self.call("POST", "/api/assistant", {"question": "Where can I approve the plan?",
                                                              "persona": "product_owner", "project": p.pid,
                                                              "view": "overview", "person": "Pekka"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["by"], "map")
        self.assertEqual(out["navigate"]["route"], f"#/p/{p.pid}/plan")
        out = self.call("POST", "/api/assistant", {"question": "how do I pause this?", "persona": "developer",
                                                   "project": p.pid})[1]
        self.assertEqual(out["navigate"]["control"], "pause")
        for body, code in (({"question": "  ", "persona": "developer"}, 400), ({"question": "x", "persona": "bot"}, 400),
                           ({"question": "x", "persona": "developer", "project": "no-such-project"}, 404)):
            self.assertEqual(self.call("POST", "/api/assistant", body)[0], code, body)
        self.assertEqual(self.call("POST", "/api/assistant", {"question": "x", "persona": "developer"}, origin=None)[0], 403)
        self.assert_no_ledger_writes(before)

    def test_FR_V1_AC_5_an_injected_models_proposals_come_back_checked_and_the_route_writes_nothing(self):
        from kernel.model import FakeModel

        p = self.built_project()
        build_task(p, "T-002", lanes=Lanes(self.tmp / "lanes2", size=1), cell_runner=lazy_cell,
                   verifier_runner=no_findings, max_rounds=1)
        esc = next(c for c in Canon(p).cards() if c["kind"] == "escalation")["id"]
        answer = {"answer": "Made the gate trend bigger as a table, and the theme compact teal.",
                  "navigate": {"route": f"#/p/{p.pid}/tasks", "control": None},
                  "propose": [
                      {"action": "layout_edit", "args": {"ops": [{"op": "resize", "widget": "gate_trend", "size": "XL"},
                                                                 {"op": "set_view", "widget": "gate_trend", "view": "table"}]},
                       "why": "you asked"},
                      {"action": "theme", "args": {"settings": {"density": "compact", "accent": "teal"}}, "why": "asked"},
                      {"action": "decide", "args": {"card": esc, "verdict": "retry", "reason": "once more"}, "why": "w"},
                      {"action": "layout_edit", "args": {"ops": [{"op": "add", "widget": "rm_rf_widget"}]}},
                      {"action": "theme", "args": {"settings": {"css": "body{display:none}"}}},
                      {"action": "decide", "args": {"card": esc, "verdict": "approve"}}],
                  "sources": ["T-002", esc, "R-77"]}
        fake = FakeModel(lambda prompt, role: "```json\n" + json.dumps(answer) + "\n```")
        server, bootstrap = self.start_server(assistant_model=fake)
        token = None
        req = urllib.request.Request(server.origin + "/auth", data=json.dumps({"bootstrap": bootstrap}).encode(),
                                     headers={"Content-Type": "application/json", "Origin": server.origin},
                                     method="POST")
        with _DIRECT.open(req, timeout=10) as res:
            token = json.loads(res.read())["token"]
        mine = {"v": 1, "lens": "delivery", "widgets": [{"id": "my-gate", "type": "gate_trend", "size": "M"}]}
        put = urllib.request.Request(server.origin + "/api/layout?persona=developer&lens=delivery",
                                     data=json.dumps({"person": "Dev", "layout": mine}).encode(), method="PUT",
                                     headers={"Content-Type": "application/json", "Origin": server.origin,
                                              "Authorization": "Bearer " + token})
        with _DIRECT.open(put, timeout=10) as res:
            self.assertEqual(res.status, 200)
        before = self.ledgers()
        layout_file = next((self.factory.home / "_cockpit" / "layouts").rglob("*.json")).read_bytes()
        ask = urllib.request.Request(server.origin + "/api/assistant", method="POST", data=json.dumps({
            "question": "Make the gate trend bigger and show it as a table, compact teal", "persona": "developer",
            "project": p.pid, "view": "tasks", "person": "Dev", "lens": "delivery"}).encode(),
            headers={"Content-Type": "application/json", "Origin": server.origin, "Authorization": "Bearer " + token})
        with _DIRECT.open(ask, timeout=20) as res:
            out = json.loads(res.read())
        self.assertEqual(out["by"], "assistant")
        self.assertEqual([x["action"] for x in out["propose"]], ["layout_edit", "theme", "decide"])
        self.assertEqual(len(out["dropped"]), 3)
        self.assertTrue(all(x["refused"] for x in out["dropped"]))
        self.assertEqual(out["unbacked_sources"], ["R-77"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{p.pid}/tasks")
        role, prompt = fake.calls[0]
        self.assertEqual(role, "assistant")
        self.assertIn("my-gate", prompt)                                       # it saw the person's layout
        for widget in cockpit.WIDGETS:
            self.assertIn(widget, prompt)                                      # and the widget library
        self.assert_no_ledger_writes(before)                               # it wrote nothing
        self.assertEqual(next((self.factory.home / "_cockpit" / "layouts").rglob("*.json")).read_bytes(), layout_file)

    def test_FR_V1_AC_5_every_view_in_the_ui_map_is_routable_and_every_control_is_on_the_page(self):
        import re

        status, ui, _ = self.call("GET", "/api/ui-map")
        self.assertEqual(status, 200)
        js = self.page_js()
        index = self.call("GET", "/", token=None, raw=True)[1].decode("utf-8")
        table = re.search(r"PAGE_ROUTES = (\{.*?\});", js, re.S)
        self.assertIsNotNone(table, "the page's route table")
        routes = json.loads(table.group(1))
        for view in ui["views"]:
            self.assertEqual(routes.get(view["id"]), view["route"], view["id"])
        for control in ui["controls"]:
            cid = re.escape(control["id"])
            pattern = rf"""data-control(="|"\s*:\s*"){cid}\""""
            self.assertTrue(re.search(pattern, index) or re.search(pattern, js), control["id"])


if __name__ == "__main__":
    unittest.main()
