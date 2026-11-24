"""The cockpit assistant's rules: what it may offer, and how it must say it (kernel/assistant.py).

- **Boundaries**: the actions it may propose, the layout schema and the theme's tokens, and the
  cockpit's map with the page each control is on (`CONTROL_PAGES`).
- **Shapes**: `normalize` reads the reasonable shapes a model writes (flat theme settings, a layout's
  own widget ids, sizes in words) as the checks read them.
- **Checks**: `check_proposal` applies the rules the Inbox and the routes apply, so a proposal a route
  would refuse is never offered.
- **Asking and telling**: a proposal is offered only when the person asks for an action
  (`asks_for_action`), and an answer never says the assistant did something (`honest`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from kernel.canon import CARD_DECIDERS, CARD_VERDICTS, Canon
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
FACTORY_PID, FACTORY_VIEWS = "_factory", ("overview", "inbox", "ledger")   # cockpit/static/core.js FACTORY_VIEWS
# Where each control of the map is: the project view it is on, and the page it is on outside a project.
# (None, None) is the shell, on every page. Take me there opens that page, then highlights the control.
CONTROL_PAGES: dict[str, tuple[str | None, str | None]] = {
    "persona": (None, None), "lens": (None, None), "palette": (None, None), "assistant": (None, None),
    "theme": (None, None), "density": (None, None), "new_project": (None, "projects"),
    "adopt_project": (None, "projects"), "scan_source": (None, "projects"), "confidential": (None, "projects"),
    "customize": (None, "home"),
    "pause": ("overview", None), "resume": ("overview", None), "autonomy": ("overview", None),
    "answer": ("questions", "inbox_all"), "assume": ("questions", None), "decide": ("inbox", "inbox_all"),
    "report": ("changes", None), "comment": ("spec", None), "log_signal": (None, "square"),
    "validate_concept": (None, "square"), "export_evidence": ("evidence", None), "build_pack": ("releases", None),
    "create_embed": (None, "settings"), "intake_summary": ("questions", None),
    "track_pill": ("overview", None), "track_settings": ("track", None),
    "checkpoint_look": ("track", None), "autopilot_start": ("track", None), "autopilot_stop": ("track", None),
    "revoke_delegation": ("track", None),
    "choose_outputs": ("outputs", None), "build_output": ("outputs", None),
    "build_outputs": ("outputs", None), "download_output": ("outputs", None), "modules": (None, "settings"),
    "revoke_embed": (None, "settings"),
    "project_settings": ("overview", None), "rewind_project": ("overview", None), "add_material": ("overview", None),
    "next_step": ("overview", None),
    "shape_open": (None, "home"), "shape_start": (None, "shape"),
    "shape_say": (None, "shape"), "shape_attach": (None, "shape"), "shape_draft": (None, "shape"),
    "shape_create": (None, "shape"), "models_open": (None, "settings"), "models_set": (None, "models"),
    "models_test": (None, "models"), "models_remove": (None, "models"), "models_preset": (None, "models"),
    "models_private": (None, "models")}
# As the cockpit names them (cockpit/server.py PERSONA_INFO), for the reasons a proposal is not offered.
PERSONA_LABEL = {"business_owner": "Business owner", "product_owner": "Product owner", "it": "IT / partner",
                 "concept_evaluator": "Concept evaluator", "end_user": "End-user tester", "developer": "Developer",
                 "operations": "Operations", "stakeholder": "Stakeholder", "compliance": "Compliance"}
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "is", "are", "where", "can", "i", "find", "how", "do", "to", "of", "what", "does",
         "this", "my", "me", "for", "in", "on", "it", "and", "or", "which", "see", "show", "go", "get", "there",
         "use", "want", "please", "you", "we", "our", "with", "be", "at", "as", "by", "from", "would", "could"}


def ui_map() -> dict:
    """The cockpit's map, with the page each control is on (CONTROL_PAGES: "view" in a project, "page"
    outside one)."""
    m = json.loads(UI_MAP_FILE.read_text(encoding="utf-8"))
    for c in m["controls"]:
        c["view"], c["page"] = CONTROL_PAGES.get(c["id"], (None, None))
    return m


def words(text: str) -> set:
    """The words that carry meaning, a plural read as its singular."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _a(kind: str) -> str:
    word = kind.replace("_", " ")
    return ("an " if word[:1] in "aeiou" else "a ") + word


