"""`rihmasto demo`: one showcase factory home, built with no model keys, no network and no Gnomon (FR-N4-AC-1).

A scripted model stands in for the analyst, the holdout author and the website chat's assistant,
and a scripted builder cell and verifier stand in for Gnomon's cells. Everything else is the real
kernel: the panel and the brief, the spec and its provenance rules, the compiled contract, the
holdout custody, git lanes, the gate (the product's own tests, the criterion trace, fail-first, the
verifier's findings), escalation, the local-preview road, the capability pack, the SARIF reader and
the security gate, the evidence pack, the autonomy cap, embeds, comments, brownfield adoption,
signals, concepts and the updates inbox.

What it builds, with neutral examples only (docs/demo.md is the guided tour):

- **Equipment loans** (web service, mixed mode, demo maturity): the panel's blocking questions wait
  for a person; a demo business owner has confirmed one assumption.
- **Shipment webhook to the stock system** (integration, assume mode, explore maturity): built
  through the gate. One task escalated after three rounds; a demo developer chose retry, and it
  passed. Release 1 ran on the local-preview road and has a capability pack. Then:
  - a security scan by a neutral example tool ("Example Scanner"), written here as SARIF 2.1.0 over
    the release's own code, was ingested; the demo compliance person accepted its one error as a
    risk, with a reason and an expiry, and the security gate recorded its verdict;
  - a demo stakeholder commented on a requirement (a comment decides nothing);
  - a website feedback chat (an embed) was created for it, and one end user's message went through
    the real embed code, with the scripted model as the chat's assistant: it was filed as a change
    and triaged by the rules;
  - a chat signal became a change on it, and an observation (a new model) opened an update card;
  - the demo compliance person exported its evidence pack into `<home>/exports/`.
- **Access review check** (ops agent, assume mode, demo maturity): built through the gate until a
  task escalated; the escalation waits for a person, with the gate's objections. Its holdout
  scenario sits in the holdout custody. The demo compliance person capped its autonomy at 3
  (prepare), with a reason.
- **Stock levels service**: an existing service (a small git repository the demo writes into
  `<home>/existing/stock-levels`, with its own unittest suite) adopted to maintain it: inventory and
  as-is spec by rule, and its own suite run once as the characterisation baseline.
- **Rihmasto itself**: a need raised in a meeting became a concept that waits for a business owner.

Every decision is made by a fake person named `demo-*`. The scripted model and cell are named
`demo-model` and `demo-builder`, and the scanner is an example; nothing they produce measures a real
model or a real scanner, and what the demo did not measure says "not measured". Timestamps are
spread over the last two days so the dashboard has ages and a trend to show. The local preview is
started, checked over loopback and stopped again before the command returns.

The kernel never imports the tests; this module re-implements the scripted model and cell natively.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from collections.abc import Callable
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
STAKEHOLDER = ("demo-stakeholder", "stakeholder")
PEOPLE = (OWNER, PRODUCT, DEVELOPER, OPERATIONS, COMPLIANCE, STAKEHOLDER)


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
STOCK = "stock"

TITLES = {
    LOANS: "Equipment loans",
    WEBHOOK: "Shipment webhook to the stock system",
    ACCESS: "Access review check",
    STOCK: "Stock levels service",
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

# A stakeholder's remark on the webhook's duplicate rule (R-2). It decides nothing.
COMMENT = {"requirement": "R-2",
           "text": "The carrier sometimes sends a relabelled parcel again under a new event_id. Would that count "
                   "twice? It happened twice last month."}

# The website feedback chat on the webhook, and the one end user who used it.
EMBED_ORIGIN = "https://warehouse.example"
EMBED_LABEL = "Warehouse feedback"
EMBED_BRIEF = "The shipment webhook keeps the warehouse's incoming stock up to date from the carrier's events."
EMBED_PROMPT = "You are a short, friendly intake assistant on a website."
EMBED_MESSAGE = ("We also need the expected arrival time next to each item on the incoming list, so we can plan "
                 "who unloads.")
EMBED_REPLY = {"reply": "Thank you: the expected arrival time beside each incoming item, to plan the unloading. "
                        "It has been passed on to the team.",
               "ready": True,
               "summary": "A warehouse user asks for each item's expected arrival time on the incoming list, to "
                          "plan the unloading."}

# The example scanner's rules over the webhook's app/routes.py: (rule, level, CWE, title, the line it
# points at, message). Both describe the scripted cell's code as it is: nothing is invented.
SCANNER = "Example Scanner"
SCAN_FILE = "example-scanner.sarif"
SCAN_RULES = (
    ("EX-AUTH-001", "error", "306", "An endpoint that changes data accepts requests without authentication",
     '@route("POST", "/webhooks/shipments")',
     "POST /webhooks/shipments accepts a request with no authentication: anyone who can reach it adds incoming "
     "stock."),
    ("EX-INPUT-002", "warning", "20", "A number from the request is used without a range check",
     'int(item.get("qty", 1))',
     "qty is read with int() and never checked: a negative quantity lowers the incoming stock."),
)
RISK_REASON = ("Release 1 runs only on the local preview at explore maturity, with recorded sample events. The "
               "carrier's shared secret (the panel's Q-003) is an IT rule for the next maturity; the verifier noted "
               "the same.")
RISK_DAYS = 90

AUTONOMY = (3, "An ops agent that reads access lists stays in the sandbox: nothing reaches staging or production "
               "until the compliance owner has signed off its first quarterly report.")
EXPORTS = "exports"

# The existing service a team brings in to maintain: a small git repository with its own tests.
STOCK_DIR = ("existing", "stock-levels")
STOCK_COMMIT = "The stock levels service as it runs today"
STOCK_README = """# Stock levels

