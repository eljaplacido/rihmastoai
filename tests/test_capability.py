import json
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402
from test_deliver import DeliveryTestCase  # noqa: E402

from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.model import FakeModel, ModelError  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


class ProfileTest(FactoryTestCase):
    def test_FR_A9_AC_1_a_profile_is_proposed_by_rule_and_shapes_intake_questions_and_spec(self):
        from kernel.profiles import PROFILES, propose_profile
        from kernel.spec import spec_prompt

        self.assertEqual(propose_profile(IDEA)["profile"], "web_service")            # nothing stands out
        self.assertEqual(propose_profile("Sync orders from SAP to our CRM via a webhook")["profile"], "integration")
        self.assertEqual(propose_profile("Train a classifier on our dataset, F1 above 0.9")["profile"], "ml_pipeline")
        self.assertEqual(propose_profile("Run a GDPR and AI Act compliance check on HR logs")["profile"], "ops_agent")
        p = self.new(mode="assume")
        intake(p, "Sync orders from SAP to our CRM via a webhook", model=model(), requested_by="Aino")
        self.assertEqual(p.meta["profile"], "integration")
        texts = [q["text"] for q in Canon(p).questions()]
        for seed in PROFILES["integration"]["seed_questions"]:
            self.assertIn(seed["text"], texts)                                      # its own questions, once
        self.assertNotIn("What look and feel", " ".join(texts))                     # no screens: no look question
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        self.assertIn("profile_chosen", kinds)
        self.assertIn("Integration or connector", spec_prompt(p))
        chosen = self.factory.new_project("Phone demo", profile="mobile_prototype")
        intake(chosen, IDEA, model=model(), requested_by="Aino")                    # a person's choice stands
        self.assertEqual(chosen.meta["profile"], "mobile_prototype")
        with self.assertRaises(ValueError):
            self.factory.new_project("x", profile="no-such")
        self.assertEqual({p_["deliverable"] for p_ in PROFILES.values()}, {"product", "capability_pack", "report"})


class SignalTest(FactoryTestCase):
    def test_FR_P1_AC_1_signals_become_a_change_on_their_project_or_a_concept_a_person_validates(self):
        from kernel.pipeline import advance
        from kernel.signals import apply_concepts, edit_concept, receive, signals, square, triage

        loans = self.new(mode="assume", title="Equipment loans")
        intake(loans, IDEA, model=model(), requested_by="Aino")
        s1 = receive(self.factory, "The equipment loans page should show overdue loans first",
                     channel="chat", source="#ops-team", person="Sanna")
        out = triage(self.factory, s1["id"])
        self.assertEqual((out["state"], out["routed_to"]["project"]), ("routed", loans.pid))
        card = Canon(loans).get_card(out["routed_to"]["card"])
        self.assertEqual(card["kind"], "change")
        self.assertIn(f"signal {s1['id']} via chat", card["payload"]["text"])
        s2 = receive(self.factory, "Warehouse staff need a way to report damaged pallets from a phone",
                     channel="feed", source="service desk export")
        out = triage(self.factory, s2["id"])
        self.assertEqual(out["state"], "concept")
        from kernel.learn import factory_project

        fcanon = Canon(factory_project(self.factory))
        concept = fcanon.get_card(out["routed_to"]["card"])
        self.assertEqual(concept["kind"], "concept")
        with self.assertRaises(DecisionRefused):
            fcanon.decide(concept["id"], "validate", person="Pekka", persona="developer")
        with self.assertRaises(DecisionRefused):
            edit_concept(self.factory, concept["id"], person="Pekka", persona="developer", maturity="pilot")
        edit_concept(self.factory, concept["id"], person="Aino", persona="business_owner", maturity="demo",
                     profile="mobile_prototype", title="Damaged pallet reports")
        self.assertEqual(len(square(self.factory)["concepts_waiting"]), 1)
        fcanon.decide(concept["id"], "validate", person="Aino", persona="business_owner")
        done = apply_concepts(self.factory)
        self.assertEqual(done[0]["verdict"], "validate")
        new = self.factory.project(done[0]["project"])
        self.assertEqual((new.meta["title"], new.meta["profile"]), ("Damaged pallet reports", "mobile_prototype"))
        self.assertEqual(apply_concepts(self.factory), [])                         # once
        self.assertEqual(next(s for s in signals(self.factory) if s["id"] == s2["id"])["state"], "validated")
        result = advance(new, model=model())                                       # intake starts from the need
        self.assertTrue(new.path("source.json").exists())
        self.assertIn("intake from the validated need", result["history"])
        with self.assertRaises(ValueError):
            receive(self.factory, "x", channel="carrier pigeon", source="?")


class EmbedTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new(mode="assume", title="Equipment loans")
        intake(self.p, IDEA, model=model(), requested_by="Aino")

    def test_FR_I1_AC_2_an_embed_files_end_user_feedback_only_from_allowed_origins_with_its_key(self):
        from kernel.embeds import EmbedRefused, RateLimit, check, converse, create, embeds, public, revoke, snippet

        with self.assertRaises(DecisionRefused):
            create(self.factory, kind="feedback", origins=["https://shop.example"], person="Pekka",
                   persona="developer", project_id=self.p.pid)
        with self.assertRaises(ValueError):
            create(self.factory, kind="feedback", origins=["http://evil.example"], person="Aino",
                   persona="product_owner", project_id=self.p.pid)            # plain http only for localhost
        e = create(self.factory, kind="feedback", origins=["https://shop.example/"], person="Aino",
                   persona="product_owner", project_id=self.p.pid, label="Loans page")
        key = e["key"]
        stored = embeds(self.factory)[0]
        self.assertNotIn("key", stored)
        self.assertNotIn(key, json.dumps(stored))                                    # only its hash is kept
        self.assertNotIn("key_sha256", public(stored))
        self.assertIn(f'/e/{e["id"]}/widget.js', snippet(stored, "https://feedback.example"))
        with self.assertRaises(EmbedRefused):
            check(self.factory, e["id"], "rk_wrong", "https://shop.example")
        with self.assertRaises(EmbedRefused):
            check(self.factory, e["id"], key, "https://other.example")
        history = [{"role": "person", "text": "The return button does nothing on my phone"}]
        out = converse(self.factory, e["id"], key, "https://shop.example", history)   # no model: files directly
        card = Canon(self.p).get_card(out["filed"]["id"])
        self.assertEqual((card["kind"], card["payload"]["source"]), ("change", "end_user"))
        self.assertIn("return button", card["payload"]["text"])
        # with a model, a vague message gets one clarifying question before anything is filed
        ask_back = FakeModel({"assistant": ['```json\n{"reply": "What did you expect to happen?", "ready": false}\n```']})
        before = len(Canon(self.p).cards(kind="change"))
        out = converse(self.factory, e["id"], key, "https://shop.example", [{"role": "person", "text": "broken"}],
                       model=ask_back)
        self.assertIsNone(out["filed"])
        self.assertEqual(len(Canon(self.p).cards(kind="change")), before)
        role, prompt = ask_back.calls[0]
        self.assertNotIn("R-1", prompt)                                             # no view of the canon
        limit = RateLimit(self.clock, per_minute=1)
        converse(self.factory, e["id"], key, "https://shop.example", history, rate=limit)
        with self.assertRaises(EmbedRefused):
            converse(self.factory, e["id"], key, "https://shop.example", history, rate=limit)
        revoke(self.factory, e["id"], person="Aino", persona="product_owner")
        with self.assertRaises(EmbedRefused):
            check(self.factory, e["id"], key, "https://shop.example")

    def test_FR_I1_AC_2_a_need_embed_files_a_signal_in_the_delivery_square(self):
        from kernel.embeds import converse, create
        from kernel.signals import signals

        e = create(self.factory, kind="need", origins=["http://localhost:8080"], person="Aino",
                   persona="business_owner", label="Ops chat")
        out = converse(self.factory, e["id"], e["key"], "http://localhost:8080",
                       [{"role": "person", "text": "We spend hours matching invoices to orders by hand"}])
        self.assertEqual(out["filed"]["kind"], "signal")
        self.assertEqual(signals(self.factory)[0]["channel"], "embed")


