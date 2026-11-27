"""The Assessment view in a real browser (FR-BA1-AC-10): headless Chrome over the DevTools protocol.

The test builds the demo home (whose Stock levels service is an adopted system), starts the cockpit on
127.0.0.1 over it, signs in as a developer, opens the adopted project's Assessment tab, assesses it with the
keyboard, reads its findings by perspective, tries the quick selections, files two findings as different
kinds, and refiles one after its card is decided. It looks at the view in dark and light and at 1440 and
390 px wide, checks that every control has an accessible name and that
the page does not scroll sideways, and after every step that there was no console error, uncaught exception,
failed request or Content-Security-Policy violation. It is skipped when Chrome is not installed.
"""

import contextlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import roads  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
NAMELESS = ("[...document.querySelectorAll('#main button, #main input, #main select, #main a[href]')]"
            ".filter((el) => el.getClientRects().length && !((el.getAttribute('aria-label') || '').trim()"
            " || (el.labels && [...el.labels].some((l) => l.textContent.trim())) || el.textContent.trim()"
            " || el.getAttribute('title'))).map((el) => el.outerHTML.slice(0, 120))")
SIDEWAYS = "document.documentElement.scrollWidth > window.innerWidth + 1"


class UiAssessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        from kernel.demo import build_demo

        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-assess-")).resolve()
        try:
            build_demo(cls.tmp / "demo", echo=lambda line: None)
        except Exception:
            roads.stop_started()
            roads.rmtree(cls.tmp)
            raise
        cls.factory = Factory(cls.tmp / "demo")
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        roads.stop_started()
        with contextlib.suppress(OSError):  # a file Chrome still holds: the OS clears the temp folder later
            roads.rmtree(cls.tmp)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-assess")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    def step(self, name: str) -> None:
        if self.browser.step != "start":
            self.check()
        self.browser.step = name

    def check(self) -> None:
        b = self.browser
        b.eval("1")
        time.sleep(0.3)
        b.eval("1")
        self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
        self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
        self.assertEqual(b.eval(NAMELESS), [], f"controls without an accessible name during '{b.step}'")
        self.assertFalse(b.eval(SIDEWAYS), f"the page scrolls sideways during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"assess-{b.step.replace(' ', '-')}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000, "deviceScaleFactor": 1,
                                                                "mobile": px < 600})

    def theme(self, word: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def choose(self, selector: str, value: str) -> None:
        self.browser.eval(f"(() => {{ const s = document.querySelector({json.dumps(selector)});"
                          f" s.value = {json.dumps(value)}; s.dispatchEvent(new Event('change', {{ bubbles: true }}));"
                          " return s.value; })()")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out')"
               " && !!document.querySelector('#grid .widget')", "the signed-in dashboard")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def test_FR_BA1_AC_10_a_person_assesses_an_adopted_system_and_files_a_finding_in_chrome(self):
        b = self.browser
        stock = next(p for p in self.factory.projects() if p.meta.get("source_kind") == "adopted")
        pid = stock.pid
        self.step("sign in")
        self.sign_in()
        self.step("open the assessment")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{pid}/overview"})
        b.click('.cap-t[data-capsule="build"]', what="the Build capsule")          # FR-UXO1: Assessment is in Build
        b.click(f'.tabs a[href="#/p/{pid}/assessment"]', what="the Assessment tab")
        b.wait("((document.querySelector('.view-body h2') || {}).textContent || '').endsWith(' · Assessment')"
               " && !!document.querySelector('[data-control=\"run_assessment\"]')", "the Assessment view")
        self.assertIn("Not assessed yet.", b.eval("document.querySelector('.view-body').textContent"))
        self.assertTrue(b.eval("document.querySelector('#as-panel').disabled"))   # the panel needs a model
        self.step("assess with the keyboard")
        b.wait("(() => { const x = document.querySelector('[data-control=\"run_assessment\"]'); x.focus();"
               " return document.activeElement === x; })()", "Assess now focused")
        for kind in ("keyDown", "keyUp"):           # Enter with its text, as a keyboard sends it: the button acts
            b.cmd("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                                             "nativeVirtualKeyCode": 13, **({"text": "\r"} if kind == "keyDown" else {})})
        b.wait("(document.querySelector('#as-sum-h') || {}).textContent", "the recorded assessment", timeout=90)
        self.assertTrue(b.eval("document.querySelector('#as-sum-h').textContent.startsWith('AS-1 of revision')"))
        persp = b.eval("[...document.querySelectorAll('.as-persp .card-t')].map((x) => x.textContent)")
        self.assertEqual(persp, ["CI/CD governance", "Maintenance", "Security", "Compliance",
                                 "Architecture and operations"])
        record = json.loads(stock.path("assessments", "AS-1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["asked_by"], {"person": PERSON, "persona": "developer"})
        findings = [c for c in record["checks"] if c.get("verdict") == "failed"]
        first = next(c for c in findings if c.get("id") == "F-1")
        second = next(c for c in findings if c.get("id") != first["id"])

        self.step("review suggested order and kinds")
        reasons = b.eval("[...document.querySelectorAll('.as-prio ol li .muted')].map((x) => x.textContent)")
        self.assertTrue(reasons and all(r.strip().endswith(".") for r in reasons))
        for f in findings:
            sel = f"#as-kind-{f['id']}"
            self.assertEqual(b.eval(f"document.querySelector('{sel}').labels[0].textContent.trim()"),
                             f"File {f['id']} as")
            self.assertTrue(b.eval(f"document.querySelector('{sel}').value"))
            why = b.eval(f"document.querySelector('{sel}').getAttribute('aria-describedby')")
            self.assertIn("Suggested:", b.eval(f"document.getElementById({json.dumps(why)}).textContent"))
        b.click('[data-key="as-all"]', what="Select all open")
        b.wait(f"document.querySelector('.as-prio [role=\"status\"]').textContent === '{len(findings)} findings ticked'",
               "all findings ticked")
        b.click('[data-key="as-clear"]', what="Clear")
        b.wait("document.querySelector('.as-prio [role=\"status\"]').textContent === '0 findings ticked'",
               "the ticked findings cleared")
        b.click('[data-key="as-top"]', what="Select the top findings")
        top = min(5, len(findings))
        b.wait(f"document.querySelector('.as-prio [role=\"status\"]').textContent.startsWith('{top} ')",
               "the top findings ticked")
        b.click('[data-key="as-clear"]', what="Clear")

        self.step("file two findings as their own kinds")
        chosen = {first["id"]: "defect", second["id"]: "infra_change"}
        for fid, kind in chosen.items():
            box = f"#as-pick-{fid}"
            b.click(box, what=f"the {fid} finding's box")
            b.wait(f"document.querySelector('{box}').checked", f"{fid} ticked")
            self.choose(f"#as-kind-{fid}", kind)
        self.assertIn(first["title"], b.eval("document.querySelector('#as-pick-F-1').labels[0].textContent"))
        b.click('[data-control="assessment_changes"]', what="File the ticked findings as changes")
        cards = {}
        for fid, kind in chosen.items():
            filed = b.wait(f"(document.querySelector('[data-id=\"{fid}\"] a[href*=\"/changes/\"]') || {{}}).textContent",
                           f"the card {fid} was filed as")
            cards[fid] = filed.split()[2]
            card = Canon(stock).get_card(cards[fid])
            self.assertEqual(card["refs"]["origin"], "assessment")
            self.assertEqual(card["payload"]["triage"]["class"], kind)

        self.step("refile a finding whose card was decided")
        Canon(stock).decide(cards[first["id"]], "defer", person="Pekka", persona="business_owner",
                            reason="next quarter")
        b.cmd("Page.reload", {"ignoreCache": True})
        box = f"#as-pick-{first['id']}"
        b.wait(f"!!document.querySelector('{box}') && !!document.querySelector('#as-kind-{first['id']}')",
               "the decided finding can be filed again with its own kind")
        self.assertIn(first["id"], b.eval("document.querySelector('.as-prio').textContent"))
        b.click(box, what="the decided finding's box")
        self.choose(f"#as-kind-{first['id']}", "change_request")
        b.click('[data-control="assessment_changes"]', what="Refile the decided finding")
        changed = b.wait(f"(() => {{ const a = document.querySelector('[data-id=\"{first['id']}\"] a[href*=\"/changes/\"]');"
                         f" return a && !a.textContent.includes({json.dumps(cards[first['id']])}) ? a.textContent : ''; }})()",
                         "the decided finding's new card")
        new_card = Canon(stock).get_card(changed.split()[2])
        self.assertEqual(new_card["payload"]["triage"]["class"], "change_request")
        for word in ("Light", "Dark"):
            self.step(f"{word.lower()} theme at 1440 px")
            self.width(1440)
            self.theme(word)
            b.wait("!!document.querySelector('#as-sum-h')", f"the view in the {word} theme at 1440 px")
            self.step(f"{word.lower()} theme at 390 px")
            self.width(390)
            b.wait("!!document.querySelector('#as-sum-h') && window.innerWidth === 390", "the view at 390 px")
        self.check()


if __name__ == "__main__":
    unittest.main()
