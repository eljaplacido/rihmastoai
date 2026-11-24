"""Any input, any author (FR-IK1; docs/guides/inputs.md): what arrived at intake is read by rule, what it
states is kept with its lines and never asked again, the facet checklist finds the gaps and the mode
settles them, an expert's ids and wording and a plan's decisions are kept as given, a model's refinement
is only a proposal, and the intake summary sets from your input, asked and assumed side by side.

The fixture inputs are in tests/fixtures/inputs/: a one-line need, a two-line Finnish need, an expert's
specification with ids and criteria, a full plan with three deliberate gaps (data and its sensitivity,
availability, acceptance criteria) and a folder of mixed documents.
"""

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.input_facets import FACET_IDS  # noqa: E402
from kernel.input_intake import already_given, asked_facets, documents_of  # noqa: E402
from kernel.input_kind import read, split_lines  # noqa: E402
from kernel.input_summary import read_source, refine, render_text, summary  # noqa: E402
from kernel.intake import intake, load_source  # noqa: E402
from kernel.model import FakeModel, ModelError  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "inputs"
ONE_LINE, FINNISH, SPEC, PLAN, FOLDER = (FIX / "need-one-line.txt", FIX / "need-finnish.txt", FIX / "spec-expert.md",
                                         FIX / "plan-full.md", FIX / "folder")


def q(text: str, proposed: str, blocking: bool = False) -> dict:
    return {"text": text, "why": "it changes what gets built", "blocking": blocking, "proposed_answer": proposed}


# The plan's panel: three questions re-ask what the plan states, three ask its gaps or something new.
PLAN_PANEL = {
    "business": [q("Who registers the visitors, and in which roles?", "receptionists"),            # users: given
                 q("What availability does the reception need?", "office hours")],               # a gap
    "it_security": [q("Which cloud or environment does it deploy to?", "Azure"),                  # deployment: given
                    q("Is any visitor data sensitive?", "names only: internal", True)],           # a gap
    "end_user": [q("Should the badge show the host's name?", "yes")],                            # no facet: asked
    "delivery": [q("Should the first version cover the other offices too?", "no")],               # scope: given
}
# The specification's panel re-asks two things the author stated, and nothing else.
SPEC_PANEL = {"end_user": [q("Who are the users of the register?", "warehouse workers")],
              "business": [q("How is success measured?", "tools reported missing")]}
# The analyst's draft: it rewords TLR-001 and TLR-002, leaves out TLR-003 and TLR-004, and adds one of its own.
SPEC_DRAFT = {
    "title": "Tool loan register", "summary": "Tools and their loans.", "users": ["warehouse workers"],
    "interface": [{"method": "POST", "path": "/tools", "purpose": "register a tool"},
                  {"method": "POST", "path": "/loans", "purpose": "lend a tool"}],
    "requirements": [
        {"id": "TLR-001", "statement": "Workers can add tools.", "sources": ["request"], "priority": "must",
         "acceptance": [{"given": "-", "when": "POST /tools", "then": "201", "kind": "holdout"},
                        {"given": "-", "when": "GET /tools", "then": "listed", "kind": "test"}]},
        {"id": "TLR-002", "statement": "Loans are recorded.", "sources": ["request", "Q-003"], "priority": "should",
         "acceptance": [{"given": "-", "when": "POST /loans", "then": "201", "kind": "test"},
                        {"given": "a loan", "when": "POST /loans again", "then": "409", "kind": "holdout"}]},
        {"id": "", "statement": "The service answers its health check.", "sources": ["proposed"], "priority": "could",
         "acceptance": [{"given": "-", "when": "GET /health", "then": "200", "kind": "test"}]},
    ],
    "out_of_scope": ["billing"],
}


