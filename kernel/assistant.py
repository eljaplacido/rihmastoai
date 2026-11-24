"""The cockpit assistant: ask where something is, what it means, how a run is going. It can propose
actions, but never takes one.

- **Navigation** comes from `cockpit/ui_map.json`, the cockpit's own map of views and controls, with
  the page each control is on. A "where is…" question is answered from the map even without a model,
  and Take me there opens the control's page before it highlights the control.
- **Answers** come only from a snapshot of the real read models (kernel/assistant_snapshot.py): now,
  health, the decision queue and whose each card is, the releases and what runs in production, the
  evidence, the decided cards, live. They cite the records they rest on, and a source the records do
  not hold is flagged. What is not in the snapshot, the assistant says it cannot see.
- **Actions** are proposals, offered only when the person asks for an action (kernel/assistant_rules.py).
  Each one is checked against the same rules as the Inbox and the routes (who may decide what, which
  verdicts a card takes, whether the project is paused) before a person sees it, and it runs only when
  that person confirms it in the cockpit, signed with their name. An answer that says the assistant did
  something is corrected. The assistant itself writes nothing.
- **Model calls** go through Gnomon as the `assistant` role (D-0005), in a lane of the assistant's own,
  so a question never waits behind intake or holdout authoring in the factory's analyst lane.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Collection
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from kernel.assistant_rules import (
    ACTIONS,
    CONTROL_PAGES,
    FACTORY_PID,
    FACTORY_VIEWS,
    FONT_SCALE,
    LAYOUT_OPS,
    SIZES,
    THEME,
    VIEWS,
    asks_for_action,
    check_layout_ops,
    check_proposal,
    check_theme,
    honest,
    normalize,
    route_ok,
    ui_map,
    words,
)
from kernel.assistant_snapshot import (
    LAYOUT_BUDGET,
    SNAPSHOT_BUDGET,
    backed,
    fit_snapshot,
    known,
    relevant_first,
    snapshot,
)
from kernel.confidential import confidential as is_confidential
from kernel.confidential import refusal
from kernel.filelock import LockHeld
from kernel.model import Model, ModelError, extract_json, run_gnomon_task

__all__ = ["ACTIONS", "CONTROL_PAGES", "FONT_SCALE", "LAYOUT_BUDGET", "LAYOUT_OPS", "SIZES", "SNAPSHOT_BUDGET",
           "THEME", "VIEWS", "AssistantModel", "ask", "assistant_model", "asks_for_action", "check_layout_ops",
           "check_proposal", "check_theme", "find_in_map", "fit_snapshot", "from_map", "normalize", "prompt",
           "snapshot", "ui_map"]
LANE_WAIT, MODEL_TIMEOUT, DEADLINE_GRACE = 10.0, 60, 15   # as the website chat's (embed/server.py ChatModel)


# -- the map -------------------------------------------------------------------------------------

def _score(q: set, it: dict) -> float:
    """A full match of the label or a synonym counts most, then how much of the question they cover;
    the purpose only breaks ties."""
    label, syns = words(it["label"]), [words(s) for s in it.get("synonyms", [])]
    named = label.union(*syns)
    text = words(it.get("purpose") or it.get("does") or "") - named
    if not q & (named | text):
        return 0.0
    best = max([(4.0 if q >= label else 2.0 * len(q & label) / len(label)) if label else 0.0]
               + [3.0 if q >= s else 1.5 * len(q & s) / len(s) for s in syns if s])
    return best + 2.0 * len(q & named) / len(q) + 0.25 * len(q & text)


def find_in_map(question: str, *, limit: int = 3, hidden: Collection[str] = ()) -> list:
    """Views and controls whose label, synonyms or purpose share words with the question, best first;
    none of the ``hidden`` ones (their module is not enabled, kernel/modules.py)."""
    q, m = words(question), ui_map()
    scored = [(_score(q, it), kind, it) for kind, items in (("view", m["views"]), ("control", m["controls"]))
              for it in items if it["id"] not in hidden]
    scored = sorted((x for x in scored if x[0] > 0), key=lambda x: -x[0])
    return [{"kind": k, **it} for _, k, it in scored[:limit]]


# -- the prompt ------------------------------------------------------------------------------------

def _catalogue(hidden: Collection[str] = ()) -> str:
    """What every assistant prompt starts with, word for word: the rules, the cockpit's views,
    controls and actions, and the answer's shape. It never changes between calls for one set of modules,
    so an endpoint that caches prompt prefixes reads it once (FR-Z1-AC-4); what a module that is not
    enabled shows is left out (``hidden``, FR-MOD2)."""
    m = ui_map()
    views = "\n".join(f"- {v['id']} ({v['route']}): {v['purpose']}" for v in m["views"] if v["id"] not in hidden)
    controls = "\n".join(f"- {c['id']}: {c['label']}, {c['where']}; {c['does']}" for c in m["controls"]
                         if c["id"] not in hidden)
    actions = "\n".join(f"- {a}({', '.join(args)})" for a, args in ACTIONS.items())
    return f"""You are Rihma's cockpit assistant. You help a person use the cockpit and understand their projects.

