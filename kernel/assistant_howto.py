"""Ask Rihma's how-to answers, made practical, and the scope each answer is about (FR-UXO1).

The owner (2026-11-25): Ask Rihma's how-to answers were impractical ("via `rihmasto ide <pid>`", "the snapshot does
not show ..."). An answer to "how do I ..." now gives numbered steps for THIS project: where to go (with Take me
there, the action that opens it), what to press there, and the command with everything filled in that is known (the
project's id, the person's name and persona, real paths), never "<pid>" or "<your name>". A sentence saying the
snapshot does not show something becomes where to look instead.

``named_project`` finds another project the question names by its title, so Rihma can say it switched; ``practical``
rewrites an answer (from the map or the model) and adds ``steps``. Neither writes anything.
"""

from __future__ import annotations

import re
from typing import Any

HOWTO = re.compile(r"^\s*(?:please\s+)?(?:how\s+(?:do|can|should|would)\s+(?:i|we)|how\s+to|how\s+does\s+one|"
                   r"what\s+do\s+i\s+do\s+to|where\s+do\s+i|what\s+are\s+the\s+steps|steps\s+to|miten|kuinka)\b", re.I)
PLACEHOLDER = re.compile(r"<\s*(?:pid|project(?:[ _-]id)?|your[ _-]name|name|persona|person|p|id)\s*>", re.I)
ANY_PLACEHOLDER = re.compile(r"<[a-z][a-z _|-]{0,30}>", re.I)
NO_SNAPSHOT = re.compile(r"[^.!?]*\b(?:the\s+)?snapshot\s+(?:does\s+not|doesn't|did\s+not|cannot)\s+"
                         r"(?:show|say|include|contain)[^.!?]*[.!?]?", re.I)
SIGNED = '--person "{person}" --persona {persona}'

# The commands that do what a map entry does, from a terminal, for one project ({pid}, {person}, {persona}, {card},
# {question} are filled in; a command whose value is not known is left out, never shown with a placeholder).
COMMANDS: dict[str, list[str]] = {
    "ide_setup": ['rihmasto ide {pid} --name "{person}"'], "ai_tools": ["rihmasto ide {pid}"],
    "aitools": ["rihmasto ide {pid}"], "ide_section": ["rihmasto ide {pid} --section"],
    "decide": ["rihmasto decide {pid} {card} <verdict> " + SIGNED + ' --reason "why"'],
    "answer": ['rihmasto answer {pid} {question} "your answer" ' + SIGNED],
    "assume": ["rihmasto assume {pid} {question} " + SIGNED],
    "report": ['rihmasto change {pid} "what should change" ' + SIGNED],
    "align_scan": ["rihmasto align {pid} --scan " + SIGNED], "align": ["rihmasto align {pid}"],
    "run_assessment": ["rihmasto assess {pid} " + SIGNED], "assessment": ["rihmasto assessment list {pid}"],
    "console_run": ["rihmasto console {pid} " + SIGNED + " -- git status"],
    "console": ["rihmasto console {pid} " + SIGNED + " -- git status"],
    "export_evidence": ["rihmasto evidence {pid} --out evidence-{pid}"],
    "evidence": ["rihmasto evidence {pid} --out evidence-{pid}"],
    "build_pack": ["rihmasto pack {pid}"], "releases": ["rihmasto pack {pid}"],
    "next_step": ["rihmasto run {pid}"], "overview": ["rihmasto status {pid}"],
    "autopilot_start": ["rihmasto autopilot start {pid} --until 8h --delegate question " + SIGNED],
    "autopilot_stop": ["rihmasto autopilot stop {pid} " + SIGNED],
    "health_run": ["rihmasto checks history {pid}"], "checks": ["rihmasto checks list {pid}"],
    "automations_open": ["rihmasto automations list"], "automations": ["rihmasto automations list"],
    "log_signal": ['rihmasto signal log --text "the need, in the words it came in" --channel chat --source cockpit'],
    "square": ["rihmasto square"],
}
# A command that names a verdict says which: the verdicts are the card's own.
VERDICT_SLOT = "<verdict>"


def asks_howto(question: str) -> bool:
    return bool(HOWTO.search(question or ""))


def named_project(factory: Any, question: str, current: str | None) -> Any:
    """Another project the question names by its title (whole words, case aside), or None."""
    low = f" {re.sub(r'[^a-z0-9åäö]+', ' ', (question or '').lower())} "
    best = None
    for p in factory.projects():
        title = re.sub(r"[^a-z0-9åäö]+", " ", str(p.meta.get("title") or "").lower()).strip()
        if p.pid == current or p.pid.startswith("_") or len(title) < 4 or f" {title} " not in low:
            continue
        if best is None or len(title) > len(str(best.meta.get("title") or "")):
            best = p
    return best


