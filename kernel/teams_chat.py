"""Ask Rihma about teams, the words a team or a project gives Rihmasto's terms, and where a setting is set, by rule and
without a model (FR-TM1, FR-TM2, FR-TM3). Whatever the cockpit does with a click, this does by asking.

- "which team is this project in?", "who is in my team?", "list the teams": the team, its members and projects;
- "move this project to the platform team", "create a team called Platform": a proposal (``team_move``,
  ``team_create``) with the preview's lines; the person confirms it, signed;
- "what do we call a requirement here?", "which terms differ?": each term with the shipped meaning, the team's, the
  project's and which is in force;
- "call a requirement a story", "say check instead of criterion for the team", "add the synonym brief for request",
  "hide the comment term", "add a term brief that means request", "undo the last change of words": a proposal
  (``vocab_set``, ``vocab_undo``) to confirm. The team's words by default; "in this project" keeps it to the project;
- "where is the enforcement level set?", "what applies where?": the scopes it may be set at, where its value comes
  from for this project, and a link to change it (kernel/scope_table.py);
- a question that uses a word a team gave a term ("where are stories?") is read as the shipped word, so the map
  finds it.

Who may change what is the people's rule (IT for a team, IT or the project's owner for a project); the answer says so
and the assistant writes nothing itself.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import graph_words_chat as graph_words
from kernel import scope_table, structure_chat, teams, vocab, vocab_edit, vocab_say
from kernel.enforcement_chat import REASON, reason_of

_low = structure_chat._low
_real = structure_chat._project       # the project in view, never Rihmasto's own

_W = r"[\w'’ -]"
TEAM_Q = re.compile(r"\b(?:which|what)\s+team\b|\bwho(?:'s|\s+is|\s+are)\s+in\s+(?:my|our|the|this)\s+team\b"
                    r"|\bwho\s+is\s+in\s+(?:team\s+)?\w+|\b(?:list|show)\s+(?:the\s+|my\s+|our\s+)?teams\b"
                    r"|\bteams?\s+(?:do\s+(?:we|i)\s+have|are\s+there)\b|\bmy\s+team\b.*\bmembers?\b")
MOVE = re.compile(rf"\b(?:move|put|assign)\b(?P<what>.*?)\b(?:to|into)\s+(?:the\s+)?(?:team\s+)?(?P<team>{_W}+?)"
                  r"(?:\s+team)?\s*$")
CREATE = re.compile(rf"\b(?:create|make|add|start)\s+(?:a\s+|the\s+)?(?:new\s+)?team\s*(?:called|named)?\s*"
                    rf"(?P<name>{_W}+?)\s*$")
SET = (re.compile(rf"\b(?:call|rename|name)\s+(?:the\s+|a\s+|an\s+)?(?P<old>{_W}+?)\s+(?:a|an|as|to|the)\s+"
                  rf"(?P<new>{_W}+?)" r"\s*(?:\b(?:for|in|only|here)\b.*)?$"),
       re.compile(rf"\bsay\s+(?P<new>{_W}+?)\s+instead\s+of\s+(?P<old>{_W}+?)\s*(?:\b(?:for|in|here)\b.*)?$"))
SYNONYM = re.compile(rf"\badd\s+(?:the\s+)?synonym\s+(?P<new>{_W}+?)\s+(?:for|to)\s+(?:the\s+)?(?P<old>{_W}+?)"
                     r"\s*(?:\b(?:for|in|here)\b.*)?$")
CUSTOM = re.compile(rf"\badd\s+(?:a\s+)?(?:custom\s+)?term\s+(?P<new>{_W}+?)\s+(?:that\s+)?means?\s+"
                    rf"(?:a\s+|an\s+|the\s+)?(?P<old>{_W}+?)\s*$")
HIDE = re.compile(rf"\bhide\s+(?:the\s+)?(?P<old>{_W}+?)(?:\s+term)?\s*(?:\b(?:for|in|from|here)\b.*)?$")
SHOW_AGAIN = re.compile(rf"\b(?:show|unhide)\s+(?:the\s+)?(?P<old>{_W}+?)(?:\s+term)?\s+again\b")
UNDO = re.compile(r"\bundo\b.*\b(?:words?|wording|vocabulary|terms?|team change|rename)\b")
VOCAB_Q = re.compile(r"\bvocabulary\b|\bwhat\s+do\s+(?:we|i)\s+call\b|\bwhich\s+terms\b"
                     r"|\bhow\s+are\s+(?:the\s+)?terms\b"
                     r"|\bwhat\s+(?:is|are)\s+(?:a\s+|an\s+|the\s+)?\w[\w ]*?\s+called\b"
                     r"|\bterms?\s+(?:differ|redefined)\b")
GENERIC_WHERE = r"\bwhat\s+applies\s+where\b|\bwhich\s+settings\b|\bper\s+(?:project|team)\b|\bscope\s+of\b"
WHERE_Q = re.compile(r"\bwhere\s+(?:is|are|do\s+i\s+set|can\s+i\s+(?:set|change))\b"
                     r".*\b(?:set|configured?|changed?|defined)\b|" + GENERIC_WHERE + r"|\bsettings?\s+scope\b")
HERE_SCOPE = ("in this project", "for this project", "only here", "just here", "this project only", "in this one")




def asks(question: str) -> str | None:
    """Which question it is (``team``, ``move``, ``create``, ``vocab_set``, ``vocab_undo``, ``vocab``, ``where``) or
    None. A change of words is only taken when the term it names is known (checked in ``answer``)."""
    low = _low(question)
    plain = REASON.sub("", low).strip()
    checks = (("create", CREATE), ("move", MOVE), ("vocab_undo", UNDO), ("where", WHERE_Q), ("team", TEAM_Q),
              ("vocab", VOCAB_Q))
    if any(p.search(plain) for p in (*SET, SYNONYM, CUSTOM, HIDE, SHOW_AGAIN)):
        return "vocab_set"
    if graph_words.asks(plain):
        return "graph_words"                                      # which terms are hidden, which words it reads in
    moving = "team" in plain and "team mode" not in plain          # "switch to team mode" is People and access's
    return next((k for k, p in checks if p.search(plain) and (k != "move" or moving)), None)


def _out(answer: str, steps: list[dict[str, Any]], nav: dict[str, Any] | None,
         propose: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"answer": answer, "steps": steps, "navigate": nav, "propose": propose or [], "dropped": [],
            "sources": [], "by": "rule", "matches": ["teams"]}


def _step(text: str, route: str | None = None, control: str | None = None) -> dict[str, Any]:
    return {"text": text, "action": "navigate", **({"route": route, "control": control} if route else {})}


def _project_named(factory: Any, project: Any, text: str) -> Any:
    """The project meant: the one open, or the one whose title the words contain."""
    low = _low(text)
    titled = [p for p in factory.projects() if str(p.meta.get("title") or "").lower() in low and p.meta.get("title")]
    return titled[0] if len(titled) == 1 and ("this project" not in low or project is None) else project


def _may(setters: tuple[str, ...], persona: str, holding: tuple[str, ...] | None) -> bool:
    return persona in setters or any(p in setters for p in holding or ())


# -- teams ---------------------------------------------------------------------------------------------------

WHO_IN = re.compile(rf"\bwho(?:'s|\s+is|\s+are)\s+in\s+(?:the\s+|team\s+)?(?P<name>{_W}+?)(?:\s+team)?\s*\??$")
OWN_WORDS = ("my", "our", "this", "the", "that")


def named_team_answer(factory: Any, question: str) -> dict[str, Any] | None:
    """Who is in (and which projects are in) the team the question names; None when it names no team of its own."""
    m = WHO_IN.search(REASON.sub("", _low(question)).strip())
    name = m.group("name").strip() if m else ""
    if not name or name in OWN_WORDS or any(name.startswith(w + " ") for w in OWN_WORDS):
        return None
    found = teams.find(factory, name)
    nav = {"route": "#/settings", "control": "teams_page"}
    if found is None:
        names = ", ".join(t["name"] for t in teams.all_teams(factory))
        return _out(f"There is no team called {name}. The teams are {names}.", [], nav)
    row = teams._row(factory, found)
    who = ", ".join(row["members"]) or "nobody yet"
    mine = ", ".join(p["title"] for p in row["projects"]) or "no project yet"
    return _out(f"{row['name']}: {who}. Its projects: {mine}.", [_step("Open Settings > Teams to see each team's "
                                                                      "people and projects.", "#/settings",
                                                                      "teams_page")], nav)


def team_answer(factory: Any, project: Any, question: str = "") -> dict[str, Any]:
    named = named_team_answer(factory, question) if question else None
    if named is not None:
        return named
    d = teams.describe(factory)
    if project is not None:
        t = teams.of_project(factory, project)["team"]
        who = ", ".join(t["members"]) or "nobody yet"
        solo = " It is your own team, made for you: there is nothing to set up." if d["solo"] else ""
        steps = [] if d["solo"] else [_step("Open the project's settings to move it to another team: the preview comes "
                                             "first (Take me there opens it).", f"#/p/{project.pid}/overview",
                                             "teams_move")]
        return _out(f"{project.meta.get('title') or project.pid} is in {t['name']} (members: {who}).{solo}", steps,
                    {"route": f"#/p/{project.pid}/overview", "control": "teams_move"})
    rows = "; ".join(f"{t['name']}: {', '.join(t['members']) or 'nobody yet'} "
                     f"({len(t['projects'])} project{'s' if len(t['projects']) != 1 else ''})" for t in d["teams"])
    steps = [_step("Open Settings > Teams to see each team's projects and move one (Take me there opens it).",
                   "#/settings", "teams_page")]
    return _out(f"Teams: {rows}.", steps, {"route": "#/settings", "control": "teams_page"})


def move_answer(factory: Any, project: Any, question: str, persona: str, may: bool) -> dict[str, Any]:
    low = _low(question)
    plain = REASON.sub("", low).strip()
    m = MOVE.search(plain)
    project = _project_named(factory, project, m.group("what") if m else "")
    there = teams.find(factory, m.group("team")) if m else None
    if project is None:
        return _out("Open the project first, or name it: \"move Loans to the platform team\".", [], None)
    if there is None:
        names = ", ".join(t["name"] for t in teams.all_teams(factory))
        return _out(f"There is no team called that. The teams are {names}. Ask me to create one (\"create a team "
                    "called Platform\"), then move the project.", [], {"route": "#/settings", "control": "teams_page"})
    seen = teams.preview(factory, project=project.pid, to=there["id"])
    lines = " ".join(seen["lines"])
    if not seen["changes"]:
        return _out(lines, [], {"route": f"#/p/{project.pid}/overview", "control": "teams_move"})
    if not may:
        return _out(f"{lines} IT or the project's owner moves a project, on the view I open.",
                    [_step("Ask one of them, or switch persona if you hold one.")],
                    {"route": f"#/p/{project.pid}/overview", "control": "teams_move"})
    reason = reason_of(question) or f"asked in Ask Rihma: {question.strip()[:240]}"
    prop = {"action": "team_move", "why": lines, "persona": persona, "project": project.pid,
            "args": {"project": project.pid, "team": there["id"], "team_name": there["name"], "reason": reason}}
    return _out(f"{lines} I can make the change; you confirm it, signed with your name. You can undo it after.",
                [_step("Confirm the proposal below, or open the project's settings to change it first.")],
                {"route": f"#/p/{project.pid}/overview", "control": "teams_move"}, [prop])


def create_answer(question: str, persona: str, may: bool) -> dict[str, Any]:
    m = CREATE.search(REASON.sub("", _low(question)).strip())
    said = " ".join(question.split())
    name = said[m.start("name"):m.end("name")].strip(" .") if m else ""
    if not name:
        return _out("Say the name: \"create a team called Platform\".", [], None)
    if not may:
        return _out(f"IT defines a team ({name}), on the Teams page I open.", [], {"route": "#/settings",
                                                                                   "control": "teams_set"})
    prop = {"action": "team_create", "why": f"A team called {name} is made.", "persona": persona, "project": None,
            "args": {"name": name, "reason": reason_of(question) or f"asked in Ask Rihma: {said[:240]}"}}
    return _out(f"A team called {name} is made. You confirm it, signed with your name; you can undo it.",
                [_step("Then move a project into it from Settings > Teams or its settings.")],
                {"route": "#/settings", "control": "teams_set"}, [prop])


# -- the words -----------------------------------------------------------------------------------------------

def _term_of(eff: dict[str, Any], words: str) -> str | None:
    """The term the words name: its word in force, its shipped word or a synonym; kinds before relations."""
    found = vocab.match(eff, words)
    return next(iter(sorted(found, key=lambda t: ("kind", "custom", "rel", "attr").index(t.split(":")[0]))), None)


def _scope(question: str, project: Any, factory: Any) -> tuple[str, str]:
    low = _low(question)
    if project is not None and any(w in low for w in HERE_SCOPE):
        return "project", project.pid
    team = teams.team_of(factory, project) if project is not None else teams.AUTO_ID
    return "team", team


def _fields(m: re.Match[str], kind: str, eff: dict[str, Any], term: str) -> dict[str, Any]:
    """The change the words ask for: a new label, a synonym, hiding or showing, or a custom term's label and kind."""
    new = " ".join(m.groupdict().get("new", "").split()).strip(" .")
    label = new[:1].upper() + new[1:]
    if kind in ("hide", "show"):
        return {"hidden": True if kind == "hide" else None}
    if kind == "synonym":
        return {"synonyms": [*(eff["terms"][term]["synonyms"]), new]}
    return {"label": label, "means": term} if kind == "custom" else {"label": label}


