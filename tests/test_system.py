"""The system's features, together, in scripted scenarios (FR-O8-AC-4).

Each test is a story told by named test personas. The models and the builder cells are scripted
fakes (no Gnomon, no network), but everything else is real: the products are compiled, built in
lanes, judged by the gate and delivered as local processes on loopback, as in tests/test_deliver.py.

- s1: a vague idea becomes an accepted demo, with its capability pack and its evidence pack;
- s2: the demo's end users give feedback through an embed over HTTP; a defect goes round the change
  loop, the earlier acceptance goes stale, and the pack's version moves;
- s3: the delivery square turns two signals into a change and a validated pilot that waits for its plan;
- s4: autonomy and governance: a cap refuses a build, an observation opens an update card, and an MCP
  client proposes but cannot decide;
- s5: an ops-agent request gets its own profile;
- s6: a model that fails in the middle of a ruling stops the run cleanly, and running again resumes;
- s7: no holdout scenario reaches any surface a client sees.

Scenarios 1, 2 and 7 share one factory, in that order: the accepted demo of s1 is where the end users
of s2 give feedback, and s7 scans what both left behind.

What the scenarios found is kept at the end of the file as regression tests, each named after the
criterion it breaks. One finding was a design question (a delivered demo listed as 'building'); FR-Q7
settles it, and s1 now checks that the accepted demo is 'trying'.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import PANEL, no_findings  # noqa: E402
from test_deliver import LOCAL_ROADS  # noqa: E402

from embed.server import make_server  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.intake import LOOK_QUESTION, intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.model import FakeModel, ModelError  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.store import REPO_ROOT, Factory, FixedClock, write_json  # noqa: E402

# -- the people -------------------------------------------------------------------------------------

OWNER = "test-business-owner"
PRODUCT_OWNER = "test-product-owner"
DEVELOPER = "test-developer"
COMPLIANCE = "test-compliance"
IT = "test-it"
MEMBER = "test-member"

IDEA = "Our makerspace keeps losing track of who borrowed which tools."
SITE = "https://tools.example"
DEFECT = "When I add a tool with an empty name the page crashes with a 500 error."
VAGUE = "Something is off with the tools list."
CLARIFIED = "I added a drill and expected to see the newest tool first, but it was at the bottom."

# What the holdout author writes for the tool library. The values are unique to the custody, so a
# leak anywhere is visible.
HELD_NAME = "hx-held-tool-5521"
SLOPPY_NAME = "hx-sloppy-hammer-8840"

# -- the product's spec, as the analyst drafts it ----------------------------------------------------

STORY_SPEC = {
    "title": "Tool library", "summary": "Members add the makerspace's tools and see which tools there are.",
    "users": ["makerspace members"],
    "interface": [{"method": "POST", "path": "/items", "purpose": "add a tool"},
                  {"method": "GET", "path": "/items", "purpose": "list the tools"},
                  {"method": "GET", "path": "/health", "purpose": "the health check"}],
    "requirements": [
        {"statement": "A member can add a tool with a name.", "sources": ["request"], "priority": "must",
         "acceptance": [{"given": "no tools", "when": "POST /items with a name", "then": "201 and the tool has an id",
                         "kind": "test"},
                        {"given": "a tool", "when": "GET /items", "then": "the tool is listed", "kind": "holdout"}]},
        {"statement": "The service answers its health check quickly.", "sources": ["proposed"], "priority": "should",
         "acceptance": [{"given": "-", "when": "GET /health", "then": "200 with status ok", "kind": "test"},
                        {"given": "-", "when": "GET /health", "then": "answers in under 500 ms", "kind": "probe"}]},
    ],
    "out_of_scope": ["billing"],
}
PALLET_SPEC = {
    "title": "Damaged pallet reports", "summary": "Warehouse staff report damaged pallets to the ERP.",
    "users": ["warehouse staff"],
    "interface": [{"method": "POST", "path": "/reports", "purpose": "report a damaged pallet"},
                  {"method": "GET", "path": "/reports", "purpose": "list the reports"}],
    "requirements": [
        {"statement": "A worker reports a damaged pallet by its id.", "sources": ["request"], "priority": "must",
         "acceptance": [{"given": "-", "when": "POST /reports with a pallet id", "then": "201 with the report",
                         "kind": "test"},
                        {"given": "a report", "when": "GET /reports", "then": "the report is listed",
                         "kind": "holdout"}]},
    ],
}
REPORT_SPEC = {
    "title": "HR log compliance report", "summary": "A GDPR and AI Act check of the HR system's logs, as a report.",
    "users": ["the compliance owner"],
    "interface": [{"method": "GET", "path": "/report", "purpose": "the report"}],
    "requirements": [
        {"statement": "Each finding cites the log line it rests on.", "sources": ["request"], "priority": "must",
         "acceptance": [{"given": "a seeded finding", "when": "GET /report", "then": "the finding cites its line",
                         "kind": "test"}]},
        {"statement": "What was not checked is reported as not measured.", "sources": ["proposed"],
         "priority": "must",
         "acceptance": [{"given": "-", "when": "GET /report", "then": "unchecked controls say not measured",
                         "kind": "test"}]},
    ],
}


def _fenced(obj) -> str:
    return "```json\n" + json.dumps(obj) + "\n```"


def _between(prompt: str, start: str, end: str) -> str:
    i = prompt.find(start)
    j = prompt.find(end, i + len(start)) if i >= 0 else -1
    return prompt[i + len(start):j] if i >= 0 and j >= 0 else ""


def _scenario(criterion: str, kind: str, *, sloppy: bool) -> dict:
    if criterion == "R-1-AC-2" and sloppy:   # it assumes a tool it never added (the first live run's mistake)
        return {"criterion": criterion, "steps": [{"method": "GET", "path": "/items", "expect_status": 200,
                                                   "expect_contains": SLOPPY_NAME}]}
    if criterion == "R-1-AC-2":
        return {"criterion": criterion, "steps": [
            {"method": "POST", "path": "/items", "body": {"name": HELD_NAME}, "expect_status": 201},
            {"method": "GET", "path": "/items", "expect_status": 200, "expect_contains": HELD_NAME}]}
    return {"criterion": criterion, "steps": [{"method": "GET", "path": "/health", "expect_status": 200,
                                               "max_ms": 500}]}


def story_model(*, sloppy: bool = False, down: str | None = None) -> FakeModel:
    """The scripted models: the panel, the analyst, the holdout author, the embed's chat and the
    triage. ``sloppy`` makes the holdout author's first scenario wrong; ``down`` names a prompt at
    which the endpoint fails, as an apparatus failure does."""

    def answer(prompt: str, role: str) -> str:
        if down and down in prompt:
            raise ModelError(f"gnomon apparatus failure for role {role}: endpoint_error")
        if "perspective on a panel" in prompt:
            for p, qs in PANEL.items():
                if f"You are the **{p}** perspective" in prompt:
                    return _fenced({"reading": f"{p} reading", "questions": qs})
        if "A panel of perspectives" in prompt:
            return _fenced({"opinions": [
                {"question": "Q-001", "perspective": "it_security", "opinion": "approval must be logged for audit"}]})
        if "You turn a brief into a software specification" in prompt:
            if "pallet" in prompt:
                return _fenced(PALLET_SPEC)
            if "GDPR" in prompt:
                return _fenced(REPORT_SPEC)
            return _fenced(STORY_SPEC)
        if "You write acceptance scenarios" in prompt:
            wanted = re.findall(r"^- (R-\d+-AC-\d+) \((holdout|probe)\):", prompt, re.MULTILINE)
            rewriting = "rewriting them" in prompt
            return _fenced({"scenarios": [_scenario(c, k, sloppy=sloppy and not rewriting) for c, k in wanted]})
        if "You are a short, friendly intake assistant" in prompt:
            convo = _between(prompt, "The conversation so far:\n", "\n\nAnswer with this JSON")
            if "crash" in convo:
                return _fenced({"reply": "Thank you. The team will look at the crash.", "ready": True,
                                "summary": "Adding a tool with an empty name crashes the page with a 500 error."})
            if "assistant:" in convo:
                return _fenced({"reply": "Thank you, that helps. It has been passed on.", "ready": True,
                                "summary": "The tools list should show the newest tool first."})
            return _fenced({"reply": "What did you try, and what did you expect to see?", "ready": False})
        if "Classify a piece of feedback" in prompt:
            said = _between(prompt, "<<<\n", "\n>>>")
            if "crash" in said:
                return _fenced({"parts": [{"class": "defect", "requirements": ["R-1"], "text": said,
                                           "summary": "an empty name crashes POST /items",
                                           "regression": {"given": "-", "when": "POST /items with an empty name",
                                                          "then": "400 with an error, not a 500"}}]})
            return _fenced({"parts": [{"class": "change_request", "requirements": ["R-1"], "text": said,
                                       "summary": "list the newest tool first"}]})
        if "A business need arrived at a solution factory" in prompt:
            need = _between(prompt, "<<<\n", "\n>>>").lower()
            listed = dict((t.lower(), p) for p, t in re.findall(r"^- (\S+): (.+)$", prompt, re.MULTILINE))
            if "tool library" in need and "tool library" in listed:
                return _fenced({"title": "Overdue tools first", "problem": "overdue tools are hard to find",
                                "who": "makerspace members", "value": "tools come back sooner",
                                "existing_project": listed["tool library"]})
            return _fenced({"title": "Damaged pallet reports", "problem": "damaged pallets are reported on paper",
                            "who": "warehouse staff", "value": "fewer write-offs", "existing_project": None})
        raise AssertionError(f"unscripted prompt for role {role}: {prompt[:120]}")

    return FakeModel(answer)


# -- the builder cells -------------------------------------------------------------------------------

ITEMS_ROUTES = '''

@route("POST", "/items")
def add_item(req):
    body = req.body if isinstance(req.body, dict) else {}
    name = str(body.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    items = load_data("items", [])
    item = {"id": str(len(items) + 1), "name": name}
    items.append(item)
    save_data("items", items)
    return 201, item


@route("GET", "/items")
def list_items(req):
    return 200, load_data("items", [])
'''
CRASH = '        raise ValueError("name is required")'
REPAIR = '        return 400, {"error": "name is required"}'


class Cells:
    """Scripted builder cells. Every visible criterion in the envelope gets a route and a test that
    fails before the route exists; R-1's cell adds the tools API (without guarding against an empty
    name, which no criterion asked for), and a criterion about an empty name gets the real repair.
    ``lazy`` names tasks whose first rounds cut a corner: a test that cannot fail."""

    def __init__(self, lazy: dict | None = None):
        self.lazy = dict(lazy or {})
        self.prompts: list = []

    def __call__(self, lane_path, prompt):
        self.prompts.append(prompt)
        task = re.search(r"^# Envelope (T-\d+)", prompt, re.MULTILINE).group(1)
        criteria = dict(re.findall(r"^- \*\*(R-\d+-AC-\d+)\*\*: (.*)$", prompt, re.MULTILINE))
        test_file = Path(lane_path, "tests", f"test_{task.lower().replace('-', '_')}.py")
        lines = ["import unittest", "", "import app.routes  # noqa: F401", "from app.server import handle", "", "",
                 "class CriteriaTest(unittest.TestCase):"]
        if self.lazy.get(task, 0) > 0:
            self.lazy[task] -= 1
            for cid in sorted(criteria):
                lines += [f"    def test_{cid.replace('-', '_')}_always_true(self):",
                          "        self.assertTrue(True)", ""]
            test_file.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 2, "model": "fake-builder",
                    "output": "done"}
        routes = Path(lane_path, "app", "routes.py")
        text = routes.read_text(encoding="utf-8")
        if any(cid.startswith("R-1-") for cid in criteria) and '"/items"' not in text:
            text += ITEMS_ROUTES
        for cid, line in sorted(criteria.items()):
            tok = cid.replace("-", "_")
            if "empty name" in line:
                text = text.replace(CRASH, REPAIR)
                lines += [f"    def test_{tok}_an_empty_name_is_refused(self):",
                          '        status, body, _ = handle("POST", "/items", {"name": ""})',
                          "        self.assertEqual(status, 400)", ""]
                continue
            if f"/criteria/{cid}" not in text:
                text += (f'\n\n@route("GET", "/criteria/{cid}")\ndef {tok.lower()}(req):\n'
                         f'    return 200, {{"criterion": "{cid}"}}\n')
            lines += [f"    def test_{tok}_is_met(self):",
                      f'        status, body, _ = handle("GET", "/criteria/{cid}")',
                      "        self.assertEqual(status, 200)", ""]
        routes.write_text(text, encoding="utf-8", newline="\n")
        test_file.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 6, "model": "fake-builder",
                "output": "done"}


# -- helpers ----------------------------------------------------------------------------------------

def kinds(project) -> list:
    return [r["event"]["kind"] for r in project.ledger().records()]


def held_strings(project) -> list:
    """What the holdout custody holds that no client may see: every step body, and every string in it."""
    out = set()
    for path in sorted(project.holdouts_dir.glob("*.json")):
        for step in json.loads(path.read_text(encoding="utf-8")).get("steps", []):
            body = step.get("body")
            if body is None:
                continue
            out.add(json.dumps(body))
            stack = [body]
            while stack:
                v = stack.pop()
                if isinstance(v, dict):
                    stack += list(v.values())
                elif isinstance(v, list):
                    stack += v
                elif isinstance(v, str) and len(v) >= 4:
                    out.add(v)
    return sorted(out)


def zip_text(path) -> str:
    with zipfile.ZipFile(path) as z:
        return "\n".join(f"== {n}\n" + z.read(n).decode("utf-8") for n in sorted(z.namelist()))


def client_surfaces(test, factory, project, tmp) -> dict:
    """Everything a client sees of the factory, by surface: an MCP client's every read (as a developer
    and as a business owner), the evidence pack, the capability pack, the dashboard read models and
    the assistant."""
    from kernel import dashboard
    from kernel.assistant import ask, snapshot
    from kernel.evidence_pack import export
    from kernel.packs import build_pack, render_yaml
    from kernel.projections import floor
    from kernel.signals import square
    from mcp.server import RihmaMCP, handle_line

    pid, surfaces = project.pid, {}
    for persona, person in (("developer", DEVELOPER), ("business_owner", OWNER)):
        server = RihmaMCP(factory, person=person, persona=persona, lanes_root=tmp / "no-lanes")
        msgs = [{"method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                    "clientInfo": {"name": "t", "version": "0"}}},
                {"method": "tools/list"}, {"method": "resources/list"}]
        for name, args in (("rihma_projects", {}), ("rihma_project", {"pid": pid}), ("rihma_waiting", {}),
                           ("rihma_floor", {}), ("rihma_timeline", {"pid": pid}), ("rihma_evidence", {"pid": pid}),
                           ("rihma_square", {}), ("rihma_ask", {"question": "where are the holdouts?", "pid": pid})):
            msgs.append({"method": "tools/call", "params": {"name": name, "arguments": args}})
        for what in ("spec", "contract", "ledger"):
            msgs.append({"method": "resources/read", "params": {"uri": f"rihma://projects/{pid}/{what}"}})
        msgs.append({"method": "resources/read", "params": {"uri": "rihma://cockpit/map"}})
        out = [handle_line(server, json.dumps({"jsonrpc": "2.0", "id": i, **msg}).encode("utf-8"))
               for i, msg in enumerate(msgs, 1)]
        for line in out:
            answer = json.loads(line)
            test.assertIn("result", answer, answer)                                   # every read is answered
            test.assertFalse(answer["result"].get("isError"), answer)
        surfaces[f"MCP outputs as {persona}"] = b"".join(out).decode("utf-8")
    surfaces["evidence pack"] = zip_text(export(project, tmp / "scan", person=COMPLIANCE, persona="compliance"))
    pack = build_pack(project)
    surfaces["capability pack"] = "\n".join(
        [json.dumps(pack), render_yaml(pack)]
        + [x.read_text(encoding="utf-8") for x in sorted(project.path("releases").glob("*/capability-pack.json"))])
    surfaces["dashboard read models"] = json.dumps({
        "pipeline": dashboard.pipeline(factory), "queue": dashboard.queue(factory),
        "gate_trend": dashboard.gate_trend(factory), "timeline": dashboard.timeline(project),
        "activity": dashboard.activity(factory), "coverage": dashboard.coverage(factory),
        "catalogue": dashboard.catalogue(factory), "square": square(factory), "floor": floor(factory)}, default=str)
    surfaces["assistant"] = json.dumps({
        "factory": snapshot(factory), "project": snapshot(factory, project=project),
        "ask": ask(factory, "where do I see the holdout results?", persona="developer", project_id=pid)}, default=str)
    return surfaces


class EmbedClient:
    """A website's chat talking to the embed server over real HTTP on 127.0.0.1."""

    def __init__(self, factory, model, clock):
        from kernel.embeds import RateLimit

        self.srv = make_server(factory, 0, model=model, rate=RateLimit(clock))
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.raw: list = []

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def post(self, embed_id: str, key: str, history: list, origin: str = SITE) -> tuple:
        data = json.dumps({"key": key, "history": history}).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/e/{embed_id}/messages", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                status, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read()
            e.close()
        self.raw.append(body)
        return status, json.loads(body)


