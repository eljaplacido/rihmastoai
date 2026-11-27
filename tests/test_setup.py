"""FR-SET1: set up every project, suggested and described automations, archiving and removing projects, and Ask
Rihma's proposals for each. The parity tables are tests/test_parity.py; the browser walk tests/test_setup_ui_drive.py.
No test here calls a real model: the scripted one answers with what it is given."""

import contextlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from alignment_fixture import make_repo  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_copilot import Scripted, tree  # noqa: E402

from kernel import automation_compose as compose  # noqa: E402
from kernel import automation_suggest as suggest  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel import project_archive as archive  # noqa: E402
from kernel import project_setup as setup  # noqa: E402
from kernel import relay  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import ProjectArchived, write_json  # noqa: E402

AINO = {"person": "Aino Example", "persona": "developer"}
EN = "every night run the tests and tell me on Teams if they fail"
FI = "öisin aja testit ja ilmoita Teamsiin jos ne epäonnistuvat"


class Shapes(FactoryTestCase):
    """Projects of different shapes, made by the kernel's own paths."""

    def attached(self, title="Loans of the tool store", profile=None):
        repo = self.tmp / title.replace(" ", "-")
        if not (repo / ".git").exists():
            make_repo(repo)
        p = attach(self.factory, title, repo=repo, person="Aino Example", persona="developer")
        p.update_meta(console={"commands": {"test": "python -m unittest"}}, **({"profile": profile} if profile else {}))
        return p

    def in_production(self):
        p = self.new(title="Room bookings")
        write_json(p.path("releases", "1.json"), {"release": 1, "maturity": "production", "state": "done", "steps": []})
        return p

    def ids(self, pid):
        return {s["id"]: s for s in suggest.scan(self.factory, pid)["suggestions"]}


class SuggestTest(Shapes):
    def test_FR_SET1_AC_1_each_shape_gets_the_suggestions_it_asks_for_with_a_reason_and_scanning_writes_nothing(self):
        from kernel.checks import store as cstore

        repo = self.attached()
        cstore.enable(repo, "secrets", **AINO)
        ml = self.attached("Demand forecast", profile="ml")
        secret = self.new(title="Payroll")
        secret.update_meta(confidential=True)
        prod, idea = self.in_production(), self.new(title="A new idea")
        before = tree(self.factory.home)
        got = {p.pid: self.ids(p.pid) for p in (repo, ml, secret, prod, idea)}
        self.assertEqual(tree(self.factory.home), before)                          # scanning writes nothing
        for sid in ("nightly_gate", "tests_on_commit", "check_failed", "align_on_change", "gate_twice_change"):
            self.assertIn(sid, got[repo.pid])
        self.assertIn("ml_weekly_eval", got[ml.pid])
        self.assertIn("local_model_alert", got[secret.pid])
        self.assertEqual(got[prod.pid]["probe_production"]["draft"]["trigger"], {"kind": "schedule", "every": "5m"})
        self.assertEqual(list(got[idea.pid]), ["first_build"])
        for sugs in got.values():
            for s in sugs.values():
                self.assertEqual(s["state"], "offered", s)
                self.assertTrue(s["reason"] and s["summary"], s)
                au._checked(self.factory, s["draft"])                                # passes the automations' checks
        # no channel yet: a notice is a signal on the square; with one, it goes to the channel
        self.assertEqual(got[secret.pid]["local_model_alert"]["draft"]["action"]["kind"], "signal")
        sub = relay.subscribe(self.factory, sink="teams", url_env="TEAMS_URL", personas=["developer"],
                              person="Ilkka", persona="it")
        told =self.ids(secret.pid)["local_model_alert"]["draft"]["action"]
        self.assertEqual((told["kind"], told["subscription"]), ("notify", sub["id"]))
        self.assertEqual(self.ids(repo.pid)["nightly_gate"]["draft"]["notify"], {"subscription": sub["id"],
                                                                                "when": "failed"})

    def test_FR_SET1_AC_2_a_suggestion_is_set_up_signed_or_dismissed_and_remembered(self):
        p = self.in_production()
        with self.assertRaises(au.AutomationRefused):
            suggest.accept(self.factory, p.pid, "probe_production", person="factory", persona="developer")
        out = suggest.accept(self.factory, p.pid, "probe_production", **AINO)
        a = out["automation"]
        self.assertEqual((a["owner"]["person"], a["action"]["kind"]), ("Aino Example", "probe"))
        self.assertEqual(self.ids(p.pid)["probe_production"]["state"], "set_up")
        suggest.dismiss(self.factory, p.pid, "weekly_summary" if "weekly_summary" in self.ids(p.pid)
                        else "first_build", **AINO)
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        self.assertIn("automation_suggestion_accepted", kinds)
        self.assertIn("automation_suggestion_dismissed", kinds)
        self.assertIn("dismissed", [s["state"] for s in self.ids(p.pid).values()])
        self.assertEqual([r["event"]["payload"]["id"] for r in factory_project(self.factory).ledger()
                          .of_kind("automation_set")], [a["id"]])
        with self.assertRaises(au.AutomationRefused):
            suggest.accept(self.factory, p.pid, "probe_production", **AINO)          # set up already


