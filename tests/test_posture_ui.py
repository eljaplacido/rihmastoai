"""Postures in a real browser (FR-POS6-AC-3): headless Chrome over the DevTools protocol.

A person opens New project, moves through the postures with the keyboard and sees the kernel's preview
change, raises a priority weight, chooses Regulated (a weight under its floor is not offered) and
creates the project; the project header's Posture chip opens what the posture does and what holds the
project, and a business owner changes it with a reason after seeing what loosens. The dialog is checked
dark and light, at 1440 and 390 pixels: no horizontal scrolling, every control named, and no console
error, failed request or Content-Security-Policy violation at any step.

It reuses the browser driver of tests/test_ui_drive.py, and is skipped when Chrome is not installed
(``RIHMA_CHROME`` names another browser binary). ``RIHMA_UI_SHOTS=<folder>`` saves a screenshot per step.
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
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
NEED = "Our team keeps losing track of who borrowed the drills and laptops. We want a simple way to lend and return things."
SECTION = ".pst-section"
FITS = ("(() => { const d = document.querySelector('#modal .modal-in');"
        " return document.documentElement.scrollWidth <= window.innerWidth"
        " && (!d || (d.scrollWidth <= d.clientWidth && d.getBoundingClientRect().right <= window.innerWidth + 1)); })()")
NAMED = ("(() => { const bad = []; document.querySelectorAll('#modal button, #modal input, #modal textarea').forEach((el) => {"
         " if (!el.getClientRects().length) return;"
         " const name = el.getAttribute('aria-label') || el.textContent.trim() || el.placeholder"
         " || (el.id && document.querySelector('label[for=\"' + el.id + '\"]') ? 'label' : '');"
         " if (!name) bad.push(el.outerHTML.slice(0, 80)); });"
         " document.querySelectorAll('#modal [role=radiogroup]').forEach((g) => { if (!g.getAttribute('aria-label')) bad.push('group'); });"
         " return bad; })()")


class PostureUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-posture-ui-")).resolve()
        cls.factory = Factory(cls.tmp / "home")
        cls.factory.new_project("Earlier work")      # not a new home: no first-run choice over the page
        cls.runner = QuietRunner()
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=cls.runner)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-posture")
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
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"posture-{b.step.replace(' ', '-')}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 900 if px > 500 else 800,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})

    def theme(self, mode: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=mode.capitalize(), what=f"{mode} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === '{mode}'", f"the {mode} theme")

    def preview_says(self, text: str) -> str:
        return self.browser.wait(f"(() => {{ const t = (document.querySelector('{SECTION} .pst-out') || {{}}).textContent || '';"
                                 f" return t.includes({json.dumps(text)}) && t; }})()", f"the preview saying {text}")

    def enter(self) -> None:
        for kind in ("keyDown", "keyUp"):
            self.browser.cmd("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "text": "\r",
                                                        "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})

    def test_FR_POS6_AC_3_a_person_chooses_and_changes_a_posture_in_chrome_with_the_preview_first(self):
        b = self.browser
        self.step("sign in")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in cockpit")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-business_owner"]', what="the business owner persona")
        b.click("#pp-done", what="Done")
        self.theme("dark")

        self.step("new project dark 1440")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/projects"})
        b.click('[data-control="new_project"]', what="New project")
        b.wait(f"!!document.querySelector('{SECTION} [data-key=\"posture:\"][aria-checked=\"true\"]')",
               "No posture chosen by default: nothing holds a daily user by surprise")
        self.preview_says("No posture: the project runs by the maturity and mode you choose")
        b.click(f'{SECTION} [data-key="posture:balanced"]', what="Balanced, one click away")
        self.preview_says("What Balanced will do")
        self.assertIn("go-ahead", self.preview_says("Autonomy 2"))
        self.assertEqual(b.eval(f"document.querySelectorAll('{SECTION} .pst-grid [role=radio]').length"), 5)
        self.assertEqual(b.eval(NAMED), [])
        self.assertTrue(b.eval(FITS))

        self.step("keyboard through the postures")
        b.eval(f"document.querySelector('{SECTION} [data-key=\"posture:balanced\"]').focus(); true")
        b.key("ArrowRight", 39)
        b.wait("document.activeElement.dataset.key === 'posture:production'"
               " && document.activeElement.getAttribute('aria-checked') === 'true'", "Production, by the arrow key")
        self.preview_says("A security scan is required before any landing, with the red team's static layer")
        b.click(f'{SECTION} [data-key="w-ux:3"]', what="UX priority 3")
        self.preview_says("Accessibility: include a requirement")
        self.assertEqual(b.eval(f"document.querySelector('{SECTION} [data-key=\"w-security:1\"]').disabled"), True)

        self.step("choose regulated and create")
        b.click(f'{SECTION} [data-key="posture:regulated"]', what="Regulated")
        self.preview_says("What Regulated will do")
        self.assertIn("Approving the plan confirms each requirement", self.preview_says("at any maturity"))
        self.assertEqual(b.eval(f"[...document.querySelectorAll('{SECTION} [data-key^=\"w-security:\"]')]"
                                ".map((x) => x.disabled).join()"), "true,true,true,false")
        b.type('input[aria-label="Title"]', "Equipment loans")
        b.type('textarea[aria-label="The need"]', NEED)
        b.click('button[type="submit"][data-control="new_project"]', what="Create and start the intake")
        b.wait("location.hash.startsWith('#/p/') && !!document.querySelector('.pst-chip')", "the new project")
        project = next(p for p in self.factory.projects() if p.meta.get("title") == "Equipment loans")
        self.assertEqual((project.meta["posture"]["name"], project.meta["posture"]["chosen_by"], project.meta["mode"]),
                         ("regulated", PERSON, "socratic"))
        self.assertEqual(self.runner.started[0][:4], ["-m", "kernel.cli", "intake", project.pid])
        self.assertEqual(b.eval("document.querySelector('.pst-chip').textContent"), "Posture: Regulated")

        self.step("the posture dialog by keyboard")
        b.eval("document.querySelector('.pst-chip').focus(); true")
        self.enter()
        b.wait("document.querySelector('#modal').open && document.querySelector('#modal-h').textContent.startsWith('Posture')",
               "the Posture dialog")
        said = b.wait("(document.querySelector('#modal .pst-dialog') || {}).textContent", "what the posture does")
        for text in ("What holds the project now", "What it does", "Chosen by " + PERSON, "The autonomy cap is 4"):
            self.assertIn(text, said)
        self.assertEqual(b.eval(NAMED), [])

        self.step("change it dark 390")
        self.width(390)
        b.wait(FITS, "the dialog within 390 pixels")
        b.click('#modal .pst-form [data-key="posture:prototype"]', what="Prototype in the dialog")
        warn = b.wait("(document.querySelector('#modal .pst-form .note.warning') || {}).textContent", "what loosens")
        self.assertIn("autonomy 1 to 3", warn)
        shown = b.wait("(document.querySelector('#modal .pst-form .pst-preview') || {}).textContent", "the new preview")
        self.assertIn("Mode assume", shown)                    # another posture starts from its own mode
        b.type("#pst-reason", "A rough demo first, then we tighten it")
        b.click('#modal .pst-form button[type="submit"]', what="Set the posture")
        b.wait("!document.querySelector('#modal').open", "the dialog closed")
        b.wait("(document.querySelector('.pst-chip') || {}).textContent === 'Posture: Prototype'", "the header's new posture")
        rec = project.meta["posture"]
        self.assertEqual((rec["name"], rec["chosen_by"], rec["persona"], rec["reason"]),
                         ("prototype", PERSON, "business_owner", "A rough demo first, then we tighten it"))
        self.assertTrue(b.eval(FITS))

        self.step("new project light 1440")
        self.width(1440)                                  # the theme menu is in the top bar at this width
        self.theme("light")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/projects"})
        b.click('[data-control="new_project"]', what="New project")
        self.preview_says("No posture: the project runs by the maturity and mode you choose")
        b.click(f'{SECTION} [data-key="posture:balanced"]', what="Balanced")
        self.preview_says("What Balanced will do")
        b.wait(FITS, "the New project dialog at 1440 pixels")
        self.assertEqual(b.eval(NAMED), [])
        b.click(f'{SECTION} [data-key="posture:"]', what="No posture")         # as before: any maturity and mode
        self.preview_says("No posture: the project runs by the maturity and mode you choose")
        self.assertEqual(b.eval(f"document.querySelectorAll('{SECTION} [data-key^=\"np-maturity:\"]').length"), 4)

        self.step("new project light 390")
        self.width(390)
        b.click(f'{SECTION} [data-key="posture:production"]', what="Production at 390 pixels")
        self.preview_says("What Production will do")
        b.wait(FITS, "the New project dialog within 390 pixels")
        self.check()

    def persona(self, persona: str) -> None:
        b = self.browser
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what=f"the {persona} persona")
        b.click("#pp-done", what="Done")

    def test_FR_POS7_AC_2_the_cockpit_offers_a_regulated_plan_only_to_the_people_who_may_approve_it(self):
        from factory_fakes import model

        from kernel.canon import Canon
        from kernel.intake import intake
        from kernel.plan import gate as plan_gate
        from kernel.spec import make_spec

        p = self.factory.new_project("Tool register", maturity="demo", posture={
            "name": "regulated", "by": PERSON, "persona": "business_owner"})
        intake(p, NEED, model=model(), requested_by=PERSON)
        canon = Canon(p)
        for q in canon.questions("open"):
            canon.answer(q["id"], q["opinions"].get(q["perspective"]) or "yes", person=PERSON, persona="business_owner")
        make_spec(p, model=model())
        card = plan_gate(p, model=model())["waiting_on"][0]
        b = self.browser
        self.step("plan as a developer dark 1440")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.server.issue_link()}"})   # a one-use link
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in cockpit")
        self.persona("developer")
        self.theme("dark")
        plan = f"{self.server.origin}/#/p/{p.pid}/plan"
        b.cmd("Page.navigate", {"url": plan})
        said = b.wait("(document.querySelector('.plan-wait') || {}).textContent", "who the plan waits on")
        self.assertIn("Waits on a decision by Business owner", said)
        self.assertEqual(b.eval(f"!!document.querySelector('[data-key=\"{card}:approve\"]')"), False)
        self.assertTrue(b.eval(FITS))
        # FR-POS7-AC-6: the project's Inbox counts nothing for a developer (the plan card is not theirs)
        self.assertEqual(b.eval("(document.querySelector('#sb-project .count') || {}).textContent || ''"), "")
        self.step("plan as a developer light 390")
        self.theme("light")                               # the theme menu is in the top bar at 1440 pixels
        self.width(390)
        b.wait(FITS, "the plan within 390 pixels")
        self.assertEqual(b.eval(f"!!document.querySelector('[data-key=\"{card}:approve\"]')"), False)
        self.step("plan as the business owner")
        self.width(1440)
        self.persona("business_owner")
        b.cmd("Page.navigate", {"url": plan})
        b.wait(f"!!document.querySelector('[data-key=\"{card}:approve\"]')", "Approve the plan for the business owner")
        self.assertEqual(b.eval(f"document.querySelector('[data-key=\"{card}:approve\"]').textContent"), "Approve the plan")
        b.wait("(document.querySelector('#sb-project .count') || {}).textContent === '1'", "the plan card in her Inbox count")
        self.check()


if __name__ == "__main__":
    unittest.main()