class SystemCase(unittest.TestCase):
    """A fresh factory with a fixed clock, every product process stopped afterwards."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-system-"))
        self.addCleanup(roadmod.rmtree, self.tmp)
        self.addCleanup(roadmod.stop_started)
        self.clock = FixedClock()
        self.factory = Factory(self.tmp / "home", clock=self.clock)
        self.lanes = Lanes(self.tmp / "lanes", size=1)

    def run_until_a_person(self, project, model, cells, **kw) -> dict:
        self.addCleanup(roadmod.stop_all, project, LOCAL_ROADS)
        return advance(project, model=model, lanes=self.lanes, cell_runner=cells, verifier_runner=no_findings,
                       deliver_kwargs={}, **kw)


# -- s1, s2 and s7: one product from a vague idea to its second pack version --------------------------

class IdeaToReleaseStory(unittest.TestCase):
    """The tool library: s1 makes it an accepted demo, s2 takes its end users' feedback round the change
    loop, and s7 scans what a client can see. Each stage runs once, in order, whichever test asks first."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-story-"))
        cls.clock = FixedClock()
        cls.factory = Factory(cls.tmp / "home", clock=cls.clock)
        write_json(cls.factory.paved_roads_path, LOCAL_ROADS)     # IT configured a local road for every maturity
        cls.model = story_model()
        cls.cells = Cells(lazy={"T-002": 3})                     # T-002's cell cuts a corner for three rounds
        cls.lanes = Lanes(cls.tmp / "lanes", size=1)
        cls.project = None
        cls.done, cls.broken = set(), None
        cls.embed_raw: list = []
        cls.facts: dict = {}

    @classmethod
    def tearDownClass(cls):
        if cls.project is not None:
            roadmod.stop_all(cls.project, LOCAL_ROADS)
        roadmod.stop_started()
        roadmod.rmtree(cls.tmp)

    def stage(self, n: int, fn) -> None:
        cls = type(self)
        if n in cls.done:
            return
        if cls.broken is not None:
            self.fail(f"the story broke at scenario {cls.broken}; this one builds on it")
        try:
            fn()
        except BaseException:
            cls.broken = n
            raise
        cls.done.add(n)

    def advance(self) -> dict:
        return advance(self.project, model=self.model, lanes=self.lanes, cell_runner=self.cells,
                       verifier_runner=no_findings, deliver_kwargs={})

    def main_rev(self) -> str:
        return _git(self.project.path("repo.git"), "rev-parse", "main")

    def demo(self, method: str, path: str, body=None) -> dict:
        state = roadmod.slot_state(self.project, "demo", "current")
        return roadmod.http_request(method, state["base_url"] + path, body)

    # -- s1 ----------------------------------------------------------------------------------------

    def scenario_1(self) -> None:
        from kernel.compile import contract_check
        from kernel.dashboard import queue
        from kernel.deliver import latest_release
        from kernel.evidence_pack import export
        from kernel.packs import build_pack
        from kernel.status import health, now

        cls, m = type(self), self.model
        p = cls.project = self.factory.new_project("Tool library", mode="assume", maturity="demo")
        canon = Canon(p)

        # Stages 1-2. The panel reads two sentences; in assume mode the factory answers every question
        # itself, each as an assumption with a due date, and asks nobody.
        out = intake(p, IDEA, model=m, requested_by=OWNER)
        self.assertEqual(p.meta["profile"], "web_service")
        self.assertEqual(out["asked"], [])
        self.assertEqual(canon.questions("open"), [])
        self.assertEqual({q["status"] for q in canon.questions()}, {"assumed"})
        self.assertIn(LOOK_QUESTION, [q["text"] for q in canon.questions()])        # a web service has screens
        self.assertTrue(canon.assumptions() and all(a["due"] for a in canon.assumptions()))
        self.assertIn("[assumed]", canon.brief)

        # Stages 3-5. Spec, contract, holdouts and the build, until a person is needed: T-002's cell
        # wrote a test that cannot fail, the gate refused it three times, and it escalates.
        first = self.advance()
        self.assertEqual((first["state"], first["stage"]), ("waiting", 5), first)
        self.assertEqual(first["history"], ["spec", "compile", {"build": {"T-001": "merged", "T-002": "escalated"}}])
        spec = p.read("spec.json")
        self.assertEqual((spec["requirements"][0]["provenance"], spec["requirements"][0]["decided_by"]),
                         ("customer-endorsed", OWNER))
        self.assertEqual(spec["requirements"][1]["provenance"], "vendor-proposed")
        report, _ = contract_check().check(p.read("contract.json"))
        self.assertEqual(report.violations, [])
        self.assertEqual(sorted(x.stem for x in p.holdouts_dir.glob("*.json")), ["R-1-AC-2", "R-2-AC-2"])
        self.assertFalse(p.holdouts_dir.resolve().is_relative_to(p.dir.resolve()))   # a separate custody
        self.assertTrue(self.cells.prompts)
        for prompt in self.cells.prompts:
            self.assertNotIn(HELD_NAME, prompt)                                        # the builder never saw one
        esc = canon.get_card(first["waiting_on"][0])
        self.assertEqual((esc["kind"], esc["refs"]["task"]), ("escalation", "T-002"))
        self.assertTrue(any(o.startswith("fail_first") for o in esc["payload"]["objections"]), esc)
        gates = [g["event"]["payload"] for g in p.ledger().of_kind("gate")]
        self.assertEqual([(g["task"], g["verdict"]) for g in gates],
                         [("T-001", "passed")] + [("T-002", "failed")] * 3)          # two repairs, then a person
        self.clock.advance(hours=2)                                                  # it waits for a person
        self.assertEqual(now(p)["state"], "waiting_on_you")
        self.assertEqual([(i["card"], i["age_hours"], "developer" in i["deciders"])
                          for i in queue(self.factory)["items"]],
                         [(esc["id"], 2.0, True)])

        # A person retries. IT may not; the developer does, with a reason.
        with self.assertRaises(DecisionRefused):
            canon.decide(esc["id"], "retry", person=IT, persona="it")
        canon.decide(esc["id"], "retry", person=DEVELOPER, persona="developer",
                     reason="the test checked nothing; build it again")
        second = self.advance()
        self.assertEqual(second["state"], "waiting", second)
        self.assertIn("escalations resolved", second["history"])
        self.assertEqual({t: s["status"] for t, s in p.read("tasks.json").items()},
                         {"T-001": "merged", "T-002": "merged"})
        self.assertTrue(p.meta["built"])

        # Stage 6. The demo runs, its holdouts passed against it, and the business owner is asked.
        acceptance = canon.get_card(second["waiting_on"][0])
        self.assertEqual((acceptance["kind"], acceptance["refs"]["release"]), ("approval", 1))
        self.assertEqual(acceptance["payload"]["environment"], "demo")
        self.assertEqual((acceptance["payload"]["holdouts"]["verdict"], acceptance["payload"]["holdouts"]["passed"]),
                         ("passed", 2))
        rel = latest_release(p)
        self.assertEqual((rel["state"], rel["holdouts"]["environment"]), ("waiting", "demo"))
        self.assertEqual(self.demo("GET", "/health")["json"]["version"], self.main_rev()[:12])
        self.assertEqual(self.demo("POST", "/items", {"name": "drill"})["status"], 201)   # an owner tries it
        self.clock.advance(hours=3)
        self.assertEqual([(i["card"], i["age_hours"]) for i in queue(self.factory)["items"]], [(acceptance["id"], 3.0)])
        with self.assertRaises(DecisionRefused):
            canon.decide(acceptance["id"], "approve", person=IT, persona="it")
        canon.decide(acceptance["id"], "approve", person=OWNER, persona="business_owner",
                     reason="it does what we asked")
        third = self.advance()
        self.assertEqual((third["state"], third["env"], third["release"]), ("done", "demo", 1), third)
        rel = latest_release(p)
        accepted = next(s for s in rel["steps"] if s["step"] == "owner_acceptance")
        self.assertEqual((accepted["outcome"], accepted["native"]["person"]), ("passed", OWNER))
        self.assertEqual(now(p), {"state": "done", "line": "Release 1 is live (demo).", "since": self.clock.stamp()})
        self.assertEqual(health(p)["status"], "on_track", health(p)["reasons"])
        self.assertEqual(queue(self.factory)["count"], 0)

        # The capability pack: version 1.0.0, pinned by hash, valid because every criterion holds.
        pack = build_pack(p)
        self.assertEqual((pack["version"], pack["release"], pack["deliverable"]), ("1.0.0", 1, "product"))
        self.assertEqual(pack["pinned"]["product_revision"], self.main_rev())
        self.assertEqual(pack["pinned"]["contract_revision"], p.read("contract.json")["revision"])
        self.assertTrue(pack["acceptance"]["valid"], pack["acceptance"]["not_valid_because"])
        self.assertEqual(pack["acceptance"]["holdout_scores"]["passed"], 2)
        self.assertIn("fake-builder", json.dumps(pack["pinned"]["built_and_judged_by"]))
        self.assertIsNone(pack["provenance"]["signature"])

        # The evidence pack, for test-compliance: intact, and attestable (never "compliant").
        zipped = export(p, self.tmp / "evidence", person=COMPLIANCE, persona="compliance")
        with zipfile.ZipFile(zipped) as z:
            att = json.loads(z.read("attestation.json"))
            decisions = json.loads(z.read("decisions.json"))
            self.assertTrue(json.loads(z.read("ledger-check.json"))["intact"])
        self.assertEqual(att["verdict"], "attestable")
        self.assertEqual([(d["person"], d["verdict"]) for d in decisions], [(DEVELOPER, "retry"), (OWNER, "approve")])
        self.assertIn("evidence_exported", kinds(p))
        self.assertTrue(p.ledger().verify().intact)
        cls.facts.update(acceptance=acceptance["id"], pack=pack)

    # -- s2 ----------------------------------------------------------------------------------------

    def scenario_2(self) -> None:
        from kernel.change import apply_change, triage
        from kernel.deliver import latest_release
        from kernel.embeds import create
        from kernel.packs import build_pack
        from kernel.signals import square
        from kernel.status import health

        cls, p, m = type(self), self.project, self.model
        canon = Canon(p)
        self.clock.advance(days=5)                                                   # the demo is in use

        # The product owner puts a feedback chat on the demo's page. A developer may not.
        with self.assertRaises(DecisionRefused):
            create(self.factory, kind="feedback", origins=[SITE], person=DEVELOPER, persona="developer",
                   project_id=p.pid)
        e = create(self.factory, kind="feedback", origins=[SITE], person=PRODUCT_OWNER, persona="product_owner",
                   project_id=p.pid, label="Tool library page", brief="Members list the makerspace's tools.")
        cls.facts["embed"] = e
        chat = EmbedClient(self.factory, m, self.clock)
        try:
            # One end user hits the crash and says so clearly: it is filed at once.
            status, defect = chat.post(e["id"], e["key"], [{"role": "person", "text": DEFECT}])
            self.assertEqual(status, 200, defect)
            self.assertEqual(defect["filed"]["kind"], "change")
            # Another is vague: the chat asks back first, and nothing is filed until they answer.
            before = len(canon.cards(state=None, kind="change"))
            status, asked = chat.post(e["id"], e["key"], [{"role": "person", "text": VAGUE}])
            self.assertEqual((status, asked["filed"]), (200, None))
            self.assertTrue(asked["reply"].endswith("?"), asked)
            self.assertEqual(len(canon.cards(state=None, kind="change")), before)
            status, clear = chat.post(e["id"], e["key"], [{"role": "person", "text": VAGUE},
                                                          {"role": "assistant", "text": asked["reply"]},
                                                          {"role": "person", "text": CLARIFIED}])
            self.assertEqual((status, clear["filed"]["kind"]), (200, "change"))
            # A website that is not allowed gets nothing.
            status, refused = chat.post(e["id"], e["key"], [{"role": "person", "text": DEFECT}],
                                        origin="https://elsewhere.example")
            self.assertEqual(status, 403, refused)
        finally:
            chat.close()
            cls.embed_raw += chat.raw
        for role, prompt in m.calls:
            if role == "assistant":                                                  # the chat never sees the canon
                self.assertNotIn("R-1", prompt)
                self.assertNotIn(HELD_NAME, prompt)

        # The cards came from end users and were triaged by the rules as they were filed, so nothing waits
        # untriaged in the square; the analyst's triage then refines them.
        self.assertEqual(square(self.factory)["end_user_feedback_waiting"], 0)
        crash_card = canon.get_card(defect["filed"]["ref"])
        newest_card = canon.get_card(clear["filed"]["ref"])
        self.assertEqual({crash_card["payload"]["source"], newest_card["payload"]["source"]}, {"end_user"})
        self.assertTrue(crash_card["payload"].get("triage") and newest_card["payload"].get("triage"))
        tri = triage(p, crash_card["id"], model=m)
        self.assertEqual((tri["class"], tri["way_back"], tri["requirements"], tri["needs_decision"]),
                         ("defect", 5, ["R-1"], False))
        tri2 = triage(p, newest_card["id"], model=m)
        self.assertEqual((tri2["class"], tri2["needs_decision"]), ("change_request", True))
        self.assertEqual(square(self.factory)["end_user_feedback_waiting"], 0)
        canon.decide(newest_card["id"], "defer", person=OWNER, persona="business_owner",
                     reason="after the crash is fixed")
        with self.assertRaises(PermissionError):                                     # deferred is not accepted
            apply_change(p, newest_card["id"], model=m)

        # The crash is real on the running demo. The defect goes back to the build with its lesson.
        self.assertEqual(self.demo("POST", "/items", {"name": ""})["status"], 500)
        contract_before = p.read("contract.json")["revision"]
        applied = apply_change(p, crash_card["id"], model=m)
        self.assertEqual((applied["class"], applied["changed"]), ("defect", ["R-1"]))
        lesson = p.read("lessons.json")[-1]
        self.assertEqual((lesson["card"], lesson["regression_criterion"]), (crash_card["id"], "R-1-AC-3"))
        self.assertNotEqual(p.read("contract.json")["revision"], contract_before)
        self.assertEqual(canon.get_card(crash_card["id"])["state"], "resolved")
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "pending")
        # The owner's acceptance of release 1 rested on R-1: it is stale now.
        stale = [d for d in canon.decisions() if d["card"] == cls.facts["acceptance"]]
        self.assertEqual([d["stale"] for d in stale], [True])
        self.assertIn(stale[0]["id"], applied["stale"])

        # The factory rebuilds R-1 and delivers release 2; the owner is asked again.
        out = self.advance()
        self.assertEqual(out["state"], "waiting", out)
        self.assertIn({"build": {"T-001": "merged"}}, out["history"])
        self.assertTrue(any("R-1-AC-3" in prompt for prompt in self.cells.prompts))   # the envelope named it
        again = canon.get_card(out["waiting_on"][0])
        self.assertEqual((again["kind"], again["refs"]["release"]), ("approval", 2))
        canon.decide(again["id"], "approve", person=OWNER, persona="business_owner", reason="the crash is gone")
        done = self.advance()
        self.assertEqual((done["state"], done["release"]), ("done", 2), done)
        self.assertEqual(latest_release(p)["revision"], self.main_rev())
        self.assertEqual(self.demo("POST", "/items", {"name": ""})["status"], 400)   # fixed where users see it

        # Pack version = behaviour version: the new release has a new version.
        pack = build_pack(p)
        self.assertEqual((pack["version"], pack["release"]), ("1.1.0", 2))
        self.assertNotEqual(pack["pinned"]["product_revision"], cls.facts["pack"]["pinned"]["product_revision"])
        self.assertTrue(pack["acceptance"]["valid"], pack["acceptance"]["not_valid_because"])
        self.assertEqual([h["version"] for h in p.read("packs.json")], ["1.0.0", "1.1.0"])
        # The approval that went stale was given again for the new release: the project is on track.
        self.assertEqual(health(p)["status"], "on_track", health(p)["reasons"])

    # -- the tests ---------------------------------------------------------------------------------

    def test_FR_O8_AC_4_s1_a_vague_idea_becomes_an_accepted_demo_with_its_packs(self):
        self.stage(1, self.scenario_1)

    def test_FR_O8_AC_4_s1_the_business_finds_the_accepted_demo_in_the_catalogue(self):
        from kernel.dashboard import catalogue
        from kernel.signals import square

        self.stage(1, self.scenario_1)
        item = next(i for i in catalogue(self.factory)["items"] if i["project"] == self.project.pid)
        self.assertEqual((item["profile"], item["deliverable"], item["maturity"]), ("web_service", "product", "demo"))
        self.assertEqual(item["pack"], {"version": "1.0.0", "valid": True})
        # Found by s1, fixed by FR-Q7: the stage and the catalogue follow what was delivered. The accepted
        # demo is at stage 6 (user validation) and listed as 'trying'; it is not in production.
        self.assertEqual((item["state"], item["stage"]), ("trying", 6))
        self.assertEqual(square(self.factory)["in_production"], 0)

    def test_FR_O8_AC_4_s2_end_user_feedback_through_an_embed_becomes_a_new_pack_version(self):
        self.stage(1, self.scenario_1)
        self.stage(2, self.scenario_2)

    def test_FR_O8_AC_4_s7_no_holdout_scenario_reaches_any_surface_a_client_sees(self):
        self.stage(1, self.scenario_1)
        self.stage(2, self.scenario_2)
        f, p = self.factory, self.project
        held = held_strings(p)
        self.assertIn(HELD_NAME, held)                                               # the scan looks for something
        self.assertIn(json.dumps({"name": HELD_NAME}), held)

        # The embed: every reply the website got in s2, and one more conversation now.
        e = self.facts["embed"]
        chat = EmbedClient(f, self.model, self.clock)
        try:
            status, _ = chat.post(e["id"], e["key"], [{"role": "person", "text": "Which tools are on the list?"},
                                                      {"role": "assistant", "text": "Which page were you on?"},
                                                      {"role": "person", "text": "The list page, after the update."}])
            self.assertEqual(status, 200)
        finally:
            chat.close()
        surfaces = {"embed replies": b"\n".join(self.embed_raw + chat.raw).decode("utf-8"),
                    **client_surfaces(self, f, p, self.tmp)}
        self.assertEqual(len(surfaces), 7)          # MCP twice, the embed, both packs, the dashboard, the assistant
        for name, text in surfaces.items():
            self.assertTrue(text.strip(), name)
            for h in held:
                self.assertNotIn(h, text, f"the {name} carry a holdout scenario's step body")


