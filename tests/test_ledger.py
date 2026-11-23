"""Tests for kernel/ledger.py (task T-006)."""

import hashlib
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from kernel.ledger import Ledger, canonical_json, event_hash, verify  # noqa: E402


class LedgerTest(unittest.TestCase):
    def test_FR_L1_AC_1_appended_events_carry_prev_and_canonical_sha256_hash_and_verify_is_intact(self):
        ledger = Ledger()
        first_payload = {"kind": "run", "id": "r-1"}
        first = ledger.append(first_payload)

        self.assertEqual(first["seq"], 0)
        self.assertIsNone(first["prev"])
        expected_first = hashlib.sha256(
            canonical_json({"event": first_payload, "prev": None, "seq": 0}).encode("utf-8")
        ).hexdigest()
        self.assertEqual(first["hash"], expected_first)

        second_payload = {"kind": "decision", "id": "d-1", "approved": True}
        second = ledger.append(second_payload)
        self.assertEqual(second["seq"], 1)
        self.assertEqual(second["prev"], first["hash"])
        expected_second = hashlib.sha256(
            canonical_json({"event": second_payload, "prev": first["hash"], "seq": 1}).encode("utf-8")
        ).hexdigest()
        self.assertEqual(second["hash"], expected_second)

        result = verify(ledger.read())
        self.assertTrue(result.intact)
        self.assertIsNone(result.broken_seq)

    def test_FR_L1_AC_1_canonical_json_ignores_dict_key_order(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), canonical_json({"a": 1, "b": 2}))
        self.assertEqual(canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')
        self.assertEqual(event_hash(0, {"b": 2, "a": 1}, None), event_hash(0, {"a": 1, "b": 2}, None))

    def test_FR_L1_AC_1_canonical_json_rejects_nan_and_infinity(self):
        """NaN and Infinity must not be allowed in canonical JSON."""
        with self.assertRaises(ValueError):
            canonical_json(float("nan"))
        with self.assertRaises(ValueError):
            canonical_json(float("inf"))
        with self.assertRaises(ValueError):
            canonical_json(float("-inf"))

    def test_FR_L1_AC_2_deleted_event_is_reported(self):
        """Deleting an event from the chain must report intact=False."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})

        events = ledger.read()
        del events[1]
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 1)

    def test_FR_L1_AC_2_swapped_events_are_reported(self):
        """Swapping two events in the chain must report intact=False."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})

        events = ledger.read()
        events[0], events[1] = events[1], events[0]
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_2_truncating_at_front_is_reported(self):
        """Truncating events at the front must report intact=False."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})

        events = ledger.read()
        del events[0]
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_2_splicing_events_is_reported(self):
        """Joining the head of one ledger to the tail of another must be reported."""
        a = Ledger()
        a.append({"ledger": "a", "id": 0})
        a.append({"ledger": "a", "id": 1})
        a.append({"ledger": "a", "id": 2})

        b = Ledger()
        b.append({"ledger": "b", "id": 0})
        b.append({"ledger": "b", "id": 1})
        b.append({"ledger": "b", "id": 2})

        events = a.read()[:2] + b.read()[2:]
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 2)

    def test_FR_L1_AC_2_verify_missing_keys_reports_broken_not_crash(self):
        """verify must not raise KeyError on records missing required fields."""
        bad_events = [
            {"seq": 0, "event": {"x": 1}},  # missing prev, hash
        ]
        result = verify(bad_events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

        bad_events2 = [
            {"seq": 0, "prev": None, "hash": "abc"},  # missing event
        ]
        result2 = verify(bad_events2)
        self.assertFalse(result2.intact)
        self.assertEqual(result2.broken_seq, 0)

        bad_events3 = [
            {"event": {"x": 1}, "prev": None, "hash": "abc"},  # missing seq
        ]
        result3 = verify(bad_events3)
        self.assertFalse(result3.intact)
        self.assertEqual(result3.broken_seq, 0)

    def test_FR_L1_AC_2_extra_fields_in_record_is_reported(self):
        """A record with keys outside {seq, event, prev, hash} must be broken."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        events = ledger.read()
        events[0]["extra_field"] = "tampered"
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_3_mutation_of_caller_dict_does_not_affect_read(self):
        """Mutating the caller's dict after append must not change what read() returns."""
        ledger = Ledger()
        caller_payload = {"kind": "run", "id": "r-1"}
        ledger.append(caller_payload)

        caller_payload["id"] = "tampered"
        stored = ledger.read()
        self.assertEqual(stored[0]["event"]["id"], "r-1")

    def test_FR_L1_AC_3_mutation_of_returned_record_does_not_affect_read(self):
        """Mutating the record returned by append must not change what read() returns."""
        ledger = Ledger()
        returned = ledger.append({"kind": "run", "id": "r-1"})
        returned["event"]["id"] = "tampered"

        stored = ledger.read()
        self.assertEqual(stored[0]["event"]["id"], "r-1")

    def test_FR_L1_AC_3_mutation_of_read_copy_does_not_affect_ledger(self):
        """Mutating the copy returned by read() must not change the ledger."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        copy = ledger.read()
        copy[0]["event"]["id"] = "tampered"

        stored = ledger.read()
        self.assertEqual(stored[0]["event"]["id"], "r-1")

    def test_FR_L1_AC_2_first_record_prev_must_be_none(self):
        """The first record must have prev=None; if not, verify reports broken."""
        bad_events = [
            {"seq": 0, "event": {"x": 1}, "prev": "not_none", "hash": "abc"},
        ]
        result = verify(bad_events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_2_seq_gap_reports_broken(self):
        """A gap in sequence numbers must be reported as broken."""
        from kernel.ledger import event_hash
        h0 = event_hash(0, {"x": 1}, None)
        # seq=2 at index 1 creates a gap (should be 1)
        bad_events = [
            {"seq": 0, "event": {"x": 1}, "prev": None, "hash": h0},
            {"seq": 2, "event": {"y": 2}, "prev": h0, "hash": "fake"},
        ]
        result = verify(bad_events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 1)

    def test_FR_L1_AC_2_changed_event_reports_first_broken_sequence_number(self):
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})

        events = ledger.read()
        events[1]["event"]["kind"] = "tampered"
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 1)

        events = ledger.read()
        events[0]["event"]["id"] = "tampered-first"
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_3_ledger_offers_append_read_and_head_only(self):
        ledger = Ledger()
        public = {
            name for name in dir(ledger)
            if not name.startswith("_") and callable(getattr(ledger, name))
        }
        self.assertEqual(public, {"append", "read", "head"})
        for forbidden in ("update", "delete", "remove", "pop", "insert", "replace", "clear"):
            self.assertFalse(hasattr(ledger, forbidden), forbidden)

    def test_FR_L1_AC_2_chain_linkage_tampered_middle_recomputed_hash(self):
        """Tamperer rewrites a middle record's payload and recomputes its own hash.
        The next record's prev no longer matches. Only the chain check catches this."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})

        events = ledger.read()
        # Tamper the middle record's payload
        events[1]["event"]["kind"] = "tampered"
        # Recompute its hash so it is internally consistent
        events[1]["hash"] = event_hash(
            events[1]["seq"], events[1]["event"], events[1]["prev"]
        )
        # The next record's prev still points to the old hash of record 1
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 2)

    def test_FR_L1_AC_2_sequence_continuity_gap_repaired_prev(self):
        """Delete a middle record, repair the following record's prev and recompute hash,
        keeping its original seq. Only the seq gap remains. Only the seq check catches this."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})

        events = ledger.read()
        # Delete the middle record (index 1)
        del events[1]
        # Now events[1] is the old record 2 (price), which has seq=2
        # Repair its prev to point at record 0's hash
        events[1]["prev"] = events[0]["hash"]
        # Recompute its hash so it is internally consistent
        events[1]["hash"] = event_hash(
            events[1]["seq"], events[1]["event"], events[1]["prev"]
        )
        # The seq is still 2 at index 1, creating a gap
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 1)

    def test_FR_L1_AC_2_first_record_prev_non_none_recomputed_hash(self):
        """Set the first record's prev to a non-None value and recompute its hash.
        Only the first-record-prev check catches this."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})

        events = ledger.read()
        events[0]["prev"] = "fake_prev_hash"
        events[0]["hash"] = event_hash(
            events[0]["seq"], events[0]["event"], events[0]["prev"]
        )
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_2_verify_nan_in_payload_reports_broken_not_raises(self):
        """A stored record whose event payload contains float('nan') must not make
        verify raise ValueError. It must report that position as broken instead."""
        bad_events = [
            {"seq": 0, "event": {"value": float("nan")}, "prev": None, "hash": "abc"},
        ]
        result = verify(bad_events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_1_append_stores_canonical_json_round_trip(self):
        """append stores the JSON round trip of the payload and hashes that stored value."""
        ledger = Ledger()
        first = ledger.append({1: "a"})
        self.assertEqual(first["event"], {"1": "a"})
        self.assertEqual(ledger.read()[0]["event"], {"1": "a"})

        second = ledger.append({"t": (1, 2)})
        self.assertEqual(second["event"], {"t": [1, 2]})
        self.assertEqual(ledger.read()[1]["event"], {"t": [1, 2]})

        result = verify(ledger.read())
        self.assertTrue(result.intact)
        self.assertIsNone(result.broken_seq)

    def test_FR_L1_AC_1_dict_subclass_deepcopy_is_not_used(self):
        """A dict subclass whose __deepcopy__ lies must still be stored as its JSON content."""
        class CopyLyingDict(dict):
            def __deepcopy__(self, memo):
                return {"spoofed": True}

        ledger = Ledger()
        ledger.append(CopyLyingDict({"kind": "run", "id": "r-1"}))
        stored = ledger.read()[0]["event"]
        self.assertEqual(stored, {"kind": "run", "id": "r-1"})
        self.assertIs(type(stored), dict)
        result = verify(ledger.read())
        self.assertTrue(result.intact)
        self.assertIsNone(result.broken_seq)

    def test_FR_L1_AC_1_non_json_payloads_are_rejected_and_nothing_is_appended(self):
        """A set, a bare object and NaN are not JSON, so append raises and appends nothing."""
        bad_payloads = [{1, 2}, {"bad": {1, 2}}, object(), float("nan")]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                ledger = Ledger()
                with self.assertRaises((ValueError, TypeError)):
                    ledger.append(payload)
                self.assertEqual(ledger.read(), [])

    def test_FR_L1_AC_2_seq_must_be_exact_int_not_bool(self):
        """True and False are ints in Python but must still be rejected as seq values."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        events = ledger.read()
        events[1]["seq"] = True
        events[1]["hash"] = event_hash(
            events[1]["seq"], events[1]["event"], events[1]["prev"]
        )
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 1)

        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        events = ledger.read()
        events[0]["seq"] = False
        events[0]["hash"] = event_hash(
            events[0]["seq"], events[0]["event"], events[0]["prev"]
        )
        result = verify(events)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_2_verify_never_raises_on_malformed_records(self):
        """verify returns a broken result for malformed records instead of raising."""
        deep_payload = current = {}
        for _ in range(100000):
            current["n"] = {}
            current = current["n"]

        malformed = [
            {"seq": 0, "event": {1, 2}, "prev": None, "hash": "abc"},
            {"seq": 0, "event": {"bad": {1, 2}}, "prev": None, "hash": "abc"},
            {"seq": 0, "event": {1: "int", "a": "str"}, "prev": None, "hash": "abc"},
            {"seq": 0, "event": deep_payload, "prev": None, "hash": "abc"},
            "not a dict",
            {"seq": 0, "event": {"x": 1}, "prev": {1, 2}, "hash": "abc"},
            {"seq": 0, "event": {"x": 1}, "prev": None, "hash": 123},
        ]
        for i, bad_event in enumerate(malformed):
            with self.subTest(i=i):
                result = verify([bad_event])
                self.assertFalse(result.intact)
                self.assertEqual(result.broken_seq, 0)

    def test_FR_L1_AC_2_verify_accepts_any_iterable(self):
        """verify must accept iterables such as generators, not just lists."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        events = ledger.read()
        result = verify(iter(events))
        self.assertTrue(result.intact)
        self.assertIsNone(result.broken_seq)

    def test_FR_L1_AC_4_append_returns_stored_record_and_head_reports_it(self):
        """append returns the new head record and head() reports seq and hash."""
        ledger = Ledger()
        self.assertEqual(ledger.head(), {"seq": -1, "hash": None})

        first = ledger.append({"kind": "run", "id": "r-1"})
        self.assertEqual(first, ledger.read()[0])
        self.assertEqual(ledger.head(), {"seq": 0, "hash": first["hash"]})

        second = ledger.append({"kind": "decision", "id": "d-1"})
        self.assertEqual(second, ledger.read()[1])
        self.assertEqual(ledger.head(), {"seq": 1, "hash": second["hash"]})

    def test_FR_L1_AC_4_verify_with_head_reports_truncated_tail(self):
        """A ledger shorter than head['seq'] + 1 is broken at the first missing position."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})
        head = ledger.head()

        result = verify(ledger.read()[:1], head=head)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 1)
        self.assertTrue(result.tail_checked)

        result = verify([], head=head)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 0)
        self.assertTrue(result.tail_checked)

    def test_FR_L1_AC_4_verify_with_head_reports_tail_hash_mismatch(self):
        """A ledger whose record at head['seq'] has another hash is broken there."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})
        head = {"seq": 2, "hash": "f" * 64}

        result = verify(ledger.read(), head=head)
        self.assertFalse(result.intact)
        self.assertEqual(result.broken_seq, 2)
        self.assertTrue(result.tail_checked)

    def test_FR_L1_AC_4_verify_with_head_allows_events_appended_after_it(self):
        """A ledger longer than the expected head is intact, not broken."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        ledger.append({"kind": "decision", "id": "d-1"})
        ledger.append({"kind": "price", "id": "p-1"})
        events = ledger.read()
        head = {"seq": 1, "hash": events[1]["hash"]}

        result = verify(events, head=head)
        self.assertTrue(result.intact)
        self.assertIsNone(result.broken_seq)
        self.assertTrue(result.tail_checked)

    def test_FR_L1_AC_4_verify_without_head_reports_tail_not_checked(self):
        """Without a head, verify cannot check truncation at the end."""
        ledger = Ledger()
        ledger.append({"kind": "run", "id": "r-1"})
        result = verify(ledger.read())
        self.assertTrue(result.intact)
        self.assertFalse(result.tail_checked)

    # Operator fixes after the round-3 blind verifier (findings 3, 4, 6).
    def test_FR_L1_AC_4_head_of_an_empty_ledger_still_checks_the_tail(self):
        empty_head = Ledger().head()
        ledger = Ledger()
        for i in range(3):
            ledger.append({"n": i})
        result = verify(ledger.read()[:1], empty_head)
        self.assertTrue(result.intact)
        self.assertTrue(result.tail_checked)

    def test_FR_L1_AC_4_malformed_head_is_not_blamed_on_a_record(self):
        ledger = Ledger()
        for i in range(3):
            ledger.append({"n": i})
        for head in ({"seq": "x", "hash": "y"}, {"seq": 1}, "not a head", {"seq": -1, "hash": "h"}):
            result = verify(ledger.read(), head)
            self.assertFalse(result.intact)
            self.assertIsNone(result.broken_seq)
            self.assertFalse(result.tail_checked)

    def test_FR_L1_AC_2_allowed_keys_cannot_be_widened_at_run_time(self):
        with self.assertRaises(AttributeError):
            Ledger.ALLOWED_KEYS.add("note")


if __name__ == "__main__":
    unittest.main()