Rules:
- Answer only from the snapshot at the end. Never state a status, cause, reason or rationale it does not
  hold: say what you cannot see and which view would show it. What its "not_shown" names exists but was
  left out to keep it short: say that more exist, never that they do not.
- Plain language, short: two to five sentences, numbers as they are in the snapshot.
- You never act. Never write that you did, recorded, changed or will do anything: you propose, and the
  person confirms each proposal in the cockpit, signed with their name. Write "I propose ...".
- Propose an action only when the person asks for one. A question about how things stand gets an answer
  and, if useful, "navigate", never a proposal. A decide's reason is the person's own words or empty.
- "yours" says whether the person's persona may decide a card; only cards that are theirs wait on them.
  factory.waiting counts what the cockpit's Decisions waiting widget counts, the panel's open questions
  included: what waits on the person is its "yours", per project in "yours_by_project".
- Production: only the projects in factory.in_production run in production. "live (demo)" is the demo
  environment; a release's deployed_to names where it ran. paused false means not paused.
- Evidence: verified (a passing gate proved it), claimed (a test names it, no gate proved it), held_out
  (it passed against a running release), failing, not_measured. An evidence pack is attestable when the
  records are intact and complete enough for a reviewer to judge.
- "sources": only ids as the snapshot writes them (a project id, C-0001, Q-001, T-001, R-1, R-1-AC-1) or
  a snapshot path such as factory.gates.first_round_rate.

The cockpit's views:
{views}

Its controls:
{controls}

Actions you may propose, with their args:
{actions}

