"""Automations (FR-AUT1): set and signed, each trigger kind on a fake clock, guards that cost nothing, scope
across projects, limits and the circuit breaker, never twice for one record, and never beyond the owner's
rights. The actions' own kernel paths are in tests/test_automations_actions.py."""

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import access as kaccess  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel import automations_run as run  # noqa: E402
from kernel import automations_text as words  # noqa: E402
from kernel import hooks  # noqa: E402
from kernel.accessfile import Access, Binding  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.next_step import next_step  # noqa: E402
from kernel.people import Identity  # noqa: E402

CHANGE = {"kind": "change", "text": "{project} saw {event}: look again"}


def tree(home: Path) -> dict:
    return {p.relative_to(home).as_posix(): p.read_bytes() for p in home.rglob("*")
            if p.is_file() and not p.name.endswith(".lock")}


class AutoCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.new(title="Loans")
        self.b = self.new(title="Bookings")

    def add(self, person="Aino", persona="product_owner", **spec):
        spec.setdefault("name", "test")
        spec.setdefault("scope", {"kind": "project", "projects": [self.a.pid]})
        spec.setdefault("action", dict(CHANGE))
        return au.add(self.factory, spec, person=person, persona=persona)

    def tick(self, **tools):
        return run.tick(self.factory, run.Tools(**tools))

    def ran(self, aid=None):
        rows = factory_project(self.factory).ledger().of_kind("automation_ran")
        return [r["event"]["payload"] for r in rows if aid is None or r["event"]["payload"]["id"] == aid]

    def changes(self, project):
        return Canon(project).cards(kind="change")


class SetTest(AutoCase):
    def test_FR_AUT1_AC_1_an_automation_is_signed_by_a_person_and_persona_and_every_change_is_recorded(self):
        a = self.add(trigger={"kind": "schedule", "daily": "02:00"}, guard={"kind": "open_cards", "at_least": 1},
                     limits={"quiet": "22:00-01:00", "max_per_hour": 4})
        self.assertEqual((a["id"], a["state"], a["owner"]["person"], a["owner"]["persona"], a["version"]),
                         ("AU-001", "active", "Aino", "product_owner", 1))
        self.assertEqual(a["limits"], {"max_per_hour": 4, "breaker": 3, "quiet": "22:00-01:00", "dry_run": False})
        summary = words.describe(a)
        self.assertTrue(summary.startswith(f"Every night at 02:00 UTC, only when 1 or more cards are open, for project "
                                           f"{self.a.pid}, open a change proposal"), summary)
        self.assertIn("At most 4 runs an hour; paused after 3 failed runs in a row; quiet 22:00-01:00 UTC.", summary)
        # refused: no person, a persona the action does not allow, a decision, an unknown event, a bad schedule
        before = tree(self.factory.home)
        for person, persona, spec in (
                ("model", "product_owner", {}), ("Aino", "end_user", {"action": {"kind": "gate"}}),
                ("Aino", "product_owner", {"action": {"kind": "decide"}}),
                ("Aino", "product_owner", {"action": {"kind": "approve_plan"}}),
                ("Aino", "product_owner", {"trigger": {"kind": "event", "types": ["automation_ran"]}}),
                ("Aino", "product_owner", {"trigger": {"kind": "schedule", "every": "1m"}}),
                ("Aino", "product_owner", {"trigger": {"kind": "hook", "source": "nobody"}})):
            with self.assertRaises((DecisionRefused, ValueError), msg=(person, persona, spec)):
                self.add(person=person, persona=persona, **({"trigger": {"kind": "schedule", "every": "1h"}} | spec))
        self.assertEqual(tree(self.factory.home), before)
        # pause by anyone; resume, edit and remove by the owner or IT; the editor owns it after
        with self.assertRaises(DecisionRefused):
            au.resume(self.factory, a["id"], person="Mallory", persona="developer")
        au.pause(self.factory, a["id"], person="Pekka", persona="operations", reason="audit week")
        au.resume(self.factory, a["id"], person="Ilkka", persona="it")
        edited = au.edit(self.factory, a["id"], {"trigger": {"kind": "schedule", "every": "2h"}}, person="Olli",
                         persona="it")
        self.assertEqual((edited["version"], edited["owner"]["person"], edited["trigger"]),
                         (2, "Olli", {"kind": "schedule", "every": "2h"}))
        au.remove(self.factory, a["id"], person="Olli", persona="it")
        self.assertEqual(au.automations(self.factory), [])
        records = factory_project(self.factory).ledger().records()
        kinds = [(r["event"]["kind"], r["event"]["payload"].get("person"))
                 for r in records if r["event"]["kind"].startswith("automation")]
        self.assertEqual(kinds, [("automation_set", "Aino"), ("automation_paused", "Pekka"),
                                 ("automation_resumed", "Ilkka"), ("automation_set", "Olli"),
                                 ("automation_removed", "Olli")])
        self.assertTrue(factory_project(self.factory).ledger().verify().intact)


