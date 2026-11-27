"""Compact boxes stay open for review (FR-CMP2), without a browser: the pieces tests/test_ui_compact_expand_fix.py drives
in Chrome are wired where they must be, the contract carries the owner's words, and the new module stays small.

The owner (2026-11-26): "When I change size of something to compact I guess I should be able to roll those compacted
boxes for review?" An independent check of FR-CMP1 found nine ways a compact box lost its Expand or said the wrong
thing; the browser test shows each one fixed, this one keeps the wiring from drifting.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.assistant_rules import ui_map  # noqa: E402
from kernel.parity import CHAT, READS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "cockpit" / "static"


def js(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def between(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


class CompactExpandFixTest(unittest.TestCase):
    def test_FR_CMP2_AC_5_the_wiring_the_words_and_the_contract_hold(self):
        xp = js("expand.js")
        keep = js("expandkeep.js")
        self.assertLessEqual(len(keep.splitlines()), 500)
        self.assertLessEqual(len(xp.splitlines()), 500)
        # one state per box, kept by the box: a box filled later gets its Expand back, the head finds the button there
        self.assertIn("const STATE = new WeakMap();", xp)
        self.assertIn("s.mo = new MutationObserver(() => keep(s));", xp)
        self.assertIn("s.mo.observe(box, { childList: true, subtree: true });", xp)
        place = between(xp, "export function inPlace", "export function dropInPlace")
        self.assertIn("if (s && s.owners.size) {", place)             # applied again: the same Expand
        self.assertIn("return s.b;", place)
        drop = between(xp, "export function dropInPlace", "// -- a view's compact section")
        self.assertIn("STATE.delete(box);", drop)                     # a normal section's head is plain again
        self.assertIn('s.lastHead.classList.remove("xp-head")', drop)
        section = between(xp, "export function compactSection", "// -- the live view's last-action box")
        self.assertIn('owner: "section"', section)
        self.assertIn("first: true", section)                         # first in the tab order
        # the side panel follows a redraw of its box, and lifts the toasts above its backdrop
        sheet = between(xp, "export function sheetButton", "// -- Ask Rihma")
        self.assertIn("shown.key === o.key && opener !== b) follow(b, o);", sheet)
        self.assertIn("liftToasts(dlg);", sheet)
        self.assertIn("dropToasts();", between(xp, "function sheetEl", "export function sheetButton"))
        # Expand only where the card cuts something, and the panel with no cap
        self.assertIn("export function cuts(shown, whole)", keep)
        self.assertIn('import { cuts } from "./expandkeep.js";', js("dashboard.js"))
        widgets = js("widgets.js")
        self.assertIn("const upTo = (w, n) => (w.full ? undefined : n);", widgets)
        self.assertEqual(len(re.findall(r"\.slice\(0, upTo\(w, ", widgets)), 4)
        # two sections never share a key, and a section's name never holds the Expand's words
        vc = js("viewcustom.js")
        self.assertIn("el.dataset.slot || slug(labelText(el)) || slug(el.classList[0])", vc)
        self.assertIn('for (let n = 2; seen.has(k); n += 1) k = base + "-" + n;', vc)
        self.assertIn('n.matches(".xp-btn, .vcz-tools")', vc)
        css = (STATIC / "expand.css").read_text(encoding="utf-8")
        self.assertIn(".cz-compact > .xp-btn { position: absolute; left: 0; right: 0; bottom: 0;", css)
        self.assertIn(".xp-sheet > .toasts {", css)
        # no new words outside words.js: every label the module says is a word("expand.*")
        self.assertNotRegex(xp + keep, r'h\("span", \{ class: "lbl" \}, "(Expand|Collapse)"\)')
        # Expand writes nothing: no route, the control a read on the map
        self.assertNotIn("api(", xp + keep)
        self.assertTrue(any(c["id"] == "expand_box" for c in ui_map()["controls"]))
        self.assertIn("expand_box", READS)
        self.assertNotIn("expand_box", CHAT)
        # the contract: the owner's words, decided by the owner, every criterion named by a test
        contract = json.loads((REPO / "contract" / "contract.json").read_text(encoding="utf-8"))
        req = next(r for r in contract["requirements"] if r["id"] == "FR-CMP2")
        self.assertEqual((req["provenance"], req["decided_by"], req["decided_on"]), ("customer-confirmed", "owner", "2026-11-26"))
        self.assertIn("roll those compacted boxes for review", req["notes"])
        self.assertIn("FR-CMP2", [r["id"] for r in contract["requirements"]])   # one of the last, as merges add others
        task = next(t for t in contract["tasks"] if "FR-CMP2-AC-1" in t["criteria"])
        self.assertEqual(task["criteria"], [f"FR-CMP2-AC-{n}" for n in range(1, 6)])


if __name__ == "__main__":
    unittest.main()
