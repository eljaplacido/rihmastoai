"""The owner's four decisions of 2026-11-24 after a journey test ("1. Yes 2. Skip 3. Agreed 4. Ask"), and what
Models setup says of a key Gnomon holds.

1. Yes (FR-CHG1-AC-11): a new kind of work, going back to the questions, withdraws the assumptions the factory
   made on its own, "made for the old kind", and keeps only what a person chose; the preview counts both.
3. Agreed (FR-CHG1-AC-12): at explore and demo a person's project waits once for a go-ahead on its spec before
   the first build: Go or Skip, in What's next and the Inbox; "Build without waiting for me" turns it off; a
   delegation may say Go; pilot keeps the plan's approval; the scripted demo sets it off.
4. Ask (FR-X1-AC-4): an adopted project whose kind is not clear from its files and words asks which kind.
5. FR-MDL1-AC-10: Models setup says "key set by Gnomon" when `gnomon key list` names the key, and never reads it.
(2. Skip is tests/test_confidential_skip.py.) Scripted models only; no network.
"""

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, isolated_routing, model  # noqa: E402
from test_adopt import README, make_repo, python_repo  # noqa: E402
from test_project_change import PO, ChangeCase  # noqa: E402

from kernel import gnomon_keys, go_ahead  # noqa: E402
from kernel import next_step as kn  # noqa: E402
from kernel import project_settings as ks  # noqa: E402
from kernel import rewind as kr  # noqa: E402
from kernel.adopt import adopt  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.delegation import grant  # noqa: E402
from kernel.graph import build as graph  # noqa: E402
from kernel.intake import render_brief  # noqa: E402
from kernel.pipeline import AGAIN, _shape  # noqa: E402
from kernel.profiles import PROFILE_QUESTION  # noqa: E402

STUB = Path(__file__).parent / "fixtures" / "stub_gnomon.py"
CHOSEN = "Is the loan history kept for a year?"


def payloads(project, kind: str) -> list:
    return [r["event"]["payload"] for r in project.ledger().of_kind(kind)]


class KindChangeKeepsWhatAPersonChoseTest(ChangeCase):
    def project(self):
        """Intake in mixed mode: Q-001 is put to a person and answered; the rest the factory assumed on its own;
        one more a person chose to let the factory assume."""
        p = self.intaken()
        canon = Canon(p)
        canon.answer("Q-001", "the team lead approves", **PO)
        q = canon.add_question(CHOSEN, "operations", opinions={"operations": "yes, a year"})
        canon.assume(q["id"], "yes, a year", chosen_by=PO["person"], persona=PO["persona"])
        return p, q["id"]

    def test_FR_CHG1_AC_11_the_preview_counts_what_is_kept_and_what_is_withdrawn(self):
        p, _ = self.project()
        by_factory = [q["id"] for q in kr.factory_assumed(p)]
        self.assertTrue(by_factory)
        seen = ks.preview(p, kind="integration")
        self.assertEqual(seen["questions"], {"kept_answers": 1, "kept_assumptions": 1, "withdrawn_open": 0,
                                             "withdrawn_assumptions": len(by_factory)})
        says = seen["impact"][0]["says"]
        self.assertIn("keeps what a person chose: 1 answer and 1 assumption", says)
        self.assertIn(f"{len(by_factory)} assumptions the factory made on its own, made for the old kind", says)
        self.assertIsNone(ks.preview(p, title="Equipment loans 2")["questions"])

    def test_FR_CHG1_AC_11_the_factory_assumptions_are_withdrawn_and_only_a_persons_choices_reach_the_panel(self):
        p, chosen = self.project()
        by_factory = [q["id"] for q in kr.factory_assumed(p)]
        out = ks.change(p, reason="it connects two systems", kind="integration", redo=True, **PO)
        self.assertEqual(sorted(out["withdrawn_assumptions"]), sorted(by_factory))
        canon = Canon(p)
        for qid in by_factory:
            q = canon.question(qid)
            self.assertEqual((q["status"], q["withdrawn"]["was"]), ("withdrawn", "assumed"))
            self.assertIn("made for the old kind of work (Web app or service)", q["withdrawn"]["why"])
            aid = q["answer"]["assumption"]
            self.assertEqual(next(a for a in canon.assumptions() if a["id"] == aid)["status"], "withdrawn")
        self.assertEqual(canon.question("Q-001")["status"], "answered")             # a person's answer stays
        self.assertEqual(canon.question(chosen)["status"], "assumed")               # a person's choice stays
        settled = {r["id"]: r["status"] for r in payloads(p, "assumption_settled")}
        self.assertEqual(set(settled.values()), {"withdrawn"})
        self.assertEqual(graph(p).parts.problems, [])                               # the records still agree
        m = model()
        self.assertEqual(_shape(p, m, []), AGAIN)                                   # the panel runs again
        panel = [prompt for _, prompt in m.calls if "perspective on a panel" in prompt]
        told = panel[0].split("Already asked and settled (never ask these again):")[1]
        self.assertIn("Who approves a loan?", told)
        self.assertIn(CHOSEN, told)
        self.assertNotIn("How is benefit measured?", told)                         # the factory's, withdrawn
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_CHG1_AC_11_without_going_back_nothing_is_withdrawn(self):
        p, _ = self.project()
        before = [q["id"] for q in kr.factory_assumed(p)]
        out = ks.change(p, reason="it connects two systems", kind="integration", redo=False, **PO)
        self.assertEqual((out["withdrawn_assumptions"], [q["id"] for q in kr.factory_assumed(p)]), ([], before))