class ScheduleTest(AutoCase):
    def test_FR_AUT1_AC_2_a_schedule_fires_on_its_slot_on_a_fake_clock_and_a_missed_slot_fires_once(self):
        t = dt.datetime(2026, 11, 22, 12, 0, tzinfo=dt.UTC)                     # a Sunday
        self.assertEqual(run.next_slot({"every": "15m"}, t), t + dt.timedelta(minutes=15))
        self.assertEqual(run.next_slot({"daily": "02:00"}, t), dt.datetime(2026, 11, 23, 2, 0, tzinfo=dt.UTC))
        self.assertEqual(run.next_slot({"daily": "13:30"}, t), dt.datetime(2026, 11, 22, 13, 30, tzinfo=dt.UTC))
        self.assertEqual(run.next_slot({"weekly": "mon 06:00"}, t), dt.datetime(2026, 11, 23, 6, 0, tzinfo=dt.UTC))
        self.assertEqual(run.next_slot({"weekly": "sun 06:00"}, t), dt.datetime(2026, 11, 29, 6, 0, tzinfo=dt.UTC))
        a = self.add(trigger={"kind": "schedule", "every": "1h"})
        self.tick()
        self.assertEqual(self.ran(), [])                                       # not yet
        self.clock.advance(minutes=61)
        self.tick()
        self.assertEqual([(r["trigger"], r["outcome"], r["project"]) for r in self.ran()],
                         [("schedule", "done", self.a.pid)])
        self.tick()
        self.assertEqual(len(self.ran()), 1)                                   # once per slot
        self.clock.advance(hours=5)                                            # five slots missed: one run
        self.tick()
        self.assertEqual(len(self.ran()), 2)
        self.assertEqual(run.state_of(self.factory, a["id"])["next_at"], "2026-11-22T19:01:00Z")


class EventTest(AutoCase):
    def test_FR_AUT1_AC_3_a_ledger_event_in_scope_fires_once_and_never_its_own_records(self):
        a = self.add(trigger={"kind": "event", "types": ["release_done", "gate_failed"]})
        self.b.log("release_done", {"revision": "r1"})                         # out of scope
        self.a.log("gate", {"task": "T-001", "verdict": "passed"})             # not a failed gate
        self.tick()
        self.assertEqual(self.ran(), [])
        self.a.log("release_done", {"revision": "r1", "environment": "preview"})
        self.a.log("gate", {"task": "T-001", "verdict": "failed"})
        self.tick()
        self.tick()
        rows = self.ran(a["id"])
        self.assertEqual([r["event"] for r in rows], ["release_done", "gate"])
        self.assertEqual(sorted(c["title"] for c in self.changes(self.a)),
                         [f"{self.a.pid} saw gate: look again", f"{self.a.pid} saw release_done: look again"])
        self.a.log("release_done", {"revision": "r2"})                         # the same words again: not twice
        self.tick()
        self.assertEqual((len(self.changes(self.a)), self.ran(a["id"])[-1]["outcome"]), (2, "nothing"))
        # its own change_submitted never fires it, even when it reacts to that kind
        b = self.add(trigger={"kind": "event", "types": ["change_submitted"]},
                     action={"kind": "signal", "text": "{project} had a change ({ref})"})
        self.a.log("change_submitted", {"card": "C-099", "persona": "end_user", "person": "Sanna"})
        self.tick()
        self.tick()
        self.assertEqual(len(self.ran(b["id"])), 1)
        self.assertEqual(self.ran(b["id"])[0]["refs"]["signal"], "S-001")
        # the project's ledger has the run too, signed with the owner's name
        mine = [r["event"]["payload"] for r in self.a.ledger().of_kind("automation_ran")]
        self.assertTrue(all(r["person"] == "Aino" for r in mine))