class ComposeTest(Shapes):
    def test_FR_SET1_AC_3_the_rules_draft_an_automation_from_english_or_finnish_with_a_summary_and_a_dry_run(self):
        p = self.new(title="Loans")
        sub = relay.subscribe(self.factory, sink="teams", url_env="TEAMS_URL", personas=["developer"],
                              person="Ilkka", persona="it")
        before = tree(self.factory.home)
        for words in (EN, FI):
            out = compose.compose(self.factory, words, project=p)
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["by"], "rules")
            d = out["draft"]
            self.assertEqual((d["trigger"], d["action"]["kind"], d["notify"], d["scope"]),
                             ({"kind": "schedule", "daily": "02:00"}, "run_check",
                              {"subscription": sub["id"], "when": "failed"}, {"kind": "project", "projects": [p.pid]}))
            self.assertTrue(out["summary"].startswith(f"Every night at 02:00 UTC, for project {p.pid}, run the "
                                                      "Test suite check"), out["summary"])
            self.assertEqual(out["dry_run"]["projects"], [p.pid])
            self.assertEqual(out["dry_run"]["first_at"], "2026-11-23T02:00:00Z")
        for words, trigger, action in (("probe production every 5 minutes", {"kind": "schedule", "every": "5m"},
                                        "probe"),
                                       ("on new commits run the gate", {"kind": "repo"}, "gate"),
                                       ("when a release is done, summarise it", {"kind": "event",
                                                                                 "types": ["release_done"]}, "ask"),
                                       ("every monday at 9 re-read the repository", {"kind": "schedule",
                                                                                     "weekly": "mon 09:00"},
                                        "align_scan")):
            out = compose.compose(self.factory, words, project=p)
            self.assertEqual((out["draft"]["trigger"], out["draft"]["action"]["kind"], out["ok"]),
                             (trigger, action, True), words)
        gate = compose.compose(self.factory, "when a check fails tell me on teams", project=p)["draft"]
        self.assertEqual(gate["guard"], {"kind": "field", "key": "verdict", "equals": "failed"})
        unread = compose.compose(self.factory, "make me a sandwich", project=p)
        self.assertFalse(unread["ok"])
        self.assertIn("I could not read when it should run and what it should do", unread["why"])
        self.assertEqual(tree(self.factory.home), before)                          # describing records nothing

    def test_FR_SET1_AC_4_a_models_draft_is_checked_against_the_allow_list_and_confidential_stays_local(self):
        p = self.new(title="Loans")
        ok = Scripted({"name": "Weekly digest", "trigger": {"kind": "schedule", "weekly": "fri 15:00"},
                       "action": {"kind": "signal", "text": "{project}: the week"},
                       "scope": {"kind": "project", "projects": [p.pid]}})
        out = compose.compose(self.factory, "automation: wrap up my week on friday afternoons", project=p, model=ok)
        self.assertEqual((out["by"], out["ok"]), ("model", True), out)
        self.assertTrue(out["summary"].startswith("Every Friday at 15:00 UTC"), out["summary"])
        self.assertEqual(ok.calls[0][0], "assistant")
        self.assertIn("never decides, approves, deploys", ok.calls[0][1])
        bad = Scripted({"name": "Approve it", "trigger": {"kind": "event", "types": ["release_done"]},
                        "action": {"kind": "approve"}, "scope": {"kind": "factory"}})
        out = compose.compose(self.factory, "automation that approves releases by itself", project=p, model=bad)
        self.assertFalse(out["ok"])
        self.assertIn("refused: an automation never may approve", out["why"])
        p.update_meta(confidential=True)
        quiet = Scripted({})
        with mock.patch("kernel.confidential.refusal", return_value="refused: hosted"):
            out = compose.compose(self.factory, "automation: wrap up my week on friday afternoons", project=p,
                                  model=quiet)
        self.assertEqual(quiet.calls, [])
        self.assertEqual(out["by"], "rules")
        self.assertIn("confidential", out["note"])


