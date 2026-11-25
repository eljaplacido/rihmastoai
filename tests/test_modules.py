"""Modules: a person uses a small part of Rihmasto or the whole of it, and changes that later (FR-MOD1), and
what a set does on the command line, in the pipeline, in the cockpit and in the assistant (FR-MOD2)."""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import assistant, modules  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.learn import FACTORY_PID, factory_project  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


def cli(home, *argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("kernel.cli._model", model), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--home", str(home), *argv])
    return code, (json.loads(out.getvalue()) if out.getvalue().strip() else None), err.getvalue()


class ModuleSetTest(FactoryTestCase):
    def test_FR_MOD1_AC_1_the_catalogue_closes_a_set_under_its_needs_and_refuses_what_it_cannot_be(self):
        for mid, spec in modules.MODULES.items():                  # each says what it adds, needs and yields
            self.assertTrue(spec["label"] and spec["adds"] and spec["outputs"], mid)
            self.assertTrue(set(spec["depends"]) <= set(modules.MODULES), mid)
        self.assertEqual(modules.closure(["delivery"]), ["plan", "build", "delivery"])
        out = modules.set_modules(self.factory, person="Aino", persona="business_owner", modules=["delivery"])
        self.assertEqual((out["modules"], out["added_for_dependencies"]), (["plan", "build", "delivery"], ["plan", "build"]))
        with self.assertRaisesRegex(ValueError, "build cannot be turned off while delivery needs it"):
            modules.set_modules(self.factory, person="Aino", persona="business_owner", disable=["build"])
        with self.assertRaisesRegex(ValueError, "no module 'nope'"):
            modules.set_modules(self.factory, person="Aino", persona="business_owner", enable=["nope"])
        with self.assertRaisesRegex(ValueError, "no preset 'tiny'"):
            modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="tiny")
        with self.assertRaisesRegex(ValueError, "at least one module"):
            modules.set_modules(self.factory, person="Aino", persona="business_owner", modules=[])
        for preset in modules.PRESETS.values():                    # every preset is closed under its needs
            self.assertEqual(modules.closure(preset["modules"]), [m for m in modules.MODULES if m in preset["modules"]])
            self.assertTrue(preset["brings"] and preset["gets"])

    def test_FR_MOD1_AC_1_the_knowledge_graph_and_the_data_and_context_pages_are_core_by_name(self):
        """Every page of the navigation is either named by a module or core by name: the Knowledge graph and the
        Data and context page (and each project's Graph and Context tabs) are core, so the smallest set shows
        them, and the browser walk (tests/test_ui_modules.py) expects them there."""
        for kind, name in (("pages", "graph_all"), ("pages", "data_all"), ("views", "graph"), ("views", "context")):
            self.assertIn(name, modules.CORE[kind], name)
            self.assertEqual(modules.owners(kind, name), [], name)
        modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        self.assertFalse({"graph_all", "data_all", "graph", "context"} & modules.hidden_ids(self.factory))

    def test_FR_MOD1_AC_2_a_factory_where_nobody_chose_is_the_full_factory_and_reading_it_creates_nothing(self):
        got = modules.factory_set(self.factory)
        self.assertEqual((got["preset"], got["modules"], got["chosen"]), ("full", list(modules.MODULES), False))
        self.assertIsNone(factory_project(self.factory, create=False))          # reading created no canon
        self.assertTrue(modules.view(self.factory)["new_home"])
        modules.set_modules(self.factory, person="Aino", persona="it", preset="full")
        with mock.patch.dict(modules.MODULES, {"later": modules._module("Later", "a module added later",
                                                                           outputs=("x",))}):
            self.assertIn("later", modules.enabled(self.factory))      # the full factory grows with the catalogue
        self.assertFalse(modules.view(self.factory)["new_home"])            # a set was chosen

    def test_FR_MOD1_AC_3_a_named_person_chooses_and_the_choice_and_a_projects_own_set_are_recorded(self):
        with self.assertRaises(DecisionRefused):
            modules.set_modules(self.factory, person="assistant", persona="business_owner", preset="spec_only")
        with self.assertRaisesRegex(DecisionRefused, "a end_user may not choose"):
            modules.set_modules(self.factory, person="Aino", persona="end_user", preset="spec_only")
        out = modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only",
                                  reason="we only need the spec")
        self.assertEqual((out["changed"], out["preset"]), (True, "spec_only"))
        store = factory_project(self.factory)
        rec = store.ledger().of_kind("modules_set")[-1]["event"]["payload"]
        self.assertEqual((rec["scope"], rec["to"], rec["preset"], rec["by"], rec["persona"], rec["reason"]),
                         ("factory", ["intake", "plan"], "spec_only", "Aino", "business_owner", "we only need the spec"))
        self.assertEqual(rec["from"], list(modules.MODULES))
        again = modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        self.assertFalse(again["changed"])
        self.assertEqual(len(store.ledger().of_kind("modules_set")), 1)       # nothing changed, nothing recorded
        p = self.new()
        self.assertEqual(modules.project_set(p)["modules"], ["intake", "plan"])
        modules.set_modules(p, person="Ilkka", persona="developer", enable=["build"])
        self.assertEqual(modules.project_set(p)["modules"], ["intake", "plan", "build"])
        self.assertEqual(modules.factory_set(self.factory)["modules"], ["intake", "plan"])   # the factory's is as it was
        back = modules.set_modules(p, person="Ilkka", persona="developer", inherit=True)
        self.assertEqual(back["modules"], ["intake", "plan"])
        kinds = [r["event"]["payload"] for r in p.ledger().of_kind("modules_set")]
        self.assertEqual([(k["scope"], k["inherit"], k["by"]) for k in kinds],
                         [("project", False, "Ilkka"), ("project", True, "Ilkka")])
        self.assertNotIn("modules", p.meta)

    def test_FR_MOD1_AC_4_modules_show_set_and_presets_on_the_command_line(self):
        code, out, _ = cli(self.factory.home, "modules", "presets")
        self.assertEqual(code, 0)
        self.assertEqual([p["id"] for p in out["presets"]],
                         ["spec_only", "gate_my_code", "assess_only", "security_only", "evidence_only",
                          "capability_only", "full"])
        code, out, _ = cli(self.factory.home, "modules", "set", "--preset", "gate_my_code", "--person", "Aino",
                           "--persona", "developer", "--reason", "our own repository")
        self.assertEqual((code, out["modules"], out["preset"]), (0, ["plan", "build"], "gate_my_code"))
        code, out, _ = cli(self.factory.home, "modules", "set", "--enable", "security", "--person", "Aino",
                           "--persona", "developer")
        self.assertEqual(out["turned_on"], ["security"])
        code, out, _ = cli(self.factory.home, "modules", "show")
        self.assertEqual(out["factory"]["modules"], ["plan", "build", "security"])
        self.assertIsNone(out["factory"]["preset"])                               # a set of its own
        self.assertEqual({m["id"]: m["on"] for m in out["modules"]}["delivery"], False)
        code, _, err = cli(self.factory.home, "modules", "set", "--preset", "full", "--person", "factory",
                           "--persona", "developer")
        self.assertEqual(code, 2)
        self.assertIn("not a person", err)


