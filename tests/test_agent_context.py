"""FR-AGC1: Rihmasto understands how a project's AI coding tools are set up, and uses it.

A team that works in Claude Code, Cursor and the rest leaves its conventions in the repository: CLAUDE.md,
AGENTS.md, Cursor rules, skills, subagents, slash commands, hooks and MCP servers. These tests build such a
folder (tests/agent_context_fixture.py) and check that the scan recognises every file with its frontmatter and
ranks the conventions right after the README; that intake's and the assessment's panels are told them; that
adoption's baseline runs the test command the team states; that a builder cell's envelope carries the rules
that apply to the files it may write; and that `rihmasto ide` prints ready-to-paste MCP configuration and the
section a person pastes into their own AGENTS.md, writing nothing. Nothing found is ever run.
"""

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_context_fixture as fx  # noqa: E402
from factory_fakes import FactoryTestCase, model  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agent_context as ac  # noqa: E402
from kernel import material  # noqa: E402
from kernel.adopt import adopt, detect_tests  # noqa: E402
from kernel.agent_context_use import builder_lines, for_builder, runnable  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.dispatch import envelope  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import _git  # noqa: E402

PERSONAL = ("personal-value", "personal-only", "personal notes")
NEVER_SHOWN = ("postgres://desk@db/loans", "${LOANS_PASSWORD}", "LOANS_PASSWORD", "X-Team", "team=desk",
               "never_run.py", "ruff format", "tickets-mcp", "$DESK_TOKEN", "LOAN_DESK_MODE")


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.relative_to(root).parts}


class RecognitionTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.folder = fx.build(self.tmp / "desk")

    def never_shown(self, shown: str) -> None:
        for word in PERSONAL + NEVER_SHOWN:
            self.assertNotIn(word, shown, word)

    def test_FR_AGC1_AC_1_every_ai_tool_file_is_recognised_with_its_frontmatter_and_nothing_found_is_run(self):
        mp, text, _ = material.gather(self.folder)
        rows = {r["path"]: r for r in mp["files"]}
        self.assertEqual({p: r.get("sub") for p, r in rows.items() if r["kind"] == ac.KIND}, {
            "CLAUDE.md": "instructions", "AGENTS.md": "instructions", "GEMINI.md": "instructions",
            "web/CLAUDE.md": "instructions", ".cursorrules": "instructions", ".windsurfrules": "instructions",
            ".clinerules": "instructions", ".cursor/rules/python.mdc": "instructions",
            ".cursor/rules/web.mdc": "instructions", ".cursor/rules/always.mdc": "instructions",
            ".cursor/rules/db.mdc": "instructions", ".github/copilot-instructions.md": "instructions",
            ".github/instructions/tests.instructions.md": "instructions",
            ".claude/skills/loan-report/SKILL.md": "skill",
            ".claude/skills/loan-report/scripts/report.py": "skill_file",
            ".claude/skills/loan-report/template.md": "skill_file", ".claude/agents/reviewer.md": "agent",
            ".claude/commands/overdue.md": "command", ".claude/commands/db/migrate.md": "command",
            ".cursor/commands/release.md": "command", ".claude/settings.json": "settings",
            ".claude/settings.local.json": "personal", "CLAUDE.local.md": "personal", ".mcp.json": "mcp",
            ".cursor/mcp.json": "mcp", ".vscode/mcp.json": "mcp"})
        ctx = mp["agent_context"]
        by = {e["path"]: e for g in ac.GROUPS for e in ctx[g]}
        # instructions, with where each applies (Cursor's frontmatter, Copilot's applyTo, a folder's own file)
        self.assertEqual(by[".cursor/rules/python.mdc"]["globs"], ["app/**/*.py", "checks/*.py"])
        self.assertEqual(by[".cursor/rules/python.mdc"]["description"], "Python style for the service")
        self.assertFalse(by[".cursor/rules/python.mdc"]["always_apply"])
        self.assertEqual(by[".cursor/rules/web.mdc"]["globs"], ["web/**/*.ts"])
        self.assertTrue(by[".cursor/rules/always.mdc"]["always_apply"])
        self.assertEqual(by[".cursor/rules/always.mdc"]["applies_to"], "the whole project")
        self.assertEqual(by[".cursor/rules/db.mdc"]["applies_to"],
                         "when relevant: the agent decides by its description")
        self.assertEqual(by[".github/instructions/tests.instructions.md"]["globs"], ["checks/**"])
        self.assertEqual(by["web/CLAUDE.md"]["applies_to"], "the files under web/")
        self.assertEqual(by["CLAUDE.md"]["applies_to"], "the whole project")
        self.assertEqual([by[p]["tool"] for p in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".cursorrules",
                                                  ".windsurfrules", ".clinerules", ".github/copilot-instructions.md")],
                         ["Claude Code", "Codex, Cursor and other agents", "Gemini CLI", "Cursor",
                          "Windsurf", "Cline", "GitHub Copilot"])
        self.assertEqual([e["path"] for e in ctx["instructions"]][:2], ["AGENTS.md", "CLAUDE.md"])
        # a skill with its frontmatter and its bundled files (listed, never read or run); subagents; commands
        skill = by[".claude/skills/loan-report/SKILL.md"]
        self.assertEqual((skill["name"], skill["description"]),
                         ("loan-report", "Builds the weekly overdue report from the loans table."))
        self.assertEqual(sorted(skill["files"]), ["scripts/report.py", "template.md"])
        self.assertEqual(rows[".claude/skills/loan-report/scripts/report.py"]["action"], "listed")
        self.assertEqual((by[".claude/agents/reviewer.md"]["name"], by[".claude/agents/reviewer.md"]["tools"]),
                         ("reviewer", "Read, Grep"))
        self.assertEqual({e["path"]: e["name"] for e in ctx["commands"]},
                         {".claude/commands/overdue.md": "/overdue", ".claude/commands/db/migrate.md": "/db:migrate",
                          ".cursor/commands/release.md": "/release"})
        self.assertEqual(by[".claude/commands/overdue.md"]["description"], "List the overdue loans")
        # hooks and permissions by name; a rule that may hold a secret is not shown; no command, no value
        settings = by[".claude/settings.json"]
        self.assertEqual([(x["event"], x["matchers"], x["hooks"]) for x in settings["hooks"]],
                         [("PreToolUse", ["Bash"], 1), ("PostToolUse", ["Edit|Write"], 1)])
        self.assertEqual(settings["permissions"], {"allow": ["Bash(npm run test:*)", "Read(./docs/**)"], "ask": [],
                                                   "deny": ["Bash(rm -rf:*)"]})
        self.assertEqual((settings["rules_not_shown"], settings["env_names"]), (1, 1))
        # MCP servers: name, transport, the command's name or the URL's host; never arguments, env or headers
        servers = {s["name"]: s for e in ctx["mcp"] for s in e["servers"]}
        self.assertEqual({n: (s["transport"], s.get("command") or s.get("host")) for n, s in servers.items()},
                         {"loans-db": ("stdio", "loans-mcp"), "docs": ("http", "docs.example.com"),
                          "tickets": ("stdio", "npx"), "wiki": ("sse", "wiki.example.org")})
        # personal settings: listed, never read
        self.assertEqual(sorted(e["path"] for e in ctx["personal"]), [".claude/settings.local.json", "CLAUDE.local.md"])
        self.assertEqual(rows[".claude/settings.local.json"]["action"], "skipped")
        self.never_shown(text + json.dumps(mp))
        self.assertIn("hooks/never_run.py", (self.folder / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertFalse((self.folder / "hooks").exists())          # the hook was never run
        self.assertIn(ac.CATALOGUE_NOTE, json.dumps(ctx))
        # the same, read from a commit's objects: nothing checked out, the working tree never looked at
        head = fx.commit(self.folder)
        (self.folder / "CLAUDE.md").write_text("# changed, not committed\n", encoding="utf-8")
        from_git = ac.from_git(self.folder, head)
        self.assertEqual(from_git["counts"], ctx["counts"] | {"personal": 0})     # personal files are not committed
        self.assertEqual(from_git["stated"], ctx["stated"])

    def test_FR_AGC1_AC_1_a_tool_file_whose_text_holds_a_credential_is_skipped_unread(self):
        fx.write(self.folder, ".mcp.json", json.dumps({"mcpServers": {"gh": {"command": "gh-mcp",
                                                                            "env": {"GITHUB_TOKEN": fx.FAKE_TOKEN}}}}))
        mp, text, _ = material.gather(self.folder)
        row = next(r for r in mp["files"] if r["path"] == ".mcp.json")
        self.assertEqual((row["action"], row["kind"], row["sub"]), ("skipped", ac.KIND, "mcp"))
        self.assertTrue(row["why"].startswith("may hold secrets"))
        self.assertIn(".mcp.json", [e["path"] for e in mp["agent_context"]["not_read"]])
        self.assertNotIn(fx.FAKE_TOKEN, text + json.dumps(mp))
        self.assertNotIn("gh-mcp", text + json.dumps(mp))

    def test_FR_AGC1_AC_2_a_big_folder_keeps_the_readme_the_instructions_and_the_skills_within_the_budget(self):
        for n in range(60):
            fx.write(self.folder, f"notes/meeting-{n:02d}.md", f"# Meeting {n}\n\n" + "The team talked. " * 400)
            fx.write(self.folder, f"specs/spec-{n:02d}.md", f"# Spec {n}\n\nIt must work. " + "Detail. " * 600)
        mp, text, _ = material.gather(self.folder)
        rows = {r["path"]: r for r in mp["files"]}
        order = [o["path"] for o in mp["order"]]
        self.assertEqual(order[:3], ["README.md", "AGENTS.md", "CLAUDE.md"])
        for path in ("CLAUDE.md", "AGENTS.md", ".cursor/rules/python.mdc", ".claude/skills/loan-report/SKILL.md",
                     ".claude/agents/reviewer.md", ".claude/commands/overdue.md"):
            self.assertEqual(rows[path]["action"], "read", path)
        self.assertEqual(rows[".mcp.json"]["action"], "summarised")
        first_spec = order.index("specs/spec-00.md")
        self.assertLess(order.index(".claude/skills/loan-report/SKILL.md"), first_spec)
        self.assertLess(order.index("web/CLAUDE.md"), order.index(".claude/settings.json"))
        cut = [r for r in mp["files"] if r["path"].startswith(("notes/", "specs/")) and r["action"] == "listed"]
        self.assertTrue(cut)                                         # the budget was spent, on the rest
        self.assertIn("Dates are stored in UTC.", text)
        self.assertIn("## CLAUDE.md (agent context: project instructions)", text)
        self.assertLessEqual(mp["totals"]["chars"], mp["totals"]["budget"] + 200)

    def test_FR_AGC1_AC_3_the_map_and_the_scan_show_how_ai_tools_here_are_set_up(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), "scan", str(self.folder)])
        self.assertEqual(code, 0)
        said = out.getvalue()
        self.assertIn("How AI tools here are set up:", said)
        for line in ("instructions  CLAUDE.md  [Claude Code; applies to the whole project]",
                     "skill         .claude/skills/loan-report/SKILL.md  [loan-report:",
                     "subagent      .claude/agents/reviewer.md",
                     "command       .claude/commands/overdue.md  [/overdue]",
                     "hooks         .claude/settings.json  [PreToolUse, PostToolUse; 3 permission rule(s)]",
                     "MCP servers   .mcp.json  [loans-db, docs]", "personal      CLAUDE.local.md  [listed, never read]",
                     'stated test   python -m unittest discover -s checks -p "check_*.py"  [CLAUDE.md, line 5]',
                     "stated lint   ruff check .", "stated build  npm run build", ac.CATALOGUE_NOTE):
            self.assertIn(line, said)
        for word in PERSONAL + NEVER_SHOWN:
            self.assertNotIn(word, said, word)
        mp = material.scan(self.folder)
        ctx = mp["agent_context"]
        self.assertEqual(ctx["counts"], {"instructions": 13, "skills": 1, "agents": 1, "commands": 3, "settings": 1,
                                         "mcp": 3, "personal": 2, "not_read": 0})