def _parse_set(question: str) -> tuple[str, re.Match[str]] | None:
    plain = REASON.sub("", question.strip()).strip().lower()
    for kind, pats in (("rename", SET), ("synonym", (SYNONYM,)), ("custom", (CUSTOM,)), ("hide", (HIDE,)),
                       ("show", (SHOW_AGAIN,))):
        found = next((m for m in (p.search(plain) for p in pats) if m), None)
        if found:
            return kind, found
    return None


def vocab_set_answer(factory: Any, project: Any, question: str, persona: str, holding: tuple[str, ...] | None
                     ) -> dict[str, Any] | None:
    parsed = _parse_set(question)
    if parsed is None:
        return None
    kind, m = parsed
    scope, owner = _scope(question, project, factory)
    eff = vocab.effective(factory, project if scope == "project" else None, owner if scope == "team" else None)
    term = _term_of(eff, m.group("old"))
    if term is None or (kind == "custom" and not term.startswith("kind:")):
        return None            # not a term of Rihmasto's (or not a kind of record): another answerer may take it
    fields = _fields(m, kind, eff, term)
    term = None if kind == "custom" else term           # a custom term is new: it gets its id from its label
    try:
        seen = vocab_edit.preview(factory, scope, owner, term=term, fields=fields)
    except ValueError as exc:
        return _out(f"That change of words cannot be made: {exc}.", [], None)
    return _set_proposal(factory, project, question, persona, holding, (scope, owner, term, fields, seen))


