"""Lenses: the same project, seen for a purpose; and the views a project's phase brings forward.

A lens answers one viewpoint's question:
- **business:** what is coming, when, and what does it need from me;
- **concept:** what we assume and what the plan says;
- **delivery:** how the run is going and why something failed;
- **operations:** what runs in production and whether it is healthy;
- **compliance:** what ran, which versions, who approved, and the evidence that it was checked;
- **insight:** how the factory itself performs and what it has learned.

Each persona starts in its own lens and may switch. Within a project, the current stage brings
its views forward: questions at stage 2, the plan at 4, the live run at 5, the try-it list at 6,
releases at 7.
"""

from __future__ import annotations

from typing import TypedDict


class Lens(TypedDict):
    """One viewpoint: its name and icon, the question it answers, its widgets and its views."""

    label: str
    icon: str
    question: str
    widgets: list[str]
    views: list[str]


LENSES: dict[str, Lens] = {
    "business": {"label": "Business", "icon": "briefcase",
                 "question": "What is coming, when, and what does it need from me?",
                 "widgets": ["decisions", "pipeline", "health", "forecast", "coverage", "activity"],
                 "views": ["overview", "inbox", "changes", "spec", "releases", "outputs"]},
    "concept": {"label": "Concept", "icon": "lightbulb",
                "question": "What do we assume, and what does the plan say?",
                "widgets": ["decisions", "questions", "assumptions", "alignment", "coverage"],
                "views": ["questions", "assumptions", "plan", "spec", "inbox"]},
    "delivery": {"label": "Delivery", "icon": "hammer",
                 "question": "How is the run going, and why did something fail?",
                 "widgets": ["live", "gate_trend", "timeline", "board", "decisions", "activity"],
                 "views": ["tasks", "cell", "spec", "inbox", "ledger", "outputs"]},
    "operations": {"label": "Operations", "icon": "activity",
                   "question": "What runs in production, and is it healthy?",
                   "widgets": ["releases", "health", "incidents", "activity"],
                   "views": ["releases", "inbox", "ledger", "overview"]},
    "compliance": {"label": "Compliance", "icon": "shield",
                   "question": "Can we show what ran, which versions, who approved, and that it was checked?",
                   "widgets": ["evidence_packs", "decisions", "autonomy", "coverage", "activity"],
                   "views": ["ledger", "releases", "spec", "inbox"]},
    "insight": {"label": "Insight", "icon": "sparkles",
                "question": "How does the factory itself perform, and what has it learned?",
                "widgets": ["decisions", "gate_trend", "models", "coverage", "pipeline", "lessons"],
                "views": ["agentops", "overview", "cell", "ledger"]},   # Agent operations first (FR-AOP1)
}

PERSONA_LENS = {"business_owner": "business", "stakeholder": "business", "product_owner": "concept",
                "concept_evaluator": "concept", "end_user": "business", "developer": "delivery",
                "it": "operations", "operations": "operations", "compliance": "compliance",
                "ai_architect": "insight"}   # the AI architect: how the agents perform and cost (FR-AOP1)

STAGE_FOCUS = {1: ["questions", "overview"], 2: ["questions", "assumptions"], 3: ["spec", "questions"],
               4: ["plan", "spec"], 5: ["tasks", "live", "spec"], 6: ["try", "inbox", "releases"],
               7: ["releases", "changes", "outputs"]}


def lens_for(persona: str, requested: str | None = None) -> str:
    if requested in LENSES:
        return requested
    return PERSONA_LENS.get(persona, "business")


def project_context(project, persona: str, lens: str | None = None) -> dict:
    """Which lens is active, and the views in the order this project's phase and that lens bring
    them forward. The stage's own focus comes first, then the lens's views."""
    name = lens_for(persona, lens)
    stage = project.meta.get("stage", 1)
    order = []
    for v in STAGE_FOCUS.get(stage, []) + LENSES[name]["views"]:
        if v not in order:
            order.append(v)
    from kernel.profiles import profile_of

    profile = profile_of(project)
    widgets = LENSES[name]["widgets"] + [w for w in profile.get("widgets", []) if w not in LENSES[name]["widgets"]]
    return {"lens": name, "label": LENSES[name]["label"], "question": LENSES[name]["question"],
            "profile": {k: profile.get(k) for k in ("id", "label", "icon", "status", "template", "summary", "note",
                                                    "vocabulary")},
            "widgets": widgets, "stage": stage, "focus": STAGE_FOCUS.get(stage, []),
            "views": order, "lenses": {k: {"label": v["label"], "icon": v["icon"], "question": v["question"]}
                                       for k, v in LENSES.items()}}