# -- s3: the delivery square ----------------------------------------------------------------------

class DeliverySquareStory(SystemCase):
    def test_FR_O8_AC_4_s3_two_signals_become_a_change_and_a_validated_pilot_that_waits_for_its_plan(self):
        from kernel.dashboard import catalogue
        from kernel.learn import factory_project
        from kernel.signals import apply_concepts, edit_concept, receive, signals, square, triage

        f, m = self.factory, story_model()
        tools = f.new_project("Tool library", mode="assume", maturity="demo")
        intake(tools, IDEA, model=m, requested_by=OWNER)

        # Two needs arrive: one from a member in the makerspace chat, one from a service desk feed.
        s1 = receive(f, "The tool library should list overdue tools first; members keep asking.", channel="chat",
                     source="#makerspace", person=MEMBER, persona="end_user")
        s2 = receive(f, "Warehouse staff need a way to report damaged pallets from their phones.", channel="feed",
                     source="service desk export")
        self.assertEqual(square(f)["signals"], {"new": 2, "total": 2})

        # The first is about the tool library: it becomes a change there, raised by the member.
        out = triage(f, s1["id"], model=m)
        self.assertEqual((out["state"], out["routed_to"]["project"]), ("routed", tools.pid))
        change = Canon(tools).get_card(out["routed_to"]["card"])
        self.assertEqual((change["kind"], change["payload"]["person"]), ("change", MEMBER))
        self.assertIn(f"[signal {s1['id']} via chat]", change["payload"]["text"])
        self.assertEqual(change["payload"]["source"], "end_user", "the change keeps the persona the signal carried")
        self.assertEqual(square(f)["end_user_feedback_waiting"], 1)                  # it waits for triage as such

        # The second is new: a concept that only a business or product owner may shape or decide.
        out = triage(f, s2["id"], model=m)
        self.assertEqual(out["state"], "concept")
        fcanon = Canon(factory_project(f))
        concept = fcanon.get_card(out["routed_to"]["card"])
        self.assertEqual((concept["kind"], concept["payload"]["title"]), ("concept", "Damaged pallet reports"))
        self.assertEqual(concept["payload"]["raised_by"], "feed signal from service desk export")
        self.assertIn("proposed", {i["state"] for i in catalogue(f)["items"]})
        with self.assertRaises(DecisionRefused):
            edit_concept(f, concept["id"], person=DEVELOPER, persona="developer", maturity="pilot")
        with self.assertRaises(DecisionRefused):
            fcanon.decide(concept["id"], "validate", person=DEVELOPER, persona="developer")
        edit_concept(f, concept["id"], person=OWNER, persona="business_owner", profile="integration", maturity="pilot")
        fcanon.decide(concept["id"], "validate", person=OWNER, persona="business_owner",
                      reason="the ERP team asked for this too")
        made = apply_concepts(f)
        self.assertEqual([x["verdict"] for x in made], ["validate"])
        self.assertEqual(apply_concepts(f), [])                                       # carried out once
        pallets = f.project(made[0]["project"])
        self.assertEqual((pallets.meta["profile"], pallets.meta["maturity"], pallets.meta["mode"]),
                         ("integration", "pilot", "mixed"))
        self.assertEqual(next(s for s in signals(f) if s["id"] == s2["id"])["state"], "validated")

        # advance starts intake from the need as it arrived; mixed mode puts the blocking question to a person.
        first = advance(pallets, model=m)
        self.assertEqual((first["state"], first["stage"]), ("waiting", 2), first)
        self.assertIn("intake from the validated need", first["history"])
        self.assertIn("damaged pallets", pallets.read("source.json")["text"])
        canon = Canon(pallets)
        texts = [q["text"] for q in canon.questions()]
        self.assertNotIn(LOOK_QUESTION, texts)                                        # an integration has no screens
        self.assertIn("What happens to a message that cannot be delivered?", texts)   # its own seed question
        blocking = canon.get_card(first["waiting_on"][0])
        canon.answer(blocking["refs"]["question"], "the shift lead approves", person=OWNER, persona="business_owner")

        # At pilot maturity nothing is compiled or built until a person approves the plan.
        second = advance(pallets, model=m)
        self.assertEqual((second["state"], second["stage"]), ("waiting", 4), second)
        plan = canon.get_card(second["waiting_on"][0])
        self.assertEqual((plan["kind"], plan["refs"]["scope"]), ("approval", "plan"))
        self.assertIn("A worker reports a damaged pallet by its id.", plan["body"])
        self.assertFalse(pallets.path("contract.json").exists())
        self.assertFalse(pallets.path("tasks.json").exists())
        self.assertEqual(advance(pallets, model=m)["waiting_on"], second["waiting_on"])   # one card, not two
        spec = pallets.read("spec.json")
        self.assertEqual((spec["requirements"][0]["provenance"], spec["requirements"][0]["decided_by"]),
                         ("customer-endorsed", OWNER))
        canon.decide(plan["id"], "approve", person=OWNER, persona="business_owner")
        third = advance(pallets, model=m, max_steps=1)                                # one step: the gate opens
        self.assertEqual(third["history"], ["compile"])
        self.assertTrue(pallets.path("contract.json").exists())
        self.assertEqual(pallets.meta["plan_approved"]["by"], OWNER)
        self.assertFalse(pallets.path("tasks.json").exists())