class HookTest(AutoCase):
    def test_FR_AUT1_AC_4_a_source_bound_to_a_project_rings_its_automation(self):
        import base64
        import json

        key = b"automation-hook-key-0123456789"
        env = {"HOOK_CI": "whsec_" + base64.b64encode(key).decode("ascii")}
        hooks.add_source(self.factory, "ci", scheme="standard", secret_env="HOOK_CI", bind=[self.a.pid],
                         person="Ilkka", persona="it")
        with self.assertRaises(DecisionRefused):
            hooks.bind_source(self.factory, "ci", [self.b.pid], person="Aino", persona="developer")
        a = self.add(trigger={"kind": "hook", "source": "ci"}, guard={"kind": "branch", "is": "main"})
        f = self.add(trigger={"kind": "hook", "source": "ci"}, scope={"kind": "factory"},
                     action={"kind": "signal", "text": "CI rang for {ref}"})

        def ring(n, branch):
            body = json.dumps({"type": "build.done", "ref": f"refs/heads/{branch}", "id": f"b{n}"}).encode()
            stamp = int(self.clock.now().timestamp())
            headers = {"webhook-id": f"m{n}", "webhook-timestamp": str(stamp),
                       "webhook-signature": hooks.sign_standard(key, f"m{n}", stamp, body)}
            return hooks.receive(self.factory, "ci", headers, body, environ=env)

        ring(1, "main")
        self.assertEqual(len(self.a.ledger().of_kind("hook_received")), 1)      # the bound project hears it
        self.assertEqual(self.b.ledger().of_kind("hook_received"), [])
        self.tick()
        self.assertEqual([(r["trigger"], r["outcome"]) for r in self.ran(a["id"])], [("hook", "done")])
        self.assertEqual([(r["trigger"], r["outcome"]) for r in self.ran(f["id"])], [("hook", "done")])
        hooks.bind_source(self.factory, "ci", [], person="Ilkka", persona="it")  # unbound: only the factory hears
        ring(2, "dev")
        self.assertEqual(len(self.a.ledger().of_kind("hook_received")), 1)
        self.tick()
        self.assertEqual((len(self.ran(a["id"])), len(self.ran(f["id"]))), (1, 2))


class GuardTest(AutoCase):
    def test_FR_AUT1_AC_6_a_guard_that_does_not_hold_drops_the_firing_and_records_nothing(self):
        a = self.add(trigger={"kind": "event", "types": ["gate_failed"]},
                     guard={"kind": "count", "event": "gate_failed", "at_least": 2, "within_hours": 24})
        self.a.log("gate", {"task": "T-001", "verdict": "failed"})
        before = len(factory_project(self.factory).ledger().records())
        out = self.tick()
        self.assertEqual(out["results"][0]["skipped"], 1)
        self.assertEqual(len(factory_project(self.factory).ledger().records()), before)   # cost nothing
        self.assertIn("fewer than 2", run.state_of(self.factory, a["id"])["last_skip"]["why"])
        self.clock.advance(hours=25)                                          # the first falls out of the window
        self.a.log("gate", {"task": "T-001", "verdict": "failed"})
        self.tick()
        self.assertEqual(self.ran(), [])
        self.a.log("gate", {"task": "T-001", "verdict": "failed"})
        self.tick()
        self.assertEqual(len(self.ran(a["id"])), 1)                            # twice within a day
        ok, why = run.guard_holds(self.factory, {"kind": "field", "key": "verdict", "equals": "failed"},
                                  {"event": {"verdict": "passed"}, "project": self.a.pid}, self.clock.now())
        self.assertEqual((ok, why), (False, "verdict is 'passed', not 'failed'"))


class ScopeTest(AutoCase):
    def test_FR_AUT1_AC_8_a_scope_reaches_projects_by_list_tag_source_or_the_whole_factory(self):
        c = self.new(title="Payroll")
        au.set_tags(self.a, ["ops", "nightly"], person="Aino", persona="product_owner")
        au.set_tags(c, ["ops"], person="Aino", persona="product_owner")
        c.update_meta(source_kind="attached")
        tagged = self.add(trigger={"kind": "schedule", "every": "1h"}, scope={"kind": "tag", "tag": "ops"})
        listed = self.add(trigger={"kind": "schedule", "every": "1h"},
                          scope={"kind": "projects", "projects": [self.b.pid, c.pid]})
        source = self.add(trigger={"kind": "schedule", "every": "1h"}, scope={"kind": "source", "source": "attached"})
        everyone = self.add(trigger={"kind": "schedule", "every": "1h"}, scope={"kind": "factory"},
                            action={"kind": "signal", "text": "hourly"})
        self.clock.advance(minutes=61)
        self.tick()
        got = {aid: sorted(r["project"] or "-" for r in self.ran(aid))
               for aid in (tagged["id"], listed["id"], source["id"], everyone["id"])}
        self.assertEqual(got, {tagged["id"]: sorted([self.a.pid, c.pid]), listed["id"]: sorted([self.b.pid, c.pid]),
                               source["id"]: [c.pid], everyone["id"]: ["-"]})
        self.assertEqual(self.a.ledger().of_kind("project_tagged")[0]["event"]["payload"]["tags"], ["nightly", "ops"])

    def test_FR_AUT1_AC_8_when_project_a_releases_a_change_proposal_opens_on_project_b(self):
        a = self.add(trigger={"kind": "event", "types": ["release_done"]},
                     action={"kind": "change", "project": self.b.pid, "text": "{project} released: check the link"})
        self.a.log("release_done", {"revision": "r2"})
        self.tick()
        cards = self.changes(self.b)
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0]["payload"]["text"].startswith(f"{self.a.pid} released: check the link"))
        self.assertEqual((cards[0]["payload"]["person"], cards[0]["state"]), ("Aino", "open"))  # a card for people
        self.assertEqual(self.changes(self.a), [])
        self.assertEqual(self.ran(a["id"])[0]["refs"], {"card": cards[0]["id"], "project": self.b.pid})


