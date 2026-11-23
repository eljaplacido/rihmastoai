"""Home's dashboard in a real browser (FR-T1-AC-17): Customize keeps the keyboard focus, keeps widget
bodies inert, and edits one lens's layout at a time; figures that were never measured say so. The
decisions count every open question; a lens is drawn at once from the last read while a fresh one comes;
an imported theme is a preview on Home only; ending a session says what changed; and a project whose
health cannot be read is shown alike in every view of the health widget.

It drives headless Chrome over the DevTools protocol on a demo home, with the driver, demo home and
server of ``test_ui_drive`` (skipped the same way when Chrome or git is missing). After every step there
is no console error, uncaught exception, failed request or CSP violation.
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import test_ui_drive as drive  # noqa: E402  (the module, so its TestCase is not collected here again)

from kernel.canon import Canon  # noqa: E402

ACTIVE_WIDGET = "(document.activeElement.closest('[data-wid]') || {dataset: {}}).dataset.wid"
TYPES = "Array.from(document.querySelectorAll('#grid .widget')).map((w) => w.dataset.type).join(',')"
THEME = "['accent', 'theme', 'density', 'radius'].map((k) => document.documentElement.dataset[k]).join('|')"
STATUS = "document.querySelector('#status').textContent"


def fetch(path: str, method: str = "GET", body: dict | None = None) -> str:
    """A page-side fetch with the tab's session token, answering {status, body}."""
    headers = "{Authorization: 'Bearer ' + sessionStorage.getItem('gf.token'), 'Content-Type': 'application/json'}"
    payload = f", body: {json.dumps(json.dumps(body))}" if body is not None else ""
    opts = f"{{method: {json.dumps(method)}, headers: {headers}{payload}}}"
    return f"fetch({json.dumps(path)}, {opts}).then(async (r) => ({{status: r.status, body: await r.json()}}))"