A small HTTP service that answers how many of each item the warehouse holds. The warehouse team
has run it on its own server for two years.

## Run it

    python -m stock.server 8080
"""
STOCK_LEVELS = '''"""Stock levels, kept as a dict of item to quantity."""


def receive(levels, sku, qty):
    """Add ``qty`` of ``sku``; a receipt needs an item and a positive quantity."""
    sku, qty = str(sku or "").strip(), int(qty)
    if not sku or qty <= 0:
        raise ValueError("a receipt needs an item and a positive quantity")
    levels[sku] = levels.get(sku, 0) + qty
    return levels[sku]


def issue(levels, sku, qty):
    """Take ``qty`` of ``sku`` out; never below zero."""
    qty = int(qty)
    if qty > levels.get(sku, 0):
        raise ValueError(f"only {levels.get(sku, 0)} of {sku} in stock")
    levels[sku] -= qty
    return levels[sku]
'''
STOCK_SERVER = '''"""A small HTTP front for the stock levels (standard library only)."""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from stock.levels import receive

LEVELS = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        sku = self.path.rsplit("/", 1)[-1]
        self._send(200, {"sku": sku, "level": LEVELS.get(sku, 0)})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self._send(201, {"level": receive(LEVELS, body.get("sku"), body.get("qty", 1))})

    def _send(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8080), Handler).serve_forever()
'''
STOCK_TESTS = '''import unittest

from stock.levels import issue, receive


class LevelsTest(unittest.TestCase):
    def test_a_receipt_adds_to_the_level(self):
        levels = {}
        receive(levels, "drill", 2)
        self.assertEqual(receive(levels, "drill", 3), 5)

    def test_a_receipt_needs_a_positive_quantity(self):
        with self.assertRaises(ValueError):
            receive({}, "drill", 0)

    def test_an_issue_never_goes_below_zero(self):
        with self.assertRaises(ValueError):
            issue({"ladder": 1}, "ladder", 2)
'''
STOCK_FILES = {
    "README.md": STOCK_README,
    "stock/__init__.py": '"""Stock levels: how many of each item the warehouse holds."""\n',
    "stock/levels.py": STOCK_LEVELS,
    "stock/server.py": STOCK_SERVER,
    "tests/test_levels.py": STOCK_TESTS,
}


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


# Prompts answered from a script per request: (how the prompt starts, the scripts by request).
SCRIPTED: tuple[tuple[str, dict], ...] = (
    ("You turn a brief into a software specification", SPECS),
    ("You write acceptance scenarios", HOLDOUTS),
    ("Classify a piece of feedback", TRIAGE),
)


def _panel(which: str, prompt: str) -> dict | None:
    """One perspective's reading and questions, for the perspective the prompt names."""
    for perspective, questions in PANELS[which].items():
        if f"You are the **{perspective}** perspective" in prompt:
            return {"reading": f"The {perspective.replace('_', ' ')} reading of the request (scripted for the demo).",
                    "questions": questions}
    return None


