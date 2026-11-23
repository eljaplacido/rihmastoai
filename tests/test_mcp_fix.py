"""Regression tests for the MCP server (FR-N3): no answer confirms a guessed holdout string, a signal
keeps the server's persona, a live cell's target names no folder of the machine, and no line the
client sends ends the server."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_mcp import PERSON, McpCase, call  # noqa: E402

import mcp.server as mcp_server  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.change import triage as triage_change  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.signals import signals  # noqa: E402
from kernel.signals import triage as triage_signal  # noqa: E402
from kernel.store import REPO_ROOT, Factory, write_json, write_text  # noqa: E402
from mcp.server import RihmaMCP, handle_line, serve  # noqa: E402

# A holdout scenario's strings, and a decoy of the same shape that no scenario holds.
HELD_ID = "zq-held-id-3307"
DECOY_ID = "zq-decoy-id-3307"
HELD_ROUTE = "/zq-held-route-8812"


class OracleTest(McpCase):
    """Redaction never runs over the client's own words: if it did, comparing what came back with what
    was sent would confirm which guesses a holdout scenario holds, with nothing in any ledger."""

    def setUp(self):
        super().setUp()
        write_json(self.built.holdouts_dir / "R-1-AC-2.json", {
            "criterion": "R-1-AC-2", "kind": "holdout", "author_role": "holdout_author",
            "steps": [{"method": "POST", "path": HELD_ROUTE, "body": {"name": HELD_ID}, "expect_status": 201}]})
        held = self.server._held()
        self.assertIn(HELD_ID, held)                                         # the guard really knows them
        self.assertIn(HELD_ROUTE, held)
        self.assertNotIn(DECOY_ID, held)

    def assert_no_oracle(self, ask) -> None:
        """The answer to a held guess is the answer to a decoy, with the guess in the decoy's place."""
        held = json.dumps(ask(HELD_ID), ensure_ascii=False)
        decoy = json.dumps(ask(DECOY_ID), ensure_ascii=False)
        self.assertEqual(held, decoy.replace(DECOY_ID, HELD_ID))
        self.assertIn(HELD_ID, held)                                         # echoed as the client sent it
        self.assertNotIn("[held out]", held)

    def test_FR_N3_AC_3_a_refusal_echoes_what_the_client_sent_so_no_guess_is_confirmed(self):
        s, pid = self.server, self.built.pid
        cards = len(Canon(self.built).cards(state=None))
        for tool in ("rihma_floor", "rihma_projects", "rihma_waiting", "rihma_square", "rihma_project"):
            # one argument whose name lists many guesses at once
            self.assert_no_oracle(lambda g, tool=tool: call(s, tool, **{f"{g}|0001|0002": "x", "pid": pid}))
        for tool, extra in (("rihma_project", {}), ("rihma_timeline", {}), ("rihma_evidence", {}),
                            ("rihma_ask", {"question": "how is it going?"}), ("rihma_report_change", {"text": "x"}),
                            ("rihma_comment", {"target_kind": "project", "target_id": "x", "text": "x"})):
            self.assert_no_oracle(lambda g, tool=tool, extra=extra: call(s, tool, pid=g, **extra))
            self.assert_no_oracle(lambda g, tool=tool, extra=extra: call(s, tool, pid="/" + g, **extra))
        self.assert_no_oracle(lambda g: s.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/read",
                                                  "params": {"uri": f"rihma://projects/{g}/spec"}}))
        self.assertEqual(len(Canon(self.built).cards(state=None)), cards)   # every guess above was refused

    def test_FR_N3_AC_3_a_write_answers_with_the_clients_own_title_target_and_source(self):
        s, pid = self.server, self.built.pid
        text = f"Rename {HELD_ID} on {HELD_ROUTE}"
        made = call(s, "rihma_report_change", pid=pid, text=text)["result"]
        self.assertEqual(made["structuredContent"]["title"], text)
        self.assertEqual(json.loads(made["content"][0]["text"])["title"], text)
        said = call(s, "rihma_comment", pid=pid, target_kind="task", target_id=HELD_ID, text="ok")["result"]
        self.assertEqual(said["structuredContent"]["target"], {"kind": "task", "id": HELD_ID})
        raised = call(s, "rihma_signal", text="We need pallets tracked.", source=HELD_ID)["result"]
        self.assertEqual(raised["structuredContent"]["source"], HELD_ID)
        self.assertNotIn("[held out]", json.dumps([made, said, raised]))
        # what is stored is the factory's record: a read of it is still guarded, as any other record is
        owner = RihmaMCP(self.factory, person="Pekka", persona="product_owner", lanes_root=self.tmp / "no-lanes")
        mine = call(owner, "rihma_project", pid=pid)["result"]["structuredContent"]["cards_you_may_decide"]
        card = next(c for c in mine if c["id"] == made["structuredContent"]["card"])
        self.assertEqual(card["title"], "Rename [held out] on [held out]")


