"""The needs of the acceptance matrix (docs/acceptance.md), and what the scripted model answers for each.

Each need is what a person types, neutral and realistic: a one-line need, a two-line vague one, a
written spec, a Finnish need, a single workflow, an automation and an assistant. The ops agent and
the integration reuse the demo's own requests, panels and specs (kernel/demo.py), with holdout
scenarios of their own. For each need the scripted model holds the panel's questions (the answer
each perspective would assume, and which are blocking), the analyst's spec and the holdout
author's scenarios. None of it measures a model: a live run on the GPU box does
(docs/acceptance.md, "The live acid test").

Every criterion a builder sees names the call that checks it ("POST /bookings ...") and starts its
"then" with the status, so the scripted builder cell (scripts.InterfaceCell) can meet it.
"""

from __future__ import annotations

from typing import Any

from kernel import demo


def q(text: str, why: str, proposed: str, *, blocking: bool = False, options: tuple = ()) -> dict:
    return {"text": text, "why": why, "blocking": blocking, "proposed_answer": proposed,
            "options": [proposed, *options]}


def ac(given: str, when: str, then: str, kind: str = "test") -> dict:
    return {"given": given, "when": when, "then": then, "kind": kind}


def req(statement: str, sources: list, *criteria: dict, priority: str = "must", rid: str = "") -> dict:
    return {"id": rid, "statement": statement, "sources": sources, "priority": priority,
            "acceptance": list(criteria)}


def post(path: str, criterion: str, status: int) -> dict:
    """A holdout step against the running service: the call a visible criterion names."""
    return {"method": "POST", "path": path, "body": {"criterion": criterion}, "expect_status": status}


# -- G1: a one-line need ---------------------------------------------------------------------------

ONE_LINE = "We need room booking for the office."

ROOMS = {
    "markers": ("room booking", "book a room", "rooms, and who keeps"),
    "panel": {
        "business": [
            q("Who may book a room, and whose booking stands when two people want the same slot?",
              "It decides the rules of the whole tool.", "anyone in the office books; the first booking stands",
              blocking=True, options=("only team leads book", "the office manager settles clashes")),
            q("How will we know it helps?", "The benefit needs a baseline.",
              "fewer double-booked rooms per month, against last month's count"),
        ],
        "end_user": [q("Do people book from a phone, a laptop or the screen beside the room?",
                       "It decides the first screen.", "from a phone or a laptop: the page works on both")],
        "it_security": [q("Must people sign in with their work account?", "Identity decides who may cancel what.",
                          "not in the first version: a shared office page")],
        "operations": [q("Which rooms are there, and who keeps the list up to date?",
                         "Without a list of rooms nothing can be booked.", "the office manager keeps the list",
                         blocking=True, options=("facilities imports it from a spreadsheet",))],
        "delivery": [q("What is the smallest first version?", "Scope.",
                       "list the rooms, book a free slot, cancel a booking")],
    },
    "opinions": [{"question": "Q-001", "perspective": "it_security",
                  "opinion": "a booking should name who made it, so a clash can be settled"}],
    "spec": {
        "title": "Room booking",
        "summary": "People see the office's meeting rooms and book a free slot in one. The first booking of a "
                   "slot stands.",
        "users": ["people in the office", "the office manager"],
        "interface": [{"method": "GET", "path": "/rooms", "purpose": "the rooms"},
                      {"method": "POST", "path": "/rooms", "purpose": "the office manager adds a room"},
                      {"method": "POST", "path": "/bookings", "purpose": "book a slot"},
                      {"method": "DELETE", "path": "/bookings/{id}", "purpose": "cancel a booking"}],
        "requirements": [
            req("A person books a free slot in a meeting room (room booking).", ["request"],
                ac("a room with no bookings", "POST /bookings with a room, a start, an end and a name",
                   "201 and the booking has an id"),
                ac("a person at their desk", "they book a room", "201: the booking is made", "holdout")),
            req("A slot that is already booked cannot be booked again: the first booking stands.", ["Q-001"],
                ac("a booked slot", "POST /bookings for the same room at an overlapping time",
                   "409 and the first booking is named")),
            req("The office manager keeps the list of rooms.", ["Q-005"],
                ac("no rooms", "POST /rooms with a name and a size", "201 and GET /rooms lists it")),
            req("A booking can be cancelled.", ["proposed"],
                ac("a booking", "DELETE /bookings/{id}", "200 and the slot is free again"), priority="should"),
        ],
        "out_of_scope": ["sign-in with a work account (a later version)"],
    },
    "holdouts": {"scenarios": [{"criterion": "R-1-AC-2", "steps": [post("/bookings", "R-1-AC-1", 201)]}]},
}

