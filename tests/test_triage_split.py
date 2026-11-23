import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model, script  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.change import submit, triage  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
MIXED = "Items with an empty name crash the page, and we would like a note field on every item."


def mixed_script(prompt, role):
    if "Classify a piece of feedback" in prompt:
        return "```json\n" + json.dumps({"parts": [
            {"class": "defect", "requirements": ["R-1"], "text": "Items with an empty name crash the page",
             "summary": "empty name crashes", "regression": "POST /items with an empty name answers 400"},
            {"class": "change_request", "requirements": ["R-1"], "text": "a note field on every item",
             "summary": "add a note field"}]}) + "\n```"
    return script(prompt, role)


class TriageSplitTest(FactoryTestCase):
    def test_FR_I3_AC_2_mixed_feedback_is_split_into_one_card_per_part(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        card = submit(p, persona="end_user", person="Tiina", text=MIXED)
        out = triage(p, card["id"], model=FakeModel(mixed_script))
        self.assertEqual(out["class"], "defect")
        self.assertEqual(out["text"], "Items with an empty name crash the page")
        self.assertEqual(len(out["split_into"]), 1)
        child = Canon(p).get_card(out["split_into"][0])
        self.assertEqual(child["payload"]["triage"]["class"], "change_request")
        self.assertTrue(child["payload"]["triage"]["needs_decision"])
        self.assertEqual((child["payload"]["person"], child["payload"]["source"]), ("Tiina", "end_user"))
        self.assertEqual(child["refs"]["split_from"], card["id"])
        again = triage(p, child["id"], model=FakeModel(mixed_script))   # a part is never split again
        self.assertNotIn("split_into", again)
        old_shape = submit(p, persona="end_user", person="Tiina", text="Adding an item with an empty name crashes with 500")
        self.assertEqual(triage(p, old_shape["id"], model=model())["class"], "defect")   # one-class answers still work


if __name__ == "__main__":
    unittest.main()
