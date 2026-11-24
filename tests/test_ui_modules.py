"""The cockpit shows only what is enabled (FR-MOD4), in a real browser: headless Chrome over the DevTools
protocol, as tests/test_ui_drive.py drives it.

A new factory home offers its first-run choice; a person picks Spec only with the keyboard and the page
shows only what that set holds: the sidebar, the phone's bar, Home's widgets, the widget library, the
palette, a project's views and the assistant's suggestions. A page of a module that is off says which
module adds it; the assistant, asked about it, names the module and takes the person to Settings,
Modules, where they turn the delivery square on, and a project's own set is chosen. Dark and light, 1440
and 390 pixels wide: nothing spills sideways, every control of these pages has an accessible name, and no
step leaves a console error, a failed request or a Content-Security-Policy violation behind.

Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary) or git is missing.
``RIHMA_UI_SHOTS=<folder>`` also saves a screenshot per step.
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

from factory_fakes import model  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import embeds as kembeds  # noqa: E402
from kernel import modules  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import Factory  # noqa: E402

PERSON = "Aino Virtanen"
IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
# Every control of the modules card, the first-run dialog, the off page and the notes has a name a screen
# reader says: a label, an aria-label or its own text. Hidden ones are left out.
NAMELESS = """(() => [...document.querySelectorAll(
  '.mod-card :is(button, a[href], input, select), #modal :is(button, a[href], input, select), .mod-off :is(a, button),'
  + ' .mod-note a, [role=radio]')].filter((el) => el.getClientRects().length).filter((el) => {
    const label = (el.labels ? [...el.labels].map((l) => l.textContent).join(' ') : '') || el.getAttribute('aria-label') || '';
    const own = /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) ? '' : el.textContent;
    return !(label + own).trim(); }).map((el) => el.outerHTML.slice(0, 120)))()"""


class UiModulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for a project's contract")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-modules-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.factory = Factory(self.tmp / "home")
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    # -- helpers -------------------------------------------------------------------------------------------

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
        self.assertEqual(b.eval(NAMELESS), [], f"controls with no accessible name during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"modules-{b.step.replace(' ', '-')}.png")

    def sign_in(self, *, dialog: bool = False) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        if dialog:
            return
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-business_owner"]', what="the business owner persona")
        b.click("#pp-done", what="Done in the person menu")

    def press(self, key: str, code: int, text: str = "") -> None:
        """A key as a person presses it: down, its character (a space activates a checkbox), up."""
        b = self.browser
        b.cmd("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": key, "code": key, "windowsVirtualKeyCode": code})
        if text:
            b.cmd("Input.dispatchKeyEvent", {"type": "char", "text": text, "key": key})
        b.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": key, "windowsVirtualKeyCode": code})

    def nav_pages(self) -> list:
        return self.browser.eval("[...document.querySelectorAll('#sb-nav a')].map((a) => a.getAttribute('href'))")

    def spec_only_with_a_project(self):
        modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        p = self.factory.new_project("Equipment loans", mode="assume", maturity="explore")
        intake(p, IDEA, model=model(), requested_by="Aino")
        return p

    def records(self, project=None) -> list:
        target = project or factory_project(self.factory)
        return [r["event"]["payload"] for r in target.ledger().of_kind("modules_set")]

    # -- the tests -----------------------------------------------------------------------------------------

    def test_FR_MOD4_AC_2_a_new_home_offers_a_first_run_choice_and_settings_changes_the_set_by_keyboard(self):
        b = self.browser
        self.step("first run")
        self.sign_in(dialog=True)
        b.wait("!!document.querySelector('#modal[open] .mod-presets')", "the first-run choice")
        self.assertEqual(b.eval("document.querySelector('#modal [role=radiogroup]').getAttribute('aria-label')"),
                         "Where to start")
        self.assertEqual(b.eval("document.querySelectorAll('#modal [role=radio]').length"), len(modules.PRESETS))
        self.assertEqual(b.active(), "fr-name")                                  # the dialog starts at the name
        b.cmd("Input.insertText", {"text": PERSON})
        b.eval("document.querySelector('#modal [role=radio][tabindex=\"0\"]').focus(); true")
        self.press("Home", 36)                                                   # the first preset: Spec only
        b.wait("document.activeElement.dataset.key === 'preset:spec_only'"
               " && document.activeElement.getAttribute('aria-checked') === 'true'", "Spec only chosen by the keyboard")
        self.step("first run chosen")
        b.click("#modal button", text="Start with this", what="Start with this")
        b.wait("!document.querySelector('#modal').open && !document.querySelector('#sb-nav a[href=\"#/square\"]')",
               "the dialog closed and the set in force")
        self.assertEqual(b.eval("document.querySelector('#pc-name').textContent"), PERSON)   # the name shows at once
        self.assertEqual(self.nav_pages(), ["#/home", "#/projects", "#/inbox", "#/jobs", "#/automations"])
        rec = self.records()[-1]
        self.assertEqual((rec["preset"], rec["by"], rec["persona"], rec["reason"]),
                         ("spec_only", PERSON, "business_owner", "the first-run choice"))
        self.step("settings")
        b.click('#sb-foot a[href="#/settings"]', what="Settings")
        b.wait("!!document.querySelector('.mod-card .mod-list')", "the modules card")
        self.assertIn("This factory uses: Spec only", b.eval("document.querySelector('.mod-now').textContent"))
        off = b.eval("document.querySelector('label[for=\"mod-m-square\"]').closest('.mod-row').textContent")
        self.assertIn("Off. Turning it on adds needs arriving as signals", off)
        b.eval("document.querySelector('[data-key=\"mod:m:square\"]').focus(); true")
        self.press(" ", 32, " ")
        b.wait("document.querySelector('[data-key=\"mod:m:square\"]').checked"
               " && document.activeElement.dataset.key === 'mod:m:square'", "the square checked, the focus kept")
        self.assertEqual(b.eval("document.querySelector('#mod-preset').value"), "")   # a set of its own now
        b.type("#mod-reason", "needs come in as signals")
        b.click('[data-key="mod:save"]', what="Save the modules")
        b.wait("!!document.querySelector('#sb-nav a[href=\"#/square\"]')", "the square in the sidebar")
        rec = self.records()[-1]
        self.assertEqual((rec["to"], rec["reason"]), (["intake", "plan", "square"], "needs come in as signals"))
        self.step("a project's own set")
        p = self.factory.new_project("Equipment loans", mode="assume", maturity="explore")
        b.click('#sb-nav a[href="#/home"]', what="Home")
        b.click('#sb-foot a[href="#/settings"]', what="Settings")
        b.wait(f"!!document.querySelector('#mod-scope option[value=\"{p.pid}\"]')", "the project in the scope list")
        b.eval(f"(() => {{ const s = document.querySelector('#mod-scope'); s.value = {json.dumps(p.pid)};"
               " s.dispatchEvent(new Event('change')); return true; })()")
        b.wait("document.querySelector('#mod-inherit').checked", "the project follows the factory")
        b.click('label[for="mod-inherit"]', what="Use the factory's set")
        b.click('label[for="mod-m-change"]', what="the change loop")
        b.click('[data-key="mod:save"]', what="Save the modules")
        b.wait(f"(document.querySelector('.mod-now') || {{}}).textContent.startsWith('This project has its own set')",
               "the project's own set")
        rec = self.records(p)[-1]
        self.assertEqual((rec["scope"], rec["to"], rec["by"]), ("project", ["intake", "plan", "change", "square"], PERSON))
        self.check()

    def test_FR_MOD4_AC_1_only_what_is_enabled_is_shown_and_what_is_off_is_named_with_a_way_to_turn_it_on(self):
        b = self.browser
        p = self.spec_only_with_a_project()
        self.step("home")
        self.sign_in()
        b.wait("!!document.querySelector('#grid .widget')", "the dashboard")
        self.assertEqual(self.nav_pages(), ["#/home", "#/projects", "#/inbox", "#/jobs", "#/automations"])
        self.assertFalse(b.eval("!!document.querySelector('#bottombar a[href=\"#/square\"]')"))
        types = b.eval("[...document.querySelectorAll('#grid .widget')].map((w) => w.dataset.type)")
        self.assertFalse({"square", "catalogue"} & set(types))                    # the business lens's two of them
        self.assertIn("2 widgets of this layout are hidden", b.eval("document.querySelector('.mod-note').textContent"))
        figures = b.eval("document.querySelector('#grid .widget[data-type=\"kpi_strip\"]').textContent")
        self.assertNotIn("Capabilities in use", figures)                         # a figure of a module that is off
        self.assertNotIn("First-round gate pass", figures)
        self.assertIn("Decisions waiting", figures)
        b.click("#customize", what="Customize")
        b.click('#cz-bar [data-key="cz:add"]', what="Add a widget")
        lib = b.wait("(document.querySelector('#library:not([hidden]) .lib-list') || {}).textContent", "the library")
        self.assertNotIn("Delivery square", lib)
        self.assertIn("more widgets are hidden", b.eval("document.querySelector('#library .mod-note').textContent"))
        b.click("#library button[aria-label='Close the library']", what="Close the library")
        b.click("#cz-bar button", text="Cancel", what="Cancel")
        self.step("palette")
        b.eval("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, bubbles: true})); true")
        listed = b.wait("document.querySelector('#palette').open && document.querySelector('#pal-list').textContent",
                        "the palette")
        self.assertNotIn("Square", listed)
        self.assertIn("Projects", listed)
        self.press("Escape", 27)
        self.step("a page that is off")
        b.eval("location.hash = '#/square'; true")
        said = b.wait("(document.querySelector('.mod-off') || {}).textContent", "the off page")
        self.assertIn("Square is part of Delivery square and signals, which is not enabled here", said)
        self.step("project views")
        b.eval(f"location.hash = '#/p/{p.pid}/releases'; true")                 # an address of a view that is off
        b.wait(f"location.hash.startsWith('#/p/{p.pid}') && !!document.querySelector('.tabs')", "the project")
        tabs = b.eval("[...document.querySelectorAll('.tabs a')].map((a) => a.getAttribute('href').split('/').pop())")
        self.assertFalse({"tasks", "cell", "releases", "try", "changes", "evidence"} & set(tabs))
        self.assertIn("questions", tabs)
        b.click(".tabs-all", what="Show all views")
        b.wait("document.querySelector('.tabs-all input').checked", "all views")
        tabs = b.eval("[...document.querySelectorAll('.tabs a')].map((a) => a.getAttribute('href').split('/').pop())")
        self.assertFalse({"tasks", "cell", "releases", "try", "changes", "evidence"} & set(tabs))
        self.step("the assistant")
        b.click('#sb-nav a[href="#/home"]', what="Home")
        b.click("#assistant-fab", what="Ask Rihma")
        suggested = b.wait("(document.querySelector('#as-suggest') || {}).textContent", "the suggestions")
        self.assertNotIn("log a signal", suggested)
        b.type("#as-q", "Where do I log a signal?")
        b.click("#as-send", what="Send")
        answer = b.wait("(() => { const m = [...document.querySelectorAll('#as-log .msg.bot')].pop();"
                        " return m && !!m.querySelector('button') && m.textContent; })()", "the answer")
        self.assertIn("is part of Delivery square and signals, which is not enabled here", answer)
        b.click("#as-log .msg.bot button", text="Take me there", what="Take me there")
        b.wait("location.hash === '#/settings' && !!document.querySelector('.mod-card')", "Settings, Modules")
        self.check()

    def test_FR_MOD5_AC_1_settings_lists_a_live_chat_while_integrations_is_off_and_revokes_it(self):
        b = self.browser
        e = kembeds.create(self.factory, kind="need", origins=["https://www.example.org"], person="Aino",
                           persona="business_owner", label="Website needs")
        self.spec_only_with_a_project()
        self.sign_in()
        for scheme, width in (("dark", 390), ("light", 1440), ("dark", 1440), ("light", 390)):
            self.step(f"embeds off {scheme} {width}")
            b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
            b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                         "mobile": width < 500})
            b.eval("location.hash = '#/settings'; true")
            note = b.wait(f"document.documentElement.dataset.theme === '{scheme}'"
                          " && (document.querySelector('[data-key=\"embeds-off\"]') || {}).textContent", "the embeds card")
            self.assertIn("Integrations is off. These chats take no messages", note)
            self.assertFalse(b.eval("!!document.querySelector('[data-control=\"create_embed\"]')"))   # no new chat
            self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0, (scheme, width))
        self.step("revoke")
        revoke = f'[data-key="revoke:{e["id"]}"]'
        self.assertEqual(b.eval(f"document.querySelector('{revoke}').getAttribute('aria-label')"), "Revoke Website needs")
        b.eval(f"document.querySelector('{revoke}').focus(); true")
        self.press("Enter", 13, "\r")
        row = b.wait(f"!document.querySelector('{revoke}') && document.activeElement.dataset.key === 'embed:{e['id']}'"
                     " && document.activeElement.textContent", "the chat revoked, its row in focus")
        self.assertIn("Revoked", row)
        self.assertEqual(kembeds.embeds(self.factory)[0]["state"], "revoked")
        rec = factory_project(self.factory).ledger().of_kind("embed_revoked")[-1]["event"]["payload"]
        self.assertEqual((rec["by"], rec["persona"]), (PERSON, "business_owner"))
        self.check()

    def test_FR_MOD4_AC_3_the_modules_pages_fit_dark_and_light_at_1440_and_390_pixels(self):
        b = self.browser
        self.spec_only_with_a_project()
        self.sign_in()
        for scheme in ("dark", "light"):
            for width in (1440, 390):
                self.step(f"{scheme} {width}")
                b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
                b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                             "mobile": width < 500})
                for route, ready in (("#/home", "#grid .widget"), ("#/square", ".mod-off"),
                                     ("#/projects", "#main .proj-card, #main .proj-grid"),
                                     ("#/settings", ".mod-card .mod-list")):
                    b.eval(f"location.hash = '{route}'; true")
                    b.wait(f"!!document.querySelector('{ready}') && document.documentElement.dataset.theme === '{scheme}'",
                           f"{route} in {scheme} at {width}")
                    b.eval("new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")
                    self.assertLessEqual(b.eval("document.documentElement.scrollWidth - innerWidth"), 0,
                                         (route, scheme, width))
                    spills = b.eval("(() => { const c = document.querySelector('.mod-card'); if (!c) return [];"
                                    " const r = c.getBoundingClientRect().right;"
                                    " return [...c.querySelectorAll('select, input, label, .mod-row')]"
                                    ".filter((e) => e.getBoundingClientRect().right > r + 1).map((e) => e.id || e.className); })()")
                    self.assertEqual(spills, [], (route, scheme, width))          # nothing leaves its card
                    if width < 500:
                        self.assertFalse(b.eval("!!document.querySelector('#bottombar a[href=\"#/square\"]')"))
                self.check()
        with contextlib.suppress(OSError):
            shutil.rmtree(self.tmp / "chrome", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
