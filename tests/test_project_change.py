"""FR-CHG1: anything set when a project was made can change, a project goes back a step, material is added later,
and a project is never stuck: it says what it waits for, who can act, and how.

The owner's words: "I don't want to see stupid mistakes like me choosing a template for the project or me
generating a spec, then I'm getting stuck somewhere because Rihmasto assumed the project template wrong. I
want all that to be able to change."

Only scripted models answer here (tests/factory_fakes.py): no network call is made.
"""

import contextlib
import io
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model, script  # noqa: E402
from test_brief_ln import tree  # noqa: E402
from test_cockpit import IDEA, CockpitTestCase  # noqa: E402

from kernel import next_step as kn  # noqa: E402
from kernel import project_material as km  # noqa: E402
from kernel import project_settings as ks  # noqa: E402
from kernel import rewind as kr  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.pipeline import AGAIN, _shape  # noqa: E402
from kernel.safestop import request_pause  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.store import REPO_ROOT, write_json  # noqa: E402

PO = {"person": "Aino Example", "persona": "product_owner"}
NEW_QUESTION = "Are desks booked by the half day or by the hour?"
DESKS = "Desks in the open office can be booked too, by the half day."


def payloads(project, kind: str) -> list:
    return [r["event"]["payload"] for r in project.ledger().of_kind(kind)]


def texts(project) -> list:
    return [q["text"] for q in Canon(project).questions() if q["status"] != "withdrawn"]


class ChangeCase(FactoryTestCase):
    def intaken(self, mode="mixed", maturity="demo"):
        p = self.new(mode=mode, maturity=maturity)
        intake(p, IDEA, model=model(), requested_by="Aino Example")
        return p

    def specced(self, mode="mixed", maturity="demo"):
        p = self.intaken(mode=mode, maturity=maturity)
        for q in Canon(p).questions("open"):
            Canon(p).answer(q["id"], "the team lead approves", **PO)
        make_spec(p, model=model())
        return p