class SignalPersonaTest(McpCase):
    def test_FR_N3_AC_2_a_signal_carries_the_servers_persona_into_its_record_its_ledger_and_its_triage(self):
        it = RihmaMCP(self.factory, person="Ilkka", persona="it", lanes_root=self.tmp / "no-lanes")
        answer = call(it, "rihma_signal", text=f"{self.built.pid} needs TLS on its staging address", source="IT desk")
        raised = answer["result"]["structuredContent"]
        self.assertEqual(raised["signed"], {"person": "Ilkka", "persona": "it"})
        sig = next(x for x in signals(self.factory) if x["id"] == raised["signal"])
        self.assertEqual((sig["person"], sig["persona"]), ("Ilkka", "it"))
        received = factory_project(self.factory).ledger().of_kind("signal_received")[-1]["event"]["payload"]
        self.assertEqual((received["id"], received["persona"]), (sig["id"], "it"))
        # triage routes it as IT's: an infrastructure change, not a stakeholder's change request
        routed = triage_signal(self.factory, sig["id"])
        self.assertEqual(routed["routed_to"]["project"], self.built.pid)
        card = Canon(self.built).get_card(routed["routed_to"]["card"])
        self.assertEqual(card["payload"]["source"], "it")
        self.assertEqual(triage_change(self.built, card["id"])["class"], "infra_change")


class LiveTargetTest(FactoryTestCase):
    """A running cell's last target names no folder of this machine, wherever it stands in a command."""

    def setUp(self):
        super().setUp()
        self.factory = Factory(self.tmp / "Jo Smith" / "home", clock=self.clock)   # a space in its path
        self.project = self.factory.new_project("L", mode="assume", maturity="demo")
        self.lanes = self.tmp / "lanes"
        write_json(self.lanes / ".lane-1.lease.json", {"holder": f"{self.project.pid}:T-001"})
        self.server = RihmaMCP(self.factory, person=PERSON, persona="developer", lanes_root=self.lanes)

    def last_target(self, tool: str, target: str) -> str:
        write_text(self.lanes / "lane-1" / ".gnomon-audit" / "task-1.jsonl", "\n".join(json.dumps(r) for r in [
            {"kind": "session_start", "role": "builder"},
            {"kind": "tool_call", "tool": tool, "target": target, "ts": "t"}]) + "\n")
        live = call(self.server, "rihma_project", pid=self.project.pid)["result"]["structuredContent"]["live"]
        return live["last"]["target"]

    def test_FR_N3_AC_3_a_live_cells_command_line_names_no_folder_of_the_machine(self):
        home, repo = Path(self.factory.home), self.project.dir / "repo"
        cases = [
            ("bash", f"pytest {repo} -k x", "pytest .../repo -k x"),
            ("bash", f'pytest "{repo / "tests"}" -q', 'pytest ".../tests" -q'),
            ("bash", f"cd {repo.as_posix()} && ls", "cd .../repo && ls"),
            ("bash", f"cat {self.tmp / 'notes.txt'}", "cat .../notes.txt"),
            ("bash", f"ls {self.lanes / 'lane-1'}", "ls .../lane-1"),
            ("bash", f"pytest {str(home)[:-3]}", "pytest ..."),                 # cut short inside the home
            ("read", str(repo / "app" / "routes.py"), ".../routes.py"),
            ("bash", "python3 -m unittest discover -s tests", "python3 -m unittest discover -s tests"),
            ("write", "app/routes.py", "app/routes.py"),
            ("bash", "curl -s http://127.0.0.1:8000/health", "curl -s http://127.0.0.1:8000/health"),
        ]
        machine = [str(home), home.as_posix(), str(self.tmp), self.tmp.as_posix(), "Jo Smith", "Smith"]
        with contextlib.suppress(RuntimeError):
            machine += [str(Path.home()), Path.home().as_posix()]
        for tool, target, shown in cases:
            served = self.last_target(tool, target)
            if len(target) <= 120:                                           # the kernel keeps 120 characters
                self.assertEqual(served, shown, target)
            for part in machine:
                self.assertNotIn(part, served, target)