class AutonomyTest(FactoryTestCase):
    def test_FR_K4_AC_1_the_autonomy_cap_is_set_by_a_person_and_the_kernel_enforces_it(self):
        from factory_fakes import good_cell, no_findings

        from kernel.autonomy import AutonomyCapped, cap_of, describe, require, set_cap
        from kernel.lanes import Lanes
        from kernel.pipeline import advance

        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        self.assertEqual(cap_of(p), 4)
        with self.assertRaises(DecisionRefused):
            set_cap(self.factory, 2, person="Pekka", persona="developer", reason="x")
        with self.assertRaises(ValueError):
            set_cap(self.factory, 2, person="Aino", persona="business_owner", reason="")
        set_cap(self.factory, 2, person="Aino", persona="business_owner", reason="answers and proposals only for now")
        self.assertEqual(cap_of(p), 2)
        with self.assertRaises(AutonomyCapped):
            require(p, 3, "building")
        out = advance(p, model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=good_cell,
                      verifier_runner=no_findings)
        self.assertEqual(out["state"], "capped")
        self.assertIn("autonomy level 3", out["why"])
        self.assertFalse(p.meta.get("built"))
        set_cap(self.factory, 4, person="Aino", persona="business_owner", reason="pilot approved")
        set_cap(p, 3, person="Ilkka", persona="it", reason="sandbox only for this one")
        self.assertEqual(cap_of(p), 3)
        set_cap(self.factory, 2, person="Aino", persona="business_owner", reason="tighten")
        with self.assertRaises(DecisionRefused):                                    # a project never exceeds it
            set_cap(p, 4, person="Ilkka", persona="it", reason="more for this one")
        self.assertEqual(cap_of(p), 2)
        set_cap(self.factory, 4, person="Aino", persona="business_owner", reason="back to normal")
        self.assertEqual([lv["allowed"] for lv in describe(p)["levels"]], [True, True, True, False])  # its own cap of 3 stays


class PackTest(DeliveryTestCase):
    maturity = "explore"

    def test_FR_Q6_AC_1_a_release_has_a_capability_pack_pinned_by_hash_valid_only_while_its_evals_hold(self):
        from kernel.deliver import deliver
        from kernel.packs import build_pack, render_yaml

        self.factory.paved_roads_path.unlink()
        with self.assertRaises(LookupError):
            build_pack(self.project)
        deliver(self.project)
        pack = build_pack(self.project)
        self.assertEqual((pack["format"], pack["version"], pack["release"]), ("rihma.capability-pack.v1", "1.0.0", 1))
        self.assertEqual(pack["pinned"]["product_revision"], self.main())
        self.assertTrue(pack["pinned"]["contract_revision"])
        self.assertIsNone(pack["provenance"]["signature"])                          # never claims a signature
        self.assertIn("not signed", pack["provenance"]["signature_note"])
        self.assertEqual(build_pack(self.project)["version"], "1.0.0")              # same content, same version
        self.assertTrue(self.project.path("releases", "1", "capability-pack.json").exists())
        self.assertIn("rihma.capability-pack.v1", render_yaml(pack))
        self.assertIsInstance(pack["acceptance"]["valid"], bool)
        if not pack["acceptance"]["valid"]:
            self.assertTrue(pack["acceptance"]["not_valid_because"])                 # it says why

    def test_FR_Q6_AC_2_the_evidence_pack_holds_scores_never_holdout_scenarios_and_is_recorded(self):
        from kernel.deliver import deliver
        from kernel.evidence_pack import export

        self.factory.paved_roads_path.unlink()
        deliver(self.project)
        with self.assertRaises(DecisionRefused):
            export(self.project, self.tmp / "out", person="Sanna", persona="stakeholder")
        path = export(self.project, self.tmp / "out", person="Kaisa", persona="compliance")
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            self.assertLessEqual({"README.md", "MANIFEST.json", "capability-pack.json", "contract.json", "ledger.jsonl",
                                  "decisions.json", "gates.json", "ledger-check.json"}, names)
            blob = "\n".join(z.read(n).decode("utf-8") for n in names)
            manifest = json.loads(z.read("MANIFEST.json"))
        for f in self.project.holdouts_dir.glob("*.json"):
            for step in json.loads(f.read_text(encoding="utf-8")).get("steps", []):
                if step.get("body"):
                    self.assertNotIn(json.dumps(step["body"]), blob)                 # scenarios stay in custody
        self.assertEqual(set(manifest["files"]), names - {"MANIFEST.json"})
        self.assertTrue(json.loads(zipfile.ZipFile(path).read("ledger-check.json"))["intact"])
        att = json.loads(zipfile.ZipFile(path).read("attestation.json"))
        self.assertIn(att["verdict"], ("attestable", "chain broken", "insufficient evidence"))
        self.assertNotIn("compliant", json.dumps(att).replace("not a statement of conformity", ""))
        self.assertTrue(any(c["status"] == "no" for c in att["controls"]))           # says what it cannot evidence
        self.assertIn("evidence_exported", [r["event"]["kind"] for r in self.project.ledger().records()])