class SettingsTest(ChangeCase):
    def test_FR_CHG1_AC_1_changing_the_kind_after_intake_withdraws_what_no_longer_fits_and_asks_again(self):
        p = self.intaken()
        self.assertEqual([q["id"] for q in Canon(p).questions("open")], ["Q-001"])
        before, records = tree(p.dir), len(p.ledger().records())
        seen = ks.preview(p, kind="integration")
        self.assertEqual(tree(p.dir), before)                                   # a preview writes nothing
        self.assertEqual(len(p.ledger().records()), records)
        self.assertEqual(seen["changes"], {"kind": {"from": "web_service", "to": "integration"}})
        self.assertEqual(seen["rewind"], "questions")
        self.assertIn("1 open question(s) no longer fit", seen["impact"][0]["says"])
        out = ks.change(p, reason="it connects two systems, not a web app", kind="integration", redo=True, **PO)
        self.assertEqual(p.meta["profile"], "integration")
        rec = payloads(p, "project_changed")[-1]
        self.assertEqual((rec["person"], rec["persona"], rec["before"], rec["after"], rec["offers"]),
                         ("Aino Example", "product_owner", {"kind": "web_service"}, {"kind": "integration"}, "questions"))
        self.assertEqual(out["rewound"]["to"], "questions")
        q1 = Canon(p).question("Q-001")
        self.assertEqual(q1["status"], "withdrawn")                             # withdrawn, never deleted
        card = Canon(p).get_card(q1["card"])
        self.assertEqual(card["state"], "withdrawn")
        self.assertIn("it connects two systems", card["closed"]["why"])
        self.assertEqual(Canon(p).question("Q-002")["status"], "assumed")       # settled answers are kept
        self.assertTrue(p.meta["redo_intake"])
        m = model()
        self.assertEqual(_shape(p, m, []), AGAIN)                               # the next tick asks again
        self.assertFalse(p.meta["redo_intake"])
        panel = [prompt for _, prompt in m.calls if "perspective on a panel" in prompt]
        self.assertTrue(panel and all("Already asked and settled" in x for x in panel))
        asked = texts(p)
        self.assertIn("Which systems does this connect, and which of them can we call in tests?", asked)  # the kind's own
        self.assertEqual(asked.count("How is benefit measured?"), 1)            # a settled one is not asked again
        self.assertEqual(asked.count("Who approves a loan?"), 1)                # the withdrawn one is asked anew
        self.assertTrue(payloads(p, "intake_rerun"))
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_CHG1_AC_2_changing_the_maturity_after_the_spec_writes_the_spec_again(self):
        p = self.specced()
        old = p.read("spec.json")
        seen = ks.preview(p, maturity="pilot")
        self.assertEqual(seen["rewind"], "spec")
        said = " ".join(r["says"] for r in seen["impact"])
        self.assertIn("The spec was written for demo maturity", said)
        self.assertIn("At pilot maturity a person approves the plan", said)
        out = ks.change(p, reason="real users try it first", maturity="pilot", redo=True, **PO)
        self.assertEqual(out["rewound"]["to"], "spec")
        self.assertFalse(p.path("spec.json").exists())
        kept = json.loads(p.path(out["rewound"]["folder"], "spec.json").read_text(encoding="utf-8"))
        self.assertEqual(kept, old)                                             # kept as a superseded version
        self.assertEqual(p.meta["maturity"], "pilot")
        self.assertEqual(_shape(p, model(), []), AGAIN)                         # the spec is written again
        self.assertTrue(p.path("spec.json").exists())
        waiting = _shape(p, model(), [])
        self.assertEqual(waiting["state"], "waiting")                           # pilot: a person approves the plan
        self.assertIn("approves the plan", waiting["why"])

    def test_FR_CHG1_AC_3_changing_the_mode_while_questions_are_open_settles_them_only_when_asked(self):
        p = self.intaken(mode="socratic")
        open_before = [q["id"] for q in Canon(p).questions("open")]
        self.assertGreater(len(open_before), 3)
        out = ks.change(p, reason="let the factory answer the small ones", mode="mixed", **PO)
        self.assertEqual(out["assumed"], [])                                    # without redo nothing is settled
        self.assertEqual([q["id"] for q in Canon(p).questions("open")], open_before)
        self.assertIn("under mixed the factory may assume them", out["impact"][0]["says"])
        expected = ks.preview(p, mode="assume")["assumes"]
        self.assertTrue(expected)
        out = ks.change(p, reason="assume everything for the demo", mode="assume", redo=True, **PO)
        self.assertEqual([Canon(p).assumptions()[i]["question"] for i in range(len(out["assumed"]))], expected)
        for a in Canon(p).assumptions():
            if a["id"] in out["assumed"]:
                q = Canon(p).question(a["question"])
                self.assertEqual((q["status"], q["answer"]["chosen_by"]), ("assumed", "Aino Example"))
        self.assertEqual(p.meta["mode"], "assume")

    def test_FR_CHG1_AC_3_a_change_is_signed_by_a_person_with_a_reason_and_a_persona_that_may(self):
        p = self.intaken()
        before = tree(p.dir)
        with self.assertRaises(DecisionRefused):
            ks.change(p, person="factory", persona="product_owner", reason="r", kind="integration")
        with self.assertRaises(DecisionRefused):
            ks.change(p, person="Sanna Example", persona="stakeholder", reason="r", kind="integration")
        with self.assertRaises(ValueError):
            ks.change(p, reason=" ", kind="integration", **PO)
        with self.assertRaisesRegex(ValueError, "kind must be one of"):
            ks.change(p, reason="r", kind="spaceship", **PO)
        with self.assertRaisesRegex(ValueError, "nothing to change"):
            ks.change(p, reason="r", mode="mixed", **PO)
        self.assertEqual(tree(p.dir), before)
        ks.change(p, reason="the desks too", title="Room and desk bookings", **PO)
        self.assertEqual(p.meta["title"], "Room and desk bookings")
        self.assertTrue(Canon(p).brief.startswith("# Brief: Room and desk bookings"))