class ScriptedModel(Model):
    """Answers the kernel's prompts from the scripts above. It is not a model: it never reads the
    prompt beyond telling which request and which kind of question it is."""

    name = MODEL_NAME

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def ask(self, prompt: str, *, role: str) -> str:
        self.calls.append((role, prompt[:80]))
        answer = self._script(prompt)
        if answer is None:
            raise ModelError(f"the demo's scripted model has no answer for this {role} prompt")
        return _fence(answer)

    @staticmethod
    def _script(prompt: str) -> Any:
        if prompt.startswith(EMBED_PROMPT):
            return EMBED_REPLY
        if prompt.startswith("A business need arrived") and SIGNAL_NEED in prompt:
            return CONCEPT
        which = _which(prompt)
        if "perspective on a panel" in prompt and which:
            return _panel(which, prompt)
        if prompt.startswith("A panel of perspectives"):
            return {"opinions": OPINIONS.get(which, []) if which else []}
        for start, scripts in SCRIPTED:
            if prompt.startswith(start) and which in scripts:
                return scripts[which]
        return None


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
        # the runner says what ran the round: a scripted stand-in, not Gnomon (no in-run policy, no audit trail)
        from kernel.runners import assurance_of
        return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": steps,
                "model": BUILDER_NAME, "output": f"{task}: {output} (scripted for the demo)",
                "runner": {"name": "scripted", "label": "scripted", "version": None,
                           **assurance_of("scripted")}}

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

    verify.__dict__["model"] = MODEL_NAME     # the stand-in names its model: the routing's is not what answered


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


def _new(b: Any, title: str, **how: str) -> Any:
    """A demo project, set outright to build without waiting for a go-ahead on its spec (kernel/go_ahead.py): a
    scripted demo never stops on a look a person did not ask for."""
    from kernel.go_ahead import choose

    p = b.factory.new_project(title, **how)
    choose(p, wait=False, person=PRODUCT[0], persona=PRODUCT[1], where="the scripted demo",
           reason="the demo runs unattended")
    return p


def _decide(project: Any, card_id: str, verdict: str, who: tuple, reason: str) -> dict:
    from kernel.canon import Canon

    return Canon(project).decide(card_id, verdict, person=who[0], persona=who[1], reason=reason)


class _Build:
    """What the steps of one demo build share: the home, the demo clock, the factory, the lanes,
    the scripted model, and what the build reports."""

    def __init__(self, home: Path) -> None:
        from kernel.lanes import Lanes

        self.home = home
        self.clock = DemoClock(_real_now() - dt.timedelta(hours=48))
        self.factory = Factory(home, clock=self.clock)
        self.lanes = Lanes(home / "lanes", size=1)
        self.model = ScriptedModel()
        self.out: dict[str, Any] = {"home": str(home), "projects": {}}

    def advance(self, project: Any, cell: ScriptedCell) -> dict:
        """The real pipeline, with the scripted cell and verifier in place of Gnomon's."""
        from kernel.pipeline import advance

        return advance(project, model=self.model, lanes=self.lanes, cell_runner=cell, verifier_runner=cell.verify,
                       deliver_kwargs={})


def build_demo(home: str | Path, *, echo: Callable[[str], object] = print) -> dict:
    """Build the demo factory home at ``home`` and return what it holds."""
    from kernel import roads

    if shutil.which("git") is None:
        raise DemoError("git was not found: the demo builds real product repositories in git lanes")
    home = Path(home).resolve()
    _prepare_home(home)
    started = time.monotonic()
    b = _Build(home)
    try:
        webhook = _webhook(b)       # hours 0-4: the gate, an escalation, a retry, release 1 and its pack
        _security(b, webhook)       # hours 6-8: a SARIF scan, a risk accepted, the security gate
        _comment(b, webhook)        # hour 10: a stakeholder's comment on a requirement
        access = _access(b)         # hours 20-22: built until an escalation; its autonomy capped
        _embed(b, webhook)          # hours 24-30: a website feedback chat, one end user's message
        loans = _loans(b)           # hours 40-41: the panel's blocking questions wait
        stock = _adopt(b)           # hour 42: an existing service adopted to maintain it
        _square(b, webhook)         # hours 44-46: signals, a concept, an update card
        _evidence(b, webhook)       # hour 47: the webhook's evidence pack, exported
    finally:
        roads.stop_started()

    out = b.out
    out["seconds"] = round(time.monotonic() - started, 1)
    for key, p in ((LOANS, loans), (WEBHOOK, webhook), (ACCESS, access), (STOCK, stock)):
        out["projects"][key] = {"id": p.pid, "title": p.meta["title"], "stage": p.meta["stage"],
                                "maturity": p.meta["maturity"], "profile": p.meta.get("profile")}
    write_json(home / DEMO_MARKER, {"schema": DEMO_SCHEMA, "built": _real_now().isoformat().replace("+00:00", "Z"),
                                    "projects": {k: v["id"] for k, v in out["projects"].items()},
                                    "people": [who[0] for who in PEOPLE],
                                    "scripted": {"model": MODEL_NAME, "builder": BUILDER_NAME, "scanner": SCANNER}})
    write_text(home / "README.md", _readme(out))
    for line in _summary(out, loans, webhook, access, stock):
        echo(line)
    return out