def _set_proposal(factory: Any, project: Any, question: str, persona: str, holding: tuple[str, ...] | None,
                  plan: tuple[str, str, str | None, dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    scope, owner, term, fields, seen = plan
    lines = " ".join(seen["lines"])
    nav = ({"route": f"#/p/{project.pid}/vocabulary", "control": "vocab_project"} if scope == "project" and project
           else {"route": "#/settings", "control": "vocab_team"})
    where = "this project" if scope == "project" else "the whole team (say \"in this project\" to keep it to one)"
    if not seen["changes"]:
        return _out(lines, [], nav)
    if not _may(vocab_edit.SETTERS[scope], persona, holding):
        who = "IT or the project's owner" if scope == "project" else "IT"
        return _out(f"{lines} {who} changes these words, on the view I open.",
                    [_step("Ask them, or switch persona if you hold one.")], nav)
    reason = reason_of(question) or f"asked in Ask Rihma: {' '.join(question.split())[:240]}"
    args = {scope: owner, "term": term, **fields, "reason": reason}
    prop = {"action": "vocab_set", "why": lines, "persona": persona, "project": owner if scope == "project" else None,
            "args": args}
    return _out(f"For {where}: {lines} Nothing stored is rewritten: records are only read in these words. You confirm "
                "it, signed with your name; Undo gives the earlier reading back.",
                [_step("Confirm the proposal below, or open the Vocabulary to change it first.")], nav, [prop])


def _undo_target(factory: Any, project: Any) -> tuple[str, str, list[dict[str, Any]]]:
    """Where the newest change of words is: the project's own, else its team's."""
    if project is not None:
        own = vocab_edit._stack(factory, "project", project.pid)
        if own:
            return "project", project.pid, own
    team = teams.team_of(factory, project) if project is not None else teams.AUTO_ID
    return "team", team, vocab_edit._stack(factory, "team", team)


def vocab_undo_answer(factory: Any, project: Any, persona: str, holding: tuple[str, ...] | None) -> dict[str, Any]:
    scope, owner, stack = _undo_target(factory, project)
    if not stack:
        return _out("There is no change of words to undo here.", [], None)
    last = stack[-1]
    if not _may(vocab_edit.SETTERS[scope], persona, holding):
        return _out(f"The last change was {last['term']}; IT or the owner undoes it, on the view I open.", [], None)
    prop = {"action": "vocab_undo", "why": f"{last['term']} reads as it did before.", "persona": persona,
            "project": owner if scope == "project" else None, "args": {scope: owner}}
    by = last.get("by") or "a person"
    return _out(f"The last change of words here was {last['term']} by {by}. I can undo it; you "
                "confirm it, signed. It stays in the record.", [], {"route": "#/settings", "control": "vocab_undo"},
                [prop])


def vocab_answer(factory: Any, project: Any, question: str) -> dict[str, Any]:
    eff = _eff(factory, project)
    asked = vocab.match(eff, REASON.sub("", _low(question)))
    rows = [eff["terms"][t] for t in asked] or vocab.differs(eff)
    nav = ({"route": f"#/p/{project.pid}/vocabulary", "control": "vocab_project"} if project is not None
           else {"route": "#/settings", "control": "vocab_team"})
    if not rows:
        return _out("Every term reads as Rihmasto ships it: nothing is redefined for this team or project. Ask me to "
                    "\"call a requirement a story\" to change one.", [_step("Open the Vocabulary to see each term "
                    "(Take me there opens it).", nav["route"], nav["control"])], nav)
    said = "; ".join(_said(r) for r in rows[:8])
    return _out(said + ".", [_step("Open the Vocabulary: each term with its shipped meaning, the team's, the "
                                    "project's and which is in force.", nav["route"], nav["control"])], nav)


def _said(r: dict[str, Any]) -> str:
    where = vocab.SCOPE_WORD[r["scope"]]
    shipped = (r["shipped"] or {}).get("label")
    extra = f", shipped as {shipped}" if shipped and shipped != r["label"] else ""
    since = f", defined on {str(r['since'])[:10]}" if r.get("since") else ""
    return f"{r['label']} ({vocab.TYPE_WORD[r['type']]}; {where}{extra}{since})"


# -- where is it set -----------------------------------------------------------------------------------------

def _generic_where(factory: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    per = ", ".join(r["label"] for r in rows if r["set_per_project"])
    wide = ", ".join(r["label"] for r in rows if not r["set_per_project"])
    scopes = ("the shipped default, all your projects, or this project" if teams.is_solo(factory) else
              "the shipped default, all teams (one setting every team shares), a team's own words, or this project")
    return _out(f"A setting is set at one of these scopes: {scopes}. Set per project (over the wider setting): "
                f"{per}. Set once for everything, or shipped only: {wide}.",
                [_step("Open Settings > What applies where for each setting's scope and where its value comes "
                       "from here.", "#/settings", "scope_view")], {"route": "#/settings", "control": "scope_view"})


def where_answer(factory: Any, project: Any, question: str) -> dict[str, Any]:
    rows = scope_table.rows(factory, project)
    low = _low(question)
    generic = re.search(GENERIC_WHERE, low)
    hit = None if generic else next((r for r in rows if any(w in low for w in _names(r))), None)
    if hit is None:
        return _generic_where(factory, rows)
    link = hit["change_for_project"] or hit["change_for_team"]
    steps = [_step(f"Change it {'for this project' if hit['change_for_project'] else 'for the team'} (Take me there "
                   "opens it).", link["route"], link["control"])] if link else []
    return _out(f"{hit['label']} can be set at: {', '.join(w.lower() for w in hit['scope_words'])}. Here: "
                f"{hit['source_word']}.", steps, link and {"route": link["route"], "control": link["control"]})


def _names(row: dict[str, Any]) -> list[str]:
    words = [row["id"].replace("_", " "), row["label"].lower().split(":")[0].split(" and ")[0]]
    return [w for w in words if len(w) > 3]


# -- the entry -----------------------------------------------------------------------------------------------

def translated(factory: Any, project: Any, question: str) -> tuple[str, list[str]]:
    """The question with a word a team gave a term said as the shipped one, and the terms found (so the map, which
    knows the shipped words, still finds "stories")."""
    eff = _eff(factory, project)
    found = [t for t in vocab.match(eff, question) if eff["terms"][t]["scope"] != "shipped"]
    extra = [w for w in (_shipped_word(eff, eff["terms"][t]) for t in found) if w]
    return (question + " " + " ".join(extra)).strip(), found


def _eff(factory: Any, project: Any) -> dict[str, Any]:
    return vocab.effective(factory, project) if project is not None else vocab.context(factory, None,
                                                                                     factory.projects())


def _shipped_word(eff: dict[str, Any], row: dict[str, Any]) -> str:
    """The word Rihmasto ships for a term, or for the kind a custom term means."""
    target = row if row["shipped"] else eff["terms"].get(str(row["means"] or ""))
    return str(((target or {}).get("shipped") or {}).get("label") or "")


def term_answer(factory: Any, project: Any, question: str, persona: str) -> dict[str, Any] | None:
    from kernel.assistant import from_map

    said, found = translated(factory, project, question)
    if not found or said == question:
        return None
    eff = _eff(factory, project)
    mapped = from_map(said, project, factory=factory, persona=persona)
    own = _said(eff["terms"][found[0]])
    rest = vocab_say.for_project(factory, project, mapped["answer"])         # in the words in force, not the shipped
    return mapped | {"answer": f"{own}. {rest}", "by": "rule", "matches": ["teams", *mapped["matches"]]}


def answer(factory: Any, question: str, project: Any, persona: str,
           holding: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    """The answer, or None when the question is not about teams, words or where a setting is set."""
    project = _real(project)
    kind = asks(question)
    if kind is None:
        return term_answer(factory, project, question, persona)
    if kind == "team":
        return team_answer(factory, project, question)
    if kind == "move":
        return move_answer(factory, project, question, persona, _may(teams.MOVERS, persona, holding))
    if kind == "create":
        return create_answer(question, persona, _may(teams.ADMINS, persona, holding))
    if kind == "where":
        return where_answer(factory, project, question)
    if kind == "graph_words":
        text, nav = graph_words.answer(factory, project)
        return _out(text, [_step("Open the Knowledge graph: its notes say the same (Take me there opens it).",
                                 nav["route"], nav["control"])], nav)
    if kind == "vocab_undo":
        return vocab_undo_answer(factory, project, persona, holding)
    if kind == "vocab_set":
        return vocab_set_answer(factory, project, question, persona, holding)
    return vocab_answer(factory, project, question)