class SetupTest(Shapes):
    def test_FR_SET1_AC_5_the_checklist_shows_each_feature_with_its_state_and_one_click_does_it(self):
        idea, repo = self.new(title="A new idea"), self.attached()
        c = setup.checklist(self.factory, idea.pid)
        states = {i["id"]: i["state"] for i in c["items"]}
        self.assertEqual(set(states), {"checks", "automations", "alignment", "insights_review", "ai_tools", "posture",
                                       "outputs", "destinations", "agent_observability", "gnomon_audits"})
        self.assertEqual((states["checks"], states["alignment"], states["ai_tools"]),
                         ("not_applicable", "not_applicable", "not_applicable"))
        self.assertTrue(all(i["why"] for i in c["items"]))
        r = {i["id"]: i for i in setup.checklist(self.factory, repo.pid)["items"]}
        self.assertEqual((r["checks"]["state"], r["alignment"]["state"], r["ai_tools"]["state"]),
                         ("offered", "offered", "offered"))
        self.assertEqual(r["checks"]["action"]["kind"], "do")
        self.assertEqual(r["posture"]["action"], {"kind": "open", "label": "Choose a posture", "view": "overview",
                                                  "page": None, "control": "posture"})
        for item in ("checks", "alignment", "automations"):
            out = setup.do(self.factory, repo.pid, item, **AINO)
            self.assertEqual({i["id"]: i["state"] for i in out["checklist"]["items"]}[item] in ("set_up", "offered"),
                             True)
        after = {i["id"]: i["state"] for i in setup.checklist(self.factory, repo.pid)["items"]}
        self.assertEqual((after["checks"], after["alignment"]), ("set_up", "set_up"))
        kinds = [x["event"]["kind"] for x in repo.ledger().records()]
        for kind in ("check_enabled", "alignment_scanned", "automation_suggestion_accepted"):
            self.assertIn(kind, kinds)
        with self.assertRaises(ValueError):
            setup.do(self.factory, repo.pid, "checks", **AINO)                     # set up already: not offered
        with self.assertRaises(ValueError):
            setup.do(self.factory, idea.pid, "posture", **AINO)                    # chosen in its own dialog
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["--home", str(self.factory.home), "setup", idea.pid]), 0)
        self.assertEqual([i["id"] for i in json.loads(out.getvalue())["items"]][:3],
                         ["checks", "automations", "alignment"])

    def test_FR_SET1_AC_5_the_automations_click_sets_up_the_suggestion_it_names_or_is_refused(self):
        """The suggestions change as the project does: the click sets up the one its button named, never the
        first one offered by then; a suggestion no longer offered is refused and nothing is set up."""
        p = self.attached()
        item = next(i for i in setup.checklist(self.factory, p.pid)["items"] if i["id"] == "automations")
        self.assertEqual(item["action"]["suggestion"], "nightly_gate")
        out = setup.do(self.factory, p.pid, "automations", suggestion="tests_on_commit", **AINO)
        self.assertEqual(out["done"]["suggestion"], "tests_on_commit")
        states = {k: v["state"] for k, v in self.ids(p.pid).items()}
        self.assertEqual((states["tests_on_commit"], states["nightly_gate"]), ("set_up", "offered"))
        with self.assertRaisesRegex(ValueError, "no longer offered"):
            setup.do(self.factory, p.pid, "automations", suggestion="tests_on_commit", **AINO)
        self.assertEqual(len(au.automations(self.factory)), 1)                     # nothing else was set up
        # Ask Rihma's proposal names the suggestion too, so Confirm sends it
        prop = next(x for x in ask(self.factory, "Set up this project", persona="developer", project_id=p.pid)
                    ["propose"] if x["args"]["item"] == "automations")
        self.assertEqual(prop["args"]["call"]["body"], {"suggestion": "nightly_gate"})


