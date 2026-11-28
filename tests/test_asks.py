"""FR-XAG1: machines, and asks between agents and machines, through the kernel, the real cockpit server on a temp
factory (tests/test_cockpit.py CockpitTestCase), the reply link's /x/ calls, the command line and Ask Rihma.

The machines are invented ("laptop", "build-server"); nothing connects anywhere: the doctor is patched where an answer
would test a connection (tests/test_reach.py tests the doctor itself).
"""

import contextlib
import io
import json
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import _DIRECT, CockpitTestCase  # noqa: E402

from kernel import agent_channel as ch  # noqa: E402
from kernel import asks, channel_consult, machines, reach  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

DANA = {"person": "Dana Example", "persona": "developer"}
WHO = ("--person", "Dana Example", "--persona", "developer")


def ledger_text(project) -> str:
    return project.path("ledger.jsonl").read_text(encoding="utf-8")


class AsksTestCase(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.factory.new_project("Webshop", mode="mixed", maturity="demo")
        machines.add(self.factory, {"name": "laptop", "reach": "ssh", "address": "me@laptop", "os": "windows",
                                    "agents": ["claude-code"]}, **DANA)

    def put(self, text="run git status and tell me the branch", **extra):
        return asks.create(self.p, to="claude-code", machine="laptop", text=text, why="to read the work there",
                           expects="the branch and the first lines", **DANA, **extra)["ask"]

    def raw_post(self, path, body, *, ctype="application/json", origin=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": ctype, **({"Origin": origin} if origin else {})}
        req = urllib.request.Request(self.origin + path, data=data, headers=headers, method="POST")
        try:
            with _DIRECT.open(req, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")


class MachinesTest(AsksTestCase):
    def test_FR_XAG1_AC_1_the_machines_are_kept_signed_platform_wide_and_the_ledger_never_holds_an_address(self):
        d = machines.describe(self.factory)
        self.assertEqual((d["scope"], [m["name"] for m in d["machines"]]), ("platform", ["laptop"]))
        machines.add(self.factory, {"name": "laptop", "agents": "claude-code, codex"}, **DANA)   # keeps the rest
        self.assertEqual(machines.get(self.factory, "laptop")["address"], "me@laptop")
        self.assertEqual(machines.get(self.factory, "laptop")["agents"], ["claude-code", "codex"])
        self.assertEqual(machines.agent_on(self.factory, "codex"), ["laptop"])
        for bad, why in (({"name": "Laptop!"}, "name"), ({"name": "x", "reach": "ftp"}, "reached"),
                         ({"name": "x", "reach": "ssh", "address": "a b"}, "ssh"),
                         ({"name": "x", "reach": "ssh", "address": r"-F\\evil.example\s\c@host"}, "ssh"),
                         ({"name": "x", "reach": "ssh", "address": "-Elog@host"}, "ssh"),
                         ({"name": "x", "reach": "https", "address": "http://x"}, "https"),
                         ({"name": "x", "os": "plan9"}, "system")):
            with self.assertRaisesRegex(machines.MachineRefused, why):
                machines.add(self.factory, bad, **DANA)
        with self.assertRaises(DecisionRefused):
            machines.add(self.factory, {"name": "x"}, person="", persona="developer")
        with self.assertRaisesRegex(DecisionRefused, "kept by"):
            machines.add(self.factory, {"name": "x"}, person="Dana Example", persona="business_owner")
        out = machines.remove(self.factory, "laptop", **DANA)
        self.assertEqual(out["removed"], "laptop")
        own = ledger_text(factory_project(self.factory))
        self.assertIn('"machine_added"', own)
        self.assertIn('"machine_removed"', own)
        self.assertNotIn("me@laptop", own)                                      # never its address
        # the cockpit's routes, signed
        status, body, _ = self.call("POST", "/api/machines", {"name": "build-server", "reach": "https",
                                                              "address": "https://build.example", **DANA})
        self.assertEqual((status, body["added"]), (200, True))
        status, body, _ = self.call("GET", "/api/machines")
        self.assertEqual([m["name"] for m in body["machines"]], ["build-server"])
        status, body, _ = self.call("POST", "/api/machines", {"name": "BAD NAME", **DANA})
        self.assertEqual(status, 400)


class AskFlowTest(AsksTestCase):
    def test_FR_XAG1_AC_2_an_ask_is_a_question_in_the_channel_an_agent_here_reads_and_answers_with_reply_to(self):
        a = self.put()
        self.assertEqual((a["id"], a["state"], a["to"], a["machine"]), ("AK-0001", "open", "claude-code", "laptop"))
        msg = ch.get(self.p, a["message"])
        self.assertEqual((msg["kind"], msg["author"]["kind"], msg["to"]), ("question", "person", ["claude-code"]))
        waiting = channel_consult.waiting(self.p, "claude-code")         # what rihma_channel_read lists for the agent
        self.assertEqual([w["id"] for w in waiting], [a["message"]])
        ch.post(self.p, author=ch.agent("claude-code", "Dana Example", "developer"), kind="answer",
                text="On branch main, 2 files changed.", refs={"message": a["message"]})
        done = asks.get(self.p, a["id"])
        self.assertEqual((done["state"], done["answer"]["text"], done["answer"]["via"]),
                         ("answered", "On branch main, 2 files changed.", "mcp"))
        self.assertEqual(asks.summary(self.factory)["asks"], [])
        led = ledger_text(self.p)
        self.assertIn('"ask_created"', led)
        self.assertNotIn("run git status", led)                              # ids, whom and how, never the words
        for bad in ({"to": "Claude Code!"}, {"to": "claude-code", "text": ""}, {"to": "claude-code", "machine": "nope"},
                    {"to": "claude-code", "days": 0}, {"to": "claude-code", "days": 99}):
            with self.assertRaises(asks.AskRefused):
                asks.create(self.p, **{"text": "x", **bad}, **DANA)
        # through the cockpit
        status, body, _ = self.call("POST", f"/api/projects/{self.p.pid}/asks",
                                    {"to": "codex", "text": "do the tests pass on main?", **DANA})
        self.assertEqual((status, body["ask"]["state"]), (200, "open"))
        status, body, _ = self.call("GET", "/api/asks")
        self.assertEqual([r["id"] for r in body["asks"]], ["AK-0002"])

    def test_FR_XAG1_AC_3_copy_for_the_other_agent_paste_the_answer_back_withdraw_and_a_settled_ask_takes_nothing(self):
        a = self.put()
        status, body, _ = self.call("POST", f"/api/projects/{self.p.pid}/asks/{a['id']}/copy", DANA)
        self.assertEqual(status, 200)
        for part in (a["id"], "Webshop", "laptop", "run git status", "Why: to read the work there",
                     "Answer with: the branch", "How to answer"):
            self.assertIn(part, body["text"])
        self.assertEqual(asks.get(self.p, a["id"])["state"], "delivered")
        status, body, _ = self.call("POST", f"/api/projects/{self.p.pid}/asks/{a['id']}/answer",
                                    {"text": "main, clean", **DANA})
        self.assertEqual((status, body["ask"]["state"], body["ask"]["answer"]["via"]), (200, "answered", "paste"))
        reply = ch.get(self.p, body["ask"]["answer"]["id"])
        self.assertEqual((reply["author"]["kind"], reply["author"]["name"], reply["author"]["operator"]),
                         ("agent", "claude-code", "Dana Example"))
        status, body, _ = self.call("POST", f"/api/projects/{self.p.pid}/asks/{a['id']}/answer", {"text": "x", **DANA})
        self.assertEqual(status, 400)                                         # answered: it takes nothing more
        b = self.put(text="second")
        asks.withdraw(self.p, b["id"], **DANA)
        self.assertEqual(asks.get(self.p, b["id"])["state"], "withdrawn")
        with self.assertRaisesRegex(asks.AskRefused, "withdrawn"):
            asks.copy_text(self.p, b["id"], **DANA)
        c = self.put(text="third", days=1)
        later = asks._now(self.factory) + asks.dt.timedelta(days=2)
        with mock.patch.object(asks, "_now", return_value=later):
            self.assertEqual(asks.get(self.p, c["id"])["state"], "expired")
            with self.assertRaisesRegex(asks.AskRefused, "expired"):
                asks.answer(self.p, c["id"], "late", **DANA)


class ReplyLinkTest(AsksTestCase):
    def test_FR_XAG1_AC_4_a_reply_link_is_shown_once_one_answer_refused_when_wrong_and_local_without_a_front(self):
        a = self.put()
        status, link, _ = self.call("POST", f"/api/projects/{self.p.pid}/asks/{a['id']}/link", DANA)
        self.assertEqual(status, 200)
        token = link["token"]
        self.assertTrue(link["local_only"])                                  # no trusted https front here
        self.assertIn("this computer only", link["said"])
        self.assertIn("/x/api/answer", link["how"])
        stored = factory_project(self.factory).path(asks.LINKS).read_text(encoding="utf-8")
        self.assertNotIn(token, stored)                                      # only its sha256
        self.assertNotIn(token, ledger_text(self.p))
        status, body = self.raw_post("/x/api/ask", {"token": token})
        self.assertEqual((status, body["ask"], body["text"]), (200, a["id"], "run git status and tell me the branch"))
        self.assertEqual(asks.get(self.p, a["id"])["state"], "delivered")
        self.assertEqual(self.raw_post("/x/api/ask", {"token": token}, ctype="text/plain")[0], 400)
        self.assertEqual(self.raw_post("/x/api/ask", {"token": token}, origin="https://evil.example")[0], 403)
        req_spoof = urllib.request.Request(
            self.origin + "/x/api/ask", data=json.dumps({"token": token}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Origin": "https://evil.example",
                     "X-Forwarded-Host": "evil.example"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as spoof_ctx:
            _DIRECT.open(req_spoof, timeout=10)
        self.assertEqual(spoof_ctx.exception.code, 403)
        spoof_ctx.exception.close()
        self.assertEqual(self.raw_post("/x/api/ask", {"token": "xa_" + "A" * 43})[0], 403)
        status, body = self.raw_post("/x/api/answer", {"token": token, "answer": "main, 2 files changed"})
        self.assertEqual(status, 200)
        done = asks.get(self.p, a["id"])
        self.assertEqual((done["state"], done["answer"]["via"]), ("answered", "link"))
        self.assertEqual(self.raw_post("/x/api/answer", {"token": token, "answer": "again"})[0], 403)   # one answer
        # refused tries wait, per address
        from kernel import hitl_page
        hitl_page._FAILS.clear()
        codes = [self.raw_post("/x/api/ask", {"token": "xa_" + "B" * 43})[0]
                 for _ in range(hitl_page.OPENS_PER_MINUTE + 1)]
        self.assertEqual(codes[-1], 429)
        hitl_page._FAILS.clear()
        # a GET is refused plainly; the cockpit's own API still needs a session
        req = urllib.request.Request(self.origin + "/x/api/ask", method="GET")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _DIRECT.open(req, timeout=10)
        self.assertEqual(ctx.exception.code, 405)
        ctx.exception.close()

    def test_FR_XAG1_AC_4_an_expired_link_is_refused(self):
        a = self.put()
        out = asks.reply_link(self.p, a["id"], **DANA, base="https://cockpit.example", hours=1, local=False)
        self.assertFalse(out["local_only"])
        self.assertNotIn("this computer only", out["said"])
        later = asks._now(self.factory) + asks.dt.timedelta(hours=2)
        with mock.patch.object(asks, "_now", return_value=later), self.assertRaisesRegex(asks.AskRefused, "expired"):
            asks.read_by_link(self.factory, out["token"])


class AskRihmaTest(AsksTestCase):
    def ask(self, q):
        return ask(self.factory, q, persona="developer", project_id=self.p.pid, model=None)

    def test_FR_XAG1_AC_5_ask_rihma_answers_waiting_and_machines_and_proposes_asks_machines_and_answers(self):
        self.assertIn("Nothing waits", self.ask("what am I waiting on from other agents?")["answer"])
        a = self.put()
        out = self.ask("what am I waiting on from other agents?")
        self.assertEqual(out["matches"], ["asks"])
        self.assertIn(a["id"], out["answer"])
        self.assertIn("laptop: by ssh", self.ask("which machines do I have?")["answer"])
        out = self.ask("ask the agent on laptop to run the tests and tell me what fails")
        prop = out["propose"][0]
        self.assertEqual((prop["action"], prop["args"]["to"], prop["args"]["machine"]),
                         ("ask_put", "claude-code", "laptop"))
        self.assertEqual(asks.listed(self.p)[0]["id"], a["id"])               # proposed only: nothing was sent
        self.assertEqual(self.ask(f"the answer to {a['id']} is main, clean")["propose"][0]["action"], "ask_answer")
        self.assertEqual(self.ask(f"withdraw {a['id']}")["propose"][0]["action"], "ask_withdraw")
        out = self.ask("add the machine build-server, reached by ssh me@build-server, linux")
        self.assertEqual(out["propose"][0]["args"], {"name": "build-server", "reach": "ssh",
                                                     "address": "me@build-server", "os": "linux"})
        self.assertEqual(self.ask("remove the machine laptop")["propose"][0]["action"], "machine_remove")
        self.assertIsNotNone(machines.get(self.factory, "laptop"))
        self.assertNotEqual(self.ask("ask claude code how to sync")["matches"], ["asks"])   # the channel's consult
        with mock.patch.object(reach, "test_ssh", return_value="refused"):
            out = self.ask("is the laptop reachable?")
        self.assertIn("refuses the connection", out["answer"])
        self.assertEqual(out["propose"][0]["action"], "ask_put")


class CommandLineTest(AsksTestCase):
    def run_cli(self, *argv):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, buf.getvalue(), err.getvalue()

    def test_FR_XAG1_AC_5_the_command_line_puts_copies_answers_and_lists_asks(self):
        code, out, _ = self.run_cli("asks", "put", self.p.pid, "--to", "codex", "--text", "is main green?",
                                    "--person", "Dana Example", "--persona", "developer")
        self.assertEqual(code, 0)
        aid = json.loads(out)["ask"]["id"]
        code, out, _ = self.run_cli("asks", "copy", self.p.pid, aid, *WHO)
        self.assertIn("is main green?", json.loads(out)["text"])
        code, out, _ = self.run_cli("asks", "answer", self.p.pid, aid, "--text", "yes", "--person", "Dana Example",
                                    "--persona", "developer")
        self.assertEqual(json.loads(out)["ask"]["state"], "answered")
        code, out, _ = self.run_cli("asks", "list", "--project", self.p.pid)
        self.assertEqual(json.loads(out)["asks"][0]["state"], "answered")
        code, _, err = self.run_cli("asks", "copy", self.p.pid, aid, *WHO)
        self.assertEqual(code, 2)
        self.assertIn("answered", err)
        code, out, _ = self.run_cli("machines", "list")
        self.assertEqual([m["name"] for m in json.loads(out)["machines"]], ["laptop"])


if __name__ == "__main__":
    unittest.main()