# -- G2: a two-line vague need ---------------------------------------------------------------------

TWO_LINE = ("Our customer service team drowns in email and requests get lost.\n"
            "We want something better, maybe with AI.")

QUEUE = {
    "markers": ("customer service", "request queue"),
    "panel": {
        "business": [q("What should change first for the customer service team: nothing lost, faster answers or "
                       "fewer emails?", "A vague need has three different products in it.",
                       "nothing lost: every email becomes a request with an owner", blocking=True,
                       options=("faster answers", "fewer emails"))],
        "end_user": [q("Where do requests arrive today?", "It decides what the first version reads.",
                       "one shared mailbox", blocking=True, options=("several mailboxes", "email and phone"))],
        "it_security": [q("May an AI read customers' emails, and where may that data be processed?",
                          "Customer emails hold personal data.",
                          "only to suggest a reply a person approves, processed in the EU and never used to train",
                          blocking=True, options=("no AI in the first version",))],
        "operations": [q("Who picks up a request nobody has claimed?", "A queue without an owner loses requests too.",
                         "the team lead, after one working day")],
        "delivery": [q("What is the smallest first version?", "Scope.",
                       "a shared queue: each email a request with an owner and a state")],
    },
    "opinions": [{"question": "Q-003", "perspective": "business",
                  "opinion": "suggested replies are what saves the team's time"}],
    "spec": {
        "title": "Customer service request queue",
        "summary": "Every customer email becomes a request with an owner and a state, so none is lost. An AI may "
                   "suggest a reply that a person approves.",
        "users": ["the customer service team", "its team lead"],
        "interface": [{"method": "POST", "path": "/requests", "purpose": "an email becomes a request"},
                      {"method": "GET", "path": "/requests/unclaimed", "purpose": "requests nobody has claimed"},
                      {"method": "POST", "path": "/requests/{id}/claim", "purpose": "take ownership"},
                      {"method": "POST", "path": "/requests/{id}/suggestion", "purpose": "a suggested reply"}],
        "requirements": [
            req("Every email to the shared mailbox becomes a request in the customer service request queue.",
                ["request", "Q-001", "Q-002"],
                ac("an email", "POST /requests with its sender and text", "201 and the request is open with no owner"),
                ac("a new email", "it arrives", "201: it is in the queue", "holdout")),
            req("A person claims a request and becomes its owner.", ["Q-001"],
                ac("an open request", "POST /requests/{id}/claim with a name", "200 and the request names its owner")),
            req("A request nobody claimed for a working day is listed for the team lead.", ["Q-004"],
                ac("a request unclaimed for a day", "GET /requests/unclaimed", "200 and lists the request")),
            req("A suggested reply waits for a person's approval and is never sent on its own.", ["Q-003"],
                ac("a request", "POST /requests/{id}/suggestion", "202 and the suggestion waits for approval")),
        ],
        "out_of_scope": ["sending replies without a person", "training a model on customer emails"],
    },
    "holdouts": {"scenarios": [{"criterion": "R-1-AC-2", "steps": [post("/requests", "R-1-AC-1", 201)]}]},
}

# -- G3: a written spec ------------------------------------------------------------------------------

WRITTEN = """# Visitor sign-in

## Goal

Visitors sign in at reception on a tablet page with a short form, and the host they visit sees that
they have arrived. Reception sees who is in the building at any moment, for example in a fire drill.

## Requirements

- VIS-001: A visitor signs in with their name, company and the host they visit.
- VIS-002: The host sees that their visitor has arrived.
- VIS-003: Reception sees everyone signed in and not yet signed out.
- VIS-004: A visitor signs out at reception, or reception signs them out at the end of the day.

## Users

Visitors, the hosts they visit and the reception desk.

## Out of scope

Printing badges. Signing in with a work account.
"""

