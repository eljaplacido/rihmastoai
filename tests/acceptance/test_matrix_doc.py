"""docs/acceptance.md is the matrix the owner tests against, and it stays true (FR-AM1).

A cell is a table row whose first column is its id in backticks (`G1.demo`) and whose last column
is its state: passes, fails or pending. A passing cell names its offline tests and each exists and
is not marked as an expected failure; a failing cell names a test marked as one; a pending cell
says why. Every acceptance test is named by a cell, and every row and column of the matrix has one.
The mode sweep's measured counts are what intake asks today, and the contract keeps the matrix's
requirements as the stream proposed them, not as decisions the owner made. This module's tests are
the matrix's own checks, not cells.
"""

import json
import re
import unittest
from pathlib import Path

from kernel.canon import Canon

from .scripts import AcceptanceCase

HERE = Path(__file__).resolve().parent
DOC = HERE.parents[1] / "docs" / "acceptance.md"
CONTRACT = HERE.parents[1] / "contract" / "contract.json"
CELL = re.compile(r"^\|\s*`([A-Z][A-Z0-9]*\.[a-z0-9-]+)`\s*\|(.*)\|\s*$")
STATE = re.compile(r"\*\*(passes|fails|pending)\*\*")
TEST = re.compile(r"`(test_FR_AM\d+_AC_\d+\w*)`")
DEF = re.compile(r"^(\s*@unittest\.expectedFailure\s*\n)?\s*def (test_FR_AM\d+_AC_\d+\w*)\(", re.MULTILINE)
ROWS = ("G1", "G2", "G3", "G4", "B", "W", "A", "C1", "C2", "I")
COLUMNS = ("M.socratic", "M.assume", "M.mixed", "G1.explore", "G1.demo", "G1.pilot", "G1.production",
           "P.prototype", "P.balanced", "P.production", "P.regulated", "X.single", "X.enforced")


def acceptance_tests() -> dict[str, bool]:
    """Each cell's test by name, and whether it is marked as an expected failure. This module's own
    test is the matrix's check, not a cell."""
    found: dict[str, bool] = {}
    for path in sorted(p for p in HERE.glob("test_*.py") if p.name != Path(__file__).name):
        for marked, name in DEF.findall(path.read_text(encoding="utf-8")):
            found[name] = bool(marked)
    return found


def cells(text: str) -> dict[str, tuple[str, list[str], str]]:
    """Each cell by id: its state, the tests it names, and its text."""
    out: dict[str, tuple[str, list[str], str]] = {}
    for line in text.splitlines():
        m = CELL.match(line)
        if not m:
            continue
        columns = [c.strip() for c in m.group(2).split("|")]
        state = STATE.fullmatch(columns[-1])
        out[m.group(1)] = (state.group(1) if state else columns[-1], TEST.findall(m.group(2)), m.group(2))
    return out


class MatrixDocTest(unittest.TestCase):
    def test_FR_AM1_AC_1_every_cell_has_a_measured_state_and_every_test_and_column_has_its_cell(self):
        text = DOC.read_text(encoding="utf-8")
        found, tests = cells(text), acceptance_tests()
        self.assertTrue(found, "docs/acceptance.md holds no cell")
        for cell_id, (state, named, body) in found.items():
            with self.subTest(cell=cell_id):
                self.assertIn(state, ("passes", "fails", "pending"))
                for name in named:
                    self.assertIn(name, tests, f"{cell_id} names a test that does not exist")
                if state == "passes":
                    self.assertTrue(named, f"{cell_id} passes but names no offline test")
                    self.assertEqual([n for n in named if tests[n]], [], f"{cell_id} names an expected failure")
                elif state == "fails":
                    self.assertTrue(named and all(tests[n] for n in named),
                                    f"{cell_id} fails: it names the test marked as an expected failure")
                else:
                    self.assertGreater(len(re.sub(r"[`|*\s]", "", body)), 40, f"{cell_id} is pending: say why")
        named_anywhere = {n for _, names, _ in found.values() for n in names}
        self.assertEqual(sorted(set(tests) - named_anywhere), [], "an acceptance test no cell names")
        for row in ROWS:
            self.assertTrue(any(c.split(".")[0] == row for c in found), f"row {row} has no cell")
        self.assertEqual([c for c in COLUMNS if c not in found], [], "a column with no cell")
        for row in ROWS:
            if row != "B":
                self.assertIn(f"{row}.production", found, f"row {row} has no production cell")

    def test_FR_AM1_AC_3_the_matrixs_requirements_are_proposed_by_the_stream_not_decided_by_the_owner(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        matrix = [r for r in contract["requirements"] if r["id"].startswith("FR-AM")]
        self.assertTrue(matrix, "the contract holds no FR-AM requirement")
        for r in matrix:
            with self.subTest(requirement=r["id"]):
                self.assertEqual(r["provenance"], "vendor-proposed")         # the wording is the stream's own
                self.assertNotIn("decided_by", r)                            # nobody decided it yet
                self.assertNotIn("decided_on", r)


# The rows of the mode sweep (docs/acceptance.md, "The mode sweep") and the need each files.
SWEEP_NEEDS = {"G1": "rooms", "G2": "queue", "G3": "visitors", "G4": "reports", "W": "purchases", "A": "invoices",
               "C1": "travel", "C2": "access", "I": "webhook"}
SWEEP = re.compile(r"Measured counts: (.*?)\.\n\n", re.DOTALL)
COUNT = re.compile(r"\b(G\d|W|A|C\d|I) (\d+)(?: questions)? \((\d+)")


class MatrixCountsTest(AcceptanceCase):
    roads = False

    def test_FR_AM1_AC_2_the_mode_sweeps_counts_on_the_page_are_what_intake_asks_today(self):
        sweep = SWEEP.search(DOC.read_text(encoding="utf-8"))
        self.assertIsNotNone(sweep, "docs/acceptance.md has no measured counts in its mode sweep")
        on_page = {row: (int(n), int(b)) for row, n, b in COUNT.findall(" ".join(sweep.group(1).split()))}
        self.assertEqual(sorted(on_page), sorted(SWEEP_NEEDS))
        for row, key in SWEEP_NEEDS.items():
            with self.subTest(row=row):
                questions = Canon(self.need(key, mode="mixed", maturity="demo")).questions()
                self.assertEqual(on_page[row], (len(questions), sum(1 for q in questions if q["blocking"])))