class UseTest(FactoryTestCase):
    def test_FR_AGC1_AC_4_intake_and_the_assessment_panel_are_told_the_projects_own_conventions(self):
        folder = fx.build(self.tmp / "desk")
        p = self.new(mode="assume")
        m = model()
        intake(p, str(folder), model=m, requested_by="Aino")
        asked = [prompt for _, prompt in m.calls if "perspective on a panel" in prompt]
        self.assertTrue(asked)
        for prompt in asked:
            self.assertIn("The project's own conventions, which its team wrote for their AI coding tools", prompt)
            self.assertIn("AGENTS.md (Codex, Cursor and other agents), CLAUDE.md (Claude Code)", prompt)
            self.assertIn('- stated test command: `python -m unittest discover -s checks -p "check_*.py"` '
                          "(CLAUDE.md, line 5)", prompt)
            self.assertIn("do not ask it again", prompt)
            self.assertIn("Never call the payment service from a request handler.", prompt)   # their text, in it
            self.assertLess(prompt.index("## CLAUDE.md (agent context"), prompt.index("## .claude/skills"))
        # the assessment's panel, from the assessed revision's own files
        from kernel import assess, assess_panel

        files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
        inv = assess._inventory(folder, files)
        self.assertEqual(inv["tests"][0]["basis"].split(":")[0], "stated in CLAUDE.md (line 5)")
        prefix = assess_panel.prefix(inv, [])
        self.assertIn("The project's own conventions", prefix)
        self.assertIn("do not propose it as a finding unless the code breaks it", prefix)
        self.assertIn("stated test command", prefix)

    def test_FR_AGC1_AC_5_the_baseline_runs_the_test_command_the_team_states_and_falls_back_to_detection(self):
        repo = fx.build(self.tmp / "desk")
        fx.commit(repo)
        files = [f for f in subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True,
                                           check=True).stdout.split("\n") if f]
        self.assertEqual(detect_tests(repo, files), [])              # by rule alone: no test command found
        p = adopt(self.factory, "Loan desk", source=str(repo), intent="maintain", person="Aino", persona="developer",
                  which=lambda name: None, suite_timeout=120)
        inv, base = p.read("inventory.json"), p.read("baseline.json")
        self.assertEqual(inv["test_command"]["command"], ["python", "-m", "unittest", "discover", "-s", "checks", "-p",
                                                          "check_*.py"])
        self.assertTrue(inv["test_command"]["basis"].startswith("stated in CLAUDE.md (line 5)"))
        self.assertEqual(inv["stated_tests"]["used"], fx.STATED_TEST)
        self.assertEqual(base["verdict"], "passed", base)
        self.assertEqual(base["runs"][0]["counts"]["passed"], 1)
        self.assertIn("(stated in CLAUDE.md (line 5)", Canon(p).brief)          # the brief names where it is from
        found = p.ledger().of_kind("agent_context_found")[-1]["event"]["payload"]
        self.assertEqual((found["instructions"], found["skills"], found["mcp"]), (13, 1, 3))
        self.assertIn("test: " + fx.STATED_TEST, found["stated"])
        # shell syntax is never run: the command found by rule is the fallback, and the record says why
        other = self.tmp / "other"
        fx.write(other, "CLAUDE.md", "Tests: `make test && rm -rf build`\n")
        fx.write(other, "tests/test_one.py", "import unittest\n\n\nclass One(unittest.TestCase):\n"
                                             "    def test_one(self):\n        self.assertTrue(True)\n")
        fx.commit(other)
        q = adopt(self.factory, "Other", source=str(other), intent="maintain", person="Aino", persona="developer",
                  which=lambda name: None, suite_timeout=120)
        inv = q.read("inventory.json")
        self.assertEqual(inv["test_command"]["runner"], "unittest")
        self.assertEqual(inv["test_command"]["command"][:4], ["python", "-m", "unittest", "discover"])
        self.assertIsNone(inv["stated_tests"]["used"])
        self.assertIn("shell syntax", inv["stated_tests"]["not_used"][0]["not_run"])
        self.assertEqual(q.read("baseline.json")["verdict"], "passed")
        # the runner table: what the kernel runs, and why the rest is not run
        self.assertEqual(runnable("pytest -q tests/unit")["command"], ["python", "-m", "pytest", "-q", "tests/unit"])
        self.assertEqual(runnable("uv run pytest -x")["command"], ["python", "-m", "pytest", "-x"])
        self.assertEqual(runnable("npm run test")["command"], ["npm", "run", "test"])
        self.assertEqual(runnable("cargo test")["command"], ["cargo", "test", "--offline"])
        self.assertEqual(runnable("go test ./...")["command"], ["go", "test", "./..."])
        self.assertIn("not a test runner", runnable("bash scripts/test.sh"))
        self.assertIn("shell syntax", runnable("pytest; curl example.com"))
        self.assertIn("shell syntax", runnable("pytest $(cat args)"))

    def test_FR_AGC1_AC_6_a_builder_cell_gets_the_instructions_that_apply_to_the_files_it_may_write(self):
        repo = fx.build(self.tmp / "desk")
        fx.commit(repo)
        p = adopt(self.factory, "Loan desk", source=str(repo), intent="maintain", person="Aino", persona="developer",
                  which=lambda name: None, suite_timeout=120)
        base = _git(p.path("repo.git"), "rev-parse", "main")
        contract = json.loads(json.dumps(p.read("contract.json")))
        task = contract["tasks"][0]
        task["scope"] = {"write": ["app/loans.py", "checks/check_loans.py"]}
        text = envelope(p, contract, task["id"], base=base)
        section = text[text.index("## The project's own conventions"):text.index("## How the product is built")]
        for said in ("### CLAUDE.md (Claude Code; applies to the whole project)", "Dates are stored in UTC.",
                     "### AGENTS.md", "Loans are never deleted.", "### .cursor/rules/python.mdc",
                     "Type hints on every public function.", "### .cursor/rules/always.mdc", "Write the test first.",
                     "### .github/instructions/tests.instructions.md", "One check per behaviour.",
                     "- .cursor/rules/db.mdc: Database migrations", "the envelope wins",
                     "Never run a hook, an MCP server or a script"):
            self.assertIn(said, section)
        for not_said in ("No inline styles.", "Every page escapes what it shows.", "Migrations are reversible.",
                         "personal notes", "never_run.py"):
            self.assertNotIn(not_said, section)
        self.assertLess(section.index("### AGENTS.md"), section.index("### .cursor/rules/python.mdc"))
        # a task on the web pages gets the web rules, and not the Python ones
        task["scope"] = {"write": ["web/pages/home.ts"]}
        web = envelope(p, contract, task["id"], base=base)
        self.assertIn("No inline styles.", web)
        self.assertIn("Every page escapes what it shows.", web)
        self.assertNotIn("Type hints on every public function.", web)
        self.assertNotIn("One check per behaviour.", web)
        # a scope by glob: the rules whose folder it may touch
        lines = "\n".join(builder_lines(ac.from_git(p.path("repo.git"), base, keep_text=True), ["web/**"]))
        self.assertIn("No inline styles.", lines)
        self.assertNotIn("Type hints on every public function.", lines)
        # a project Rihmasto builds itself has no such section
        self.assertEqual(for_builder(self.new(), base, ["app/loans.py"]), [])


