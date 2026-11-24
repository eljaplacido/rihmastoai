"""Project settings (FR-CHG1) judged by the project's posture (kernel/posture_change.py's rules).

A new maturity or mode in Project settings says, in its impact, when it also loosens or tightens the
project's posture; a maturity or mode the posture does not take is refused with the posture named, and
loosening a posture there needs a persona that may loosen one, as in the posture's own change flow. A
project without a posture changes as before.
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import project_settings as ps  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402

AINO = "Aino Example"


def said(out: dict) -> list:
    return [r["says"] for r in out["impact"] if r["what"] == "posture"]


class PostureSettingsTest(FactoryTestCase):
    def posture(self, name: str, **kw):
        return self.factory.new_project("Tool loans", posture={"name": name, "by": AINO, "persona": "business_owner"},
                                        **kw)

    def test_a_maturity_change_says_it_tightens_the_posture(self):
        p = self.posture("balanced")                                   # demo, mixed
        out = ps.preview(p, maturity="pilot")
        self.assertEqual(len(said(out)), 1, out["impact"])
        self.assertTrue(said(out)[0].startswith("This also tightens the Balanced posture: maturity demo to pilot"),
                        said(out))
        self.assertEqual(out["posture"]["loosens"], [])
        ps.change(p, person=AINO, persona="developer", reason="the pilot starts", maturity="pilot")
        self.assertEqual(p.meta["maturity"], "pilot")                    # tightening needs no loosener

    def test_a_maturity_change_that_loosens_the_posture_needs_a_loosener(self):
        p = self.posture("prototype")                                  # demo, assume
        out = ps.preview(p, maturity="explore")
        self.assertTrue(said(out)[0].startswith("This also loosens the Prototype posture: maturity demo to explore"),
                        said(out))
        self.assertIn("business_owner", said(out)[0])
        with self.assertRaisesRegex(DecisionRefused, "loosens the Prototype posture"):
            ps.change(p, person=AINO, persona="developer", reason="explore first", maturity="explore")
        self.assertEqual(p.meta["maturity"], "demo")
        ps.change(p, person=AINO, persona="business_owner", reason="explore first", maturity="explore")
        self.assertEqual(p.meta["maturity"], "explore")

    def test_a_maturity_or_mode_the_posture_does_not_take_is_refused(self):
        p = self.posture("balanced")
        self.assertIn("The Balanced posture does not take this", said(ps.preview(p, maturity="production"))[0])
        for given in ({"maturity": "production"}, {"mode": "assume"}):
            with self.assertRaisesRegex(ValueError, "The Balanced posture does not take this"):
                ps.change(p, person=AINO, persona="business_owner", reason="faster", **given)
        self.assertEqual((p.meta["maturity"], p.meta["mode"]), ("demo", "mixed"))

    def test_adopting_takes_a_posture_and_its_maturity_and_mode_or_production_and_mixed_as_before(self):
        from unittest import mock

        from kernel import cli

        asked = []
        common = ["--home", str(self.factory.home), "adopt", "Orders", "--source", str(self.factory.home),
                  "--intent", "maintain", "--person", AINO, "--persona", "developer"]
        with mock.patch("kernel.adopt.adopt", side_effect=lambda f, t, **kw: asked.append(kw) or self.posture("balanced")), \
                mock.patch("kernel.material_cli.confidential.refusal", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            for extra in ([], ["--posture", "regulated", "--weights", "security=3"], ["--posture", "production",
                                                                                     "--mode", "socratic"]):
                self.assertEqual(cli.main([*common, *extra]), 0)
        self.assertEqual([(a["maturity"], a["mode"], (a["posture"] or {}).get("name")) for a in asked],
                         [("production", "mixed", None), ("pilot", "socratic", "regulated"),
                          ("production", "socratic", "production")])
        self.assertEqual((asked[1]["posture"]["by"], asked[1]["posture"]["weights"]["security"]), (AINO, 3))

    def test_a_project_without_a_posture_changes_as_before(self):
        p = self.factory.new_project("Plain")
        out = ps.preview(p, maturity="explore")
        self.assertEqual((said(out), out["posture"]), ([], None))
        ps.change(p, person=AINO, persona="developer", reason="explore", maturity="explore")
        self.assertEqual(p.meta["maturity"], "explore")


if __name__ == "__main__":
    unittest.main()