class StdioTest(FactoryTestCase):
    """No line the client sends ends the server: each gets an answer and the next one is still read."""

    def setUp(self):
        super().setUp()
        self.factory.new_project("Loans", mode="assume", maturity="demo")
        self.server = RihmaMCP(self.factory, person=PERSON, persona="developer", lanes_root=self.tmp / "no-lanes")

    def test_FR_N3_AC_1_a_deeply_nested_line_is_refused_and_the_server_keeps_serving(self):
        deep = "[" * 200000
        answer = json.loads(handle_line(self.server, deep.encode("utf-8")))
        self.assertEqual((answer["id"], answer["error"]["code"]), (None, -32700))
        self.assertIn("nested too deeply", answer["error"]["message"])
        nested_argument = ('{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "rihma_floor", '
                           '"arguments": {"x": ' + "[" * 25000 + "]" * 25000 + "}}}")
        lines = [deep, nested_argument, json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})]
        env = dict(os.environ, GF_LANES=str(self.tmp / "no-lanes"))
        proc = subprocess.run([sys.executable, "-m", "mcp.server", "--home", str(self.factory.home), "--person",
                               PERSON, "--persona", "developer"], input="".join(x + "\n" for x in lines).encode(),
                              capture_output=True, cwd=REPO_ROOT, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace")[-2000:])
        answers = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        self.assertEqual([(a["id"], a.get("error", {}).get("code")) for a in answers],
                         [(None, -32700), (None, -32700), (2, None)])
        self.assertEqual(answers[2]["result"], {})

    def test_FR_N3_AC_1_a_line_that_breaks_the_server_is_answered_and_the_next_one_still_is(self):
        real = mcp_server.handle_line

        def breaks_once(server, line):
            if b"breaks" in line:
                raise RuntimeError("a bug")
            return real(server, line)

        lines = [{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"breaks": True}},
                 {"jsonrpc": "2.0", "id": 2, "method": "ping"}]
        stdin = io.BytesIO("".join(json.dumps(m) + "\n" for m in lines).encode("utf-8"))
        stdout, stderr = io.BytesIO(), io.StringIO()
        mcp_server.handle_line = breaks_once
        try:
            with contextlib.redirect_stderr(stderr):
                serve(self.server, stdin=stdin, stdout=stdout)
        finally:
            mcp_server.handle_line = real
        answers = [json.loads(line) for line in stdout.getvalue().decode("utf-8").splitlines()]
        self.assertEqual(answers[0], {"jsonrpc": "2.0", "id": None,
                                      "error": {"code": -32603, "message": "internal error: RuntimeError"}})
        self.assertEqual(answers[1], {"jsonrpc": "2.0", "id": 2, "result": {}})
        self.assertIn("RuntimeError: a bug", stderr.getvalue())               # the traceback went to stderr

    def test_FR_N3_AC_1_an_invalid_request_echoes_its_id_only_when_it_is_a_string_or_a_number(self):
        s = self.server
        self.assertIsNone(s.handle({"jsonrpc": "1.0", "id": [[1]]})["id"])
        self.assertIsNone(s.handle({"jsonrpc": "2.0", "id": {"a": [1]}})["id"])
        self.assertIsNone(s.handle({"jsonrpc": "1.0", "id": True})["id"])
        self.assertEqual(s.handle({"jsonrpc": "1.0", "id": 7})["id"], 7)
        self.assertEqual(s.handle({"jsonrpc": "2.0", "id": "q"})["id"], "q")
        # an id nested as deep as the parser goes is never written back
        depth = 5000
        line = '{"jsonrpc": "1.0", "id": ' + "[" * depth + "]" * depth + "}"
        answer = json.loads(handle_line(s, line.encode("utf-8")))
        self.assertEqual((answer["id"], answer["error"]["code"]), (None, -32600))


if __name__ == "__main__":
    unittest.main()