class IdeTest(FactoryTestCase):
    def cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue()

    def test_FR_AGC1_AC_8_rihmasto_ide_prints_mcp_config_how_a_change_comes_back_and_the_section_writing_nothing(self):
        from kernel.attach import attach

        repo = fx.build(self.tmp / "desk")
        head = fx.commit(repo)
        p = attach(self.factory, "Loan desk", repo=repo, person="Aino", persona="developer")
        self.assertEqual(p.read("agent_context.json")["counts"]["skills"], 1)
        self.assertEqual(p.ledger().of_kind("agent_context_found")[-1]["event"]["payload"]["revision"], head)
        repo_before, home_before = tree(repo), tree(self.factory.home)
        code, said = self.cli("ide", p.pid, "--name", "Aino Virtanen")
        self.assertEqual(code, 0)
        server = str(Path(__file__).resolve().parents[1] / "mcp" / "server.py")
        for line in ("How AI tools here are set up:", "Work on it from your IDE",
                     "Claude Code: .mcp.json in your clone", "claude mcp add rihma -- ", "Cursor: .cursor/mcp.json",
                     "Codex: ~/.codex/config.toml",
                     "[mcp_servers.rihma]", f"rihmasto repo gate {p.pid} --head <revision>",
                     "Rihmasto never writes to it", f"rihmasto ide {p.pid} --section"):
            self.assertIn(line, said)
        code, out = self.cli("ide", p.pid, "--name", "Aino Virtanen", "--json")
        view = json.loads(out)
        rihma = view["ide"]["claude_code"]["json"]["mcpServers"]["rihma"]
        self.assertEqual(rihma["type"], "stdio")
        self.assertEqual(rihma["args"][:2], [server, "--home"])
        self.assertEqual(rihma["args"][-4:], ["--person", "Aino Virtanen", "--persona", "developer"])
        self.assertEqual(view["ide"]["cursor"]["json"]["mcpServers"]["rihma"]["args"], rihma["args"])
        self.assertNotIn("type", view["ide"]["cursor"]["json"]["mcpServers"]["rihma"])
        self.assertIn('"Aino Virtanen"', view["ide"]["claude_code"]["command"])
        self.assertTrue(view["context"]["read_from"].startswith("the committed main of "))
        code, section = self.cli("ide", p.pid, "--section")
        self.assertTrue(section.startswith(f"<!-- rihmasto:begin {p.pid} -->\n## Rihmasto's contract and open "
                                           "questions for your IDE agent"))
        self.assertTrue(section.rstrip().endswith(f"<!-- rihmasto:end {p.pid} -->"))
        for said in ("### The contract", "### Waiting on a decision", "### How your change comes back",
                     "rihma_report_change", "Never edit `.gnomon/`"):
            self.assertIn(said, section)
        # nothing was written: not the person's repository, not the factory home
        self.assertEqual(tree(repo), repo_before)
        self.assertEqual(tree(self.factory.home), home_before)
        self.assertFalse((repo / "AGENTS.md").read_text(encoding="utf-8").count("rihmasto:begin"))
        # an adopted project: a workspace's submission comes back through the gate
        q = adopt(self.factory, "Loan desk adopted", source=str(repo), intent="maintain", person="Aino",
                  persona="developer", which=lambda name: None, suite_timeout=120)
        code, said = self.cli("ide", q.pid)
        self.assertIn(f"rihmasto workspace submit {q.pid}", said)
        self.assertIn(f"rihmasto sync {q.pid}", said)
        self.assertIn('"<your name>"', said)
        self.assertIn("(read from main of the product repository)", said)
        # a project Rihmasto builds itself: nothing to read
        code, said = self.cli("ide", self.new().pid)
        self.assertIn("there is no team repository to read", said)

    def test_FR_AGC1_AC_9_skills_and_mcp_servers_are_candidates_only_nothing_is_enabled_or_run(self):
        from kernel.attach import attach
        from kernel.dashboard import catalogue

        repo = fx.build(self.tmp / "desk")
        fx.commit(repo)
        ran = []
        real = subprocess.run

        def watched(argv, *a, **k):     # every program the recognition starts is git, reading objects
            ran.append(list(argv))
            return real(argv, *a, **k)

        p = attach(self.factory, "Loan desk", repo=repo, person="Aino", persona="developer")
        with mock.patch("kernel.agent_context.subprocess.run", side_effect=watched):
            ctx = ac.from_git(Path(p.meta["attached"]["repo"]), "main")
        self.assertTrue(ran)
        self.assertTrue(all(a[0] == "git" and ({"ls-tree", "cat-file"} & set(a)) for a in ran), ran)
        self.assertEqual(ctx["catalogue_note"], ac.CATALOGUE_NOTE)
        self.assertIn("after a person approves", ac.CATALOGUE_NOTE)
        self.assertEqual([s["name"] for s in ctx["skills"]], ["loan-report"])
        self.assertEqual(sorted(s["name"] for e in ctx["mcp"] for s in e["servers"]), ["docs", "loans-db", "tickets",
                                                                                     "wiki"])
        listed = json.dumps(catalogue(self.factory))                 # nothing entered Rihmasto's own catalogue
        for name in ("loan-report", "loans-db", "tickets", "wiki", "reviewer"):
            self.assertNotIn(name, listed)
        self.assertFalse((repo / "hooks").exists())                  # the hook that would make it was never run
        self.assertFalse(any(self.factory.home.rglob("*.mcp.json")))


