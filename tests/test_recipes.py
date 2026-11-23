"""Recipes and sandbox trials (FR-Q8): a proven capability becomes a recipe, a new need is matched to a
recipe first, and a sandbox trial is time-boxed and waits for a named person."""

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import model  # noqa: E402
from test_deliver import LOCAL_ROADS, DeliveryTestCase  # noqa: E402

from kernel import recipes  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.deliver import deliver  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.operate import load_scenarios, smoke  # noqa: E402
from kernel.packs import build_pack  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.roads import slot_state  # noqa: E402
from kernel.signals import receive  # noqa: E402
from kernel.store import write_json  # noqa: E402

PARAMETERS = [{"name": "approver", "question": "Who approves a loan?"}, "Which kinds of items are lent?"]


class RecipeTestCase(DeliveryTestCase):
    maturity = "explore"

    def valid_pack(self) -> dict:
        """The fixture builds one task of four, so its pack is not valid. With every criterion verified,
        it stands for a finished product: the pack is built by build_pack as always."""
        from kernel.status import evidence as real

        with mock.patch("kernel.status.evidence", side_effect=lambda p: [dict(c, state="verified") for c in real(p)]):
            return build_pack(self.project)

    def saved(self) -> dict:
        deliver(self.project)
        self.valid_pack()
        return recipes.save(self.project, parameters=PARAMETERS, person="Aino", persona="product_owner")


class SaveTest(RecipeTestCase):
    def test_FR_Q8_AC_1_a_recipe_is_saved_only_from_a_valid_pack_by_an_allowed_person(self):
        def save(**kw):
            return recipes.save(self.project, parameters=PARAMETERS, **({"person": "Aino", "persona": "product_owner"} | kw))

        with self.assertRaisesRegex(DecisionRefused, "no delivered release"):
            save()
        deliver(self.project)
        with self.assertRaisesRegex(DecisionRefused, "no capability pack yet"):
            save()
        invalid = build_pack(self.project)
        self.assertFalse(invalid["acceptance"]["valid"])
        with self.assertRaisesRegex(DecisionRefused, "is not valid: R-"):
            save()
        pack = self.valid_pack()
        self.assertEqual((pack["version"], pack["acceptance"]["valid"]), ("1.1.0", True))
        for person, persona in (("Pekka", "developer"), ("Sanna", "stakeholder"), ("factory", "it")):
            with self.assertRaises(DecisionRefused):
                save(person=person, persona=persona)
        with self.assertRaisesRegex(ValueError, "needs a question"):
            recipes.save(self.project, parameters=[{"name": "x"}], person="Aino", persona="product_owner")
        path = self.project.path("releases", "1", "capability-pack.json")
        edited = json.loads(path.read_text(encoding="utf-8"))
        write_json(path, dict(edited, title="Something else"))                  # edited after it was written
        with self.assertRaisesRegex(DecisionRefused, "does not match its record"):
            save()
        self.valid_pack()
        recipe = save(persona="it", person="Ilkka")
        self.assertEqual((recipe["id"], recipe["profile"], recipe["from_project"]), ("RC-001", "web_service", self.project.pid))
        self.assertEqual(recipe["pack"], {"version": "1.1.0", "content_sha256": pack["content_sha256"], "release": 1})
        self.assertEqual(recipe["spec"], self.project.read("spec.json"))
        self.assertEqual(recipe["contract"]["revision"], self.project.read("contract.json")["revision"])
        self.assertEqual([r["id"] for r in recipe["contract"]["requirements"]],
                         [r["id"] for r in self.project.read("spec.json")["requirements"]])
        self.assertEqual([p["name"] for p in recipe["parameters"]], ["approver", "which-kinds-of-items-are-lent"])
        self.assertIn("equipment", recipe["keywords"])
        with self.assertRaisesRegex(ValueError, "already recipe RC-001"):
            save()
        saved = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("recipe_saved")]
        self.assertEqual([(s["recipe"], s["by"], s["persona"]) for s in saved], [("RC-001", "Ilkka", "it")])