class ArchiveTest(Shapes):
    def cli(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["--home", str(self.factory.home), *argv]), code, err.getvalue())
        return json.loads(out.getvalue()) if out.getvalue().strip() else err.getvalue()

    def test_FR_SET1_AC_6_archive_hides_and_freezes_restore_brings_back_and_remove_exports_first(self):
        keep, copy = self.new(title="Loans"), self.new(title="Loans")
        copy.log("note", {"text": "a record"})
        dup = archive.duplicates(self.factory)
        self.assertEqual(len(dup), 1)
        gone = dup[0]["copies"][0]["id"]
        self.assertEqual((dup[0]["keep"]["id"], gone), (copy.pid, keep.pid))      # the one with more records stays
        target = self.factory.project(gone)
        signed = ["--person", "Aino Example", "--persona", "product_owner"]
        self.assertIn("is not archived", self.cli("project", "remove", gone, "--confirm", gone, *signed, code=2))
        with self.assertRaises(archive.ArchiveRefused):
            archive.archive(self.factory, gone, person="Aino Example", persona="end_user")
        self.cli("project", "archive", gone, "--reason", "a duplicate", *signed)
        self.assertNotIn(gone, [p.pid for p in self.factory.projects()])            # gone from every list
        self.assertEqual([r["id"] for r in archive.archived(self.factory)], [gone])
        with self.assertRaises(ProjectArchived):
            target.log("note", {"text": "read-only"})
        self.cli("project", "restore", gone, *signed)
        self.assertIn(gone, [p.pid for p in self.factory.projects()])
        target.log("note", {"text": "writable again"})
        self.cli("project", "archive", gone, *signed)
        said = self.cli("project", "remove", gone, *signed, code=2)
        self.assertIn(f"Remove Loans ({gone}) for good: this cannot be undone", said)
        self.assertIn(f"Run it again with --confirm {gone}",
                      self.cli("project", "remove", gone, "--confirm", "loans", *signed, code=2))
        with self.assertRaises(archive.ArchiveRefused):
            archive.remove(self.factory, gone, person="Aino Example", persona="product_owner", confirm="loans")
        out = self.cli("project", "remove", gone, "--confirm", gone, *signed)
        self.assertFalse(target.dir.exists())
        export = self.factory.home / out["export"]["relative"]
        with zipfile.ZipFile(export) as zf:
            names = zf.namelist()
        self.assertIn("project/ledger.jsonl", names)
        self.assertIn("project/project.json", names)
        removed = factory_project(self.factory).ledger().of_kind("project_removed")[-1]["event"]["payload"]
        self.assertEqual((removed["project"], removed["sha256"], removed["person"]),
                         (gone, out["export"]["sha256"], "Aino Example"))
        kinds = [r["event"]["kind"] for r in factory_project(self.factory).ledger().records()]
        self.assertEqual([k for k in kinds if k.startswith("project_")],
                         ["project_archived", "project_restored", "project_archived", "project_removed"])


