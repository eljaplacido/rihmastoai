"""Enforcement levels per environment (FR-ENF1): advise or enforce, per platform and project, beside the pipeline.

The owner (2026-11-25): "in development we wouldn't want forced human check on everything; in testing and
production we wouldn't want any critical changes without human checks." Every GitHub answer here comes from
tests/enforcement_fakes.py FakeGh (a neutral acme/orders); nothing reaches GitHub.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from enforcement_fakes import REPO, FakeGh  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_deliver import DeliveryTestCase  # noqa: E402  (a built product per test, on local roads)

from kernel import assistant, enforcement_chat, enforcement_pipeline  # noqa: E402
from kernel import automations_actions as acts  # noqa: E402
from kernel import enforcement as ke  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.deliver import deliver  # noqa: E402
from kernel.enforcement_guard import at_automation, at_deploy, at_gate, guard, recent  # noqa: E402
from kernel.enforcement_preview import preview  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

IT, OWNER, COMP, DEV = "Ilkka Example", "Aino Example", "Cecilia Example", "Dana Example"
NONE = {f: [] for f in ke.FAMILIES}


def found(family: str, item: str = "check tests: 2 failed") -> dict:
    return {**NONE, family: [item]}


class LevelsTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")

    def cell(self, env, fam, project=True):
        return ke.cell(self.factory, self.p if project else None, env, fam)

    def test_FR_ENF1_AC_1_advise_by_default_and_each_cell_says_its_scope(self):
        self.assertTrue(all(c["level"] == "advise" and c["scope"] == "default" for c in ke.grid(self.factory, self.p)))
        self.assertIsNone(factory_project(self.factory, create=False))       # reading created nothing
        ke.set_levels(self.factory, None, levels={"prod": {"security": "enforce"}}, person=IT, persona="it")
        self.assertEqual((self.cell("prod", "security")["level"], self.cell("prod", "security")["scope"]),
                         ("enforce", "platform"))
        ke.set_levels(self.factory, self.p, levels={"test": {"governance": "require_review"}},
                      reviewers={"governance": "compliance"}, person=COMP, persona="compliance")
        own = self.cell("test", "governance")
        self.assertEqual((own["level"], own["scope"], own["reviewer"], own["reviewer_scope"]),
                         ("require_review", "project", "compliance", "project"))
        self.assertEqual(self.cell("test", "governance", project=False)["scope"], "default")
        ke.set_levels(self.factory, self.p, levels={"test": {"governance": "inherit"}}, person=COMP,
                      persona="compliance", reason="back to the platform's")
        self.assertEqual(self.cell("test", "governance")["scope"], "default")
        fac = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind(ke.LEVELS_KIND)]
        self.assertEqual((fac[0]["person"], fac[0]["scope"], fac[0]["changes"]),
                         (IT, "platform", [{"env": "prod", "family": "security", "from": None, "to": "enforce"}]))
        own_log = [r["event"]["payload"] for r in self.p.ledger().of_kind(ke.LEVELS_KIND)]
        self.assertEqual([r["person"] for r in own_log], [COMP, COMP])
        self.assertEqual(own_log[1]["reason"], "back to the platform's")

    def test_FR_ENF1_AC_1_a_non_person_another_persona_or_a_loosening_without_reason_is_refused(self):
        before = self.p.ledger().records()
        for person, persona in (("", "it"), (DEV, "end_user"), (DEV, "operations")):
            with self.assertRaises(DecisionRefused, msg=(person, persona)):
                ke.set_levels(self.factory, self.p, levels={"prod": {"quality": "enforce"}}, person=person,
                              persona=persona)
        self.assertEqual(self.p.ledger().records(), before)
        self.assertFalse(self.p.path("enforcement.json").exists())
        ke.set_levels(self.factory, self.p, preset="split", person=OWNER, persona="business_owner")
        with self.assertRaisesRegex(ValueError, "needs a reason"):
            ke.set_levels(self.factory, self.p, levels={"prod": {"security": "advise"}}, person=DEV,
                          persona="developer")
        out = ke.set_levels(self.factory, self.p, levels={"prod": {"security": "advise"}}, person=DEV,
                            persona="developer", reason="a demo week")
        self.assertEqual(out["changes"], [{"env": "prod", "family": "security", "from": "enforce", "to": "advise"}])
        with self.assertRaises(ValueError):
            ke.set_levels(self.factory, self.p, levels={"stage": {"quality": "enforce"}}, person=DEV,
                          persona="developer")

    def test_FR_ENF1_AC_2_a_preview_says_what_a_change_would_do_and_records_nothing(self):
        other = self.new(title="Inventory")
        ke.set_levels(self.factory, other, levels={"prod": {"governance": "advise"}}, person=OWNER,
                      persona="business_owner")
        guard(self.p, env="staging", source="deploy", subject="release 1", found=NONE)
        guard(self.p, env="production", source="deploy", subject="release 1", found=found("security"))
        files = sorted(str(f) for f in self.factory.home.rglob("*") if f.is_file())
        ledgers = (len(self.p.ledger().records()), len(other.ledger().records()))
        mine = preview(self.factory, self.p, preset="split")
        self.assertIn({"env": "prod", "family": "security", "from": "advise", "to": "enforce", "from_scope": "default",
                       "to_scope": "project", "reviewer": "it",
                       "next": "The work will wait until IT / partner decides its card."}, mine["changes"])
        self.assertEqual(mine["would"], {"looked_at": 3, "moved": {"noted -> review": 1, "noted -> refused": 2}})
        self.assertIn("Of the last 3 outcomes Rihmasto recorded, 2 noted would become refused, 1 noted would become "
                      "review.", mine["lines"])
        everyone = preview(self.factory, None, levels={"prod": {"governance": "enforce"}})
        self.assertEqual(everyone["reached"], [self.p.pid])
        self.assertEqual(everyone["kept"], [{"project": other.pid, "title": "Inventory"}])
        self.assertEqual(sorted(str(f) for f in self.factory.home.rglob("*") if f.is_file()), files)
        self.assertEqual((len(self.p.ledger().records()), len(other.ledger().records())), ledgers)


class GuardTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")
        self.canon = Canon(self.p)

    def set(self, levels, **kw):
        ke.set_levels(self.factory, self.p, levels=levels, person=OWNER, persona="business_owner", **kw)

    def cards(self):
        return self.canon.cards(state=None, kind="enforcement")

    def test_FR_ENF1_AC_3_advise_notes_and_goes_on_and_development_stays_quiet(self):
        self.assertIsNone(at_deploy(self.p, "staging", 1))
        self.assertIsNone(at_deploy(self.p, "production", 1))
        self.assertIsNone(at_deploy(self.p, "demo", 1))                         # development, nothing found
        self.assertIsNone(at_gate(self.p, "passed", "repo:abc", "a" * 40))
        noted = at_gate(self.p, "failed", "repo:abc", "b" * 40)
        self.assertEqual((noted["outcome"], noted["checked"][0]["family"]), ("noted", "quality"))
        rows = recent(self.p)
        self.assertEqual([(r["env"], r["family"], r["outcome"], r["subject"]) for r in rows],
                         [("dev", "quality", "noted", "change bbbbbbbbbbbb"), ("prod", "governance", "noted", "release 1"),
                          ("test", "governance", "noted", "release 1")])
        self.assertEqual(self.cards(), [])

    def test_FR_ENF1_AC_4_require_review_opens_one_card_for_the_named_reviewer_and_goes_on(self):
        self.set({"test": {"governance": "require_review"}}, reviewers={"governance": "compliance"})
        self.assertIsNone(at_deploy(self.p, "staging", 2))
        self.assertIsNone(at_deploy(self.p, "staging", 2))                       # the same release: no second card
        (card,) = self.cards()
        self.assertEqual((card["deciders"], card["blocking"], card["payload"]["subject"]),
                         (["compliance"], False, "release 2"))
        with self.assertRaises(DecisionRefused):
            self.canon.decide(card["id"], "approve", person=DEV, persona="developer")
        self.canon.decide(card["id"], "approve", person=COMP, persona="compliance", reason="looked at it")
        self.assertEqual(recent(self.p)[0]["outcome"], "review")

    def test_FR_ENF1_AC_5_enforce_holds_until_the_reviewer_decides_and_the_approval_is_the_recorded_override(self):
        self.set({"prod": {"governance": "enforce"}})
        held = at_deploy(self.p, "production", 3)
        self.assertEqual(held["outcome"], "waiting")
        card = self.canon.get_card(held["card"])
        self.assertEqual((card["kind"], card["deciders"], card["blocking"]), ("enforcement", ["business_owner"], True))
        self.assertIn(held["card"], held["waiting_on"])
        self.assertIn("business owner", held["waiting_on"])
        self.assertEqual(at_deploy(self.p, "production", 3)["card"], held["card"])   # still held, the same card
        self.canon.decide(held["card"], "approve", person=OWNER, persona="business_owner", reason="release notes read")
        self.assertIsNone(at_deploy(self.p, "production", 3))
        last = recent(self.p)[0]
        self.assertEqual((last["outcome"], last["override"]["by"], last["override"]["reason"]),
                         ("cleared", OWNER, "release notes read"))
        refused = at_deploy(self.p, "production", 4)
        self.canon.decide(refused["card"], "refuse", person=OWNER, persona="business_owner", reason="not yet")
        self.assertEqual(at_deploy(self.p, "production", 4)["card"], refused["card"])

    def test_FR_ENF1_AC_5_an_automation_that_changes_something_is_refused_while_enforced(self):
        self.set({"dev": {"quality": "enforce"}})
        a = {"id": "AU-001", "trigger": {"kind": "schedule"}, "owner": {"person": DEV, "persona": "developer"},
             "action": {"kind": "command", "project": self.p.pid}}
        firing = {"trigger": "schedule", "project": self.p.pid}
        self.assertIsNone(at_automation(self.factory, a, firing))               # nothing found: governance only
        with mock.patch("kernel.enforcement_guard.findings", return_value=found("quality")):
            out = acts.run(self.factory, a, firing, tools=None)
        self.assertEqual(out["outcome"], "refused")
        self.assertRegex(out["detail"], r"C-\d+ waits for the developer to decide")
        notify = dict(a, action={"kind": "notify", "project": self.p.pid})
        self.assertIsNone(at_automation(self.factory, notify, firing))          # a notice changes nothing

    def test_FR_ENF1_AC_6_each_level_in_each_environment(self):
        expect = {"off": ("passed", 0, None), "advise": ("noted", 1, None), "require_review": ("review", 1, False),
                  "enforce": ("refused", 1, True)}
        for env, named in (("dev", "demo"), ("test", "staging"), ("prod", "production")):
            for level, (outcome, records, blocking) in expect.items():
                with self.subTest(env=env, level=level):
                    p = self.new(title=f"{env} {level}")
                    ke.set_levels(self.factory, p, levels={env: {"security": level}}, person=IT, persona="it",
                                  reason="matrix")
                    before = len(p.ledger().of_kind("enforcement"))
                    out = guard(p, env=named, source="deploy", subject="release 1", found=found("security"))
                    mine = [x for x in out["checked"] if x["family"] == "security"]
                    self.assertEqual(mine[0]["outcome"] if mine else "passed", outcome)
                    self.assertEqual(len([r for r in p.ledger().of_kind("enforcement")[before:]
                                          if r["event"]["payload"]["family"] == "security"]), records)
                    cards = [c for c in Canon(p).cards(state=None, kind="enforcement")
                             if c["payload"]["family"] == "security"]
                    self.assertEqual([(c["blocking"], c["deciders"]) for c in cards],
                                     [] if blocking is None else [(blocking, ["it"])])


class DeployStepTest(DeliveryTestCase):
    """A real release of a built product on local roads: the deploy to staging asks the project's levels."""

    maturity = "pilot"

    def test_FR_ENF1_AC_5_a_release_waits_on_the_enforcement_card_before_testing_and_goes_on_once_approved(self):
        ke.set_levels(self.factory, self.project, levels={"test": {"governance": "enforce"}},
                      reviewers={"governance": "it"}, person=IT, persona="it")
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting")
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual((card["kind"], card["deciders"]), ("enforcement", ["it"]))
        self.assertFalse(roadmod.slot_state(self.project, "staging", "current"))   # nothing deployed yet
        self.decide(card["id"], "approve", "it", person="Jaana", reason="staging is ours this week")
        out = deliver(self.project)
        self.assertNotEqual(out.get("waiting_on"), card["id"])
        self.assertTrue(roadmod.slot_state(self.project, "staging", "current"))
        cleared = [r for r in recent(self.project) if r["outcome"] == "cleared"]
        self.assertEqual(cleared[0]["override"]["by"], "Jaana")


class PipelineTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")

    def test_FR_ENF1_AC_7_github_is_read_with_get_only_and_compared_per_environment(self):
        ke.set_levels(self.factory, self.p, repo=REPO, person=DEV, persona="developer")
        gh = FakeGh()
        pipe = enforcement_pipeline.read(self.p, run=gh)
        self.assertTrue(all(c[:3] == ["api", "-X", "GET"] for c in gh.calls))
        self.assertEqual([(e["name"], e["env"], e["required_reviewers"]) for e in pipe["environments"]],
                         [("staging", "test", 0), ("production", "prod", 1)])
        self.assertEqual((pipe["branch"], pipe["protection"]["required_reviews"], pipe["protection"]["required_checks"]),
                         ("main", 1, ["tests"]))
        cmp = enforcement_pipeline.compare(ke.describe(self.factory, self.p), pipe)
        self.assertEqual({r["env"]: r["state"] for r in cmp["rows"]},
                         {"dev": "pipeline_stricter", "test": "agree", "prod": "pipeline_stricter"})
        self.assertEqual(cmp["suggested"], {"dev": {"governance": "enforce"}, "test": {"governance": "advise"},
                                            "prod": {"governance": "enforce"}})
        ke.set_levels(self.factory, self.p, levels=cmp["suggested"] | {"test": {"quality": "require_review"}},
                      person=DEV, persona="developer")
        again = enforcement_pipeline.compare(ke.describe(self.factory, self.p), pipe)
        self.assertEqual({r["env"]: r["state"] for r in again["rows"]},
                         {"dev": "agree", "test": "rihmasto_stricter", "prod": "agree"})
        self.assertIn("never", next(r["todo"] for r in again["rows"] if r["env"] == "test"))

    def test_FR_ENF1_AC_7_not_read_says_why_and_how(self):
        out = enforcement_pipeline.read(self.p, run=FakeGh())
        self.assertEqual((out["read"], out["why"]), (False, "this project has no repository on this machine"))
        self.assertIn("Name the repository", out["how"])
        ke.set_levels(self.factory, self.p, repo=REPO, person=DEV, persona="developer")
        out = enforcement_pipeline.read(self.p, run=FakeGh(signed_in=False))
        self.assertEqual(out["read"], False)
        self.assertIn("gh auth login", out["why"] + out["how"])
        unprotected = enforcement_pipeline.read(self.p, run=FakeGh(protected=False))
        self.assertEqual((unprotected["protection"]["protected"], unprotected["protection"]["readable"]), (False, True))
        self.assertEqual(enforcement_pipeline.compare(ke.describe(self.factory, self.p), out), {"rows": [],
                                                                                                "suggested": None})


class ChatTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")

    def test_FR_ENF1_AC_8_ask_rihma_answers_and_proposes_by_rule(self):
        out = enforcement_chat.answer(self.factory, "How is production enforced here?", self.p, "developer")
        self.assertIn("prod: advise (from default)", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.p.pid}/enforcement", "control": "enforcement_levels"})
        self.assertEqual(out["propose"], [])
        ask = enforcement_chat.answer(self.factory, "Require review in test for security", self.p, "compliance")
        (prop,) = ask["propose"]
        self.assertEqual((prop["action"], prop["args"]),
                         ("enforcement_levels_set", {"project": self.p.pid,
                                                     "levels": {"test": {"security": "require_review"}}}))
        self.assertIn("1 setting would change.", ask["answer"])
        self.assertEqual(enforcement_chat.answer(self.factory, "Require review in test", self.p, "end_user")["propose"],
                         [])
        platform = enforcement_chat.answer(self.factory, "Use the split for all projects", self.p, "it")
        self.assertEqual(platform["propose"][0]["args"], {"project": None, "preset": "split"})
        self.assertEqual(platform["navigate"]["route"], "#/settings")
        self.assertIsNone(enforcement_chat.answer(self.factory, "What is on the roadmap?", self.p, "developer"))
        via = assistant.ask(self.factory, "Enforce security in production", persona="it", project_id=self.p.pid)
        self.assertEqual(via["propose"][0]["args"]["levels"], {"prod": {"security": "enforce"}})
        self.assertEqual(ke.cell(self.factory, self.p, "prod", "security")["level"], "advise")   # nothing changed