class MatchTest(RecipeTestCase):
    def test_FR_Q8_AC_1_a_need_is_matched_by_rule_and_instantiated_with_its_parameters_as_questions(self):
        recipe = self.saved()
        found = recipes.match(self.factory, "The lab needs to track equipment loans too")
        self.assertEqual([m["recipe"] for m in found], ["RC-001"])
        self.assertEqual(found[0]["keywords"], ["equipment", "loans", "track"])
        self.assertEqual(found[0]["parameters"], ["Who approves a loan?", "Which kinds of items are lent?"])
        self.assertEqual(recipes.match(self.factory, "Sync orders from SAP to our CRM via a webhook"), [])
        self.assertEqual(recipes.match(self.factory, "Our equipment"), [])        # one word, no profile named
        portal = recipes.match(self.factory, "A web portal for equipment")       # one word and its profile
        self.assertEqual([(m["recipe"], m["keywords"], m["same_profile"]) for m in portal],
                         [("RC-001", ["equipment"], True)])
        signal = receive(self.factory, "Our lab keeps losing track of borrowed equipment", channel="chat",
                         source="#lab", person="Sanna")
        self.assertEqual([m["recipe"] for m in recipes.match_signal(self.factory, signal["id"])], ["RC-001"])
        with self.assertRaises(DecisionRefused):
            recipes.instantiate(self.factory, "RC-001", title="Lab loans", parameters={}, person="Pekka",
                                persona="developer")
        with self.assertRaisesRegex(ValueError, "no parameter colour"):
            recipes.instantiate(self.factory, "RC-001", title="Lab loans", parameters={"colour": "red"},
                                person="Aino", persona="business_owner")
        new = recipes.instantiate(self.factory, "RC-001", title="Lab equipment loans",
                                  parameters={"approver": "the lab manager"}, person="Aino", persona="business_owner")
        meta = new.meta
        self.assertEqual((meta["maturity"], meta["profile"], meta["approve_plan"], meta["stage"]),
                         ("explore", "web_service", True, 2))
        self.assertEqual(meta["recipe"], {"id": "RC-001", "pack": recipe["pack"]["version"], "from": self.project.pid})
        spec = new.read("spec.json")
        self.assertEqual(spec["title"], "Lab equipment loans")
        self.assertEqual([r["id"] for r in spec["requirements"]], [r["id"] for r in recipe["spec"]["requirements"]])
        self.assertEqual({r["provenance"] for r in spec["requirements"]}, {"vendor-proposed"})  # this owner confirms later
        self.assertFalse(any("decided_by" in r for r in spec["requirements"]))
        canon = Canon(new)
        answered, open_ = canon.questions("answered"), canon.questions("open")
        self.assertEqual([(q["text"], q["answer"]["text"], q["answer"]["by"]) for q in answered],
                         [("Who approves a loan?", "the lab manager", "Aino")])
        self.assertEqual([(q["text"], q["blocking"]) for q in open_], [("Which kinds of items are lent?", True)])
        self.assertEqual(canon.get_card(open_[0]["card"])["kind"], "question")   # put to a person
        self.assertIn("From recipe RC-001", canon.brief)
        out = advance(new, model=model())                                          # nothing built around it
        self.assertEqual((out["state"], out["stage"]), ("waiting", 4))
        self.assertFalse(new.path("contract.json").exists())
        used = factory_project(self.factory).ledger().of_kind("recipe_used")[-1]["event"]["payload"]
        self.assertEqual((used["project"], used["by"], used["open"]), (new.pid, "Aino", [open_[0]["id"]]))


