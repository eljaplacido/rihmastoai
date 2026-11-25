"""Words per persona in every view, and Customize layouts that follow the person (FR-UXO1), in a real browser.

The owner: "review that for each persona in each view the terms are not AI slop, they are sensible, they make sense
in the context ... if you're a business persona the terms are like that; if you are a developer you want to
understand where we are on a technical level." And the layouts a person makes with Customize must follow them to a
separate work computer.

Every top-level page and every project view of the demo home is read as a business owner and as a developer. The
interface text a person sees (``VISIBLE``: every visible text node, except a record's own wording) must hold none of
the filler words words.js lists as SLOP, for anyone, and none of its JARGON for a business owner unless it is a
glossary term (``[data-term]``, explained in its tooltip). A record's own text (``[data-ud]``: titles, briefs,
findings, kernel-written lines), code, ids in monospace and folded details are not reworded and are left out.
Each empty view of a new project says what would appear and how it gets there, in different words for each reader.
The layouts are kept on the server: a browser's earlier layouts move there, a second browser profile sees them, and
Reset clears them.

It drives headless Chrome over the DevTools protocol on the demo home of ``test_ui_drive`` (skipped the same way when
Chrome or git is missing). ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
"""

import json
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_drive as drive  # noqa: E402  (the module, so its TestCase is not collected here again)

PERSON = drive.PERSON
WORDS_JS = Path(__file__).resolve().parent.parent / "cockpit" / "static" / "words.js"
PAGES = ["home", "square", "catalogue", "projects", "inbox", "insights", "floor", "jobs", "automations", "health", "review",
         "agents", "settings", "models", "runners"]
VIEWS = ["overview", "inbox", "review", "questions", "plan", "spec", "tasks", "changes", "align", "console", "assumptions",
         "assessment", "cell", "releases", "outputs", "checks", "automations", "try", "evidence", "track", "insights", "ledger",
         "agents", "aitools"]
# The views a new project, before its intake, shows empty: each says what would appear there and how.
EMPTY_VIEWS = ["questions", "assumptions", "spec", "tasks", "cell", "releases", "changes", "ledger"]


def _list(name: str) -> list:
    """A list exported from words.js (JARGON or SLOP), read from the file so the test and the page share it."""
    m = re.search(rf"export const {name} = \[(.*?)\];", WORDS_JS.read_text(encoding="utf-8"), re.S)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


JARGON = _list("JARGON")
SLOP = _list("SLOP")

# The visible interface text under a root, as [text, where] pairs (where: the nearest classes, for a readable failure).
VISIBLE = """((sel) => {
  const root = document.querySelector(sel);
  if (!root) return [];
  const skip = "code, pre, kbd, samp, .mono, [data-term], [data-ud], .vcz-tools, script, style, template, svg, .vh";
  const out = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) {
    const n = w.currentNode, el = n.parentElement, t = n.textContent.replace(/\\s+/g, " ").trim();
    if (!t || !el || el.closest(skip)) continue;
    if (el.checkVisibility && !el.checkVisibility({ visibilityProperty: true })) continue;
    if (!el.getClientRects().length) continue;
    const path = []; let x = el;
    while (x && x !== root && path.length < 3) {
      path.unshift(x.tagName.toLowerCase() + (typeof x.className === "string" && x.className.trim() ? "." + x.className.trim().split(/\\s+/).join(".") : ""));
      x = x.parentElement;
    }
    out.push([t, path.join(" > ")]);
  }
  return out;
})"""


def hits(pairs: list, words: list) -> list:
    """The (word, text, where) of every listed word found, as a whole word, in the visible text."""
    out = []
    for text, where in pairs:
        for wd in words:
            if re.search(r"(?<![\w-])" + re.escape(wd) + r"(?![\w-])", text, re.I):
                out.append((wd, text[:160], where))
    return out


def visible(browser, sel: str = "#main") -> list:
    return browser.eval(VISIBLE + f"({json.dumps(sel)})") or []