# -- the steps, in the order they happen on the demo clock ----------------------------------------

def _webhook(b: _Build) -> Any:
    """Built through the gate: one task escalates after three rounds, a demo developer chooses retry,
    release 1 runs on the local-preview road and gets its capability pack."""
    from kernel import roads
    from kernel.intake import intake
    from kernel.packs import build_pack

    webhook = _new(b, TITLES[WEBHOOK], maturity="explore", mode="assume")
    intake(webhook, REQUESTS[WEBHOOK], model=b.model, requested_by=PRODUCT[0])
    cell = ScriptedCell(WEBHOOK, b.clock, lazy={"T-002": 3})
    first = b.advance(webhook, cell)
    if first["state"] != "waiting":
        raise DemoError(f"the webhook should wait on its escalation, but it is {first['state']}: {first.get('why')}")
    b.clock.at(hours=4)
    _decide(webhook, first["waiting_on"][0], "retry", DEVELOPER,
            "The gate is right: the test cannot fail. Build it again with a test that checks the duplicate.")
    second = b.advance(webhook, cell)
    if second["state"] != "done":
        raise DemoError(f"the webhook's release did not finish: {second['state']}: {second.get('why')}")
    roads.stop_all(webhook)  # the preview was started and checked; nothing keeps running
    b.clock.advance(minutes=5)
    pack = build_pack(webhook)
    b.out["pack"] = {"version": pack["version"], "valid": pack["acceptance"]["valid"]}
    return webhook


def _sarif(routes: str) -> dict:
    """The example scanner's SARIF 2.1.0 log over the release's app/routes.py. Each result points at
    the line it describes, found in the code the release holds."""
    lines = routes.splitlines()
    results = []
    for rule, level, _, _, snippet, message in SCAN_RULES:
        line = next((n for n, text in enumerate(lines, 1) if snippet in text), None)
        if line is None:
            raise DemoError(f"the release's app/routes.py has no line with {snippet!r} for the example scan")
        results.append({"ruleId": rule, "level": level, "message": {"text": message},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app/routes.py"},
                                                            "region": {"startLine": line}}}]})
    rules = [{"id": rule, "shortDescription": {"text": title}, "defaultConfiguration": {"level": level},
              "properties": {"tags": ["security", f"CWE-{cwe}"]}} for rule, level, cwe, title, _, _ in SCAN_RULES]
    return {"version": "2.1.0", "runs": [{
        "tool": {"driver": {"name": SCANNER, "version": "1.0.0", "rules": rules}},
        "invocations": [{"executionSuccessful": True}],
        "properties": {"note": "written by the demo over its own release: an example scan, not a real scanner's "
                               "output"},
        "results": results}]}


def _security(b: _Build, webhook: Any) -> None:
    """A neutral example scanner's SARIF, written from the release's own code, goes through the real
    reader. The demo compliance person accepts the error as a risk until a date, with a reason, and
    the security gate records its verdict (the warning stays open; it does not block)."""
    from adapters import sarif
    from kernel.lanes import _git
    from kernel.security import accept_risk, security_gate

    b.clock.at(hours=6)
    path = b.home / "scans" / SCAN_FILE
    write_json(path, _sarif(_git(webhook.path("repo.git"), "show", "main:app/routes.py")))
    scan = sarif.ingest(webhook, path, person=DEVELOPER[0], persona=DEVELOPER[1])
    b.clock.at(hours=8)
    error = next(f for f in scan["findings"] if f["level"] == "error")
    accepted = accept_risk(webhook, error["id"], person=COMPLIANCE[0], persona=COMPLIANCE[1], reason=RISK_REASON,
                           expires=b.clock.today() + dt.timedelta(days=RISK_DAYS))
    gate = security_gate(webhook)
    b.out["security"] = {"tool": SCANNER, "file": path.relative_to(b.home).as_posix(), "scan": scan["scan"],
                         "counts": {k: v for k, v in scan["counts"].items() if v}, "accepted": accepted["finding"],
                         "expires": accepted["expires"], "gate": gate["verdict"]}


