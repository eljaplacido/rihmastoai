"""Work profiles: what kind of work a project is, so the factory asks, checks and shows the right things.

Rihma is used for very different work: a web service, an integration between systems, a fast
mobile prototype, an ML or data pipeline, an agentic workflow, or the engineering of an agent
harness itself. The governance core is the same for every profile: canon, Inbox, contract, gate,
holdouts, ledger. A profile changes only what sits around that core:

- **intake:** what each panel perspective should also weigh, and a few questions asked once;
- **spec:** guidance on criteria and checks (for example an ML model's eval threshold as a test,
  its hidden eval set as a holdout);
- **roads:** where a release lands;
- **cockpit:** extra widgets, and the words people in that field use.

A profile is proposed by rule from the request (no model) and a person may choose another. When
the rule is not sure (few of a profile's words, or two profiles close), the proposal says it is
uncertain and names the candidates a person should choose from. Each
profile says honestly which product template it builds on today (`template`) and whether it is
`ready` or a `preview` (its intake, spec and checks are shaped, its own template is still to come).
"""

from __future__ import annotations

import re
from typing import Any

# Each profile is a JSON-like record the cockpit serves as is (`public`); `note` is optional.
PROFILES: dict[str, dict[str, Any]] = {
    "web_service": {
        "deliverable": "product", "label": "Web app or service", "icon": "globe", "status": "ready", "template": "web-service",
        "summary": "A web application or HTTP service with screens and an API.",
        "keywords": ["web", "app", "portal", "dashboard", "page", "form", "api", "service", "crud", "booking",
                     "sivusto", "palvelu", "lomake"],
        "panel_focus": {
            "end_user": "the screens and the everyday tasks on them",
            "it_security": "identity, roles and where the data lives",
        },
        "seed_questions": [],
        "screens": True,
        "spec_guidance": "Most criteria are unit tests through handle(); the key user journeys are holdouts "
                         "against the running service.",
        "widgets": ["try_it", "releases"],
        "vocabulary": {},
    },
    "integration": {
        "deliverable": "product", "label": "Integration or connector", "icon": "plug", "status": "ready", "template": "web-service",
        "summary": "Moves data or events between systems: webhooks, polling, mapping, retries.",
        "keywords": ["integration", "integrate", "connector", "webhook", "sync", "etl", "feed", "adapter", "erp",
                     "crm", "sap", "event", "queue", "carrier", "interface", "rajapinta", "integraatio"],
        "panel_focus": {
            "it_security": "every system involved, its authentication, and the data each message carries",
            "operations": "retries, dead letters, idempotency, feed freshness and who is alerted",
            "delivery": "which upstream systems can be simulated for tests",
        },
        "seed_questions": [
            {"text": "Which systems does this connect, and which of them can we call in tests?",
             "perspective": "it_security",
             "proposed": "simulate every external system in tests; call real systems only on staging",
             "options": ["simulate every external system in tests; call real systems only on staging",
                         "use the vendors' sandboxes in tests", "record real traffic once and replay it"]},
            {"text": "What happens to a message that cannot be delivered?", "perspective": "operations",
             "proposed": "retry with backoff, then park it in a dead-letter list a person can replay",
             "options": ["retry with backoff, then park it in a dead-letter list a person can replay",
                         "drop it and log an error", "stop the whole feed until someone fixes it"]},
        ],
        "screens": False,
        "spec_guidance": "Give each upstream system a contract test against a recorded or simulated message, "
                         "test idempotency (the same message twice is processed once) and the dead-letter path, "
                         "and make the end-to-end flow through a simulator a holdout. Feed freshness is a probe.",
        "widgets": ["feed_health"],
        "vocabulary": {"release": "release", "user": "connected system"},
    },
    "mobile_prototype": {
        "deliverable": "product", "label": "Mobile app prototype", "icon": "smartphone", "status": "preview", "template": "web-service",
        "summary": "A fast phone-first prototype to show or test an idea, installable as a web app.",
        "keywords": ["mobile", "phone", "ios", "android", "app store", "prototype", "pwa", "offline",
                     "mobiili", "puhelin", "sovellus"],
        "panel_focus": {
            "end_user": "the three screens that carry the idea, one-handed use, and offline moments",
            "delivery": "what the prototype must prove, and to whom, by when",
        },
        "seed_questions": [
            {"text": "Who sees the prototype first, and on what device?", "perspective": "business",
             "proposed": "the owner and three test users, on their own phones, through a link",
             "options": ["the owner and three test users, on their own phones, through a link",
                         "a demo on one phone in a meeting", "a public test group"]},
        ],
        "screens": True,
        "spec_guidance": "Design phone-first (390 px wide). Each key screen is reachable and usable at that "
                         "width; make the main journey a holdout. A prototype needs no production hardening.",
        "widgets": ["try_it", "releases"],
        "vocabulary": {"release": "build"},
        "note": "Delivered as an installable web app (phone-first); a native template is not built yet.",
    },
    "ml_pipeline": {
        "deliverable": "capability_pack", "label": "ML or data pipeline", "icon": "brain", "status": "preview", "template": "web-service",
        "summary": "Trains, evaluates or serves a model, or transforms data, with metrics that must hold.",
        "keywords": ["machine learning", "ml", "model", "train", "dataset", "classifier", "regression", "predict",
                     "forecast", "embedding", "eval", "accuracy", "f1", "pipeline", "data", "analytics",
                     "koneoppiminen", "malli", "ennuste"],
        "panel_focus": {
            "business": "the metric that decides success, its threshold and today's baseline",
            "it_security": "where the data comes from, its licence, personal data and retention",
            "delivery": "the train, validation and hidden test split, and how runs are reproduced",
        },
        "seed_questions": [
            {"text": "Which metric decides whether the model is good enough, and at what threshold?",
             "perspective": "business", "proposed": "a metric and threshold agreed with the owner, against today's baseline",
             "options": ["a metric and threshold agreed with the owner, against today's baseline",
                         "beat the current baseline by any margin", "no threshold yet: explore first"]},
            {"text": "Which data may be used, and does it hold personal data?", "perspective": "it_security",
             "proposed": "only data the owner provides, with personal data removed before training",
             "options": ["only data the owner provides, with personal data removed before training",
                         "public data with a known licence", "synthetic data only"]},
        ],
        "screens": False,
        "spec_guidance": "State the metric and its threshold in a criterion and check it as a test on a fixed "
                         "evaluation set. Keep a hidden test set as a holdout: the builder never sees it, which "
                         "is exactly what holdout custody is for. Record the data's source and version.",
        "widgets": ["eval_trend"],
        "vocabulary": {"release": "model version", "criterion": "metric"},
        "note": "The model is served behind the web-service template; a training template is not built yet.",
    },
    "agentic_workflow": {
        "deliverable": "capability_pack", "label": "Agent or assistant", "icon": "bot", "status": "preview", "template": "web-service",
        "summary": "An AI agent, assistant or multi-step workflow: inside an app or standalone for a process, using tools, with people approving what matters.",
        "keywords": ["agent", "agentic", "workflow", "assistant", "chatbot", "copilot", "llm", "rag", "tool use",
                     "automation", "orchestrat", "agentti", "avustaja"],
        "panel_focus": {
            "business": "what the agent may decide alone and what needs a person",
            "it_security": "the tools and data the agent may touch, and what it must refuse",
            "operations": "cost per run, failure budget, and how a bad run is stopped",
        },
        "seed_questions": [
            {"text": "Which of the agent's actions need a person's approval?", "perspective": "business",
             "proposed": "anything that sends, pays, deletes or changes another system",
             "options": ["anything that sends, pays, deletes or changes another system",
                         "nothing: it only drafts", "only payments"]},
        ],
        "screens": False,
        "spec_guidance": "Write scenarios as trials: given an input, the workflow reaches the goal. Add refusal "
                         "criteria (it must refuse a forbidden action) and a cost-per-run limit as a probe. Make "
                         "the hardest trials holdouts.",
        "widgets": ["eval_trend"],
        "vocabulary": {"criterion": "trial"},
        "note": "Run as a service on the web-service template; a Gnomon-surface template is planned.",
    },
    "harness_engineering": {
        "deliverable": "capability_pack", "label": "Harness engineering", "icon": "flask", "status": "preview", "template": "web-service",
        "summary": "Builds or tunes an agent harness, policy or evaluation suite, measured against a baseline.",
        "keywords": ["harness", "benchmark", "evaluation suite", "evals", "policy", "guardrail", "prompt",
                     "system prompt", "surface", "skill", "gnomon", "red team", "jailbreak"],
        "panel_focus": {
            "business": "which behaviour must change and how the change is measured against a baseline",
            "delivery": "the benchmark or trial set, seeded defects, and the regression budget",
        },
        "seed_questions": [
            {"text": "What is the baseline, and how much regression elsewhere is acceptable?",
             "perspective": "delivery", "proposed": "today's harness on the same trial set; no regression on any trial",
             "options": ["today's harness on the same trial set; no regression on any trial",
                         "a small regression on unrelated trials is acceptable", "no baseline yet"]},
        ],
        "screens": False,
        "spec_guidance": "Every claim is a delta against a named baseline on a fixed trial set. Seed known defects "
                         "and require that the checks catch them. Keep part of the trial set as holdouts.",
        "widgets": ["eval_trend", "models"],
        "vocabulary": {"criterion": "trial", "release": "surface version"},
        "note": "Gnomon's own trial specs and `gnomon improve` are the natural engine here; a surface template is planned.",
    },
    "ops_agent": {
        "deliverable": "report", "label": "Ops agent: report with evidence", "icon": "shield", "status": "preview",
        "template": "web-service",
        "summary": "An agent that does a job and proves it: a compliance check (AI Act, GDPR, NIS2), a security "
                   "scan, a log analysis or a maintenance report, delivered as a report with an evidence pack.",
        "keywords": ["ai act", "gdpr", "nis2", "compliance", "audit", "security scan", "vulnerability", "cve",
                     "log analysis", "logs", "incident report", "maintenance report", "evidence", "tietosuoja",
                     "auditointi", "lokianalyysi"],
        "panel_focus": {
            "business": "which decision the report supports and who signs it off",
            "it_security": "which systems, logs or configurations the agent may read, and nothing more",
            "operations": "how often it runs and who acts on a finding",
        },
        "seed_questions": [
            {"text": "Which framework or checklist must the report follow, and who signs it off?",
             "perspective": "business", "proposed": "the framework the owner names, signed off by a named compliance owner",
             "options": ["the framework the owner names, signed off by a named compliance owner",
                         "an internal checklist only", "no sign-off: information only"]},
            {"text": "What may the agent read?", "perspective": "it_security",
             "proposed": "read-only exports a person provides; no live access to production systems",
             "options": ["read-only exports a person provides; no live access to production systems",
                         "read-only access to named systems", "live access with approval per run"]},
        ],
        "screens": False,
        "spec_guidance": "Each finding in the report cites the evidence it rests on (a log line, a configuration, a "
                         "document). State what was not checked as not measured, never as passed. Seed known "
                         "findings in a test fixture and require that the agent reports them.",
        "widgets": ["evidence_packs"],
        "vocabulary": {"release": "report", "criterion": "check"},
        "note": "Mode B of the capability layer: the factory's own agents do the work and deliver the proof.",
    },
}

