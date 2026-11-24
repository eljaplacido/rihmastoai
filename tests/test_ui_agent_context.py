"""FR-AGC1-AC-7 and AC-3 in a real browser (headless Chrome over the DevTools protocol, tests/test_ui_drive.py).

An attached repository whose team works in Claude Code and Cursor (tests/agent_context_fixture.py). A developer
opens its overview: "AI tools in this project" lists the instructions, skills, subagents, commands, hooks and
MCP servers with where each is, and "Work on it from your IDE" gives the MCP configuration for Claude Code,
Cursor and Codex with the person's name, how a change comes back, and the section to paste into AGENTS.md. In
New project the same folder's scan shows "How AI tools here are set up" as a group of its own. Dark and light,
1440 and 390 px wide: nothing scrolls sideways, every control has a name, and there is no console error, failed
request or CSP violation. Skipped when Chrome is not installed (``RIHMA_CHROME`` names another browser binary).
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
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import agent_context_fixture as fx  # noqa: E402
from test_ui_drive import PERSON, Browser, QuietRunner, find_chrome  # noqa: E402

from cockpit.server import make_server  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402
from kernel.store import Factory  # noqa: E402

NAMELESS = ("[...document.querySelectorAll('#main button, #main input, #main select, #main a[href], #main summary,"
            " #main pre[tabindex]')].filter((el) => el.getClientRects().length && !((el.getAttribute('aria-label') ||"
            " '').trim() || (el.labels && [...el.labels].some((l) => l.textContent.trim())) || el.textContent.trim()"
            " || el.getAttribute('title'))).map((el) => el.outerHTML.slice(0, 120))")
SIDEWAYS = "document.documentElement.scrollWidth > window.innerWidth + 1"
CARDS = "document.querySelectorAll('.ait-card').length === 2"


class UiAgentContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for the attached repository")
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-ui-agc-")).resolve()
        cls.patch = mock.patch.dict(os.environ, {ROOTS_ENV: str(cls.tmp)})
        cls.patch.start()
        cls.repo = fx.build(cls.tmp / "desk")
        fx.commit(cls.repo)
        cls.factory = Factory(cls.tmp / "home")
        cls.project = attach(cls.factory, "Loan desk", repo=cls.repo, person=PERSON, persona="developer")
        cls.server, cls.bootstrap = make_server(cls.factory, 0, runner=QuietRunner())
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.shots = Path(os.environ["RIHMA_UI_SHOTS"]) if os.environ.get("RIHMA_UI_SHOTS") else None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.patch.stop()
        with contextlib.suppress(OSError):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.browser = Browser(self.chrome, self.tmp / f"chrome-{int(time.time() * 1000)}")
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
            b.screenshot(self.shots / f"agc-{b.step.replace(' ', '-')}.png")

    def width(self, px: int) -> None:
        self.browser.cmd("Emulation.setDeviceMetricsOverride", {"width": px, "height": 1000 if px > 500 else 900,
                                                                "deviceScaleFactor": 1, "mobile": px < 500})
        self.browser.wait(f"window.innerWidth === {px}", f"a {px} px wide page")

    def theme(self, word: str) -> None:
        b = self.browser
        b.click("#theme", what="Theme")
        b.click("#menu-pop .menu-item", text=word, what=f"{word} in the theme menu")
        b.wait(f"document.documentElement.dataset.theme === {json.dumps(word.lower())}", f"the {word} theme")

    def sign_in(self) -> None:
        b = self.browser
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#k={self.server.issue_link()}"})   # a link works once
        b.wait("!document.documentElement.classList.contains('signed-out') && !!document.querySelector('#person-chip')",
               "the signed-in page")
        b.click("#person-chip", what="the person chip")
        b.type("#person", PERSON)
        b.click('label[for="pp-developer"]', what="the developer persona")
        b.click("#pp-done", what="Done in the person menu")
        b.wait(f"document.querySelector('#pc-name').textContent === {json.dumps(PERSON)}", "the person chip")

    def test_FR_AGC1_AC_7_the_project_page_shows_its_ai_tools_and_how_to_work_on_it_from_an_ide(self):
        b = self.browser
        pid = self.project.pid
        self.step("sign in")
        self.sign_in()
        self.step("open the overview")
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/#/p/{pid}/overview"})
        b.wait(CARDS, "the two cards")
        tools = b.eval("document.querySelector('#ait-h').closest('.ait-card').innerText")
        for said in ("AI tools in this project", "Project instructions", "CLAUDE.md", "Claude Code",
                     "Applies to the whole project", ".cursor/rules/python.mdc", "app/**/*.py", "Skills", "loan-report",
                     "2 bundled files, listed, never run", "Subagents", "reviewer", "Slash commands", "/overdue",
                     "Hooks and permissions", "PreToolUse on Bash", "Bash(npm run test:*)", "MCP servers",
                     "loans-db (stdio, loans-mcp)", "docs (http, docs.example.com)",
                     "Applies when relevant: the agent decides by its description. Database migrations",
                     "Commands the instructions state", "ruff check .", "candidates for Rihmasto's own catalogue only",
                     "Read from the committed main of"):
            self.assertIn(said, tools)
        self.assertNotIn("Personal settings", tools)       # read from the commit: personal files are not committed
        page = b.eval("document.body.innerText")
        for never in ("personal-value", "postgres://desk@db/loans", "never_run.py", "LOANS_PASSWORD", "$DESK_TOKEN"):
            self.assertNotIn(never, page)
        ide = b.eval("document.querySelector('#ide-h').closest('.ait-card').innerText")
        for said in ("Work on it from your IDE", "Claude Code", ".mcp.json in your clone", "claude mcp add rihma",
                     '"Aino Virtanen"', "How your change comes back", f"rihmasto repo gate {pid} --head <revision>",
                     "Rihmasto's contract and open questions for your IDE agent", "Copy the section", "Download it",
                     "Rihmasto never writes into your folder or repository."):
            self.assertIn(said, ide)
        self.step("cursor and the section")
        b.click('[data-key="ide:cursor"] > summary', what="Cursor")
        b.wait("document.querySelector('[data-key=\"ide:cursor\"]').open", "the Cursor configuration")
        cursor = json.loads(b.eval("document.querySelector('[data-key=\"ide:cursor\"] pre').textContent"))
        self.assertEqual(cursor["mcpServers"]["rihma"]["args"][-4:], ["--person", PERSON, "--persona", "developer"])
        b.click(".ait-card details.ait-ide:last-of-type > summary", text="Show the section", what="Show the section")
        section = b.wait("(() => { const d = [...document.querySelectorAll('.ait-card details.ait-ide')]"
                         ".find((x) => x.open && x.textContent.includes('Show the section'));"
                         " return d && d.querySelector('pre').textContent; })()", "the section")
        self.assertTrue(section.startswith(f"<!-- rihmasto:begin {pid} -->"))
        b.click('[data-key="ide-section:copy"]', what="Copy the section")
        said = b.wait("(document.querySelector('#status .toast') || {}).textContent", "the copy said")
        self.assertTrue("The section copied." in said or "Copy it by hand" in said, said)
        for word in ("Light", "Dark"):
            for px in (1440, 390):
                self.step(f"{word.lower()} at {px} px")
                self.width(px)
                if b.eval("document.documentElement.dataset.theme") != word.lower():
                    self.theme(word)
                b.wait(CARDS, f"the cards in the {word} theme at {px} px")
                b.eval("document.querySelector('.ait').scrollIntoView(); true")
                if self.shots:
                    b.screenshot(self.shots / f"agc-cards-{word.lower()}-{px}.png")
        self.check()
        self.width(1440)

    def scan(self) -> None:
        b = self.browser
        b.eval("location.hash = '#/projects'; true")
        b.click('[data-control="new_project"]', text="New project", what="New project")
        b.wait("!!document.querySelector('form.np-form')", "the New project dialog")
        b.click('[data-key="np-start:existing"]', what="Start from: An existing project")
        b.type('form.np-form input[aria-label="Title"]', "Loan desk again")
        b.type('[data-control="adopt_project"]', str(self.repo))
        b.wait("document.querySelector('form.np-form button[type=submit]').textContent.trim() === 'Scan the folder'",
               "the submit button asking to scan first")
        b.click("form.np-form button[type=submit]", what="Scan the folder")
        b.wait("!!document.querySelector('.scan-step:not([hidden]) .scan-agent')", "the AI tools group")

    def test_FR_AGC1_AC_3_the_scan_step_groups_how_ai_tools_here_are_set_up(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()
        self.step("scan the folder")
        self.scan()
        groups = b.eval("[...document.querySelectorAll('.scan-group > summary')].map((s) => s.textContent)")
        self.assertEqual(groups[0].rstrip("0123456789"), "How AI tools here are set up")
        agent = b.eval("document.querySelector('.scan-agent').innerText")
        for said in ("CLAUDE.md", "project instructions, read in full", ".claude/skills/loan-report/SKILL.md",
                     "skill, read in full", ".mcp.json", "MCP servers, summarised",
                     ".claude/settings.local.json", "personal settings, skipped", "never read"):
            self.assertIn(said, agent)
        personal = ".scan-agent input[data-path=\\\".claude/settings.local.json\\\"]"
        self.assertFalse(b.eval(f"!!document.querySelector('{personal}')"))       # nothing to tick: never read
        self.assertTrue(b.eval("!!document.querySelector('.scan-agent input[data-path=\"CLAUDE.md\"]')"))
        for word in ("Dark", "Light"):
            self.step(f"scan {word.lower()}")
            b.key("Escape", 27)
            b.wait("!document.querySelector('form.np-form')", "the dialog closed")
            self.width(1440)
            if b.eval("document.documentElement.dataset.theme") != word.lower():
                self.theme(word)
            self.scan()
            for px in (1440, 390):
                self.width(px)
                sizes = b.eval("(() => { const s = document.querySelector('.scan-step');"
                               " return [document.documentElement.scrollWidth, s.scrollWidth, s.clientWidth]; })()")
                self.assertLessEqual(sizes[0], px, (word, px, sizes))
                self.assertLessEqual(sizes[1], sizes[2], (word, px, sizes))
                if self.shots:
                    b.screenshot(self.shots / f"agc-scan-{word.lower()}-{px}.png")
        self.width(1440)
        self.check()


if __name__ == "__main__":
    unittest.main()