class WhatASetDoesTest(FactoryTestCase):
    def test_FR_MOD2_AC_1_the_command_line_refuses_a_command_of_a_module_that_is_off_and_says_how_to_turn_it_on(self):
        home = self.factory.home
        p = self.new()
        modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        code, _, err = cli(home, "signal", "list")
        self.assertEqual(code, 2)
        self.assertIn("signal list is part of Delivery square and signals, which is not enabled for this factory", err)
        self.assertIn("rihmasto modules set --enable square", err)
        code, _, err = cli(home, "workspace", "list", p.pid)                    # a chain command: refused, no traceback
        self.assertEqual(code, 2)
        self.assertIn(f"not enabled for project {p.pid}", err)
        self.assertIn(f"--enable build --project {p.pid}", err)
        modules.set_modules(p, person="Aino", persona="business_owner", enable=["build"])
        code, out, _ = cli(home, "workspace", "list", p.pid)                    # the project's own set decides
        self.assertEqual((code, out), (0, {"workspaces": []}))
        code, out, _ = cli(home, "status", p.pid)                               # core always runs
        self.assertEqual(code, 0)
        self.assertEqual(out["projects"][0]["id"], p.pid)

    def test_FR_MOD2_AC_2_the_pipeline_stops_at_the_edge_of_the_set_and_says_why_once(self):
        modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        p = self.new(mode="assume", maturity="explore")
        intake(p, IDEA, model=model(), requested_by="Aino")
        out = advance(p, model=model())
        self.assertEqual((out["state"], out["stopped_by_modules"]), ("done", "build"))
        self.assertIn("nothing is built here: Build and gate is not enabled (Spec only)", out["why"])
        self.assertIn(f"rihmasto contract export {p.pid} --out DIR", out["why"])
        self.assertIn("rihmasto modules set --enable build", out["why"])
        self.assertTrue(p.path("contract.json").exists())
        self.assertFalse(p.meta.get("built"))
        self.assertEqual(p.ledger().of_kind("cell_ran"), [])
        advance(p, model=model())                                                # run again: the same stop
        self.assertEqual(len(p.ledger().of_kind("stopped_by_modules")), 1)        # recorded once
        q = self.new(mode="assume", maturity="explore", title="Built elsewhere")
        modules.set_modules(q, person="Aino", persona="developer", modules=["intake", "plan", "build"])
        intake(q, IDEA, model=model(), requested_by="Aino")
        make_spec(q, model=model())
        compile_project(q)
        q.update_meta(built=True)                                                # as if every task had merged
        out = advance(q, model=model())
        self.assertEqual((out["state"], out["stopped_by_modules"]), ("done", "delivery"))
        self.assertIn("nothing is delivered here: Delivery is not enabled", out["why"])
        self.assertFalse(q.path("releases").exists())


