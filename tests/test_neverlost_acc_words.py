"""FR-NVL3: never lost when something breaks, the second half: Why? Ask Rihma on every empty or warning item with
the right subject, scope and reason, automations, team mode, a bad or slow model, a damaged record and a system
failure, each said plainly. Through the real cockpit server on a temp factory (tests/test_cockpit.py)."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402

DEV = {"person": "Ida Example", "persona": "developer"}


class NeverLostAccWordsTest(CockpitTestCase):
    def get(self, path):
        status, out, _ = self.call("GET", path)
        return status, out

    # -- AC-11: every empty, null or warning item offers Why ------------------------------------------------------

    def test_FR_NVL3_AC_11_empty_words_and_warning_notes_get_why_ask_rihma_too(self):
        js = self.page_js()
        self.assertIn('$$(".note.warning:not([data-unreadable]), .w-warn", root).forEach(onEmpty)', js)
        self.assertIn("onEmptyWords(root)", js)
        found = re.search(r"const EMPTY_WORDS = /(.+)/i;", js)
        self.assertIsNotNone(found)
        words = re.compile(found.group(1).replace("\\\\", "\\"), re.I)
        for said in ("No AI agent posted progress in this period", "No AI cost recorded in this period",
                     "No data integration declared", "No archived project yet", "Nothing is live yet",
                     "No priced AI work was recorded", "No health checks are on yet", "No check enabled.",
                     "No embed server address is set"):
            self.assertTrue(words.search(said), said)
        self.assertFalse(words.search("Nothing for you"))          # a plain status is not an empty state

    # -- AC-12, AC-13, AC-14: Why names the right thing, scope and reason ---------------------------------------------

    def test_FR_NVL3_AC_12_why_on_a_not_measured_zero_asks_about_the_checks_not_the_value(self):
        status, out = self.get("/api/why?view=health&kind=not_measured&field=0&basis=")
        self.assertEqual(status, 200, out)
        self.assertIn("no check is enabled yet", out["answer"])
        self.assertFalse(out["answer"].startswith("0"), out["answer"])
        self.assertEqual(out["fill"]["control"], "health_enable")
        self.assertIn("field = fieldOf(box) || \"this\"", self.page_js())

    def test_FR_NVL3_AC_13_why_on_the_all_projects_automations_names_the_platform_scope(self):
        status, out = self.get("/api/why?view=automations&kind=empty")
        self.assertEqual(status, 200, out)
        self.assertIn("for the platform or any project", out["answer"])
        self.assertNotIn("(project)", out["answer"])
        self.assertNotIn("for this project", out["answer"])
        p = self.new()
        out = self.get(f"/api/why?view=automations&kind=empty&project={p.pid}")[1]
        self.assertIn("for this project", out["answer"])

    def test_FR_NVL3_AC_14_why_on_a_page_whose_module_is_off_says_so_and_goes_to_modules(self):
        from kernel import modules

        modules.set_modules(self.factory, person="Ida Example", persona="it", preset="spec_only")
        status, out = self.get("/api/why?view=catalogue&kind=empty")
        self.assertEqual(status, 200, out)
        self.assertIn("its module is turned off in Settings, Modules", out["answer"])
        self.assertNotIn("nothing has been released", out["answer"])
        self.assertEqual((out["fill"]["route"], out["fill"]["control"]), ("#/settings", "modules"))

    # -- AC-15: templates that cannot work yet are marked; Run now and Remove say what happened ----------------------

    def test_FR_NVL3_AC_15_automations_say_what_waits_what_ran_and_who_removed_what(self):
        status, out = self.get("/api/automations")
        self.assertEqual(status, 200, out)
        tpl = {t["id"]: t for t in out["templates"]}
        self.assertEqual(tpl["notify_on_release"]["waits"], ["needs IT: a relay subscription"])
        self.assertIn("developer", tpl["nightly_regate"]["personas"])
        self.assertNotIn("business_owner", tpl["nightly_regate"]["personas"])
        # a draft that needs a relay says so in plain words, never an empty name or a CLI command
        status, out, _ = self.call("POST", "/api/automations", {"automation": dict(tpl["notify_on_release"]["draft"]),
                                                                **DEV})
        self.assertEqual(status, 400, out)
        self.assertIn("needs a relay subscription", out["error"])
        self.assertNotIn("rihmasto relay subscribe", out["error"])
        self.assertNotIn("''", out["error"])
        draft = {"name": "Nightly re-gate", "trigger": {"kind": "schedule", "daily": "02:00"},
                 "action": {"kind": "gate"}, "scope": {"kind": "source", "source": "attached"}}
        status, out, _ = self.call("POST", "/api/automations", {"automation": draft, **DEV})
        self.assertEqual(status, 201, out)
        aid = out["automation"]["id"]
        status, out, _ = self.call("POST", f"/api/automations/{aid}/run", DEV)
        self.assertEqual(status, 200, out)
        self.assertIs(out["ran"], False)
        self.assertIn("No project matches", out["why"])
        status, out, _ = self.call("POST", f"/api/automations/{aid}/remove", DEV)
        self.assertEqual(status, 200, out)
        listed = self.get("/api/automations")[1]
        self.assertEqual([(r["id"], r["by"]) for r in listed["removed"]], [(aid, "Ida Example")])
        js = self.page_js()
        self.assertIn("Press again to remove ", js)
        self.assertIn("if (out.ran === false)", js)
        self.assertIn('"Not set up: " + err.message', js)

    # -- AC-16: team mode's start line and header -----------------------------------------------------------------

    def test_FR_NVL3_AC_16_team_mode_says_how_to_sign_in_at_start_and_the_header_follows_the_mode(self):
        from cockpit.server import access_note

        status, out, _ = self.call("POST", "/api/people/mode", {"mode": "team", "reason": "test",
                                                               "person": "Ida Example", "persona": "it"})
        self.assertIn(status, (200, 201), out)
        said = access_note(self.factory)
        self.assertNotIn("None", said)
        self.assertIn("team mode", said)
        self.assertIn("first IT user", said)
        js = self.page_js()
        self.assertIn("if (nav.drawAccess) nav.drawAccess();", js)
        self.assertIn('api("GET", "/api/meta").then((meta) => { S.meta = meta; drawAccess(); })', js)

    # -- AC-17: Ask Rihma with a model that answers badly or hangs -------------------------------------------------

    def test_FR_NVL3_AC_17_a_bad_or_slow_model_never_leaves_ask_rihma_at_a_dead_end(self):
        import time

        from kernel import assistant
        from kernel.model import FakeModel

        nonsense = FakeModel(lambda prompt, role: '{"answer": "", "propose": []}')
        out = assistant.ask(self.factory, "Summarise my week", persona="developer", model=nonsense)
        self.assertTrue(out["answer"].strip())
        self.assertIsNotNone(out["navigate"])
        self.assertNotIn("Three ways in", out["answer"])

        from kernel.assistant_lane import AssistantModel
        from kernel.lanes import lane_lock

        lane = self.tmp / "lanes" / "assistant" / "analyst"       # another question holds the model's lane (hangs)
        lane.mkdir(parents=True)
        started = time.monotonic()
        with lane_lock(lane):
            out = assistant.ask(self.factory, "Where is the inbox?", persona="developer", model=AssistantModel(lane))
        self.assertLess(time.monotonic() - started, 2.0)          # never the lane's 10 s wait
        self.assertEqual(out["by"], "map")
        self.assertIsNotNone(out["navigate"])
        # who acted names the model that answered
        from kernel import who_acted

        class Answered:
            last_record = {"model": "qwen-small-local"}

        who = who_acted.for_answer(self.factory, None, {"by": "assistant", "answer": "x"}, Answered())
        self.assertEqual(who["model"], "qwen-small-local")
        self.assertIn('"data-control": "assistant_cancel"', self.page_js())

    # -- AC-18, AC-19: a damaged record and a system failure are said plainly, with Why --------------------------------

    def test_FR_NVL3_AC_18_a_damaged_automations_file_names_the_file_and_line_never_a_drawing_error(self):
        from kernel import immune

        path = self.factory.home / "automations" / "automations.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"automations": [\n', encoding="utf-8")
        status, out = self.get("/api/automations")
        self.assertEqual(status, 400, out)
        self.assertIn("automations.json cannot be read (line 2)", out["error"])
        self.assertIn("Restore it from a backup", out["error"])
        self.assertNotIn("Expecting value", out["error"])
        cls = immune.classify({"kind": "action_failed", "message": out["error"], "where": "automations_all"})
        self.assertEqual(cls["id"], "record_unreadable")
        self.assertIn('err.status ? "action_failed" : "view_broken"', self.page_js())
        why = self.get("/api/why?view=automations&kind=error&basis=" + out["error"].replace(" ", "%20"))[1]
        self.assertIn("a record file is damaged and cannot be read", why["answer"])

    def test_FR_NVL3_AC_19_system_failures_are_plain_words_and_report_waits_while_the_cockpit_is_down(self):
        import errno

        from kernel import recovery

        said = recovery.os_words(PermissionError(errno.EACCES, "Permission denied", r"C:\Users\x\home\ledger.jsonl"))
        self.assertEqual(said.split(" is read-only")[0], "ledger.jsonl")
        self.assertNotIn("Errno", said)
        self.assertNotIn("C:\\Users", said)
        self.assertIn("The disk is full", recovery.os_words(OSError(errno.ENOSPC, "No space left", "x.json")))
        js = self.page_js()
        self.assertIn("!inc && !(err && err.down) ? button(\"Report it\"", js)
        self.assertIn("personSet() ? \"Report it: Rihmasto keeps", js)
        self.assertIn("down.down = true", js)