def _who(persona: str) -> str:
    return PERSONA_LABEL.get(persona, persona)


def _plain(filt: Any) -> bool:
    return isinstance(filt, dict) and len(json.dumps(filt, default=str)) <= 400 and all(
        isinstance(k, str) and isinstance(v, (str, int, float, bool, type(None))) for k, v in filt.items())


def check_layout_ops(ops: Any, widgets: list) -> str | None:
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
        if o["op"] == "set_filter" and not _plain(o.get("filter")):   # as cockpit/server.py _check_layout
            return "set_filter needs a small 'filter' object of plain values"
    return None


def check_theme(settings: Any) -> str | None:
    if not isinstance(settings, dict) or not settings:
        return "settings is a non-empty object"
    for k, v in settings.items():
        if k == "font_scale":
            if not isinstance(v, (int, float)) or not FONT_SCALE[0] <= v <= FONT_SCALE[1]:
                return f"font_scale is between {FONT_SCALE[0]} and {FONT_SCALE[1]}"
        elif k not in THEME or v not in THEME[k]:
            return f"{k} is not a theme setting, or {v!r} is not one of its values"
    return None


# -- the reasonable shapes a model writes, read as the checks read them ---------------------------

_ALIAS = {"layout": "layout_edit", "edit_layout": "layout_edit", "set_theme": "theme", "embed": "create_embed",
          "answer": "answer_question", "assume": "let_rihma_assume", "navigate": "open", "rule": "decide"}
_OP = {"size": "resize", "set_size": "resize", "view": "set_view", "show_as": "set_view", "delete": "remove",
       "insert": "add", "filter": "set_filter", "reorder": "move"}
_SIZE = {"s": "S", "small": "S", "m": "M", "medium": "M", "l": "L", "large": "L", "wide": "L", "big": "L",
         "bigger": "L", "xl": "XL", "extra large": "XL", "huge": "XL", "wide and tall": "XL", "full": "XL"}


def _instances(ui: dict | None) -> dict:
    """The person's layout: each placed widget's own id, and its type."""
    layout = (ui or {}).get("layout")
    placed = layout.get("widgets") if isinstance(layout, dict) else layout
    return {w.get("id"): w.get("type") for w in placed or [] if isinstance(w, dict)}


def _widget(o: dict, ui: dict | None) -> Any:
    """The widget type an op names: by its type, its id in the layout ("gate_trend-2") or its name."""
    lib = list((ui or {}).get("widgets") or [])
    w = next((o[k] for k in ("widget", "type", "widget_type", "widget_id", "id", "name") if o.get(k)), None)
    w = _instances(ui).get(w) or w
    if isinstance(w, str) and w not in lib:
        w = next((t for t in lib if w.startswith(t + "-") or w.lower().replace(" ", "_") == t), w)
    return w


def _op(o: Any, ui: dict | None) -> Any:
    """One layout operation, in the layout schema's own words."""
    if not isinstance(o, dict):
        return o
    o = {str(k).lower(): v for k, v in o.items()}
    op = str(o.get("op") or o.get("action") or "").lower()
    out = {"op": _OP.get(op, op), "widget": _widget(o, ui)}
    if "size" in o:
        out["size"] = _SIZE.get(str(o["size"]).strip().lower(), o["size"])
    if "view" in o:
        out["view"] = str(o["view"]).strip().lower()
    to = next((o[k] for k in ("to", "position", "index") if k in o), None)
    if to is not None:
        out["to"] = int(to) if str(to).strip().lstrip("-").isdigit() else to
    if "filter" in o:
        out["filter"] = o["filter"]
    return out