class RewindTest(ChangeCase):
    def test_FR_CHG1_AC_4_going_back_to_each_step_sets_it_aside_and_the_next_tick_runs_it_again(self):
        p = self.specced(mode="assume")
        compile_project(p)
        contract = p.read("contract.json")
        self.assertEqual(kr.reached(p), list(kr.STEPS))
        out = kr.rewind(p, to="plan", reason="the plan missed the desks", **PO)
        self.assertEqual(out["files"], ["contract.json", "checkplan.json", "repo.git"])
        self.assertEqual(json.loads(p.path(out["folder"], "contract.json").read_text(encoding="utf-8")), contract)
        self.assertIsNone(p.meta["contract_revision"])
        self.assertEqual(_shape(p, model(), []), AGAIN)                         # compiled again
        self.assertTrue(p.path("contract.json").exists() and p.path("repo.git").exists())
        out = kr.rewind(p, to="spec", reason="the spec is too thin", **PO)
        self.assertEqual(set(out["files"]), {"spec.json", "spec.md", "contract.json", "checkplan.json", "repo.git"})
        self.assertEqual(_shape(p, model(), []), AGAIN)                         # the spec again
        self.assertTrue(p.path("spec.json").exists())
        self.assertFalse(p.path("contract.json").exists())
        out = kr.rewind(p, to="questions", reason="the questions missed the desks", **PO)
        self.assertTrue(p.meta["redo_intake"])
        self.assertEqual(_shape(p, model(), []), AGAIN)                         # the intake again
        self.assertFalse(p.path("spec.json").exists())
        out = kr.rewind(p, to="material", reason="the request was the wrong document", **PO)
        self.assertIn("source.json", out["files"])
        self.assertEqual(_shape(p, model(), [])["why"], "no intake yet: run `factory intake` with a source")
        self.assertEqual(kn.next_step(p)["state"], "needs_material")
        km.add_material(p, text=IDEA, note="the right request", reintake=True, model=model(), **PO)
        self.assertTrue(p.path("source.json").exists())
        self.assertEqual(p.meta["stage"], 2)                                    # its intake ran from the material
        index = kr.superseded(p)
        self.assertEqual([e["to"] for e in index], ["plan", "spec", "questions", "material"])
        for e in index:                                                          # nothing deleted
            for name in e["files"]:
                self.assertTrue(p.path(e["folder"], name).exists(), (e["folder"], name))
        recs = payloads(p, "rewound")
        self.assertEqual([(r["to"], r["person"], r["persona"]) for r in recs],
                         [(s, "Aino Example", "product_owner") for s in ("plan", "spec", "questions", "material")])
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_CHG1_AC_5_a_released_project_is_never_rewound_and_says_to_use_the_change_loop(self):
        p = self.specced()
        compile_project(p)
        write_json(p.path("releases", "1.json"), {"release": 1, "state": "done", "steps": []})
        before = tree(p.dir)
        for step in kr.STEPS:
            with self.assertRaises(kr.RewindRefused) as ctx:
                kr.rewind(p, to=step, reason="back", **PO)
            self.assertIn("release 1", str(ctx.exception))
            self.assertIn("change loop", str(ctx.exception))
            self.assertIn("release 1", kr.preview(p, step)["refused"])
        self.assertEqual(tree(p.dir), before)
        seen = ks.preview(p, kind="integration")
        self.assertIsNone(seen["rewind"])
        self.assertIn("Release 1 is out", seen["impact"][-1]["says"])
        out = ks.change(p, reason="its kind was wrong", kind="integration", redo=True, **PO)
        self.assertIsNone(out["rewound"])                                       # the setting changed, no rewind
        self.assertTrue(p.path("contract.json").exists())