DELIVERABLES = {
    "product": "a deployable product: an app, a service or an integration",
    "capability_pack": "a capability pack: agent, harness, prompts, tools and pinned models, with its evals",
    "report": "a report with an evidence pack, produced by an ops agent",
}

DEFAULT_PROFILE = "web_service"
_WORD = re.compile(r"[a-zåäö0-9]+")
# The confidence rule. A best score under CLEAR_SCORE rests on too few words to be sure; a lead of
# less than CLEAR_LEAD keywords over the runner-up is too close to call. Either way the proposal
# is uncertain, and names the profiles a person should choose from (at most MAX_CANDIDATES).
CLEAR_SCORE = 2
CLEAR_LEAD = 2
MAX_CANDIDATES = 4
PROFILE_QUESTION = "Which kind of work is this?"


def _uncertainty(scores: dict[str, list[str]], ranked: list[str]) -> str | None:
    """Why a proposal is uncertain, or None when it is clear."""
    best, runner = ranked[0], ranked[1]
    top, second = len(scores[best]), len(scores[runner])
    if top == 0:
        return "no keyword stood out: the default is a guess"
    if top < CLEAR_SCORE:
        return f"only one keyword names it ({', '.join(scores[best])})"
    if top - second < CLEAR_LEAD:
        return (f"{PROFILES[runner]['label']} scores {second} against {top}: too close to call"
                if second < top else f"{PROFILES[runner]['label']} scores the same ({top}): a tie")
    return None