class GoAheadTest(ChangeCase):
    def waiting(self, maturity="demo"):
        p = self.specced(maturity=maturity)
        go_ahead.choose(p, wait=True, person=PO["person"], persona=PO["persona"], where="New project")
        return p

    def test_FR_CHG1_AC_12_a_demo_project_waits_once_for_go_or_skip_before_its_first_build(self):
        for verdict in ("go", "skip"):
            with self.subTest(verdict=verdict):
                p = self.waiting()
                out = _shape(p, model(), [])
                self.assertEqual(out["state"], "waiting")
                card = Canon(p).get_card(out["waiting_on"][0])
                self.assertEqual((card["kind"], card["title"], card["refs"]["scope"]),
                                 ("go_ahead", "Look at the spec before building", "spec"))
                self.assertFalse(p.path("contract.json").exists())                  # nothing built or compiled yet
                nx = kn.next_step(p)
                self.assertEqual(nx["state"], "go_ahead")
                self.assertEqual([a["id"] for a in nx["actions"]],
                                 ["look_spec", "go_ahead_go", "go_ahead_skip", "change_settings"])
                self.assertEqual({a.get("verdict") for a in nx["actions"] if a.get("control") == "go_ahead"},
                                 {"go", "skip"})
                self.assertEqual(_shape(p, model(), [])["waiting_on"], [card["id"]])  # one card, not a new one
                Canon(p).decide(card["id"], verdict, person=PO["person"], persona=PO["persona"])
                self.assertEqual(_shape(p, model(), []), AGAIN)                      # the run goes on
                self.assertTrue(p.path("contract.json").exists())
                given = payloads(p, "go_ahead_given")
                self.assertEqual([(g["verdict"], g["by"]) for g in given], [(verdict, PO["person"])])

    def test_FR_CHG1_AC_12_build_without_waiting_turns_it_off_and_withdraws_an_open_card(self):
        p = self.waiting()
        card = _shape(p, model(), [])["waiting_on"][0]
        seen = ks.preview(p, build_without_waiting=True)
        self.assertEqual(seen["changes"], {"build_without_waiting": {"from": False, "to": True}})
        self.assertIn("builds the spec without waiting", seen["impact"][0]["says"])
        ks.change(p, reason="I trust the spec at demo", build_without_waiting=True, **PO)
        self.assertEqual(Canon(p).get_card(card)["state"], "withdrawn")
        self.assertEqual(ks.current(p)["build_without_waiting"], True)
        self.assertEqual(_shape(p, model(), []), AGAIN)
        self.assertEqual(payloads(p, "go_ahead_set")[-1]["where"], "Project settings")

    def test_FR_CHG1_AC_12_pilot_keeps_the_plan_approval_and_older_projects_build_as_before(self):
        p = self.waiting(maturity="pilot")
        out = _shape(p, model(), [])
        self.assertEqual(Canon(p).get_card(out["waiting_on"][0])["kind"], "approval")   # the plan's approval
        self.assertFalse(Canon(p).cards(kind="go_ahead"))
        older = self.specced()                                                          # nobody said: as before
        self.assertEqual(_shape(older, model(), []), AGAIN)

    def test_FR_CHG1_AC_12_a_delegation_may_say_go(self):
        p = self.waiting()
        card = _shape(p, model(), [])["waiting_on"][0]
        grant(p, ["go_ahead"], person=PO["person"], persona=PO["persona"], until="8h")
        from kernel.pipeline import _delegated

        self.assertTrue(_delegated(p, {"waiting_on": [card]}, []))
        decision = Canon(p).get_card(card)["decision"]
        self.assertEqual((decision["verdict"], decision.get("delegation")), ("go", "DL-001"))

    def test_FR_CHG1_AC_12_new_project_on_the_command_line_sets_it_and_the_demo_sets_it_off(self):
        source = self.tmp / "need.md"
        source.write_text("Our team keeps losing track of who borrowed the drills.\n", encoding="utf-8")
        for flag, wait in (([], True), (["--build-without-waiting"], False)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), mock.patch("kernel.cli._model", return_value=model()):
                code = main(["--home", str(self.factory.home), "new", "Equipment loans", "--source-file",
                             str(source), "--requested-by", "Aino Example", *flag])
            self.assertEqual(code, 0)
            p = self.factory.project(json.loads(out.getvalue())["project"])
            self.assertEqual(go_ahead.waits_for_me(p), wait)
        demo = (Path(go_ahead.__file__).parent / "demo.py").read_text(encoding="utf-8")
        self.assertEqual(demo.count("b.factory.new_project("), 1)        # every demo project goes through _new
        self.assertIn("choose(p, wait=False", demo)