def _setting(k: str, v: Any) -> Any:
    if k == "font_scale":
        try:
            f = float(str(v).rstrip("% "))
        except ValueError:
            return v
        return f / 100 if f > 3 else f
    return str(v).strip().lower().removesuffix(" mode").removesuffix(" corners") if isinstance(v, str) else v


def _layout_args(args: dict, ui: dict | None) -> dict:
    ops = args.get("ops", args.get("operations", [args] if "op" in args else None))
    return {} if ops is None else {"ops": [_op(o, ui) for o in (ops if isinstance(ops, list) else [ops])]}


def _theme_args(args: dict, ui: dict | None) -> dict:
    s = args.get("settings", args.get("theme", args))   # also flat: {"accent": "teal", "density": "compact"}
    return {"settings": {str(k).lower(): _setting(str(k).lower(), v) for k, v in s.items()}} \
        if isinstance(s, dict) and s else {}


def _embed_args(args: dict, ui: dict | None) -> dict:
    o = args.get("origins", args.get("origin", []))
    o = re.split(r"[\s,]+", o) if isinstance(o, str) else o if isinstance(o, list) else []
    return {**args, "kind": str(args.get("kind") or "feedback").strip().lower(),   # no origin: the form asks
            "origins": [str(x).strip() for x in o if str(x).strip() not in ("", "*")]}


def _decide_args(args: dict, ui: dict | None) -> dict:
    if "verdict" in args:
        args["verdict"] = re.sub(r"[\s-]+", "_", str(args["verdict"]).strip().lower())
    return args


_ARGS = {"layout_edit": _layout_args, "theme": _theme_args, "create_embed": _embed_args, "decide": _decide_args}


def normalize(p: dict, ui: dict | None = None) -> dict:
    """A proposal in the shape the checks read: its arguments under "args", a layout op's widget by its
    type (also when the model names the layout's own instance id), a theme's flat settings wrapped,
    sizes and verdicts in their canonical spelling, a website chat's origins as a list."""
    action = str(p.get("action") or "").strip().lower()
    action = _ALIAS.get(action, action)
    args = dict(p["args"]) if isinstance(p.get("args"), dict) else \
        {k: v for k, v in p.items() if k not in ("action", "args", "why")}
    if action in _ARGS:
        args = _ARGS[action](args, ui)
    return {**{k: v for k, v in p.items() if k not in ("action", "args")}, "action": action, "args": args}


# -- the checks ------------------------------------------------------------------------------------

def route_ok(route: Any, factory: Any) -> bool:
    """A cockpit route, for a project that exists, and a view that project has."""
    for v in ui_map()["views"]:
        pattern = re.escape(v["route"]).replace(re.escape("{pid}"), "(?P<pid>[a-z0-9_-]+)")
        if (m := re.fullmatch(pattern, str(route))):
            pid = m.groupdict().get("pid")
            return pid is None or ((factory.projects_dir / pid / "project.json").exists()
                                   and (pid != FACTORY_PID or v["id"] in FACTORY_VIEWS))
    return False


def _check_embed(project: Any, persona: str, args: dict) -> str | None:
    from kernel.embeds import _ORIGIN, CREATORS, KINDS

    if persona not in CREATORS:
        return f"as {_who(persona)} you may not create an embed (who may: {', '.join(map(_who, CREATORS))})"
    if args["kind"] not in KINDS:
        return f"an embed's kind is one of {KINDS}"
    if not isinstance(args["origins"], list) or not all(_ORIGIN.match(str(o).rstrip("/").lower())
                                                        for o in args["origins"]):
        return "origins are https://host addresses (or http://localhost for testing)"
    if args["kind"] == "feedback" and (project is None or project.pid == FACTORY_PID):
        return "a feedback embed belongs to an open product project"
    return None


def _check_decide(project: Any, persona: str, args: dict) -> str | None:
    try:
        card = Canon(project).get_card(str(args["card"]).upper())
    except (KeyError, OSError):
        return f"no card {args['card']}"
    kind = card["kind"]
    if card["state"] != "open":
        return f"{card['id']} is {card['state']}"
    if args["verdict"] not in CARD_VERDICTS[kind]:
        return f"{_a(kind)} card takes {', '.join(CARD_VERDICTS[kind])}"
    if persona not in CARD_DECIDERS[kind]:
        who = ", ".join(map(_who, CARD_DECIDERS[kind]))
        return f"as {_who(persona)} you may not decide {_a(kind)} card (who may: {who})"
    return None