def propose_profile(text: str) -> dict:
    """The profile whose keywords the request names most, by rule; web service when nothing stands out.

    A low best score, or a best score close to the runner-up's, is **uncertain**: the proposal says
    so (`confidence`, `uncertain_because`) and names the top `candidates`, for a person to choose
    from (`profile_question`). A clear proposal's only candidate is itself."""
    low = (text or "").lower()
    words = set(_WORD.findall(low))
    scores = {}
    for pid, p in PROFILES.items():
        hits = sorted({k for k in p["keywords"] if (k in words if " " not in k and len(k) <= 4 else k in low)})
        scores[pid] = hits
    # Highest score first; a tie keeps the default, then the catalogue's order.
    ranked = sorted(PROFILES, key=lambda pid: (-len(scores[pid]), pid != DEFAULT_PROFILE))
    best = ranked[0]
    why = _uncertainty(scores, ranked)
    top = len(scores[best])
    candidates = [pid for pid in ranked if top - len(scores[pid]) < CLEAR_LEAD][:MAX_CANDIDATES] if why else [best]
    return {"profile": best, "basis": scores[best] or ["no keyword stood out: the default"],
            "scores": {k: len(v) for k, v in scores.items()}, "confidence": "uncertain" if why else "clear",
            "uncertain_because": why, "candidates": candidates}


