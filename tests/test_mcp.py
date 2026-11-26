import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, model, no_findings  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.change import submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.rulings import open_ruling  # noqa: E402
from kernel.signals import signals  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import REPO_ROOT, write_json, write_text  # noqa: E402
from mcp.server import PROTOCOL_VERSIONS, TOOLS, RihmaMCP, main, tool_list  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
# The agent bridge's tools (mcp/bridge_tools.py, FR-BRG1, FR-CHN1): reads, and writes that are proposals or posts.
BRIDGE_WRITES = ("rihma_progress", "rihma_propose_answer", "rihma_request_gate", "rihma_channel_post", "rihma_ask_rihma")
BRIDGE_TOOLS = {"rihma_next", "rihma_plan", "rihma_questions", "rihma_handoff", "rihma_feedback", "rihma_insights",
                "rihma_alignment", "rihma_health", "rihma_channel_read", *BRIDGE_WRITES}
PERSON = "Tessa"
# Words a tool that takes a decision would carry. None may appear in the server's tool list.
DECIDING = ("decide", "answer", "approve", "accept", "reject", "pause", "resume", "deploy", "assume", "settle",
            "advance", "rollback", "grant", "promote", "verdict", "rule")

# Holdout content: tokens that appear nowhere else, so any leak is visible.
HELD_BODY = "zq-held-body-4471"
HELD_EXPECT = "zq-held-expect-9083"
HELD_PATH = "/zq-held-path-2265"
HELD_OLD = "zq-retired-scenario-5510"          # a scenario since rewritten: no longer in the custody
OUTSIDE = "zq-outside-secret-7342"
ROAD_SECRET = "zq-road-secret-6618"


def seed(factory, tmp):
    """A built project, a project waiting on a question, and the factory's own canon."""
    built = factory.new_project("Built", mode="assume", maturity="demo")
    intake(built, IDEA, model=model(), requested_by="Aino")
    make_spec(built, model=model())
    compile_project(built)
    build_task(built, "T-001", lanes=Lanes(tmp / "lanes", size=1), cell_runner=good_cell,
               verifier_runner=no_findings)
    waiting = factory.new_project("Waiting", mode="mixed", maturity="demo")
    intake(waiting, IDEA, model=model(), requested_by="Aino")
    return built, waiting


def call(server, name, mid=1, **arguments):
    return server.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments}})


class McpCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.built, self.waiting = seed(self.factory, self.tmp)
        self.server = RihmaMCP(self.factory, person=PERSON, persona="developer", lanes_root=self.tmp / "no-lanes")

    def result(self, name, **arguments):
        answer = call(self.server, name, **arguments)
        self.assertIn("result", answer, answer)
        self.assertFalse(answer["result"]["isError"], answer)
        return answer["result"]["structuredContent"]