def scripted(panel: dict, draft: dict | None = None):
    """A model that answers the panel from ``panel`` (nothing for a perspective it does not name), keeps
    no opinions, and drafts ``draft`` as the analyst."""
    def answer(prompt: str, role: str) -> str:
        if "perspective on a panel" in prompt:
            who = next(p for p in ("business", "end_user", "it_security", "operations", "delivery")
                       if f"You are the **{p}** perspective" in prompt)
            return "```json\n" + json.dumps({"reading": f"{who} reading", "questions": panel.get(who, [])}) + "\n```"
        if "A panel of perspectives" in prompt:
            return '```json\n{"opinions": []}\n```'
        if "You turn a brief into a software specification" in prompt and draft is not None:
            return "```json\n" + json.dumps(draft) + "\n```"
        raise AssertionError(f"unscripted prompt for {role}: {prompt[:100]}")
    return FakeModel(answer)


class InputsTestCase(FactoryTestCase):
    def project(self, source: Path, panel: dict, *, mode: str = "mixed", maturity: str = "production",
                draft: dict | None = None, literal: bool = False):
        p = self.factory.new_project(source.stem, mode=mode, maturity=maturity, profile="web_service")
        m = scripted(panel, draft)
        text = source.read_text(encoding="utf-8") if literal else str(source)
        out = intake(p, text, model=m, requested_by="Aino", literal=literal)
        return p, out, m

    @staticmethod
    def asked_texts(p) -> list:
        return [x["text"] for x in Canon(p).questions()]


class ReadingTest(InputsTestCase):
    def test_FR_IK1_AC_1_each_input_is_read_as_its_kind_by_rule_and_a_folders_documents_each_by_its_own(self):
        cases = {ONE_LINE: ("need", "certain", "en"), FINNISH: ("need", "certain", "fi"),
                 SPEC: ("specification", "certain", "en"), PLAN: ("plan", "certain", "en"),
                 FOLDER: ("folder", "certain", "mixed")}
        for source, expected in cases.items():
            r = read_source(str(source))
            self.assertEqual((r["kind"], r["confidence"], r["language"]), expected, source.name)
            self.assertTrue(r["basis"], source.name)                                   # the rule that fired is named
        self.assertEqual(read_source(str(SPEC))["basis"], ["4 requirements with the author's own ids",
                                                           "5 acceptance criteria"])
        self.assertIn("3 decisions", read_source(str(PLAN))["basis"])
        docs = {d["name"]: d["kind"] for d in read_source(str(FOLDER))["documents"]}
        self.assertEqual(docs, {"brief.md": "need", "data.md": "reference", "decisions.md": "plan",
                                "notes.txt": "need", "requirements.md": "specification"})
        # the same text typed in is read the same way as the file
        self.assertEqual(read_source(FINNISH.read_text(encoding="utf-8").strip())["kind"], "need")
        unsure = read([("request", " ".join(["The register keeps every loan."] * 40))])
        self.assertEqual((unsure["kind"], unsure["confidence"]), ("need", "uncertain"))   # long, no structure

    def assert_lines_hold(self, reading: dict, root: Path) -> None:
        """Every fact quotes the lines it names, in the document it names."""
        for f in reading["facts"]:
            path = root if root.is_file() else root / f["document"]
            lines = split_lines(path.read_text(encoding="utf-8"))
            a, b = f["lines"]
            quoted = " ".join(x.strip() for x in lines[a - 1:b] if x.strip())
            self.assertIn(f["text"][:40], quoted, f["id"])               # its words, list markers aside
            self.assertTrue(lines[a - 1].strip() and lines[b - 1].strip(), f["id"])

    def test_FR_IK1_AC_2_what_the_input_states_is_kept_with_its_lines_and_the_gaps_are_what_it_does_not_state(self):
        one = read_source(str(ONE_LINE))
        self.assertEqual((one["given"], one["gaps"]), ([], list(FACET_IDS)))
        fi = read_source(str(FINNISH))
        self.assertEqual(fi["given"], ["users_roles"])
        self.assertEqual((fi["facts"][0]["lines"], fi["facts"][0]["how"]), ([2, 2], "cue"))
        self.assertIn("käyttäjinä ovat varaston työntekijät", fi["facts"][0]["text"])
        self.assertEqual(fi["gaps"], [f for f in FACET_IDS if f != "users_roles"])
        spec = read_source(str(SPEC))
        self.assertEqual(spec["given"], ["users_roles", "outcomes", "performance", "acceptance"])
        self.assertEqual(spec["gaps"], ["scope", "data", "integrations", "security", "privacy", "availability",
                                        "accessibility", "deployment", "constraints"])
        reqs = {r["id"]: r for r in spec["requirements"]}
        self.assertEqual(list(reqs), ["TLR-001", "TLR-002", "TLR-003", "TLR-004"])
        self.assertEqual(reqs["TLR-003"]["statement"],
                         "A loan of a tool worth more than 500 euros needs a shift supervisor's approval.")
        self.assertEqual([len(r["acceptance"]) for r in reqs.values()], [1, 2, 1, 1])
        self.assertEqual(reqs["TLR-001"]["acceptance"][0], {
            "given": "no tool with inventory number 77", "when": 'a worker registers "Drill" with number 77',
            "then": "the register lists Drill with number 77.", "lines": [18, 18]})
        plan = read_source(str(PLAN))
        self.assertEqual(plan["gaps"], ["data", "availability", "acceptance"])          # the three deliberate gaps
        self.assertEqual([(d["id"], d["lines"]) for d in plan["decisions"]], [("D1", [56, 56]), ("D2", [57, 57]),
                                                                               ("D3", [58, 58])])
        folder = read_source(str(FOLDER))
        self.assertEqual(folder["given"], ["users_roles", "outcomes", "data", "security", "deployment", "acceptance"])
        where = {(f["facet"], f["document"]) for f in folder["facts"]}
        self.assertTrue({("users_roles", "notes.txt"), ("security", "notes.txt"), ("data", "data.md"),
                         ("deployment", "decisions.md"), ("outcomes", "brief.md")} <= where)
        for reading, root in ((fi, FINNISH), (spec, SPEC), (plan, PLAN), (folder, FOLDER)):
            self.assert_lines_hold(reading, root)
        # a section that only says "TBD" leaves its facet open, and that is recorded with its line
        left = read([("plan.md", "# Plan\n\n## Users\n\nWarehouse staff.\n\n## Availability\n\nTBD\n")])
        self.assertEqual((left["given"], left["left_open"][0]["facet"], left["left_open"][0]["lines"]),
                         (["users_roles"], "availability", [7, 9]))
        self.assertIn("availability", left["gaps"])


