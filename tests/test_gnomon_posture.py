"""Each project's Gnomon posture, computed from its own Gnomon files (FR-GNP1).

Every project here is attached to a temporary folder holding `.gnomon` files written for the test
(tests/gnomon_posture_fakes.py). Nothing outside the folders is read and no network is used.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_epics  # noqa: E402  (its command-line helper; a module, so its own tests do not run here)
from factory_fakes import FactoryTestCase  # noqa: E402
from gnomon_posture_fakes import STRONG, WEAK, project  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_devboard import tree  # noqa: E402

from kernel import assistant  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.gnomon_posture.ask import asks  # noqa: E402
from kernel.gnomon_posture.read import read  # noqa: E402
from kernel.gnomon_posture.score import CHECKS, DIMENSIONS  # noqa: E402
from kernel.gnomon_posture.view import build, propose  # noqa: E402

DEV = "Dana Example"


class PostureCase(FactoryTestCase):
    cli = test_epics.EpicsCase.cli                              # main([--home, ...]) with its output caught

    def weak(self):
        return project(self.factory, self.tmp, WEAK, folder="weak")


class ReadTest(PostureCase):
    def test_FR_GNP1_AC_1_only_the_projects_own_gnomon_files_are_read_and_nothing_is_written(self):
        p = self.weak()
        folder = self.tmp / "weak"
        (folder / ".gnomon" / "roles.toml").write_text("this is not read = [", encoding="utf-8")
        (folder / "secret.env").write_text("TOKEN=x\n", encoding="utf-8")
        before = tree(folder)
        got = read(p)
        self.assertEqual((got["found"], got["source"], sorted(got["files"])), (True, "folder",
                                                                              ["config.toml", "policy.toml"]))
        self.assertEqual(tree(folder), before)                          # nothing written in the working copy
        home_before = tree(self.factory.home)
        build(self.factory, p)
        self.assertEqual(tree(self.factory.home), home_before)          # reading keeps nothing either
        self.assertEqual(got["problems"], [])                           # roles.toml was never opened
        if shutil.which("git"):                                         # no working copy: Rihmasto's repository copy
            bare = p.path("repo.git")
            subprocess.run(["git", "init", "-q", "-b", "main", str(folder)], check=True)
            subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "add", ".gnomon"], check=True)
            subprocess.run(["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "commit", "-qm", "gnomon"], check=True)
            subprocess.run(["git", "clone", "-q", "--bare", str(folder), str(bare)], check=True)
            p.update_meta(attached={"repo": str(self.tmp / "gone")})
            via = read(p)
            self.assertEqual((via["found"], via["source"]), (True, "repository"))
            self.assertEqual(via["files"]["policy.toml"]["verify"]["command"], "python -m pytest -q")


class ScoreTest(PostureCase):
    def test_FR_GNP1_AC_2_six_dimensions_from_documented_settings_the_weakest_first(self):
        self.assertEqual([m for _, _, m in DIMENSIONS], [20, 20, 20, 15, 15, 10])
        for dim, _, most in DIMENSIONS:
            self.assertEqual(sum(c[2] for c in CHECKS if c[1] == dim), most, dim)
        v = build(self.factory, self.weak())
        self.assertTrue(v["measured"])
        self.assertEqual(v["max"], 100)
        pcts = [d["pct"] for d in v["dimensions"]]
        self.assertEqual(pcts, sorted(pcts))
        self.assertEqual(len(v["dimensions"]), 6)
        self.assertIn("checks", v["dimensions"][0])
        self.assertIn("the working copy at", v["said"])
        self.assertEqual(v["read"], ["config.toml", "policy.toml"])
        strong = build(self.factory, project(self.factory, self.tmp, STRONG, ("skills", "trials"), folder="strong"))
        self.assertEqual((strong["total"], strong["weakest"], strong["suggestions"]), (100, [], []))
        empty_tables = project(self.factory, self.tmp,
                               {"config.toml": "[audit.anchor]\n[context]\n[resilience]\n",
                                "policy.toml": "[approval]\n"}, folder="empty-tables")
        self.assertEqual(build(self.factory, empty_tables)["total"], 2)    # only the absent-legacy check holds
        broken = project(self.factory, self.tmp, {"policy.toml": "[verify\ncommand = 1"}, folder="broken")
        b = build(self.factory, broken)
        self.assertTrue(any("not TOML" in x for x in b["problems"]))


class NotMeasuredTest(PostureCase):
    def test_FR_GNP1_AC_3_not_measured_with_why_and_gnomon_init_first_never_a_zero(self):
        bare = build(self.factory, project(self.factory, self.tmp, None, folder="plain"))
        self.assertFalse(bare["measured"])
        self.assertNotIn("total", bare)
        self.assertIn("Gnomon is not set up", bare["why"])
        self.assertEqual(bare["suggestions"][0]["id"], "GP-init")
        self.assertIn("gnomon init", bare["suggestions"][0]["setting"])
        built = build(self.factory, self.factory.new_project("Built here"))
        self.assertFalse(built["measured"])
        self.assertIn("no local working copy", built["why"])
        self.assertEqual(built["suggestions"], [])
        plain = project(self.factory, self.tmp, None, folder="plain-init")
        first = propose(self.factory, plain, "GP-init", person=DEV, persona="developer")
        second = propose(self.factory, plain, "GP-init", person=DEV, persona="developer")
        self.assertEqual((first["already"], second["already"], second["card"]["id"]),
                         (False, True, first["card"]["id"]))
        self.assertEqual(build(self.factory, plain)["suggestions"][0]["card"], first["card"]["id"])
        if shutil.which("git"):
            from kernel import adopt

            src = self.tmp / "adopted-no-gnomon"
            src.mkdir()
            (src / "app.py").write_text("def ok():\n    return True\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
            subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "add", "."], check=True)
            subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "commit", "-qm", "init"], check=True)
            ap = adopt.adopt(self.factory, "Adopted Plain", source=str(src), intent="maintain",
                             person=DEV, persona="developer")
            self.assertFalse(build(self.factory, ap)["measured"])
            shutil.rmtree(src, ignore_errors=True)
            self.assertFalse(build(self.factory, ap)["measured"])


class SuggestionTest(PostureCase):
    def test_FR_GNP1_AC_4_the_exact_setting_in_the_projects_own_file_high_first(self):
        v = build(self.factory, self.weak())
        sev = [s["severity"] for s in v["suggestions"]]
        self.assertEqual(sev, sorted(sev, key={"high": 0, "medium": 1, "low": 2}.get))
        first = v["suggestions"][0]
        self.assertEqual((first["id"], first["setting"], first["file"]), ("GP-sandbox-exec", '[sandbox] exec = "os"',
                                                                           ".gnomon/policy.toml"))
        self.assertEqual(first["where"], str(self.tmp / "weak" / ".gnomon" / "policy.toml"))
        by_id = {s["id"]: s for s in v["suggestions"]}
        self.assertTrue(by_id["GP-governance"]["partly"])               # observe: governed in part
        self.assertIn("GP-legacy", by_id)                               # the old [sandbox] level key
        self.assertNotIn("GP-verify-command", by_id)                    # a verify command is declared
        self.assertNotIn("GP-audit-enabled", by_id)


class ProposeTest(PostureCase):
    def test_FR_GNP1_AC_5_one_signed_change_card_per_suggestion_nothing_applied(self):
        p = self.weak()
        folder = self.tmp / "weak"
        for person, persona in ((DEV, "business_owner"), ("system", "developer")):
            with self.assertRaises(DecisionRefused):
                propose(self.factory, p, "GP-sandbox-exec", person=person, persona=persona)
        with self.assertRaises(KeyError):
            propose(self.factory, p, "GP-verify-command", person=DEV, persona="developer")   # it already holds
        before = tree(folder)
        out = propose(self.factory, p, "GP-sandbox-exec", person=DEV, persona="developer")
        body = json.dumps(out["card"])
        self.assertFalse(out["already"])
        for words in ('[sandbox] exec = \\"os\\"', "Rihmasto applied nothing", "stays the owner's act"):
            self.assertIn(words, body)
        self.assertEqual(tree(folder), before)                          # no .gnomon file written
        again = propose(self.factory, p, "GP-sandbox-exec", person=DEV, persona="it")
        self.assertEqual((again["already"], again["card"]["id"]), (True, out["card"]["id"]))
        self.assertEqual(build(self.factory, p)["suggestions"][0]["card"], out["card"]["id"])
        filed = [r for r in p.ledger().records() if r["event"]["kind"] == "gnomon_posture_filed"]
        self.assertEqual([r["event"]["payload"]["person"] for r in filed], [DEV])


class AskAndCliTest(PostureCase):
    def test_FR_GNP1_AC_6_ask_rihma_and_the_command_line_answer_from_the_projects_files(self):
        for q in ("How well is Gnomon governing this project?", "What should I tighten first?",
                  "what is the gnomon  score here"):
            self.assertTrue(asks(q), q)
        self.assertFalse(asks("what should IT check for this project?"))
        p = self.weak()
        out = assistant.ask(self.factory, "What should I tighten first?", persona="developer", project_id=p.pid,
                            model=None)
        self.assertIn("/100", out["answer"])
        self.assertIn('[sandbox] exec = "os"', out["answer"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{p.pid}/gnomon_posture")
        self.assertEqual(out["matches"], ["gnomon_posture"])
        plain = project(self.factory, self.tmp, None, folder="plain")
        out = assistant.ask(self.factory, "How well is Gnomon governing this project?", persona="developer",
                            project_id=plain.pid, model=None)
        self.assertIn("not measured", out["answer"])
        self.assertIn("gnomon init", out["answer"])
        code, text, err = self.cli("gnomon-posture", "show", p.pid)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(text)["suggestions"][0]["id"], "GP-sandbox-exec")
        code, text, err = self.cli("gnomon-posture", "propose", p.pid, "GP-sandbox-exec", "--person", DEV,
                                   "--persona", "developer")
        self.assertEqual(code, 0, err)
        code, _, err = self.cli("gnomon-posture", "propose", p.pid, "GP-audit-chain", "--person", DEV,
                                "--persona", "business_owner")
        self.assertEqual(code, 2)
        self.assertIn("a developer or IT does", err)


class RoutesTest(CockpitTestCase):
    def test_FR_GNP1_AC_6_the_cockpit_reads_the_posture_and_files_a_suggestion_signed(self):
        p = project(self.factory, self.tmp, WEAK, folder="weak")
        status, out, _ = self.call("GET", f"/api/projects/{p.pid}/gnomon-posture?persona=developer")
        self.assertEqual((status, out["measured"]), (200, True))
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/gnomon-posture/propose",
                                   {"suggestion": "GP-sandbox-exec", "person": DEV, "persona": "developer"})
        self.assertEqual(status, 200, out)
        self.assertTrue(out["card"]["id"])


if __name__ == "__main__":
    unittest.main()