class CockpitTest(CockpitTestCase):
    def test_FR_ENF1_AC_1_the_routes_read_set_and_refuse_as_the_kernel_does(self):
        p = self.factory.new_project("Order desk")
        status, out, _ = self.call("PUT", "/api/enforcement", {"preset": "split", "person": IT, "persona": "it"})
        self.assertEqual((status, out["scope"], len(out["changes"])), (200, "platform", 12))
        status, out, _ = self.call("GET", f"/api/projects/{p.pid}/enforcement")
        self.assertEqual((status, out["strictest"]), (200, {"dev": "advise", "test": "require_review",
                                                            "prod": "enforce"}))
        self.assertTrue(all(c["scope"] == "platform" for c in out["cells"]))
        self.assertEqual(out["platform_levels"]["prod"]["legal"], "enforce")
        status, out, _ = self.call("PUT", f"/api/projects/{p.pid}/enforcement",
                                   {"levels": {"prod": {"legal": "advise"}}, "person": "", "persona": "it"})
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("POST", "/api/enforcement/preview",
                                   {"project": p.pid, "levels": {"prod": {"legal": "advise"}}, "person": DEV,
                                    "persona": "developer"})
        self.assertEqual((status, out["changes"][0]["to"], out["changes"][0]["to_scope"]), (200, "advise", "project"))
        status, out, _ = self.call("GET", "/api/enforcement")
        self.assertEqual((status, out["history"][0]["person"]), (200, IT))

    def test_FR_ENF1_AC_7_the_view_reads_the_pipeline_on_request(self):
        p = self.factory.new_project("Order desk")
        self.call("PUT", f"/api/projects/{p.pid}/enforcement", {"repo": REPO, "person": DEV, "persona": "developer"})
        with mock.patch.object(enforcement_pipeline, "gh", FakeGh()):
            status, out, _ = self.call("GET", f"/api/projects/{p.pid}/enforcement?pipeline=1")
        self.assertEqual((status, out["pipeline"]["repo"], len(out["compare"]["rows"])), (200, REPO, 3))
        status, out, _ = self.call("GET", f"/api/projects/{p.pid}/enforcement")
        self.assertNotIn("pipeline", out)

    def test_FR_ENF1_AC_9_the_view_the_settings_card_and_the_controls_are_wired(self):
        static = Path(__file__).resolve().parent.parent / "cockpit" / "static"
        caps = (static / "capsules.js").read_text(encoding="utf-8")
        self.assertIn('registerView({ id: "enforcement", capsule: "govern"', caps)
        self.assertIn("enforcementSettingsCard()", (static / "screens.js").read_text(encoding="utf-8"))
        status, ui, _ = self.call("GET", "/api/ui-map")
        self.assertIn("enforcement", {v["id"] for v in ui["views"]})
        ids = {c["id"] for c in ui["controls"]}
        self.assertLessEqual({"enforcement_levels", "enforcement_platform", "enforcement_preview",
                              "enforcement_pipeline", "enforcement_take_pipeline"}, ids)
        from cockpit.solo_routes import NEEDS

        for name in ("put_enforcement", "put_project_enforcement", "post_enforcement_preview"):
            self.assertEqual(NEEDS[name](self.factory, {}, {}), tuple(ke.SETTERS), name)
        js = (static / "enforcement.js").read_text(encoding="utf-8")
        self.assertIn("emptyState(", js)
        self.assertIn("Ask Rihma why and how", js)
        self.assertEqual(json.loads(json.dumps(ke.describe(self.factory)))["meta"]["default_level"], "advise")