class IntakeTest(InputsTestCase):
    def test_FR_IK1_AC_3_what_the_input_states_is_never_asked_again_and_the_panel_is_told_what_it_states(self):
        p, out, m = self.project(PLAN, PLAN_PANEL, mode="socratic")
        asked = self.asked_texts(p)
        for given in ("Who registers the visitors, and in which roles?",
                      "Which cloud or environment does it deploy to?",
                      "Should the first version cover the other offices too?"):
            self.assertNotIn(given, asked)
        for kept in ("What availability does the reception need?", "Is any visitor data sensitive?",
                     "Should the badge show the host's name?"):
            self.assertIn(kept, asked)
        reading = p.read("inputs.json")
        facts = {f["id"]: f for f in reading["facts"]}
        not_asked = {x["text"]: x for x in reading["not_asked"]}
        self.assertEqual(not_asked["Who registers the visitors, and in which roles?"]["facets"], ["users_roles"])
        for x in not_asked.values():                                  # each rests on facts of its own facets
            self.assertTrue(x["because"] and all(facts[i]["facet"] in x["facets"] for i in x["because"]))
        self.assertEqual(out["not_asked"], 3)
        screened = p.ledger().of_kind("input_screened")[-1]["event"]["payload"]
        self.assertEqual(len(screened["not_asked"]), 3)
        prompts = [prompt for _, prompt in m.calls if "perspective on a panel" in prompt]
        self.assertEqual(len(set(x[:x.index("You are the **")] for x in prompts)), 1)  # one shared prefix
        self.assertIn("Never ask about them again", prompts[0])
        self.assertIn("Receptionists sign in with the organisation's single sign-on", prompts[0])
        self.assertIn("The gaps, what it does not state: data and its sensitivity, availability, acceptance criteria.",
                      prompts[0])
        # a need: its one stated fact is not asked again either
        fp, _, _ = self.project(FINNISH, {"end_user": [q("Who are the users?", "warehouse staff")]}, mode="socratic",
                                maturity="demo")
        self.assertNotIn("Who are the users?", self.asked_texts(fp))
        self.assertEqual(fp.read("inputs.json")["not_asked"][0]["because"], ["F-001"])

    def test_FR_IK1_AC_4_the_checklist_asks_only_the_gaps_and_the_mode_settles_them(self):
        p, _, _ = self.project(PLAN, PLAN_PANEL, mode="socratic")
        reading, canon = p.read("inputs.json"), Canon(p)
        self.assertEqual([g["facet"] for g in reading["gap_questions"]], ["acceptance"])  # no panel question covered it
        gap = canon.question(reading["gap_questions"][0]["question"])
        self.assertEqual((gap["text"], gap["perspective"]), ("How will you accept it: what must you see working?",
                                                             "delivery"))
        for question in canon.questions():                              # socratic: every asked question has a card
            self.assertTrue(question["card"])
            self.assertFalse(set(reading["question_facets"].get(question["id"]) or ["none"]) <= set(reading["given"]))
        self.assertEqual(canon.assumptions(), [])

        a, _, _ = self.project(PLAN, PLAN_PANEL, mode="assume")
        assumed = {x["question"]: x for x in Canon(a).assumptions()}
        self.assertEqual(Canon(a).cards(kind="question"), [])
        acc = a.read("inputs.json")["gap_questions"][0]["question"]
        self.assertEqual((assumed[acc]["text"], assumed[acc]["due"]), ("the analyst's criteria, approved with the plan",
                                                                        "2026-12-06"))

        s, out, _ = self.project(SPEC, SPEC_PANEL, mode="mixed", maturity="pilot")
        sr, sc = s.read("inputs.json"), Canon(s)
        self.assertEqual([g["facet"] for g in sr["gap_questions"]],
                         ["scope", "data", "integrations", "security", "privacy", "accessibility", "deployment",
                          "constraints"])
        to_person = {sr["question_facets"][x["id"]][0] for x in sc.questions() if x["card"]}
        self.assertEqual(to_person, {"scope", "data"})                   # the blocking gaps go to a person
        self.assertEqual(len(out["assumed"]), 7)                         # six gaps and the look, with due dates
        self.assertNotIn("availability", [g["facet"] for g in sr["gap_questions"]])   # asked from production on
        notes = {f["facet"]: (f["state"], f["note"]) for f in summary(s)["facets"]}
        self.assertEqual(notes["availability"], ("open", "not asked at this maturity"))

        n, out, _ = self.project(ONE_LINE, {"business": [q("Who approves a loan?", "the team lead", True)]},
                                 mode="mixed", maturity="production")
        self.assertEqual(n.read("inputs.json")["gap_questions"], [])     # a need's gaps are the panel's to ask
        self.assertEqual(out["gap_questions"], [])
        self.assertEqual({f["note"] for f in summary(n)["facets"] if f["state"] == "open"},
                         {"a need's gaps are the panel's to ask"})
        self.assertEqual(asked_facets("production", "prototype"), ["users_roles", "outcomes", "scope"])
        self.assertIn("privacy", asked_facets("demo", "regulated"))      # the posture hook

    def test_FR_IK1_AC_5_an_experts_ids_and_wording_are_kept_and_a_plans_decisions_arrive_as_given(self):
        p, _, m = self.project(SPEC, SPEC_PANEL, mode="assume", maturity="demo", draft=copy.deepcopy(SPEC_DRAFT))
        spec = make_spec(p, model=m)
        reqs = {r["id"]: r for r in spec["requirements"]}
        self.assertEqual(list(reqs), ["TLR-001", "TLR-002", "TLR-003", "TLR-004", "R-1"])
        authored = {r["id"]: r for r in p.read("inputs.json")["requirements"]}
        for rid in ("TLR-001", "TLR-002", "TLR-003", "TLR-004"):
            self.assertEqual(reqs[rid]["statement"], authored[rid]["statement"])      # the author's own words
            self.assertEqual([c["then"] for c in reqs[rid]["acceptance"]],
                             [c["then"] for c in authored[rid]["acceptance"]])
            self.assertEqual((reqs[rid]["provenance"], reqs[rid]["decided_by"], reqs[rid]["wording"]),
                             ("customer-endorsed", "Aino", "author"))
        self.assertEqual([c["kind"] for c in reqs["TLR-002"]["acceptance"]], ["test", "holdout"])   # the draft's
        self.assertEqual([c["kind"] for c in reqs["TLR-001"]["acceptance"]], ["test"])   # one visible check at least
        self.assertEqual(reqs["TLR-002"]["sources"], ["request", "Q-003"])
        self.assertIn("restored", reqs["TLR-003"])
        self.assertNotIn("restored", reqs["TLR-001"])
        self.assertEqual(reqs["R-1"]["provenance"], "vendor-proposed")
        compile_project(p)                                               # the contract compiles from it
        self.assertEqual([r["id"] for r in p.read("contract.json")["requirements"]][:4],
                         ["TLR-001", "TLR-002", "TLR-003", "TLR-004"])

        plan, _, _ = self.project(PLAN, PLAN_PANEL, mode="assume")
        decisions = plan.read("inputs.json")["decisions"]
        self.assertEqual([d["id"] for d in decisions], ["D1", "D2", "D3"])
        canon = Canon(plan)
        for d in decisions:                                              # given, never assumed nor asked
            self.assertFalse(any(d["text"] in a["text"] for a in canon.assumptions()))
            self.assertFalse(any(d["text"] in x["text"] for x in canon.questions()))
        self.assertEqual(canon.decisions(), [])                          # nobody decided anything in the canon
        self.assertIn("- Decision D1 (plan-full.md, line 56): Badges are printed on the existing label printer at the "
                      "reception. [owner: decided in the input]", canon.brief)
        self.assertIn("[owner: given by Aino]", canon.brief)