class AdoptAsksTheKindTest(FactoryTestCase):
    def test_FR_X1_AC_4_an_unclear_adopted_project_asks_which_kind_with_the_candidates(self):
        src = make_repo(self.tmp / "src", {"README.md": "# Tools\n\nSome scripts the team uses.\n",
                                           "tools.py": "def main():\n    return 0\n"})
        p = adopt(self.factory, "Team tools", source=str(src), intent="maintain", person="Aino",
                  persona="developer", which=lambda name: None)
        self.assertIsNone(p.meta.get("profile"))                                  # no web app by default
        q = next(x for x in Canon(p).questions("open") if x["text"] == PROFILE_QUESTION)
        self.assertTrue(q["blocking"] and q["card"])
        self.assertIn("Web app or service (web_service)", q["options"])
        self.assertGreater(len(q["options"]), 1)
        self.assertEqual(payloads(p, "adopt_kind_asked")[0]["question"], q["id"])
        self.assertIn("a person is asked which kind of work it is", Canon(p).brief)
        nx = kn.next_step(p)
        self.assertEqual(nx["actions"][0]["id"], "answer")
        Canon(p).answer(q["id"], "Automation (automation)", person="Aino", persona="developer")
        render_brief(p)                                                           # as the cockpit and the CLI do
        self.assertEqual(p.meta["profile"], "automation")
        self.assertEqual(p.read("adopted.json")["profile"]["by"], "Aino")
        self.assertIn("- Work profile: Automation or small capability, chosen by Aino.", Canon(p).brief)
        self.assertIn("An existing solution adopted to **maintain** it", Canon(p).brief)  # the adoption brief stays

    def test_FR_X1_AC_4_one_clear_candidate_proceeds_and_says_which_and_why(self):
        src = python_repo(self.tmp / "src")                                       # its README and its HTTP routes
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--home", str(self.factory.home), "adopt", "Legacy loans", "--source", str(src),
                         "--intent", "maintain", "--person", "Aino", "--persona", "developer"])
        self.assertEqual(code, 0)
        said = json.loads(out.getvalue())
        self.assertEqual(said["profile"], "web_service")
        self.assertIn("Work profile: Web app or service, proposed by rule (api, service)", said["profile_basis"])
        self.assertNotIn("kind_asked", said)
        self.assertFalse([q for q in Canon(self.factory.project(said["project"])).questions("open")])
        self.assertIn("tracks which workshop equipment", README)


class GnomonKeyTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        from kernel import models_setup

        self.ms, self.real = models_setup, models_setup.gnomon_keys   # this test asks the stand-in Gnomon itself
        isolated_routing(self, self.tmp)
        gnomon_keys.forget()
        self.addCleanup(gnomon_keys.forget)

    def gnomon(self, keys: str, **extra):
        return mock.patch.dict(os.environ, {"GNOMON_CMD": f"{Path(sys.executable).as_posix()} {STUB.as_posix()}",
                                            "STUB_GNOMON_KEYS": keys, **extra})

    def builder(self):
        return next(r for r in self.ms.models_view(probe=False)["roles"] if r["role"] == "builder")

    def test_FR_MDL1_AC_10_a_key_gnomon_holds_reads_key_set_by_gnomon_never_no_key(self):
        real = self.real
        with self.gnomon("OPENCODE_API_KEY,OTHER_KEY"), mock.patch.object(self.ms, "gnomon_keys", real):
            self.assertEqual(real(), frozenset({"OPENCODE_API_KEY", "OTHER_KEY"}))
            role = self.builder()
            self.assertEqual((role["key"]["kind"], role["key"]["set"]), ("gnomon", True))
            self.assertEqual(role["readiness"]["state"], "configured")
            self.assertIn("set in Gnomon", role["readiness"]["why"])
            tested = self.ms.probe_role("builder")
            self.assertFalse(tested["ok"])
            self.assertIn("set in Gnomon, which Rihmasto never reads", tested["error"])
        gnomon_keys.forget()
        with self.gnomon(""), mock.patch.object(self.ms, "gnomon_keys", real):
            self.assertEqual(self.builder()["readiness"]["state"], "no_key")      # Gnomon holds none: no key

    def test_FR_MDL1_AC_10_when_gnomon_cannot_say_its_store_only_makes_it_maybe(self):
        real = self.real
        missing = {"GNOMON_CMD": (self.tmp / "no-such-gnomon").as_posix(), "XDG_DATA_HOME": str(self.tmp / "data")}
        with mock.patch.dict(os.environ, missing), mock.patch.object(self.ms, "gnomon_keys", real):
            self.assertIsNone(real())
            self.assertEqual(self.builder()["readiness"]["state"], "no_key")
            store = self.tmp / "data" / "gnomon" / "credentials.json"
            store.parent.mkdir(parents=True)
            store.write_text('{"OPENCODE_API_KEY": "stand-in-value-never-shown"}', encoding="utf-8")
            view = self.ms.models_view(probe=False)                          # only the store's presence counts
            role = next(r for r in view["roles"] if r["role"] == "builder")
            self.assertNotIn("stand-in-value-never-shown", json.dumps(view))
            self.assertEqual((role["key"]["kind"], role["readiness"]["state"]), ("gnomon_maybe", "maybe_key"))
            self.assertIn("Gnomon may have its own key for this host", role["readiness"]["why"])


if __name__ == "__main__":
    unittest.main()
