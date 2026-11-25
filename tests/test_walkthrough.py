"""FR-WLK1: walkthroughs in Ask Rihma, in the kernel and on the command line (kernel/walkthrough.py).

Each walkthrough's state machine without a model; the walkthrough a person's plain words ask for, in English
and Finnish; nothing written before a Confirm, and the factory's ledger holding ids and step names only; the
confidential branch with a hosted role and the Models setup detour; resume, replace and cancel; and the command
line, which adopts a real repository in the terminal. The cockpit's routes and the waited-for job are in
tests/test_walkthrough_cockpit.py, the browser in tests/test_ui_walkthrough.py.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_fakes import FactoryTestCase, isolated_routing  # noqa: E402
from walkthrough_fakes import allow_roots  # noqa: E402

from kernel import walkthrough as wk  # noqa: E402
from kernel import walkthrough_flows as wf  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import FACTORY_PID, factory_project  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402
from kernel.walkthrough_intent import offer, recognise  # noqa: E402

P, R = "Aino Example", "developer"
SYSTEM = "C:/Windows" if os.name == "nt" else "/etc"
LEDGER_KEYS = {"walkthrough", "name", "step", "person", "persona", "back", "parent", "outcome", "project", "resumed"}
HOSTED = {"endpoints": {"far": {"url": "https://api.example.com/v1/chat/completions"},
                        "near": {"url": "http://127.0.0.1:8080/v1/chat/completions"}},
          "roles": {"analyst": {"endpoint": "far", "model": "m"}, "holdout_author": {"endpoint": "near", "model": "m"},
                    "builder": {"endpoint": "near", "model": "m"}, "verifier": {"endpoint": "near", "model": "m"}}}


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def code_folder(path: Path, *, repo: bool) -> Path:
    """A small Python service with a passing test, an AGENTS.md and a secret-looking .env (never committed)."""
    (path / "tests").mkdir(parents=True)
    (path / "README.md").write_text("# Orders\n\nA small web service for orders.\n", encoding="utf-8")
    (path / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (path / "AGENTS.md").write_text("# Agents\n\nRun the tests before a change.\n", encoding="utf-8")
    (path / "tests" / "test_app.py").write_text(
        "import unittest\n\nfrom app import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n"
        "        self.assertEqual(add(1, 2), 3)\n", encoding="utf-8")
    if repo:
        (path / ".gitignore").write_text(".env\n", encoding="utf-8")
        git(path, "init", "-q")
        git(path, "add", "-A")
        git(path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x")
    (path / ".env").write_text("TOKEN=not-a-real-one\n", encoding="utf-8")
    return path


class Walking(FactoryTestCase):
    def setUp(self):
        super().setUp()
        allow_roots(self, self.tmp)

    def walk(self, name: str, *replies, said: str = "", person: str = P, persona: str = R) -> dict:
        """A fresh walkthrough of ``name``, with the replies given in turn."""
        going = wk.mine(self.factory, person)
        if going is not None:
            wk.cancel(self.factory, going["id"], person=person, persona=persona)
        w = wk.start(self.factory, name, person=person, persona=persona, said=said)
        for r in replies:
            w = wk.reply(self.factory, w["id"], person=person, persona=persona,
                         **(r if isinstance(r, dict) else {"text": r}))
        return w

    def say(self, w: dict, text: str = None, **kw) -> dict:
        return wk.reply(self.factory, w["id"], person=P, persona=R, **({"text": text} if text else kw))

    @staticmethod
    def last(w: dict) -> dict:
        return [m for m in w["messages"] if m["from"] == "rihma"][-1]

    def events(self) -> list:
        return [r["event"] for r in factory_project(self.factory).ledger().records()]


class StateMachineTest(Walking):
    def test_FR_WLK1_AC_1_plug_in_checks_the_folder_scans_it_and_asks_until_adopt_without_a_model(self):
        repo = code_folder(self.tmp / "orders", repo=True)
        w = self.walk("plug_in")
        self.assertEqual((w["step"], self.last(w)["input"]["kind"]), ("source", "path"))
        w = self.say(w, SYSTEM)                                      # a system folder: said plainly, how to allow
        self.assertEqual(w["step"], "source")
        self.assertIn(ROOTS_ENV, self.last(w)["text"])
        self.assertEqual(self.last(w)["input"]["kind"], "path")                   # answered right there
        w = self.say(w, f'"{repo}"')
        self.assertEqual(w["step"], "title")
        scan = next(m["scan"] for m in w["messages"] if m.get("scan"))
        self.assertTrue(scan["git"] and scan["code"])
        self.assertIn("AGENTS.md (Codex, OpenCode)", scan["ai_setup"])
        self.assertEqual(scan["secret_files"], [".env"])
        self.assertTrue(any(lang.startswith("Python") for lang in scan["languages"]))
        self.assertGreaterEqual(scan["read"], 1)
        self.assertEqual(next(m for m in w["messages"] if m.get("scan"))["links"][0]["label"], "See the full map")
        w = self.say(w, choice="default")
        self.assertEqual(w["step"], "confidential")
        w = self.say(w, "ei")                                          # Finnish no
        self.assertEqual(w["step"], "intent")
        self.assertEqual([o["id"] for o in self.last(w)["options"]], ["monitor", "maintain", "improve", "back"])
        w = self.say(w, "2")                                           # by its number
        w = self.say(w, "No posture (the default)")                    # by its label
        self.assertEqual(w["step"], "confirm")
        prop = wk.proposal(w)
        self.assertEqual((prop["action"], prop["label"]), ("adopt", "Adopt Orders"))
        self.assertEqual({k: prop["args"][k] for k in ("intent", "posture", "confidential")},
                         {"intent": "maintain", "posture": None, "confidential": False})
        w = self.say(w, choice="back")
        self.assertEqual(w["step"], "posture")
        w = self.say(w, choice="balanced")
        self.assertEqual(wk.proposal(w)["args"]["posture"], "balanced")

    def test_FR_WLK1_AC_1_a_folder_with_no_code_is_offered_as_documents_and_documents_make_a_new_project(self):
        papers = self.tmp / "papers"
        papers.mkdir()
        (papers / "brief.md").write_text("# Tool loans\n\nThe team lends drills and laptops and loses track of "
                                         "who has them. We need a simple way to lend and return.\n" * 4,
                                         encoding="utf-8")
        w = self.walk("plug_in", str(papers))
        self.assertEqual(w["step"], "nocode")
        w = self.say(w, choice="documents")                           # documents instead, the folder carried
        self.assertEqual((w["name"], w["step"], w["switched_from"] is not None), ("documents", "title", True))
        w = self.say(w, choice="default")
        w = self.say(w, choice="no")
        w = self.say(w, choice="none")
        prop = wk.proposal(w)
        self.assertEqual((prop["action"], prop["args"]["folder"], prop["args"]["source"]),
                         ("new_project", True, str(papers.resolve())))
        spec = self.tmp / "spec.md"
        spec.write_text("# Room bookings\n\nPeople book meeting rooms on paper.\n", encoding="utf-8")
        w = self.walk("documents", str(spec), {"choice": "default"}, {"choice": "no"}, {"choice": "none"})
        self.assertEqual((wk.proposal(w)["args"]["folder"], wk.proposal(w)["label"]), (False, "Create Spec"))
        self.assertIn("People book meeting rooms", wk.proposal(w)["args"]["source"])

    def test_FR_WLK1_AC_1_a_new_idea_goes_to_shape_it_in_chat_or_a_quick_start(self):
        w = self.walk("new_idea", said="Our team loses track of borrowed drills and laptops.")
        self.assertEqual(w["step"], "how")
        w = self.say(w, choice="shape")
        self.assertEqual(wk.proposal(w), {"action": "shape", "label": "Open Shape it in chat",
                                          "lines": ["“Our team loses track of borrowed drills and laptops.”"],
                                          "args": {"text": "Our team loses track of borrowed drills and laptops."}})
        w = self.say(w, choice="back")
        w = self.say(w, "quick")
        self.assertEqual((w["step"], self.last(w)["options"][0]["label"]), ("title", "Our team loses track of borrowed"))
        w = self.say(w, "Tool loans")
        w = self.say(w, choice="same")
        w = self.say(w, "Demo")
        prop = wk.proposal(w)
        self.assertEqual(prop["args"], {"title": "Tool loans", "maturity": "demo",
                                        "source": "Our team loses track of borrowed drills and laptops."})

    def test_FR_WLK1_AC_1_set_up_a_model_lists_the_roles_and_never_keeps_a_key_typed_into_the_chat(self):
        isolated_routing(self, self.tmp)
        w = self.walk("model")
        self.assertIn("Analyst:", self.last(w)["text"])
        self.assertIn("assistant", [o["id"] for o in self.last(w)["options"]])
        w = self.walk("model", {"choice": "assistant"}, {"choice": "hosted"}, {"choice": "openai"}, {"choice": "preset"})
        self.assertEqual(w["step"], "key")
        w = self.say(w, "sk-abc123DEF456ghi789")
        self.assertEqual(w["step"], "key")
        self.assertIn("looks like a key", self.last(w)["text"])
        self.assertNotIn("sk-abc123", json.dumps(wk.get(self.factory, w["id"])))     # never kept
        w = self.say(w, "OPENAI_API_KEY")
        self.assertEqual(wk.proposal(w)["args"], {"role": "assistant", "base_url": "https://api.openai.com/v1",
                                                  "model": "gpt-4.1-mini", "key_env": "OPENAI_API_KEY",
                                                  "private": False})

    def test_FR_WLK1_AC_1_the_tour_has_five_stops_with_take_me_there_next_and_back(self):
        p = self.new()
        w = self.walk("tour")
        stops = [self.last(w)["navigate"]]
        for _ in range(4):
            w = self.say(w, choice="next")
            stops.append(self.last(w)["navigate"])
        self.assertEqual(stops, [{"route": "#/home", "control": "customize"}, {"route": "#/inbox", "control": None},
                                 {"route": f"#/p/{p.pid}/overview", "control": "next_step"},
                                 {"route": f"#/p/{p.pid}/overview", "control": "project_settings"},
                                 {"route": "#/home", "control": "assistant"}])
        w = self.say(w, choice="back")
        self.assertEqual(w["step"], "settings")
        w = self.say(w, "next")
        w = self.say(w, choice="next")
        self.assertEqual((w["state"], w["outcome"]), ("done", "done"))


class IntentTest(Walking):
    def test_FR_WLK1_AC_2_plain_words_in_english_and_finnish_name_the_walkthrough(self):
        cases = {"I have an existing project": "plug_in", "minulla on olemassa oleva projekti": "plug_in",
                 "Can you help me plug in my repo?": "plug_in", "new idea": "new_idea", "uusi idea": "new_idea",
                 "I have an idea for a booking tool": "new_idea", "how do I get started": "tour",
                 "miten pääsen alkuun?": "tour", "set up a model": "model", "haluan asettaa mallin": "model",
                 "I want to start from my documents": "documents", "Where is the ledger?": None,
                 "Where do I assess an existing system?": None}
        for said, name in cases.items():
            self.assertEqual(recognise(said), name, said)

    def test_FR_WLK1_AC_2_ask_rihma_offers_it_by_rule_and_from_the_model_s_take_me_there(self):
        from kernel.assistant import ask

        out = ask(self.factory, "I have an existing project", persona="developer")       # the map, no model
        self.assertEqual(offer("I have an existing project", out)["name"], "plug_in")
        said = {"answer": "I propose the walkthrough.", "navigate": {"route": None, "control": "walk_model"},
                "by": "assistant"}
        self.assertEqual(offer("my answers are slow", said), {"name": "model", "label": "Set up a model",
                                                              "about": wk.flow("model").about, "by": "assistant"})
        self.assertIsNone(offer("Where is the ledger?", {"navigate": {"route": "#/projects", "control": None}}))


class NothingBeforeConfirmTest(Walking):
    def test_FR_WLK1_AC_3_nothing_is_written_before_confirm_and_the_ledger_holds_ids_and_step_names_only(self):
        isolated_routing(self, self.tmp)
        repo = code_folder(self.tmp / "orders", repo=True)
        adopt = self.walk("plug_in", str(repo), {"choice": "default"}, {"choice": "no"}, {"choice": "improve"},
                          {"choice": "none"})
        model = self.walk("model", {"choice": "analyst"}, {"choice": "local"}, {"choice": "ollama"}, {"choice": "preset"},
                          person="Ville Example")
        self.assertEqual((adopt["step"], model["step"]), ("confirm", "confirm"))
        self.assertEqual([p.pid for p in self.factory.projects()], [FACTORY_PID])          # nothing adopted
        self.assertFalse((self.tmp / "routing" / "routing.local.json").exists())           # no role set
        events = self.events()
        self.assertTrue(events and all(e["kind"].startswith("walkthrough_") for e in events))
        for e in events:
            self.assertLessEqual(set(e["payload"]), LEDGER_KEYS, e)
        self.assertNotIn(str(repo), json.dumps(events))                        # no path, no reply: in its file
        calls = []
        done = wk.confirm(self.factory, adopt["id"], person=P, persona=R,
                          run=lambda prop: calls.append(prop) or {"job": {"id": "J-1", "state": "running"}})
        self.assertEqual((len(calls), calls[0]["action"], done["step"]), (1, "adopt", "adopting"))
        with self.assertRaises(wk.WalkRefused):                     # nothing waits on a confirm now
            wk.confirm(self.factory, adopt["id"], person=P, persona=R, run=calls.append)
        self.assertEqual(len(calls), 1)

    def test_FR_WLK1_AC_3_a_refused_confirm_is_said_in_the_chat_and_changes_nothing(self):
        repo = code_folder(self.tmp / "orders", repo=True)
        w = self.walk("plug_in", str(repo), {"choice": "default"}, {"choice": "no"}, {"choice": "improve"},
                      {"choice": "none"})

        def refuse(prop):
            raise PermissionError("Intake and spec is not enabled for this factory")
        out = wk.confirm(self.factory, w["id"], person=P, persona=R, run=refuse)
        self.assertEqual((out["step"], out["refused"]), ("confirm", "Intake and spec is not enabled for this factory"))
        self.assertTrue(self.last(out)["proposal"])                       # asked again: confirm once it is fixed
        self.assertTrue(any(m.get("refused") for m in out["messages"]))


class ConfidentialTest(Walking):
    def test_FR_WLK1_AC_5_confidential_names_the_hosted_roles_and_offers_the_models_setup_detour(self):
        repo = code_folder(self.tmp / "orders", repo=True)
        isolated_routing(self, self.tmp)
        with mock.patch("kernel.confidential._routing", return_value=HOSTED):
            w = self.walk("plug_in", str(repo), {"choice": "default"}, {"text": "kyllä"})
            self.assertEqual(w["step"], "hosted")
            self.assertIn("the analyst role goes to far (api.example.com)", self.last(w)["text"])
            child = self.say(w, choice="walk:model")
            self.assertEqual((child["name"], child["parent"]), ("model", w["id"]))
            self.assertEqual(wk.get(self.factory, w["id"])["state"], "paused")
            self.assertEqual(wk.mine(self.factory, P)["id"], child["id"])          # one active per person
            out = wk.cancel(self.factory, child["id"], person=P, persona=R)
            self.assertEqual(out["resumed"], w["id"])
            back = wk.get(self.factory, w["id"])
            self.assertEqual((back["state"], back["step"]), ("active", "hosted"))
            self.assertIn("Back to Plug in an existing project", [m["text"] for m in back["messages"]][-2])
            w = self.say(back, choice="go")
            self.assertEqual(w["step"], "intent")
            docs = self.tmp / "papers"
            docs.mkdir()
            (docs / "brief.md").write_text("# Loans\n\n" + "We lend drills and lose them. " * 30, encoding="utf-8")
            d = self.walk("documents", str(docs), {"choice": "default"}, {"choice": "yes"})
            self.assertEqual(self.last(d)["options"][1]["label"], "Go on without confidential")
            d = self.walk("documents", str(docs), {"choice": "default"}, {"choice": "yes"}, {"choice": "go"},
                          {"choice": "none"})
            self.assertFalse(wk.proposal(d)["args"]["confidential"])     # refused while hosted: said, not sent


class ResumeCancelTest(Walking):
    def test_FR_WLK1_AC_6_resume_one_active_per_person_replace_and_cancel_at_any_step(self):
        repo = code_folder(self.tmp / "orders", repo=True)
        w = wk.start(self.factory, "tour", person=P, persona=R)
        self.assertEqual(wk.start(self.factory, "tour", person=P, persona=R)["id"], w["id"])      # resumed
        with self.assertRaises(wk.WalkRefused) as refused:
            wk.start(self.factory, "plug_in", person=P, persona=R)
        self.assertIn("is going", str(refused.exception))
        a = wk.start(self.factory, "plug_in", person=P, persona=R, replace=True)
        self.assertEqual((wk.get(self.factory, w["id"])["state"], wk.get(self.factory, w["id"])["outcome"]),
                         ("cancelled", "replaced"))
        with self.assertRaises(wk.WalkRefused):
            wk.reply(self.factory, w["id"], person=P, persona=R, choice="next")
        a = self.say(a, str(repo))
        with self.assertRaises(DecisionRefused):                      # with access enforced: only its own person
            wk.reply(self.factory, a["id"], person="Ville Example", persona=R, choice="default", enforced=True)
        with self.assertRaises(DecisionRefused):
            wk.reply(self.factory, a["id"], person="factory", persona=R, choice="default")   # not a person
        out = wk.cancel(self.factory, a["id"], person=P, persona=R)
        self.assertEqual(out["state"], "cancelled")
        self.assertIsNone(wk.mine(self.factory, P))
        done = [e["payload"] for e in self.events() if e["kind"] == "walkthrough_done"]
        self.assertEqual([d["outcome"] for d in done], ["replaced", "cancelled"])
        again = wk.start(self.factory, "plug_in", person=P, persona=R)
        self.assertEqual(self.last(again)["options"][0], {"id": "recent:0", "label": str(repo.resolve())})
        self.assertEqual(self.say(again, choice="recent:0")["step"], "title")


class CliTest(Walking):
    def run_cli(self, argv: list, answers: list) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        given = iter(answers)
        with mock.patch("builtins.input", lambda prompt="": next(given)), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_WLK1_AC_7_the_command_line_walks_through_plugging_in_and_adopts_in_the_terminal(self):
        repo = code_folder(self.tmp / "orders", repo=False)                   # not a git repository
        code, out, err = self.run_cli(["walkthrough", "plug_in", "--person", P, "--persona", R],
                                      [str(repo), "/map", "1", "no", "maintain", "1", "yes"])
        self.assertEqual(code, 0, err)
        for said in ("Rihma: Which project?", "AI-tool setup found: AGENTS.md", "Read in full", "Type yes to Adopt Orders",
                     "Orders is adopted. Its baseline: passed"):
            self.assertIn(said, out)
        self.assertIn("adopt: running its own tests once for a baseline", err)
        project = next(p for p in self.factory.projects() if p.pid != FACTORY_PID)
        self.assertEqual((project.meta["intent"], project.meta["stage"]), ("maintain", 5))
        code, out, _ = self.run_cli(["walkthrough", "tour", "--person", P, "--persona", R], ["1", "/quit"])
        self.assertIn("Left WT-", out)
        wid = out.rsplit("--resume ", 1)[1].split(".")[0].strip()
        code, out, _ = self.run_cli(["walkthrough", "tour", "--person", P, "--persona", R, "--resume", wid],
                                    ["/cancel"])
        self.assertEqual((code, wk.get(self.factory, wid)["state"]), (0, "cancelled"))
        code, out, _ = self.run_cli(["walkthrough", "list"], [])
        self.assertEqual([w["name"] for w in json.loads(out)["walkthroughs"]],
                         ["plug_in", "documents", "new_idea", "model", "tour"])

    def test_FR_WLK1_AC_10_after_the_adoption_plug_in_offers_open_alignment_and_the_ai_tools_card(self):
        repo = code_folder(self.tmp / "orders", repo=False)
        code, out, err = self.run_cli(["walkthrough", "plug_in", "--person", P, "--persona", R],
                                      [str(repo), "1", "no", "maintain", "1", "yes"])
        self.assertEqual(code, 0, err)
        project = next(p for p in self.factory.projects() if p.pid != FACTORY_PID)
        adopted = out.split("Orders is adopted.", 1)[1]                   # offered once it is done, not before
        self.assertIn(f"Open Alignment: #/p/{project.pid}/align", adopted)
        self.assertIn(f"AI tools in this project: #/p/{project.pid}/overview", adopted)
        self.assertNotIn("Open Alignment", out.split("Orders is adopted.", 1)[0])
        links = wf.adopted_links(project.pid)
        self.assertEqual([(x["label"], x["control"]) for x in links],
                         [("Open Alignment", "align_scan"), ("AI tools in this project", "ai_tools")])


if __name__ == "__main__":
    unittest.main()