def desks_script(prompt: str, role: str) -> str:
    """The panel on added material: a new question, and two it asked before (never added again)."""
    if "perspective on a panel" in prompt and "added material" in prompt:
        qs = [{"text": "Who approves a loan?", "blocking": True, "proposed_answer": "the team lead"},
              {"text": "how is benefit measured", "proposed_answer": "fewer lost items"}]
        if "You are the **business** perspective" in prompt:
            qs.append({"text": NEW_QUESTION, "why": "the booking unit", "blocking": True,
                       "proposed_answer": "by the half day", "options": ["by the hour"]})
        return "```json\n" + json.dumps({"reading": "desks", "questions": qs}) + "\n```"
    return script(prompt, role)


class MaterialTest(ChangeCase):
    def test_FR_CHG1_AC_6_added_material_is_appended_and_re_intake_asks_only_about_what_is_new(self):
        p = self.intaken()
        Canon(p).answer("Q-001", "the team lead approves", **PO)
        original = p.read("source.json")["text"]
        m = FakeModel(desks_script)
        out = km.add_material(p, text=DESKS, note="desks", reintake=True, model=m, **PO)
        text = p.read("source.json")["text"]
        self.assertTrue(text.startswith(original))                               # the original is kept
        self.assertIn("## Added material 1: desks\n\n" + DESKS, text)
        kept = km.material(p)
        self.assertEqual(kept["original"]["text"], original)
        self.assertEqual([(a["n"], a["note"], a["by"]) for a in kept["added"]], [(1, "desks", "Aino Example")])
        rec = payloads(p, "material_added")[-1]
        self.assertEqual((rec["person"], rec["chars"], len(rec["sha256"])), ("Aino Example", len(DESKS), 64))
        new = out["reintake"]["questions"]
        self.assertEqual([Canon(p).question(q)["text"] for q in new], [NEW_QUESTION])
        self.assertEqual(out["reintake"]["asked"], [Canon(p).question(new[0])["card"]])   # mixed, blocking: a person
        self.assertEqual(texts(p).count("Who approves a loan?"), 1)
        self.assertEqual(Canon(p).question("Q-001")["answer"]["text"], "the team lead approves")
        panel = [x for _, x in m.calls if "perspective on a panel" in x]
        self.assertEqual(len(panel), 5)
        self.assertTrue(all(DESKS in x and IDEA not in x and "Already asked and settled" in x for x in panel))
        # from the cockpit the panel reads it at the next run
        km.add_material(p, text="Parking spots are booked by the day.", reintake=True, **PO)
        self.assertEqual(p.meta["reintake_pending"], [2])
        self.assertEqual(kn.next_step(p)["state"], "intake_again")
        self.assertIn("added material 2", km.pending_intake(p, model=FakeModel(desks_script)))
        self.assertEqual(p.meta["reintake_pending"], [])
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_CHG1_AC_6_material_is_text_or_a_path_and_never_empty(self):
        p = self.intaken()
        doc = self.tmp / "desks.md"
        doc.write_text("# Desks\n\nBooked by the half day.\n", encoding="utf-8")
        out = km.add_material(p, path=str(doc), **PO)
        self.assertEqual((out["n"], out["reintake"]), (1, None))
        self.assertIn("Booked by the half day.", p.read("source.json")["text"])
        for bad in ({}, {"text": "x", "path": str(doc)}, {"text": "   "}):
            with self.assertRaises(ValueError):
                km.add_material(p, **bad, **PO)
        with self.assertRaises(FileNotFoundError):
            km.add_material(p, path=str(self.tmp / "missing.md"), **PO)


