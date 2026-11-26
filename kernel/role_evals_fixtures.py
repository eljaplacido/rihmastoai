"""The neutral fixtures of Rihmasto's own evals of its agents (FR-EVL1, kernel/role_evals.py).

Every need, requirement, question and goal here is made up for the evals: no customer's words, no project's data.
Each case says what a good answer has, so a rule can judge it without a model.
"""

from __future__ import annotations

from typing import Any

# The analyst reading a need from the business perspective: what its questions should touch.
NEEDS: list[dict[str, Any]] = [
    {"id": "N-1", "text": "A board-game café wants guests to reserve a table and a game for an evening, and staff to "
                          "see tonight's reservations on a tablet.",
     "topics": ("how many", "cancel", "deposit", "staff", "guest", "who", "time", "table", "no-show", "pay")},
    {"id": "N-2", "text": "A community garden wants members to book shared tools and see who has which tool.",
     "topics": ("member", "late", "return", "damage", "who", "how long", "overdue", "notify", "deposit")},
    {"id": "N-3", "text": "A cycling club wants to publish weekend rides and let riders sign up, with a limit per "
                          "ride.",
     "topics": ("limit", "waiting", "cancel", "leader", "weather", "who", "pay", "level", "notify")},
]

# Requirements the analyst writes acceptance criteria for: are they testable?
REQUIREMENTS: list[dict[str, Any]] = [
    {"id": "S-1", "text": "A guest can reserve a table for a date and a party size; a full evening is refused."},
    {"id": "S-2", "text": "A member returns a borrowed tool, and the tool shows as available again."},
    {"id": "S-3", "text": "A rider signs up for a ride; once the ride is full, the next rider is put on a waiting "
                          "list."},
]
VAGUE = ("user-friendly", "user friendly", "intuitive", "easy", "fast", "quickly", "appropriate", "properly",
         "correctly", "seamless", "nice", "good", "etc", "as expected", "works")
OBSERVABLE = (r"\b\d{3}\b", r"\b\d+\b", r"\breturn", r"\bshow", r"\bdisplay", r"\brefus", r"\breject", r"\bis "
              r"(?:listed|recorded|saved|marked|added|removed|available|on)\b", r"\berror\b", r"\bmessage\b",
              r"\bstatus\b", r"\bcontains?\b", r"\bequals?\b", r"\bsees?\b", r"\bgets?\b", r"\breceives?\b",
              r'"[^"]+"', r"\bwaiting list\b", r"\bavailable\b")

# Ask Rihma over a fixed snapshot: where things are (map), how things stand (status), how to do something (how-to).
SNAPSHOT: dict[str, Any] = {"factory": {     # the shape of kernel/assistant_snapshot.py snapshot()
    "projects": [{"id": "cafe-tables", "title": "Café tables", "stage": 4, "maturity": "demo", "paused": False,
                  "now": {"health": "on_track", "reasons": []}, "latest_release": None},
                 {"id": "tool-shed", "title": "Tool shed", "stage": 7, "maturity": "production", "paused": False,
                  "now": {"health": "at_risk", "reasons": ["a probe failed in production"]},
                  "latest_release": {"release": 3, "state": "done", "deployed_to": "production"}}],
    "in_production": ["tool-shed"], "gates": {"first_round_rate": 75},
    "waiting": {"total": 5, "yours": 3, "yours_by_project": {"cafe-tables": 2, "tool-shed": 1}},
    "waiting_cards": [{"project": "cafe-tables", "id": "C-0004", "kind": "approval", "yours": True},
                      {"project": "tool-shed", "id": "C-0002", "kind": "change", "yours": True}],
    "capabilities": {"counts": {"in_use": 1}, "in_use": ["Tool shed"]}, "models": []}}
QUESTIONS: list[dict[str, Any]] = [
    {"id": "A-1", "kind": "map", "q": "Where do I decide the cards that wait on me?",
     "route_ends": ("/inbox", "#/inbox"), "controls": ("decide",), "words": ("inbox", "decisions")},
    {"id": "A-2", "kind": "map", "q": "Where can I see each project's checks and their last results?",
     "route_ends": ("/checks", "#/health"), "controls": ("health_run", "health_enable"), "words": ("health",)},
    {"id": "A-3", "kind": "status", "q": "How many decisions wait on me?", "figures": ("3",)},
    {"id": "A-4", "kind": "status", "q": "Which project runs in production?", "figures": ("tool shed", "tool-shed")},
    {"id": "A-5", "kind": "status", "q": "Why is the tool shed at risk?", "figures": ("probe",)},
    {"id": "A-6", "kind": "howto", "q": "How do I pause a project?", "controls": ("pause",), "words": ("pause",)},
    {"id": "A-7", "kind": "howto", "q": "How do I export the evidence pack?", "controls": ("export_evidence",),
     "words": ("evidence",)},
]

# Goal help: a goal and the facts of a made-up project; a valid plan has steps the cockpit can take.
GOALS: list[dict[str, Any]] = [
    {"id": "G-1", "goal": "Run it every night and tell us when it fails"},
    {"id": "G-2", "goal": "Monitor it and alert operations when it is down"},
    {"id": "G-3", "goal": "Audit this project with Gnomon every week"},
]
FACTS: dict[str, Any] = {"pid": "fixture-project", "title": "Tool shed", "stage": 7, "stage_name": "operate",
                         "profile": "service", "maturity": "pilot", "posture": None, "confidential": False,
                         "source_kind": "attached", "contract": True, "waits_for": None, "next": [],
                         "integrations": [], "paved_road": None}