class StdioTest(McpCase):
    def run_server(self, lines: list, *args) -> subprocess.CompletedProcess:
        env = dict(os.environ, GF_LANES=str(self.tmp / "no-lanes"))
        argv = [sys.executable, "-m", "mcp.server", "--home", str(self.factory.home), *args]
        stdin = "".join(line + "\n" for line in lines).encode("utf-8")
        return subprocess.run(argv, input=stdin, capture_output=True, cwd=REPO_ROOT, env=env, timeout=120)

    def test_FR_N3_AC_1_the_server_speaks_mcp_over_stdio_end_to_end(self):
        pid = self.built.pid
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "rihma_projects", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "rihma_project", "arguments": {"pid": pid}}},
            {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 6, "method": "resources/read", "params": {"uri": f"rihma://projects/{pid}/spec"}},
            {"jsonrpc": "2.0", "id": 7, "method": "resources/read", "params": {"uri": f"rihma://projects/{pid}/contract"}},
            {"jsonrpc": "2.0", "id": 8, "method": "resources/read", "params": {"uri": f"rihma://projects/{pid}/ledger"}},
            {"jsonrpc": "2.0", "id": 9, "method": "resources/read", "params": {"uri": "rihma://cockpit/map"}},
            {"jsonrpc": "2.0", "id": 10, "method": "ping"},
            {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "rihma_decide", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {"name": "rihma_project", "arguments": {"pid": "no-such"}}},
            {"jsonrpc": "2.0", "id": 13, "method": "tools/call", "params": {"name": "rihma_timeline", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 14, "method": "resources/read", "params": {"uri": "rihma://projects/no-such/spec"}},
            {"jsonrpc": "2.0", "id": 15, "method": "no/such/method"},
        ]
        proc = self.run_server([json.dumps(m) for m in msgs] + ["this is not json"],
                               "--person", PERSON, "--persona", "developer")
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        out = proc.stdout.decode("utf-8")
        self.assertNotIn("Traceback", out)
        answers = [json.loads(line) for line in out.splitlines()]          # stdout holds only messages
        self.assertTrue(all(a["jsonrpc"] == "2.0" for a in answers))
        by_id = {a["id"]: a for a in answers}
        self.assertEqual(len(answers), 16)                                  # 15 requests and the parse error
        init = by_id[1]["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertEqual(init["serverInfo"]["name"], "rihma")
        self.assertIn("version", init["serverInfo"])
        self.assertEqual(init["capabilities"], {"tools": {}, "resources": {}})
        self.assertIn("cockpit", init["instructions"])
        tools = by_id[2]["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, set(TOOLS))
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["description"])
        projects = by_id[3]["result"]
        self.assertFalse(projects["isError"])
        self.assertEqual(projects["content"][0]["type"], "text")
        self.assertEqual(json.loads(projects["content"][0]["text"]), projects["structuredContent"])
        rows = {r["id"]: r for r in projects["structuredContent"]["projects"]}
        self.assertEqual(set(rows), {self.built.pid, self.waiting.pid})
        self.assertEqual(set(rows[pid]), {"id", "title", "profile", "maturity", "stage", "stage_name", "now", "health"})
        self.assertEqual(rows[pid]["profile"], "web_service")
        one = by_id[4]["result"]["structuredContent"]
        self.assertEqual(one["evidence"].get("verified"), 1)                  # T-001 merged through its gate
        self.assertEqual(one["live"]["running"], False)
        uris = {r["uri"] for r in by_id[5]["result"]["resources"]}
        self.assertLessEqual({f"rihma://projects/{pid}/{w}" for w in ("spec", "contract", "ledger")}
                             | {"rihma://cockpit/map"}, uris)
        spec = by_id[6]["result"]["contents"][0]
        self.assertEqual((spec["uri"], spec["mimeType"]), (f"rihma://projects/{pid}/spec", "text/markdown"))
        self.assertEqual(spec["text"], self.built.path("spec.md").read_text(encoding="utf-8"))
        contract = json.loads(by_id[7]["result"]["contents"][0]["text"])
        self.assertEqual(contract["revision"], self.built.read("contract.json")["revision"])
        ledger = json.loads(by_id[8]["result"]["contents"][0]["text"])
        self.assertEqual(ledger["total"], len(self.built.ledger().records()))
        self.assertLessEqual(ledger["shown"], 100)
        self.assertEqual(ledger["records"][-1]["seq"], ledger["total"] - 1)
        self.assertIn("views", json.loads(by_id[9]["result"]["contents"][0]["text"]))
        self.assertEqual(by_id[10]["result"], {})
        self.assertEqual(by_id[11]["error"]["code"], -32602)                  # unknown tool: a protocol error
        self.assertIn("Unknown tool", by_id[11]["error"]["message"])
        self.assertTrue(by_id[12]["result"]["isError"])                       # unknown project: a plain message
        self.assertIn("no project no-such", by_id[12]["result"]["content"][0]["text"])
        self.assertTrue(by_id[13]["result"]["isError"])                       # a missing argument
        self.assertIn("pid is required", by_id[13]["result"]["content"][0]["text"])
        self.assertEqual(by_id[14]["error"]["code"], -32002)
        self.assertEqual(by_id[15]["error"]["code"], -32601)
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertIn("serving", proc.stderr.decode("utf-8", "replace"))      # logs go to stderr

    def test_FR_N3_AC_1_protocol_versions_are_negotiated_and_bad_arguments_get_plain_messages(self):
        s = self.server
        init = s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(init["result"]["protocolVersion"], PROTOCOL_VERSIONS[0])
        for v in PROTOCOL_VERSIONS:
            init = s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": v}})
            self.assertEqual(init["result"]["protocolVersion"], v)
        self.assertIsNone(s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(s.handle({"jsonrpc": "2.0", "id": 2, "method": "server/discover"})["error"]["code"], -32601)
        bad = [("rihma_project", {"pid": "../../etc"}, "no project"),
               ("rihma_project", {"pid": 7}, "pid must be text"),
               ("rihma_project", {"pid": self.built.pid, "extra": "x"}, "unknown argument"),
               ("rihma_comment", {"pid": self.built.pid, "target_kind": "nothing", "target_id": "x", "text": "t"},
                "target_kind must be one of"),
               ("rihma_report_change", {"pid": self.built.pid, "text": "   "}, "text is required"),
               ("rihma_ask", {"question": "where is the ledger?", "pid": "no-such"}, "no project")]
        for name, args, says in bad:
            answer = call(s, name, **args)
            self.assertTrue(answer["result"]["isError"], (name, args))
            self.assertIn(says, answer["result"]["content"][0]["text"])
        answer = s.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "rihma_project", "arguments": ["not", "an", "object"]}})
        self.assertEqual(answer["error"]["code"], -32602)
        asked = self.result("rihma_ask", question="where is the ledger?", pid=self.built.pid)
        self.assertEqual(asked["by"], "map")
        self.assertEqual(asked["navigate"]["route"], f"#/p/{self.built.pid}/ledger")
        self.assertIn("cockpit", asked["note"])