class ProjectPageTest(CockpitTestCase):
    def test_FR_AGC1_AC_7_the_project_page_reads_its_ai_tools_and_the_ide_card_records_nothing(self):
        from kernel.attach import attach

        repo = fx.build(self.tmp / "desk")
        fx.commit(repo)
        p = attach(self.factory, "Loan desk", repo=repo, person="Aino", persona="developer")
        home = tree(self.factory.home)
        records = len(p.ledger().records())
        status, out, _ = self.call("GET", f"/api/projects/{p.pid}/ai-tools?persona=developer&person=Aino%20Virtanen")
        self.assertEqual(status, 200, out)
        self.assertEqual((out["applies"], out["kind"]), (True, "attached"))
        ctx = out["context"]
        self.assertEqual([e["path"] for e in ctx["instructions"]][:2], ["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(ctx["skills"][0]["files"], ["scripts/report.py", "template.md"])
        self.assertEqual(out["ide"]["signed_as"], {"person": "Aino Virtanen", "persona": "developer"})
        self.assertIn("Rihmasto's contract and open questions for your IDE agent", out["section"])
        self.assertEqual(out["section_file"], f"rihmasto-{p.pid}-agents-section.md")
        for word in PERSONAL + NEVER_SHOWN:
            self.assertNotIn(word, json.dumps(out), word)
        self.assertEqual((tree(self.factory.home), len(p.ledger().records())), (home, records))   # records nothing
        status, out, _ = self.call("GET", f"/api/projects/{self.new().pid}/ai-tools?persona=developer")
        self.assertEqual((status, out["applies"]), (200, False))
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/ai-tools", token=None)[0], 401)


if __name__ == "__main__":
    unittest.main()
