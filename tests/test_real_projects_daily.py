"""FR-RPJ1: working on an adopted project day to day (kernel side).

A neutral notes-and-scripts folder with no git and no test command, adopted to improve: the hand-off brief an
agent gets, Ask Rihma on working in a terminal and on a change as a goal, the Plug in walkthrough given the same
folder again, and what the project page says about a baseline that is not measured. Each test names the
criterion it holds; the page's text is held in tests/test_ui_real_projects.py's style by reading the module.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rpj_fixture as fx  # noqa: E402
from walkthrough_fakes import allow_roots  # noqa: E402

from kernel import adopt, agent_bridge, copilot  # noqa: E402
from kernel import assistant as kassistant  # noqa: E402
from kernel import walkthrough as wk  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = ("Aino Tester", "developer")
ROOT = Path(__file__).resolve().parents[1]
SUMMARY = "A toolbox of scripts and local services that keep my notes and machines in step."


def toolbox(root: Path) -> Path:
    """A folder with no git and no test command: a README, scripts and a service unit."""
    fx._write(root, {"README.md": f"# Toolbox\n\n{SUMMARY}\n\n## Use\n\nRun the scripts by hand.\n",
                     "scripts/sync.py": "print('sync')\n", "scripts/switch.ps1": "Write-Output 'switch'\n",
                     "units/sync.service": "[Unit]\nDescription=sync\n"})
    return root


class WorkOnAdoptedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rpj-daily-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.src = toolbox(cls.tmp / "toolbox")
        cls.p = adopt.adopt(cls.factory, "Toolbox", source=str(cls.src), intent="improve", person=PERSON[0],
                            persona=PERSON[1], suite_timeout=5, maturity="explore")

    def test_FR_RPJ1_AC_17_the_hand_off_brief_of_an_adopted_project_says_what_it_is_and_how_its_tests_run(self):
        b = agent_bridge.brief(self.p)
        md = agent_bridge.render(b)
        self.assertIn("Governed in Rihmasto: adopted to improve: improving, maturity explore.", md)
        self.assertNotIn("stage 5", md)
        self.assertEqual(b["goal"], f"Toolbox: {SUMMARY}")                    # not only the title
        self.assertNotIn("paved road's product suite", md)
        self.assertIn("no test command was found by rule", md)
        self.assertIn("do not invent one", md)
        finding = {"id": "F-1", "key": "cicd.pipeline", "perspective": "cicd", "severity": "high",
                   "title": "A CI pipeline is defined", "summary": "no pipeline definition found",
                   "suggestion": "Add a pipeline.", "evidence": ["none of the known files"]}
        said = agent_bridge.finding_said(finding)
        self.assertEqual(said, "F-1 (high, cicd): A CI pipeline is defined: no pipeline definition found (evidence: "
                               "none of the known files). Suggested: Add a pipeline.")
        lines = agent_bridge.insight_lines({"health": {"at_risk": "0", "failures": "1"},
                                            "usage": {"tokens": "not measured"}})
        self.assertEqual(lines, ["- health: at risk 0, failures 1"])            # a lens with nothing measured: out
        out = agent_bridge.render(dict(b, findings=[said], insights={"health": {"at_risk": "0"}}))
        self.assertNotIn("{'", out)
        card = Canon(self.p).card("change", "Switch modes reliably", body="The switch script keeps its mode.")["id"]
        with_change = agent_bridge.brief(self.p, change=card)
        self.assertEqual(with_change["goal"], b["goal"])                        # the change is its own section
        self.assertIn(f"## The change {card}", agent_bridge.render(with_change))

    def test_FR_RPJ1_AC_18_asking_how_to_work_in_a_terminal_gives_this_projects_commands(self):
        pid = self.p.pid
        for q in ("how do I work on this in my terminal?", "How can I work on it locally?"):
            out = kassistant.ask(self.factory, q, persona="developer", project_id=pid, person="Aino Tester")
            self.assertIn(f"rihmasto workspace open {pid} --person \"Aino Tester\" --persona developer --agent shell",
                          out["answer"], q)
            self.assertIn(f"rihmasto workspace submit {pid}", out["answer"])
            self.assertIn(f"rihmasto shell {pid}", out["answer"])
            self.assertIn("Open a terminal here", out["answer"])
            self.assertEqual(out["navigate"], {"route": f"#/p/{pid}/console", "control": "console_terminal"})
        where = kassistant.ask(self.factory, "where is the ledger?", persona="developer", project_id=pid)
        self.assertNotIn("workspace open", where["answer"])                     # a where-question stays the map's

    def test_FR_RPJ1_AC_19_a_change_to_the_project_itself_gets_goal_help(self):
        goal = "I want to make the switch script change modes reliably and add a smoke test for it"
        self.assertEqual(copilot.intents(goal), ["develop"])
        self.assertTrue(copilot.asks_goal(goal))
        out = kassistant.ask(self.factory, goal, persona="developer", project_id=self.p.pid, person="Aino Tester")
        self.assertEqual(out["by"], "goal")
        titles = [s["title"] for s in out["plan"]["steps"]]
        self.assertEqual(titles[:6], ["Draft a change request", "See what its repository already says",
                                      "Build it in a branch of your own", "Run its tests as a Health check",
                                      "Send your commits through the gate", "Run its tests in the Console"])
        branch = out["plan"]["steps"][2]["action"]["command"]
        self.assertIn('--person "Aino Tester" --persona developer', branch)       # the person asking, not "..."
        self.assertNotIn("--person ...", str(out["plan"]["steps"]))
        self.assertIn("Hand it to a coding agent", titles)
        draft = out["plan"]["steps"][0]["action"]
        self.assertIn("How will you know it works", draft["text"])
        self.assertEqual(draft["hint"], "change_request")                      # filed as a change, not a question
        from kernel.change import heuristic_class
        self.assertEqual(heuristic_class("developer", draft["text"], draft["hint"]), "change_request")
        goal_js = (ROOT / "cockpit" / "static" / "goal.js").read_text(encoding="utf-8")
        self.assertIn("openDraftChange(pid, a.text, a.hint)", goal_js)
        connect = kassistant.ask(self.factory, "I want to connect it to SharePoint", persona="developer",
                                 project_id=self.p.pid)
        self.assertEqual(connect["plan"]["steps"][0]["action"]["hint"], "new_requirement")
        self.assertEqual(copilot.intents("make the gate trend bigger and show it as a table, compact"), [])
        self.assertEqual(copilot.intents("deploy it to production and fix the logging"), ["cloud"])   # kept
        self.assertNotIn("test_env", copilot.intents("add a smoke test for the qa panel"))
        self.assertIn("test_env", copilot.intents("deploy it to qa first"))


class PlugInAgainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rpj-again-")).resolve()
        allow_roots(self, self.tmp)
        self.factory = Factory(self.tmp / "home")
        self.src = toolbox(self.tmp / "toolbox")
        self.p = adopt.adopt(self.factory, "Toolbox", source=str(self.src), intent="improve", person=PERSON[0],
                             persona=PERSON[1], suite_timeout=5, maturity="explore")

    def reply(self, w, **kw):
        return wk.reply(self.factory, w["id"], person=PERSON[0], persona=PERSON[1], **kw)

    def test_FR_RPJ1_AC_20_the_walkthrough_says_a_folder_is_adopted_already(self):
        w = wk.start(self.factory, "plug_in", person=PERSON[0], persona=PERSON[1])
        w = self.reply(w, text=str(self.src))
        self.assertEqual(w["step"], "seen")
        last = [m for m in w["messages"] if m["from"] == "rihma"][-1]
        self.assertIn(f"Already adopted as Toolbox ({self.p.pid})", last["text"])
        self.assertEqual([o["id"] for o in last["options"]][:3], ["open", "again", "another"])
        self.assertEqual(last["links"][0], {"label": "Open Toolbox", "route": f"#/p/{self.p.pid}/overview"})
        w = self.reply(w, choice="again")
        self.assertEqual(w["step"], "title")
        for said in ({"choice": "default"}, {"choice": "no"}, {"choice": "improve"}, {"choice": "none"}):
            w = self.reply(w, **said)
        prop = wk.proposal(w)
        self.assertTrue(prop["args"]["again"])                                    # the adopt route's explicit again
        self.assertTrue(any(line.startswith("Adopted already as Toolbox") for line in prop["lines"]))
        fresh = self.tmp / "other"
        toolbox(fresh)
        wk.cancel(self.factory, w["id"], person=PERSON[0], persona=PERSON[1])
        w2 = wk.start(self.factory, "plug_in", person=PERSON[0], persona=PERSON[1])
        self.assertEqual(self.reply(w2, text=str(fresh))["step"], "title")       # a new folder: no detour
        wk.cancel(self.factory, w2["id"], person=PERSON[0], persona=PERSON[1])
        again = wk.start(self.factory, "plug_in", person=PERSON[0], persona=PERSON[1])
        again = self.reply(again, text=str(self.src))
        self.assertEqual(self.reply(again, choice="another")["step"], "source")


class ServiceUnitsTest(unittest.TestCase):
    def test_FR_RPJ1_AC_9_service_units_without_a_manifest_point_to_knowledge_or_tooling(self):
        from kernel.profiles_shapes import file_hints

        files = ["README.md", "serve/box/sync.service", "serve/box/sync.timer", "serve/box/sync.py", "tools/run.ps1"]
        hints = file_hints(files)
        self.assertEqual([(h["profile"], h["words"]) for h in hints], [("knowledge_tooling", ["toolbox", "local service"])])
        self.assertIn("service units of its own (serve/box/sync.service", hints[0]["why"])
        self.assertEqual(file_hints([*files, "pyproject.toml"]), [])             # a package that ships: not a toolbox
        vault = file_hints([*files, *(f"notes/n{i}.md" for i in range(6))])
        self.assertEqual([h["profile"] for h in vault], ["knowledge_tooling"])    # said once


class DiagramTest(unittest.TestCase):
    def test_FR_RPJ1_AC_22_an_svg_diagram_page_is_read_by_its_labels(self):
        from kernel import material

        root = Path(tempfile.mkdtemp(prefix="rpj-svg-")).resolve()
        fx._write(root, {"README.md": "# Drawings\n\nTwo diagrams.\n", "diagram.html": (
            "<!doctype html><html><head><title>Flow</title><style>body{margin:0}</style></head><body>"
            "<svg viewBox='0 0 10 10'><title>Two boxes</title><style>.a{fill:red}</style><rect class='a'/>"
            "<text x='1'>Planner <tspan>on the desk</tspan></text><text>Checker</text>"
            "<script>alert(1)</script></svg></body></html>")})
        mp, text, _ = material.gather(root)
        row = next(r for r in mp["files"] if r["path"] == "diagram.html")
        self.assertIn(row["action"], ("read", "summarised"))
        self.assertIn("Two boxes\nPlanner on the desk\nChecker", text)
        for hidden in ("fill:red", "alert(1)", "viewBox"):
            self.assertNotIn(hidden, text)


class PageWordingTest(unittest.TestCase):
    def test_FR_RPJ1_AC_21_the_page_says_why_a_baseline_is_not_measured_and_alignment_says_what_would_appear(self):
        adopted = (ROOT / "cockpit" / "static" / "adopted.js").read_text(encoding="utf-8")
        self.assertIn("function unmeasured(p)", adopted)
        self.assertIn("unmeasured(p)))", adopted)                                 # in How it is held's baseline
        self.assertIn('"data-control": "baseline_how"', adopted)
        self.assertIn("as a Test suite check in ", adopted)
        align = (ROOT / "cockpit" / "static" / "alignment.js").read_text(encoding="utf-8")
        self.assertIn("if (!a.groups.some((g) => g.items.length)) { out.append(nothingYet(pid, a)); return out; }", align)
        self.assertIn("Nothing to align yet.", align)
        self.assertIn('h("a", { href: link(pid, "changes") }, "Changes")', align)


if __name__ == "__main__":
    unittest.main()