class ProposalTest(McpCase):
    def test_FR_N3_AC_2_the_tool_list_holds_no_decide_answer_approve_pause_or_deploy_tool(self):
        tools = tool_list()
        self.assertEqual({t["name"] for t in tools},
                         {"rihma_projects", "rihma_project", "rihma_waiting", "rihma_floor", "rihma_timeline",
                          "rihma_evidence", "rihma_square", "rihma_ask", "rihma_report_change", "rihma_comment",
                          "rihma_signal", "rihma_track", "rihma_autopilot", "rihma_assessment"} | BRIDGE_TOOLS)
        for t in tools:
            # a proposed answer is a suggestion a person confirms (FR-BRG1): "answer" only after "propose"
            name, title = (t["name"].replace("propose_answer", "propose"),
                           t["title"].lower().replace("propose an answer", "propose"))
            for word in DECIDING:
                self.assertNotIn(word, name.lower(), t["name"])
                self.assertNotIn(word, title, t["name"])
            writes = not t["annotations"]["readOnlyHint"]
            self.assertEqual(writes, t["name"] in ("rihma_report_change", "rihma_comment", "rihma_signal",
                                                   *BRIDGE_WRITES))
        self.assertIn("No tool here decides a card, answers a question, approves, pauses, resumes or deploys",
                      self.server.instructions)

    def test_FR_N3_AC_2_writes_are_proposals_signed_with_the_servers_person_and_persona(self):
        p = self.built
        canon = Canon(p)
        decisions, cards = len(canon.decisions()), {c["id"]: c["state"] for c in canon.cards(state=None)}
        made = self.result("rihma_report_change", pid=p.pid, text="We should rename the report to Monthly losses")
        card = canon.get_card(made["card"])
        self.assertEqual((card["kind"], card["state"]), ("change", "open"))
        self.assertEqual((card["payload"]["person"], card["payload"]["source"]), (PERSON, "developer"))
        self.assertEqual(made["signed"], {"person": PERSON, "persona": "developer"})
        self.assertEqual(made["triage"]["class"], "change_request")
        self.assertTrue(made["triage"]["needs_decision"])                     # a person decides it, not the server
        said = self.result("rihma_comment", pid=p.pid, target_kind="requirement", target_id="R-2",
                           text="Could the approver be optional for small items?")
        comment = canon.comments({"kind": "requirement", "id": "R-2"})[-1]
        self.assertEqual((comment["id"], comment["person"], comment["persona"]), (said["comment"], PERSON, "developer"))
        raised = self.result("rihma_signal", text="The warehouse also needs to track pallets.", source="code review")
        sig = next(s for s in signals(self.factory) if s["id"] == raised["signal"])
        self.assertEqual((sig["person"], sig["persona"], sig["channel"], sig["source"], sig["state"]),
                         (PERSON, "developer", "manual", "code review", "new"))
        # signed in the ledgers, with the persona
        kinds = [(r["event"]["kind"], r["event"]["payload"]) for r in p.ledger().records()]
        self.assertIn(("change_submitted", {"card": made["card"], "persona": "developer", "person": PERSON}), kinds)
        notes = [pl for k, pl in kinds if k == "mcp_write"]
        self.assertEqual([(n["action"], n["person"], n["persona"]) for n in notes],
                         [("report_change", PERSON, "developer"), ("comment", PERSON, "developer")])
        fnotes = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("mcp_write")]
        self.assertEqual([(n["action"], n["target"], n["person"], n["persona"]) for n in fnotes],
                         [("signal", raised["signal"], PERSON, "developer")])
        # proposals only: no decision was recorded and no card already there changed state
        self.assertEqual(len(canon.decisions()), decisions)
        self.assertEqual({cid: canon.get_card(cid)["state"] for cid in cards}, cards)
        # what waits on a persona is the Inbox's rule: the change waits on a product owner, not a developer
        waits = self.result("rihma_waiting")["items"]
        self.assertNotIn((p.pid, made["card"]), [(i["project"], i["card"]) for i in waits])
        self.assertIn((self.waiting.pid, "question"), [(i["project"], i["kind"]) for i in waits])  # open to all
        owner = RihmaMCP(self.factory, person="Pekka", persona="product_owner", lanes_root=self.tmp / "no-lanes")
        waits = call(owner, "rihma_waiting")["result"]["structuredContent"]["items"]
        self.assertIn((p.pid, made["card"]), [(i["project"], i["card"]) for i in waits])
        mine = call(owner, "rihma_project", pid=p.pid)["result"]["structuredContent"]["cards_you_may_decide"]
        self.assertIn({"id": made["card"], "title": card["title"]}, mine)

    def test_FR_N3_AC_2_the_server_refuses_to_start_for_a_non_person_or_an_unknown_persona(self):
        for person in ("assistant", "claude", "  ", "model"):
            with self.assertRaises(ValueError):
                RihmaMCP(self.factory, person=person, persona="developer")
        with self.assertRaises(ValueError):
            RihmaMCP(self.factory, person=PERSON, persona="root")
        home = str(self.factory.home)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(["--home", home, "--person", PERSON, "--persona", "root"]), 2)
            self.assertEqual(main(["--home", str(self.tmp / "no-home"), "--person", PERSON, "--persona", "developer"]), 2)
        self.assertIn("persona must be one of", err.getvalue())
        env = dict(os.environ, GF_LANES=str(self.tmp / "no-lanes"))
        proc = subprocess.run([sys.executable, "-m", "mcp.server", "--home", home, "--person", "assistant",
                               "--persona", "developer"], input=b"", capture_output=True, cwd=REPO_ROOT, env=env,
                              timeout=60)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b"")                                    # nothing on the protocol stream
        self.assertIn("not a person", proc.stderr.decode("utf-8", "replace"))


