---
id: A-0004
kind: contract-amendment (approved under delegation, see D-0009)
proposed_by: operator session, from the blind verifier's review of T-006 round 3
proposed_on: 2026-11-22
amends: contract r3
---

# The ledger criteria say what a chain can and cannot see

The blind verifier found three places where the criteria promised more than the behaviour can
give, or named it differently. The behaviour is the right one, so the wording changes:

- **FR-L1-AC-2:** a change to the *last* event, like an end cut off, is caught only against a
  head (AC-4). No chain alone can see it.
- **FR-L1-AC-3:** `head` is a third read-only method beside `append` and `read`. There is
  still no update and no delete.
- **FR-L1-AC-4:**
  - The head check is "the record at the head's sequence number". Events appended after a head
    was taken are fine.
  - An empty ledger's head is sequence -1, so a head taken before the first append still
    checks the tail.
  - A malformed head blames no record.

The three code gaps found with it (an empty-ledger head of `None`, a malformed head blamed on
record 0, a mutable `ALLOWED_KEYS`) were fixed by the operator, with tests that failed first.