def scope_of(factory: Any, question: str, pid: str | None) -> tuple[str | None, bool]:
    """The project a question is about: another project it names by its title (and that it switched), else ``pid``."""
    named = named_project(factory, question, pid)
    return (named.pid, True) if named is not None else (pid, False)


def finish(out: dict[str, Any], question: str, *, factory: Any, pid: str | None, view: str | None, switched: bool,
           person: str, persona: str, label: Any) -> dict[str, Any]:
    """The answer made practical (``practical``) with the scope it was given in: the project and its title, the view
    (none once the question switched project), and whether it switched."""
    project = factory.project(pid) if pid else None
    out = practical(out, question, project=project, person=person, persona=persona)
    title = label(pid, project.meta.get("title", pid)) if project is not None else None
    out["scope"] = {"project": pid, "title": title, "view": None if switched else view, "switched": switched}
    return out


def _open_card(project: Any, persona: str) -> tuple[str | None, list[str]]:
    from kernel.canon import Canon

    try:
        cards = Canon(project).cards(state="open", persona=persona)
    except (OSError, ValueError, KeyError):
        return None, []
    c = next((c for c in cards if c.get("kind") != "question"), None)
    return (c["id"], list(c.get("verdicts") or [])) if c else (None, [])


def _open_question(project: Any) -> str | None:
    from kernel.canon import Canon

    try:
        return next((q["id"] for q in Canon(project).questions() if q.get("status") == "open"), None)
    except (OSError, ValueError, KeyError, AttributeError):
        return None


def fill(text: str, values: dict[str, str]) -> str:
    """Every placeholder whose value is known, filled in: <pid>, <your name>, "Your Name", --person Aino."""
    out = str(text or "")
    if values.get("pid"):
        out = re.sub(r"<\s*(?:pid|project(?:[ _-]id)?)\s*>", values["pid"], out, flags=re.I)
    if values.get("person"):
        out = re.sub(r"<\s*(?:your[ _-]name|name|person)\s*>", values["person"], out, flags=re.I)
        out = re.sub(r'"Your Name"|Your Name\b', values["person"], out)
        out = re.sub(r"--person\s+(?:Aino|Ilkka|Pekka|Sanna|Tester)\b", f'--person "{values["person"]}"', out)
    if values.get("persona"):
        out = re.sub(r"<\s*(?:persona|p)\s*>", values["persona"], out, flags=re.I)
    return out


def _commands(ids: list[str], values: dict[str, str]) -> list[str]:
    out: list[str] = []
    for mid in ids:
        for cmd in COMMANDS.get(mid, []):
            need = set(re.findall(r"\{(\w+)\}", cmd))
            if any(not values.get(k) for k in need):
                continue            # a value not known: the command is left out, never shown with a placeholder
            line = cmd.format(**values)
            if VERDICT_SLOT in line:
                verdicts = values.get("verdicts") or ""
                if not verdicts:
                    continue
                line = line.replace(VERDICT_SLOT, verdicts.split(",")[0])
            if line not in out:
                out.append(line)
        if out:
            break                   # the commands of the best match only
    return out[:2]


def _where(ids: list[str]) -> tuple[str, str]:
    from kernel.assistant_rules import ui_map

    items = {i["id"]: i for i in ui_map()["views"] + ui_map()["controls"]}
    item = next((items[i] for i in ids if i in items), None)
    if not item:
        return "", ""
    if item.get("route"):
        return item["label"], ""
    return str(item.get("where") or ""), f"Press {item['label']}: it {item['does']}"


# The capsule each project view is in (cockpit/static/capsules.js), so a step names the path a person clicks.
CAPSULE = {"overview": "Now", "inbox": "Now", "review": "Now", "questions": "Now", "plan": "Now", "spec": "Build",
           "tasks": "Build", "changes": "Build", "align": "Build", "console": "Build", "assumptions": "Build",
           "assessment": "Build", "cell": "Build", "releases": "Run", "outputs": "Run", "checks": "Run",
           "automations": "Run", "try": "Run", "evidence": "Govern", "track": "Govern", "insights": "Govern",
           "ledger": "Govern", "agents": "Agents", "aitools": "Agents"}


