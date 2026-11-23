"""`rihma demo`: a demo factory home, built with no model keys, no network and no Gnomon (FR-N4-AC-1).

A scripted model stands in for the analyst and the holdout author, and a scripted builder cell and
verifier stand in for Gnomon's cells. Everything else is the real kernel: the panel and the brief,
the spec and its provenance rules, the compiled contract, the holdout custody, git lanes, the gate
(the product's own tests, the criterion trace, fail-first, the verifier's findings), escalation, the
local-preview road, the capability pack, signals, concepts and the updates inbox.

What it builds, with neutral examples only:

- **Equipment loans** (web service, mixed mode, demo maturity): the panel's blocking questions wait
  for a person; a demo business owner has confirmed one assumption.
- **Shipment webhook to the stock system** (integration, assume mode, explore maturity): built
  through the gate. One task escalated after three rounds; a demo developer chose retry, and it
  passed. Release 1 ran on the local-preview road and has a capability pack. A chat signal became a
  change on it, and an observation (a new model) opened an update card.
- **Access review check** (ops agent, assume mode, demo maturity): built through the gate until a
  task escalated; the escalation waits for a person, with the gate's objections. Its holdout
  scenario sits in the holdout custody.
- **Rihma itself**: a need raised in a meeting became a concept that waits for a business owner.

Every decision is made by a fake person named `demo-*`. The scripted model and cell are named
`demo-model` and `demo-builder`; nothing they produce measures a real model. Timestamps are spread
over the last two days so the dashboard has ages and a trend to show. The local preview is started,
checked over loopback and stopped again before the command returns.

The kernel never imports the tests; this module re-implements the scripted model and cell natively.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from kernel.model import Model, ModelError
from kernel.store import REPO_ROOT, Clock, Factory, write_json, write_text

DEMO_MARKER = "demo.json"
DEMO_SCHEMA = "rihma.demo/1"
MODEL_NAME = "demo-model"
BUILDER_NAME = "demo-builder"

# The fake people who make every decision in the demo: (name, persona).
OWNER = ("demo-owner", "business_owner")
PRODUCT = ("demo-product", "product_owner")
DEVELOPER = ("demo-dev", "developer")
OPERATIONS = ("demo-ops", "operations")
COMPLIANCE = ("demo-compliance", "compliance")


class DemoError(RuntimeError):
    """The demo cannot be built here (a folder that is not a demo home, or no git)."""


def default_home() -> Path:
    return REPO_ROOT / "var" / "demo"


# -- time --------------------------------------------------------------------------------------

class DemoClock(Clock):
    """A clock that starts in the past and only moves forward, never beyond the real now."""

    def __init__(self, start: dt.datetime):
        self.start = start
        self._at = start

    def now(self) -> dt.datetime:
        return self._at

    def advance(self, **delta) -> None:
        self._at = min(self._at + dt.timedelta(**delta), _real_now())

    def at(self, hours: float) -> None:
        """Move to ``hours`` after the start (never backwards)."""
        target = self.start + dt.timedelta(hours=hours)
        if target > self._at:
            self._at = min(target, _real_now())


def _real_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


# -- the three requests --------------------------------------------------------------------------

LOANS = "loans"
WEBHOOK = "webhook"
ACCESS = "access"

TITLES = {
    LOANS: "Equipment loans",
    WEBHOOK: "Shipment webhook to the stock system",
    ACCESS: "Access review check",
}

REQUESTS = {
    LOANS: "Our team keeps losing track of who borrowed the drills, ladders and laptops. We want a simple "
           "page where people lend and return equipment, so nothing goes missing.",
    WEBHOOK: "When the carrier posts a shipment event to our webhook, update the stock system so the "
             "warehouse sees what is on its way. The same event sent twice must count once.",
    ACCESS: "Each quarter, check the exported access list of our ticketing system for compliance: flag "
            "accounts without an owner and accounts unused for 90 days, and give the compliance owner a "
            "report with evidence for each finding.",
}


def _q(text, why, proposed, *, blocking=False, options=()):
    return {"text": text, "why": why, "blocking": blocking, "proposed_answer": proposed,
            "options": [proposed, *options]}


PANELS = {
    LOANS: {
        "business": [
            _q("Who approves a loan?", "It decides the workflow and who is told.", "the team lead approves",
               blocking=True, options=("any team member", "the IT desk")),
            _q("How will we know it helps?", "The benefit needs a baseline.",
               "fewer lost items per month, against last quarter's count"),
        ],
        "end_user": [
            _q("Must every loan have a return date?", "It decides whether reminders are possible.",
               "yes, two weeks by default", blocking=True, options=("only for expensive items", "no return dates")),
            _q("Do people lend things from a phone?", "Loans happen in the storeroom.",
               "yes: the page must work on a phone"),
        ],
        "it_security": [_q("Is single sign-on required?", "Identity decides the build.",
                           "not for the demo: a shared team page is enough")],
        "operations": [_q("What availability is needed?", "Support hours.", "office hours")],
        "delivery": [_q("What is the smallest first version?", "Scope.", "add an item, lend it, return it")],
    },
    WEBHOOK: {
        "business": [_q("What should the warehouse see first?", "It sets the first screen of the stock system.",
                        "what is on its way, by item")],
        "end_user": [_q("Who reads the incoming stock?", "It decides where the data must appear.",
                        "warehouse staff, in the stock system they already use")],
        "it_security": [_q("How does the carrier authenticate to the webhook?", "An open webhook accepts anyone.",
                           "a shared secret in a header, kept by IT")],
        "operations": [_q("Who is told when events stop arriving?", "A silent feed looks like a quiet day.",
                          "the warehouse team lead, after one hour of silence")],
        "delivery": [_q("Can the carrier be simulated in tests?", "Tests must not call the carrier.",
                        "yes: recorded sample events")],
    },
    ACCESS: {
        "business": [_q("Who signs off the quarterly report?", "A report nobody signs decides nothing.",
                        "the compliance owner")],
        "end_user": [_q("What does the compliance owner need beside each finding?", "Evidence makes a finding usable.",
                        "the line of the export it rests on")],
        "it_security": [_q("May the check read the ticketing system directly?", "Least access.",
                           "no: only the exported access list a person provides")],
        "operations": [_q("How often does it run?", "It sets the schedule.", "once a quarter, and on request")],
        "delivery": [_q("Which known findings can seed the tests?", "Seeded findings prove the check works.",
                        "a sample export with one unowned and one stale account")],
    },
}

OPINIONS = {
    LOANS: [{"question": "Q-001", "perspective": "it_security", "opinion": "approval must be logged for audit"},
            {"question": "Q-001", "perspective": "end_user", "opinion": "any team member should be able to approve"},
            {"question": "Q-003", "perspective": "operations",
             "opinion": "a return date is what makes overdue reminders possible"}],
    WEBHOOK: [{"question": "Q-003", "perspective": "operations",
               "opinion": "rotate the shared secret every quarter, and alert when an event fails to authenticate"}],
    ACCESS: [],
}

SPECS = {
    # Panel questions are Q-001 to Q-005; the integration profile then asks Q-006 (systems) and
    # Q-007 (undeliverable messages), which the assume mode assumed.
    WEBHOOK: {
        "title": TITLES[WEBHOOK],
        "summary": "Receives the carrier's shipment events and keeps the incoming stock per item. Duplicates "
                   "count once, and an event that cannot be applied waits for a person.",
        "users": ["warehouse staff", "the carrier's system"],
        "interface": [
            {"method": "POST", "path": "/webhooks/shipments", "purpose": "receive one shipment event"},
            {"method": "GET", "path": "/shipments/{id}", "purpose": "one shipment and its status"},
            {"method": "GET", "path": "/incoming", "purpose": "incoming stock per item"},
            {"method": "GET", "path": "/dead-letters", "purpose": "events parked for a person"},
        ],
        "requirements": [
            {"statement": "A shipment event from the carrier is recorded and its items count as incoming stock.",
             "sources": ["request"], "priority": "must",
             "acceptance": [{"given": "no events", "when": "POST /webhooks/shipments with an event_id and items",
                             "then": "202, and GET /shipments/{id} shows the shipment as on its way",
                             "kind": "test"}]},
            {"statement": "The same event sent twice counts once.", "sources": ["request"], "priority": "must",
             "acceptance": [{"given": "an event already received",
                             "when": "the same event_id is posted again",
                             "then": "200 marked duplicate, and GET /incoming counts its items once",
                             "kind": "test"}]},
            {"statement": "An event that cannot be applied is parked in a dead-letter list a person can replay.",
             "sources": ["Q-007"], "priority": "should",
             "acceptance": [{"given": "-", "when": "POST /webhooks/shipments without items",
                             "then": "422, and GET /dead-letters lists the event", "kind": "test"}]},
        ],
        "out_of_scope": ["authenticating the carrier (an IT rule for a later maturity)", "a screen"],
    },
    # Panel questions Q-001 to Q-005; the ops-agent profile adds Q-006 (framework) and Q-007 (reads).
    ACCESS: {
        "title": TITLES[ACCESS],
        "summary": "Reads an exported access list and reports accounts without an owner and accounts unused "
                   "for 90 days, each finding citing the export line it rests on.",
        "users": ["the compliance owner"],
        "interface": [
            {"method": "POST", "path": "/checks", "purpose": "run a check over the rows of an export"},
            {"method": "GET", "path": "/checks/{id}", "purpose": "one report with its findings"},
        ],
        "requirements": [
            {"statement": "The check flags every account without an owner, citing the export line it rests on.",
             "sources": ["request", "Q-002"], "priority": "must",
             "acceptance": [
                 {"given": "an export where one account has no owner", "when": "POST /checks with the rows",
                  "then": "200 and a finding for that account with its line number", "kind": "test"},
                 {"given": "a fresh export", "when": "the compliance owner runs a check",
                  "then": "every unowned account is listed with its line", "kind": "holdout"}]},
            {"statement": "The check flags accounts unused for 90 days or more.", "sources": ["request"],
             "priority": "must",
             "acceptance": [{"given": "an account last used 120 days ago", "when": "POST /checks with the rows",
                             "then": "200 and a finding for that account", "kind": "test"}]},
            {"statement": "What the check could not read is reported as not measured, never as passed.",
             "sources": ["proposed"], "priority": "must",
             "acceptance": [{"given": "a row without a last-used date", "when": "POST /checks with the rows",
                             "then": "the report lists that account under not_measured", "kind": "test"}]},
        ],
        "out_of_scope": ["reading the ticketing system directly"],
    },
}

HOLDOUTS = {
    ACCESS: {"scenarios": [{"criterion": "R-1-AC-2", "steps": [
        {"method": "POST", "path": "/checks", "expect_status": 200, "expect_contains": "holdout-r1ac2-svc",
         "body": {"rows": [{"line": 1, "account": "holdout-r1ac2-user", "owner": "team-a", "last_used_days": 3},
                           {"line": 2, "account": "holdout-r1ac2-svc", "owner": "", "last_used_days": 5}]}}]}]},
}

TRIAGE = {
    WEBHOOK: {"parts": [{"class": "change_request", "requirements": ["R-1"],
                         "text": "tell the stock system when a delivery is split into two parcels",
                         "summary": "A shipment event may arrive as parcels; the stock system should see each one."}]},
}

SIGNAL_CHANGE = "The shipment webhook should tell the stock system when a delivery is split into two parcels."
SIGNAL_NEED = "Field technicians need to record maintenance visits offline on a phone and sync them later."
CONCEPT = {"title": "Offline maintenance visits", "problem": "Technicians lose visit notes where there is no network.",
           "who": "field technicians and their team lead",
           "value": "complete visit records without typing them up again at the office", "existing_project": None}


def _fence(obj) -> str:
    return "```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```"


def _which(prompt: str) -> str | None:
    low = prompt.lower()
    if "access review" in low or "access list" in low:
        return ACCESS
    if "webhook" in low or "shipment" in low:
        return WEBHOOK
    if "loan" in low or "drills" in low:
        return LOANS
    return None


class ScriptedModel(Model):
    """Answers the kernel's prompts from the scripts above. It is not a model: it never reads the
    prompt beyond telling which request and which kind of question it is."""

    name = MODEL_NAME

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def ask(self, prompt: str, *, role: str) -> str:
        self.calls.append((role, prompt[:80]))
        if prompt.startswith("A business need arrived") and SIGNAL_NEED in prompt:
            return _fence(CONCEPT)
        which = _which(prompt)
        if "perspective on a panel" in prompt and which:
            for perspective, questions in PANELS[which].items():
                if f"You are the **{perspective}** perspective" in prompt:
                    return _fence({"reading": f"The {perspective.replace('_', ' ')} reading of the request "
                                              f"(scripted for the demo).", "questions": questions})
        if prompt.startswith("A panel of perspectives"):
            return _fence({"opinions": OPINIONS.get(which, []) if which else []})
        if prompt.startswith("You turn a brief into a software specification") and which in SPECS:
            return _fence(SPECS[which])
        if prompt.startswith("You write acceptance scenarios") and which in HOLDOUTS:
            return _fence(HOLDOUTS[which])
        if prompt.startswith("Classify a piece of feedback") and which in TRIAGE:
            return _fence(TRIAGE[which])
        raise ModelError(f"the demo's scripted model has no answer for this {role} prompt")


# -- the scripted builder cell --------------------------------------------------------------------

WEBHOOK_HEAD = '''"""Shipment events from the carrier, kept as incoming stock (written by the demo's scripted cell)."""

from app.server import load_data, route, save_data


def _add_incoming(items):
    incoming = load_data("incoming", {})
    for item in items:
        if isinstance(item, dict) and str(item.get("sku", "")).strip():
            sku = str(item["sku"]).strip()
            incoming[sku] = incoming.get(sku, 0) + int(item.get("qty", 1))
    save_data("incoming", incoming)


@route("POST", "/webhooks/shipments")
def receive_shipment(req):
    body = req.body if isinstance(req.body, dict) else {}
    event_id = str(body.get("event_id", "")).strip()
    items = body.get("items") if isinstance(body.get("items"), list) else []
'''

WEBHOOK_PARK = '''    if not event_id or not items:
        parked = load_data("dead_letters", [])
        parked.append({"event": body, "reason": "an event needs an event_id and at least one item"})
        save_data("dead_letters", parked)
        return 422, {"error": "parked in the dead-letter list for a person to replay"}
'''

WEBHOOK_LOAD = '''    events = load_data("events", {})
'''

WEBHOOK_DUPLICATE = '''    if event_id in events:
        return 200, {"event_id": event_id, "duplicate": True}
'''

WEBHOOK_TAIL = '''    events[event_id] = {"event_id": event_id, "items": items, "status": "on its way"}
    save_data("events", events)
    _add_incoming(items)
    return 202, events[event_id]


@route("GET", "/shipments/{id}")
def get_shipment(req):
    event = load_data("events", {}).get(req.params["id"])
    return (200, event) if event else (404, {"error": "no such shipment"})


@route("GET", "/incoming")
def incoming(req):
    return 200, load_data("incoming", {})
'''

WEBHOOK_DEAD_LETTERS = '''

@route("GET", "/dead-letters")
def dead_letters(req):
    return 200, load_data("dead_letters", [])
'''


def _webhook_routes(task: str) -> str:
    level = int(task.split("-")[1])
    return (WEBHOOK_HEAD + (WEBHOOK_PARK if level >= 3 else "") + WEBHOOK_LOAD
            + (WEBHOOK_DUPLICATE if level >= 2 else "") + WEBHOOK_TAIL + (WEBHOOK_DEAD_LETTERS if level >= 3 else ""))


TEST_HEAD = '''import unittest

import app.routes  # noqa: F401
from app.server import handle


class {cls}(unittest.TestCase):
'''

WEBHOOK_TESTS = {
    "T-001": ("tests/test_shipments.py", "ShipmentTest", '''    def test_R_1_AC_1_an_event_is_recorded_as_a_shipment_on_its_way(self):
        status, _, _ = handle("POST", "/webhooks/shipments", {"event_id": "ev-r1", "items": [{"sku": "drill", "qty": 2}]})
        self.assertEqual(status, 202)
        status, body, _ = handle("GET", "/shipments/ev-r1")
        self.assertEqual((status, body["status"]), (200, "on its way"))
'''),
    "T-002": ("tests/test_duplicates.py", "DuplicateTest", '''    def test_R_2_AC_1_the_same_event_twice_counts_once(self):
        event = {"event_id": "ev-r2", "items": [{"sku": "ladder", "qty": 3}]}
        handle("POST", "/webhooks/shipments", event)
        status, body, _ = handle("POST", "/webhooks/shipments", event)
        self.assertEqual((status, body.get("duplicate")), (200, True))
        _, incoming, _ = handle("GET", "/incoming")
        self.assertEqual(incoming["ladder"], 3)
'''),
    "T-003": ("tests/test_dead_letters.py", "DeadLetterTest", '''    def test_R_3_AC_1_an_event_without_items_is_parked_for_a_person(self):
        status, _, _ = handle("POST", "/webhooks/shipments", {"event_id": "ev-r3"})
        self.assertEqual(status, 422)
        status, parked, _ = handle("GET", "/dead-letters")
        self.assertEqual(status, 200)
        self.assertIn("ev-r3", [p["event"].get("event_id") for p in parked])
'''),
}

ACCESS_ROUTES = '''"""A quarterly access review over an exported access list (written by the demo's scripted cell)."""

from app.server import load_data, route, save_data


def _rows(body):
    rows = body.get("rows") if isinstance(body, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


@route("POST", "/checks")
def run_check(req):
    rows = _rows(req.body)
    findings = []
    for n, row in enumerate(rows, 1):
        if not str(row.get("owner") or "").strip():
            findings.append({"check": "owner", "account": row.get("account"), "line": row.get("line", n),
                             "finding": "the account has no owner"})
    checks = load_data("checks", [])
    report = {"id": str(len(checks) + 1), "rows": len(rows), "findings": findings}
    checks.append(report)
    save_data("checks", checks)
    return 200, report


@route("GET", "/checks/{id}")
def get_check(req):
    for report in load_data("checks", []):
        if report["id"] == req.params["id"]:
            return 200, report
    return 404, {"error": "no such check"}
'''

ACCESS_TESTS = {
    "T-001": ("tests/test_owners.py", "OwnerTest", '''    def test_R_1_AC_1_an_account_without_an_owner_is_a_finding_with_its_line(self):
        rows = [{"line": 1, "account": "acct-1", "owner": "team-a", "last_used_days": 4},
                {"line": 2, "account": "svc-old", "owner": "", "last_used_days": 30}]
        status, report, _ = handle("POST", "/checks", {"rows": rows})
        self.assertEqual(status, 200)
        self.assertIn(("svc-old", 2), [(f["account"], f["line"]) for f in report["findings"]])
'''),
}

ENVELOPE = re.compile(r"^# Envelope (T-\d+)", re.MULTILINE)
VISIBLE = re.compile(r"^- \*\*(R-\d+-AC-\d+)\*\*", re.MULTILINE)


class ScriptedCell:
    """Stands in for a Gnomon builder cell and the verifier, for one project.

    ``lazy`` maps a task to how many rounds the cell does it badly: it writes a test that asserts
    True and nothing else. The gate's fail-first signal and the scripted verifier both catch that,
    which is how the demo shows an escalation. Each run moves the demo clock on a few minutes."""

    def __init__(self, project_key: str, clock: DemoClock, *, lazy: dict | None = None):
        self.key = project_key
        self.clock = clock
        self.lazy = dict(lazy or {})
        self.last_lazy: tuple[str, list[str]] | None = None

    def __call__(self, lane_path, prompt: str) -> dict:
        envelope = ENVELOPE.search(prompt)
        if envelope is None:
            raise DemoError("the scripted builder was given a prompt without a task envelope")
        task = envelope.group(1)
        criteria = sorted(set(VISIBLE.findall(prompt)))
        self.clock.advance(minutes=7)
        lane = Path(lane_path)
        if self.lazy.get(task, 0) > 0:
            self.lazy[task] -= 1
            self.last_lazy = (task, criteria)
            body = "".join(f"    def test_{c.replace('-', '_')}_is_handled(self):\n        self.assertTrue(True)\n\n"
                           for c in criteria)
            _write(lane / "tests" / f"test_{task.lower().replace('-', '_')}.py",
                   TEST_HEAD.format(cls="PlaceholderTest") + body.rstrip() + "\n")
            return self._record(task, steps=3, output="Added a test for the criteria.")
        self.last_lazy = None
        routes, tests = (_webhook_routes(task), WEBHOOK_TESTS) if self.key == WEBHOOK else (ACCESS_ROUTES, ACCESS_TESTS)
        _write(lane / "app" / "routes.py", routes)
        if task in tests:
            path, cls, body = tests[task]
            _write(lane / path, TEST_HEAD.format(cls=cls) + body)
        return self._record(task, steps=9, output="Wrote each criterion's test first, saw it fail, then the code.")

    def _record(self, task: str, *, steps: int, output: str) -> dict:
        return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": steps,
                "model": BUILDER_NAME, "output": f"{task}: {output} (scripted for the demo)"}

    def verify(self, prompt: str) -> str:
        """The verifier's review. It is read-only and, in the demo, scripted."""
        self.clock.advance(minutes=2)
        if self.last_lazy:
            task, criteria = self.last_lazy
            return _fence({"findings": [{"criterion": c, "in_scope": True, "severity": "high",
                                         "finding": "the test asserts True and calls nothing, so it cannot fail",
                                         "repro": f"read tests/test_{task.lower().replace('-', '_')}.py"}
                                        for c in criteria]})
        if self.key == WEBHOOK and "for task T-001" in prompt:
            return _fence({"findings": [{"criterion": None, "in_scope": False, "severity": "low",
                                         "finding": "the webhook does not check the carrier's shared secret yet",
                                         "repro": "POST /webhooks/shipments without any header is accepted"}]})
        return _fence({"findings": []})


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


# -- the home ------------------------------------------------------------------------------------

def _prepare_home(home: Path) -> None:
    """An empty or missing folder is used; an earlier demo home is replaced; anything else is refused,
    so a real factory home is never touched."""
    if home.exists() and not home.is_dir():
        raise DemoError(f"{home} is a file, not a folder")
    if home.is_dir() and any(home.iterdir()):
        if not (home / DEMO_MARKER).is_file():
            raise DemoError(f"{home} is not empty and is not a demo home: choose another folder with --home")
        from kernel.roads import rmtree, stop_all

        old = Factory(home)
        for p in old.projects():
            with contextlib.suppress(Exception):  # an earlier preview that is already gone
                stop_all(p)
        rmtree(home)
        if home.exists():
            raise DemoError(f"could not remove the earlier demo home at {home}")
    home.mkdir(parents=True, exist_ok=True)


def _decide(project, card_id: str, verdict: str, who: tuple, reason: str) -> dict:
    from kernel.canon import Canon

    return Canon(project).decide(card_id, verdict, person=who[0], persona=who[1], reason=reason)


def build_demo(home, *, echo=print) -> dict:
    """Build the demo factory home at ``home`` and return what it holds."""
    from kernel import roads
    from kernel.canon import Canon
    from kernel.change import triage as triage_change
    from kernel.intake import intake
    from kernel.lanes import Lanes
    from kernel.observations import observe
    from kernel.packs import build_pack
    from kernel.pipeline import advance
    from kernel.signals import receive
    from kernel.signals import triage as triage_signal

    if shutil.which("git") is None:
        raise DemoError("git was not found: the demo builds real product repositories in git lanes")
    home = Path(home).resolve()
    _prepare_home(home)
    started = time.monotonic()
    clock = DemoClock(_real_now() - dt.timedelta(hours=48))
    factory = Factory(home, clock=clock)
    lanes = Lanes(home / "lanes", size=1)
    model = ScriptedModel()
    out: dict[str, Any] = {"home": str(home), "projects": {}}

    def kwargs(cell):
        return dict(model=model, lanes=lanes, cell_runner=cell, verifier_runner=cell.verify, deliver_kwargs={})

    try:
        # 1. The webhook: built through the gate, one escalation, a retry, a release and its pack.
        webhook = factory.new_project(TITLES[WEBHOOK], maturity="explore", mode="assume")
        intake(webhook, REQUESTS[WEBHOOK], model=model, requested_by=PRODUCT[0])
        cell = ScriptedCell(WEBHOOK, clock, lazy={"T-002": 3})
        first = advance(webhook, **kwargs(cell))
        if first["state"] != "waiting":
            raise DemoError(f"the webhook should wait on its escalation, but it is {first['state']}: {first.get('why')}")
        clock.at(hours=4)
        escalation = first["waiting_on"][0]
        _decide(webhook, escalation, "retry", DEVELOPER,
                "The gate is right: the test cannot fail. Build it again with a test that checks the duplicate.")
        second = advance(webhook, **kwargs(cell))
        if second["state"] != "done":
            raise DemoError(f"the webhook's release did not finish: {second['state']}: {second.get('why')}")
        roads.stop_all(webhook)  # the preview was started and checked; nothing keeps running
        clock.advance(minutes=5)
        pack = build_pack(webhook)

        # 2. The access review: built through the gate until a task escalated; it waits for a person.
        clock.at(hours=20)
        access = factory.new_project(TITLES[ACCESS], maturity="demo", mode="assume")
        intake(access, REQUESTS[ACCESS], model=model, requested_by=COMPLIANCE[0])
        waiting = advance(access, **kwargs(ScriptedCell(ACCESS, clock, lazy={"T-002": 99})))
        if waiting["state"] != "waiting":
            raise DemoError(f"the access review should wait on its escalation, but it is {waiting['state']}")

        # 3. Equipment loans: the panel's blocking questions wait; one assumption is confirmed.
        clock.at(hours=40)
        loans = factory.new_project(TITLES[LOANS], maturity="demo", mode="mixed")
        intake(loans, REQUESTS[LOANS], model=model, requested_by=OWNER[0])
        clock.at(hours=41)
        canon = Canon(loans)
        benefit = next(a for a in canon.assumptions("open") if "lost items" in a["text"])
        canon.settle_assumption(benefit["id"], confirmed=True, person=OWNER[0], persona=OWNER[1])

        # 4. The delivery square: a chat signal becomes a change; a meeting need becomes a concept.
        clock.at(hours=44)
        s1 = receive(factory, SIGNAL_CHANGE, channel="chat", source="warehouse chat", person=OPERATIONS[0],
                     persona=OPERATIONS[1])
        routed = triage_signal(factory, s1["id"])  # by rule: it names the webhook project's title
        triage_change(webhook, routed["routed_to"]["card"], model=model)
        clock.at(hours=45)
        s2 = receive(factory, SIGNAL_NEED, channel="meeting", source="monthly operations review",
                     person=OWNER[0], persona=OWNER[1])
        triage_signal(factory, s2["id"], model=model)  # the model only summarises; it names no project

        # 5. The updates inbox: a new model is available for what built the webhook.
        clock.at(hours=46)
        obs = observe(factory, "model_release", facts={"model": "demo-model-2", "replaces": BUILDER_NAME,
                                                       "projects": [webhook.pid]}, source="demo release notes")
    finally:
        roads.stop_started()

    seconds = round(time.monotonic() - started, 1)
    for key, p in ((LOANS, loans), (WEBHOOK, webhook), (ACCESS, access)):
        out["projects"][key] = {"id": p.pid, "title": p.meta["title"], "stage": p.meta["stage"],
                                "maturity": p.meta["maturity"], "profile": p.meta.get("profile")}
    out.update(seconds=seconds, pack={"version": pack["version"], "valid": pack["acceptance"]["valid"]},
               observation=obs["id"], signals=[s1["id"], s2["id"]])
    write_json(home / DEMO_MARKER, {"schema": DEMO_SCHEMA, "built": _real_now().isoformat().replace("+00:00", "Z"),
                                    "projects": {k: v["id"] for k, v in out["projects"].items()},
                                    "people": [OWNER[0], PRODUCT[0], DEVELOPER[0], OPERATIONS[0], COMPLIANCE[0]],
                                    "scripted": {"model": MODEL_NAME, "builder": BUILDER_NAME}})
    write_text(home / "README.md", _readme(out))
    for line in _summary(out, loans, webhook, access):
        echo(line)
    return out


def _readme(out: dict) -> str:
    return f"""# A Rihma demo home

Built by `rihma demo` with a scripted model (`{MODEL_NAME}`) and a scripted builder cell
(`{BUILDER_NAME}`): no model keys, no network and no Gnomon. The gate, the contract, the ledger,
the holdout custody and the local-preview road are the real kernel.

Every decision here was made by a fake person named `demo-*`. Timestamps are spread over the two
days before it was built, so the dashboard has ages and a trend to show.

Open it with `rihma-cockpit --home {out['home']}` (or `python -m cockpit.server --home ...`).
**Advance** in the cockpit runs the real pipeline, which needs Gnomon and a model: the scripted
cell exists only inside `rihma demo`. Run `rihma demo` again to rebuild this folder.
"""


def _summary(out: dict, loans, webhook, access) -> list:
    from kernel.canon import Canon
    from kernel.learn import factory_project

    def waiting(p, kind):
        return [c for c in Canon(p).cards(kind=kind)]

    concept = waiting(factory_project(webhook.factory), "concept")
    rows = [
        (TITLES[LOANS], f"stage {loans.meta['stage']}",
         f"{len([c for c in waiting(loans, 'question') if c['blocking']])} blocking questions wait for a person"),
        (TITLES[WEBHOOK], f"stage {webhook.meta['stage']}",
         f"release 1 on the local preview, capability pack {out['pack']['version']} "
         f"({'valid' if out['pack']['valid'] else 'not valid'}); a change and an update card wait"),
        (TITLES[ACCESS], f"stage {access.meta['stage']}",
         "a task escalated after 3 gate rounds; the escalation waits for a person"),
        ("Rihma itself", "", f"{len(concept)} concept from a meeting waits for a business owner"),
    ]
    width = max(len(r[0]) for r in rows)
    lines = [f"Rihma demo: built in {out['seconds']} s with no model keys, no network and no Gnomon.",
             f"Home: {out['home']}", ""]
    lines += [f"  {t.ljust(width)}  {s.ljust(7)}  {w}" for t, s, w in rows]
    lines += ["",
              f"A scripted model ({MODEL_NAME}) and a scripted builder cell ({BUILDER_NAME}) stood in for Gnomon.",
              "The gate, the contract, the ledger and the road are the real kernel. Every decision was made",
              "by a demo-* person. The local preview was started, checked and stopped again.", "",
              "Next, open the cockpit on this home:",
              f"  rihma-cockpit --home {out['home']}",
              f"  (or, without installing: python -m cockpit.server --home {out['home']})"]
    return lines