class NextStepTest(ChangeCase):
    def test_FR_CHG1_AC_7_every_state_the_pipeline_returns_maps_to_an_action(self):
        literal = re.compile(r'"state": "([a-z_]+)"')
        found = set()
        for name in ("pipeline", "track", "autopilot", "attach", "modules"):
            body = (REPO_ROOT / "kernel" / f"{name}.py").read_text(encoding="utf-8")
            found |= {s for s in literal.findall(body) if s not in ("open", "running")}
        self.assertLessEqual(found, set(kn.PIPELINE_STATES))                     # the list is whole
        p = self.specced()
        variants = [{"state": s, "why": "why"} for s in kn.PIPELINE_STATES] + [
            {"state": "waiting", "checkpoint": 5}, {"state": "waiting", "blocked": ["F-1"]},
            {"state": "waiting", "sandbox": {"sandbox": False}}, {"state": "waiting", "attached": True},
            {"state": "failed", "why": "no intake yet: run `factory intake` with a source"},
            {"state": "failed", "why": "a person stopped the build"},
            {"state": "done", "stopped_by_modules": "build"}]
        for last in variants:
            seen = kn.from_run(p, last)
            self.assertTrue(seen["actions"], last)
            self.assertTrue(seen["who"], last)
            for a in seen["actions"]:
                self.assertTrue(a["label"] and a["personas"] and (a.get("control") or a.get("view") or a.get("command")
                                                                  or a.get("page")), (last, a))

    def test_FR_CHG1_AC_7_next_step_reads_every_state_of_the_records(self):
        def ids(p, **kw):
            seen = kn.next_step(p, **kw)
            self.assertTrue(seen["actions"], seen)
            return seen["state"], [a["id"] for a in seen["actions"]]

        fresh = self.new()
        self.assertEqual(ids(fresh), ("needs_material", ["add_material", "change_settings"]))
        asking = self.intaken(mode="socratic")
        state, acts = ids(asking)
        self.assertEqual((state, acts[:2]), ("questions", ["answer", "assume"]))
        self.assertIn("change_settings", acts)
        self.assertEqual(ids(asking, running=True)[0], "working")
        request_pause(asking, person="Aino Example", persona="product_owner", reason="audit")
        self.assertEqual(ids(asking), ("paused", ["resume"]))
        pilot = self.specced(maturity="pilot")
        from kernel.plan import open_card

        card = open_card(pilot)
        state, acts = ids(pilot)
        self.assertEqual((state, acts), ("decisions", ["decide"]))
        self.assertEqual(kn.next_step(pilot)["actions"][0]["card"], card["id"])
        demo = self.specced()
        self.assertEqual(ids(demo)[0], "ready")
        demo.log("apparatus_failure", {"where": "pipeline", "error": "connection refused"})
        state, acts = ids(demo)
        self.assertEqual((state, acts), ("model_not_set_up", ["set_up_model", "advance"]))
        self.assertIn("kernel/routing.json", kn.next_step(demo)["actions"][0]["where"])
        demo.update_meta(redo_intake=True)
        self.assertEqual(ids(demo)[0], "intake_again")
        demo.update_meta(redo_intake=False, halted=True)
        self.assertEqual(ids(demo), ("stopped_by_person", ["rewind", "change_settings", "file_change"]))
        demo.update_meta(halted=False)
        write_json(demo.path("releases", "1.json"), {"release": 1, "state": "done"})
        demo.log("delivered", {"release": 1})
        self.assertEqual(ids(demo), ("live", ["file_change"]))
        demo.update_meta(source_kind="attached")
        self.assertEqual(ids(demo)[0], "attached")
        adopted = self.new()
        adopted.update_meta(source_kind="adopted", intent="maintain")
        self.assertEqual(ids(adopted)[0], "adopted")