def _comment(b: _Build, webhook: Any) -> None:
    """A demo stakeholder comments on the duplicate rule. A comment decides nothing; a product owner
    may promote it into a change."""
    from kernel.canon import Canon

    b.clock.at(hours=10)
    c = Canon(webhook).comment({"kind": "requirement", "id": COMMENT["requirement"]}, COMMENT["text"],
                               person=STAKEHOLDER[0], persona=STAKEHOLDER[1])
    b.out["comment"] = {"id": c["id"], "target": c["target"], "by": c["person"]}


def _access(b: _Build) -> Any:
    """Built through the gate until a task escalated; the escalation waits for a person. The demo
    compliance person then caps the project's autonomy, with a reason."""
    from kernel.autonomy import set_cap
    from kernel.intake import intake

    b.clock.at(hours=20)
    access = _new(b, TITLES[ACCESS], maturity="demo", mode="assume")
    intake(access, REQUESTS[ACCESS], model=b.model, requested_by=COMPLIANCE[0])
    waiting = b.advance(access, ScriptedCell(ACCESS, b.clock, lazy={"T-002": 99}))
    if waiting["state"] != "waiting":
        raise DemoError(f"the access review should wait on its escalation, but it is {waiting['state']}")
    b.clock.at(hours=22)
    level, reason = AUTONOMY
    cap = set_cap(access, level, person=COMPLIANCE[0], persona=COMPLIANCE[1], reason=reason)
    b.out["autonomy"] = {"project": access.pid, "cap": cap["cap"], "by": COMPLIANCE[0]}
    return access


def _embed(b: _Build, webhook: Any) -> None:
    """A demo product owner makes a website feedback chat for the webhook. One end user's message
    goes through the real embed code (its key, origin and filing), with the scripted model as the
    chat's assistant: it is filed as a change and triaged by the rules. The key lives only here."""
    from kernel import embeds
    from kernel.canon import Canon

    b.clock.at(hours=24)
    e = embeds.create(b.factory, kind="feedback", origins=[EMBED_ORIGIN], person=PRODUCT[0], persona=PRODUCT[1],
                      project_id=webhook.pid, label=EMBED_LABEL, brief=EMBED_BRIEF)
    b.clock.at(hours=30)
    turn = embeds.converse(b.factory, e["id"], e["key"], EMBED_ORIGIN, [{"role": "person", "text": EMBED_MESSAGE}],
                           model=b.model)
    filed = turn["filed"] or {}
    if filed.get("kind") != "change":
        raise DemoError(f"the website chat's message was not filed as a change: {filed}")
    triage = Canon(webhook).get_card(filed["id"])["payload"].get("triage") or {}
    b.out["embed"] = {"id": e["id"], "card": filed["id"], "class": triage.get("class"), "by": triage.get("by")}


def _loans(b: _Build) -> Any:
    """The panel's blocking questions wait for a person; a demo business owner confirms one assumption."""
    from kernel.canon import Canon
    from kernel.intake import intake

    b.clock.at(hours=40)
    loans = _new(b, TITLES[LOANS], maturity="demo", mode="mixed")
    intake(loans, REQUESTS[LOANS], model=b.model, requested_by=OWNER[0])
    b.clock.at(hours=41)
    canon = Canon(loans)
    benefit = next(a for a in canon.assumptions("open") if "lost items" in a["text"])
    canon.settle_assumption(benefit["id"], confirmed=True, person=OWNER[0], persona=OWNER[1])
    return loans