class RefineAndSummaryTest(InputsTestCase):
    def test_FR_IK1_AC_6_a_models_refinement_is_kept_as_model_proposed_with_lines_the_kernel_checked(self):
        p, _, _ = self.project(ONE_LINE, {}, mode="assume", maturity="demo")
        before = (len(Canon(p).questions()), Canon(p).decisions())
        answer = {"kind": "plan", "why": "it reads like a plan to me",
                  "stated": [{"facet": "users_roles", "lines": [1, 1]}, {"facet": "nonsense", "lines": [1, 1]},
                             {"facet": "privacy", "lines": [5, 9]}]}
        model = FakeModel(lambda prompt, role: "```json\n" + json.dumps(answer) + "\n```")
        with self.assertRaises(DecisionRefused):
            refine(p, model, person="model", persona="product_owner")       # a model never asks for itself
        proposal = refine(p, model, person="Pekka", persona="product_owner")
        self.assertIn("The rule read it as a need (certain)", model.calls[-1][1])
        self.assertEqual((proposal["kind"], proposal["measured"], proposal["asked_by"]), ("plan", True, "Pekka"))
        self.assertEqual(proposal["stated"], [{"facet": "users_roles", "lines": [1, 1], "document": ONE_LINE.name,
                                               "text": ONE_LINE.read_text(encoding="utf-8").strip()}])
        self.assertEqual([d["why"] for d in proposal["dropped"]], ["not a facet of the checklist",
                                                                   "lines 5-9 are not lines of the request"])
        reading = p.read("inputs.json")
        self.assertEqual((reading["kind"], reading["kind_by"], reading["given"]), ("need", "rule", []))   # unchanged
        self.assertEqual((len(Canon(p).questions()), Canon(p).decisions()), before)
        refined = p.ledger().of_kind("input_refined")[-1]["event"]["payload"]
        self.assertEqual((refined["asked_by"], refined["model_kind"], refined["rule_kind"]), ("Pekka", "plan", "need"))

        def silent(prompt, role):
            raise ModelError("no endpoint answered")
        self.assertFalse(refine(p, FakeModel(silent), person="Pekka", persona="product_owner")["measured"])
        self.assertEqual(len(p.ledger().of_kind("input_refined")), 1)       # nothing written when not measured
        # in a folder, a line of the joined request is a line of one document
        f, _, _ = self.project(FOLDER, {}, mode="assume", maturity="demo")
        notes = next(d for d in f.read("inputs.json")["documents"] if d["name"] == "notes.txt")
        cite = {"kind": "folder", "stated": [{"facet": "privacy", "lines": [notes["first_line"] + 1] * 2}]}
        prop = refine(f, FakeModel(lambda prompt, role: "```json\n" + json.dumps(cite) + "\n```"),
                      person="Pekka", persona="product_owner")
        self.assertIsNone(prop["kind"])                                  # a folder of one document is never proposed
        self.assertEqual((prop["stated"][0]["document"], prop["stated"][0]["lines"]), ("notes.txt", [2, 2]))

    def test_FR_IK1_AC_7_the_intake_summary_sets_from_your_input_asked_and_assumed_side_by_side(self):
        p, _, _ = self.project(PLAN, PLAN_PANEL, mode="mixed")
        data_q = next(x for x in Canon(p).questions() if x["text"] == "Is any visitor data sensitive?")
        Canon(p).answer(data_q["id"], "visitor names only, internal", person="Pekka", persona="business_owner")
        s = summary(p)
        self.assertEqual((s["kind"], s["kind_by"], s["by"]), ("plan", "rule", "Aino"))
        self.assertEqual(len(s["from_input"]["facts"]), 11)
        self.assertEqual([d["id"] for d in s["from_input"]["decisions"]], ["D1", "D2", "D3"])
        self.assertEqual([(x["text"], x["status"], x["by"]) for x in s["asked"]],
                         [("Is any visitor data sensitive?", "answered", "Pekka")])
        self.assertEqual(sorted(x["facets"][0] for x in s["assumed"] if x["facets"]), ["acceptance", "availability"])
        self.assertTrue(all(x["due"] for x in s["assumed"]))
        states = {f["facet"]: f["state"] for f in s["facets"]}
        self.assertEqual((states["data"], states["availability"], states["acceptance"], states["users_roles"]),
                         ("answered", "assumed", "assumed", "given"))
        self.assertEqual(s["counts"]["not_asked"], 3)
        text = render_text(s)
        for said in ("From your input, given by Aino", "Asked:", "Assumed:",
                     "Not asked, because your input already says it:", "decision D2 (plan-full.md, line 57)"):
            self.assertIn(said, text)
        # the same through `rihmasto inputs`
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--home", str(self.factory.home), "inputs", "summary", p.pid]), 0)
        self.assertEqual(json.loads(out.getvalue())["counts"], s["counts"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--home", str(self.factory.home), "inputs", "summary", p.pid, "--text"]), 0)
        self.assertEqual(out.getvalue(), text + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["inputs", "read", str(PLAN), "--maturity", "production"]), 0)
        self.assertEqual(json.loads(out.getvalue())["checklist_would_ask"], ["data", "availability", "acceptance"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch("kernel.cli._model", lambda: FakeModel({})):
            self.assertEqual(main(["--home", str(self.factory.home), "inputs", "refine", p.pid, "--person", "assistant",
                                   "--persona", "product_owner"]), 2)
        self.assertIn("not a person", err.getvalue())
        # the ledger: who asked, the kind, every fact with its lines and the request's sha256
        read_rec = p.ledger().of_kind("input_read")[-1]["event"]["payload"]
        self.assertEqual((read_rec["requested_by"], read_rec["kind"], len(read_rec["sha256"])), ("Aino", "plan", 64))
        self.assertEqual(read_rec["facts"][0], {"id": "F-001", "facet": "outcomes", "document": "plan-full.md",
                                                "lines": [10, 11], "how": "section"})
        self.assertEqual(p.ledger().of_kind("intake_done")[-1]["event"]["payload"]["input_kind"], "plan")
        self.assertTrue(p.ledger().verify().intact)
        # a project read before inputs were read has no summary, and says so
        p.path("inputs.json").unlink()
        self.assertIsNone(summary(p))


# A panel on the specification that names its stated facets (users, outcomes, performance, acceptance) but
# asks about things the specification never says, beside two questions that only restate it.
NEW_DETAIL_PANEL = {
    "end_user": [q("Can users delete a tool from the register?", "no"),
                 q("Should the users get an email reminder when a loan is overdue?", "yes", True)],
    "operations": [q("How fast should a worker be able to lend a tool, and should it work offline?", "online only")],
    "delivery": [q("Which tests should run before each release?", "the acceptance tests")],
    "business": [q("Is there a goal for how many tools are tracked in total?", "all of them"),
                 q("Who are the users of the register?", "warehouse workers", True),     # restates, but blocking
                 q("How is success measured?", "tools reported missing")],                # restates: not asked
}


class ScreeningRepairTest(InputsTestCase):
    def test_FR_IK2_AC_1_a_question_that_asks_more_than_the_input_states_is_asked_and_a_blocking_one_reaches_a_person(self):
        p, out, _ = self.project(SPEC, NEW_DETAIL_PANEL, mode="mixed", maturity="pilot")
        canon, reading = Canon(p), p.read("inputs.json")
        asked = {x["text"]: x for x in canon.questions()}
        for new in ("Can users delete a tool from the register?",
                    "Should the users get an email reminder when a loan is overdue?",
                    "How fast should a worker be able to lend a tool, and should it work offline?",
                    "Which tests should run before each release?",
                    "Is there a goal for how many tools are tracked in total?"):
            self.assertIn(new, asked)
        self.assertEqual([x["text"] for x in reading["not_asked"]], ["How is success measured?"])
        self.assertEqual(out["not_asked"], 1)
        restated = asked["Who are the users of the register?"]                 # blocking: a person decides it
        self.assertTrue(restated["blocking"] and restated["card"])
        self.assertIn("Your input already states: \"Warehouse workers lend and return tools.", restated["rationale"])
        self.assertIn("(spec-expert.md, lines", restated["rationale"])
        kept = reading["restated_blocking"]
        self.assertEqual([(x["text"], x["facets"]) for x in kept], [("Who are the users of the register?",
                                                                      ["users_roles"])])
        facts = {f["id"]: f for f in reading["facts"]}
        self.assertTrue(kept[0]["because"] and all(facts[i]["facet"] == "users_roles" for i in kept[0]["because"]))
        screened = p.ledger().of_kind("input_screened")[-1]["event"]["payload"]
        self.assertEqual(screened["restated_blocking"], kept)
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_IK2_AC_2_a_folders_housekeeping_files_are_not_read_as_the_authors_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            files = {"README.md": "# Visitor log\n\nA log of the visitors at the main office.\n",
                     "CHANGELOG.md": "# Changelog\n\n## 1.0\n\n- First release for the users.\n",
                     "LICENSE.txt": "Licensed under the terms below.\n",
                     "SECURITY.md": "# Security policy\n\nReport vulnerabilities to the maintainers by email.\n",
                     "CONTRIBUTING.md": "# Contributing\n\nOpen a pull request with tests.\n",
                     "requirements.txt": "somepackage==1.0\n",
                     "notes.md": "# Notes\n\nThe receptionist keeps the log.\n",
                     "docs/design.md": "# Design\n\nOne page lists today's visitors.\n"}
            for name, text in files.items():
                (root / name).write_text(text, encoding="utf-8")
            kind, text = load_source(str(root))
            heads = [h for h in (line[3:].replace("\\", "/") for line in text.splitlines() if line.startswith("## "))
                     if h in files]
            self.assertEqual(heads, ["README.md", "notes.md", "docs/design.md"])
            documents, folder = documents_of(text, str(root))
            self.assertEqual([n for n, _ in documents], ["README.md", "notes.md", "docs/design.md"])
            reading = read(documents, folder=folder)
            self.assertNotIn("security", reading["given"])
            reading.update(not_asked=[], restated_blocking=[], titles=[])
            self.assertFalse(already_given(reading, {"text": "Which sign-in must it use: SSO or local accounts?"},
                                           "it_security"))


if __name__ == "__main__":
    unittest.main()