def profile_question(proposal: dict) -> dict | None:
    """The question an uncertain proposal puts to a person: which kind of work this is, with the top
    candidates as options. It carries no proposed answer, so no mode assumes it. None when the
    proposal is clear."""
    if proposal.get("confidence") != "uncertain":
        return None
    label = PROFILES[proposal["profile"]]["label"]
    return {"text": PROFILE_QUESTION, "perspective": "business", "blocking": False,
            "options": [f"{PROFILES[pid]['label']} ({pid})" for pid in proposal["candidates"]][:MAX_CANDIDATES],
            "rationale": f"The work profile was proposed by rule as {label}, but {proposal['uncertain_because']}. "
                         "The profile shapes the panel's questions, the spec's guidance and what is delivered."}


def add_profile_question(canon: Any, proposal: dict) -> dict | None:
    """Add an uncertain proposal's question to the canon, with no proposed answer: intake's settling
    puts such a question to a person. Returns the question, or None when the proposal is clear."""
    q = profile_question(proposal)
    if q is None:
        return None
    return dict(canon.add_question(q["text"], q["perspective"], blocking=q["blocking"], rationale=q["rationale"],
                                   options=q["options"]))


def profile_of(project) -> dict:
    pid = project.meta.get("profile") or DEFAULT_PROFILE
    return {"id": pid, **PROFILES.get(pid, PROFILES[DEFAULT_PROFILE])}


def choose(project, profile: str, *, basis) -> dict:
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {', '.join(PROFILES)}, got {profile!r}")
    project.update_meta(profile=profile)
    project.log("profile_chosen", {"profile": profile, "basis": basis})
    return profile_of(project)


def panel_focus(profile: dict, perspective: str) -> str:
    focus = profile.get("panel_focus", {}).get(perspective)
    return f"\nThis is a **{profile['label']}** project. From your perspective, also weigh {focus}.\n" if focus else \
        f"\nThis is a **{profile['label']}** project.\n"


def spec_guidance(profile: dict) -> str:
    return f"\nThis is a **{profile['label']}** project ({profile['summary']}) {profile['spec_guidance']}\n"


def public(profile_id: str | None = None) -> dict | list:
    """What the cockpit shows about profiles: everything but the keyword lists."""
    def view(pid, p):
        return {"id": pid, **{k: v for k, v in p.items() if k != "keywords"}}
    if profile_id:
        return view(profile_id, PROFILES[profile_id])
    return [view(pid, p) for pid, p in PROFILES.items()]
