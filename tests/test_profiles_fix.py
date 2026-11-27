"""The work profile's confidence rule (FR-A9-AC-1): a proposal the rule is not sure of says so.

Dogfood: `propose_profile` proposed `ml_pipeline` for Rihmasto's own repository, and nothing said
that the agent profile scored the same. A low best score, or a best score close to the
runner-up's, is now uncertain: the proposal says so and names the top candidates, a question puts
them to a person, and adoption records the uncertainty.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_adopt import make_repo  # noqa: E402

from kernel.adopt import adopt, first_paragraph  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.profiles import (  # noqa: E402
    PROFILE_QUESTION,
    PROFILES,
    add_profile_question,
    profile_question,
    propose_profile,
)

ROOT = Path(__file__).resolve().parent.parent
# The README's first paragraph when the dogfood finding was made (main at 0d25c3b).
DOGFOOD = ("Rihma is a governed AI factory. Its product is agentic capability: apps, integrations, mobile "
           "prototypes, ML pipelines, agents and assistants, tuned agent harnesses, and ops agents that do a job "
           "and prove it. Models propose, a deterministic kernel decides whether work is accepted, and people "
           "decide what matters.")


def own_readme() -> str:
    # The README as it stood when this was decided (main at 26f45c8): many kinds of work in one text. The live
    # README now leads with one framing, so a frozen copy keeps testing a text whose signals are mixed.
    return (ROOT / "tests" / "fixtures" / "readme_many_kinds.txt").read_text(encoding="utf-8")


class ProfileConfidenceTest(FactoryTestCase):
    def test_FR_A9_AC_1_a_low_or_close_score_is_uncertain_and_names_the_top_candidates(self) -> None:
        dogfood = propose_profile(f"Rihmasto\n{DOGFOOD}")
        self.assertEqual((dogfood["profile"], dogfood["confidence"]), ("ml_pipeline", "uncertain"))
        self.assertEqual(dogfood["candidates"], ["ml_pipeline", "agentic_workflow", "mobile_prototype"])
        self.assertIn("a tie", dogfood["uncertain_because"])
        close = propose_profile("Integration feed: sync webhook events, an ML model, train on a dataset")
        self.assertEqual(close["confidence"], "uncertain")                           # 5 against 4: too close
        self.assertIn("too close to call", close["uncertain_because"])
        lone = propose_profile("A small service that tracks which equipment is lent to whom.")
        self.assertEqual((lone["profile"], lone["confidence"]), ("web_service", "uncertain"))
        self.assertIn("only one keyword", lone["uncertain_because"])
        nothing = propose_profile("Our team keeps losing track of who borrowed the drills.")
        self.assertIn("no keyword stood out", nothing["uncertain_because"])
        self.assertEqual(nothing["candidates"][0], "web_service")                    # the default leads
        for text, profile in (("Sync orders from SAP to our CRM via a webhook", "integration"),
                              ("We need a booking page where staff reserve the meeting rooms.", "web_service"),
                              ("Train a classifier on our dataset, F1 above 0.9", "ml_pipeline")):
            clear = propose_profile(text)
            self.assertEqual((clear["profile"], clear["confidence"], clear["candidates"]),
                             (profile, "clear", [profile]), text)
            self.assertIsNone(clear["uncertain_because"])
            self.assertIsNone(profile_question(clear))

    def test_FR_A9_AC_1_this_repositorys_own_readme_is_an_uncertain_proposal(self) -> None:
        text = own_readme()
        for request in (f"Rihmasto\n{first_paragraph(text)}", text):
            proposal = propose_profile(request)
            self.assertEqual(proposal["confidence"], "uncertain", proposal)
            self.assertGreaterEqual(len(proposal["candidates"]), 2, proposal)
            self.assertEqual(proposal["candidates"][0], proposal["profile"])

    def test_FR_A9_AC_1_an_uncertain_proposal_asks_a_person_with_the_top_candidates_as_options(self) -> None:
        proposal = propose_profile(f"Rihmasto\n{DOGFOOD}")
        q = profile_question(proposal)
        assert q is not None
        # Blocking since FR-DF4-AC-3: the spec waits for the answer in every mode.
        self.assertEqual((q["text"], q["perspective"], q["blocking"]), (PROFILE_QUESTION, "business", True))
        self.assertEqual(q["options"], ["ML or data pipeline (ml_pipeline)", "Agent or assistant (agentic_workflow)",
                                        "Mobile app prototype (mobile_prototype)"])
        self.assertIn("a tie", q["rationale"])
        p = self.new(mode="assume")
        canon = Canon(p)
        added = add_profile_question(canon, proposal)
        assert added is not None
        kept = canon.question(added["id"])
        self.assertEqual((kept["status"], kept["opinions"], kept["options"]), ("open", {}, q["options"]))
        # No proposed answer: intake's settling puts it to a person in every mode, assume included.
        self.assertEqual(kept["opinions"].get(kept["perspective"], ""), "")
        self.assertIsNone(add_profile_question(canon, propose_profile("Sync orders from SAP to our CRM")))
        self.assertEqual(len(canon.questions()), 1)

    def test_FR_A9_AC_1_adopting_this_repository_records_that_its_profile_is_uncertain(self) -> None:
        src = make_repo(self.tmp / "rihmasto", {"README.md": own_readme()})
        p = adopt(self.factory, "Rihmasto", source=str(src), intent="improve", person="Aino",
                  persona="product_owner", which=lambda name: None)
        # Uncertain, it is no longer taken: a person is asked which kind (FR-X1-AC-4, kernel/adopt_kind.py).
        self.assertEqual(p.ledger().of_kind("profile_chosen"), [])
        self.assertIsNone(p.meta.get("profile"))
        basis = p.ledger().of_kind("adopt_kind_asked")[-1]["event"]["payload"]
        self.assertGreaterEqual(len(basis["candidates"]), 2)
        self.assertTrue(basis["why"])
        recorded = p.read("adopted.json")["profile"]
        self.assertEqual((recorded["by"], recorded["confidence"], recorded["candidates"]),
                         ("rule", "uncertain", basis["candidates"]))
        brief = Canon(p).brief
        self.assertIn("a person is asked which kind of work it is", brief)
        for pid in basis["candidates"]:
            self.assertIn(PROFILES[pid]["label"], brief)


if __name__ == "__main__":
    unittest.main()