class CustodyTest(McpCase):
    """Holdout content and anything outside the factory home never reach the client."""

    def setUp(self):
        super().setUp()
        p = self.built
        # the holdout custody, outside the project folder
        write_json(p.holdouts_dir / "R-1-AC-2.json", {
            "criterion": "R-1-AC-2", "kind": "holdout", "author_role": "holdout_author",
            "steps": [{"method": "POST", "path": HELD_PATH, "body": {"name": HELD_BODY}, "expect_status": 201},
                      {"method": "GET", "path": "/items", "expect_contains": HELD_EXPECT}]})
        write_json(p.holdouts_dir / "R-4-AC-2.json", {
            "criterion": "R-4-AC-2", "kind": "probe",
            "steps": [{"method": "GET", "path": "/health", "expect_json": {"status": HELD_BODY}, "max_ms": 500}]})
        # a release whose holdout failed, as kernel/deliver.py records it, and the ruling card it opens
        failing = [{"criterion": "R-1-AC-2", "failed_step": 2, "request": {"method": "GET", "path": "/items"},
                    "expected": {"expect_contains": HELD_EXPECT}, "observed": {"status": 200, "body": []},
                    "reason": f"the response does not contain {HELD_EXPECT!r}"}]
        reason = f"holdout R-1-AC-2 failed at step 2: the response does not contain {HELD_EXPECT!r}"
        release = {"number": 1, "revision": "r1", "state": "failed", "failed_step": "holdouts:staging",
                   "reason": reason, "steps": [{"step": "holdouts:staging", "outcome": "failed",
                                                "native": {"verdict": "failed", "failing": failing, "why": reason}}]}
        write_json(p.path("releases", "1.json"), release)
        p.log("release_failed", {"release": 1, "step": "holdouts:staging", "reason": reason, "incident": None,
                                 "handoff": None})
        self.ruling = open_ruling(p, 1, release)
        self.assertIn(HELD_EXPECT, self.ruling["body"])                       # the data is really in the home
        # a person pastes the failure into a change, which waits on an owner
        pasted = submit(p, persona="operations", person="Olli", kind_hint="change_request",
                        text=f"Expect {HELD_EXPECT} on {HELD_PATH}")
        triage(p, pasted["id"])
        # a project whose release stopped on a scenario since rewritten: its reason is all that is left
        self.stopped = self.factory.new_project("Stopped", mode="assume", maturity="demo")
        intake(self.stopped, IDEA, model=model(), requested_by="Aino")
        make_spec(self.stopped, model=model())
        compile_project(self.stopped)
        old = f"holdout R-1-AC-2 failed at step 1: the response does not contain {HELD_OLD!r}"
        write_json(self.stopped.path("releases", "1.json"), {"number": 1, "state": "failed", "reason": old,
                                                              "failed_step": "holdouts:staging", "steps": []})
        self.stopped.log("release_failed", {"release": 1, "step": "holdouts:staging", "reason": old})
        self.stopped.log("holdouts_authored", {"criteria": ["R-1-AC-2"], "missing": [],
                                               "reauthored_because": f"it expected {HELD_OLD}", "ruled_by": "Aino"})
        # secrets in the home that are not served, and a file outside the home
        write_json(self.factory.paved_roads_path, {"azure-prod": {"identity": ROAD_SECRET}})
        self.outside = self.tmp / "outside-dir-q7z"
        write_text(self.outside / "secret.txt", OUTSIDE + "\n")
        write_text(self.outside / "spec.md", OUTSIDE + "\n")
        write_json(self.outside / "project.json", {"id": "evil", "title": OUTSIDE, "stage": 1})
        # a running cell whose last action names a file outside the home
        lanes = self.tmp / "lanes-live"
        write_json(lanes / ".lane-1.lease.json", {"holder": f"{p.pid}:T-002"})
        write_text(lanes / "lane-1" / ".gnomon-audit" / "task-1.jsonl", "\n".join(json.dumps(r) for r in [
            {"kind": "session_start", "role": "builder"}, {"kind": "model_call", "model": "fake-builder"},
            {"kind": "tool_call", "tool": "read", "target": str(self.outside / "secret.txt"), "ts": "t"}]) + "\n")
        self.symlinked = False
        link = self.factory.projects_dir / "evil-1"
        try:
            os.symlink(self.outside, link, target_is_directory=True)
            self.symlinked = True
        except (OSError, NotImplementedError):                                # no symlink rights: try a junction
            try:
                import _winapi

                _winapi.CreateJunction(str(self.outside), str(link))
                self.symlinked = True
            except (ImportError, OSError):
                pass

    def sweep(self, persona: str) -> str:
        """Every tool with real arguments and every resource the server offers, plus reads that try to leave
        the home, as the text a client would receive."""
        s = RihmaMCP(self.factory, person=PERSON, persona=persona, lanes_root=self.tmp / "lanes-live")
        out = []
        pids = [self.built.pid, self.waiting.pid, self.stopped.pid, "evil-1", "_factory"]
        calls = [("rihma_projects", {}), ("rihma_waiting", {}), ("rihma_floor", {}), ("rihma_square", {}),
                 ("rihma_ask", {"question": "why did the release stop?"})]
        for pid in pids + ["../outside-dir-q7z", "..", "outside-dir-q7z"]:
            calls += [("rihma_project", {"pid": pid}), ("rihma_timeline", {"pid": pid}),
                      ("rihma_evidence", {"pid": pid}), ("rihma_ask", {"question": "how is it going?", "pid": pid})]
        for n, (name, args) in enumerate(calls):
            out.append(json.dumps(call(s, name, mid=n, **args), ensure_ascii=False))
        listed = s.handle({"jsonrpc": "2.0", "id": "l", "method": "resources/list"})
        out.append(json.dumps(listed, ensure_ascii=False))
        uris = [r["uri"] for r in listed["result"]["resources"]]
        uris += [f"rihma://projects/{pid}/{w}" for pid in pids for w in ("spec", "contract", "ledger")]
        uris += ["rihma://projects/../spec", "rihma://projects/..%2Foutside-dir-q7z/spec",
                 "rihma://projects/outside-dir-q7z/spec", f"file:///{(self.outside / 'secret.txt').as_posix()}",
                 "rihma://projects/_factory/../../outside-dir-q7z/secret.txt", "rihma://cockpit/../holdouts",
                 f"rihma://projects/{self.built.pid}/holdouts", f"rihma://holdouts/{self.built.pid}/R-1-AC-2"]
        for n, uri in enumerate(uris):
            out.append(json.dumps(s.handle({"jsonrpc": "2.0", "id": n, "method": "resources/read",
                                            "params": {"uri": uri}}), ensure_ascii=False))
        out.append(json.dumps(s.handle({"jsonrpc": "2.0", "id": "t", "method": "resources/templates/list"})))
        return "\n".join(out)

    def test_FR_N3_AC_3_holdout_content_and_anything_outside_the_home_never_reach_the_client(self):
        home = self.factory.home
        for persona in ("product_owner", "developer"):
            text = self.sweep(persona)
            # content, and the machine's own paths (a refusal may echo what the client asked for, nothing more)
            for token in (HELD_BODY, HELD_EXPECT, HELD_PATH, HELD_OLD, OUTSIDE, ROAD_SECRET,
                          str(home), home.as_posix(), json.dumps(str(home))[1:-1]):
                self.assertNotIn(token, text, f"{token!r} reached a {persona} client")
        # the reads still say what happened, with the details held out
        s = RihmaMCP(self.factory, person=PERSON, persona="product_owner", lanes_root=self.tmp / "lanes-live")
        built = call(s, "rihma_project", pid=self.built.pid)["result"]["structuredContent"]
        self.assertIn(self.ruling["id"], [c["id"] for c in built["cards_you_may_decide"]])
        self.assertTrue(any("[held out]" in c["title"] for c in built["cards_you_may_decide"]))
        self.assertEqual(built["live"]["last"]["target"], ".../secret.txt")
        stopped = call(s, "rihma_project", pid=self.stopped.pid)["result"]["structuredContent"]
        self.assertEqual(stopped["now"]["state"], "failed")
        self.assertIn("holdout R-1-AC-2 failed at step 1: [held out]", stopped["now"]["line"])
        read = s.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                         "params": {"uri": f"rihma://projects/{self.stopped.pid}/ledger"}})
        records = json.loads(read["result"]["contents"][0]["text"])["records"]
        failed = next(r for r in records if r["kind"] == "release_failed")
        self.assertEqual(failed["redacted"], ["reason"])
        authored = next(r for r in records if r["kind"] == "holdouts_authored" and r.get("redacted"))
        self.assertEqual(authored["redacted"], ["reauthored_because"])
        evidence = call(s, "rihma_evidence", pid=self.built.pid)["result"]["structuredContent"]
        self.assertEqual(next(e for e in evidence["criteria"] if e["criterion"] == "R-1-AC-2")["state"], "failing")
        refused = s.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/read",
                            "params": {"uri": "rihma://projects/../spec"}})
        self.assertEqual(refused["error"]["code"], -32002)
        if self.symlinked:                                                    # a project folder that leads out of the home
            self.assertIn("evil-1", [p.pid for p in self.factory.projects()])  # the kernel alone would list it
            self.assertTrue(call(s, "rihma_project", pid="evil-1")["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
