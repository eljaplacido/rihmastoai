"""The cockpit assistant: ask where something is, what it means, how a run is going. It can propose
actions, but never takes one.

- **Navigation** comes from `cockpit/ui_map.json`, the cockpit's own map of views and controls. A
  "where is…" question is answered from the map even without a model.
- **Answers** come only from a snapshot of the real read models: now, health, the decision queue,
  the evidence, the timeline, live. They cite the records they rest on. What is not in the
  snapshot, the assistant says it cannot see.
- **Actions** are proposals. Each one is checked against the same rules as the Inbox (who may
  decide what, which verdicts a card takes) before a person sees it. It runs only when that person
  confirms in the cockpit, signed with their name. The assistant itself writes nothing.
- **Model calls** go through Gnomon, in the analyst lane, as the `assistant` role (D-0005).
"""

from __future__ import annotations

import copy
import json
import re

from kernel.canon import CARD_DECIDERS, CARD_VERDICTS, Canon
from kernel.model import ModelError, extract_json
from kernel.store import REPO_ROOT

UI_MAP_FILE = REPO_ROOT / "cockpit" / "ui_map.json"
ACTIONS = {
    "open": ("route",),
    "answer_question": ("question", "text"),
    "let_rihma_assume": ("question",),
    "decide": ("card", "verdict", "reason"),
    "pause": ("reason",),
    "resume": (),
    "report_change": ("text",),
    "comment": ("target_kind", "target_id", "text"),
    # Reshaping the cockpit, within its modular boundaries: the layout schema, the widget library,
    # and the theme's tokens. The person sees a preview and keeps it or not.
    "layout_edit": ("ops",),
    "theme": ("settings",),
    "create_embed": ("kind", "origins"),
}
LAYOUT_OPS = ("add", "remove", "resize", "move", "set_view", "set_filter")
SIZES = ("S", "M", "L", "XL")
VIEWS = ("chart", "table", "list")
THEME = {"accent": ("amber", "teal", "violet", "blue", "green", "rose"), "density": ("comfortable", "compact"),
         "mode": ("dark", "light", "system"), "radius": ("soft", "crisp")}
FONT_SCALE = (0.9, 1.25)


def check_layout_ops(ops, widgets: list) -> str | None:
    """None if every operation stays inside the layout schema and the widget library."""
    if not isinstance(ops, list) or not ops or len(ops) > 12:
        return "ops is a list of 1 to 12 operations"
    for o in ops:
        if not isinstance(o, dict) or o.get("op") not in LAYOUT_OPS:
            return f"each op is one of {LAYOUT_OPS}"
        if o.get("widget") not in widgets:
            return f"unknown widget {o.get('widget')!r}"
        if o["op"] == "resize" and o.get("size") not in SIZES:
            return f"size is one of {SIZES}"
        if o["op"] == "set_view" and o.get("view") not in VIEWS:
            return f"view is one of {VIEWS}"
        if o["op"] == "move" and not isinstance(o.get("to"), int):
            return "move needs an integer position 'to'"
        if o["op"] == "set_filter" and not isinstance(o.get("filter"), dict):
            return "set_filter needs a 'filter' object"
    return None


def check_theme(settings) -> str | None:
    if not isinstance(settings, dict) or not settings:
        return "settings is a non-empty object"
    for k, v in settings.items():
        if k == "font_scale":
            if not isinstance(v, (int, float)) or not FONT_SCALE[0] <= v <= FONT_SCALE[1]:
                return f"font_scale is between {FONT_SCALE[0]} and {FONT_SCALE[1]}"
        elif k not in THEME or v not in THEME[k]:
            return f"{k} is not a theme setting, or {v!r} is not one of its values"
    return None
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "is", "are", "where", "can", "i", "find", "how", "do", "to", "of", "what", "does",
         "this", "my", "me", "for", "in", "on", "it", "and", "or", "which", "see", "show", "go", "get", "there"}


def ui_map() -> dict:
    return json.loads(UI_MAP_FILE.read_text(encoding="utf-8"))