class LimitTest(AutoCase):
    def test_FR_AUT1_AC_9_runs_per_hour_wait_and_quiet_hours_hold_the_queue(self):
        a = self.add(trigger={"kind": "event", "types": ["release_done"]}, limits={"max_per_hour": 2},
                     action={"kind": "signal", "text": "{project} {ref}"})
        for n in range(3):
            self.a.log("release_done", {"release": n + 1})
        out = self.tick()["results"][0]
        self.assertEqual((len(out["ran"]), out["state"]), (2, "at its runs per hour"))
        self.clock.advance(minutes=61)
        self.tick()
        self.assertEqual(len(self.ran(a["id"])), 3)                             # the third waited, then ran
        quiet = self.add(trigger={"kind": "event", "types": ["release_done"]}, limits={"quiet": "11:00-14:00"},
                         action={"kind": "signal", "text": "quiet {project}"})
        self.clock.advance(minutes=-60)                                        # 12:01 on the clock again
        self.a.log("release_done", {"release": 4})
        held = [r for r in self.tick()["results"] if r["id"] == quiet["id"]][0]
        self.assertEqual(held["state"], "quiet hours")
        self.assertEqual(self.ran(quiet["id"]), [])
        self.clock.advance(hours=2)
        self.tick()
        self.assertEqual(len(self.ran(quiet["id"])), 1)                         # it ran once the quiet ended

    def test_FR_AUT1_AC_9_the_circuit_breaker_pauses_it_and_home_and_whats_next_say_why(self):
        a = self.add(trigger={"kind": "event", "types": ["release_done"]}, limits={"breaker": 2},
                     action={"kind": "ask", "text": "What changed?"})          # no model: every run fails
        for n in range(3):
            self.a.log("release_done", {"release": n + 1})
        out = self.tick()["results"][0]
        self.assertEqual(out["state"], "paused by the circuit breaker")
        self.assertEqual([r["outcome"] for r in self.ran(a["id"])], ["failed", "failed"])
        paused = au.get(self.factory, a["id"])
        self.assertEqual(paused["state"], "paused")
        self.assertIn("the circuit breaker: 2 failed runs in a row", paused["paused_why"])
        self.assertIn("no model is set up", paused["paused_why"])
        nx = next_step(self.a)
        act = next(x for x in nx["actions"] if x["id"] == "automation_paused")
        self.assertEqual((act["view"], act["control"]), ("automations", "automations_resume"))
        self.assertIn(a["id"], act["label"])
        self.tick()
        self.assertEqual(len(self.ran(a["id"])), 2)                            # paused: nothing runs
        au.resume(self.factory, a["id"], person="Aino", persona="product_owner")
        self.assertEqual(run.state_of(self.factory, a["id"])["failures"], 0)
        self.assertNotIn("automation_paused", [x["id"] for x in next_step(self.a)["actions"]])

    def test_FR_AUT1_AC_9_a_dry_run_records_what_it_would_do_and_does_nothing(self):
        a = self.add(trigger={"kind": "event", "types": ["release_done"]}, limits={"dry_run": True})
        self.a.log("release_done", {"release": 1})
        preview = run.dry_run(self.factory, a["id"])
        self.assertEqual([(f["project"], f["guard"]) for f in preview["firings"]], [(self.a.pid, "holds")])
        self.assertIn("would open a change proposal", preview["firings"][0]["would"])
        before = tree(self.factory.home)
        run.dry_run(self.factory, a["id"])
        self.assertEqual(tree(self.factory.home), before)                       # the preview changes nothing
        self.tick()
        self.assertEqual([r["outcome"] for r in self.ran(a["id"])], ["would"])
        self.assertTrue(self.ran(a["id"])[0]["dry_run"])
        self.assertEqual(self.changes(self.a), [])                               # nothing done