class CockpitModulesTest(CockpitTestCase):
    def test_FR_MOD2_AC_3_the_cockpit_refuses_a_write_of_a_module_that_is_off_never_a_read_and_changes_sets_signed(self):
        p = self.intake_project(mode="assume")
        status, view, _ = self.call("GET", "/api/modules")
        self.assertEqual((status, view["factory"]["chosen"], view["new_home"]), (200, False, False))
        status, out, _ = self.call("PUT", "/api/modules", {"preset": "spec_only", "person": "Aino",
                                                           "persona": "end_user"})
        self.assertEqual(status, 403)                                            # not a persona that chooses
        status, out, _ = self.call("PUT", "/api/modules", {"preset": "spec_only", "person": "Aino",
                                                           "persona": "business_owner", "reason": "spec first"})
        self.assertEqual((status, out["preset"], out["view"]["factory"]["modules"]), (200, "spec_only", ["intake", "plan"]))
        status, out, _ = self.call("POST", "/api/signals", {"text": "a need", "person": "Aino", "persona": "business_owner"})
        self.assertEqual(status, 403)
        self.assertIn("post_signal is part of Delivery square and signals", out["error"])
        self.assertEqual(self.call("GET", "/api/signals")[0], 200)              # a read is never refused
        status, ctx, _ = self.call("GET", f"/api/projects/{p.pid}/context?persona=developer&lens=delivery")
        self.assertEqual(status, 200)
        self.assertFalse({"tasks", "cell", "releases", "changes"} & set(ctx["views"]))
        self.assertIn("spec", ctx["views"])
        status, out, _ = self.call("PUT", f"/api/projects/{p.pid}/modules", {"modules": ["intake", "plan", "change"],
                                                                            "person": "Ilkka", "persona": "developer"})
        self.assertEqual((status, out["modules"]), (200, ["intake", "plan", "change"]))
        status, ctx, _ = self.call("GET", f"/api/projects/{p.pid}/context?persona=developer&lens=business")
        self.assertIn("changes", ctx["views"])
        self.assertEqual(self.call("GET", "/api/modules")[1]["projects"][p.pid]["modules"], ["intake", "plan", "change"])
        status, out, _ = self.call("PUT", f"/api/projects/{FACTORY_PID}/modules", {"preset": "full", "person": "Ilkka",
                                                                                   "persona": "developer"})
        self.assertEqual(status, 400)
        rec = p.ledger().of_kind("modules_set")[-1]["event"]["payload"]
        self.assertEqual((rec["by"], rec["persona"], rec["to"]), ("Ilkka", "developer", ["intake", "plan", "change"]))

    def test_FR_MOD2_AC_4_the_assistant_points_only_to_what_is_on_and_names_the_module_of_what_is_off(self):
        modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        hidden = modules.hidden_ids(self.factory)
        self.assertTrue({"square", "log_signal", "releases", "evidence", "export_evidence", "create_embed"} <= hidden)
        self.assertFalse({"settings", "modules", "questions", "plan", "inbox", "ledger"} & hidden)
        status, out, _ = self.call("POST", "/api/assistant", {"question": "Where do I log a signal?",
                                                              "persona": "business_owner", "person": "Aino"})
        self.assertEqual(status, 200)
        self.assertEqual(out["navigate"], {"route": "#/settings", "control": "modules"})
        self.assertIn("Log a signal is part of Delivery square and signals, which is not enabled here", out["answer"])
        self.assertEqual(out["not_enabled"], "square")
        out = assistant.from_map("Where are the assumptions?", None, hidden=hidden)
        self.assertEqual(out["navigate"]["route"], "#/projects")                   # what is on is still found
        self.assertNotIn("- square (#/square)", assistant._catalogue(hidden))
        self.assertNotIn("- log_signal:", assistant._catalogue(hidden))
        self.assertIn("- square (#/square)", assistant._catalogue())               # the full factory's map
        self.assertTrue(assistant._catalogue().startswith(assistant._catalogue(hidden)[:200]))
        self.assertIsNone(assistant._checked_nav({"route": "#/square"}, self.factory, None, hidden))
        self.assertEqual(assistant._checked_nav({"route": "#/settings"}, self.factory, None, hidden)["route"],
                         "#/settings")
        seen = []

        class Model:
            def ask(self, prompt, role):
                seen.append(prompt)
                return '```json\n{"answer": "It is on the square.", "navigate": {"route": "#/square"}, "sources": []}\n```'

        self.server.assistant_model = Model()
        modules.set_modules(self.factory, person="Aino", persona="business_owner", enable=["assistant"])
        status, out, _ = self.call("POST", "/api/assistant", {"question": "How is it going?",
                                                              "persona": "business_owner", "person": "Aino"})
        self.assertEqual((out["by"], out["navigate"]), ("assistant", None))      # a route that is off is not followed
        self.assertNotIn("- square (#/square)", seen[-1])
        modules.set_modules(self.factory, person="Aino", persona="business_owner", disable=["assistant"])
        status, out, _ = self.call("POST", "/api/assistant", {"question": "How is it going?",
                                                              "persona": "business_owner", "person": "Aino"})
        self.assertEqual(out["by"], "map")                                       # the assistant module off: no model
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
