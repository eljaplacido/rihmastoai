"""FR-SHP1-AC-10 and FR-MDL1-AC-8: Shape it in chat and Models setup in a real browser (headless Chrome over the
DevTools protocol, as tests/test_ui_drive.py).

Shape it in chat: from Home's header a person starts a conversation with a sentence and a file, answers Rihma
(a scripted model), edits the draft, attaches a folder, leaves and resumes from the list, and creates the
project with Rihma's suggestion. Models setup: from Home's "Set up a model" card a person sets the analyst
with a preset and a stored key against a stub endpoint on 127.0.0.1, tests it, sees the card go, and takes
the role back. Both run in the dark theme at 1440 px, then the light theme at 390 px. After every step there is
no console error, failed request or Content-Security-Policy violation, every control has a name, and nothing
is wider than the screen. Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser).
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import isolated_routing  # noqa: E402
from test_models_setup import stub_server  # noqa: E402
from test_shape import NOTES, rihma  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import lanes  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.store import Factory, write_json  # noqa: E402

PERSON = "Aino Virtanen"
KEY = "fake-ui-key-0123456789abcdef"
NAMELESS = """[...document.querySelectorAll('#main :is(button, a[href], input, textarea, select), #modal :is(button, input, textarea, select)')]
  .filter((el) => el.getClientRects().length)
  .filter((el) => !((el.getAttribute('aria-label') || '').trim() || (el.labels && [...el.labels].some((l) => l.textContent.trim()))
                    || (!/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) && el.textContent.trim())))
  .map((el) => el.outerHTML.slice(0, 120))"""
OVERFLOW = "document.documentElement.scrollWidth - window.innerWidth"


class ShapeModelsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-shape-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.routing = isolated_routing(self, self.tmp)
        self.factory = Factory(self.tmp / "home")
        self.factory.new_project("Old intranet", maturity="demo", mode="mixed")   # not a first run: no welcome dialog
        self.server, self.bootstrap = make_server(self.factory, 0, runner=QuietRunner())
        self.server.shape_model = FakeModel(rihma)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.addCleanup(self.browser.close)
        self.browser.shots = self.shots

    # -- helpers ---------------------------------------------------------------------------------------

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
        self.assertEqual(b.eval(NAMELESS), [], f"controls with no name during '{b.step}'")
        self.assertLessEqual(b.eval(OVERFLOW), 0, f"the page is wider than the screen during '{b.step}'")
        if self.shots:
            self.shots.mkdir(parents=True, exist_ok=True)
            b.screenshot(self.shots / f"shape-models-{b.step.replace(' ', '-')}.png")

    def sign_in(self, persona: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#grid')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click(f'label[for="pp-{persona}"]', what="the persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def theme(self, mode: str, label: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=label, what=f"{label} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(mode)}", f"the {mode} theme")

    def narrow(self) -> None:
        b = self.browser
        b.cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
        b.wait("window.innerWidth === 390", "the narrow screen")
        time.sleep(0.3)

    def choose_file(self, selector: str, path: Path) -> None:
        b = self.browser
        root = b.cmd("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
        node = b.cmd("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
        b.cmd("DOM.setFileInputFiles", {"files": [str(path)], "nodeId": node})

    def log_has(self, text: str, what: str) -> None:
        self.browser.wait(f"(document.querySelector('#shp-log') || {{}}).textContent.includes({json.dumps(text)})"
                          " && !document.querySelector('#shp-log .pending')", what)

    # -- Shape it in chat --------------------------------------------------------------------------------

    def test_FR_SHP1_AC_10_a_person_shapes_a_need_in_chat_and_creates_the_project_in_chrome_dark_and_light_wide_and_narrow(self):
        b = self.browser
        notes = self.tmp / "notes.md"
        notes.write_text(NOTES, encoding="utf-8")
        folder = self.tmp / "specs"
        folder.mkdir()
        (folder / "README.md").write_text("# Loans\n\nA loan has a due date.\n", encoding="utf-8")
        self.step("sign in")
        self.sign_in("business_owner")
        self.theme("dark", "Dark")
        self.step("start from home with a sentence and a file")
        b.click('[data-key="home:shape"]', what="Shape it in chat on Home")
        b.wait("location.hash === '#/shape' && !!document.querySelector('#shp-first')", "the chat's start")
        b.type("#shp-first", "Our team keeps losing track of who borrowed the drills and laptops.")
        self.choose_file("#shp-new-file", notes)
        b.key("Enter", 13)                                               # Enter starts the conversation
        b.wait("location.hash.startsWith('#/shape/SH-')", "the conversation")
        self.log_has("Who borrows the tools", "Rihma's question")
        self.assertIn("weekdays", b.eval("document.querySelector('#shp-f-constraints').value"))   # it read the file
        self.assertIn("Still needed", b.eval("document.querySelector('#shp-state').textContent"))
        sid = b.eval("location.hash.split('/')[2]")
        self.step("answer rihma")
        b.type("#shp-input", "The team members borrow them; ")
        before = b.eval("document.querySelectorAll('#shp-log .shp-msg').length")
        b.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter",
                                         "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                                         "modifiers": 8, "text": "\r"})       # Shift+Enter: a newline, not Send
        b.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter",
                                         "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13, "modifiers": 8})
        self.assertTrue(b.eval("document.querySelector('#shp-input').value.endsWith('\\n')"))
        self.assertEqual(b.eval("document.querySelectorAll('#shp-log .shp-msg').length"), before)
        b.cmd("Input.insertText", {"text": "Pekka keeps the store."})
        b.key("Enter", 13)                                               # Enter sends the reply
        self.log_has("create the project when you are ready", "Rihma's answer")
        b.wait("document.querySelector('#shp-state').textContent.includes('Good enough to create the project')",
               "good enough")
        self.step("edit the draft")
        b.type("#shp-f-problem", "Drills go missing every month.")
        b.click('[data-key="shape:draft"]', what="Save the draft")
        b.wait("!!document.querySelector('.shp-field.yours #shp-f-problem')", "the field marked as yours")
        self.step("attach a folder")
        b.click('[data-key="shape:attach-toggle"]', what="Attach a file or folder")
        b.type("#shp-att-path", str(folder))
        b.click('[data-key="shape:attach"]', what="Attach it")
        self.log_has("Attached specs (folder", "the folder in the conversation")
        self.assertEqual(b.eval("document.querySelector('#shp-f-problem').value"), "Drills go missing every month.")
        self.step("leave and resume")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/home"})
        b.wait("!!document.querySelector('#grid')", "Home")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/shape"})
        b.click(f'[data-key="shape:{sid}"] a', what="the conversation in the list")
        self.log_has("Attached specs", "the conversation again")
        self.assertEqual(b.eval("document.querySelectorAll('#shp-log .shp-msg').length"), 8)
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        self.assertEqual(b.eval("new Set([...document.querySelectorAll('.shp-cols > .card')].map((c) => c.getBoundingClientRect().left)).size"), 1)
        self.step("create the project")
        b.click('[data-key="shape:create"]', what="Create the project from this")
        b.wait("!!document.querySelector('#modal [data-key=\"shape:create-confirm\"]')", "the create dialog")
        self.assertIn("Rihma suggests", b.eval("document.querySelector('#modal').textContent"))
        self.assertEqual(b.eval("document.querySelector('[data-key=\"shp-maturity:explore\"]').getAttribute('aria-checked')"), "true")
        b.click('[data-key="shp-maturity:demo"]', what="the demo maturity")
        b.click('#modal [data-key="shape:create-confirm"]', what="Create and start the intake")
        b.wait("/^#\\/p\\/equipment-loans-[0-9a-f]+\\/overview$/.test(location.hash)", "the new project")
        pid = b.eval("location.hash.split('/')[2]")
        self.check()
        p = self.factory.project(pid)
        self.assertEqual((p.meta["maturity"], p.meta["mode"]), ("demo", "assume"))
        self.assertEqual(p.read("shape.json")["id"], sid)
        created = factory_project(self.factory).ledger().of_kind("shape_created")[-1]["event"]["payload"]
        self.assertEqual((created["person"], created["project"]), (PERSON, pid))

    # -- Models setup ------------------------------------------------------------------------------------

    def test_FR_MDL1_AC_8_a_person_sets_tests_and_takes_back_a_model_in_chrome_dark_and_light_wide_and_narrow(self):
        b = self.browser
        stub = stub_server(self)
        base = f"http://127.0.0.1:{stub.server_address[1]}/v1"
        # the assistant's local server is not running here, whatever runs on this machine's port 8080
        write_json(self.routing / "routing.local.json", {"roles": {"assistant": {"model": "qwen3.6-35b", "endpoint": "nothing"}},
                                                         "endpoints": {"nothing": {"kind": "openai", "url": "http://127.0.0.1:9/v1/chat/completions"}}})
        found = mock.patch("kernel.models_setup.gnomon_found", return_value=True)
        found.start()
        self.addCleanup(found.stop)
        self.step("sign in")
        self.sign_in("it")
        self.theme("dark", "Dark")
        self.step("home asks for a model")
        b.wait("!!document.querySelector('.setup-card')", "the Set up a model card")
        b.click('[data-key="home:models"]', what="Open Models setup")
        b.wait("location.hash === '#/models' && document.querySelectorAll('.mdl-row').length === 5", "the five roles")
        self.step("set the analyst")
        b.click('[data-key="mdl-set:analyst"]', what="Change on the analyst")
        b.wait("!!document.querySelector('#mdl-preset')", "the form")
        b.eval("(() => { const s = document.querySelector('#mdl-preset'); s.value = 'llama_cpp';"
               " s.dispatchEvent(new Event('change')); return true; })()")
        self.assertEqual(b.eval("document.querySelector('#mdl-base').value"), "http://127.0.0.1:8080/v1")
        b.type("#mdl-base", base)
        b.type("#mdl-model", "qwen3:32b")
        b.click('[data-key="mdl-key-how:store"]', what="Store a key")
        b.type("#mdl-key", KEY)
        b.click('[data-key="mdl-save"]', what="Save")
        b.wait("!document.querySelector('#modal').open && document.querySelector('[data-key=\"model:analyst\"]')"
               ".textContent.includes('Set on this machine')", "the analyst set")
        page = b.eval("document.documentElement.outerHTML + [...document.querySelectorAll('input')].map((i) => i.value).join()")
        self.assertNotIn(KEY, page)                                                     # never on the page again
        overlay = json.loads(lanes.ROUTING_LOCAL_FILE.read_text(encoding="utf-8"))
        self.assertEqual(overlay["roles"]["analyst"]["endpoint"], "analyst-custom")
        self.assertNotIn(KEY, json.dumps(overlay))
        self.step("test it")
        b.click('[data-key="mdl-test:analyst"]', what="Test on the analyst")
        b.wait("document.querySelector('#mdl-res-analyst').textContent.includes('Answered in')", "the answer")
        self.assertEqual(stub.seen[-1]["auth"], f"Bearer {KEY}")
        self.step("home has a model now")
        b.click('#sb-nav a[href="#/home"]', what="Home")
        b.wait("!!document.querySelector('#grid') && !document.querySelector('.setup-card')", "Home without the card")
        b.click('#sb-foot a[href="#/settings"]', what="Settings")
        b.click('[data-key="set:models"]', what="Open Models setup in Settings")
        b.wait("location.hash === '#/models' && document.querySelectorAll('.mdl-row').length === 5", "Models setup")
        self.step("light and narrow")
        self.theme("light", "Light")
        self.narrow()
        self.step("take it back")
        b.click('[data-key="mdl-remove:analyst"]', what="Back to shipped on the analyst")
        b.wait("!document.querySelector('[data-key=\"model:analyst\"]').textContent.includes('Set on this machine')",
               "the analyst back on the shipped routing")
        self.check()
        overlay = json.loads(lanes.ROUTING_LOCAL_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("analyst", overlay.get("roles", {}))
        kinds = [r["event"]["kind"] for r in factory_project(self.factory).ledger().records()]
        self.assertEqual([k for k in kinds if k.startswith("models_")], ["models_set", "models_removed"])


if __name__ == "__main__":
    unittest.main()