class ObservationTest(FactoryTestCase):
    def test_FR_V2_AC_1_one_observation_three_renderings_and_an_update_card_within_the_cap(self):
        from kernel.autonomy import set_cap
        from kernel.observations import apply_updates, observe

        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        obs = observe(self.factory, "eval_drift", facts={"project": p.pid, "criterion": "R-1-AC-1",
                                                          "before": "0.94", "after": "0.88"}, source="nightly evals")
        t = obs["touched"][0]
        self.assertEqual(set(t["views"]), {"developer", "expert", "business"})
        self.assertEqual(t["views"]["developer"]["action"], "trial")
        self.assertIn("0.88", t["views"]["expert"])
        self.assertTrue(t["views"]["business"].endswith("?"))
        card = Canon(p).get_card(t["card"])
        self.assertEqual(card["kind"], "update")
        Canon(p).decide(card["id"], "trial", person="Pekka", persona="developer")
        self.assertEqual(apply_updates(p)[0]["verdict"], "trial")
        self.assertEqual(p.meta["trial"]["approved_by"], "Pekka")
        set_cap(self.factory, 1, person="Aino", persona="business_owner", reason="answers only")
        quiet = observe(self.factory, "eval_drift", facts={"project": p.pid, "criterion": "R-1-AC-1"}, source="x")
        self.assertIsNone(quiet["touched"][0]["card"])                              # level 1: inform, no card


class CatalogueTest(FactoryTestCase):
    def test_FR_T1_AC_14_the_capability_catalogue_lists_each_capability_with_its_state(self):
        from kernel.dashboard import catalogue
        from kernel.signals import receive, triage

        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        triage(self.factory, receive(self.factory, "An assistant for maintenance manuals offline",
                                     channel="meeting", source="steering group")["id"])
        cat = catalogue(self.factory)
        states = {i["state"] for i in cat["items"]}
        self.assertEqual(states, {"shaping", "proposed"})
        self.assertEqual(cat["counts"]["proposed"], 1)
        item = next(i for i in cat["items"] if i["project"] == p.pid)
        self.assertEqual((item["profile"], item["deliverable"]), ("web_service", "product"))


class ApparatusTest(FactoryTestCase):
    def test_FR_J2_AC_2_an_unreachable_model_stops_the_pipeline_cleanly_and_a_rerun_resumes(self):
        from kernel.pipeline import advance

        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")

        class Down:
            def ask(self, prompt, *, role):
                raise ModelError("gnomon apparatus failure for role analyst: endpoint_error")

        out = advance(p, model=Down())
        self.assertEqual((out["state"], out["apparatus"]), ("apparatus_failure", True))
        self.assertIn("endpoint_error", out["why"])
        self.assertIn("apparatus_failure", [r["event"]["kind"] for r in p.ledger().records()])
        self.assertFalse(p.path("spec.json").exists())                              # nothing half-written
        from factory_fakes import good_cell, no_findings

        from kernel.lanes import Lanes

        again = advance(p, model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=good_cell,
                        verifier_runner=no_findings, max_steps=3)
        self.assertTrue(p.path("spec.json").exists())
        self.assertNotEqual(again["state"], "apparatus_failure")


if __name__ == "__main__":
    unittest.main()
