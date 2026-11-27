"""Enforcement levels, made right (FR-ENF2): rulesets, a card that never strands its solo reviewer, approvals tied to
what was seen, stage names by whole words, the gate's own stage, Ask Rihma's gaps, the override's reason and one id
per decision.

The owner (2026-11-25): "in testing and production we wouldn't want any critical changes without human checks."
Every GitHub answer comes from tests/enforcement_fakes.py FakeGh (a neutral acme/orders); nothing reaches GitHub.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from enforcement_fakes import REPO, FakeGh  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import assistant, enforcement_chat, enforcement_pipeline, status  # noqa: E402
from kernel import enforcement as ke  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.enforcement_guard import at_automation, at_deploy, at_gate, guard, recent  # noqa: E402
from kernel.enforcement_places import env_of  # noqa: E402
from kernel.gate_external import HELD_EXIT, exit_code  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OWNER, IT, DEV = "Aino Example", "Ilkka Example", "Dana Example"
NONE = {f: [] for f in ke.FAMILIES}


def found(family: str, *items: str) -> dict:
    return {**NONE, family: list(items or ["check tests: 2 failed"])}


class RulesetsTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")
        ke.set_levels(self.factory, self.p, repo=REPO, person=DEV, persona="developer")

    def test_FR_ENF2_AC_1_a_ruleset_on_main_is_read_beside_classic_protection(self):
        gh = FakeGh(protected=False, rulesets=True)
        pipe = enforcement_pipeline.read(self.p, run=gh)
        self.assertTrue(all(c[:3] == ["api", "-X", "GET"] for c in gh.calls))
        self.assertIn(["api", "-X", "GET", f"repos/{REPO}/rules/branches/main"], gh.calls)
        prot = pipe["protection"]
        self.assertEqual((prot["protected"], prot["readable"], prot["pull_request"], prot["required_reviews"]),
                         (True, True, True, 0))
        self.assertEqual((prot["required_checks"], prot["sources"]), (["ci", "lint"], ["ruleset Protect main"]))
        dev = next(r for r in enforcement_pipeline.compare(ke.describe(self.factory, self.p), pipe)["rows"]
                   if r["env"] == "dev")
        self.assertIn("only through a pull request and the checks ci, lint", dev["pipeline_says"])
        self.assertNotIn("takes a merge without a review", dev["pipeline_says"])
        self.assertEqual((dev["pipeline_human"], dev["state"]), (False, "agree"))
        both = enforcement_pipeline.read(self.p, run=FakeGh(rulesets=True))["protection"]
        self.assertEqual((both["required_reviews"], both["required_checks"], both["sources"]),
                         (1, ["tests", "ci", "lint"], ["branch protection", "ruleset Protect main"]))
        none = enforcement_pipeline.read(self.p, run=FakeGh(protected=False))["protection"]
        self.assertEqual((none["protected"], none["readable"]), (False, True))


class NeverStrandedTest(CockpitTestCase):
    """A solo owner looking as business owner meets the IT card that holds a release, and decides it."""

    def setUp(self):
        super().setUp()
        self.p = self.factory.new_project("Order desk")
        ke.set_levels(self.factory, self.p, levels={"prod": {"security": "enforce"}}, person=IT, persona="it")
        self.held = at_deploy(self.p, "production", 7, {"blocking": ["SEC-1 a secret in the repository"]})

    def test_FR_ENF2_AC_2_the_card_shows_in_both_inboxes_the_banner_and_the_words_say_where(self):
        cid = self.held["card"]
        self.assertIn("IT", self.held["waiting_on"])
        self.assertIn("Enforcement view", self.held["waiting_on"])
        self.assertIn("view as everything", self.held["waiting_on"])
        status_, box, _ = self.call("GET", f"/api/projects/{self.p.pid}/inbox?persona=business_owner")
        self.assertEqual(status_, 200)
        self.assertEqual([(c["id"], c["decide_as"]) for c in box["elsewhere"]], [(cid, "it")])
        status_, every, _ = self.call("GET", "/api/inbox?persona=business_owner")
        self.assertEqual([c["id"] for c in every["elsewhere"]], [cid])
        status_, mine, _ = self.call("GET", f"/api/projects/{self.p.pid}/inbox?persona=it")
        self.assertEqual(mine["elsewhere"], [])
        now = status.now(self.p)
        self.assertEqual(now["state"], "waiting_on_you")
        self.assertIn(cid, now["cards"])

    def test_FR_ENF2_AC_2_the_owner_decides_it_in_place_signed_as_the_role_it_needs(self):
        cid = self.held["card"]
        body = {"verdict": "approve", "reason": "the secret was rotated", "person": OWNER,
                "persona": "business_owner", "as_needed": True}
        status_, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/cards/{cid}/decide", body)
        self.assertEqual(status_, 200, out)
        self.assertEqual((out["decision"]["persona"], out["decision"]["person"]), ("it", OWNER))
        self.assertIsNone(at_deploy(self.p, "production", 7, {"blocking": ["SEC-1 a secret in the repository"]}))


class SeenTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")
        self.canon = Canon(self.p)

    def set(self, levels, **kw):
        ke.set_levels(self.factory, self.p, levels=levels, person=OWNER, persona="business_owner", **kw)

    def test_FR_ENF2_AC_3_one_approval_lets_one_firing_of_an_automation_through(self):
        self.set({"dev": {"governance": "enforce"}})
        a = {"id": "AU-001", "action": {"kind": "advance", "project": self.p.pid}}
        firing = {"project": self.p.pid}
        first = at_automation(self.factory, a, firing)
        card = first["enforcement"]["checked"][0]["card"]
        self.assertEqual(at_automation(self.factory, a, firing)["enforcement"]["checked"][0]["card"], card)
        self.canon.decide(card, "approve", person=OWNER, persona="business_owner", reason="one run, watched")
        self.assertIsNone(at_automation(self.factory, a, firing))                  # firing 2: the approval
        third = at_automation(self.factory, a, firing)                              # firing 3: asks again
        self.assertIsNotNone(third)
        self.assertNotEqual(third["enforcement"]["checked"][0]["card"], card)
        self.assertEqual([r["outcome"] for r in recent(self.p)][:2], ["refused", "cleared"])

    def test_FR_ENF2_AC_3_an_approval_covers_what_was_seen_and_a_refusal_says_what_holds(self):
        self.set({"prod": {"security": "enforce"}})
        held = at_deploy(self.p, "production", "r-7", {"blocking": ["SEC-1"]})
        self.canon.decide(held["card"], "approve", person=OWNER, persona="it", reason="accepted risk")
        self.assertIsNone(at_deploy(self.p, "production", "r-7", {"blocking": ["SEC-1"]}))
        again = at_deploy(self.p, "production", "r-7", {"blocking": ["SEC-1", "SEC-2 a new finding"]})
        self.assertIsNotNone(again)
        self.assertNotEqual(again["card"], held["card"])
        self.assertIn("SEC-2", self.canon.get_card(again["card"])["body"])
        self.canon.decide(again["card"], "refuse", person=OWNER, persona="it", reason="fix SEC-2 first")
        refused = at_deploy(self.p, "production", "r-7", {"blocking": ["SEC-1", "SEC-2 a new finding"]})
        self.assertEqual(refused["card"], again["card"])
        self.assertIn(f"{again['card']} was refused by {OWNER}", refused["waiting_on"])
        self.assertIn("fix SEC-2 first", refused["waiting_on"])
        self.assertNotIn("waits for", refused["waiting_on"])
        fixed = at_deploy(self.p, "production", "r-7", {"blocking": ["SEC-1"]})     # what was approved before
        self.assertIsNone(fixed)

    def test_FR_ENF2_AC_3_an_open_card_that_saw_something_else_is_withdrawn_for_a_new_one(self):
        self.set({"prod": {"security": "enforce"}})
        first = at_deploy(self.p, "production", 8, {"blocking": ["SEC-1"]})
        second = at_deploy(self.p, "production", 8, {"blocking": ["SEC-1", "SEC-3"]})
        self.assertNotEqual(first["card"], second["card"])
        self.assertEqual(self.canon.get_card(first["card"])["state"], "withdrawn")


class NamesTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")

    def test_FR_ENF2_AC_4_names_are_placed_by_whole_words_and_an_unknown_one_counts_as_production(self):
        expect = {"productivity-tools": None, "latest": None, "contest": None, "protest": None, "eu-west": None,
                  "customer-a": None, "prod-eu": "prod", "staging2": "test", "qa": "test", "pre-prod": "test",
                  "pre_production": "test", "production": "prod", "demo": "dev", "live": "prod"}
        self.assertEqual({k: env_of(k) for k in expect}, expect)
        ke.set_levels(self.factory, self.p, levels={"prod": {"governance": "require_review"}}, person=OWNER,
                      persona="business_owner")
        out = guard(self.p, env="eu-west", source="deploy", subject="release 1", found=NONE)
        self.assertEqual((out["env"], out["placed"]["how"], out["outcome"]), ("prod", "unknown", "review"))
        self.assertIn("'eu-west' is not a stage name Rihmasto knows", out["says"])
        with self.assertRaisesRegex(ValueError, "needs a reason"):
            ke.set_levels(self.factory, self.p, names={"eu-west": "dev"}, person=OWNER, persona="business_owner")
        ke.set_levels(self.factory, self.p, names={"EU-West": "test"}, person=OWNER, persona="business_owner",
                      reason="our acceptance region")
        self.assertEqual(guard(self.p, env="eu-west", source="deploy", subject="release 2", found=NONE)["env"], "test")
        self.assertEqual(ke.describe(self.factory, self.p)["names"],
                         [{"name": "eu-west", "env": "test", "scope": "project"}])
        ke.set_levels(self.factory, None, names={"customer-a": "prod"}, person=IT, persona="it")
        self.assertEqual(ke.place(self.factory, self.p, "customer-a")["scope"], "platform")


class GateStageTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")

    def test_FR_ENF2_AC_5_the_gate_asks_its_stage_and_an_enforce_level_holds_the_change(self):
        ke.set_levels(self.factory, self.p, levels={"test": {"quality": "enforce"}}, person=OWNER,
                      persona="business_owner")
        self.assertEqual(at_gate(self.p, "failed", "repo:abc", "a" * 40)["env"], "dev")   # development by default
        ke.set_levels(self.factory, self.p, gate_env="test", person=OWNER, persona="business_owner")
        out = at_gate(self.p, "failed", "repo:abc", "b" * 40)
        self.assertEqual((out["env"], out["outcome"], out["held"], out["stage_scope"]),
                         ("test", "refused", True, "project"))
        self.assertEqual(exit_code("passed", {"card": "C-1"}), HELD_EXIT)
        self.assertEqual((exit_code("passed", None), exit_code("failed", {"card": "C-1"})), (0, 1))
        with self.assertRaisesRegex(ValueError, "needs a reason"):
            ke.set_levels(self.factory, self.p, gate_env="dev", person=OWNER, persona="business_owner")
        self.assertEqual(ke.describe(self.factory, self.p)["gate_env"], {"env": "test", "scope": "project"})


class ChatTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(title="Order desk")

    def ask(self, q, persona="business_owner"):
        return assistant.ask(self.factory, q, persona=persona, project_id=self.p.pid)

    def test_FR_ENF2_AC_6_ask_rihma_takes_the_ways_people_say_it_by_rule(self):
        ke.set_levels(self.factory, self.p, preset="split", person=OWNER, persona="business_owner")
        off = self.ask("Turn off checks in production")
        self.assertEqual((off["matches"], off["propose"]), (["enforcement"], []))
        self.assertIn("needs your reason", off["answer"])
        why = self.ask("Turn off checks in production because the demo week ends Friday")
        (prop,) = why["propose"]
        self.assertEqual(prop["args"]["levels"], {"prod": {f: "off" for f in ke.FAMILIES}})
        self.assertEqual(prop["args"]["reason"], "the demo week ends Friday")
        legal = self.ask("Make staging require review for legal")
        self.assertEqual(legal["matches"], ["enforcement"])
        self.assertIn("already", legal["answer"])             # the split already reviews testing
        block = self.ask("Block deploys to prod")
        self.assertEqual(block["matches"], ["enforcement"])
        everywhere = self.ask("Advise everywhere because we are still exploring")
        self.assertEqual(everywhere["propose"][0]["args"]["project"], self.p.pid)    # every stage, this project
        self.assertEqual(everywhere["navigate"]["route"], f"#/p/{self.p.pid}/enforcement")
        name = self.ask("Treat eu-west as testing because it is our acceptance region")
        self.assertEqual(name["propose"][0]["args"]["names"], {"eu-west": "test"})
        gate = enforcement_chat.answer(self.factory, "The gate's changes go to production", self.p, "developer")
        self.assertEqual(gate["propose"][0]["args"]["gate_env"], "prod")
        js = (ROOT / "cockpit" / "static" / "enforcement.js").read_text(encoding="utf-8")
        self.assertNotIn("asked in Ask Rihma", js)
        self.assertIn("reason: a.reason", js)


class OverrideReasonTest(CockpitTestCase):
    def test_FR_ENF2_AC_7_approving_held_work_needs_a_reason_and_a_review_does_not(self):
        p = self.factory.new_project("Order desk")
        ke.set_levels(self.factory, p, levels={"prod": {"security": "enforce"}, "test": {"security": "require_review"}},
                      person=IT, persona="it")
        held = at_deploy(p, "production", 1, {"blocking": ["SEC-1"]})["card"]
        status_, out, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{held}/decide",
                                    {"verdict": "approve", "reason": " ", "person": IT, "persona": "it"})
        self.assertGreaterEqual(status_, 400, out)
        self.assertEqual(Canon(p).get_card(held)["state"], "open")
        with self.assertRaisesRegex(DecisionRefused, "override: say why"):
            Canon(p).decide(held, "approve", person=IT, persona="it")
        Canon(p).decide(held, "approve", person=IT, persona="it", reason="rotated")
        guard(p, env="staging", source="deploy", subject="release 1", found=found("security", "SEC-1"))
        review = next(c for c in Canon(p).cards(kind="enforcement") if not c["blocking"])
        Canon(p).decide(review["id"], "approve", person=IT, persona="it")             # a look, not an override
        js = (ROOT / "cockpit" / "static" / "decide.js").read_text(encoding="utf-8")
        self.assertIn('c.kind === "enforcement" && v === "approve" && !!c.blocking', js)


class DecisionIdsTest(unittest.TestCase):
    def test_FR_ENF2_AC_8_every_decision_has_its_own_id_matching_its_file(self):
        ids = {}
        for path in sorted((ROOT / "decisions").glob("D-*.md")):
            head = re.search(r"^id:\s*(D-\d{4})\s*$", path.read_text(encoding="utf-8"), re.M)
            self.assertIsNotNone(head, path.name)
            self.assertTrue(path.name.startswith(head.group(1) + "-"), path.name)
            ids.setdefault(head.group(1), []).append(path.name)
        self.assertEqual({k: v for k, v in ids.items() if len(v) > 1}, {})
        self.assertIn("D-0026", ids)
        for rel in ("kernel/enforcement.py", "kernel/enforcement_guard.py", "kernel/enforcement_preview.py",
                    "cockpit/enforcement_routes.py", "contract/contract.json"):
            self.assertNotIn("D-0025-enforcement", (ROOT / rel).read_text(encoding="utf-8"), rel)
            self.assertNotIn("(D-0025", (ROOT / rel).read_text(encoding="utf-8"), rel)


if __name__ == "__main__":
    unittest.main()
