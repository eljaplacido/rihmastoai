"""A project's development board, trace and developer briefing, its session hooks and Ask Rihma by rule (FR-DEV1).

A neutral fixture: a project with four contract tasks (one merged, one escalated with its card open, one handed to an
outside agent, one waiting for it), gate rounds, cells, a model run, an MCP write, a channel post, and a bare
repository whose commits name the tasks. Skipped without git.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agent_channel as ch  # noqa: E402
from kernel import assistant, devask, devboard, devbrief, devsessions, devtrace  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402

DEV = "Dana Example"
GIT = shutil.which("git")
TASKS = [{"id": "T-001", "title": "Record a loan", "criteria": ["R-1-AC-1"]},
         {"id": "T-002", "title": "A loan has a return date", "criteria": ["R-2-AC-1"], "depends_on": ["T-001"]},
         {"id": "T-003", "title": "Remind before the return date", "criteria": ["R-3-AC-1"]},
         {"id": "T-004", "title": "List overdue loans", "criteria": ["R-3-AC-2"], "depends_on": ["T-003"]}]
REQS = [{"id": f"R-{n}", "acceptance": [{"id": f"R-{n}-AC-{k}", "given": "a loan", "when": "it is saved",
                                        "then": f"rule {n}.{k} holds"} for k in (1, 2)]} for n in (1, 2, 3)]


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def commit(work: Path, name: str, subject: str) -> str:
    (work / name).write_text(subject + "\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", subject)
    return git(work, "rev-parse", "HEAD")


def gate_round(task, rnd, verdict, head, objections=()):
    return {"task": task, "round": rnd, "head": head, "verdict": verdict, "objections": list(objections),
            "signals": {"tests": "passed", "trace": "passed", "fail_first": verdict, "verifier": verdict}}


def round_with_tests(rnd, verdict, names):
    return {"round": rnd, "cell": {}, "gate": {"verdict": verdict, "signals": [
        {"name": "tests", "verdict": "passed", "native": {"ran": len(names), "tests": names}}]}}


def world(case) -> object:
    """The fixture project, with a repository when git is here."""
    p = case.factory.new_project("Loans board", mode="mixed", maturity="demo")
    p.write("contract.json", {"revision": "sha256:x", "requirements": REQS, "tasks": TASKS})
    heads = {}
    if GIT:
        work = case.tmp / "work"
        work.mkdir()
        git(work, "init", "-q", "-b", "main")
        heads["base"] = commit(work, "a.txt", "Scaffold from the paved road")
        heads["T-001"] = commit(work, "b.txt", "T-001 round 0: cell work")
        heads["T-002"] = commit(work, "c.txt", "T-002 round 1: cell work")
        subprocess.run(["git", "clone", "-q", "--bare", str(work), str(p.path("repo.git"))], check=True)
    runner = {"name": "gnomon", "label": "Gnomon"}
    p.log("cell_ran", {"task": "T-001", "round": 0, "model": "m1", "head": heads.get("T-001"), "runner": runner})
    p.log("gate", gate_round("T-001", 0, "passed", heads.get("T-001")))
    p.log("merged", {"task": "T-001", "revision": heads.get("T-001"), "permitted_by": "policy"})
    p.log("model_run", {"role": "verifier", "model": "m2", "task": "T-001"})
    case.clock.advance(hours=1)
    p.log("cell_ran", {"task": "T-002", "round": 0, "model": "m1", "runner": runner})
    p.log("gate", gate_round("T-002", 0, "failed", heads.get("T-002"), ["fail_first: passes without it"]))
    card = Canon(p).card("escalation", "T-002 did not pass its gate", refs={"task": "T-002"}, blocking=True)
    p.log("escalated", {"task": "T-002", "card": card["id"]})
    Canon(p).card("change", "Add a due-date filter", refs={"source": "operations"})
    p.write("tasks.json", {"T-001": {"status": "merged", "rounds": [round_with_tests(0, "passed", {
        "test_R_1_AC_1_a_loan_is_recorded": "ok", "test_SCAFFOLD_health": "ok"})]},
        "T-002": {"status": "escalated",
                  "rounds": [round_with_tests(0, "failed", {"test_R_2_AC_1_return_date": "fail"})]}})
    p.log("mcp_write", {"action": "propose_change", "target": "C-0009", "person": DEV, "persona": "developer"})
    ch.post(p, author=ch.agent("claude-code", DEV, "developer", "claude-code"), kind="progress",
            text="Started the reminder", refs={"tasks": ["T-003"]})
    case.card = card["id"]
    return p


@unittest.skipUnless(GIT, "git is needed for the repository")
class BoardTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = world(self)

    def test_FR_DEV1_AC_1_each_task_is_in_its_lane_with_what_it_rests_on(self):
        before = tree(self.factory.home)
        b = devboard.board(self.p)
        cards = {c["id"]: c for c in b["cards"]}
        self.assertEqual({t: cards[t]["lane"] for t in ("T-001", "T-002", "T-003", "T-004")},
                         {"T-001": "done", "T-002": "blocked", "T-003": "in_progress", "T-004": "planned"})
        one, two = cards["T-001"], cards["T-002"]
        self.assertEqual(one["requirements"], ["R-1"])
        self.assertEqual(one["criteria"][0]["then"], "rule 1.1 holds")
        self.assertEqual(one["tests"], [{"name": "test_R_1_AC_1_a_loan_is_recorded", "result": "ok"}])
        self.assertEqual([c["subject"] for c in one["commits"]], ["T-001 round 0: cell work"])
        self.assertTrue(one["commits"][0]["on_main"])
        self.assertEqual([(g["round"], g["verdict"]) for g in one["gates"]], [(0, "passed")])
        self.assertEqual([(a["harness"], a["via"]) for a in one["agents"]], [("gnomon", "cell")])
        self.assertEqual((two["waits_on"]["card"], "developer" in two["waits_on"]["who"]), (self.card, True))
        self.assertIn("escalation", two["why"])
        self.assertIn(("claude-code", "channel"), [(a["harness"], a["via"]) for a in cards["T-003"]["agents"]])
        self.assertEqual(cards["T-004"]["why"], "waits for T-003")
        change = next(c for c in b["cards"] if c["kind"] == "change")
        self.assertEqual(change["lane"], "planned")
        self.assertEqual(b["counts"], {"planned": 2, "in_progress": 1, "review": 0, "blocked": 1, "done": 1})
        self.assertIn("claude-code", b["filters"]["harnesses"])
        self.assertEqual(b["filters"]["requirements"], ["R-1", "R-2", "R-3"])
        self.assertTrue(b["commits"]["measured"])
        self.assertEqual(tree(self.factory.home), before)            # reading writes nothing

    def test_FR_DEV1_AC_1_without_a_repository_commits_are_not_measured_and_no_tasks_says_how(self):
        self.p.path("repo.git").rename(self.tmp / "set-aside.git")       # its objects are read-only on Windows
        b = devboard.board(self.p)
        self.assertEqual((b["commits"]["measured"], bool(b["commits"]["how"])), (False, True))
        bare = self.factory.new_project("Empty board")
        out = devboard.board(bare)
        self.assertEqual(out["cards"], [])
        self.assertIn("compiled", out["no_tasks"]["why"])

    def test_FR_DEV1_AC_2_every_interaction_once_with_who_and_its_record(self):
        t = devtrace.trace(self.p, window="all")
        ats = [i["at"] for i in t["items"]]
        self.assertEqual(ats, sorted(ats, reverse=True))
        kinds = {i["kind"]: i for i in t["items"]}
        self.assertEqual(kinds["cell_ran"]["who"]["harness"], "gnomon")
        self.assertEqual((kinds["model_run"]["who"]["kind"], kinds["model_run"]["who"]["role"]), ("rihma", "verifier"))
        self.assertEqual((kinds["mcp_write"]["who"]["kind"], kinds["mcp_write"]["who"]["operator"]), ("agent", DEV))
        self.assertEqual(kinds["merged"]["what"], "T-001 merged into main")
        self.assertIsInstance(kinds["gate"]["record"]["seq"], int)
        posts = [i for i in t["items"] if "reminder" in i["what"]]
        self.assertEqual(len(posts), 1)                                  # a channel post shows once
        self.assertEqual((posts[0]["who"]["harness"], posts[0]["task"]), ("claude-code", "T-003"))
        self.assertNotIn("channel_posted", kinds)
        agents = devtrace.trace(self.p, window="all", who="agent")
        self.assertTrue(agents["items"] and all(i["who"]["kind"] == "agent" for i in agents["items"]))
        self.assertEqual({i["task"] for i in devtrace.trace(self.p, task="T-002")["items"]}, {"T-002"})
        self.clock.advance(days=3)
        self.assertEqual(devtrace.trace(self.p, window="24h")["items"], [])
        self.assertIn("claude-code", t["filters"]["harnesses"])

    def test_FR_DEV1_AC_3_the_next_step_and_only_what_blocks_it(self):
        b = devbrief.briefing(self.p, person=DEV)
        self.assertEqual(b["since_basis"], "the last 7 days")
        self.assertEqual(b["next"]["task"], "T-002")
        self.assertEqual(b["next"]["action"]["control"], "decide")
        self.assertEqual([x["card"] for x in b["blocking"]], [self.card])      # not the change: it blocks nothing
        self.assertEqual(b["by_harness"].get("gnomon"), 2)
        self.assertEqual((b["changed"]["gates"]["passed"], b["changed"]["gates"]["failed"]), (1, 1))
        self.assertEqual(b["changed"]["merged"], ["T-001"])
        self.assertEqual(b["changed"]["tests"]["failed"], ["test_R_2_AC_1_return_date"])
        devsessions.look(self.p, person=DEV, persona="developer")
        self.clock.advance(minutes=5)
        self.p.log("cell_ran", {"task": "T-003", "round": 0, "model": "m1", "runner": {"name": "gnomon"}})
        again = devbrief.briefing(self.p, person=DEV)
        self.assertEqual(again["since_basis"], "your last look")
        self.assertEqual([s["task"] for s in again["sessions"]], ["T-003"])
        self.assertEqual(devbrief.briefing(self.p, person="Someone Else")["since_basis"], "the last 7 days")

    def test_FR_DEV1_AC_3_the_order_of_the_next_step(self):
        def card(cid, lane, kind="task", why="ready to start", **more):
            return {"id": cid, "lane": lane, "kind": kind, "why": why, "title": cid, **more}
        board = {"project": "p", "cards": [card("T-1", "review", gates=[{"objections": 2}]), card("T-2", "planned")]}
        self.assertTrue(devbrief.next_step(board)["title"].startswith("Fix what the gate found on T-1"))
        board["cards"].append(card("S-0001", "in_progress", kind="session"))
        self.assertTrue(devbrief.next_step(board)["title"].startswith("Finish the"))
        board["cards"] = [card("T-2", "planned"), card("T-3", "done")]
        self.assertEqual(devbrief.next_step(board)["task"], "T-2")
        board["cards"] = [card("T-3", "done")]
        self.assertIn("Every task is merged", devbrief.next_step(board)["title"])
        board["cards"].append(card("C-0002", "planned", kind="change"))
        self.assertEqual(devbrief.next_step(board)["action"]["control"], "decide")

    def test_FR_DEV1_AC_5_ask_rihma_by_rule(self):
        before = len(self.p.ledger().records())
        out = assistant.ask(self.factory, "What's next in development?", persona="developer", project_id=self.p.pid,
                            person=DEV)
        self.assertTrue(out["answer"].startswith("Next in development: Decide " + self.card), out["answer"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/board")
        self.assertEqual(out["by"], "map")
        out = assistant.ask(self.factory, "What did the agents do since yesterday?", persona="developer",
                            project_id=self.p.pid, person=DEV)
        self.assertIn("the last 24 hours", out["answer"])
        self.assertIn("claude-code", out["answer"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.p.pid}/trace")
        self.clock.advance(days=3)
        quiet = devask.answer(self.factory, self.p, "mitä agentit tekivät eilen?", person=DEV)
        self.assertTrue(quiet["answer"].startswith("No agent worked on this project in the last 24 hours"))
        self.assertIsNone(devask.answer(self.factory, None, "what's next in development?", person=DEV))  # FR-DEV2
        self.assertIsNone(devask.asks("What is the weather?"))
        self.assertEqual(len(self.p.ledger().records()), before)          # nothing recorded


@unittest.skipUnless(GIT, "git is needed for the session hooks")
class HooksTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.factory.new_project("Hooked project")
        self.work = self.tmp / "repo"
        self.work.mkdir()
        git(self.work, "init", "-q", "-b", "work/t-003")
        commit(self.work, "a.txt", "start")

    def hook(self, event, session="sess-1", harness="claude-code", **more):
        stdin = StringIO(json.dumps({"session_id": session, "cwd": str(self.work), **more}))
        return devsessions.hook_main(["--harness", harness, "--event", event], stdin, home=str(self.factory.home),
                                     pid=self.p.pid, person=DEV, persona="developer")

    def test_FR_DEV1_AC_4_the_hooks_record_metadata_only_signed_by_the_operator(self):
        files = {f["path"]: f for f in devsessions.hooks(self.p, person=DEV, persona="developer",
                                                         python=sys.executable)["files"]}
        claude = json.loads(files[".claude/settings.json"]["content"])
        self.assertIn("--event start", claude["hooks"]["SessionStart"][0]["hooks"][0]["command"])
        self.assertIn("--event end", claude["hooks"]["SessionEnd"][0]["hooks"][0]["command"])
        cursor = json.loads(files[".cursor/hooks.json"]["content"])
        self.assertEqual(sorted(cursor["hooks"]), ["beforeSubmitPrompt", "stop"])
        script = files[devsessions.HOOK_FILE]["content"]
        compile(script, "session_hook.py", "exec")
        self.assertIn(json.dumps(self.p.pid), script)
        start = self.hook("start", source="startup", prompt="secret words")
        self.assertTrue(start["recorded"])
        self.assertEqual((start["session"]["branch"], len(start["session"]["head"])), ("work/t-003", 40))
        self.assertFalse(self.hook("start")["recorded"])                 # the same session's second start
        self.clock.advance(minutes=30)
        commit(self.work, "b.txt", "T-003 remind before the date")
        commit(self.work, "c.txt", "T-003 tests")
        end = self.hook("end", reason="logout")
        self.assertEqual({k: end["session"][k] for k in ("commits", "files_changed", "tasks", "reason")},
                         {"commits": 2, "files_changed": 2, "tasks": ["T-003"], "reason": "logout"})
        self.assertIsInstance(end["session"]["seconds"], int)            # the hook reads the real clock
        self.assertFalse(self.hook("end")["recorded"])                   # Cursor's stop after every turn: updated
        kept = json.dumps(devsessions.sessions(self.p))
        self.assertNotIn("secret words", kept)
        recs = [r["event"]["payload"] for r in self.p.ledger().of_kind(devsessions.KIND)]
        self.assertEqual([(r["event"], r["person"]) for r in recs], [("start", DEV), ("end", DEV)])
        b = devboard.board(self.p)
        self.assertEqual([c["kind"] for c in b["cards"]], [])               # the session ended: nothing open

    def test_FR_DEV1_AC_4_bad_input_is_refused_and_a_failing_hook_never_stops_the_agent(self):
        bad = [dict(harness="vim"), dict(event="pause"), dict(session="a b"), dict(person="kernel"),
               dict(branch="x;rm"), dict(head="zz"), dict(commits=-1)]
        for more in bad:
            args = dict(harness="cursor", event="start", session="s", person=DEV, persona="developer") | more
            with self.assertRaises(devsessions.SessionRefused, msg=str(more)):
                devsessions.record(self.p, **args)
        self.assertEqual(devsessions.sessions(self.p), [])
        files = devsessions.hooks(self.p, person=DEV, persona="developer", python=sys.executable)["files"]
        script = self.tmp / "hook.py"
        script.write_text(files[0]["content"].replace(json.dumps(self.p.pid), json.dumps("no-such-project")),
                          encoding="utf-8")
        done = subprocess.run([sys.executable, str(script), "--harness", "cursor", "--event", "start"],
                              input=json.dumps({"conversation_id": "c1"}), capture_output=True, text=True,
                              timeout=60, cwd=str(self.work))
        self.assertEqual(done.returncode, 0)
        self.assertIn("not recorded", done.stderr)
        self.assertEqual(done.stdout.strip(), '{"continue": true}')

    def test_FR_DEV1_AC_4_the_generated_script_records_a_real_session_and_the_command_line_too(self):
        files = devsessions.hooks(self.p, person=DEV, persona="developer", python=sys.executable)["files"]
        hook = self.work / devsessions.HOOK_FILE
        hook.parent.mkdir(parents=True)
        hook.write_text(files[0]["content"], encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run([sys.executable, devsessions.HOOK_FILE, "--harness", "claude-code", "--event", "start"],
                              input=json.dumps({"session_id": "real-1", "cwd": str(self.work)}), capture_output=True,
                              text=True, timeout=60, cwd=str(self.work), env=env)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual([s["session"] for s in devsessions.sessions(self.p)], ["real-1"])
        self.assertEqual([c["kind"] for c in devboard.board(self.p)["cards"]], ["session"])
        code = main(["--home", str(self.factory.home), "dev", "session", self.p.pid, "--harness", "codex", "--event",
                     "start", "--session", "cli-1", "--person", DEV, "--persona", "developer"])
        self.assertEqual(code, 0)
        self.assertEqual(main(["--home", str(self.factory.home), "dev", "session", self.p.pid, "--harness", "codex",
                               "--event", "start", "--session", "cli-2", "--person", "kernel", "--persona",
                               "developer"]), 2)


@unittest.skipUnless(GIT, "git is needed for the repository")
class DevRoutesTest(CockpitTestCase):
    def test_FR_DEV1_AC_3_got_it_is_signed_and_the_routes_answer_from_the_records(self):
        p = world(self)
        base = f"/api/projects/{p.pid}/dev"
        status, board, _ = self.call("GET", base + "/board")
        self.assertEqual((status, board["counts"]["blocked"]), (200, 1))
        status, t, _ = self.call("GET", base + "/trace?window=all&who=rihma")
        self.assertEqual((status, {i["kind"] for i in t["items"]}), (200, {"model_run"}))
        status, hooks, _ = self.call("GET", base + f"/hooks?person={DEV.replace(' ', '%20')}&persona=developer")
        self.assertEqual((status, len(hooks["files"]), hooks["person"]), (200, 3, DEV))
        status, out, _ = self.call("POST", base + "/seen", {"person": "kernel", "persona": "developer"})
        self.assertEqual(status, 403, out)
        self.assertEqual(p.ledger().of_kind(devsessions.LOOKED), [])
        status, out, _ = self.call("POST", base + "/seen", {"person": DEV, "persona": "developer"})
        self.assertEqual(status, 200, out)
        self.assertEqual(p.ledger().of_kind(devsessions.LOOKED)[-1]["event"]["payload"]["person"], DEV)
        status, b, _ = self.call("GET", base + f"/briefing?person={DEV.replace(' ', '%20')}")
        self.assertEqual((status, b["since_basis"], b["next"]["task"]), (200, "your last look", "T-002"))
        status, f, _ = self.call("GET", "/api/projects/_factory/dev/board")
        self.assertEqual((status, f["applies"]), (200, False))


if __name__ == "__main__":
    unittest.main()