Answer with this JSON in a ```json block:
{{"answer": "...", "navigate": {{"route": "#/p/<project id>/<view>", "control": "<control id or null>"}},
  "propose": [{{"action": "pause", "args": {{"reason": "the person's words"}}, "why": "you asked to pause it"}}],
  "sources": ["..."]}}
Use null for "navigate" when nothing should open, and [] for "propose" when nothing was asked for.
"""


def _ui_rules(ui: dict | None) -> str:
    """The widget library and the theme's tokens, so the assistant may propose reshaping the cockpit,
    but only within its boundaries, with each argument's shape."""
    if not ui:
        return ""
    return ("\nThe person may ask you to reshape the cockpit. Propose 'layout_edit' with args {\"ops\": [...]}, "
            f"each op {{\"op\": one of {json.dumps(list(LAYOUT_OPS))}, \"widget\": a widget type from "
            f"{json.dumps(ui.get('widgets') or [])}}}, and with resize or add a size from {json.dumps(list(SIZES))}, "
            f"with set_view a view from {json.dumps(list(VIEWS))}, with move a 0-based position 'to', with "
            "set_filter a filter object of plain values. Name the widget by its type, not by its id in the layout. "
            f"Propose 'theme' with args {{\"settings\": {{...}}}} from {json.dumps(THEME)} and font_scale "
            f"{FONT_SCALE[0]} to {FONT_SCALE[1]}, for example {{\"settings\": {{\"accent\": \"teal\", \"density\": "
            "\"compact\"}}. To make a chat for a website, propose 'create_embed' with kind 'feedback' or 'need' "
            "and the website origins (https://host) the person names; if they named none, propose it with "
            "origins [] and ask for them: the form opens for them to fill in.\n")


def _layout_line(ui: dict | None) -> str:
    """The person's current layout, whole, or a note that it is too large to show: never a slice."""
    if not ui:
        return ""
    layout = json.dumps(ui.get("layout"))
    if len(layout) > LAYOUT_BUDGET:
        return f"Their current layout is over {LAYOUT_BUDGET:,} characters and is not shown.\n"
    return f"Their current layout: {layout}\n"


def prompt(question: str, snap: dict, *, persona: str, view: str | None, hints: list, ui: dict | None = None,
           hidden: Collection[str] = ()) -> str:
    """The static catalogue first, then who is asking and what, and the snapshot last."""
    return (_catalogue(hidden) + _ui_rules(ui)
            + f"\nThe person is the {persona} persona, looking at the {view or 'projects'} view.\n"
            + _layout_line(ui)
            + f"Map entries that match the question: {json.dumps([h['id'] for h in hints])}\n\n"
            + f"The question:\n<<<\n{question}\n>>>\n\n"
            + "Snapshot (JSON):\n"
            + json.dumps(fit_snapshot(relevant_first(snap, question)), ensure_ascii=False, default=str) + "\n")


# -- navigation ------------------------------------------------------------------------------------

def _target(item: dict, project: Any, views: dict) -> tuple[str | None, str]:
    """The route that opens a view, or the page a control is on, and a note when it cannot be opened."""
    if item.get("route"):
        pv, top = (item["id"], None) if "{pid}" in item["route"] else (None, item["id"])
    else:
        pv, top = item.get("view"), item.get("page")
    if project is not None and project.pid == FACTORY_PID and item.get("id") in ("pause", "resume", "autonomy"):
        return None, f" Rihma itself has no {item['label']}: it runs no pipeline of its own."
    if pv and project is not None and (project.pid != FACTORY_PID or pv in FACTORY_VIEWS):
        return views[pv]["route"].replace("{pid}", project.pid), ""
    if top:
        return views[top]["route"], ""
    if pv and project is not None:
        return None, f" Rihma itself has no {views[pv]['label']} view."
    if pv:
        return "#/projects", f" Open a project first: it is in each project's {views[pv]['label']} view."
    return None, ""


def _by_id() -> tuple[dict, dict]:
    m = ui_map()
    return {v["id"]: v for v in m["views"]}, {c["id"]: c for c in m["controls"]}


def _route_view(route: str) -> str:
    """The map id of the view a route opens: `#/p/<pid>/releases` is releases, `#/inbox` is inbox_all."""
    parts = route.lstrip("#/").split("/")
    if parts[0] == "p":
        return parts[2] if len(parts) > 2 else "overview"
    return "inbox_all" if parts[0] == "inbox" else parts[0]


def _visible(hidden: Collection[str]) -> tuple[dict, dict]:
    """The map's views and controls that a module that is on shows."""
    views, controls = _by_id()
    return ({k: v for k, v in views.items() if k not in hidden}, {k: v for k, v in controls.items() if k not in hidden})


def _followable(route: Any, factory: Any, hidden: Collection[str]) -> bool:
    return bool(route_ok(route, factory)) and _route_view(str(route)) not in hidden