def _check_question(project: Any, persona: str, args: dict) -> str | None:
    try:
        q = Canon(project).question(str(args["question"]).upper())
    except KeyError:
        return f"no question {args['question']}"
    return None if q["status"] == "open" else f"{q['id']} is {q['status']}"


def _check_pause(project: Any, persona: str, args: dict, *, pause: bool = True) -> str | None:
    """As the pause and resume routes: who may, never Rihma itself, and not twice."""
    from kernel.safestop import MAY_PAUSE

    held = project.meta.get("pause")
    if persona not in MAY_PAUSE:
        return f"as {_who(persona)} you may not pause or resume a project"
    if project.pid == FACTORY_PID:
        return "Rihma itself has no pipeline to pause"
    if pause and held:
        return f"{project.pid} is already paused by {held.get('requested_by')}"
    return None if pause or held else f"{project.pid} is not paused"


def _check_comment(project: Any, persona: str, args: dict) -> str | None:
    ok = args["target_kind"] in Canon.COMMENT_TARGETS
    return None if ok else f"a comment's target is one of {', '.join(Canon.COMMENT_TARGETS)}"


# The rules the routes apply to an action on a project, so what they would refuse is never offered.
_ON_PROJECT: dict[str, Callable[[Any, str, dict], str | None]] = {
    "decide": _check_decide, "answer_question": _check_question, "let_rihma_assume": _check_question,
    "pause": _check_pause, "resume": lambda pr, who, a: _check_pause(pr, who, a, pause=False),
    "comment": _check_comment}


def _check_ui(factory: Any, project: Any, persona: str, action: str, args: dict, ui: dict | None) -> str | None:
    """The checks that need no project: the layout schema, the theme's tokens, an embed, a route."""
    if action == "layout_edit":
        return check_layout_ops(args["ops"], list((ui or {}).get("widgets") or []))
    if action == "theme":
        return check_theme(args["settings"])
    if action == "create_embed":
        return _check_embed(project, persona, args)
    return None if route_ok(args["route"], factory) else "not a cockpit route"


def check_proposal(factory: Any, project: Any, persona: str, p: dict, ui: dict | None = None) -> str | None:
    """None if the proposal may be offered to this persona; otherwise why not."""
    action, args = p.get("action"), p.get("args") or {}
    if action not in ACTIONS:
        return f"unknown action {action!r}"
    missing = [a for a in ACTIONS[action] if a not in args and a != "reason"]
    if missing:
        return f"missing {', '.join(missing)}"
    if action in ("layout_edit", "theme", "create_embed", "open"):
        return _check_ui(factory, project, persona, str(action), args, ui)
    if action in ("answer_question", "report_change", "comment") and not str(args.get("text") or "").strip():
        return "the text is empty"
    if project is None:
        return "no project is open: open the project first"
    check = _ON_PROJECT.get(str(action))
    return check(project, persona, args) if check else None


# -- asking for an action, and an answer that only proposes ------------------------------------------

_ASKING = {"where", "what", "which", "why", "when", "who", "whom", "whose", "how", "is", "are", "was", "were",
           "does", "do", "did", "has", "have", "should", "mikä", "mitä", "missä", "miksi", "milloin", "kuka",
           "ketkä", "miten", "onko", "ovatko", "paljonko", "montako", "kenen", "mihin", "mistä", "voiko"}
_FILLER = {"please", "hey", "hi", "rihma", "ok", "okay", "so", "now", "then", "and", "but", "also", "can", "could",
           "would", "will", "you", "kindly", "voitko", "voisitko", "ole", "hyvä"}
