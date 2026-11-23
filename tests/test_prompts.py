"""FR-Z1: model-facing prompts are compact, consistent and cache-friendly.

- AC-1: the analyst lane's toolless roles read a short system prompt of their own, not Gnomon's
  tool-use rules.
- AC-2: the product lane's system.md is role-neutral; each rule only one role can follow is in that
  role's own task, once.
- AC-3: the five intake perspectives share one prefix, word for word, and a cut request says so.
- AC-4: the assistant's static catalogue comes first and its snapshot last, fitted to a budget by
  whole items, with what was dropped named.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel import lanes  # noqa: E402
from kernel.assistant import (LAYOUT_BUDGET, SNAPSHOT_BUDGET, _catalogue, fit_snapshot, prompt,  # noqa: E402
                              snapshot)
from kernel.canon import PERSPECTIVES, Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import envelope  # noqa: E402
from kernel.gate import verifier_prompt  # noqa: E402
from kernel.intake import MAX_SOURCE_CHARS, intake  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
# Gnomon's `init` rules that assume tools: a toolless role must not read them.
TOOL_RULES = ("Use the declared tools", "through `compute`", "Run what you produced", "A reply with no tool call")


def panel_prompts(m: FakeModel) -> list[str]:
    return [text for _, text in m.calls if "perspective on a panel" in text]


def product_part(system_md: str) -> str:
    """What follows Gnomon's `init` prompt in a product lane's system.md, with its lines joined."""
    return " ".join(system_md[len(lanes.scaffold_system_md()):].split())


class AnalystLanePromptTest(FactoryTestCase):
    def test_FR_Z1_AC_1_the_analyst_lane_reads_a_short_prompt_of_its_own_without_tool_rules(self) -> None:
        lane = lanes.ensure_analyst_lane(lanes.load_routing(), root=self.tmp / "lanes")
        system = (lane / ".gnomon" / "system.md").read_text(encoding="utf-8")
        self.assertEqual(system, lanes.analyst_system_md())
        for rule in TOOL_RULES:                                               # nothing it cannot follow
            self.assertNotIn(rule, system)
        self.assertNotIn(lanes.SCAFFOLD_MARKER, system)
        self.assertIn("no tools", system)
        self.assertIn("Answer only from it", system)                          # the task file is its world
        self.assertIn("```json fenced block", system)                         # JSON in a fence, when asked
        self.assertLess(len(system), len(lanes.scaffold_system_md()) / 3)     # compact: a fraction of init
        self.assertNotIn("\r", system)


class ProductLanePromptTest(FactoryTestCase):
    def contract(self) -> tuple[Any, dict]:
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        return p, compile_project(p)

    def test_FR_Z1_AC_2_the_product_system_md_is_role_neutral_and_each_builder_rule_is_said_once(self) -> None:
        repo = self.tmp / "repo"
        lanes.write_product_surface(repo, lanes.load_routing(), ["app/", "tests/"])
        system = (repo / ".gnomon" / "system.md").read_text(encoding="utf-8")
        self.assertTrue(system.startswith(lanes.scaffold_system_md()))       # the product lane keeps init
        own = product_part(system)
        # Every safety rule stays, for every role.
        self.assertIn("`.gnomon/`, `contract.json` and `factory/` are read-only", own)
        self.assertIn("Write nothing outside the paths your task names", own)
        self.assertIn("LF line endings", own)
        # Nothing only the builder can follow: the verifier has neither bash nor write.
        for builder_only in ("unittest", "bash", "Write it first", "test_R_", "standard library"):
            self.assertNotIn(builder_only, own)
        self.assertNotIn("run", own.lower())
        p, contract = self.contract()
        task = envelope(p, contract, "T-001", base="0" * 40)
        for rule in ("python3 -m unittest discover -s tests", "it must fail before your code exists",
                     "standard library only", "## Report"):
            self.assertEqual((system + task).count(rule), 1, rule)            # in the builder's task, once
        verifier = verifier_prompt(contract, "T-001", "0" * 40)
        self.assertIn("run nothing else", verifier)                           # and nothing contradicts it


class PanelPromptTest(FactoryTestCase):
    def test_FR_Z1_AC_3_the_perspectives_share_one_prefix_and_a_cut_request_says_so(self) -> None:
        m = model()
        p = self.new(mode="assume")
        intake(p, IDEA, model=m, requested_by="Aino")
        prompts = panel_prompts(m)
        self.assertEqual(len(prompts), len(PERSPECTIVES))
        prefix = os.path.commonprefix(prompts)
        self.assertTrue(prefix.endswith("You are the **"))                  # identical up to the perspective
        self.assertIn(IDEA, prefix)
        self.assertIn("Answer with this JSON", prefix)
        for perspective, text in zip(PERSPECTIVES, prompts):
            self.assertTrue(text[len(prefix):].startswith(f"{perspective}** perspective on a panel"))
        self.assertNotIn("was cut", prefix)
        self.assertEqual(p.ledger().of_kind("request_cut"), [])
        self.assertNotIn("cut_from", p.read("source.json"))

        text = (IDEA + "\n\n" + "Each loan has a borrower, an item and a due date. " * 1000)[:MAX_SOURCE_CHARS + 5000]
        doc = self.tmp / "long-request.md"
        doc.write_text(text, encoding="utf-8", newline="\n")
        m, p = model(), self.new(mode="assume", title="Long request")
        intake(p, str(doc), model=m, requested_by="Aino")
        prompts = panel_prompts(m)
        note = f"(The request was cut at {MAX_SOURCE_CHARS:,} of {len(text):,} characters: the rest is not shown.)"
        for each in prompts:
            self.assertIn("<<<\n" + text[:MAX_SOURCE_CHARS] + "\n>>>\n" + note, each)
        self.assertIn(note, os.path.commonprefix(prompts))                   # the note is shared too
        cut = [r["event"]["payload"] for r in p.ledger().of_kind("request_cut")]
        self.assertEqual(cut, [{"kind": "markdown", "kept": MAX_SOURCE_CHARS, "of": len(text)}])
        self.assertEqual(p.read("source.json")["cut_from"], len(text))
        self.assertIn(f"first {MAX_SOURCE_CHARS:,} of {len(text):,} characters", Canon(p).brief)


def big_snapshot(projects: int = 300, cards: int = 30, questions: int = 9, tasks: int = 40) -> dict:
    return {"factory": {"projects": [{"id": f"p-{i}", "title": f"Project {i}", "stage": 3,
                                      "now": {"state": "building", "line": "Building T-001, round 1 of 3."}}
                                     for i in range(projects)],
                        "gates": {"passed": 3}, "waiting": {"question": 2}},
            "project": {"id": "p-0", "title": "Project 0", "now": {"line": "Building."}, "health": {"status": "ok"},
                        "live": {"run": "T-001"},
                        "tasks": {f"T-{i:03d}": {"status": "pending", "rounds": 0} for i in range(1, tasks + 1)},
                        "open_cards": [{"id": f"C-{i:04d}", "kind": "question", "title": f"Card {i}"}
                                       for i in range(1, cards + 1)],
                        "open_questions": [{"id": f"Q-{i:03d}", "text": f"Question {i}?", "blocking": False}
                                           for i in range(1, questions + 1)]}}


def sent_snapshot(text: str) -> dict:
    """The snapshot as the prompt carries it: the last block, whole JSON."""
    return json.loads(text.split("Snapshot (JSON):\n", 1)[1])


class AssistantPromptTest(FactoryTestCase):
    def test_FR_Z1_AC_4_the_catalogue_comes_first_and_the_snapshot_last_within_its_budget(self) -> None:
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        small = snapshot(self.factory, project=p)
        ui = {"widgets": ["now", "health"], "layout": [{"widget": "now", "size": "M"}]}
        a = prompt("Where do I approve the plan?", small, persona="product_owner", view="decide",
                   hints=[{"id": "plan"}], ui=ui)
        b = prompt("How is the run going?", big_snapshot(), persona="developer", view=None, hints=[])
        catalogue = _catalogue()
        for text in (a, b):                                                  # one shared, static prefix
            self.assertTrue(text.startswith(catalogue))
            self.assertLess(text.index("The question:"), text.index("Snapshot (JSON):"))
        self.assertGreater(a.index("The person is the product_owner persona"), len(catalogue))
        self.assertGreaterEqual(len(os.path.commonprefix([a, b])), len(catalogue))
        self.assertEqual(sent_snapshot(a), small)                            # a small snapshot goes whole
        self.assertNotIn("not_shown", sent_snapshot(a))

        sent = sent_snapshot(b)                                              # parses: nothing cut mid-object
        self.assertLessEqual(len(json.dumps(sent, ensure_ascii=False)), SNAPSHOT_BUDGET)
        full = big_snapshot()
        kept = sent["factory"]["projects"]
        self.assertEqual(kept, full["factory"]["projects"][:len(kept)])      # whole items, from the end
        self.assertIn(f"{300 - len(kept)} of 300 projects in the factory list", sent["not_shown"])
        self.assertEqual(sent["project"]["open_cards"], full["project"]["open_cards"][:10])
        self.assertIn("20 of 30 open cards", sent["not_shown"])
        self.assertIn("3 of 9 open questions", sent["not_shown"])

    def test_FR_Z1_AC_4_a_snapshot_or_layout_too_large_to_fit_is_named_never_sliced(self) -> None:
        tight = fit_snapshot(big_snapshot(), budget=800)
        self.assertLessEqual(len(json.dumps(tight, ensure_ascii=False)), 800)
        self.assertIn("300 of 300 projects in the factory list", tight["not_shown"])
        huge = big_snapshot(projects=1)
        huge["project"]["title"] = "x" * (SNAPSHOT_BUDGET + 1)
        self.assertEqual(fit_snapshot(huge), {"not_shown": [
            f"the whole snapshot: it is over {SNAPSHOT_BUDGET:,} characters even without its lists"]})
        layout = [{"widget": "now", "size": "M", "filter": {"note": "x" * 200}} for _ in range(20)]
        text = prompt("Make it compact", {"factory": {"projects": []}}, persona="developer", view=None, hints=[],
                      ui={"widgets": ["now"], "layout": layout})
        self.assertIn(f"Their current layout is over {LAYOUT_BUDGET:,} characters and is not shown.", text)
        self.assertNotIn('"filter"', text)


if __name__ == "__main__":
    unittest.main()