def _checked_nav(nav: Any, factory: Any, project: Any, hidden: Collection[str] = ()) -> dict | None:
    """Where Take me there goes: a route the cockpit has, and a control from the map. A view named as a
    control opens that view, and a control without a route opens the page it is on. Nothing of a module
    that is not enabled (``hidden``) is followed."""
    if not isinstance(nav, dict):
        return None
    views, controls = _by_id()
    on_views, on_controls = _visible(hidden)
    route, control = nav.get("route") or None, nav.get("control") or None
    if control in on_views:
        route, control = route or _target(views[control], project, views)[0], None
    if control not in on_controls:
        control = None
    if route and not _followable(route, factory, hidden):
        route = None  # a route the cockpit does not have, or does not show, is never followed
    if control and not route:
        route, note = _target(controls[control], project, views)
        control = None if note else control   # not on the page that opens, or not in this project
    return {"route": route, "control": control} if route or control else None


# -- answering from the map --------------------------------------------------------------------------

_THEME_WORDS = {"theme", "accent", "colour", "color", "dark", "light", "teal", "violet", "rose", "amber", "blue",
                "green", "font", "corner", "radiu", "compact", "density", "spacing"}
_LAYOUT_WORDS = {"widget", "wide", "wider", "bigger", "smaller", "larger", "table", "chart", "layout", "resize",
                 "dashboard"}


def _control_answer(c: dict) -> str:
    where, does, plural = c["where"], c["does"], c["label"].endswith("s") and not c["label"].endswith("ss")
    if where.split(" ", 1)[0].lower() not in ("the", "a", "an") and not (" " not in where and where[:1].isupper()):
        where = "the " + where
    if plural:
        does = re.sub(r"^(\w+?)(?:(?<=ch|sh|ss)es|(?<=x)es|s)\b", r"\1", does)
    return f"{c['label']} {'are' if plural else 'is'} in {where}: {'they' if plural else 'it'} {does}."


def _status_line(project: Any) -> str:
    from kernel.status import health, now

    line = now(project)["line"]
    return (f"{project.meta.get('title')}: {line}{'' if line.endswith(('.', '!', '?')) else '.'} Health: "
            f"{health(project)['status'].replace('_', ' ')}.")


def _reshape(question: str, controls: dict) -> list | None:
    """A request to reshape the cockpit needs a model: the control that does it by hand, or None."""
    said = words(question)
    if said & _THEME_WORDS:
        return [{"kind": "control", **controls["density" if said & _THEME_WORDS <= {"compact", "density", "spacing"}
                                                else "theme"]}]
    return [{"kind": "control", **controls["customize"]}] if said & _LAYOUT_WORDS else None


def _not_enabled(item: dict) -> dict:
    """The answer about a view or a control whose module is not enabled here: which module adds it, what
    else it adds, and Take me there to Settings, Modules, where a person turns it on (FR-MOD2)."""
    from kernel.modules import offering

    mod = offering(item["id"]) or {"id": None, "label": "a module", "adds": "more"}
    return {"answer": f"{item['label']} is part of {mod['label']}, which is not enabled here. It adds {mod['adds']}. "
                      "Settings, Modules turns it on.", "navigate": {"route": "#/settings", "control": "modules"},
            "propose": [], "dropped": [], "sources": [], "by": "map", "matches": [item["id"]],
            "not_enabled": mod["id"]}


def _map_hits(question: str, act: bool, controls: dict, hidden: Collection[str]) -> tuple[list, dict | None]:
    """The map's best matches that are on, or none and the best match when that one is off."""
    hits = (_reshape(question, controls) if act else None) or find_in_map(question)
    if hits and hits[0]["id"] in hidden:
        return [], hits[0]
    return [h for h in hits if h["id"] not in hidden], None


def from_map(question: str, project: Any, *, hidden: Collection[str] = ()) -> dict:
    """An answer from the cockpit's map alone: where a view or a control is, and Take me there. A request
    to act or to reshape the cockpit is told plainly that the map cannot, and where to do it oneself. What
    a module that is not enabled shows (``hidden``) is never pointed to; asked for, it is named."""
    act = asks_for_action(question)
    views, controls = _by_id()
    hits, off = _map_hits(question, act, controls, hidden)
    if off is not None:
        return _not_enabled(off)
    nav = None
    if hits:
        top = hits[0]
        route, note = _target(top, project, views)
        answer = (f"{top['label']} shows {top['purpose']}." if top["kind"] == "view" else _control_answer(top)) + note
        control = top["id"] if top["kind"] == "control" and not note else None   # not on the page it opens
        nav = {"route": route, "control": control} if route or control else None
        if act:
            answer = "I can only point the way here: no model is set up to propose actions. " + answer
    elif project is not None:
        answer = _status_line(project)
    else:
        answer = "I could not match that to a view or a control. Try the palette (Ctrl+K) or name the view."
    return {"answer": answer, "navigate": nav, "propose": [], "dropped": [], "sources": [], "by": "map",
            "matches": [h["id"] for h in hits]}