class CommandLineTest(ChangeCase):
    def cli(self, *argv) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_CHG1_AC_8_the_command_line_changes_settings_goes_back_adds_material_and_says_whats_next(self):
        p = self.specced()
        who = ["--person", "Aino Example", "--persona", "product_owner"]
        code, out, err = self.cli("settings", p.pid, "--kind", "integration", "--reason", "an integration",
                                  "--preview", *who)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["rewind"], "questions")
        self.assertEqual(p.meta.get("profile"), "web_service")                   # a preview writes nothing
        code, out, err = self.cli("settings", p.pid, "--maturity", "pilot", "--reason", "real users", "--redo", *who)
        self.assertEqual((code, json.loads(out)["rewound"]["to"]), (0, "spec"), err)
        code, out, err = self.cli("material", "add", p.pid, "--text", DESKS, "--note", "desks", *who)
        self.assertEqual((code, json.loads(out)["n"]), (0, 1), err)
        code, out, err = self.cli("rewind", p.pid, "--to", "questions", "--reason", "ask about the desks", *who)
        self.assertEqual((code, json.loads(out)["to"]), (0, "questions"), err)
        code, out, err = self.cli("next", p.pid)
        self.assertEqual((code, json.loads(out)["state"]), (0, "intake_again"), err)
        write_json(p.path("releases", "1.json"), {"release": 1, "state": "done"})
        code, out, err = self.cli("rewind", p.pid, "--to", "spec", "--reason", "again", *who)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("rihmasto rewind: release 1", err)
        self.assertIn("change loop", err)


class RoutesTest(CockpitTestCase):
    def test_FR_CHG1_AC_8_the_cockpit_routes_preview_change_go_back_and_add_material_signed(self):
        p = self.intake_project()
        base = f"/api/projects/{p.pid}"
        before = tree(self.factory.home)
        status, out, _ = self.call("POST", base + "/settings/preview", {"kind": "integration", **PO})
        self.assertEqual((status, out["rewind"]), (200, "questions"), out)
        self.assertEqual(tree(self.factory.home), before)                       # the preview writes nothing
        status, out, _ = self.call("PUT", base + "/settings", {"kind": "integration", "reason": "r", "person": "factory",
                                                               "persona": "product_owner"})
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("PUT", base + "/settings", {"kind": "integration", "reason": "an integration",
                                                               "redo": True, **PO})
        self.assertEqual(status, 200, out)
        self.assertEqual((out["rewound"]["to"], out["next"]["state"]), ("questions", "intake_again"))
        audit = payloads(p, "cockpit_write")[-1]
        self.assertEqual((audit["action"], audit["person"], audit["fields"]), ("change_settings", "Aino Example", ["kind"]))
        status, out, _ = self.call("POST", base + "/material", {"path": str(self.tmp / "missing.md"), **PO})
        self.assertEqual(status, 400, out)
        status, out, _ = self.call("POST", base + "/material", {"text": DESKS, "reintake": True, **PO})
        self.assertEqual(status, 200, out)
        self.assertEqual(self.runner.started[-1][1], ["-m", "kernel.cli", "run", p.pid])   # the panel reads it in a run
        status, out, _ = self.call("POST", base + "/rewind", {"to": "material", "reason": "wrong", **PO})
        self.assertEqual(status, 409, out)                                       # a job runs for it now
        self.runner.states[self.runner.started[-1][0]] = "done"
        write_json(p.path("releases", "1.json"), {"release": 1, "state": "done"})
        status, out, _ = self.call("POST", base + "/rewind", {"to": "material", "reason": "wrong", **PO})
        self.assertEqual(status, 409, out)
        self.assertIn("change loop", out["error"])
        status, out, _ = self.call("GET", base)
        self.assertEqual(out["next"]["state"], "intake_again")
        self.assertEqual([s["to"] for s in out["change"]["steps"]], list(kr.STEPS))
        self.assertEqual(out["change"]["settings"]["kind"], "integration")
        self.assertEqual(out["change"]["material"][0]["n"], 1)
        meta = self.call("GET", "/api/meta")[1]
        self.assertEqual(meta["change"]["changers"], list(kr.CHANGERS))


if __name__ == "__main__":
    unittest.main()