class UiWordsTest(unittest.TestCase):
    setUpClass = classmethod(drive.UiDriveTest.setUpClass.__func__)
    tearDownClass = classmethod(drive.UiDriveTest.tearDownClass.__func__)
    setUp = drive.UiDriveTest.setUp
    step = drive.UiDriveTest.step
    check = drive.UiDriveTest.check
    project = drive.UiDriveTest.project

    def sign_in(self, persona: str = "business_owner", browser=None) -> None:
        b = browser or self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.server.issue_link(600)}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid .widget')",
               "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what=persona)
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def persona(self, persona: str) -> None:
        b = self.browser
        b.click("#person-chip", what="the person chip")
        b.click(f'label[for="pp-{persona}"]', what=persona)
        b.click("#pp-done", what="Done")

    def go(self, where: str, ready: str, browser=None) -> None:
        b = browser or self.browser
        b.eval(f"location.hash = {json.dumps(where)}; true")
        b.wait(ready, where)

    def open_view(self, pid: str, view: str, browser=None, need: bool = True) -> bool:
        """Open a project's view; a view the project does not have is reported, not failed, unless needed."""
        b = browser or self.browser
        self.go("#/projects", "!!document.querySelector('.proj-card') && document.querySelector('#main').dataset.loaded === '1'", b)
        b.eval(f"location.hash = {json.dumps(f'#/p/{pid}/{view}')}; true")
        ready = (f"!!document.querySelector('.view-body') && document.querySelector('.view-body').dataset.view === '{view}'"
                 " && document.querySelector('#main').dataset.loaded === '1' && !document.querySelector('.view-body [aria-busy=\"true\"]')")
        try:
            b.wait(ready, f"{view} of {pid}", timeout=10 if need else 4)
        except AssertionError:
            if need:
                raise
            return False
        time.sleep(0.4)                                   # a view's own reads (the agents strip, the channel) settle
        return True

    def test_FR_UXO1_AC_8_every_view_says_it_in_the_readers_words_with_no_filler(self):
        b = self.browser
        webhook, stock = self.project("Shipment webhook to the stock system"), self.project("Stock levels service")
        self.sign_in("business_owner")
        found, read = [], 0
        for persona in ("business_owner", "developer"):
            if persona != "business_owner":
                self.persona(persona)
            words = SLOP + (JARGON if persona == "business_owner" else [])
            for page in PAGES:
                self.step(f"{persona} page {page}")
                self.go(f"#/{page}", "document.querySelector('#main').dataset.loaded === '1' && !!document.querySelector('#main h1')")
                time.sleep(0.4)
                found += [(persona, page) + x for x in hits(visible(b), words)]
            for p in (webhook, stock):
                for view in VIEWS:
                    self.step(f"{persona} {p.pid[:12]} {view}")
                    if self.open_view(p.pid, view, need=False):
                        read += 1
                        found += [(persona, view) + x for x in hits(visible(b), words)]
        self.assertEqual(found, [], "words a reader should not meet: " + json.dumps(found[:25], indent=1))
        self.assertGreaterEqual(read, 2 * 2 * (len(VIEWS) - 2), "views read")   # every view but the plan and Try it, twice per reader
        self.check()

    def test_FR_UXO1_AC_8_no_machine_patterns_in_what_a_person_reads(self):
        """The two readers' review: "(s)" plurals, "[embed E-001]" prefixes, UTC times, two names for the bucket of
        new ideas, and the kernel's raw now lines are never shown, in any text a person reads, a record's line included."""
        b = self.browser
        webhook = self.project("Shipment webhook to the stock system")
        self.sign_in("business_owner")
        bad = {r"\b\d+ [a-z ]+\(s\)": "a (s) plural", r"\[(embed|signal) [A-Z]+-\d+": "an id prefix on a request",
               r"\bUTC\b": "a UTC time", r"Rihma itself|The factory itself": "another name for new ideas",
               r"ready for the next step": "the kernel's raw now line", r"decided by the people who may": "a stiff next step",
               r"Let the factory assume": "the factory as the AI", r"Default layout": "noise about the layout"}
        found = []
        for persona in ("business_owner", "developer"):
            if persona != "business_owner":
                self.persona(persona)
            for page in ("home", "projects", "inbox", "review", "square", "catalogue", "floor"):
                self.step(f"{persona} patterns {page}")
                self.go(f"#/{page}", "document.querySelector('#main').dataset.loaded === '1' && !!document.querySelector('#main h1')")
                time.sleep(0.6)
                text = b.eval("document.querySelector('#main').innerText") or ""
                found += [(persona, page, why, m.group(0)) for rx, why in bad.items() for m in [re.search(rx, text)] if m]
            for view in ("overview", "inbox"):
                self.open_view(webhook.pid, view)
                text = b.eval("document.querySelector('#main').innerText") or ""
                found += [(persona, view, why, m.group(0)) for rx, why in bad.items() for m in [re.search(rx, text)] if m]
        self.assertEqual(found, [], json.dumps(found, indent=1))
        self.check()

    def test_FR_UXO1_AC_9_the_same_meaning_in_each_readers_words(self):
        b = self.browser
        webhook = self.project("Shipment webhook to the stock system")
        said = {}
        self.sign_in("business_owner")
        for persona in ("business_owner", "developer"):
            if persona != "business_owner":
                self.persona(persona)
            self.step(f"{persona} overview")
            self.open_view(webhook.pid, "overview")
            said[persona] = {
                "chips": b.eval("document.querySelector('.proj-head .chips').textContent"),
                "terms": b.eval("Object.fromEntries([...document.querySelectorAll('.view-body [data-term]')]"
                                ".map((t) => [t.dataset.term, t.textContent]))"),
                "stages": b.eval("[...document.querySelectorAll('.stepper .step-n')].map((s) => s.textContent)"),
            }
            self.open_view(webhook.pid, "ledger")
            said[persona]["ledger"] = b.eval("document.querySelector('.view-body .view-h').textContent")
            said[persona]["tab"] = b.eval("document.querySelector('.caps-sub a.on, .caps-sub a[aria-current]').textContent")
            self.open_view(webhook.pid, "tasks")
            said[persona]["lanes"] = b.eval("[...document.querySelectorAll('.lane-h')].map((x) => x.textContent).join('|')")
        biz, dev = said["business_owner"], said["developer"]
        self.assertIn("decision record intact", biz["chips"])
        self.assertIn("ledger intact", dev["chips"])
        self.assertIn("Ambition", biz["chips"])
        self.assertIn("Maturity", dev["chips"])
        self.assertTrue(biz["ledger"].endswith("Decision record"), biz["ledger"])
        self.assertTrue(dev["ledger"].endswith("Ledger"), dev["ledger"])
        self.assertIn("Decision record", biz["tab"])
        self.assertIn("Ledger", dev["tab"])
        self.assertIn("Done", biz["lanes"])
        self.assertIn("Merged", dev["lanes"])
        self.assertNotEqual(biz["stages"], dev["stages"])
        self.assertEqual(len(biz["stages"]), len(dev["stages"]))
        # a glossary term is the same concept for both readers, in each one's word
        self.assertEqual(set(biz["terms"]), set(dev["terms"]))
        self.assertTrue({"ledger", "maturity", "mode"} <= set(biz["terms"]), biz["terms"])
        for key in ("ledger", "maturity", "mode"):
            self.assertNotEqual(biz["terms"][key], dev["terms"][key], key)
        self.check()

    def test_FR_UXO1_AC_10_each_empty_view_says_what_would_appear_and_how(self):
        b = self.browser
        fresh = self.factory.new_project("Desk booking for the office")
        self.sign_in("business_owner")
        lines = {}
        for persona in ("business_owner", "developer"):
            if persona != "business_owner":
                self.persona(persona)
            for view in VIEWS:
                self.step(f"{persona} empty {view}")
                if not self.open_view(fresh.pid, view, need=view in EMPTY_VIEWS):
                    continue
                empties = b.eval("[...document.querySelectorAll('.view-body .empty')].filter((e) => e.getClientRects().length)"
                                 ".map((e) => [e.dataset.empty || '', (e.querySelector('.empty-t') || e).textContent.trim(),"
                                 " ((e.querySelector('.empty-how') || {}).textContent || '').trim()])")
                for _, what, how in empties:
                    self.assertTrue(what, f"{view}: an empty state with no line")
                    self.assertTrue(how, f"{view}: “{what}” does not say what would appear or how it gets there ({persona})")
                if view in EMPTY_VIEWS:
                    self.assertTrue(empties, f"{view} of a new project shows no empty state ({persona})")
                    lines[(persona, view)] = empties[0][1] + " " + empties[0][2]
            for view in EMPTY_VIEWS:
                self.assertNotRegex(lines[(persona, view)], r"(?i)\b(" + "|".join(map(re.escape, SLOP)) + r")\b")
        differ = [v for v in EMPTY_VIEWS if lines[("business_owner", v)] != lines[("developer", v)]]
        self.assertGreaterEqual(len(differ), len(EMPTY_VIEWS) - 1, differ)   # each reader's own words
        self.check()

    def test_FR_UXO1_AC_11_a_persons_layouts_follow_them_to_another_browser(self):
        b = self.browser
        webhook = self.project("Shipment webhook to the stock system")
        store = self.factory.home / "_cockpit" / "view-layouts"
        self.step("an earlier version's layout in this browser")
        b.cmd("Page.navigate", {"url": self.server.origin + "/"})
        b.wait("document.readyState === 'complete'", "the page")
        b.eval(f"localStorage.setItem({json.dumps('gf.vlayout.' + PERSON + '.g:projects')}, JSON.stringify({{order: [], hidden: ['old-section'], size: {{}}}}));"
               f"localStorage.setItem({json.dumps('gf.tabs.' + PERSON)}, JSON.stringify({{hidden: ['review'], pinned: []}})); true")
        self.sign_in("business_owner")
        self.open_view(webhook.pid, "overview")
        saved = b.wait(f"(async () => {{ const r = await fetch('/api/view-layouts?person=' + encodeURIComponent({json.dumps(PERSON)}),"
                       " { headers: { Authorization: 'Bearer ' + sessionStorage.getItem('gf.token') } }); const j = await r.json();"
                       " return j.saved ? j : null; })()", "the layouts moved to the server")
        self.assertEqual(saved["views"]["g:projects"]["hidden"], ["old-section"])
        self.assertEqual(saved["tabs"]["hidden"], ["review"])
        self.assertFalse(b.eval(f"!!localStorage.getItem({json.dumps('gf.tabs.' + PERSON)})"
                                f" || !!localStorage.getItem({json.dumps('gf.vlayout.' + PERSON + '.g:projects')})"))
        self.assertFalse(b.eval("!!document.querySelector('.caps-sub a[data-view=\"review\"]')"))   # the moved tab choice applies
        self.step("customize the overview")
        b.click("#customize", what="Customize")
        hide = b.wait("[...document.querySelectorAll('.vcz-tools [data-key$=\":hide\"]')].map((x) => x.dataset.key).pop()", "a section to hide")
        sec = hide.split(":")[1]
        b.click(f'[data-key="{hide}"]', what="Hide a section")
        b.click('[data-key="vcz:done"]', what="Done")
        b.wait("!document.querySelector('#vcz-bar')", "Customize done")
        doc = drive_wait(lambda: next((json.loads(f.read_text(encoding="utf-8")) for f in store.glob("*.json")), None),
                         lambda d: d and sec in d["views"].get("p:overview", {}).get("hidden", []))
        self.assertEqual(doc["person"], PERSON)
        self.assertFalse(any(sec in json.dumps(r) for p in self.factory.projects() for r in p.ledger().records()[-3:]))
        self.check()
        self.step("another browser profile, the same person")
        other = drive.Browser(self.chrome, self.tmp / "chrome-other-computer")
        self.addCleanup(other.close)
        other.shots = self.shots
        self.sign_in("business_owner", browser=other)
        self.open_view(webhook.pid, "overview", browser=other)
        other.wait(f"document.querySelector('[data-cz-key=\"{sec}\"]').classList.contains('cz-off')", "the hidden section, on the other computer")
        self.assertTrue(other.eval("!!document.querySelector('.vcz-hidden-note')"))
        self.assertFalse(other.eval("!!document.querySelector('.caps-sub a[data-view=\"review\"]')"))
        if self.shots:
            other.screenshot(self.shots / "other-computer-the-layout-followed.png")
        self.step("reset on the other computer")
        other.click("#customize", what="Customize")
        other.click('[data-key="vcz:reset"]', what="Reset")
        other.click('[data-key="vcz:done"]', what="Done")
        other.wait("!document.querySelector('.cz-off') && !!document.querySelector('.caps-sub a[data-view=\"review\"]')", "the default layout")
        drive_wait(lambda: json.loads(next(store.glob("*.json")).read_text(encoding="utf-8")),
                   lambda d: "p:overview" not in d["views"] and d["tabs"] == {"hidden": [], "pinned": []})
        self.assertEqual(other.problems, [])
        if self.shots:
            other.screenshot(self.shots / "other-computer-after-reset.png")
        self.step("back on the first computer")
        b.cmd("Page.reload", {})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('.view-body')"
               " && document.querySelector('#main').dataset.loaded === '1'", "the overview again")
        b.wait(f"!!document.querySelector('[data-cz-key=\"{sec}\"]') && !document.querySelector('.cz-off')", "the section shown again")
        self.check()


def drive_wait(read, ok, timeout: float = 10.0):
    """What ``read`` gives once ``ok`` holds for it (a file the server writes after the page's save)."""
    end = time.monotonic() + timeout
    while True:
        got = read()
        if ok(got):
            return got
        if time.monotonic() > end:
            raise AssertionError(f"timed out; last read: {got}")
        time.sleep(0.1)


if __name__ == "__main__":
    unittest.main()