# -- the model ---------------------------------------------------------------------------------------

class AssistantModel(Model):
    """Gnomon's `assistant` role in a lane of its own (`<lanes root>/assistant/analyst`), never the factory's
    analyst lane, where intake, spec and holdout authoring run for many minutes. A question waits at most
    ``lane_wait`` seconds for the lane (LockHeld after that), and Gnomon gets at most ``timeout`` seconds."""

    def __init__(self, lane_dir: str | Path, *, timeout: int = MODEL_TIMEOUT, lane_wait: float = LANE_WAIT) -> None:
        self.lane_dir, self.timeout, self.lane_wait = Path(lane_dir), timeout, lane_wait

    def ask(self, prompt: str, *, role: str) -> str:
        from kernel.lanes import lane_lock

        give_up = time.monotonic() + self.lane_wait
        with ExitStack() as held:
            while True:
                try:
                    held.enter_context(lane_lock(self.lane_dir, blocking=False))
                    break
                except LockHeld:
                    if time.monotonic() >= give_up:
                        raise
                    time.sleep(0.2)
            record = run_gnomon_task(self.lane_dir, prompt, role=role, timeout=self.timeout,
                                     deadline=max(1, self.timeout - DEADLINE_GRACE))
        self.last_record, output = record, record.get("output")
        if record.get("bucket") == "apparatus_failure" or not isinstance(output, str) or not output.strip():
            raise ModelError(f"gnomon task --role {role} gave no answer (stop: {record.get('stop_reason')})")
        return output


def assistant_model(root: str | Path | None = None) -> AssistantModel:
    """The assistant's model, in ``<lanes root>/assistant/analyst``: a toolless analyst lane of its own."""
    from kernel.lanes import ensure_analyst_lane, lanes_root, load_routing

    return AssistantModel(ensure_analyst_lane(load_routing(), root=Path(root or lanes_root()) / "assistant"))


_OWN_LANES: dict[str, Model] = {}


def _own_lane(model: Model) -> Model:
    """A GnomonModel for the factory's analyst lane is asked through the assistant's own lane beside it
    (`assistant_model`), so a question never waits on that lane's lock behind a long run."""
    from kernel.model import GnomonModel

    if not isinstance(model, GnomonModel):
        return model
    key = str(model.lane_dir)
    if key not in _OWN_LANES:
        _OWN_LANES[key] = assistant_model(Path(key).parent)
    return _OWN_LANES[key]


# -- answering -----------------------------------------------------------------------------------------

# The map control a proposal acts through: one whose control a module that is off shows is not offered.
_ACTION_CONTROL = {"answer_question": "answer", "let_rihma_assume": "assume", "decide": "decide", "pause": "pause",
                   "resume": "resume", "report_change": "report", "comment": "comment", "theme": "theme",
                   "create_embed": "create_embed"}


def _module_off(target: Any, p: dict, hidden: Collection[str]) -> str | None:
    """Why a proposal is not offered because what it acts through, a view it opens, a control or a widget it
    adds, belongs to a module that is not enabled here (FR-MOD5); None when it is on."""
    from kernel import modules

    args = p.get("args") or {}
    if p["action"] == "layout_edit":
        added = [str(o.get("widget")) for o in args.get("ops") or [] if isinstance(o, dict) and o.get("op") == "add"]
        found = [modules.owner("widgets", w) for w in added if not modules.shown(target, "widgets", w)]
    else:
        name = _route_view(str(args.get("route") or "")) if p["action"] == "open" else _ACTION_CONTROL.get(p["action"])
        found = [(modules.offering(name) or {}).get("id")] if name in hidden else []
    off = next((m for m in found if m), None)
    return f"{modules.MODULES[off]['label']} is not enabled here: Settings, Modules turns it on" if off else None


