import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from adapters.gnomon_ingest import AUDIT_KINDS, canonical_json, context, find_trail, ingest, verify_audit  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "gnomon"
# Shaped like Gnomon 0.6.6 from the tag's own schema files, chained by Gnomon's own canonicaliser
# in JavaScript (fixtures/gnomon-0.6.6/make_fixture.mjs says how and from what).
FIX_066 = Path(__file__).parent / "fixtures" / "gnomon-0.6.6"


class IngestTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.audit = self.tmp / "audit"
        shutil.copytree(FIX, self.audit)
        self.record = json.loads((self.audit / "analyst-run.record.json").read_text(encoding="utf-8"))
        self.trail = self.audit / "analyst-run.jsonl"

    def test_FR_C2_AC_1_one_ledger_event_carries_identity_chain_head_and_verdict(self):
        chain = verify_audit(self.trail)
        self.assertTrue(chain["intact"])                       # Gnomon's own hashes re-verified
        p = self.new()
        payload = ingest(p, self.record, self.trail, task="T-001", round_no=0)
        events = p.ledger().of_kind("gnomon_run")
        self.assertEqual(len(events), 1)
        e = events[0]["event"]["payload"]
        self.assertEqual(e, payload)
        self.assertEqual(e["surface_hash"], self.record["surface_hash"])
        self.assertEqual(e["harness"], "gnomon/0.6.5+fb458ea5")
        self.assertEqual((e["role"], e["model"]), ("analyst", "deepseek-v4-pro"))
        self.assertEqual(e["chain"]["head"], chain["head"])
        self.assertTrue(e["chain"]["intact"])
        self.assertEqual(e["verdict"], "not measured")          # an analyst run has no verify
        self.assertEqual(e["native"]["bucket"], "result")
        self.assertEqual(e["tokens"]["in"], 2366)

    def test_FR_C2_AC_2_a_broken_chain_is_tampered_and_not_measured(self):
        lines = self.trail.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[1])
        rec["completion_tokens"] = 1                            # rewrite a record, keep its hash
        lines[1] = json.dumps(rec)
        self.trail.write_text("\n".join(lines) + "\n", encoding="utf-8")
        chain = verify_audit(self.trail)
        self.assertFalse(chain["intact"])
        self.assertEqual(chain["broken_seq"], 1)
        p = self.new()
        record = dict(self.record, verify="passed")             # even a record claiming success
        e = ingest(p, record, self.trail)
        self.assertTrue(e["tampered"])
        self.assertEqual(e["verdict"], "not measured")
        missing = ingest(p, record, None)
        self.assertTrue(missing["tampered"])
        self.assertEqual(missing["verdict"], "not measured")

    def test_FR_C2_AC_5_a_0_6_6_trail_reverifies_intact_and_every_kind_is_kept(self):
        for name, records in (("builder-run.jsonl", 14), ("proposal-decision.jsonl", 3), ("inbox-item.jsonl", 3)):
            chain = verify_audit(FIX_066 / name)
            self.assertTrue(chain["intact"], (name, chain))
            self.assertEqual(chain["records"], records)
            self.assertEqual(sum(chain["kinds"].values()), records)       # every record counted, none dropped
        run = verify_audit(FIX_066 / "builder-run.jsonl")
        for kind in ("think_cap", "skill_use", "model_call", "checkpoint", "stall_signal"):
            self.assertIn(kind, run["kinds"])
        self.assertEqual(run["unknown_kinds"], ["external_context"])        # a newer Gnomon's kind is kept
        self.assertEqual(verify_audit(FIX_066 / "proposal-decision.jsonl")["kinds"]["proposal_decision"], 1)
        self.assertEqual(verify_audit(FIX_066 / "inbox-item.jsonl")["kinds"]["inbox_item"], 1)
        for kind in ("skill_use", "think_cap", "inbox_item", "proposal_decision"):
            self.assertIn(kind, AUDIT_KINDS)
        self.assertEqual(len(AUDIT_KINDS), 36)

    def test_FR_C2_AC_5_canonical_json_is_written_as_javascript_writes_it(self):
        # 0.00005, 1.5e-7, -0.00004: Python's json.dumps writes 5e-05, 1.5e-07 and -4e-05, so a
        # record holding one (a checkpoint's share_left, a stall signal's cusum, a policy's
        # token_delta) failed the chain check before. Key order is by UTF-16 code unit.
        cases = json.loads((FIX_066 / "canonical-cases.json").read_text(encoding="utf-8"))
        for case in cases:
            self.assertEqual(canonical_json(case["value"]), case["canonical"], case["value"])

    def test_FR_C2_AC_5_a_rewritten_0_6_6_record_still_breaks_the_chain(self):
        trail = self.tmp / "builder-run.jsonl"
        lines = (FIX_066 / "builder-run.jsonl").read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[2])
        self.assertEqual(rec["kind"], "model_call")
        rec["trim"]["basis"] = "measured"                                   # was "safety"
        lines[2] = json.dumps(rec, ensure_ascii=False)
        trail.write_text("\n".join(lines) + "\n", encoding="utf-8")
        chain = verify_audit(trail)
        self.assertFalse(chain["intact"])
        self.assertEqual(chain["broken_seq"], 2)
        self.assertEqual(sum(chain["kinds"].values()), 14)                   # still every record counted
        unchained = self.tmp / "unchained.jsonl"
        unchained.write_text(json.dumps({"seq": 0, "ts": "t", "kind": "session_start", "prev": None}) + "\n",
                             encoding="utf-8")
        self.assertFalse(verify_audit(unchained)["intact"])                 # [audit] chain = false proves nothing

    def test_FR_C2_AC_6_the_run_event_carries_the_window_its_source_the_trims_and_their_basis(self):
        record = json.loads((FIX_066 / "builder-run.record.json").read_text(encoding="utf-8"))
        p = self.new()
        e = ingest(p, record, FIX_066 / "builder-run.jsonl", task="T-001", round_no=0)
        self.assertTrue(e["chain"]["intact"])
        self.assertEqual(e["chain"]["unknown_kinds"], ["external_context"])
        self.assertEqual(e["harness"], "gnomon/0.6.6+v0.6.6-d3c574a")
        self.assertEqual(e["context"], {"window": 98304, "source": "listing:llamacpp",
                                        "trims": {"leg": 1, "overflow": 0, "pre_call": 1, "dropped": 9},
                                        "basis": {"measured": 1, "safety": 1}, "ratio": 1.074})
        self.assertEqual(e["verdict"], "not measured")                       # verify unrunnable
        self.assertEqual((e["native"]["verify_exit"], e["native"]["verify_rounds"]), (5, 1))
        self.assertNotIn("verify_tail", e["native"])                          # the check's output stays in the record
        # A 0.6.5 record: no pre_call trim and no basis yet; nothing is invented.
        old = context(self.record)
        self.assertEqual(old["trims"], {"leg": 0, "overflow": 0, "pre_call": 0, "dropped": 0})
        self.assertEqual((old["window"], old["source"], old["basis"]), (1000000, "listing:opencode", {}))
        self.assertEqual(context({}), {"window": None, "source": None, "trims": None, "basis": {}, "ratio": None})

    def test_find_trail_uses_the_session_name(self):
        (self.audit / f"{self.record['session']}.jsonl").write_text(self.trail.read_text(encoding="utf-8"),
                                                                  encoding="utf-8")
        self.assertEqual(find_trail(self.audit, self.record).name, f"{self.record['session']}.jsonl")
        self.assertIsNone(find_trail(self.audit, {"session": "nope"}))


if __name__ == "__main__":
    unittest.main()