def _existing_repo(path: Path, at: str) -> None:
    """The existing service a team brings in: a small git repository with its own tests, committed
    by a demo person at the demo clock's time."""
    for rel, text in STOCK_FILES.items():
        _write(path / rel, text)
    # Example Gnomon config on the adopted service so Gnomon safety posture shows real suggestions in the demo.
    _write(path / ".gnomon" / "config.toml", '[defaults]\nedit_format = "str_replace"\n\n[audit]\nenabled = true\n')
    _write(path / ".gnomon" / "policy.toml",
           '[verify]\ncommand = "python -m unittest"\nafter = "change"\n\n[governance]\nlevel = "observe"\n')
    name, email = DEVELOPER[0], f"{DEVELOPER[0]}@example.invalid"
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": at,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": at}
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", STOCK_COMMIT)):
        proc = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=path, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise DemoError(f"git {args[0]} failed for the demo's existing service: {proc.stderr.strip()[-300:]}")


def _adopt(b: _Build) -> Any:
    """A demo developer adopts the existing service to maintain it: mirrored with its upstream
    fetch-only, inventoried and specified as it is by rule, and its own suite run once as the
    characterisation baseline. Nothing is built until a change arrives. The demo developer names its kind of
    work, so the scripted demo never waits on the question an unclear adoption asks (kernel/adopt_kind.py)."""
    from kernel.adopt import adopt

    b.clock.at(hours=42)
    repo = b.home.joinpath(*STOCK_DIR)
    _existing_repo(repo, b.clock.stamp())
    b.clock.advance(minutes=20)
    stock = adopt(b.factory, TITLES[STOCK], source=repo, intent="maintain", person=DEVELOPER[0],
                  persona=DEVELOPER[1], maturity="production", timeout=120, profile="web_service")
    # Leave one untracked draft file in the adopted working copy so Work in progress has a live change,
    # and seed one hand-reached demo machine + open cross-agent ask on the agent channel.
    _write(repo / "wip_notes.md", "# Draft\nNext: add low-stock alert threshold.\n")
    from kernel import asks, machines

    machines.add(b.factory, {"name": "demo-laptop", "reach": "hand", "os": "linux", "agents": ["claude-code"],
                             "note": "Example workstation for copy-and-paste agent asks"},
                 person=DEVELOPER[0], persona=DEVELOPER[1])
    asks.create(stock, to="claude-code", machine="demo-laptop",
                text="Check whether stock_levels.py handles negative restock deltas cleanly.",
                why="Demo example of an open ask to an agent on another machine",
                person=DEVELOPER[0], persona=DEVELOPER[1])
    return stock


def _square(b: _Build, webhook: Any) -> None:
    """The delivery square: a chat signal becomes a change on the webhook, a meeting need becomes a
    concept; then the updates inbox: a new model is available for what built the webhook."""
    from kernel.change import triage as triage_change
    from kernel.observations import observe
    from kernel.signals import receive
    from kernel.signals import triage as triage_signal

    b.clock.at(hours=44)
    s1 = receive(b.factory, SIGNAL_CHANGE, channel="chat", source="warehouse chat", person=OPERATIONS[0],
                 persona=OPERATIONS[1])
    routed = triage_signal(b.factory, s1["id"])  # by rule: it names the webhook project's title
    triage_change(webhook, routed["routed_to"]["card"], model=b.model)
    b.clock.at(hours=45)
    s2 = receive(b.factory, SIGNAL_NEED, channel="meeting", source="monthly operations review",
                 person=OWNER[0], persona=OWNER[1])
    triage_signal(b.factory, s2["id"], model=b.model)  # the model only summarises; it names no project
    b.clock.at(hours=46)
    obs = observe(b.factory, "model_release", facts={"model": "demo-model-2", "replaces": BUILDER_NAME,
                                                     "projects": [webhook.pid]}, source="demo release notes")
    b.out.update(observation=obs["id"], signals=[s1["id"], s2["id"]])


def _evidence(b: _Build, webhook: Any) -> None:
    """The demo compliance person exports the webhook's evidence pack into the demo home."""
    from kernel.evidence_pack import export

    b.clock.at(hours=47)
    path = export(webhook, b.home / EXPORTS, person=COMPLIANCE[0], persona=COMPLIANCE[1])
    with zipfile.ZipFile(path) as z:
        verdict = json.loads(z.read("attestation.json"))["verdict"]
    b.out["evidence"] = {"file": path.relative_to(b.home).as_posix(), "attestation": verdict}


# -- what the build says -----------------------------------------------------------------------------