# -- s4: autonomy and governance --------------------------------------------------------------------

class GovernanceStory(SystemCase):
    def test_FR_O8_AC_4_s4_a_cap_refuses_a_build_an_update_is_decided_and_mcp_cannot_decide(self):
        from kernel.autonomy import cap_of, set_cap
        from kernel.learn import factory_project
        from kernel.observations import apply_updates, observe

        f, m, cells = self.factory, story_model(), Cells()
        p = f.new_project("Tool library", mode="assume", maturity="demo")
        intake(p, IDEA, model=m, requested_by=OWNER)

        # test-compliance caps the factory at 2 (suggest): the factory specifies, but builds nothing.
        with self.assertRaises(DecisionRefused):
            set_cap(f, 2, person=DEVELOPER, persona="developer", reason="quiet week")
        set_cap(f, 2, person=COMPLIANCE, persona="compliance", reason="audit week: proposals only")
        capped = self.run_until_a_person(p, m, cells)
        self.assertEqual(capped["state"], "capped", capped)
        self.assertIn("autonomy level 3", capped["why"])
        self.assertEqual(capped["history"], ["spec", "compile"])
        self.assertEqual(cells.prompts, [])                                           # no cell ran
        self.assertNotIn("cell_ran", kinds(p))
        self.assertFalse(p.meta.get("built"))

        # Raised to 4, the same project builds, and stops at the road IT has not configured yet.
        set_cap(f, 4, person=COMPLIANCE, persona="compliance", reason="audit done")
        self.assertEqual(cap_of(p), 4)
        out = self.run_until_a_person(p, m, cells)
        self.assertEqual(out["state"], "waiting", out)
        self.assertEqual({t: s["status"] for t, s in p.read("tasks.json").items()},
                         {"T-001": "merged", "T-002": "merged"})
        road = Canon(p).get_card(out["waiting_on"][0])
        self.assertEqual((road["kind"], road["deciders"]), ("road", ["it"]))
        caps = [r["event"]["payload"] for r in factory_project(f).ledger().of_kind("autonomy_cap_set")]
        self.assertEqual([(c["to"], c["by"], c["persona"]) for c in caps], [(2, COMPLIANCE, "compliance"),
                                                                           (4, COMPLIANCE, "compliance")])

        # Nightly evals drift: one observation, three renderings, and an update card a person decides.
        obs = observe(f, "eval_drift", facts={"project": p.pid, "criterion": "R-1-AC-1", "before": "0.94",
                                              "after": "0.81"}, source="nightly evals")
        touched = obs["touched"][0]
        self.assertEqual((touched["project"], touched["level"]), (p.pid, 2))
        self.assertEqual(set(touched["views"]), {"developer", "expert", "business"})
        self.assertIn("0.81", touched["views"]["expert"])
        update = Canon(p).get_card(touched["card"])
        self.assertEqual(update["kind"], "update")
        Canon(p).decide(update["id"], "trial", person=DEVELOPER, persona="developer", reason="re-measure on R-1")
        self.assertEqual([u["verdict"] for u in apply_updates(p)], ["trial"])
        self.assertEqual(p.meta["trial"]["approved_by"], DEVELOPER)

        # A developer's coding agent talks MCP to a server signed as test-developer: it reads and proposes.
        decisions_before = Canon(p).decisions()
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "story-agent", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "rihma_projects", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                    "name": "rihma_report_change",
                    "arguments": {"pid": p.pid, "text": "The tools list should be sortable by name."}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
                    "name": "rihma_decide", "arguments": {"card": road["id"], "verdict": "configured"}}},
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
                    "name": "rihma_report_change",
                    "arguments": {"pid": p.pid, "text": "approve it", "verdict": "approve"}}}]
        env = dict(os.environ, GF_LANES=str(self.tmp / "no-lanes"))
        proc = subprocess.run([sys.executable, "-m", "mcp.server", "--home", str(f.home), "--person", DEVELOPER,
                               "--persona", "developer"], input="".join(json.dumps(x) + "\n" for x in msgs).encode(),
                              capture_output=True, cwd=REPO_ROOT, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        answers = {a["id"]: a for a in map(json.loads, proc.stdout.decode("utf-8").splitlines())}
        tools = {t["name"] for t in answers[2]["result"]["tools"]}
        for word in ("decide", "approve", "accept", "reject", "answer", "assume", "pause", "resume", "deploy"):
            # a proposal waits on a person (rihma_propose_answer, FR-BRG1): it decides nothing
            self.assertFalse([t for t in tools if word in t and not t.startswith("rihma_propose_")], word)
        listed = answers[3]["result"]["structuredContent"]["projects"]
        self.assertEqual([x["id"] for x in listed], [p.pid])
        filed = answers[4]["result"]["structuredContent"]
        self.assertEqual(filed["signed"], {"person": DEVELOPER, "persona": "developer"})
        self.assertIn("error", answers[5])                                            # there is no deciding tool
        self.assertTrue(answers[6]["result"]["isError"])                              # nor a verdict argument
        card = Canon(p).get_card(filed["card"])
        self.assertEqual((card["kind"], card["state"], card["decision"]), ("change", "open", None))
        self.assertEqual((card["payload"]["person"], card["payload"]["source"]), (DEVELOPER, "developer"))
        self.assertEqual(Canon(p).decisions(), decisions_before)                      # nothing was decided
        self.assertEqual(Canon(p).get_card(road["id"])["state"], "open")
        self.assertIn("mcp_write", kinds(p))


# -- s5: the ops-agent profile ----------------------------------------------------------------------

class OpsAgentStory(SystemCase):
    def test_FR_O8_AC_4_s5_a_compliance_check_request_gets_the_ops_agent_profile(self):
        from kernel.dashboard import catalogue
        from kernel.profiles import PROFILES, profile_of

        m = story_model()
        p = self.factory.new_project("HR log check", mode="assume", maturity="demo")
        intake(p, "GDPR and AI Act check of the HR system's logs", model=m, requested_by=COMPLIANCE)
        self.assertEqual(p.meta["profile"], "ops_agent")
        chosen = next(r["event"]["payload"] for r in p.ledger().of_kind("profile_chosen"))
        self.assertEqual(chosen["basis"]["by"], "rule")
        self.assertIn("gdpr", chosen["basis"]["keywords"])
        texts = [q["text"] for q in Canon(p).questions()]
        for seed in PROFILES["ops_agent"]["seed_questions"]:
            self.assertIn(seed["text"], texts)                                        # its own questions, once
            self.assertEqual(texts.count(seed["text"]), 1)
        self.assertNotIn(LOOK_QUESTION, texts)                                        # a report has no screens
        self.assertEqual(profile_of(p)["deliverable"], "report")
        panel = [prompt for _, prompt in m.calls if "perspective on a panel" in prompt]
        self.assertTrue(panel and all("Ops agent: report with evidence" in x for x in panel))

        out = advance(p, model=m, max_steps=1)                                        # the spec, and no further
        self.assertEqual(out["history"], ["spec"])
        spec_prompts = [prompt for _, prompt in m.calls if "You turn a brief into a software specification" in prompt]
        self.assertEqual(len(spec_prompts), 1)
        self.assertIn(PROFILES["ops_agent"]["spec_guidance"], spec_prompts[0])
        self.assertEqual(p.read("spec.json")["title"], "HR log compliance report")
        item = next(i for i in catalogue(self.factory)["items"] if i["project"] == p.pid)
        self.assertEqual((item["profile"], item["deliverable"]), ("ops_agent", "report"))


# -- s6: an apparatus failure in the middle of a ruling ---------------------------------------------

class ApparatusRecoveryStory(SystemCase):
    def test_FR_O8_AC_4_s6_a_model_failing_while_a_holdout_is_rewritten_stops_cleanly_and_resumes(self):
        from kernel.deliver import releases
        from kernel.status import evidence, now

        write_json(self.factory.paved_roads_path, LOCAL_ROADS)
        f, cells = self.factory, Cells()
        p = f.new_project("Tool library", mode="assume", maturity="demo")
        intake(p, IDEA, model=story_model(), requested_by=OWNER)

        # The holdout author assumes a tool nobody added, so the demo's holdouts fail.
        first = self.run_until_a_person(p, story_model(sloppy=True), cells)
        self.assertEqual(first["state"], "waiting", first)
        ruling = Canon(p).get_card(first["waiting_on"][0])
        self.assertEqual((ruling["kind"], ruling["refs"]["criteria"]), ("holdout_ruling", ["R-1-AC-2"]))
        self.assertEqual((releases(p)[0]["state"], releases(p)[0]["failed_step"]), ("failed", "holdouts:demo"))
        states = {e["criterion"]: e["state"] for e in evidence(p)}
        self.assertEqual((states["R-1-AC-2"], states["R-2-AC-2"]), ("failing", "held_out"))   # the probe passed
        reason = "the scenario looked for a tool it never added"
        Canon(p).decide(ruling["id"], "scenario_defect", person=DEVELOPER, persona="developer", reason=reason)

        # The holdout author's endpoint fails while it rewrites the scenario: the run stops cleanly.
        down = story_model(down="You write acceptance scenarios")
        out = self.run_until_a_person(p, down, cells)
        self.assertEqual((out["state"], out["apparatus"]), ("apparatus_failure", True), out)
        self.assertIn("endpoint_error", out["why"])
        failure = p.ledger().of_kind("apparatus_failure")[-1]["event"]["payload"]
        self.assertEqual(failure["where"], "pipeline")
        self.assertTrue(any("You write acceptance scenarios" in prompt for _, prompt in down.calls))
        self.assertFalse(p.read("rulings_applied.json"))                              # the ruling is not spent
        self.assertIn(SLOPPY_NAME, (p.holdouts_dir / "R-1-AC-2.json").read_text(encoding="utf-8"))
        self.assertEqual(len(releases(p)), 1)                                          # nothing delivered
        self.assertFalse(p.meta.get("redeliver"))
        self.assertTrue(p.ledger().verify().intact)
        stopped = now(p)
        self.assertEqual(stopped["state"], "failed")
        self.assertIn("Release 1 stopped: holdout R-1-AC-2 failed at step 1", stopped["line"])
        # While the run is stopped, people look: test-compliance exports an evidence pack for the review,
        # the assistant sums the project up, a developer's agent reads it over MCP. What the failing
        # scenario expected stays with the release record and the ruling card, for the person who rules.
        for name, text in client_surfaces(self, f, p, self.tmp).items():
            self.assertNotIn(SLOPPY_NAME, text, f"the {name} carry the failing holdout scenario")

        # Running again with a working endpoint applies the ruling and delivers the same revision again.
        working = story_model()
        again = self.run_until_a_person(p, working, cells)
        self.assertEqual(again["state"], "waiting", again)
        self.assertIn({"rulings": ["scenario_defect"]}, again["history"])
        self.assertEqual(p.read("rulings_applied.json"), [ruling["id"]])
        rewritten = json.loads((p.holdouts_dir / "R-1-AC-2.json").read_text(encoding="utf-8"))
        self.assertNotIn(SLOPPY_NAME, json.dumps(rewritten))
        self.assertEqual(rewritten["author_role"], "holdout_author")
        authored = p.ledger().of_kind("holdouts_authored")[-1]["event"]["payload"]
        self.assertEqual((authored["ruled_by"], authored["criteria"]), (DEVELOPER, ["R-1-AC-2"]))
        held = authored["reauthored_because"]                                          # the reason is in custody:
        self.assertEqual((held["custody"], held["length"]), ("holdout", len(reason)))  # the ledger holds its hash
        self.assertNotIn(reason, json.dumps(p.ledger().records()))
        from kernel.rulings import held_reason

        self.assertEqual(held_reason(p, held["sha256"]), reason)
        rewrite = [x for _, x in working.calls if "You write acceptance scenarios" in x]
        self.assertTrue(rewrite and reason in rewrite[0])                             # the author heard the ruling
        rels = releases(p)
        self.assertEqual([r["release"] for r in rels], [1, 2])
        self.assertEqual(rels[0]["revision"], rels[1]["revision"])                    # the same revision, again
        self.assertEqual(rels[1]["holdouts"]["verdict"], "passed")
        self.assertEqual(Canon(p).get_card(again["waiting_on"][0])["kind"], "approval")
        self.assertEqual(len(cells.prompts), 2)                                       # nothing was rebuilt
        self.assertEqual(self.run_until_a_person(p, working, cells)["waiting_on"], again["waiting_on"])
        self.assertEqual(p.read("rulings_applied.json"), [ruling["id"]])              # applied once


# -- regression tests for what the scenarios found ---------------------------------------------------

class FoundInTheSquare(SystemCase):
    def test_FR_P1_AC_1_a_signal_routed_to_a_project_keeps_the_persona_that_raised_it(self):
        """Found by s3: a routed signal's change was always filed as a stakeholder's, so the persona the
        signal carried was lost, and an IT signal never reached IT's road."""
        from kernel.change import triage as triage_change
        from kernel.signals import receive, triage

        f = self.factory
        p = f.new_project("Tool library", mode="assume", maturity="demo")
        intake(p, IDEA, model=story_model(), requested_by=OWNER)
        s = receive(f, f"{p.pid} needs TLS on its staging address", channel="email", source="IT desk", person=IT,
                    persona="it")
        card = Canon(p).get_card(triage(f, s["id"])["routed_to"]["card"])
        self.assertEqual((card["payload"]["source"], card["payload"]["person"]), ("it", IT))
        self.assertEqual(triage_change(p, card["id"])["class"], "infra_change")        # IT's need goes to the road
        anonymous = receive(f, f"{p.pid}: the list answers slowly", channel="monitoring", source="probe dashboard")
        card = Canon(p).get_card(triage(f, anonymous["id"])["routed_to"]["card"])
        self.assertEqual((card["payload"]["source"], card["payload"]["person"]),
                         ("stakeholder", "monitoring signal from probe dashboard"))


class FoundInAlignment(SystemCase):
    def test_FR_S6_AC_1_a_stale_acceptance_is_given_again_by_accepting_the_release_that_replaced_it(self):
        """Found by s2: an approval of release 1 that a defect made stale counted as 'not given again' for
        ever, because only an approval with identical refs (the same release) gave it again, so the
        project stayed at risk after its owner accepted release 2."""
        from kernel.insight import alignment
        from kernel.status import health

        p = self.factory.new_project("Tool library", mode="assume", maturity="demo")
        canon = Canon(p)
        reqs = ["R-1", "R-2"]

        def stale_ones():
            return [x["decision"] for x in alignment(p) if x["kind"] == "stale_approval"]

        one = canon.card("approval", "Accept the demo of release 1", refs={"release": 1, "requirements": reqs})
        first = canon.decide(one["id"], "approve", person=OWNER, persona="business_owner")
        self.clock.advance(hours=1)
        canon.mark_stale({"R-1"}, reason="defect C-0009")
        self.assertEqual(stale_ones(), [first["id"]])                                # not given again yet
        self.clock.advance(hours=1)
        two = canon.card("approval", "Accept the demo of release 2", refs={"release": 2, "requirements": reqs})
        canon.decide(two["id"], "reject", person=OWNER, persona="business_owner", reason="not yet")
        self.assertEqual(stale_ones(), [first["id"]])                                # a rejection does not give it
        other = canon.card("validation", "Validate release 2", refs={"release": 2, "requirements": reqs})
        canon.decide(other["id"], "accept", person=OWNER, persona="business_owner")
        self.assertEqual(stale_ones(), [first["id"]])                                # nor another kind of approval
        self.assertEqual(health(p)["status"], "at_risk")
        three = canon.card("approval", "Accept the demo of release 3", refs={"release": 3, "requirements": reqs})
        canon.decide(three["id"], "approve", person=OWNER, persona="business_owner")
        self.assertEqual(stale_ones(), [])                                           # the later release's acceptance
        self.assertEqual(health(p)["status"], "on_track", health(p)["reasons"])


class FoundOnAFailingHoldout(SystemCase):
    """A demo whose holdout author looked for a tool nobody added: its first release stops on a holdout."""

    def setUp(self):
        super().setUp()
        from kernel.deliver import latest_release

        write_json(self.factory.paved_roads_path, LOCAL_ROADS)
        self.p = self.factory.new_project("Tool library", mode="assume", maturity="demo")
        intake(self.p, IDEA, model=story_model(), requested_by=OWNER)
        out = self.run_until_a_person(self.p, story_model(sloppy=True), Cells())
        self.assertEqual(Canon(self.p).get_card(out["waiting_on"][0])["kind"], "holdout_ruling")
        self.release = latest_release(self.p)
        self.assertIn(SLOPPY_NAME, self.release["reason"])                          # the record keeps it (FR-H3)

    def test_FR_O6_AC_3_a_scenario_that_passed_in_a_failing_run_is_held_out_not_unmeasured(self):
        """Found by s6: status.evidence reads the criteria a holdout run ran, but delivery never recorded
        them, so the probe that passed against release 1 showed as not measured beside its passing score."""
        from kernel.packs import build_pack
        from kernel.status import evidence

        step = next(s for s in self.release["steps"] if s["step"] == "holdouts:demo")
        self.assertEqual(sorted(step["native"]["ran"]), ["R-1-AC-2", "R-2-AC-2"])
        states = {e["criterion"]: e["state"] for e in evidence(self.p)}
        self.assertEqual((states["R-1-AC-2"], states["R-2-AC-2"]), ("failing", "held_out"))
        pack = build_pack(self.p)
        self.assertEqual(pack["acceptance"]["not_valid_because"], [{"criterion": "R-1-AC-2", "state": "failing"}])
        self.assertEqual(pack["acceptance"]["holdout_scores"]["by_criterion"], {"R-1-AC-2": "failed",
                                                                                "R-2-AC-2": "passed"})

    def test_FR_Q6_AC_2_what_a_failing_holdout_expected_stays_out_of_the_ledger_and_the_evidence_pack(self):
        """Found by s6: the ledger's release_failed event quoted the scenario's expectation, and the
        evidence pack carries the ledger whole."""
        from kernel.evidence_pack import export

        failed = self.p.ledger().of_kind("release_failed")[-1]["event"]["payload"]
        self.assertEqual(failed["reason"], "holdout R-1-AC-2 failed at step 1: [held out]")
        text = zip_text(export(self.p, self.tmp / "out", person=COMPLIANCE, persona="compliance"))
        self.assertNotIn(SLOPPY_NAME, text)
        self.assertIn("holdout R-1-AC-2 failed at step 1", text)                     # what failed is still said
        self.assertTrue(self.p.ledger().verify().intact)

    def test_FR_T1_AC_4_a_release_stopped_on_a_holdout_says_where_not_what_the_scenario_expected(self):
        """Found by s6: the one-line status quoted the release's reason whole, so the assistant's snapshot
        (and the cockpit's project line) carried what the scenario expected."""
        from kernel.assistant import snapshot
        from kernel.status import now

        ruling = Canon(self.p).cards(kind="holdout_ruling")[0]
        Canon(self.p).decide(ruling["id"], "scenario_defect", person=DEVELOPER, persona="developer",
                             reason="it looked for a tool it never added")
        line = now(self.p)
        self.assertEqual((line["state"], line["line"]),
                         ("failed", "Release 1 stopped: holdout R-1-AC-2 failed at step 1: [held out]"))
        self.assertNotIn(SLOPPY_NAME, json.dumps(snapshot(self.factory, project=self.p)))


if __name__ == "__main__":
    unittest.main()