class ChatTest(Shapes):
    def acts(self, out):
        return [(p["args"]["op"], p["args"]["call"]["method"], p["args"]["call"]["path"]) for p in out["propose"]
                if p["action"] == "act"]

    def test_FR_SET1_AC_7_ask_rihma_proposes_each_change_checked_from_the_table_of_operations(self):
        p, copy = self.in_production(), self.new(title="Room bookings")
        out = ask(self.factory, "Set up this project", persona="developer", project_id=p.pid)
        self.assertEqual(out["by"], "setup")
        self.assertIn(("setup_step", "POST", f"/api/projects/{p.pid}/setup/automations"), self.acts(out))
        out = ask(self.factory, "Suggest automations for this project", persona="developer", project_id=p.pid)
        self.assertIn(("accept_suggestion", "POST",
                       f"/api/projects/{p.pid}/automation-suggestions/probe_production/accept"), self.acts(out))
        out = ask(self.factory, "probe production every 5 minutes", persona="developer", project_id=p.pid)
        [(op, method, path)] = self.acts(out)
        self.assertEqual((op, method, path), ("add_automation", "POST", "/api/automations"))
        self.assertEqual(out["propose"][0]["args"]["call"]["body"]["automation"]["trigger"],
                         {"kind": "schedule", "every": "5m"})
        out = ask(self.factory, "Delete so many duplicate projects", persona="product_owner")
        kept = archive.duplicates(self.factory)[0]
        self.assertEqual(self.acts(out), [("archive_project", "POST", f"/api/projects/{c['id']}/archive")
                                          for c in kept["copies"]])
        self.assertEqual(ask(self.factory, "Delete so many duplicate projects", persona="end_user")["propose"], [])
        archive.archive(self.factory, copy.pid, person="Aino Example", persona="product_owner")
        out = ask(self.factory, f"remove {copy.pid} for good", persona="product_owner")
        self.assertEqual(self.acts(out), [("remove_project", "POST", f"/api/projects/{copy.pid}/remove")])
        self.assertIn("cannot be undone", out["answer"])
        self.assertEqual(out["propose"][0]["args"]["call"]["body"], {"confirm": copy.pid})
        out = ask(self.factory, "Set up this project", persona="developer", project_id=copy.pid)
        self.assertEqual(self.acts(out), [])                                        # archived: nothing offered
        # a question about where things are is answered from the map, never as a proposal
        out = ask(self.factory, "Where do I archive a project?", persona="product_owner", project_id=p.pid)
        self.assertEqual((out["by"], out["propose"]), ("map", []))
        self.assertEqual(out["navigate"]["control"], "archive_project")


class CockpitTest(CockpitTestCase):
    def test_FR_SET1_AC_7_confirming_a_proposal_sends_its_request_signed_and_an_archived_project_refuses_writes(self):
        p, copy = self.new(title="Loans"), self.new(title="Loans")
        status, out, _ = self.call("POST", "/api/assistant", {"question": "archive the duplicate projects",
                                                               "persona": "product_owner", "person": "Aino"})
        self.assertEqual(status, 200, out)
        [prop] = out["propose"]
        call = prop["args"]["call"]
        target = call["path"].split("/")[3]
        status, done, _ = self.call(call["method"], call["path"], {**call["body"], "person": "Aino Example",
                                                                   "persona": "product_owner"})
        self.assertEqual(status, 200, done)
        self.assertTrue(done["project"]["archived"])
        status, refused, _ = self.call("POST", f"/api/projects/{target}/changes", {"text": "x", "person": "Aino",
                                                                                  "persona": "end_user"})
        self.assertEqual(status, 403, refused)
        self.assertIn("is archived", refused["error"])
        status, rows, _ = self.call("GET", "/api/projects")
        self.assertNotIn(target, [r["id"] for r in rows])
        status, arc, _ = self.call("GET", "/api/archived-projects")
        self.assertEqual([r["id"] for r in arc["archived"]], [target])
        status, out, _ = self.call("POST", f"/api/projects/{target}/remove", {"confirm": "no", "person": "Aino",
                                                                             "persona": "product_owner"})
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("POST", "/api/automations/compose", {"text": EN, "project": p.pid,
                                                                        "person": "Aino", "persona": "developer"})
        self.assertEqual((status, out["ok"], out["by"]), (200, True, "rules"), out)
        status, setup_out, _ = self.call("GET", f"/api/projects/{p.pid}/setup")
        self.assertEqual(status, 200)
        self.assertEqual(setup_out["project"], p.pid)

    def test_FR_SET1_AC_5_the_one_click_sends_the_suggestion_it_names_and_one_no_longer_offered_is_refused(self):
        p = self.new(title="Room bookings")
        write_json(p.path("releases", "1.json"), {"release": 1, "maturity": "production", "state": "done", "steps": []})
        signed = {"person": "Aino Example", "persona": "developer"}
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/setup/automations",
                                   {**signed, "suggestion": "nightly_gate"})      # never offered here
        self.assertEqual(status, 400, out)
        self.assertIn("no longer offered", out["error"])
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/setup/automations",
                                   {**signed, "suggestion": "test_road_checks"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["done"]["suggestion"], "test_road_checks")             # that one, not the first
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/setup/automations", {**signed, "suggestion": 7})
        self.assertEqual(status, 400, out)
        js = (Path(__file__).parent.parent / "cockpit" / "static" / "setup.js").read_text(encoding="utf-8")
        self.assertIn("suggestion: a.suggestion", js)                              # the button sends what it names


if __name__ == "__main__":
    unittest.main()