VISITORS = {
    "markers": ("visitor sign-in", "visitor records", "fire drill"),
    "panel": {
        "business": [q("Who reads the list of people in the building during a fire drill?",
                       "The list is for a moment when every second counts.", "the reception desk, on the same page")],
        "end_user": [q("Do visitors type their details or scan a code?", "It decides the tablet page.",
                       "type them; no codes in the first version")],
        "it_security": [q("How long are visitor records kept?", "Visitor records are personal data.",
                          "30 days, then deleted", options=("one year",))],
        "operations": [q("How is the host told?", "The spec says the host sees it, not how.",
                         "on the host's own list on the page; no email in the first version")],
        "delivery": [],
    },
    "opinions": [],
    "spec": {
        "title": "Visitor sign-in",
        "summary": "Visitors sign in on a tablet page and their hosts see them arrive. Reception sees everyone in "
                   "the building.",
        "users": ["visitors", "hosts", "the reception desk"],
        "interface": [{"method": "POST", "path": "/visits", "purpose": "a visitor signs in"},
                      {"method": "GET", "path": "/hosts/{name}/visits", "purpose": "a host's visitors"},
                      {"method": "GET", "path": "/visits/present", "purpose": "everyone in the building"},
                      {"method": "POST", "path": "/visits/{id}/sign-out", "purpose": "sign a visit out"},
                      {"method": "POST", "path": "/visits/purge", "purpose": "delete visits older than 30 days"}],
        "requirements": [
            req("A visitor signs in with their name, company and the host they visit.", ["request"],
                ac("no visits", "POST /visits with a name, a company and a host", "201 and the visit has an id"),
                ac("a visitor at the tablet", "they sign in", "201: the visit is recorded", "holdout"),
                rid="VIS-001"),
            req("The host sees that their visitor has arrived.", ["request", "Q-004"],
                ac("a visit for a host", "GET /hosts/{name}/visits", "200 and the visit is listed"), rid="VIS-002"),
            req("Reception sees everyone signed in and not yet signed out.", ["request"],
                ac("two visitors in, one out", "GET /visits/present", "200 and lists only the one still in"),
                rid="VIS-003"),
            req("A visitor or reception signs a visit out.", ["request"],
                ac("a visit", "POST /visits/{id}/sign-out", "200 and the visit is no longer present"), rid="VIS-004"),
            req("Visitor records are deleted after 30 days.", ["Q-003"],
                ac("a visit 31 days old", "POST /visits/purge", "200 and the visit is gone"), priority="should"),
        ],
        "out_of_scope": ["printing badges", "signing in with a work account"],
    },
    "holdouts": {"scenarios": [{"criterion": "VIS-001-AC-2", "steps": [post("/visits", "VIS-001-AC-1", 201)]}]},
}

# -- G4: a need in Finnish ---------------------------------------------------------------------------

FINNISH = ("Tarvitsemme palvelun, jossa taloyhtiön asukkaat jättävät vikailmoituksen lomakkeella ja näkevät, "
           "missä vaiheessa sen käsittely on.")

REPORTS = {
    "markers": ("vikailmoitu", "taloyhtiö"),
    "panel": {
        "business": [q("Kuka käsittelee vikailmoitukset ja päättää niiden kiireellisyydestä?",
                       "Se ratkaisee, kenelle ilmoitus menee.", "isännöitsijä käsittelee ja päättää kiireellisyydestä",
                       blocking=True, options=("huoltoyhtiö käsittelee kaikki ilmoitukset",))],
        "end_user": [q("Jättävätkö asukkaat ilmoituksen puhelimella?", "Se ratkaisee ensimmäisen näkymän.",
                       "kyllä: lomake toimii puhelimella")],
        "it_security": [q("Tarvitseeko asukkaan tunnistautua?", "Tunnistautuminen ratkaisee, kuka näkee mitä.",
                          "ei ensimmäisessä versiossa: asunnon numero ja puhelinnumero riittävät")],
        "operations": [q("Kuka saa tiedon kiireellisestä viasta virka-ajan ulkopuolella?",
                         "Vesivuoto ei odota aamuun.", "huoltoyhtiön päivystys")],
        "delivery": [q("Mikä on pienin ensimmäinen versio?", "Rajaus.", "ilmoituksen jättäminen ja sen tila")],
    },
    "opinions": [],
    "spec": {
        "title": "Vikailmoitukset",
        "summary": "Taloyhtiön asukas jättää vikailmoituksen lomakkeella ja näkee sen käsittelyn vaiheen.",
        "users": ["asukkaat", "isännöitsijä"],
        "interface": [{"method": "POST", "path": "/reports", "purpose": "uusi vikailmoitus"},
                      {"method": "GET", "path": "/reports/{id}", "purpose": "ilmoituksen tila"},
                      {"method": "PATCH", "path": "/reports/{id}", "purpose": "isännöitsijä päättää kiireellisyyden"}],
        "requirements": [
            req("Asukas jättää vikailmoituksen lomakkeella.", ["request"],
                ac("ei ilmoituksia", "POST /reports asunnon numerolla ja kuvauksella", "201 ja ilmoituksella on tunnus")),
            req("Asukas näkee, missä vaiheessa ilmoituksen käsittely on.", ["request"],
                ac("jätetty ilmoitus", "GET /reports/{id}", "200 ja ilmoituksen tila näkyy")),
            req("Isännöitsijä päättää ilmoituksen kiireellisyydestä.", ["Q-001"],
                ac("jätetty ilmoitus", "PATCH /reports/{id} kiireellisyydellä", "200 ja kiireellisyys on tallessa")),
        ],
        "out_of_scope": ["tunnistautuminen"],
    },
    "holdouts": {"scenarios": []},
}

