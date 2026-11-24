"""FR-AUT1-AC-5 and FR-AUT1-AC-7: each action of an automation through its real kernel path, with scripted models
and stubs on 127.0.0.1 only. A repository change on an attached repository fires the gate; the project's own
tests run in a temporary clone; a folder is re-scanned; a notice and a signed CloudEvent go through IT's relay
subscriptions; a model's answer becomes a comment; an output is rebuilt; an advance stops where a person is
needed, deciding nothing."""

import base64
import hashlib
import hmac
import http.server
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import model  # noqa: E402
from test_automations import AutoCase  # noqa: E402
from test_standalone import StandaloneTestCase, git, write  # noqa: E402

from kernel import automations as au  # noqa: E402
from kernel import automations_run as run  # noqa: E402
from kernel import outputs, relay  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402

KEY = b"automation-relay-key-0123456789ab"
FAILING = "import unittest\n\nimport calc\n\n\nclass Add(unittest.TestCase):\n    def test_adds(self):\n" \
          "        self.assertEqual(calc.add(2, 3), 5)\n"


def receiver(case):
    """A receiver on 127.0.0.1 that keeps what it is sent."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
            self.send_response(202)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    case.addCleanup(lambda: (server.shutdown(), server.server_close()))
    return f"http://127.0.0.1:{server.server_address[1]}", seen


class RepoActionTest(StandaloneTestCase):
    def ran(self, aid):
        return [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("automation_ran")
                if r["event"]["payload"]["id"] == aid]

    def commit(self, files):
        for name, text in files.items():
            write(self.repo / name, text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "next")
        return git(self.repo, "rev-parse", "HEAD")

    def test_FR_AUT1_AC_5_new_commits_on_an_attached_branch_fire_the_gate_and_notify_when_it_fails(self):
        p = self.attached("--contract", str(self.contract_file))
        base, seen = receiver(self)
        env = {"RELAY_KEY": "whsec_" + base64.b64encode(KEY).decode("ascii")}
        sub = relay.subscribe(self.factory, sink="webhook", url=base + "/ops", secret_env="RELAY_KEY",
                              person="Ilkka", persona="it")
        a = au.add(self.factory, {"name": "Gate on push", "trigger": {"kind": "repo", "branch": "main"},
                                  "action": {"kind": "gate", "verifier": False},
                                  "scope": {"kind": "source", "source": "attached"},
                                  "notify": {"subscription": sub["id"], "when": "failed"}},
                   person="Aino", persona="developer")
        tools = run.Tools(environ=env)
        run.tick(self.factory, tools)                                        # the first look: the baseline
        self.assertEqual(self.ran(a["id"]), [])
        head = self.commit({"tests/test_add.py": FAILING})
        self.clock.advance(minutes=6)
        run.tick(self.factory, tools)
        rows = self.ran(a["id"])
        self.assertEqual([(r["trigger"], r["outcome"], r["verdict"]) for r in rows], [("repo", "done", "failed")])
        self.assertEqual(rows[0]["refs"]["head"], head)
        gate = p.ledger().of_kind("gate")[-1]["event"]["payload"]
        self.assertEqual((gate["head"], gate["verdict"], gate["person"]), (head, "failed", "Aino"))
        self.assertEqual(len(seen), 1)                                         # notified: the gate failed
        sent = seen[0]
        doc = json.loads(sent["body"])
        self.assertEqual(doc["type"], "rihma.automation.notice")
        mac = hmac.new(KEY, f"{sent['headers']['webhook-id']}.{sent['headers']['webhook-timestamp']}.".encode()
                       + sent["body"], hashlib.sha256).digest()
        self.assertEqual(sent["headers"]["webhook-signature"], "v1," + base64.b64encode(mac).decode())
        self.clock.advance(minutes=6)
        run.tick(self.factory, tools)                                          # nothing new: nothing fires
        self.assertEqual(len(self.ran(a["id"])), 1)
        self.untouched()

    def test_FR_AUT1_AC_7_the_projects_own_tests_run_in_a_temporary_clone(self):
        p = self.attached("--contract", str(self.contract_file))
        a = au.add(self.factory, {"name": "Nightly tests", "trigger": {"kind": "schedule", "daily": "02:00"},
                                  "action": {"kind": "command"}, "scope": {"kind": "project", "projects": [p.pid]}},
                   person="Aino", persona="developer")
        self.clock.advance(hours=15)
        run.tick(self.factory)
        row = self.ran(a["id"])[0]
        self.assertEqual((row["outcome"], row["verdict"]), ("done", "passed"), row)
        suite = p.ledger().of_kind("automation_suite")[-1]["event"]["payload"]
        self.assertEqual((suite["verdict"], suite["person"]), ("passed", "Aino"))
        self.untouched()


class ActionTest(AutoCase):
    def test_FR_AUT1_AC_7_notices_go_to_teams_slack_and_mail_through_its_subscriptions_and_a_projects_own(self):
        base, seen = receiver(self)
        env = {"SLACK_URL": base + "/slack", "TEAMS_URL": base + "/teams"}
        slack = relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["it"], person="Ilkka",
                                persona="it")
        teams = relay.subscribe(self.factory, sink="teams", url_env="TEAMS_URL", personas=["it"], person="Ilkka",
                                persona="it", projects=[self.a.pid])
        mails = []
        mail = relay.subscribe(self.factory, sink="email", personas=["it"], person="Ilkka", persona="it",
                               mail={"host": "127.0.0.1", "port": 2525, "from": "rihmasto@example.org",
                                     "to": ["ops@example.org"]})
        for sub in (slack, teams, mail):
            au.add(self.factory, {"name": f"Tell {sub['sink']}",
                                  "trigger": {"kind": "event", "types": ["release_done"]},
                                  "action": {"kind": "notify", "subscription": sub["id"],
                                             "text": "{project} released ({event}) see https://evil.example"},
                                  "scope": {"kind": "factory"}}, person="Ilkka", persona="it")
        self.a.log("release_done", {"release": 1})
        run.tick(self.factory, run.Tools(environ=env, send=lambda m, msg, e: mails.append(msg)))
        self.assertEqual(sorted(s["path"] for s in seen), ["/slack", "/teams"])
        text = b"".join(s["body"] for s in seen).decode()
        self.assertIn(f"{self.a.pid} released (release_done)", text)
        self.assertNotIn("https://evil.example", text)                        # defanged, as every notice
        self.assertEqual(len(mails), 1)
        self.assertIn("[Rihmasto]", mails[0]["Subject"])
        log = relay.deliveries(self.factory)
        self.assertEqual(sorted(r["sink"] for r in log if r["kind"] == "automation_notice"),
                         ["email", "slack", "teams"])

    def test_FR_AUT1_AC_12_a_projects_own_relay_receiver_hears_only_that_project(self):
        env = {"RELAY_KEY": "whsec_" + base64.b64encode(KEY).decode("ascii")}
        own = relay.subscribe(self.factory, sink="webhook", url="http://127.0.0.1:9/a", secret_env="RELAY_KEY",
                              projects=[self.a.pid], person="Ilkka", persona="it")
        self.assertEqual(own["projects"], [self.a.pid])
        self.a.log("release_done", {"release": 1})
        self.b.log("release_done", {"release": 1})
        sent = []
        relay.run(self.factory, environ=env, post=lambda url, body, headers: sent.append(json.loads(body)) or 202)
        self.assertEqual({e["data"]["stream"]["project_id"] for e in sent}, {self.a.pid})
        recorded = factory_project(self.factory).ledger().of_kind("relay_subscribed")[-1]["event"]["payload"]
        self.assertEqual(recorded["projects"], [self.a.pid])

    def test_FR_AUT1_AC_7_a_models_answer_with_the_projects_context_is_posted_as_a_comment(self):
        prompts = []

        def answer(prompt, role):
            prompts.append((prompt, role))
            return "Probably the new loan rule: the approver is missing in two tests."

        a = self.add(trigger={"kind": "event", "types": ["gate_failed"]},
                     action={"kind": "ask", "text": "Why did the gate fail on {project}?"})
        self.a.log("gate", {"task": "T-001", "verdict": "failed"})
        run.tick(self.factory, run.Tools(model=lambda: FakeModel(answer)))
        (prompt, role), = prompts
        self.assertEqual(role, "assistant")
        self.assertIn("Project Loans", prompt)
        self.assertIn(f"Why did the gate fail on {self.a.pid}?", prompt)
        comment = Canon(self.a).comments()[-1]
        self.assertEqual((comment["target"], comment["person"]), ({"kind": "project", "id": self.a.pid}, "Aino"))
        self.assertTrue(comment["text"].startswith(f"[Automation {a['id']}, test]"))
        self.assertIn("approver is missing", comment["text"])

    def test_FR_AUT1_AC_7_a_folder_is_rescanned_and_only_a_change_is_added_as_material(self):
        folder = self.tmp / "notes"
        folder.mkdir()
        (folder / "README.md").write_text("# Loans\n\nA loan has a due date.\n", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {ROOTS_ENV: str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)
        a = self.add(trigger={"kind": "schedule", "weekly": "mon 06:00"},
                     action={"kind": "rescan", "folder": str(folder)})
        self.clock.advance(days=1)
        run.tick(self.factory)
        self.clock.advance(days=7)
        run.tick(self.factory)
        (folder / "README.md").write_text("# Loans\n\nA loan has a due date and a deposit.\n", encoding="utf-8")
        self.clock.advance(days=7)
        run.tick(self.factory)
        rows = [r for r in self.ran(a["id"])]
        self.assertEqual([r["outcome"] for r in rows], ["done", "nothing", "done"])
        added = self.a.read("material.json")["added"]
        self.assertEqual([m["by"] for m in added], ["Aino", "Aino"])
        self.assertIn("deposit", self.a.read("source.json")["text"])

    def test_FR_AUT1_AC_7_the_chosen_outputs_are_rebuilt(self):
        outputs.choose(self.a, ["report"], person="Aino", persona="product_owner")
        a = self.add(trigger={"kind": "event", "types": ["release_done"]}, action={"kind": "output"})
        self.a.log("release_done", {"release": 1})
        run.tick(self.factory)
        row = self.ran(a["id"])[0]
        self.assertEqual((row["outcome"], row["refs"]["built"]), ("done", ["report"]), row)
        built = self.a.ledger().of_kind("output_built")[-1]["event"]["payload"]
        self.assertEqual((built["target"], built["by"]), ("report", "Aino"))
        self.assertTrue(list((self.factory.home / "_cockpit" / "exports").glob("*report*")))

    def test_FR_AUT1_AC_7_an_advance_runs_the_pipeline_and_leaves_every_card_for_people(self):
        intake(self.a, "Our team keeps losing track of who borrowed the drills.", model=model(),
               requested_by="Aino")
        open_before = [c["id"] for c in Canon(self.a).cards()]
        self.assertTrue(open_before)
        a = self.add(trigger={"kind": "schedule", "every": "1h"}, action={"kind": "advance"})
        self.clock.advance(hours=1, minutes=1)
        run.tick(self.factory, run.Tools(model=model))
        row = self.ran(a["id"])[0]
        self.assertEqual((row["outcome"], row["verdict"]), ("done", "waiting"), row)
        self.assertEqual([c["id"] for c in Canon(self.a).cards()], open_before)   # nothing decided
        self.assertEqual(self.a.ledger().of_kind("decision"), [])

    def test_FR_AUT1_AC_7_a_module_that_is_off_refuses_the_action(self):
        from kernel import modules

        modules.set_modules(self.factory, preset="spec_only", person="Ilkka", persona="it")
        a = self.add(trigger={"kind": "event", "types": ["release_done"]})
        self.a.log("release_done", {"release": 1})
        run.tick(self.factory)
        row = self.ran(a["id"])[0]
        self.assertEqual(row["outcome"], "refused")
        self.assertIn("not enabled", row["detail"])


if __name__ == "__main__":
    unittest.main()