class OnceTest(AutoCase):
    def test_FR_AUT1_AC_10_no_record_fires_twice_not_even_when_a_run_dies_or_two_ticks_meet(self):
        a = self.add(trigger={"kind": "event", "types": ["release_done"]},
                     action={"kind": "signal", "text": "{project} {ref}"})
        self.a.log("release_done", {"release": 1})
        died = mock.patch("kernel.automations_actions.run", side_effect=SystemExit("the process died"))
        with died, self.assertRaises(SystemExit):
            self.tick()
        self.tick()
        self.tick()
        self.assertEqual(self.ran(a["id"]), [])                                # taken before it ran: never again
        self.a.log("release_done", {"release": 2})
        from kernel.filelock import locked

        with locked(self.factory.home / "automations" / "tick.lock", blocking=False):
            self.assertIn("busy", self.tick())                                 # another tick holds the lock
        self.tick()
        self.tick()
        self.assertEqual([r["outcome"] for r in self.ran(a["id"])], ["done"])
        # a project made after the automation was set: its records are new, and fire once
        c = self.new(title="Payroll")
        au.edit(self.factory, a["id"], {"scope": {"kind": "factory"}}, person="Aino", persona="product_owner")
        c.log("release_done", {"release": 1})
        self.tick()
        self.tick()
        self.assertEqual([r["project"] for r in self.ran(a["id"])], [self.a.pid, c.pid])

    def test_FR_AUT1_AC_10_with_no_automation_a_tick_writes_nothing(self):
        before = tree(self.factory.home)
        self.assertEqual(self.tick(), {"automations": 0, "results": []})
        self.assertEqual(tree(self.factory.home), before)


class RightsTest(AutoCase):
    def enforced(self, *bindings):
        people = {"local:aino": "Aino", "local:ilkka": "Ilkka"}
        return Access(kaccess.ENFORCED, people=people, bindings=tuple(bindings))

    def test_FR_AUT1_AC_11_it_runs_with_its_owners_rights_and_stops_when_a_grant_goes(self):
        aino = Identity("local:aino", "Aino")
        grant = Binding("product_owner", (self.a.pid,), subject="local:aino")
        with mock.patch("kernel.access.load", return_value=self.enforced(grant)):
            with self.assertRaises(kaccess.AccessRefused), kaccess.signing(aino):   # not granted on project B
                self.add(scope={"kind": "projects", "projects": [self.a.pid, self.b.pid]},
                         trigger={"kind": "event", "types": ["release_done"]})
            with kaccess.signing(aino):
                a = self.add(trigger={"kind": "event", "types": ["release_done"]})
            self.assertEqual(a["owner"]["identity"], "local:aino")
            self.a.log("release_done", {"release": 1})
            self.tick()
            card = self.changes(self.a)[0]
            self.assertEqual(self.a.ledger().of_kind("change_submitted")[-1]["event"]["payload"]["identity"],
                             "local:aino")                                     # signed as the owner's identity
            self.assertEqual(card["state"], "open")
        with mock.patch("kernel.access.load", return_value=self.enforced()):     # IT removed the grant
            self.a.log("release_done", {"release": 2})
            self.tick()
        last = self.ran(a["id"])[-1]
        self.assertEqual(last["outcome"], "refused")
        self.assertIn("is not granted the product_owner persona", last["detail"])
        self.assertEqual(len(self.changes(self.a)), 1)

    def test_FR_AUT1_AC_11_no_action_decides_a_card(self):
        self.assertFalse([k for k in au.ACTIONS if any(w in k for w in au.NEVER)])
        for kind in ("decide", "approve", "accept_as_is", "deploy", "merge", "delegate"):
            with self.assertRaises(DecisionRefused, msg=kind):
                self.add(trigger={"kind": "schedule", "every": "1h"}, action={"kind": kind})
        with self.assertRaises(DecisionRefused):
            au.edit(self.factory, self.add(trigger={"kind": "schedule", "every": "1h"})["id"],
                    {"action": {"kind": "decide"}}, person="Aino", persona="product_owner")


if __name__ == "__main__":
    unittest.main()
