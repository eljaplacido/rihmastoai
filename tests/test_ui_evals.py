"""Audits & evals in a real browser (FR-EVL1-AC-10): headless Chrome over the DevTools protocol.

A person opens a project's Health tab and sees Audits & evals: each of Gnomon's audits with its last result and trend
(from runs of a fake Gnomon, tests/gnomon_fakes.py), the findings with Make it a change, and Run now, which starts a
job (the test's runner starts nothing); the Health page's list across projects; and Models setup's "On our evals"
with the comparison of two scripted endpoints. Dark and light, at 1440 and 390 pixels: nothing scrolls sideways,
every control has a name, and no console error, failed request or Content-Security-Policy violation happens.

It reuses the browser driver of tests/test_ui_drive.py, and is skipped when Chrome is not installed.
"""

import contextlib
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import gnomon_fakes as gf  # noqa: E402
from console_fakes import PERSON, attached, git_repo  # noqa: E402
from test_role_evals import bad, good  # noqa: E402
from test_ui_drive import Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel import gnomon_evals_run as gr  # noqa: E402
from kernel import role_evals as rv  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

FITS = "document.documentElement.scrollWidth <= window.innerWidth"
TOAST = "(() => { const t = document.querySelector('#status .toast'); return t && t.textContent.includes('%s'); })()"
NAMED = ("(() => { const bad = []; document.querySelectorAll(['#ev-box', '#ev-all', '#re-box'].map((s) =>"
         " ['button', 'select', 'input', 'a[href]'].map((t) => s + ' ' + t).join(', ')).join(', '))"
         ".forEach((el) => { if (!el.getClientRects().length) return;"
         " const label = el.id && document.querySelector('label[for=\"' + el.id + '\"]');"
         " const name = el.getAttribute('aria-label') || el.textContent.trim() || el.title"
         " || (label && label.textContent.trim());"
         " if (!name) bad.push(el.outerHTML.slice(0, 90)); }); return bad; })()")


class _Cleanups:
    def __init__(self) -> None:
        self.fns: list = []

    def addCleanup(self, fn, *args) -> None:  # noqa: N802 - unittest's name
        self.fns.append((fn, args))

    def run(self) -> None:
        for fn, args in reversed(self.fns):
            with contextlib.suppress(Exception):
                fn(*args)


class EvalsUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-evals-ui-")).resolve()
        cls.saved = {k: os.environ.get(k) for k in ("GF_LANES",)}
        os.environ["GF_LANES"] = str(cls.tmp / "lanes")
        cls.cleanups = _Cleanups()
        fake = gf.install(cls.cleanups, cls.tmp / "bin")
        cls.factory = Factory(cls.tmp / "home", clock=FixedClock())
        repo = git_repo(cls.tmp / "shop", {"README.md": "# Shop\n", ".gnomon/config.toml": "[routing]\n"})
        cls.p = attached(cls.factory, repo, "Shop")
        for eid in ("security", "compliance", "metrics"):
            gr.run(cls.p, eid, person=PERSON, persona="developer")
        gf.answer(fake, security=gf.risky_security())
        gr.run(cls.p, "security", person=PERSON, persona="developer")
        rv.run(cls.factory, person=PERSON, persona="it", role="assistant", models=["qwen3.6-35b@local", "glm-5.3@go"],
               model_for=lambda c: FakeModel(good if c["endpoint"] == "local" else bad))
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
        cls.cleanups.run()
        for k, v in cls.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / "chrome-evals")
        self.addCleanup(self.browser.close)

    def step(self, name: str) -> None:
        b = self.browser
        if b.step != "start":
            b.eval("1")
            time.sleep(0.3)
            b.eval("1")
            self.assertEqual(b.problems, [], f"console errors or failed requests during '{b.step}'")
            self.assertEqual(b.violations(), [], f"CSP violations during '{b.step}'")
            if self.shots:
                self.shots.mkdir(parents=True, exist_ok=True)
                b.screenshot(self.shots / f"evals-{b.step.replace(' ', '-')}.png")
        b.step = name

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 900 if px > 500 else 800,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})

    def theme(self, mode: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=mode.capitalize(), what=f"{mode} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === '{mode}'", f"the {mode} theme")

    def readable(self, where: str) -> None:
        self.assertTrue(self.browser.eval(FITS), f"{where} scrolls sideways")
        self.assertEqual(self.browser.eval(NAMED), [], f"{where}: a control without a name")

    def views(self, where: str) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.p.pid}/checks"})
        rows = b.wait("(() => { const l = document.querySelector('#ev-list');"
                      " return l && l.querySelectorAll('li.mdl-row').length; })()", "the audits")
        self.assertEqual(rows, 13)
        self.assertIn("Gnomon 0.6.5+fake", b.eval("document.querySelector('#ev-line').textContent"))
        self.assertTrue(b.eval("!!document.querySelector('[data-key=\"eval:security\"] [data-verdict=\"failed\"]')"))
        self.readable(f"Audits & evals ({where})")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/health"})
        b.wait("!!document.querySelector('#ev-all [data-key^=\"ev-p:\"]')", "the audits across projects")
        self.readable(f"the Health page ({where})")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/models"})
        line = b.wait("(() => { const l = document.querySelector('#re-lines'); return l && l.textContent; })()",
                      "On our evals")
        self.assertIn("100% vs", line)
        self.readable(f"Models setup ({where})")

    def test_FR_EVL1_AC_10_audits_and_evals_in_a_browser_dark_and_light_at_two_widths(self):
        b = self.browser
        self.step("sign in")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.bootstrap}"})
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in cockpit")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done")
        self.theme("dark")

        self.step("dark 1440")
        self.views("dark 1440")

        self.step("make a finding a change")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{self.p.pid}/checks"})
        b.wait("!!document.querySelector('#ev-findings [data-control=\"evals_make_change\"]')", "a finding")
        b.click('#ev-findings [data-control="evals_make_change"]', what="Make it a change")
        b.wait(TOAST % "filed", "the change toast")
        b.wait("!!document.querySelector('#ev-findings a[data-key^=\"ef-card:\"]')", "the finding's change")

        self.step("run an audit now")
        b.click('[data-key="eval:doctor"] [data-control="evals_run"]', what="Run now on the doctor")
        b.wait(TOAST % "job", "the job toast")
        self.assertEqual(self.runner.started[-1][-3:-1], ["carry", self.p.pid])

        self.step("dark 390")
        self.width(390)
        self.views("dark 390")

        self.step("light 1440")
        self.width(1440)
        self.theme("light")
        self.views("light 1440")

        self.step("light 390")
        self.width(390)
        self.views("light 390")
        self.step("end")


if __name__ == "__main__":
    unittest.main()