class TrialTest(RecipeTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(recipes.stop_watchdogs)

    def test_FR_Q8_AC_2_a_trial_is_time_boxed_stopped_automatically_and_waits_for_the_named_person(self):
        with self.assertRaises(DecisionRefused):
            recipes.trial(self.project, 30, person="Sanna", persona="stakeholder", watchdog=False)
        for ttl in (0, -5, 24 * 60 + 1, True):
            with self.assertRaises(ValueError):
                recipes.trial(self.project, ttl, person="Aino", persona="product_owner", watchdog=False)
        t = recipes.trial(self.project, 30, person="Aino", persona="product_owner", watchdog=False)
        self.assertEqual((t["trial"], t["state"], t["delivery"], t["expires_at"]), (1, "running", "done", "2026-11-22T12:30:00Z"))
        self.assertTrue(t["preview"].startswith("http://127.0.0.1:"))
        self.assertTrue(smoke(t["preview"])["ok"])
        scenarios = len(load_scenarios(self.project))
        self.assertGreater(scenarios, 0)
        self.assertEqual((t["holdouts"]["verdict"], t["holdouts"]["passed"], t["holdouts"]["scenarios"]),
                         ("passed", scenarios, scenarios))
        for words in ("runs as a local preview", "holdout scenario", "passed.", "It stops by itself at "
                      "2026-11-22T12:30:00Z, after 30 minutes", "Aino decides: promote it to a normal project"):
            self.assertIn(words, t["result"])
        card = Canon(self.project).get_card(t["card"])
        self.assertEqual((card["kind"], card["refs"]["scope"], card["payload"]["waits_for"], card["blocking"]),
                         ("approval", "trial", "Aino", True))
        written = self.project.path("trials.json").read_text(encoding="utf-8") + json.dumps(card)
        for scenario in load_scenarios(self.project):                               # scores only, never scenarios
            for s in scenario["steps"]:
                if s.get("body"):
                    self.assertNotIn(json.dumps(s["body"]), written)
        self.assertNotIn("expect_", written)
        with self.assertRaisesRegex(DecisionRefused, "trial 1 still runs"):
            recipes.trial(self.project, 30, person="Aino", persona="product_owner", watchdog=False)
        self.clock.advance(minutes=29)
        self.assertEqual(recipes.expire(self.project), [])                         # not yet
        self.assertIsNotNone(slot_state(self.project, "preview", "current"))
        self.clock.advance(minutes=1)
        self.assertEqual(recipes.sweep(self.factory)["stopped"], [(self.project.pid, 1)])
        self.assertIsNone(slot_state(self.project, "preview", "current"))
        self.assertFalse(smoke(t["preview"])["ok"])
        stopped = recipes.trials(self.project)[0]
        self.assertEqual((stopped["state"], stopped["stopped"]["why"]), ("stopped", "its time limit passed"))
        self.assertIn("It was stopped automatically at 2026-11-22T12:30:00Z", stopped["result"])
        self.assertEqual(Canon(self.project).get_card(t["card"])["state"], "open")   # the outcome still waits
        # only the named person decides: not through the trial, and not through the Inbox
        with self.assertRaisesRegex(DecisionRefused, "waits for Aino"):
            recipes.decide(self.project, 1, "promote", person="Pekka", persona="developer")
        Canon(self.project).decide(t["card"], "approve", person="Pekka", persona="developer")
        self.assertEqual(recipes.settle(self.project), [])
        again = recipes.trials(self.project)[0]
        self.assertIn("decided by Pekka, but trial 1 waits for Aino; asked again", again["note"])
        self.assertNotEqual(again["card"], t["card"])
        self.assertEqual(self.project.meta["maturity"], "explore")                 # nothing was applied
        done = recipes.decide(self.project, 1, "promote", person="Aino", persona="product_owner", reason="it works")
        self.assertEqual((done["state"], done["decision"]["verdict"], done["decision"]["maturity"]),
                         ("promoted", "promote", "demo"))
        self.assertEqual((self.project.meta["maturity"], self.project.meta["redeliver"]), ("demo", True))
        with self.assertRaisesRegex(ValueError, "explore maturity"):
            recipes.trial(self.project, 30, person="Aino", persona="product_owner", watchdog=False)
        kinds = [r["event"]["kind"] for r in self.project.ledger().records()]
        for kind in ("trial_started", "trial_stopped", "trial_asked_again", "trial_decided"):
            self.assertIn(kind, kinds)

    def test_FR_Q8_AC_2_the_watchdog_stops_the_preview_when_no_one_calls_and_a_discard_stops_the_project(self):
        t = recipes.trial(self.project, 0.04, person="Aino", persona="business_owner")   # 2.4 seconds
        self.assertEqual(t["watchdog"]["after_seconds"], 0.04 * 60)
        self.assertTrue(smoke(t["preview"])["ok"])
        deadline = time.monotonic() + 90
        while recipes.trials(self.project)[0]["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.5)
        stopped = recipes.trials(self.project)[0]
        self.assertEqual((stopped["state"], stopped["stopped"]["why"]), ("stopped", "its time limit passed"),
                         self.project.path("trials", "1-watchdog.log").read_text(encoding="utf-8", errors="replace"))
        self.assertIsNone(slot_state(self.project, "preview", "current"))
        self.assertFalse(smoke(t["preview"])["ok"])
        done = recipes.decide(self.project, 1, "discard", person="Aino", persona="business_owner", reason="not needed")
        self.assertEqual(done["state"], "discarded")
        self.assertTrue(self.project.meta["halted"])
        self.assertEqual(self.project.meta["discarded"]["by"], "Aino")
        with self.assertRaisesRegex(DecisionRefused, "stopped or discarded"):
            recipes.trial(self.project, 30, person="Aino", persona="business_owner", watchdog=False)

    def test_FR_Q8_AC_2_a_trial_that_cannot_start_says_so_and_still_waits_for_the_person(self):
        write_json(self.factory.paved_roads_path, dict(LOCAL_ROADS, maturity={"explore": "no-such-road"}))
        t = recipes.trial(self.project, 30, person="Aino", persona="product_owner")
        self.assertEqual((t["state"], t["preview"], t["holdouts"], t["watchdog"]), ("failed", None, None, None))
        self.assertIn("did not start: it waits on card", t["result"])
        self.assertIn("Nothing runs", t["result"])
        self.assertEqual(Canon(self.project).get_card(t["card"])["payload"]["waits_for"], "Aino")


if __name__ == "__main__":
    unittest.main()
