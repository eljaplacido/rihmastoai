"""FR-RPJ1: working on a real project once it is adopted (kernel side).

The neutral game-like repository of tests/rpj_fixture.py, adopted: its Console, Ask Rihma's how-to, goal help and
the hand-off brief use the commands its own instructions state (AC-17); and the rules a large repository needs:
areas split in a monorepo, folders set aside, bookkeeping lines, LFS and long paths, commits that never write
the tree out (AC-18). Each test names the criterion it holds.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rpj_fixture as fx

from kernel import adopt, agent_bridge, areas, console, copilot, git_clone
from kernel import compile as kcompile
from kernel.agent_context_use import stated_commands
from kernel.assistant import from_map
from kernel.repo_specs import _first_line
from kernel.repo_structure import archived, roles
from kernel.store import Factory

PERSON = ("Aino Tester", "developer")
STATED = "python tools/pipeline/check.py test"


class WorkOnAdoptedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rpj-game-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.src = fx.game(cls.tmp / "isles")
        cls.game = adopt.adopt(cls.factory, "Isles", source=str(cls.src), intent="improve", person=PERSON[0],
                               persona=PERSON[1], suite_timeout=120)

    def test_FR_RPJ1_AC_17_the_console_offers_the_commands_its_instructions_state(self):
        offers = {o["line"]: o for o in console.offered(self.game)}
        self.assertIn(STATED, offers)
        self.assertIn("stated in CLAUDE.md (line", offers[STATED]["source"])

    def test_FR_RPJ1_AC_17_how_to_work_in_my_terminal_is_practical(self):
        got = from_map("how do I work on this in my terminal?", self.game)
        pid = self.game.pid
        self.assertIn(f"rihmasto workspace open {pid}", got["answer"])
        self.assertIn(f"rihmasto workspace submit {pid}", got["answer"])
        self.assertIn(STATED, got["answer"])
        self.assertIn(f"rihmasto ide {pid}", got["answer"])
        self.assertEqual(got["navigate"], {"route": f"#/p/{pid}/console", "control": "console_terminal"})
        self.assertNotIn("workspace open", from_map("how is it doing?", self.game)["answer"])

    def test_FR_RPJ1_AC_17_goal_help_for_a_change_to_the_work_itself(self):
        plan = copilot.rule_plan(self.factory, self.game, "I want the harbour level to load faster")
        titles = [s["title"] for s in plan["steps"]]
        self.assertIn("Build it in a branch of your own", titles)
        self.assertIn("Run its tests in the Console", titles)
        branch = next(s for s in plan["steps"] if s["title"] == "Build it in a branch of your own")
        self.assertIn(f"rihmasto workspace open {self.game.pid}", branch["action"]["command"])

    def test_FR_RPJ1_AC_17_the_brief_follows_the_projects_own_instructions(self):
        text = agent_bridge.render(agent_bridge.brief(self.game))
        self.assertIn("Follow the project's own instructions: `CLAUDE.md`", text)
        self.assertIn(STATED, text)

    def test_FR_RPJ1_AC_17_a_command_is_named_by_its_own_words_first(self):
        text = ("# Harness\n\nRun `python tools/agents/sync_harness.py` and check the diff.\n\n"
                "## Tests\n\n```\npython tools/pipeline/check.py test\n```\n")
        kinds = {s["command"]: s["kind"] for s in stated_commands([{"path": "AGENTS.md", "text": text}])}
        self.assertEqual(kinds, {"python tools/agents/sync_harness.py": "build", STATED: "test"})

    def test_FR_RPJ1_AC_4_plug_in_says_the_folder_is_adopted_already(self):
        from kernel import walkthrough as wk

        w = wk.start(self.factory, "plug_in", person=PERSON[0], persona=PERSON[1], said=str(self.src), replace=True)
        self.assertEqual(w["step"], "seen")
        said = w["messages"][-1]
        self.assertIn(f"Already adopted as Isles ({self.game.pid})", said["text"])
        self.assertEqual(said["links"][0]["route"], f"#/p/{self.game.pid}/overview")
        w = wk.reply(self.factory, w["id"], person=PERSON[0], persona=PERSON[1], choice="again")
        self.assertEqual((w["step"], w["data"]["again"]), ("title", True))
        wk.cancel(self.factory, w["id"], person=PERSON[0], persona=PERSON[1])

    def test_FR_RPJ1_AC_18_the_kernels_commit_never_writes_the_tree_out(self):
        contract = dict(self.game.read("contract.json"))
        contract["revision"] = "sha256:" + "a" * 64
        with mock.patch.object(kcompile, "_git", wraps=kcompile._git) as spy:
            head = kcompile.update_repo_contract(self.game, contract)
        clone = next(c.args for c in spy.call_args_list if "clone" in c.args)
        self.assertIn("--no-checkout", clone)
        bare = self.game.path("repo.git")
        listed = subprocess.run(["git", "ls-tree", "-r", "--name-only", head], cwd=bare, capture_output=True,
                                text=True, check=True).stdout.split()
        self.assertLessEqual({"contract.json", "assets/models/boat.glb", "lore/history.md", "project.godot"},
                             set(listed))


class AllowedFolderWalkthroughTest(unittest.TestCase):
    def test_FR_RPJ1_AC_8_the_walkthrough_reads_a_folder_allowed_in_settings(self):
        from kernel import source_guard
        from kernel import walkthrough as wk
        from kernel import walkthrough_flows as wf

        tmp = Path(tempfile.mkdtemp(prefix="rpj-allow-")).resolve()
        factory = Factory(tmp / "home")
        outside = fx.repo(tmp / "dev" / "isles", {"README.md": "# Isles\n\nA small game.\n"})
        ctx = wk.Ctx(factory, {"step": "folder"}, PERSON[0], PERSON[1], None)
        with mock.patch("pathlib.Path.home", return_value=tmp / "me"), \
                mock.patch.dict(os.environ, {source_guard.ROOTS_ENV: ""}):
            self.assertIsNone(wf.scan_folder(ctx, str(outside)))
            self.assertIn("Settings > Folders the cockpit may read", ctx.w["messages"][-1]["text"])
            source_guard.allow(factory.home, str(outside.parent), person=PERSON[0], persona=PERSON[1],
                               enforced=False, confirmed=True)
            self.assertEqual(wf.scan_folder(ctx, str(outside)), outside)       # no restart, no environment


class LargeRepositoryRulesTest(unittest.TestCase):
    def test_FR_RPJ1_AC_18_the_dominant_folder_of_a_monorepo_is_split_into_areas(self):
        paths = [f"apps/game/assets/t{n}.png" for n in range(100)] + [f"apps/game/scripts/s{n}.gd" for n in range(100)]
        paths += ["apps/game/project.godot", "apps/site/index.html", "docs/plan.md", "README.md"]
        split = areas.splits(paths)
        self.assertEqual(split, frozenset({"apps", "apps/game"}))
        self.assertEqual(areas._area("apps/game/assets/t1.png", split), "apps/game/assets")
        self.assertEqual(areas._area("apps/game/project.godot", split), "apps/game")
        self.assertEqual(areas._area("apps/site/index.html", split), "apps/site")
        self.assertEqual(areas._area("docs/plan.md", split), "docs")
        self.assertEqual(areas.splits(paths[:50]), frozenset())          # a small repository keeps its top folders

    def test_FR_RPJ1_AC_18_lore_first_and_no_tools_dot_folders_in_the_document_index(self):
        root = fx.repo(Path(tempfile.mkdtemp(prefix="rpj-docs-")) / "r", {
            "docs/design/combat.md": "# Combat\n", "lore/sagas.md": "# **The sagas**\n",
            ".claude/agents/lore-keeper.md": "# Lore keeper\n", "world/inputs.md": "# Inputs\n",
            "docs/inputs.md": "# Inputs\n"})
        paths = fx.git(root, "ls-files").split()
        docs = areas.documents(root, "HEAD", paths)
        titles = [d["title"] for d in docs]
        self.assertEqual(titles[0], "The sagas")
        self.assertNotIn("Lore keeper", titles)
        self.assertLessEqual({"Inputs (world)", "Inputs (docs)"}, set(titles))

    def test_FR_RPJ1_AC_18_a_folder_set_aside_gives_nothing_to_the_structure_map(self):
        self.assertTrue(archived("archive/old/tests/test_old.py"))
        self.assertEqual(roles("archive/old/tests/test_old.py"), set())
        self.assertEqual(roles("docs/_attic/spec.md"), set())
        self.assertTrue(roles("tests/test_world.py"))
        self.assertFalse(archived("src/archive.py"))

    def test_FR_RPJ1_AC_18_a_bookkeeping_line_is_never_a_statement(self):
        lines = ["## Story 3: Hearth", "**Priority**: High", "Status: Draft", "", "The player kindles a hearth."]
        self.assertEqual(_first_line(lines, "fallback"), "The player kindles a hearth.")

    def test_FR_RPJ1_AC_18_clones_keep_lfs_pointers_and_long_paths(self):
        with mock.patch.object(git_clone, "_LFS_CONFIGURED", [True]):
            opts = git_clone.clone_options()
        self.assertIn("filter.lfs.process=git-lfs filter-process --skip", opts)
        self.assertIn("filter.lfs.smudge=git-lfs smudge --skip -- %f", opts)
        self.assertEqual(("core.longpaths=true" in opts), os.name == "nt")
        with mock.patch.object(git_clone, "_LFS_CONFIGURED", [False]):
            self.assertFalse(any("lfs" in o for o in git_clone.clone_options()))


if __name__ == "__main__":
    unittest.main()
