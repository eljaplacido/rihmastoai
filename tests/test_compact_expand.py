"""Compact boxes open for review (FR-CMP1), without a browser: the wiring of every compact mode to Expand, the words,
the live view's earlier steps, and the map and parity entries. tests/test_ui_compact_expand.py drives the same in
Chrome.

The owner (2026-11-26): "When I change size of something to compact I guess I should be able to roll those compacted
boxes for review?"
"""

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.assistant_rules import ui_map  # noqa: E402
from kernel.control_pages import CONTROL_PAGES  # noqa: E402
from kernel.parity import CHAT, READS  # noqa: E402
from kernel.status import RECENT, live  # noqa: E402
from kernel.store import Factory  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "cockpit" / "static"


def js(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


class CompactExpandTest(unittest.TestCase):
    def test_FR_CMP1_AC_1_small_and_medium_widgets_open_in_full_in_the_side_panel_and_keep_their_size(self):
        dash = js("dashboard.js")
        self.assertIn('import { sheetButton, headToggles } from "./expand.js";', dash)
        # only a small or medium widget, never while customizing, drawn at the wide-and-tall size in the panel
        # (FR-CMP2: drawn with no cap, and Expand only where the card cuts something)
        self.assertIn('def && !custom && (w.size === "S" || w.size === "M") ? () =>', dash)
        self.assertIn('const full = cut ? sheetButton(', dash)
        self.assertIn('Object.assign({}, wv, { size: "XL", full: true })', dash)
        self.assertIn('label: word("expand.open"), icon: "expand", onclick: () => full.click()', dash)   # the widget menu
        self.assertIn('headToggles($(".card-head", el), full)', dash)                                      # its head
        xp = js("expand.js")
        sheet = xp[xp.index("export function sheetButton"):xp.index("// -- Ask Rihma")]
        self.assertNotIn("editLayout", sheet)                       # Expand never changes the layout's size
        self.assertIn('b.setAttribute("aria-controls", "xp-sheet")', sheet)
        self.assertIn("dlg.showModal()", sheet)
        self.assertIn("close.focus()", sheet)                       # the focus goes into the panel ...
        self.assertIn("b.focus()", xp[xp.index("function sheetEl"):xp.index("export function sheetButton")])   # ... and back
        css = (STATIC / "expand.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"@media \(max-width: 760px\) \{\s*\.xp-sheet \{ margin: auto 0 0; width: 100vw;")   # a sheet on a phone
        self.assertIn('<link rel="stylesheet" href="/static/expand.css">', js("index.html"))

    def test_FR_CMP1_AC_2_a_compact_section_expands_in_place_with_aria_and_keeps_its_size(self):
        vc = js("viewcustom.js")
        self.assertIn('if (lay.size[k] === "compact") compactSection(el, key + ":" + k, sectionLabel(el), () => sectionLabel(el));'
                      ' else dropInPlace(el);', vc)
        xp = js("expand.js")
        place = xp[xp.index("function apply(s, open)"):xp.index("export function dropInPlace")]
        for needed in ('box.classList.toggle("xp-open", open)', 's.b.setAttribute("aria-controls", box.id)', "OPEN.add(s.key)",
                       "queueMicrotask(() => { if (s.b.isConnected) s.b.focus(); })"):
            self.assertIn(needed, place)
        self.assertIn('b.setAttribute("aria-expanded", String(open))', xp)
        self.assertIn("s.b.hidden = s.owners.size === 1 && (!filled || (!cut && !open));", xp)   # nothing cut: no Expand
        css = (STATIC / "expand.css").read_text(encoding="utf-8")
        self.assertIn(".cz-compact.xp-open { max-height: none; overflow: visible; }", css)
        self.assertNotIn("saveViewLayout", xp)                      # the view's saved layout stays compact

    def test_FR_CMP1_AC_3_the_live_view_keeps_the_steps_before_the_last_action_newest_first(self):
        tmp = Path(tempfile.mkdtemp(prefix="rihma-cmp-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = Factory(tmp / "home").new_project("Room bookings", maturity="demo", mode="assume")
        lanes = tmp / "lanes"
        lane = lanes / "lane-1"
        (lane / ".gnomon-audit").mkdir(parents=True)
        (lanes / ".lane-1.lease.json").write_text(json.dumps({"holder": f"{p.pid}:T-001"}), encoding="utf-8")
        trail = [{"kind": "session_start", "role": "builder"}] + [
            {"kind": "tool_call", "tool": "write", "target": f"app/part_{n}.py", "ts": f"2026-11-26T10:00:{n:02d}Z"}
            for n in range(RECENT + 3)]
        (lane / ".gnomon-audit" / "task-1.jsonl").write_text("\n".join(json.dumps(r) for r in trail) + "\n", encoding="utf-8")
        got = live(p, lanes_root=lanes)
        self.assertEqual(got["steps"], RECENT + 3)
        self.assertEqual(len(got["recent"]), RECENT)
        self.assertEqual(got["recent"][0], got["last"])             # the last action first
        self.assertEqual([s["target"] for s in got["recent"][:3]],
                         [f"app/part_{n}.py" for n in (RECENT + 2, RECENT + 1, RECENT)])
        self.assertFalse(live(Factory(tmp / "home").new_project("Other", maturity="demo", mode="assume"),
                              lanes_root=lanes)["running"])
        # the box, the channel beside the view and the Agents strip each carry Expand in place
        self.assertIn('lv.recent, "live-last:" + LIVE.pid)', js("project.js"))
        agents = js("agents.js")
        self.assertIn('inPlace(aside, { key: "agent-aside", name: "Agent channel", head, place: tools })', agents)
        self.assertIn('class: i >= 5 ? "xp-more" : null', agents)
        self.assertIn('if (a.items.length > 5) inPlace(box, { key: "agents-strip:" + pid', agents)
        css = (STATIC / "expand.css").read_text(encoding="utf-8")
        self.assertIn(".xp-box:not(.xp-open) .xp-more { display: none; }", css)
        self.assertIn(".agent-aside.xp-open { inset: 0; width: auto; border-radius: 0; }", css)

    def test_FR_CMP1_AC_4_ask_rihma_opens_a_compact_box_by_name_and_the_map_has_the_control(self):
        ask = js("askscope.js")
        local = ask[ask.index("export function localAnswer"):ask.index("export function layoutBlock")]
        self.assertLess(local.index("expandIntent(q)"), local.index("viewLayoutIntent(q)"))   # before a layout change
        self.assertIn("applyExpand(xp)", local)
        self.assertIn('out.expandBox ? expandBlock(out.expandBox, idx) : null', js("assistant.js"))
        xp = js("expand.js")
        opens = re.search(r"const OPENS = /(.*)/;", xp).group(1)
        for said in ("expand", "unfold", "roll open", "show in full"):
            self.assertIn(said, opens)
        self.assertIn("collapse", re.search(r"const CLOSES = /(.*)/;", xp).group(1))
        self.assertIn("return b ? { verb, name: b.dataset.xpName, key: b.dataset.key } : null;", xp)   # else Rihma answers
        self.assertNotIn("api(", xp)                                # Expand writes nothing: no route
        control = next(c for c in ui_map()["controls"] if c["id"] == "expand_box")
        self.assertIn("expand a compact box", control["synonyms"])
        self.assertEqual(CONTROL_PAGES["expand_box"], (None, None))
        self.assertIn("expand_box", READS)
        self.assertNotIn("expand_box", CHAT)
        self.assertIn('"data-control": "expand_box"', xp)

    def test_FR_CMP1_AC_5_the_words_come_from_words_js(self):
        words = js("words.js")
        xp = js("expand.js")
        keys = set(re.findall(r'word\("(expand\.[a-z_]+)"\)', xp)) | set(re.findall(r'word\(open \? "(expand\.[a-z_]+)" : "(expand\.[a-z_]+)"\)', xp)[0])
        keys |= {"expand.open", "expand.close"}
        for key in sorted(keys):
            self.assertTrue(re.search(rf'"{re.escape(key)}": \[\s*"[^"]+",\s*"[^"]+"\]', words), f"{key} in words.js, plain and technical")
        self.assertNotRegex(xp, r'h\("span", \{ class: "lbl" \}, "(Expand|Collapse)"\)')   # no label outside words.js


if __name__ == "__main__":
    unittest.main()
