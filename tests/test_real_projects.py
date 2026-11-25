"""FR-RPJ1: real projects of every shape, fed in by rule (kernel side).

Neutral folders shaped like the projects people feed into Rihmasto (tests/rpj_fixture.py): a documents-only
experiment with a results.zip, a repository with uncommitted work, a workspace of several repositories with a
copy, a notes folder, and a game-like repository with assets and lore. Each test names the criterion it holds.
"""

import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rpj_fixture as fx  # noqa: E402

from kernel import adopt, adopt_stated, adopt_watch, adopted_state, material, material_git  # noqa: E402
from kernel import material_zip, profiles, source_guard, status, track  # noqa: E402
from kernel.adopt_seen import adopted_as  # noqa: E402
from kernel.assistant_status import status_answer  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.source_guard import ROOTS_ENV as ROOTS  # noqa: E402
from kernel.profiles_shapes import SHAPES, file_hints  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = ("Aino Tester", "developer")


def rows(mp):
    return {r["path"]: r for r in mp["files"]}


class ScanShapesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rpj-")).resolve()

    def test_FR_RPJ1_AC_1_housekeeping_files_are_listed_and_the_readme_is_read_first_in_full(self):
        root = fx.experiment(self.tmp / "exp")
        for n in range(40):                 # many junk files: the README still comes first, in full
            (root / f"logs-{n}.txt").write_text(f"line {n}\n" * 300, encoding="utf-8")
        mp = material.scan(root, budget=20_000)
        r = rows(mp)
        for junk in (".gitattributes", ".gitignore", ".editorconfig", ".ignore", "data/.gitignore", "SHA256SUMS",
                     ".env.example", "uv.lock"):
            self.assertEqual(r[junk]["action"], "listed", junk)
            self.assertTrue(r[junk].get("housekeeping"), junk)
            self.assertNotIn(junk, [o["path"] for o in mp["order"]])
        self.assertEqual(r["uv.lock"]["why"], "a lockfile: kept by a tool, not read")
        self.assertEqual(mp["totals"]["housekeeping"], 8)
        self.assertEqual(mp["order"][0]["path"], "README.md")
        self.assertEqual((r["README.md"]["action"], r["README.md"]["why"]), ("read", "read in full"))

    def test_FR_RPJ1_AC_2_a_zip_is_read_inside_by_the_same_rules_never_extracted(self):
        root = fx.experiment(self.tmp / "exp")
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        mp, text, _ = material.gather(root)
        r = rows(mp)
        z = "results.zip!/results/"
        self.assertIn("an archive of 7 entries", r["results.zip"]["why"])
        self.assertEqual(r[z + "report.md"]["action"], "read")
        self.assertEqual(r[z + "metrics.csv"]["action"], "summarised")
        self.assertEqual(r[z + ".env"]["action"], "skipped")
        self.assertEqual(r[z + "curve.png"]["why"], "binary: not read")
        self.assertEqual(r[z + "inner.zip"]["why"], "an archive inside an archive: not opened")
        self.assertEqual(r[z + "plot.py"]["why"], "code inside an archive: listed, not read")
        self.assertIn("Run r1 reaches 0.74 accuracy", text)
        self.assertNotIn("MODE=demo", text)
        self.assertFalse(material.has_code(mp))                  # code inside an archive is not the folder's code
        self.assertEqual(sorted(p.relative_to(root).as_posix() for p in root.rglob("*")), before)   # nothing extracted
        (root / "bomb.zip").write_bytes(fx.bomb_zip())          # 40 MB of zeros in a few kilobytes
        r = rows(material.scan(root))
        self.assertIn("zip bomb", r["bomb.zip"]["why"])
        self.assertFalse([p for p in r if p.startswith("bomb.zip!/")])
        infos = [zipfile.ZipInfo("x")]
        infos[0].file_size, infos[0].compress_size = material_zip.MAX_EXPANDED + 1, 10 ** 9
        self.assertIn("would inflate", material_zip.bomb(infos))
        (root / "broken.zip").write_bytes(b"PK\x03\x04 not really")
        self.assertIn("could not be opened", rows(material.scan(root))["broken.zip"]["why"])

    def test_FR_RPJ1_AC_3_the_last_commit_is_scanned_and_uncommitted_work_is_counted(self):
        repo = fx.uncommitted(self.tmp / "ledger")
        self.assertEqual(material_git.working_changes(repo), {"uncommitted": 1, "untracked": 2})
        committed = rows(material.scan(repo, tree=material_git.GitTree(repo)))
        self.assertNotIn("draft.md", committed)
        self.assertNotIn("app/extra.py", committed)
        working = rows(material.scan(repo))
        self.assertIn("draft.md", working)
        mp, text, _ = material.gather(repo, tree=material_git.GitTree(repo))
        self.assertIn(".claude/skills/tidy/SKILL.md", rows(mp))
        self.assertNotIn("A draft not committed", text)

    def test_FR_RPJ1_AC_6_a_workspace_lists_its_repositories_and_reads_a_copy_once(self):
        ws = fx.workspace(self.tmp / "harbour")
        got = material_git.workspace(ws)
        self.assertEqual([r["path"] for r in got["repositories"]], ["harbour-app", "harbour-tools"])
        self.assertEqual(got["copies"], ["harbour-app_snapshot"])
        self.assertTrue(got["several"])
        self.assertEqual(got["repositories"][0]["commits"], 1)
        r = rows(material.scan(ws))
        self.assertEqual(r["harbour-app_snapshot/docs/plan.md"]["why"], "the same text as harbour-app/docs/plan.md: read once")
        self.assertEqual(r["harbour-app/docs/plan.md"]["action"], "read")
        self.assertIsNone(material_git.workspace(ws / "harbour-app"))      # a repository is not a workspace

    def test_FR_RPJ1_AC_7_a_scan_reports_progress_and_stops_when_cancelled(self):
        root = fx.notes(self.tmp / "vault")
        progress = material.Progress()
        material.scan(root, progress=progress)
        view = progress.view()
        self.assertEqual(view["files"], 9)
        self.assertGreaterEqual(view["read"], 9)
        stop = material.Progress()
        stop.cancelled = True
        with self.assertRaises(material.ScanCancelled):
            material.scan(root, progress=stop)

    def test_FR_RPJ1_AC_8_allowed_folders_are_kept_in_the_factory_home_and_system_folders_stay_refused(self):
        home, outside = self.tmp / "home", self.tmp / "dev" / "app"
        outside.mkdir(parents=True)
        logged = []
        log = lambda kind, payload: logged.append((kind, payload))      # noqa: E731
        with mock.patch("pathlib.Path.home", return_value=self.tmp / "me"), mock.patch.dict(os.environ, {ROOTS: ""}):
            with self.assertRaisesRegex(source_guard.SourceRefused, "can be allowed in Settings"):
                source_guard.check_folder(str(outside), "developer", home)
            offer = source_guard.offer(outside, enforced=False, home=home)
            self.assertEqual(offer["who"], "you")
            self.assertTrue(offer["say"].startswith("Allow "))
            self.assertTrue(source_guard.offer(outside, enforced=True, home=home)["say"].startswith("Ask IT to allow"))
            with self.assertRaisesRegex(source_guard.SourceRefused, "say yes"):
                source_guard.allow(home, str(outside.parent), person=PERSON[0], persona=PERSON[1], enforced=False,
                                   confirmed=False)
            with self.assertRaisesRegex(source_guard.SourceRefused, "only IT"):
                source_guard.allow(home, str(outside.parent), person=PERSON[0], persona=PERSON[1], enforced=True,
                                   confirmed=True)
            source_guard.allow(home, str(outside.parent), person=PERSON[0], persona=PERSON[1], enforced=False,
                               confirmed=True, log=log)
            self.assertEqual(source_guard.check_folder(str(outside), "developer", home), outside)   # no restart
            self.assertEqual(logged[0][0], "source_root_allowed")
            (self.tmp / ".ssh").mkdir()
            for bad, why in ((Path(Path.cwd().anchor), "root"), (self.tmp / ".ssh", "keys")):
                with self.assertRaisesRegex(source_guard.SourceRefused, why):
                    source_guard.allow(home, str(bad), person=PERSON[0], persona="it", enforced=True, confirmed=True)
            with self.assertRaises(source_guard.SourceRefused):
                source_guard.allow(home, "C:/Windows" if sys.platform == "win32" else "/etc", person=PERSON[0],
                                   persona="it", enforced=True, confirmed=True)
            source_guard.disallow(home, str(outside.parent), person=PERSON[0], persona=PERSON[1], enforced=False)
            with self.assertRaises(source_guard.SourceRefused):
                source_guard.check_folder(str(outside), "developer", home)

    def test_FR_RPJ1_AC_9_profiles_for_real_shapes_with_focus_questions_and_gates_recognised_by_rule(self):
        for pid in ("game", "ml_experiment", "knowledge_tooling", "library_cli", "data_pipeline"):
            p = profiles.PROFILES[pid]
            self.assertIs(p, SHAPES[pid])
            self.assertTrue(p["panel_focus"] and p["seed_questions"] and p["gates"], pid)
        self.assertEqual(profiles.propose_profile("A Godot game: levels, lore and gameplay")["profile"], "game")
        self.assertEqual(profiles.propose_profile("Fine-tuning a LoRA: training runs, checkpoints and an eval set")
                         ["profile"], "ml_experiment")
        self.assertEqual(profiles.propose_profile("My second brain: an Obsidian vault and a toolbox")["profile"],
                         "knowledge_tooling")
        self.assertEqual(profiles.propose_profile("An Airflow DAG with dbt models and data quality checks")["profile"],
                         "data_pipeline")
        game = [r["path"] for r in material.scan(fx.game(self.tmp / "isles"))["files"]]
        self.assertEqual([h["profile"] for h in file_hints(game)], ["game"])
        notes = [r["path"] for r in material.scan(fx.notes(self.tmp / "vault"))["files"]]
        self.assertEqual([h["profile"] for h in file_hints(notes)], ["knowledge_tooling"])
        exp = [r["path"] for r in material.scan(fx.experiment(self.tmp / "exp"))["files"]]
        self.assertEqual([h["profile"] for h in file_hints(exp)], ["ml_experiment"])
        q = profiles.profile_question(profiles.propose_profile("game"))   # "which kind" offers the new ones
        self.assertIn("Game (game)", q["options"])


class AdoptShapesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rpj-adopt-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.game_src = fx.game(cls.tmp / "isles")
        cls.game = adopt.adopt(cls.factory, "Isles", source=str(cls.game_src), intent="monitor", person=PERSON[0],
                               persona=PERSON[1], suite_timeout=120)

    def test_FR_RPJ1_AC_10_an_adopted_project_shows_its_real_state_not_the_seven_stages(self):
        s = adopted_state.state(self.game)
        self.assertEqual((s["intent"], s["state"], s["took"]), ("monitor", "monitoring", "commit"))
        self.assertTrue(s["line"].startswith("Adopted, monitoring · baseline "))
        self.assertEqual(s["usage"]["said"], "in production")
        self.assertEqual(self.game.meta["profile"], "game")
        self.assertIn("a game engine's files", (self.game.read("adopted.json") or {})["profile"]["from"])

    def test_FR_RPJ1_AC_11_a_failed_baseline_is_a_health_item(self):
        self.assertEqual(adopted_state.state(self.game)["baseline"]["verdict"], "failed")
        h = status.health(self.game)
        self.assertEqual(h["status"], "at_risk")
        self.assertTrue(any(r.startswith("existing tests fail at the baseline (recorded, not judged)")
                            for r in h["reasons"]), h)
        self.assertTrue(any("existing tests fail" in r["why"] for r in track.track(self.game)["reasons"]))

    def test_FR_RPJ1_AC_12_a_stated_command_runs_as_the_baseline_only_with_a_yes(self):
        offers = adopt_stated.offers(self.game)
        self.assertEqual([o["command"] for o in offers], ["python tools/pipeline/check.py test"])
        self.assertIn("runs the project's own code", offers[0]["runs_code"])
        with self.assertRaisesRegex(adopt_stated.StatedRefused, "say yes"):
            adopt_stated.run(self.game, offers[0]["command"], person=PERSON[0], persona=PERSON[1], confirmed=False)
        with self.assertRaisesRegex(adopt_stated.StatedRefused, "as stated"):
            adopt_stated.run(self.game, "python evil.py", person=PERSON[0], persona=PERSON[1], confirmed=True)
        got = adopt_stated.run(self.game, offers[0]["command"], person=PERSON[0], persona=PERSON[1], confirmed=True)
        self.assertEqual((got["verdict"], got["command"], got["stated"]), ("failed", offers[0]["command"], True))
        self.assertEqual(self.game.ledger().of_kind("baseline_stated_run")[-1]["event"]["payload"]["person"], PERSON[0])
        self.assertIn("check.py test", status.failed_baseline(self.game))

    def test_FR_RPJ1_AC_14_areas_inventory_activity_and_lore_index(self):
        got = self.game.read("areas.json")
        by = {a["area"]: a for a in got["areas"]}
        self.assertEqual(by["assets"]["assets"], {"textures": 2, "models": 1, "audio": 1})
        act = got["activity"]
        self.assertTrue(act["measured"])
        week = {m["area"] for m in act["windows"]["7"]}
        self.assertEqual(week, {"assets", "lore"})
        self.assertNotIn("code", {m["area"] for m in act["windows"]["30"]})      # its only commit is 60 days old
        self.assertLessEqual({"Factions of the isles", "The drowned lantern"}, {d["title"] for d in got["documents"]})
        answer = status_answer(self.game, "how are the assets coming along?")
        self.assertIn("assets holds 4 files", answer["answer"])
        self.assertEqual(answer["navigate"]["control"], "project_areas")

    def test_FR_RPJ1_AC_13_a_watch_summarises_new_commits_and_activity(self):
        view = adopt_watch.setup(self.game, person=PERSON[0], persona=PERSON[1])
        self.assertTrue(view["line"].startswith("Watching: new commits -> a summary in Review and the timeline [AU-"))
        self.assertIn("waits for a notification channel", view["line"])
        self.assertEqual(adopted_state.state(self.game)["watch"]["watching"], True)
        fx.commit(self.game_src, {"lore/tides.md": "# Tides\n"}, "Tides")
        fired = adopt_watch.fire(self.game, "commits")
        self.assertEqual(fired["outcome"], "done")
        self.assertTrue(fired["ref"].startswith("C-"))                     # the Review card
        self.assertTrue(self.game.ledger().of_kind("watch_commits"))
        self.assertEqual(adopt_watch.fire(self.game, "areas")["outcome"], "done")

    def test_FR_RPJ1_AC_4_the_same_folder_or_origin_is_known_as_adopted(self):
        self.assertEqual([x["project"] for x in adopted_as(self.factory, self.game_src)], [self.game.pid])
        self.assertEqual(adopted_as(self.factory, self.tmp), [])
        clone = self.tmp / "isles-clone"
        fx.git(self.tmp, "clone", "-q", str(self.game_src), str(clone))
        fx.git(clone, "remote", "set-url", "origin", "https://user:tok@example.invalid/org/isles.git")
        p = adopt.adopt(self.factory, "Isles clone", source=str(clone), intent="improve", person=PERSON[0],
                        persona=PERSON[1], suite_timeout=1)
        self.assertEqual(p.read("adopted.json")["origin"], "https://example.invalid/org/isles")    # no credential
        seen = adopted_as(self.factory, None, "git@example.invalid:org/isles.git")
        self.assertEqual([(x["project"], x["by"]) for x in seen], [(p.pid, "origin")])

    def test_FR_RPJ1_AC_3_adopting_the_working_copy_or_the_last_commit(self):
        src = fx.uncommitted(self.tmp / "ledger")
        p = adopt.adopt(self.factory, "Ledger", source=str(src), intent="maintain", person=PERSON[0],
                        persona=PERSON[1], suite_timeout=1)
        a = p.read("adopted.json")
        self.assertEqual((a["took"], a["left_out"]), ("commit", {"uncommitted": 1, "untracked": 2}))
        self.assertIn("1 uncommitted change(s) and 2 untracked file(s) were left out", Canon(p).brief)
        w = adopt.adopt(self.factory, "Ledger now", source=str(src), intent="maintain", person=PERSON[0],
                        persona=PERSON[1], suite_timeout=1, working_copy=True)
        self.assertEqual(w.read("adopted.json")["took"], "working copy")
        self.assertIn("draft.md", rows(w.read("material.json")))
        self.assertTrue(src.joinpath("draft.md").exists())                   # the person's folder is unchanged

    def test_FR_RPJ1_AC_15_a_documents_folder_is_tracked_and_evaluated(self):
        src = fx.experiment(self.tmp / "buoys")
        with self.assertRaisesRegex(adopt.AdoptionRefused, "no code"):
            adopt.adopt(self.factory, "Buoys", source=str(src), intent="monitor", person=PERSON[0], persona=PERSON[1])
        p = adopt.adopt(self.factory, "Buoys", source=str(src), intent="monitor", person=PERSON[0], persona=PERSON[1],
                        documents=True, maturity="explore")
        s = adopted_state.state(p)
        self.assertEqual((s["state"], s["took"]), ("monitoring", "documents"))
        self.assertEqual(p.meta["profile"], "ml_experiment")
        self.assertEqual(p.meta["stage"], 7)
        self.assertFalse(Canon(p).questions("open"))            # no build questions
        self.assertIn("results.zip!/results/report.md", rows(p.read("material.json")))


class ZipEntryTest(unittest.TestCase):
    def test_FR_RPJ1_AC_2_an_entry_that_inflates_beyond_its_header_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("a.txt", os.urandom(3 * 512 * 1024).hex())         # 3 MB that do not compress
            z.writestr("b.txt", "0" * (200 * 1024))                         # 200 KB of zeros in a few hundred bytes
            z.writestr("c.txt", "fine\n")
        root = Path(tempfile.mkdtemp(prefix="rpj-zip-"))
        (root / "big.zip").write_bytes(buf.getvalue())
        r = rows(material.scan(root))
        self.assertEqual(r["big.zip!/a.txt"]["why"], "too large to read inside the archive (3.0 MB)")
        self.assertEqual(r["big.zip!/b.txt"]["why"], "refused: it inflates far beyond its packed size (a zip bomb)")
        self.assertEqual(r["big.zip!/c.txt"]["action"], "read")


if __name__ == "__main__":
    unittest.main()
