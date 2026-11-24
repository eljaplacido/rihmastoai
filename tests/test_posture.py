"""Postures and priority weights (FR-POS1 to FR-POS5): one choice that sets how a project runs.

Every effect is a rule in the kernel (kernel/posture.py, kernel/posture_rules.py), previewed before
anyone chooses, recorded with who chose it, and said now and later when it changes during the run
(kernel/posture_change.py). A project without a posture runs exactly as before.
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, generic_cell, model, no_findings, script  # noqa: E402

from adapters.sarif import ingest  # noqa: E402
from kernel import cli  # noqa: E402
from kernel.autonomy import AutonomyCapped, cleared_to_build, cleared_to_deliver, set_cap  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.embeds import create as create_embed  # noqa: E402
from kernel.intake import SendBack, intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.plan import edit_requirement, gate as plan_gate, required as plan_required  # noqa: E402
from kernel.posture import effects, lines, of, parse_weights, preview, weights_of  # noqa: E402
from kernel.posture_change import change  # noqa: E402
from kernel.posture_rules import Held, missing_topics, view  # noqa: E402
from kernel.security import security_gate, summary  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


def kinds(project) -> list:
    return [r["event"]["kind"] for r in project.ledger().records()]


def payloads(project, kind: str) -> list:
    return [r["event"]["payload"] for r in project.ledger().of_kind(kind)]


def sarif(path: Path, tool: str, levels=()) -> Path:
    """A SARIF 2.1.0 scan by ``tool`` with one finding per level given."""
    results = [{"ruleId": f"R{i}", "level": lvl, "message": {"text": f"finding {i}"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app/routes.py"},
                                                    "region": {"startLine": 10 + i}}}]}
               for i, lvl in enumerate(levels, 1)]
    doc = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": tool, "version": "1.0.0", "rules": [
        {"id": f"R{i}", "shortDescription": {"text": f"rule {i}"}} for i in range(1, len(levels) + 1)]}},
        "results": results}]}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def cli_run(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class PostureCase(FactoryTestCase):
    def posed(self, name, weights=None, **kw):
        return self.factory.new_project("Equipment loans", posture={"name": name, "weights": weights, "by": "Aino",
                                                                    "persona": "business_owner"}, **kw)

    def answer_all(self, p):
        canon = Canon(p)
        for q in canon.questions("open"):
            canon.answer(q["id"], q["opinions"].get(q["perspective"]) or "yes", person="Aino", persona="business_owner")


class PostureChoiceTest(PostureCase):
    def test_FR_POS1_AC_1_each_posture_sets_its_mode_maturity_autonomy_and_gates_as_decided(self):
        pro, bal, prod, reg = (effects(n) for n in ("prototype", "balanced", "production", "regulated"))
        self.assertEqual((pro["mode"], pro["maturities"], pro["autonomy"]), ("assume", ["explore", "demo"], 3))
        self.assertEqual((pro["gate"]["scan"], pro["gate"]["redteam"], pro["gate"]["evidence"], pro["plan_approval"]),
                         (False, [], None, False))
        self.assertEqual((bal["mode"], bal["maturities"], bal["autonomy"], bal["gate"]["scan"]),
                         ("mixed", ["demo", "pilot"], 2, False))
        self.assertEqual((prod["maturities"], prod["maturity"], prod["gate"]["scan"], prod["gate"]["redteam"],
                          prod["gate"]["evidence"]), (["pilot", "production"], "production", True, ["static"], "exported"))
        said = " ".join(lines(prod)["people"])
        self.assertIn("end users validate it on staging, then IT's deploy gate before production", said)
        self.assertEqual((reg["mode"], reg["maturities"], reg["autonomy"], reg["plan_approval"], reg["confirm"]),
                         ("socratic", ["explore", "demo", "pilot", "production"], 1, True, True))
        self.assertEqual((reg["gate"]["block_on"], reg["gate"]["redteam"], reg["gate"]["evidence"]),
                         (["error", "warning"], ["static", "agentic"], "attestable"))
        # Building waits under autonomy 2 and 1; delivering to staging waits under 3 too; prototype goes alone.
        self.assertIn("building and delivering to demo wait for a person's go-ahead card", lines(bal)["people"][0])
        self.assertIn("nothing waits for a go-ahead", lines(pro)["people"][0])
        # The same choice always gives the same preview, and the command line shows exactly it.
        for name in ("prototype", "balanced", "production", "regulated"):
            self.assertEqual(json.dumps(preview(name)), json.dumps(preview(name)))
        code, out, _ = cli_run("--home", str(self.factory.home), "posture", "preview", "production")
        self.assertEqual((code, json.loads(out)), (0, json.loads(json.dumps(preview("production")))))
        self.assertFalse(self.factory.projects_dir.exists())                    # a preview made and wrote nothing

    def test_FR_POS1_AC_2_weights_shape_the_panel_the_spec_the_gates_and_how_much_waits(self):
        base = effects("balanced")
        w = effects("balanced", {"security": 3, "ux": 2, "compliance": 0})
        budget, before = w["intake"]["budget"], base["intake"]["budget"]
        self.assertEqual(budget["it_security"], before["it_security"] + 2)     # security 3: two more questions
        self.assertEqual(budget["end_user"], before["end_user"] + 1)           # ux 2: one more
        self.assertEqual(budget["delivery"], before["delivery"])
        self.assertIn("security (3 of 3)", " ".join(w["intake"]["emphasis"]["it_security"]))
        self.assertIn("compliance has no weight", " ".join(w["intake"]["emphasis"]["business"]))
        self.assertEqual(w["spec"]["topics"], ["accessibility", "security"])   # compliance 0: no record-keeping topic
        self.assertEqual((w["gate"]["block_on"], w["gate"]["scan"], w["gate"]["redteam"]),
                         (["error", "warning"], True, ["static", "agentic"]))
        self.assertEqual(w["autonomy"], 1)                                     # security 3: more waits for a person
        self.assertEqual(effects("balanced", {"speed": 3})["autonomy"], 3)     # speed 3: less waits
        self.assertEqual(effects("balanced", {"speed": 3})["intake"]["budget"]["delivery"], before["delivery"] - 1)
        comp = effects("balanced", {"compliance": 3})
        self.assertEqual((comp["plan_approval"], comp["confirm"], comp["gate"]["evidence"]), (True, True, "attestable"))
        self.assertEqual(comp["spec"]["topics"], ["record_keeping", "data_protection"])
        # A floor raises a weight below it, and the preview says so.
        raised = preview("production", {"security": 0})
        self.assertEqual(raised["effects"]["weights"]["security"], 2)
        self.assertEqual(raised["lines"]["raised"], ["security raised from 0 to 2: the floor of the production posture"])
        # Work with no screens is not asked for accessibility.
        flat = preview("balanced", {"ux": 3}, profile="integration")
        self.assertEqual(flat["effects"]["spec"]["topics"], [])
        self.assertIn("no screens", " ".join(flat["lines"]["spec"]))
        for bad in ("speed=4", "taste=1", "security", "ux=-1"):
            with self.assertRaises(ValueError):
                parse_weights(bad)
        for bad in ({"ux": True}, {"ux": 2.0}, {"ux": 4}, {"look": 1}):
            with self.assertRaises(ValueError):
                weights_of("balanced", bad)
        code, _, err = cli_run("posture", "preview", "balanced", "--weights", "speed=9")
        self.assertEqual(code, 2)
        self.assertIn("speed", err)

    def test_FR_POS1_AC_3_a_new_project_takes_the_posture_and_records_who_chose_it_and_what_they_were_shown(self):
        p = self.posed("regulated", {"ux": 2})
        self.assertEqual((p.meta["mode"], p.meta["maturity"]), ("socratic", "pilot"))
        self.assertEqual((p.meta["posture"]["name"], p.meta["posture"]["chosen_by"]), ("regulated", "Aino"))
        rec = payloads(p, "posture_chosen")[0]
        self.assertEqual((rec["by"], rec["persona"], rec["weights"]["ux"], rec["autonomy"]),
                         ("Aino", "business_owner", 2, 1))
        self.assertEqual(rec["shown"], lines(of(p)))                            # the preview the person saw
        self.assertLess(kinds(p).index("project_created"), kinds(p).index("posture_chosen"))
        self.assertEqual(self.posed("prototype", maturity="explore").meta["maturity"], "explore")
        for kw in ({"maturity": "demo"}, {"mode": "assume"}):
            with self.assertRaises(ValueError):
                self.posed("production", **kw)
        with self.assertRaises(DecisionRefused):
            self.factory.new_project("T", posture={"name": "balanced", "by": "factory"})
        home = str(self.factory.home)
        before = len(self.factory.projects())
        for argv in (["--posture", "prototype", "--maturity", "production"], ["--posture", "regulated", "--mode", "mixed"],
                     ["--weights", "ux=2"], ["--posture", "balanced", "--weights", "ux=7"]):
            code, _, err = cli_run("--home", home, "new", "T", "--source", IDEA, "--requested-by", "Aino", *argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err.strip(), argv)
        self.assertEqual(len(self.factory.projects()), before)                   # nothing was made
        plain = self.factory.new_project("Plain")
        self.assertEqual((plain.meta["maturity"], plain.meta["mode"], "posture" in plain.meta), ("demo", "mixed", False))
        self.assertNotIn("posture_chosen", kinds(plain))


class PostureChainTest(PostureCase):
    def test_FR_POS2_AC_1_each_perspective_asks_within_its_budget_and_hears_what_it_weighs(self):
        def many(prompt, role):
            if "perspective on a panel" in prompt:
                who = prompt.split("You are the **")[1].split("**")[0]
                return "```json\n" + json.dumps({"reading": who, "questions": [
                    {"text": f"{who} asks {i}", "why": "w", "blocking": False, "proposed_answer": "yes"}
                    for i in range(8)]}) + "\n```"
            if "A panel of perspectives" in prompt:
                return '```json\n{"opinions": []}\n```'
            return script(prompt, role)

        p = self.posed("balanced", {"security": 3, "ux": 2, "compliance": 0})
        fake = FakeModel(many)
        intake(p, IDEA, model=fake, requested_by="Aino")
        budget = of(p)["intake"]["budget"]
        asked = {}
        for q in Canon(p).questions():
            if " asks " in q["text"]:
                asked[q["perspective"]] = asked.get(q["perspective"], 0) + 1
        self.assertEqual(asked, budget)
        prompts = {c[1].split("You are the **")[1].split("**")[0]: c[1] for c in fake.calls if "perspective on a panel" in c[1]}
        self.assertIn(f"ask at most {budget['it_security']} questions", prompts["it_security"])
        self.assertIn("Weigh security (3 of 3)", prompts["it_security"])
        self.assertIn("Weigh ux (2 of 3)", prompts["end_user"])
        self.assertNotIn("Weigh", prompts["delivery"])
        # without a posture the prompts are as before
        plain = self.factory.new_project("Plain")
        fake2 = FakeModel(many)
        intake(plain, IDEA, model=fake2, requested_by="Aino")
        self.assertFalse(any("posture" in c[1] for c in fake2.calls))

    def test_FR_POS2_AC_2_the_spec_covers_the_posture_topics_or_the_plan_waits_for_a_person(self):
        p = self.posed("balanced", {"security": 2})
        intake(p, IDEA, model=model(), requested_by="Aino")
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        fake = model()
        make_spec(p, model=fake)
        prompt = next(c[1] for c in fake.calls if "You turn a brief into a software specification" in c[1])
        self.assertIn("Security: include a threat-model requirement", prompt)
        self.assertIn("Write at most 6 requirements", prompt)                  # demo's five, one more per topic
        self.assertEqual(payloads(p, "posture_spec_checked")[0]["missing"], ["security"])
        self.assertTrue(plan_required(p))                                       # demo needs no approval, the gap does
        waiting = plan_gate(p, model=model())
        body = Canon(p).get_card(waiting["waiting_on"][0])["body"]
        self.assertIn("threat model and security: MISSING", body)
        # a person's edit that covers it counts at once: nothing then holds a demo plan
        edit_requirement(p, "R-2", person="Aino", persona="product_owner", acceptance=[
            {"given": "an item", "when": "POST /items/{id}/loan without a credential", "then": "401 and nothing changes"}])
        self.assertEqual(missing_topics(p), [])
        self.assertFalse(plan_required(p))

    def test_FR_POS2_AC_3_a_confirming_posture_settles_every_question_confirms_every_requirement_and_lets_no_assumption_stand(self):
        p = self.posed("regulated", maturity="demo")
        intake(p, IDEA, model=model(), requested_by="Aino")
        canon = Canon(p)
        self.assertEqual(canon.assumptions(), [])                              # socratic: every question to a person
        canon.answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        with self.assertRaises(SendBack) as held:                               # not only the blocking ones
            make_spec(p, model=model())
        self.assertEqual({q["id"] for q in held.exception.questions}, {q["id"] for q in canon.questions("open")})
        self.answer_all(p)
        make_spec(p, model=model())
        waiting = plan_gate(p, model=model())                                   # plan approval at demo too
        card = waiting["waiting_on"][0]
        self.assertIn("Approving confirms each requirement in your name (R-4 are not confirmed", canon.get_card(card)["body"])
        canon.decide(card, "approve", person="Aino", persona="business_owner", reason="as discussed")
        self.assertIsNone(plan_gate(p, model=model()))
        reqs = p.read("spec.json")["requirements"]
        self.assertEqual({r["provenance"] for r in reqs}, {"customer-confirmed", "customer-endorsed"})
        r4 = next(r for r in reqs if r["id"] == "R-4")
        self.assertEqual((r4["confirmed"]["by"], r4["confirmed"]["was"]), ("Aino", "vendor-proposed"))
        self.assertEqual(payloads(p, "requirements_confirmed")[0]["requirements"], ["R-4"])
        a = canon.add_assumption("every laptop has an asset tag", "operations")
        with self.assertRaises(Held) as stop:
            cleared_to_build(p)
        self.assertIn(a["id"], str(stop.exception))
        code, out, _ = cli_run("--home", str(self.factory.home), "posture", "confirm", p.pid, a["id"],
                               "--person", "Aino", "--persona", "business_owner")
        self.assertEqual((code, json.loads(out)["status"]), (0, "confirmed"))
        with self.assertRaises(Held) as stop:
            cleared_to_build(p)
        self.assertNotIn(a["id"], str(stop.exception))
        self.assertIn("go-ahead", str(stop.exception))


class PostureWaitsTest(PostureCase):
    def test_FR_POS3_AC_1_a_step_above_the_posture_autonomy_waits_for_a_go_ahead_card(self):
        p = self.posed("balanced")
        p.update_meta(contract_revision="sha256:" + "ab" * 32)
        with self.assertRaises(Held) as first:
            cleared_to_build(p)
        card = first.exception.card
        with self.assertRaises(Held) as again:
            cleared_to_build(p)
        self.assertEqual(again.exception.card, card)                            # one card per step and revision
        canon = Canon(p)
        canon.decide(card, "reject", person="Aino", persona="business_owner", reason="not before Monday")
        with self.assertRaises(Held) as asked:
            cleared_to_build(p)
        self.assertNotEqual(asked.exception.card, card)
        self.assertIn("Declined before by Aino: not before Monday", canon.get_card(asked.exception.card)["body"])
        canon.decide(asked.exception.card, "approve", person="Aino", persona="business_owner")
        self.assertIs(cleared_to_build(p), p)
        self.assertEqual([x["posture"] for x in payloads(p, "go_ahead_asked")], ["balanced", "balanced"])
        # the autonomy cap still refuses above it, whatever the posture
        set_cap(p, 2, person="Ilkka", persona="it", reason="the pilot runs on customer data")
        with self.assertRaises(AutonomyCapped) as capped:
            cleared_to_build(p)
        self.assertNotIsInstance(capped.exception, Held)
        # a posture whose autonomy covers the step asks nobody
        quick = self.posed("prototype")
        self.assertIs(cleared_to_build(quick), quick)
        self.assertNotIn("go_ahead_asked", kinds(quick))

    def test_FR_POS3_AC_2_a_balanced_project_runs_from_an_idea_to_its_delivery_stopping_for_each_go_ahead(self):
        p = self.posed("balanced")
        intake(p, IDEA, model=model(), requested_by="Aino")
        kw = dict(model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=generic_cell,
                  verifier_runner=no_findings, deliver_kwargs={})
        canon, decided = Canon(p), []
        for _ in range(6):
            out = advance(p, **kw)
            card = next(iter(canon.cards()), None)
            if card is None or card["kind"] == "road":
                break
            decided.append((card["kind"], card["refs"].get("scope"), out["state"]))
            if card["kind"] == "question":
                canon.answer(card["refs"]["question"], "the team lead approves", person="Aino", persona="business_owner")
            else:
                canon.decide(card["id"], "approve", person="Aino", persona="business_owner", reason="go")
        self.assertEqual(decided, [("question", None, "waiting"), ("approval", "go_ahead", "capped"),
                                   ("approval", "go_ahead", "capped")])
        self.assertTrue(p.meta["built"])
        self.assertEqual(card["kind"], "road")                                  # the release started: the road is IT's
        k = kinds(p)
        asked = [i for i, x in enumerate(k) if x == "go_ahead_asked"]
        self.assertLess(asked[0], k.index("merged"))
        self.assertLess(k.index("merged"), asked[1])
        self.assertLess(asked[1], k.index("release_started"))
        go = [d for d in canon.decisions() if d.get("verdict") == "approve"]
        self.assertEqual([(d["person"], d["persona"]) for d in go], [("Aino", "business_owner")] * 2)
        self.assertTrue(p.ledger().verify().intact)


class PostureGatesTest(PostureCase):
    def test_FR_POS4_AC_1_a_posture_that_requires_a_scan_holds_a_landing_until_the_scan_and_red_team_layers_ran(self):
        p = self.posed("production", maturity="pilot")
        gate = security_gate(p, record=False)
        self.assertEqual((gate["verdict"], gate["blocked"]), ("not measured", True))
        self.assertEqual([b["id"] for b in gate["blocking"]], ["POSTURE-SCAN", "POSTURE-REDTEAM-STATIC"])
        self.assertIn("python -m kernel.redteam static", gate["reason"])
        ingest(p, sarif(self.tmp / "other.sarif", "Example Scanner"))
        self.assertEqual([b["id"] for b in security_gate(p, record=False)["blocking"]], ["POSTURE-REDTEAM-STATIC"])
        ingest(p, sarif(self.tmp / "static.sarif", "Rihmasto red team (static)", ["warning"]))
        gate = security_gate(p, record=False)
        self.assertEqual((gate["verdict"], gate["blocked"]), ("passed", False))   # a warning does not block at security 2
        # regulated: warnings block, and the agentic layer is required once the project has an LLM-facing surface
        r = self.posed("regulated", maturity="pilot")
        ingest(r, sarif(self.tmp / "static.sarif", "Rihmasto red team (static)", ["warning"]))
        self.assertEqual([b["id"] for b in security_gate(r, record=False)["blocking"]], ["SEC-1-1"])
        create_embed(self.factory, kind="feedback", origins=["https://shop.example"], person="Ilkka", persona="it",
                     project_id=r.pid, label="Shop", brief="loans")
        self.assertIn("POSTURE-REDTEAM-AGENTIC", [b["id"] for b in security_gate(r, record=False)["blocking"]])
        ingest(r, sarif(self.tmp / "agentic.sarif", "Rihmasto red team (agentic embed)"))
        self.assertNotIn("POSTURE-REDTEAM-AGENTIC", [b["id"] for b in security_gate(r, record=False)["blocking"]])
        # a preview or demo landing is held too, before anything is asked of a person
        d = self.posed("regulated", maturity="demo")
        with self.assertRaises(Held) as held:
            cleared_to_deliver(d)
        self.assertIn("the security gate holds delivery to demo", str(held.exception))
        self.assertNotIn("go_ahead_asked", kinds(d))
        # without a posture: no scan is "not measured" and holds nothing, as before
        plain = self.factory.new_project("Plain")
        none = security_gate(plain, record=False)
        self.assertEqual((none["verdict"], none["blocked"], none["block_on"], "posture" in none),
                         ("not measured", False, ["error"], False))

    def test_FR_POS4_AC_2_before_production_the_release_waits_for_its_evidence_pack(self):
        for name, verdict, holds in (("production", "insufficient evidence", False),
                                     ("regulated", "insufficient evidence", True),
                                     ("regulated", "attestable", False)):
            p = self.posed(name, maturity="production")
            ingest(p, sarif(self.tmp / "static.sarif", "Rihmasto red team (static)"))
            p.write("releases/1.json", {"release": 1, "revision": "c0ffee", "state": "waiting", "maturity": "production",
                                        "steps": [{"step": "deploy_gate", "outcome": "passed"}]})
            p.log("release_started", {"release": 1, "revision": "c0ffee"})
            gate = security_gate(p, record=False)
            self.assertIn("POSTURE-EVIDENCE", [b["id"] for b in gate["blocking"]])
            self.assertIn(f"rihmasto evidence {p.pid} --out DIR", gate["reason"])
            p.log("evidence_exported", {"file": "x.zip", "by": "Kaisa", "persona": "compliance", "verdict": verdict})
            ids = [b["id"] for b in security_gate(p, record=False)["blocking"]]
            self.assertEqual("POSTURE-EVIDENCE" in ids, holds, (name, verdict))
            # a pack's summary reports the findings alone: the scan found nothing, whatever the posture still asks
            pack = summary(p)
            self.assertEqual(pack["verdict"], "passed", (name, verdict, pack))
            self.assertNotIn("posture", json.dumps(pack).lower())


class PostureChangeTest(PostureCase):
    def test_FR_POS5_AC_1_a_change_during_the_run_says_what_it_changes_now_and_later_and_who_may_loosen_it(self):
        p = self.posed("prototype")
        intake(p, IDEA, model=model(), requested_by="Aino")
        open_ones = [a["id"] for a in Canon(p).assumptions("open")]
        self.assertTrue(open_ones)
        out = change(p, "regulated", person="Pia", persona="product_owner", reason="customer data after all",
                     maturity="demo")
        self.assertIn(f"confirmation reopened: {', '.join(open_ones)} must be confirmed or refuted by a person before "
                      "the next build", out["now"])
        self.assertTrue(any(x.startswith("mode assume to socratic") for x in out["later"]))
        self.assertEqual((p.meta["mode"], p.meta["maturity"], p.meta["posture"]["chosen_by"]), ("socratic", "demo", "Pia"))
        rec = payloads(p, "posture_changed")[0]
        self.assertEqual((rec["from"], rec["to"], rec["by"], rec["persona"], rec["reason"], rec["now"]),
                         ("prototype", "regulated", "Pia", "product_owner", "customer data after all", out["now"]))
        with self.assertRaises(DecisionRefused) as loose:                     # loosening is not a product owner's
            change(p, "prototype", person="Pia", persona="product_owner", reason="faster")
        self.assertIn("autonomy 1 to 3", str(loose.exception))
        back = change(p, "prototype", person="Aino", persona="business_owner", reason="a demo first")
        self.assertIn("no confirmation by name", back["loosens"])
        for who, persona, reason in (("Pia", "stakeholder", "x"), ("factory", "business_owner", "x"),
                                     ("Aino", "business_owner", " ")):
            with self.assertRaises(ValueError):
                change(p, "balanced", person=who, persona=persona, reason=reason)
        home = str(self.factory.home)
        code, _, err = cli_run("--home", home, "posture", "set", p.pid, "balanced", "--reason", "x",
                               "--person", "Pia", "--persona", "stakeholder")
        self.assertEqual(code, 2)
        self.assertIn("may not choose a posture", err)
        code, out, _ = cli_run("--home", home, "posture", "set", p.pid, "balanced", "--reason", "people say go",
                               "--person", "Pia", "--persona", "product_owner")
        self.assertEqual((code, json.loads(out)["posture"]), (0, "balanced"))
        code, out, _ = cli_run("--home", home, "posture", "show", p.pid)
        shown = json.loads(out)
        self.assertEqual((code, shown["posture"]["posture"], shown["lines"]), (0, "balanced", lines(of(p))))
        self.assertIn("holds", shown)
        # a go-ahead the new posture does not need is withdrawn, and the change says so
        b = self.posed("balanced")
        with self.assertRaises(Held) as held:
            cleared_to_build(b)
        moved = change(b, "prototype", person="Aino", persona="business_owner", reason="speed up")
        self.assertIn(f"{held.exception.card} withdrawn", moved["applied"])
        self.assertEqual(Canon(b).get_card(held.exception.card)["state"], "withdrawn")
        with self.assertRaises(DecisionRefused):
            from kernel.learn import factory_project

            change(factory_project(self.factory), "balanced", person="Aino", persona="business_owner", reason="x")

    def test_FR_POS5_AC_2_a_project_without_a_posture_runs_exactly_as_before(self):
        p = self.factory.new_project("Equipment loans")
        fake = model()
        intake(p, IDEA, model=fake, requested_by="Aino")
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        make_spec(p, model=fake)
        self.assertFalse(any("posture" in c[1] for c in fake.calls))
        self.assertIsNone(plan_gate(p, model=fake))                             # demo: no plan card, as before
        p.update_meta(contract_revision="sha256:" + "cd" * 32)
        self.assertIs(cleared_to_build(p), p)
        self.assertEqual([k for k in kinds(p) if "posture" in k or "go_ahead" in k], [])
        self.assertIsNone(view(p)["posture"])
        self.assertEqual(Canon(p).cards(kind="approval"), [])
        # it may take a posture the same way, compared with how it runs today
        out = change(p, "balanced", person="Aino", persona="business_owner", reason="a person should say go")
        self.assertIn("from the next step the factory acts alone up to level 2 (suggest); a step above it waits for a "
                      "person's go-ahead card", out["now"])
        self.assertEqual(out["loosens"], [])
        self.assertIsNone(payloads(p, "posture_changed")[0]["from"])


if __name__ == "__main__":
    unittest.main()