def _offered(factory: Any, project: Any, persona: str, question: str, raw: Any, ui: dict | None,
             hidden: Collection[str] = ()) -> tuple:
    """The model's proposals, each checked, none of a module that is off, and how many it made that the
    person did not ask for."""
    asked, proposals, dropped, unasked = asks_for_action(question), [], [], 0
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        p = normalize(p, ui)
        if not asked and p["action"] != "open":
            unasked += 1  # a question about how things stand gets an answer, not a proposal
            continue
        why_not = (check_proposal(factory, project, persona, p, ui)
                   or _module_off(project if project is not None else factory, p, hidden))
        if why_not:
            dropped.append({**p, "refused": why_not})
        else:
            proposals.append({**p, "persona": persona, "project": project.pid if project is not None else None})
    return proposals, dropped, unasked


def _local_only(project: Any, model: Model | None) -> tuple[Model | None, dict]:
    """No model, and a note, for a confidential project whose assistant model is hosted (kernel/confidential.py):
    it is answered from the cockpit map, and nothing about it is sent."""
    if model is None or project is None or not is_confidential(project) or not refusal(["assistant"]):
        return model, {}
    return None, {"note": "this project is confidential and the assistant's model is hosted: answered from the map"}


def _fallback(question: str, project: Any, exc: Exception, hidden: Collection[str] = ()) -> dict:
    out = from_map(question, project, hidden=hidden)
    out["note"] = (f"the assistant's model was busy for {LANE_WAIT:.0f} seconds with another question; this answer "
                   "comes from the cockpit map. Ask again in a moment" if isinstance(exc, LockHeld) else
                   f"the assistant model gave no usable answer ({exc}); this answer comes from the cockpit map")
    return out


def ask(factory: Any, question: str, *, persona: str, project_id: str | None = None, view: str | None = None,
        ui: dict | None = None, model: Model | None = None) -> dict:
    """The assistant's answer: from the map without a model; with one, from the snapshot, with its
    proposals checked, its sources checked against the records, and its wording kept to proposing."""
    if not question.strip():
        raise ValueError("the question is empty")
    from kernel.modules import hidden_ids

    project = factory.project(project_id) if project_id else None
    hidden = hidden_ids(project if project is not None else factory)   # the map of what is enabled there
    model, kept_local = _local_only(project, model)
    if model is None:
        return from_map(question, project, hidden=hidden) | kept_local
    snap = snapshot(factory, project=project, persona=persona)
    try:
        raw = extract_json(_own_lane(model).ask(prompt(question, snap, persona=persona, view=view, ui=ui,
                                                       hints=find_in_map(question, hidden=hidden), hidden=hidden),
                                                role="assistant"))
        if not isinstance(raw, dict):
            raise ModelError("the answer is not a JSON object")
    except (ModelError, OSError, RuntimeError, ValueError) as exc:   # LockHeld is a RuntimeError
        return _fallback(question, project, exc, hidden)
    proposals, dropped, unasked = _offered(factory, project, persona, question, raw.get("propose"), ui, hidden)
    answer, note = honest(str(raw.get("answer") or "").strip(), proposals, dropped)
    sources = [str(s) for s in raw.get("sources") or [] if isinstance(s, (str, int)) and str(s).strip()]
    held = known(factory, project, snap)
    out = {"answer": answer, "navigate": _checked_nav(raw.get("navigate"), factory, project, hidden),
           "propose": proposals,
           "dropped": dropped, "unasked": unasked, "sources": sources,
           "unbacked_sources": [s for s in sources if not backed(s, held, snap)], "by": "assistant"}
    if note:
        out["note"] = note
    return out