# -- W: a single workflow ----------------------------------------------------------------------------

WORKFLOW = ("A workflow that routes each purchase request to its budget owner for approval and reminds the owner "
            "after two working days.")

PURCHASES = {
    "markers": ("purchase request", "budget owner"),
    "panel": {
        "business": [q("Which purchases need approval, and from whom?", "It is the workflow's one rule.",
                       "every purchase over 1,000 euros, from the cost centre's budget owner", blocking=True)],
        "end_user": [q("Where does the requester see where their request is?", "Requesters ask by email otherwise.",
                       "on the request's own page")],
        "it_security": [q("Where does the list of budget owners come from?", "A wrong owner approves the wrong spend.",
                          "a list the finance team keeps; no live link to the finance system yet")],
        "operations": [q("What happens when the budget owner is away?", "A workflow that waits on one person stops.",
                         "after the reminder the request goes to their deputy")],
        "delivery": [q("What is the smallest first version?", "Scope.",
                       "file a request, route it, approve or reject it, remind after two working days")],
    },
    "opinions": [],
    "spec": {
        "title": "Purchase approval workflow",
        "summary": "Each purchase request goes to its budget owner, who approves or rejects it; a request left "
                   "waiting for two working days reminds the owner.",
        "users": ["requesters", "budget owners", "the finance team"],
        "interface": [{"method": "POST", "path": "/requests", "purpose": "file a purchase request"},
                      {"method": "POST", "path": "/requests/{id}/decision", "purpose": "approve or reject"},
                      {"method": "POST", "path": "/reminders/run", "purpose": "remind owners of waiting requests"}],
        "requirements": [
            req("Each purchase request goes to its cost centre's budget owner.", ["request", "Q-001"],
                ac("a list of budget owners", "POST /requests with an amount and a cost centre",
                   "201 and the request names its budget owner"),
                ac("a requester", "they file a request", "201: it waits for its budget owner", "holdout")),
            req("The budget owner approves or rejects a request, with a reason for a rejection.", ["request"],
                ac("a waiting request", "POST /requests/{id}/decision approving it", "200 and the request is approved")),
            req("A request waiting for two working days reminds its budget owner.", ["request"],
                ac("a request filed three working days ago", "POST /reminders/run",
                   "200 and lists the request as reminded")),
        ],
        "out_of_scope": ["payments", "a live link to the finance system"],
    },
    "holdouts": {"scenarios": [{"criterion": "R-1-AC-2", "steps": [post("/requests", "R-1-AC-1", 201)]}]},
}

# -- A: an automation --------------------------------------------------------------------------------

AUTOMATION = ("Automate the monthly invoice summary: on the first working day of each month, collect the open "
              "invoices from the finance export and send the finance team a summary.")

INVOICES = {
    "markers": ("invoice summary", "open invoices"),
    "panel": {
        "business": [q("Who reads the monthly invoice summary, and what do they decide with it?",
                       "A report nobody acts on is noise.", "the finance team lead, to chase overdue invoices",
                       blocking=True)],
        "end_user": [],
        "it_security": [q("Where does the finance export come from, and may the automation read the finance system "
                          "directly?", "Least access.",
                          "a CSV export a person drops in its folder; no direct access to the finance system",
                          blocking=True)],
        "operations": [q("What happens when the export is missing on the first working day?",
                         "A silent automation looks like a quiet month.",
                         "the run says not measured and tells the finance team lead")],
        "delivery": [q("What is the smallest first version?", "Scope.",
                       "read one export, total the open invoices per customer, keep the summary")],
    },
    "opinions": [],
    "spec": {
        "title": "Monthly invoice summary",
        "summary": "A run reads the finance export and totals the open invoices per customer. A run with no export "
                   "says not measured.",
        "users": ["the finance team"],
        "interface": [{"method": "POST", "path": "/runs", "purpose": "run the summary over an export"},
                      {"method": "GET", "path": "/summaries/latest", "purpose": "the latest summary"}],
        "requirements": [
            req("A run totals the open invoices of an export per customer.", ["request", "Q-002"],
                ac("an export with three open invoices", "POST /runs with the export",
                   "201 and the run lists the total per customer")),
            req("A run without an export says not measured, never an empty summary.", ["Q-003"],
                ac("no export", "POST /runs without an export", "422 and the run says not measured")),
            req("The finance team reads the latest summary.", ["Q-001"],
                ac("a finished run", "GET /summaries/latest", "200 and the summary of that run")),
        ],
        "out_of_scope": ["reading the finance system directly", "sending email"],
    },
    "holdouts": {"scenarios": []},
}