_ACT = re.compile(r"^(?:decid|rule|approv|reject|accept|refus|retr|defer|park|validat|declin|paus|stop|halt|resum|"
                  r"continu|answer|assum|repl|report|file|comment|note|make|creat|chang|set|use|switch|show|resiz|"
                  r"add|remov|delet|move|put|filter|enlarg|shrink|let|mark|record|log|turn|apply|keep|undo|build|"
                  r"export|acknowledg|roll|trial|bigger|smaller|wider|wide|larger|compact|dark|light|theme|table|"
                  r"chart|defect|hyväksy|hylkää|päätä|tauot|pysäytä|jatka|vastaa|oleta|raportoi|kommentoi|tee|"
                  r"luo|muuta|vaihda|näytä|lisää|poista|siirrä|merkitse|kirjaa)")


def asks_for_action(question: str) -> bool:
    """Whether the person asks for something to be done, rather than how things stand: a sentence that
    does not open as a question ("where", "how", "is", "mikä"...) and names an action."""
    for sentence in re.split(r"[.?!;:\n]+", question.lower()):
        said = re.findall(r"\w+", sentence)
        while said and said[0] in _FILLER:
            said.pop(0)
        if said and said[0] not in _ASKING and any(_ACT.match(w) for w in said):
            return True
    return False


# "I have noted ...", "I'll flag it", "we've sent it on": the assistant saying it did, or will do, something.
# "I note that ..." (an observation) and "I propose ..." are not claims.
_CLAIM = re.compile(
    r"\b(?:I|we)(?:'ve|'ll|'m| have| had| will| shall| am| are| just| now| also| already| hereby| going to|"
    r" ready to| about to| gone ahead and| went ahead and)*\s+(?:record|decid|paus|resum|chang|updat|sav|creat|"
    r"made|mak|appl|set|switch|resiz|fil|submit|answer|approv|reject|accept|mark|log|add|remov|mov|rul|assum|"
    r"report|comment|enabl|disabl|turn|proceed|done|complet|retr|defer|park|validat|noted\b|noting\b|"
    r"t(?:ook|aken|ake|aking) (?:a )?note|jott|wr(?:ote|itten) (?:it |this |that )?down|register|flag|captured|"
    r"escalat|forwarded|sent\b|notified|assigned|scheduled|queued|triggered|resolved|acknowledg|confirm)\w*"
    r"|\bolen\s+(?:nyt\s+)?(?:kirjannut|tallentanut|päättänyt|muuttanut|tauottanut|luonut|tehnyt|hyväksynyt|"
    r"hylännyt|vastannut|lisännyt|poistanut|merkinnyt|lähettänyt|ilmoittanut)\b", re.I)
# A sentence that opens by saying it is done: "Noted.", "Done:", "Recorded, ..."
_DONE = re.compile(r"^\s*(?:noted|done|recorded|logged|filed|saved|submitted|kirjattu|merkitty|tehty)\s*[.!:,;]",
                   re.I)
_OFFER = re.compile(r"\b(?:would you like me to|shall i|should i|do you want me to|want me to)\b", re.I)


def honest(answer: str, proposals: list, dropped: list) -> tuple[str, str | None]:
    """The answer without any sentence that says the assistant did, or will do, something, and with what
    is true instead: nothing is done until a person confirms a proposal. Also a note when one went."""
    parts = [s for s in re.split(r"(?<=[.!?])\s+", answer) if s]
    kept = [s for s in parts if not (_CLAIM.search(s) or _DONE.search(s) or _OFFER.search(s))]
    removed = len(kept) < len(parts)
    if proposals:
        tail = ("Nothing is done yet: what I propose below runs only when you confirm it"
                + (", after a preview." if any(p["action"] in ("layout_edit", "theme") for p in proposals) else "."))
    elif dropped:
        tail = f"Nothing is done, and I could not offer it: {dropped[0]['refused']}."
    else:
        tail = "Nothing is done: I only propose actions, and a person confirms them."
    if removed or (dropped and not proposals):
        kept.append(tail)
    return (" ".join(kept).strip(), "A sentence that said the assistant had acted, or would act, was taken out: "
            "it only proposes, and you confirm." if removed else None)
