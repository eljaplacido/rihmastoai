"""Greenfield from an almost blank need (docs/acceptance.md, rows G1 to G4; FR-AM2).

A person types a need of one line, two vague lines, a written spec or a Finnish sentence. The panel
asks what changes the build, the mode settles each question, the spec and contract follow with
provenance, every task passes the gate, and the release lands where the maturity says, with a
valid capability pack.
"""

from kernel.canon import Canon
from kernel.deliver import latest_release

from .scripts import OWNER, AcceptanceCase, payloads


class GreenfieldTest(AcceptanceCase):
    def asked_and_assumed(self, p) -> tuple[list, int]:
        canon = Canon(p)
        asked = sorted(c["refs"]["question"] for c in canon.cards(kind="question"))
        return asked, len(canon.assumptions("open"))

    def holdouts_passed(self, p) -> list:
        results = (latest_release(p).get("holdouts") or {}).get("results") or []
        self.assertTrue(results)
        self.assertEqual({r["verdict"] for r in results}, {"passed"}, results)
        return [r["criterion"] for r in results]

    def test_FR_AM2_AC_1_a_one_line_need_is_asked_shaped_built_and_accepted_as_a_demo(self):
        p = self.need("rooms", mode="mixed", maturity="demo")
        asked, assumed = self.asked_and_assumed(p)
        self.assertEqual(asked, ["Q-001", "Q-005"])                     # who books, which rooms: to Aino
        self.assertEqual(assumed, len(Canon(p).questions()) - 2)        # the rest assumed, with due dates
        chosen = payloads(p, "profile_chosen")[-1]
        self.assertEqual((chosen["profile"], chosen["basis"]["confidence"]), ("web_service", "uncertain"))
        first = self.run_chain(p)
        self.assertEqual((first["state"], first["stage"]), ("waiting", 2))
        self.assertFalse(p.path("spec.json").exists())                  # nothing is built on a guess
        self.assertEqual(self.answer_blocking(p), ["Q-001", "Q-005"])
        out, decided = self.ship(p)
        self.assertEqual(decided, [("approval", "business_owner")])     # Aino accepts the demo
        prov = {r["id"]: (r["provenance"], r.get("decided_by")) for r in p.read("spec.json")["requirements"]}
        self.assertEqual(prov, {"R-1": ("customer-endorsed", "Aino"), "R-2": ("customer-confirmed", "Aino"),
                                "R-3": ("customer-confirmed", "Aino"), "R-4": ("vendor-proposed", None)})
        self.assertEqual(self.holdouts_passed(p), ["R-1-AC-2"])         # run on the demo's twin
        self.assertTrue((p.holdouts_dir / "R-1-AC-2.json").exists())    # in custody, outside the project
        self.assertNotIn(p.dir.resolve(), p.holdouts_dir.resolve().parents)
        pack = self.assertDelivered(p, out, "demo")
        self.assertEqual(pack["deliverable"], "product")
        self.assertTraced(p, decided_by={OWNER})

    def test_FR_AM2_AC_2_a_two_line_vague_need_asks_what_to_build_first_before_anything_is_built(self):
        p = self.need("queue", mode="mixed", maturity="demo")
        asked, _ = self.asked_and_assumed(p)
        self.assertEqual(asked, ["Q-001", "Q-002", "Q-003"])            # what first, where from, may an AI read
        self.assertEqual(self.run_chain(p)["state"], "waiting")
        self.answer_blocking(p)
        out, decided = self.ship(p)
        self.assertEqual(decided, [("approval", "business_owner")])
        spec = p.read("spec.json")
        ai = next(r for r in spec["requirements"] if "never sent on its own" in r["statement"])
        self.assertEqual((ai["provenance"], ai["decided_by"]), ("customer-confirmed", "Aino"))   # rests on Q-003
        self.assertIn("sending replies without a person", spec["out_of_scope"])
        self.assertEqual(self.holdouts_passed(p), ["R-1-AC-2"])
        self.assertDelivered(p, out, "demo")
        self.assertTraced(p, decided_by={OWNER})

    def test_FR_AM2_AC_3_a_written_spec_keeps_its_own_ids_and_is_asked_only_the_blocking_facet_it_leaves_out(self):
        p = self.need("visitors", mode="mixed", maturity="demo")
        self.assertEqual(p.read("source.json")["kind"], "markdown")
        canon = Canon(p)
        asked, assumed = self.asked_and_assumed(p)
        self.assertEqual(asked, ["Q-006"])                              # the spec never says what data it holds
        data = canon.question("Q-006")
        self.assertEqual((data["text"], data["perspective"], data["blocking"]),
                         ("What data will it hold, and how sensitive is it?", "it_security", True))
        self.assertEqual(assumed, len(canon.questions()) - 1)           # the panel's and the other gaps, assumed
        first = self.run_chain(p)
        self.assertEqual((first["state"], first["stage"]), ("waiting", 2))
        self.assertFalse(p.path("spec.json").exists())                  # nothing is built on a guess
        personal = next(o for o in data["options"] if o.startswith("personal"))
        with self.signed(OWNER):                                        # visitors' names are personal data
            canon.answer("Q-006", personal, person=OWNER[0], persona=OWNER[1])
        out, decided = self.ship(p)
        self.assertEqual(decided, [("approval", "business_owner")])
        self.assertEqual(Canon(p).question("Q-006")["answer"]["text"], personal)
        spec = p.read("spec.json")
        self.assertEqual([r["id"] for r in spec["requirements"]], ["VIS-001", "VIS-002", "VIS-003", "VIS-004", "R-1"])
        purge = spec["requirements"][-1]
        self.assertEqual(purge["provenance"], "assumption")             # 30 days rests on an assumption
        self.assertEqual({t["id"] for t in p.read("contract.json")["tasks"]}, {"T-001", "T-002", "T-003", "T-004",
                                                                              "T-005"})
        named = [g for g in payloads(p, "gate") if g["verdict"] == "passed"]
        self.assertEqual(len(named), 5)
        self.assertEqual(self.holdouts_passed(p), ["VIS-001-AC-2"])
        self.assertDelivered(p, out, "demo")
        self.assertTraced(p, decided_by={OWNER})

    def test_FR_AM2_AC_4_a_need_in_finnish_is_read_asked_and_specified_in_finnish(self):
        p = self.need("reports", mode="mixed", maturity="explore")
        chosen = payloads(p, "profile_chosen")[-1]
        self.assertEqual((chosen["profile"], chosen["basis"].get("confidence", "clear")), ("web_service", "clear"))
        asked, _ = self.asked_and_assumed(p)
        self.assertEqual(asked, ["Q-001"])
        self.assertIn("taloyhtiön asukkaat", Canon(p).brief)
        self.assertEqual(self.answer_blocking(p), ["Q-001"])
        out, decided = self.ship(p)
        self.assertEqual(decided, [])                                   # explore: nobody after the answer
        spec = p.read("spec.json")
        self.assertEqual(spec["requirements"][2]["provenance"], "customer-confirmed")
        self.assertIn("isännöitsijä", Canon(p).question("Q-001")["answer"]["text"])
        self.assertDelivered(p, out, "preview")
        self.assertTraced(p, decided_by={OWNER})