def _readme(out: dict) -> str:
    return f"""# A Rihmasto demo home

Built by `rihmasto demo` with a scripted model (`{MODEL_NAME}`) and a scripted builder cell
(`{BUILDER_NAME}`): no model keys, no network and no Gnomon. The gate, the contract, the ledger,
the holdout custody, the local-preview road, the SARIF reader and the security gate, the evidence
pack, embeds and adoption are the real kernel. The security scan in `scans/` is an example written
by the demo ("{SCANNER}"), not a real scanner's output.

Every decision here was made by a fake person named `demo-*`. Timestamps are spread over the two
days before it was built, so the dashboard has ages and a trend to show.

- `exports/`: the webhook's evidence pack, as a reviewer receives it.
- `scans/`: the example scanner's SARIF file.
- `existing/stock-levels/`: the existing service the demo adopted. Commit a change there, then run
  `rihmasto sync <its project id>` to see the drift and the review card it opens.

Open it with `rihmasto-cockpit --home {out['home']}` (or `python -m cockpit.server --home ...`).
**Advance** in the cockpit runs the real pipeline, which needs Gnomon and a model: the scripted
cell exists only inside `rihmasto demo`. Run `rihmasto demo` again to rebuild this folder. The
guided tour is `docs/demo.md` in the Rihmasto repository.
"""


def _summary(out: dict, loans: Any, webhook: Any, access: Any, stock: Any) -> list:
    from kernel.canon import Canon
    from kernel.learn import factory_project

    concepts = Canon(factory_project(webhook.factory)).cards(kind="concept")
    changes = Canon(webhook).cards(kind="change")
    blocking = [c for c in Canon(loans).cards(kind="question") if c["blocking"]]
    sec, emb, aut = out["security"], out["embed"], out["autonomy"]
    rows = [
        (TITLES[LOANS], f"stage {loans.meta['stage']}", f"{len(blocking)} blocking questions wait for a person"),
        (TITLES[WEBHOOK], f"stage {webhook.meta['stage']}",
         f"release 1 on the local preview, capability pack {out['pack']['version']} "
         f"({'valid' if out['pack']['valid'] else 'not valid'}); {len(changes)} changes and an update card wait"),
        (TITLES[ACCESS], f"stage {access.meta['stage']}",
         f"a task escalated after 3 gate rounds; the escalation waits for a person; autonomy cap {aut['cap']}"),
        (TITLES[STOCK], f"stage {stock.meta['stage']}", f"adopted to maintain; {_baseline_line(stock)}"),
        ("Rihmasto itself", "", f"{len(concepts)} concept from a meeting waits for a business owner"),
    ]
    width = max(len(r[0]) for r in rows)
    lines = [f"Rihmasto demo: built in {out['seconds']} s with no model keys, no network and no Gnomon.",
             f"Home: {out['home']}", ""]
    lines += [f"  {t.ljust(width)}  {s.ljust(7)}  {w}" for t, s, w in rows]
    lines += ["", "Also on the webhook:",
              f"  - a website feedback chat ({emb['id']}): one end user's message, filed as {emb['card']} and "
              f"triaged by the {emb['by']} as {emb['class']}",
              f"  - a stakeholder's comment ({out['comment']['id']}) on requirement {out['comment']['target']['id']}",
              f"  - a scan by {sec['tool']} ({sec['file']}): the error accepted as a risk by {COMPLIANCE[0]} until "
              f"{sec['expires']}; security gate {sec['gate']}",
              f"  - its evidence pack: {out['evidence']['file']} ({out['evidence']['attestation']})",
              "",
              f"A scripted model ({MODEL_NAME}) and a scripted builder cell ({BUILDER_NAME}) stood in for Gnomon.",
              "The gate, the contract, the ledger and the road are the real kernel. Every decision was made",
              "by a demo-* person. The local preview was started, checked and stopped again.", "",
              "Next, open the cockpit on this home (the tour is docs/demo.md):",
              f"  rihmasto-cockpit --home {out['home']}",
              f"  (or, without installing: python -m cockpit.server --home {out['home']})"]
    return lines


def _baseline_line(project: Any) -> str:
    """What the adopted service's own suite did at the baseline, as measured (or not measured)."""
    base = project.read("baseline.json") or {}
    counts = next((r.get("counts") for r in base.get("runs") or [] if r.get("counts")), None)
    said = f"its own tests at the baseline: {base.get('verdict', 'not measured')}"
    return said + (f" ({counts['passed']} of {counts['ran']} passed)" if counts and "ran" in counts else "")