# -- C1: an agentic capability: an assistant -------------------------------------------------------

ASSISTANT = ("An assistant that answers employees' questions about the travel policy and cites the paragraph each "
             "answer rests on.")

TRAVEL = {
    "markers": ("travel policy",),
    "panel": {
        "business": [q("Which questions may it answer alone, and which go to a person?",
                       "What the agent may decide alone.",
                       "questions the travel policy answers; anything about one person's own claim goes to HR")],
        "end_user": [q("Where do employees ask: the intranet, chat or email?", "It decides where it runs.",
                       "a chat box on the intranet's travel page")],
        "it_security": [q("What may the travel policy assistant read?", "Least access.",
                          "only the published travel policy; no employee records")],
        "operations": [q("Who updates the policy text when it changes?", "Answers must follow the current policy.",
                         "HR publishes the new version; earlier answers keep the version they cited")],
        "delivery": [q("Which questions prove it works?", "Trials.",
                       "twenty real questions from last year, each with the paragraph that answers it")],
    },
    "opinions": [],
    "spec": {
        "title": "Travel policy assistant",
        "summary": "Answers employees' questions from the published travel policy and cites the paragraph. "
                   "Personal claims go to HR.",
        "users": ["employees", "HR"],
        "interface": [{"method": "POST", "path": "/questions", "purpose": "ask a question"}],
        "requirements": [
            req("The assistant answers a question about the travel policy and cites the paragraph it rests on.",
                ["request"],
                ac("the published policy", "POST /questions asking for the daily allowance abroad",
                   "200 and the answer names its paragraph"),
                ac("an employee", "they ask a policy question", "200: answered with its paragraph", "holdout")),
            req("A question about one person's own claim is passed to HR, not answered.", ["Q-001"],
                ac("a question about the asker's own claim", "POST /questions about a claim",
                   "202 and the question is passed to HR")),
            req("The assistant answers only from the published travel policy.", ["Q-003"],
                ac("a question the policy does not answer", "POST /questions about something else",
                   "422 and says it answers only from the travel policy")),
        ],
        "out_of_scope": ["employee records", "approving claims"],
    },
    "holdouts": {"scenarios": [{"criterion": "R-1-AC-2", "steps": [post("/questions", "R-1-AC-1", 200)]}]},
}

# -- B: developing an adopted service further -----------------------------------------------------------

LOW_STOCK = "We also need a low-stock list: every item whose level is below the threshold."
STOCK_AMENDMENT = {"modify": [], "withdraw": [], "add": [
    {"statement": "Items whose level is below a threshold are listed as low stock.",
     "acceptance": [{"given": "levels of 1 drill and 9 ladders", "when": "low_stock(levels, 3) is called",
                     "then": "it returns the drill only", "kind": "test"}]}]}

# -- C2 and I: the demo's ops agent and integration ------------------------------------------------------

def _demo_need(key: str, markers: tuple, holdouts: dict) -> dict:
    """One of the demo's requests as the matrix runs it: the demo's panel, opinions and spec, and
    holdout scenarios the matrix's builder can meet (the demo's own expect data its cell writes)."""
    return {"markers": markers, "panel": demo.PANELS[key], "opinions": demo.OPINIONS[key],
            "spec": demo.SPECS[key], "holdouts": holdouts}


ACCESS = _demo_need(demo.ACCESS, ("access review", "access list"),
                    {"scenarios": [{"criterion": "R-1-AC-2", "steps": [post("/checks", "R-1-AC-1", 200)]}]})
WEBHOOK = _demo_need(demo.WEBHOOK, ("webhook", "shipment"), {"scenarios": []})

NEEDS: dict[str, dict[str, Any]] = {"rooms": ROOMS, "queue": QUEUE, "visitors": VISITORS, "reports": REPORTS,
                                    "purchases": PURCHASES, "invoices": INVOICES, "travel": TRAVEL,
                                    "access": ACCESS, "webhook": WEBHOOK}
TEXTS = {"rooms": ONE_LINE, "queue": TWO_LINE, "visitors": WRITTEN, "reports": FINNISH, "purchases": WORKFLOW,
         "invoices": AUTOMATION, "travel": ASSISTANT, "access": demo.REQUESTS[demo.ACCESS],
         "webhook": demo.REQUESTS[demo.WEBHOOK]}