class SeparateRecordsTest(FactoryTestCase):
    """Acceptance (2026-11-26, blocker): saving levels was read back as opting out of Gnomon's enforcement."""

    def test_saving_levels_leaves_gnomon_enforcement_on_and_uses_its_own_record_kind(self):
        from kernel import harness_enforcement as he

        p = self.new(title="Order desk")
        ke.set_levels(self.factory, None, preset="split", person=IT, persona="it")
        ke.set_levels(self.factory, p, preset="split", person=COMP, persona="compliance")
        st = he.state(self.factory, p)
        self.assertEqual((st["on"], st["from"], st["platform"]["on"]), (True, "default", True), st)
        self.assertIn("(the default)", st["said"])
        self.assertNotEqual(ke.LEVELS_KIND, he.KIND)
        self.assertEqual(p.ledger().of_kind(he.KIND), [])
        self.assertTrue(p.ledger().of_kind(ke.LEVELS_KIND))
        self.assertEqual(ke.history(self.factory, p)[0]["person"], COMP)

    def test_a_levels_record_kept_under_the_old_kind_is_not_read_as_an_opt_out(self):
        from kernel import harness_enforcement as he

        p = self.new(title="Order desk")
        p.log("enforcement_set", {"scope": "project", "changes": [{"env": "prod"}], "person": IT, "persona": "it"})
        self.assertTrue(he.state(self.factory, p)["on"])
        self.assertIsNone(he.timeline(self.factory, p)("2999-01-01", 10**6)["record"])
        self.assertEqual(ke.history(self.factory, p)[0]["person"], IT)

    def test_the_levels_proposal_and_the_opt_out_control_have_different_ids(self):
        out = enforcement_chat.answer(self.factory, "Use the split for all projects", None, "it")
        self.assertEqual(out["propose"][0]["action"], "enforcement_levels_set")
        js = (Path(__file__).resolve().parent.parent / "cockpit" / "static" / "enforcement.js").read_text("utf-8")
        self.assertIn("enforcement_levels_set: {", js)
        self.assertNotIn("  enforcement_set: {", js)

    def test_the_preview_names_personas_in_words_and_counts_what_save_counts(self):
        p = self.new(title="Order desk")
        seen = preview(self.factory, p, preset="split")     # development's advise is already in force: 8 differ
        nexts = " ".join(c["next"] for c in seen["changes"])
        self.assertIn("IT / partner", nexts)
        self.assertNotIn("the it ", nexts)
        self.assertNotIn("the compliance", nexts)
        saved = ke.set_levels(self.factory, p, preset="split", person=IT, persona="it")
        self.assertEqual(seen["lines"][0], f"{len(saved['changes'])} settings would change.")


if __name__ == "__main__":
    unittest.main()