def _open_step(nav: dict[str, Any], where: str, project: Any) -> str:
    """Where to go, as the path a person clicks: "Open Loans › Build › Alignment"."""
    from kernel.assistant_rules import ui_map

    route = str(nav.get("route") or "")
    views = {v["id"]: v for v in ui_map()["views"]}
    parts = route.lstrip("#/").split("/")
    if route == "#/projects" and project is None:
        return "Open Projects and pick the project (Take me there opens Projects)."
    if parts[:1] == ["p"] and len(parts) > 1:
        view = parts[2] if len(parts) > 2 else "overview"
        title = str(project.meta.get("title")) if project is not None else parts[1]
        label = (views.get(view) or {}).get("label", view)
        return f"Open {title} › {CAPSULE.get(view, 'Now')} › {label} (Take me there opens it)."
    page = next((v for v in views.values() if v.get("route") == route), None)
    if page:
        return f"Open {page['label']} (Take me there opens it)."
    w = where if where.split(" ", 1)[0].lower() in ("the", "a", "an") else "the " + where
    return f"Find it in {w} (Take me there shows it)."


def _values(project: Any, person: str, persona: str) -> dict[str, str]:
    """What a command may be filled in with: the project's id, the person, the persona, an open card and question."""
    values = {"pid": project.pid if project is not None else "", "person": (person or "").strip(),
              "persona": persona or ""}
    if project is not None:
        card, verdicts = _open_card(project, persona)
        values.update(card=card or "", verdicts=",".join(verdicts), question=_open_question(project) or "")
    return values


def _sayer(values: dict[str, str], where: str, project: Any) -> Any:
    """A text with its placeholders filled, a snapshot sentence turned into where to look, and a command for one
    project asked about none turned into how to get it."""
    look = f" Look in {where or 'the project Overview'}: it shows what is recorded there."
    ask = "its command (open the project and ask again: it is filled in)"

    def said(text: str) -> str:
        text = NO_SNAPSHOT.sub(lambda m: look, fill(text, values)).strip()
        if project is None:
            text = re.sub(r"`[^`]*<\s*pid\s*>[^`]*`", ask, text)
        return text
    return said


def _fill_plan(plan: dict[str, Any], said: Any, values: dict[str, str]) -> None:
    """A goal's plan (kernel/copilot.py): its steps are the actions, one click each, their words filled in."""
    for s in plan.get("steps") or []:
        for k in ("title", "detail"):
            if isinstance(s.get(k), str):
                s[k] = said(s[k])
        act = s.get("action") or {}
        if isinstance(act.get("command"), str):
            act["command"] = fill(act["command"], values)


def _terminal_step(ids: list[str], values: dict[str, str], project: Any) -> dict[str, Any] | None:
    cmds = _commands(ids, values)
    if cmds:
        verdicts = values.get("verdicts") or ""
        names_card = bool(values.get("card")) and any(f" {values['card']} " in c for c in cmds)
        choose = f" (the verdict is yours: {', '.join(verdicts.split(','))})" if names_card and verdicts else ""
        return {"text": f"Or from a terminal, in the folder Rihmasto runs from{choose}:", "commands": cmds}
    if project is None and any(COMMANDS.get(i) for i in ids):
        return {"text": "Open the project you mean first (Projects, or name it in your question): "
                        "the steps then name it."}
    return None


def _steps(ids: list[str], nav: dict[str, Any], values: dict[str, str], project: Any,
           said: Any) -> list[dict[str, Any]]:
    where, press = _where(ids)
    steps: list[dict[str, Any]] = []
    if nav.get("route") or nav.get("control"):
        steps.append({"text": _open_step(nav, where, project), "action": "navigate"})
    if press:
        steps.append({"text": said(press.rstrip(".") + ".")})
    terminal = _terminal_step(ids, values, project)
    if terminal:
        steps.append(terminal)
    if not values["person"] and any("{person}" in c for i in ids for c in COMMANDS.get(i, [])):
        steps.append({"text": "Set your name in the person chip (top right): every signed step carries it."})
    return steps


def practical(out: dict[str, Any], question: str, *, project: Any, person: str, persona: str) -> dict[str, Any]:
    """The answer with every known placeholder filled, "the snapshot does not show" replaced by where to look, and,
    for a how-to question, numbered steps for this project with their commands and the action that opens it."""
    values = _values(project, person, persona)
    nav = out.get("navigate") or {}
    ids = ([str(nav["control"])] if nav.get("control") else []) + [str(m) for m in out.get("matches") or [] if m]
    said = _sayer(values, _where(ids)[0], project)
    out["answer"] = said(str(out.get("answer") or ""))
    if isinstance(out.get("plan"), dict):
        _fill_plan(out["plan"], said, values)
        return out
    if asks_howto(question):
        steps = _steps(ids, nav, values, project, said)
        if steps:
            out["steps"] = steps
    return out