class UiHomeTest(unittest.TestCase):
    setUpClass = classmethod(drive.UiDriveTest.setUpClass.__func__)
    tearDownClass = classmethod(drive.UiDriveTest.tearDownClass.__func__)
    setUp = drive.UiDriveTest.setUp
    step = drive.UiDriveTest.step
    check = drive.UiDriveTest.check
    sign_in = drive.UiDriveTest.sign_in
    project = drive.UiDriveTest.project

    def test_FR_T1_AC_17_customize_keeps_the_focus_inert_bodies_and_one_lens_per_session(self):
        b = self.browser
        self.step("sign in")
        self.sign_in()

        self.step("figures")
        b.wait("!!document.querySelector('#grid [data-type=\"kpi_strip\"] .kpi-i')", "the key figures")
        basis = b.eval("Array.from(document.querySelectorAll('#grid .kpi-i')).map((e) => e.tagName + ':'"
                       " + (document.getElementById(e.getAttribute('aria-describedby')) || {}).textContent)")
        self.assertTrue(basis and all(x.startswith("BUTTON:Basis: ") for x in basis), basis)

        self.step("customize")
        b.click("#customize", what="Customize")
        b.wait("!document.querySelector('#cz-bar').hidden && !!document.querySelector('#grid .widget.cz')", "Customize")
        self.assertTrue(b.eval("Array.from(document.querySelectorAll('#grid .card-body')).every((x) => x.inert)"))
        took = b.eval("(() => { const x = document.querySelector('#grid .card-body [data-control=\"decide\"]');"
                      " if (!x) return 'none'; x.focus(); return document.activeElement === x; })()")
        self.assertIn(took, (False, "none"))                   # a verdict cannot be reached while customizing
        wids = b.eval("Array.from(document.querySelectorAll('#grid .widget')).map((w) => w.dataset.wid)")
        b.click(f'#grid [data-wid="{wids[0]}"] [data-fk="size"]', what="the size button")
        b.wait(f"document.activeElement.dataset.fk === 'size' && {ACTIVE_WIDGET} === {json.dumps(wids[0])}",
               "the focus kept on the size button")
        b.click(f'#grid [data-wid="{wids[1]}"] [data-fk="remove"]', what="Remove")
        b.wait(f"document.activeElement.tagName === 'SECTION' && {ACTIVE_WIDGET} === {json.dumps(wids[2])}",
               "the focus on the widget that took its place")
        self.assertEqual(b.eval("document.querySelector('.layout-kind').textContent"), "Unsaved changes")

        self.step("switch lens while customizing")
        b.click('#lens-switch [data-lens="insight"]', what="the Insight lens")
        b.wait("document.title.startsWith('Insight') && !!document.querySelector('#grid .widget.cz')", "the Insight layout")
        self.assertIn("not kept", b.eval("document.querySelector('#status').textContent"))
        self.assertIn("Insight", b.eval("document.querySelector('#cz-bar').textContent"))
        insight = b.eval(TYPES)
        b.click('#cz-bar [data-key="cz:cancel"]', what="Cancel")
        b.wait("!document.documentElement.classList.contains('customizing')", "Customize closed")
        self.assertEqual(b.eval(TYPES), insight)               # Insight's own layout, not Business's widgets

        self.step("save the insight layout")
        b.click("#customize", what="Customize")
        b.wait("!!document.querySelector('#grid .widget.cz')", "Customize")
        first = b.eval("document.querySelector('#grid .widget').dataset.wid")
        b.click(f'#grid [data-wid="{first}"] [data-fk="size"]', what="the size button")
        b.click('#cz-bar [data-key="cz:done"]', what="Done")
        b.wait("!document.documentElement.classList.contains('customizing') && document.activeElement.id === 'customize'",
               "Customize closed, the focus back on Customize")
        saved = [json.loads(p.read_text(encoding="utf-8"))
                 for p in (self.factory.home / "_cockpit" / "layouts").rglob("insight.json")]
        self.assertEqual([s["layout"]["lens"] for s in saved], ["insight"])
        self.assertEqual(b.eval("document.querySelector('.layout-kind').textContent"), "Your layout")

        self.step("spend over no run")
        spend = b.wait("(document.querySelector('#grid [data-type=\"spend\"] .card-body') || {}).innerText", "Spend")
        self.assertIn("Not measured", spend)                   # the demo ran no Gnomon run: nothing is priced
        self.assertNotIn("0.0000", spend)
        self.check()

    def test_FR_T1_AC_17_home_counts_open_questions_draws_a_lens_at_once_and_keeps_a_preview_on_home(self):
        b = self.browser
        loans = self.project("Equipment loans")
        canon = Canon(loans)
        canon.ask(canon.add_question("Should a loan show the borrower's team?", "business")["id"])   # not blocking

        self.step("sign in")
        self.bootstrap = self.server.issue_link(600)            # the class's link worked once, for the other test
        self.sign_in()

        self.step("an open question waits on a person")
        raw = b.eval(fetch("/api/dashboard"))["body"]["kpis"]["decisions"]["value"]   # blocking cards only
        figure = ("(Array.from(document.querySelectorAll('#grid .kpi')).find((k) => k.getAttribute('aria-label')"
                  " === 'Decisions waiting') || {}).querySelector('.kpi-v').textContent")
        self.assertEqual(b.wait(figure, "the decisions figure"), str(raw + 1))
        summary = b.eval("document.querySelector('#grid [data-type=\"decisions\"] .w-sum').textContent")
        self.assertIn(f"{raw + 1} waiting in all", summary)

        self.step("a lens is drawn before its fresh read")
        paused, note = [], b._note

        def keep(msg: dict) -> None:
            if msg.get("method") == "Fetch.requestPaused":
                paused.append(msg["params"]["requestId"])
            else:
                note(msg)

        b._note = keep
        b.cmd("Fetch.enable", {"patterns": [{"urlPattern": "*/api/dashboard*"}]})
        try:
            b.click('#lens-switch [data-lens="operations"]', what="the Operations lens")
            b.wait("document.title.startsWith('Operations') && !!document.querySelector('#grid .widget')"
                   " && !!document.querySelector('#fresh-note .dash-refreshing')",
                   "Operations drawn while its read waits")
            self.assertEqual(b.eval("document.querySelector('#grid').getAttribute('aria-busy')"), "true")
            for _ in range(100):
                if paused:
                    break
                b.eval("1")
                time.sleep(0.05)
            self.assertTrue(paused)                              # the fresh read went out after the draw
            for request in paused:
                b.cmd("Fetch.continueRequest", {"requestId": request})
        finally:
            b.cmd("Fetch.disable")
            b._note = note
        b.wait("!document.querySelector('.dash-refreshing')"
               " && document.querySelector('#grid').getAttribute('aria-busy') === 'false'", "the fresh read shown")

        self.step("an imported theme stays on Home")
        themed = self.tmp / "themed-layout.json"
        themed.write_text(json.dumps({"v": 1, "lens": "operations", "widgets": [{"id": "g1", "type": "gate_trend"}],
                                      "theme": {"accent": "rose", "mode": "dark", "density": "compact",
                                                "radius": "crisp"}}), encoding="utf-8")
        kept = b.eval(THEME)
        b.click("#customize", what="Customize")
        b.wait("!!document.querySelector('#grid .widget.cz')", "Customize")
        b.cmd("Page.setInterceptFileChooserDialog", {"enabled": True})
        b.click('#cz-bar [data-key="cz:import"]', what="Import")
        b.wait("!!document.querySelector('input[type=\"file\"]')", "the file input")
        root = b.cmd("DOM.getDocument")["root"]["nodeId"]
        node = b.cmd("DOM.querySelector", {"nodeId": root, "selector": "input[type=\"file\"]"})["nodeId"]
        b.cmd("DOM.setFileInputFiles", {"files": [str(themed)], "nodeId": node})
        b.wait(f"{THEME} === 'rose|dark|compact|crisp'", "the imported theme previewed on Home")
        b.cmd("Page.setInterceptFileChooserDialog", {"enabled": False})
        b.click('#sb-nav a[href="#/projects"]', what="Projects")
        b.wait(f"document.title.startsWith('Projects') && {THEME} === {json.dumps(kept)}", "the kept theme off Home")
        self.assertFalse(b.eval("document.documentElement.classList.contains('customizing')"))
        self.assertIn("wait on Home", b.wait(STATUS, "the note that the edits wait"))
        b.click('#sb-nav a[href="#/home"]', what="Home")
        b.wait(f"!!document.querySelector('#grid .widget.cz') && {THEME} === 'rose|dark|compact|crisp'",
               "the session resumed with its preview")
        b.click('#cz-bar [data-key="cz:cancel"]', what="Cancel")
        b.wait(f"!document.documentElement.classList.contains('customizing') && {THEME} === {json.dumps(kept)}",
               "the kept theme after Cancel")

        self.step("a persona switch says why the edits were not kept")
        b.click("#customize", what="Customize")
        first = b.wait("(document.querySelector('#grid .widget.cz') || {dataset: {}}).dataset.wid", "Customize")
        b.click(f'#grid [data-wid="{first}"] [data-fk="size"]', what="the size button")
        b.click("#person-chip", what="the person chip")
        b.click('label[for="pp-product_owner"]', what="the product owner persona")
        b.wait("document.title.startsWith('Concept') && !!document.querySelector('#grid .widget.cz')",
               "the product owner's Concept layout, still customizing")
        said = b.eval(STATUS)
        self.assertIn("not kept: you switched to the Product owner persona", said)
        self.assertIn("customizing the Product owner's Concept layout", said)
        b.click("#pp-done", what="Done in the person menu")
        b.click('#cz-bar [data-key="cz:cancel"]', what="Cancel")
        b.wait("!document.documentElement.classList.contains('customizing')", "Customize closed")

        self.step("health views agree when a project's records cannot be read")
        access = self.project("Access review check")
        contract = access.path("contract.json")
        original = contract.read_bytes()
        self.addCleanup(contract.write_bytes, original)
        contract.write_text('{"tasks": "oops", "requirements": 5}', encoding="utf-8")
        widgets = [{"id": f"health-{v}", "type": "health", "size": "M", "view": v, "filter": {}}
                   for v in ("chart", "list", "table")]
        put = b.eval(fetch("/api/layout?persona=product_owner&lens=compliance", "PUT",
                           {"person": drive.PERSON, "layout": {"v": 1, "lens": "compliance", "widgets": widgets}}))
        self.assertEqual(put["status"], 200)
        b.click('#lens-switch [data-lens="compliance"]', what="the Compliance lens")   # its fresh read follows
        bodies = b.wait("(() => { const t = (v) => (document.querySelector('#grid [data-wid=\"health-' + v + '\"]"
                        " .card-body') || {}).innerText || ''; const all = ['chart', 'list', 'table'].map(t);"
                        " return all.every((x) => x.includes('health: TypeError')) && all; })()",
                        "the health widgets with the unread project")
        for body in bodies:
            self.assertIn("may be incomplete", body)                 # each view shows what it can, and warns
            self.assertNotIn("Nothing here means zero", body)
        self.assertIn("Health not read", bodies[0])
        self.assertIn("could not be read", bodies[2])
        self.check()


if __name__ == "__main__":
    unittest.main()