def _words(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def find_in_map(question: str, *, limit: int = 3) -> list:
    """Views and controls whose label, synonyms or purpose share words with the question."""
    q = _words(question)
    scored = []
    m = ui_map()
    for kind, items in (("view", m["views"]), ("control", m["controls"])):
        for it in items:
            label = _words(it["label"])
            syn = set().union(*[_words(s) for s in it.get("synonyms", [])]) if it.get("synonyms") else set()
            text = _words(it.get("purpose") or it.get("does") or "")
            score = 3 * len(q & label) + 2 * len(q & syn) + len(q & text)
            phrase = any(s in question.lower() for s in it.get("synonyms", []) if " " in s)
            score += 3 if phrase else 0
            if score:
                scored.append((score, kind, it))
    scored.sort(key=lambda x: -x[0])
    return [{"kind": k, **it} for _, k, it in scored[:limit]]


def snapshot(factory, *, project=None) -> dict:
    """A picture of what the assistant may talk about. Nothing outside it is known. The prompt
    carries it through `fit_snapshot`, which keeps it within its budget by whole items."""
    from kernel.dashboard import queue
    from kernel.projections import floor
    from kernel.status import evidence, health, live, now

    snap = {"factory": {"projects": [{"id": p.pid, "title": p.meta.get("title"), "stage": p.meta.get("stage"),
                                      "now": now(p)} for p in factory.projects() if not p.pid.startswith("_")],
                        "gates": floor(factory)["gates"], "waiting": queue(factory)["by_kind"]}}
    if project is not None:
        canon = Canon(project)
        ev = evidence(project) if project.path("contract.json").exists() else []
        counts = {}
        for e in ev:
            counts[e["state"]] = counts.get(e["state"], 0) + 1
        tasks = project.read("tasks.json", {}) or {}
        snap["project"] = {
            "id": project.pid, "title": project.meta.get("title"), "maturity": project.meta.get("maturity"),
            "stage": project.meta.get("stage"), "now": now(project), "health": health(project),
            "evidence": counts, "live": live(project),
            "tasks": {t: {"status": s.get("status"), "rounds": len(s.get("rounds", []))} for t, s in tasks.items()},
            "open_cards": [{"id": c["id"], "kind": c["kind"], "title": c["title"][:120], "verdicts": c["verdicts"],
                            "deciders": c["deciders"]} for c in canon.cards()],
            "open_questions": [{"id": q["id"], "text": q["text"][:160], "options": q.get("options", []),
                                "blocking": q["blocking"]} for q in canon.questions("open")],
        }
    return snap


# The snapshot as the model reads it: at most this many characters of JSON (FR-Z1-AC-4).
SNAPSHOT_BUDGET = 12_000
LAYOUT_BUDGET = 3_000
# What the snapshot sheds, least needed first: whole items from the end of these lists, at most
# `most` kept in any case: (section, key, how "not_shown" names them, most).
_SHED_ITEMS: tuple[tuple[str, str, str, int | None], ...] = (
    ("factory", "projects", "projects in the factory list", None), ("project", "tasks", "tasks", None),
    ("project", "open_questions", "open questions", 6), ("project", "open_cards", "open cards", 10))
# Then whole sections, if the lists were not enough.
_SHED_SECTIONS = (("project", "live", "the project's live run"), ("factory", "gates", "the factory's gates"),
                  ("factory", "waiting", "what waits in the factory"), ("project", "health", "the project's health"))


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _over(snap: dict, not_shown: list[str], budget: int) -> int:
    """How many characters the snapshot is over its budget, with room for its "not_shown" key."""
    return _size(snap) + (_size(not_shown) + 15 if not_shown else 0) - budget


def _shed(items: list | dict, excess: int) -> None:
    """Drop whole items from the end of ``items`` until about ``excess`` characters are gone."""
    gone = 0
    while items and gone < excess:
        if isinstance(items, dict):
            key, value = items.popitem()
            gone += _size(key) + _size(value) + 4
        else:
            gone += _size(items.pop()) + 2


def _fit_list(out: dict, items: list | dict, label: str, total: int, not_shown: list[str], budget: int) -> None:
    """Shed whole items while the snapshot, with the note that says so, is over budget; then add
    that note to ``not_shown`` if any of the ``total`` items are gone."""
    note = [f"{total} of {total} {label}"]  # as long as its note can be
    while items and _over(out, not_shown + (note if len(items) < total else []), budget) > 0:
        _shed(items, _over(out, not_shown + note, budget))
    if len(items) < total:
        not_shown.append(f"{total - len(items)} of {total} {label}")


def fit_snapshot(snap: dict, budget: int = SNAPSHOT_BUDGET) -> dict:
    """The snapshot within ``budget`` characters of JSON. Whole items go, least needed first, never a
    slice of one, and the snapshot's "not_shown" says what went (FR-Z1-AC-4)."""
    out: dict = copy.deepcopy(snap)
    not_shown: list[str] = []
    lists = [(items, label, len(items), most) for section, key, label, most in _SHED_ITEMS
             if (items := (out.get(section) or {}).get(key))]
    for items, _label, _total, most in lists:  # the caps first, so the budget sheds only what it must
        if most is not None and isinstance(items, list):
            del items[most:]
    for items, label, total, _most in lists:
        _fit_list(out, items, label, total, not_shown, budget)
    for section, key, label in _SHED_SECTIONS:
        if _over(out, not_shown, budget) > 0 and key in (out.get(section) or {}):
            del out[section][key]
            not_shown.append(label)
    if _over(out, not_shown, budget) > 0:  # one record is too large by itself: say so rather than cut it
        out, not_shown = {}, [f"the whole snapshot: it is over {budget:,} characters even without its lists"]
    if not_shown:
        out["not_shown"] = not_shown
    return out


def _catalogue() -> str:
    """What every assistant prompt starts with, word for word: the rules, the cockpit's views,
    controls and actions, and the answer's shape. It never changes between calls, so an endpoint
    that caches prompt prefixes reads it once (FR-Z1-AC-4)."""
    m = ui_map()
    views = "\n".join(f"- {v['id']} ({v['route']}): {v['purpose']}" for v in m["views"])
    controls = "\n".join(f"- {c['id']}: {c['label']}, {c['where']}; {c['does']}" for c in m["controls"])
    actions = "\n".join(f"- {a}({', '.join(args)})" for a, args in ACTIONS.items())
    return f"""You are Rihma's cockpit assistant. You help a person use the cockpit and understand their projects.

Rules:
- Answer only from the snapshot at the end. If it does not hold the answer, say what you cannot see and
  which view would show it. What its "not_shown" names exists but was left out to keep it short.
- Plain language, short: two to five sentences, numbers as they are in the snapshot.
- You never act. You may propose actions; the person confirms each one, and it is signed with their name.
- Cite the snapshot items you used (project ids, card ids, task ids, question ids) in "sources".

The cockpit's views:
{views}

Its controls:
{controls}

Actions you may propose:
{actions}

Answer with this JSON in a ```json block:
{{"answer": "...", "navigate": {{"route": "#/p/<project id>/<view>", "control": "<control id or null>"}},
  "propose": [{{"action": "decide", "args": {{"card": "C-0001", "verdict": "approve", "reason": "..."}}, "why": "..."}}],
  "sources": ["..."]}}
Use null for "navigate" when nothing should open, and [] for "propose" when nothing should be done.
"""


def _ui_rules(ui: dict | None) -> str:
    """The widget library and the theme's tokens, so the assistant may propose reshaping the cockpit,
    but only within its boundaries."""
    if not ui:
        return ""
    return ("\nThe person may ask you to reshape the cockpit. Propose 'layout_edit' with ops from "
            f"{list(LAYOUT_OPS)} on widgets from {json.dumps(ui.get('widgets') or [])} (sizes {list(SIZES)}, views "
            f"{list(VIEWS)}), or 'theme' with settings from {json.dumps(THEME)} and font_scale "
            f"{FONT_SCALE[0]} to {FONT_SCALE[1]}. To make a chat for a website, propose 'create_embed' with kind "
            "'feedback' or 'need' and the website origins.\n")


def _layout_line(ui: dict | None) -> str:
    """The person's current layout, whole, or a note that it is too large to show: never a slice."""
    if not ui:
        return ""
    layout = json.dumps(ui.get("layout"))
    if len(layout) > LAYOUT_BUDGET:
        return f"Their current layout is over {LAYOUT_BUDGET:,} characters and is not shown.\n"
    return f"Their current layout: {layout}\n"


def prompt(question: str, snap: dict, *, persona: str, view: str | None, hints: list, ui: dict | None = None) -> str:
    """The static catalogue first, then who is asking and what, and the snapshot last."""
    return (_catalogue() + _ui_rules(ui)
            + f"\nThe person is the {persona} persona, looking at the {view or 'projects'} view.\n"
            + _layout_line(ui)
            + f"Map entries that match the question: {json.dumps([h['id'] for h in hints])}\n\n"
            + f"The question:\n<<<\n{question}\n>>>\n\n"
            + f"Snapshot (JSON):\n{json.dumps(fit_snapshot(snap), ensure_ascii=False, default=str)}\n")


def check_proposal(factory, project, persona: str, p: dict, ui: dict | None = None) -> str | None:
    """None if the proposal may be offered to this persona; otherwise why not."""
    from kernel.safestop import MAY_PAUSE

    action, args = p.get("action"), p.get("args") or {}
    if action not in ACTIONS:
        return f"unknown action {action!r}"
    missing = [a for a in ACTIONS[action] if a not in args and a not in ("reason",)]
    if missing:
        return f"missing {', '.join(missing)}"
    if action == "layout_edit":
        return check_layout_ops(args["ops"], list((ui or {}).get("widgets") or []))
    if action == "theme":
        return check_theme(args["settings"])
    if action == "create_embed":
        from kernel.embeds import CREATORS, KINDS, _ORIGIN

        if persona not in CREATORS:
            return f"a {persona} may not create an embed"
        if args["kind"] not in KINDS:
            return f"an embed's kind is one of {KINDS}"
        if not isinstance(args["origins"], list) or not args["origins"] or \
                not all(_ORIGIN.match(str(o).rstrip("/").lower()) for o in args["origins"]):
            return "origins are https://host addresses (or http://localhost for testing)"
        if args["kind"] == "feedback" and project is None:
            return "a feedback embed belongs to an open project"
        return None
    if action == "open":
        routes = [v["route"] for v in ui_map()["views"]]
        pattern = [re.escape(r).replace(re.escape("{pid}"), "[a-z0-9_-]+") for r in routes]
        return None if any(re.fullmatch(x, str(args["route"])) for x in pattern) else "not a cockpit route"
    if project is None:
        return "no project is open"
    canon = Canon(project)
    if action == "decide":
        try:
            card = canon.get_card(str(args["card"]))
        except KeyError:
            return f"no card {args['card']}"
        if card["state"] != "open":
            return f"{card['id']} is {card['state']}"
        if args["verdict"] not in CARD_VERDICTS[card["kind"]]:
            return f"a {card['kind']} card takes {CARD_VERDICTS[card['kind']]}"
        if persona not in CARD_DECIDERS[card["kind"]]:
            return f"a {persona} may not decide a {card['kind']} card"
    if action in ("answer_question", "let_rihma_assume"):
        try:
            q = canon.question(str(args["question"]))
        except KeyError:
            return f"no question {args['question']}"
        if q["status"] != "open":
            return f"{q['id']} is {q['status']}"
    if action in ("pause", "resume") and persona not in MAY_PAUSE:
        return f"a {persona} may not pause or resume"
    return None


def from_map(question: str, snap: dict, project) -> dict:
    hits = find_in_map(question)
    nav = None
    if hits:
        top = hits[0]
        if top["kind"] == "view":
            route = top["route"].replace("{pid}", project.pid) if project is not None else top["route"]
            if "{pid}" not in route:
                nav = {"route": route, "control": None}
            answer = f"{top['label']} shows {top['purpose']}."
        else:
            answer = f"{top['label']} is in the {top['where']}: it {top['does']}."
            nav = {"route": None, "control": top["id"]}
    elif project is not None:
        p = snap["project"]
        answer = f"{p['title']}: {p['now']['line']} Health: {p['health']['status'].replace('_', ' ')}."
    else:
        answer = "I could not match that to a view or a control. Try the palette (Ctrl+K) or name the view."
    return {"answer": answer, "navigate": nav, "propose": [], "dropped": [], "sources": [], "by": "map",
            "matches": [h["id"] for h in hits]}


def ask(factory, question: str, *, persona: str, project_id: str | None = None, view: str | None = None, ui=None,
        model=None) -> dict:
    if not question.strip():
        raise ValueError("the question is empty")
    project = factory.project(project_id) if project_id else None
    snap = snapshot(factory, project=project)
    if model is None:
        return from_map(question, snap, project)
    hints = find_in_map(question)
    try:
        raw = extract_json(model.ask(prompt(question, snap, persona=persona, view=view, hints=hints, ui=ui),
                                     role="assistant"))
    except ModelError as exc:
        out = from_map(question, snap, project)
        out["note"] = f"the assistant model gave no usable answer ({exc}); this answer comes from the cockpit map"
        return out
    proposals, dropped = [], []
    for p in raw.get("propose") or []:
        if not isinstance(p, dict):
            continue
        why_not = check_proposal(factory, project, persona, p, ui)
        (dropped if why_not else proposals).append(p if not why_not else {**p, "refused": why_not})
    nav = raw.get("navigate") if isinstance(raw.get("navigate"), dict) else None
    if nav and nav.get("route") and check_proposal(factory, project, persona, {"action": "open", "args": {"route": nav["route"]}}):
        nav = None  # a route the cockpit does not have is never followed
    known = {p["id"] for p in snap["factory"]["projects"]}
    if project is not None:
        known |= {c["id"] for c in snap["project"]["open_cards"]} | set(snap["project"]["tasks"]) | \
                 {q["id"] for q in snap["project"]["open_questions"]}
    sources = [s for s in (raw.get("sources") or []) if isinstance(s, str)]
    return {"answer": str(raw.get("answer") or "").strip(), "navigate": nav, "propose": proposals,
            "dropped": dropped, "sources": sources,
            "unbacked_sources": [s for s in sources if s not in known], "by": "assistant"}
