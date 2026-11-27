"""A useful agent channel (FR-CHN2): Rihma puts a person's question to a coding agent, and guides with next steps.

The owner (2026-11-26), on an adopted project: "not sure yet what should I expect from this chat." In the channel
they had asked Rihma to consult Claude Code on how to sync with Rihmasto and what to monitor, and were told twice
that it could not. Here, for any project:

- ``head``: what the channel is for, who is connected to it (the coding agents that posted in it) and how an agent
  reads it, for the channel's head in the cockpit;
- ``consult``: a person asks Rihma to consult, ask or check with a coding agent (by name, "the agent", "Claude
  Code"). Rihma posts the question addressed to that agent in the channel and tells the person what it did, how the
  agent sees it (``rihma_channel_read`` over MCP lists it under ``asked_agents``; the session-start hook
  ``rihmasto ide <pid> --section`` lists it under "Questions for you") and what it can say now from the records.
  With no agent connected it says how to connect one, with a button;
- ``sync_rule``: how to keep an adopted (or any) project in step with Rihmasto and what to monitor, by rule from
  its state: upstream change cards follow commits (the watch), the project's own sources fed in as material, the
  checks for its kind of work, the automations to schedule;
- ``actions``: the next steps from the real state as buttons on Rihma's answers (a waiting card, the watch, the
  project's own sources, the assessment, what the project waits for);
- ``whole``: records quoted whole, never cut mid-sentence: when they do not all fit, fewer are quoted and the rest
  are counted.

Only a person's message makes Rihma put a question to an agent, so two agents cannot set each other going.

FR-CHN3 keeps it holding up: only a request to Rihma asks an agent (kernel/channel_intent.py), a long question is
put to the agent shortened with the person's message named, the reply command the agent gets runs as written, an
agent's post answers a question only with reply_to, the buttons come from kernel/channel_buttons.py, and the sync
answer is short and names the baseline with a way to state the test command.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import agent_channel as ch
from kernel import channel_buttons, channel_guard, channel_intent

ANY = "coding-agent"           # a question for whichever coding agent reads the channel next
MAX_ACTIONS = channel_buttons.MAX_ACTIONS
BUDGET = 2400                  # the characters of quoted records one answer holds
HARNESSES = (("claude-code", "Claude Code", r"claude(?:[ -]?code)?"), ("cursor", "Cursor", r"cursor"),
             ("codex", "Codex", r"codex"), ("opencode", "OpenCode", r"open ?code"),
             ("copilot", "Copilot", r"copilot"), ("gemini", "Gemini CLI", r"gemini(?: cli)?"))
_GENERIC = r"(?:the|my|your|our|a|that|this) (?:coding |ide |terminal )?agent|coding agent|ide agent"
_AGENT = "|".join(rx for _, _, rx in HARNESSES) + "|" + _GENERIC
CONSULT = re.compile(r"\b(?:consult|ask|check with|confer with|run (?:it|this|that) (?:by|past)|"
                     r"put (?:it|this|that|the question|my question) to|get (?:an? )?(?:answer|opinion|view) from|"
                     rf"kysy|konsultoi)\b[\s,:]*(?:with |to |from )?(?P<agent>{_AGENT})\b", re.I)
SYNC = re.compile(r"\b(?:sync\w*|synchron\w*|in step|up to date|monitor\w*|watch(?:ing)?|keep track|"
                  r"what (?:should|to) (?:i |we )?(?:watch|monitor|track)|seuraa\w*|valvo\w*|synkr\w*)\b", re.I)
SETUP = ("Give the agent Rihmasto's MCP server: `rihmasto ide {pid}` prints the configuration for Claude Code, "
         "Cursor, Codex and OpenCode (docs/guides/configure-your-agents.md).",
         "Add the session-start hook `rihmasto ide {pid} --section` (or paste its output into AGENTS.md or "
         "CLAUDE.md), so each session starts with the questions waiting for the agent.",
         "Tell the agent to read this channel (`rihma_channel_read`) and answer here; its first post connects it.")


# -- quoting whole --------------------------------------------------------------------------------------------

def whole(items: list[tuple[str, str]], budget: int = BUDGET) -> tuple[str, list[str]]:
    """``(id, text)`` pairs quoted whole, as many as fit the budget (at least one), the rest counted by id."""
    said, ids, used = [], [], 0
    for rid, text in items:
        line = f"{rid} {' '.join(str(text).split())}".strip()
        if said and used + len(line) > budget:
            break
        said.append(line)
        ids.append(rid)
        used += len(line) + 2
    rest = len(items) - len(said)
    tail = f" And {rest} more: ask about one by its id." if rest else ""
    return "; ".join(said) + ("." if said and not said[-1].endswith(".") else "") + tail, ids


# -- who is connected ---------------------------------------------------------------------------------------

def connected(project: Any) -> list[dict[str, Any]]:
    """The coding agents that posted in the channel, the most recent first: name, harness, operator, last post."""
    seen: dict[str, dict[str, Any]] = {}
    for m in ch.read(project).get("messages") or []:
        a = m["author"]
        if a["kind"] == "agent":
            seen.pop(a["name"], None)
            seen[a["name"]] = {"name": a["name"], "harness": a.get("harness"), "operator": a.get("operator"),
                               "last": m["at"]}
    return list(reversed(seen.values()))


def _answered_ids(msgs: list[dict[str, Any]]) -> set[str]:
    """Message ids an agent answered: only those it replied to (refs.message). Naming an id in a post ("started
    on M-0013") answers nothing (FR-CHN3)."""
    out: set[str] = set()
    for m in msgs:
        if m["author"]["kind"] == "agent":
            ref = (m.get("refs") or {}).get("message")
            out.update([ref] if isinstance(ref, str) else ref or [])
    return out


def waiting(project: Any, name: str | None = None) -> list[dict[str, Any]]:
    """The questions put to coding agents that no agent answered yet (for ``name``: those to it or to any). A reply
    to Rihma's question, or to the person's message it puts to the agent, answers it."""
    msgs = ch.read(project).get("messages") or []
    done = _answered_ids(msgs)
    out = []
    for m in msgs:
        to = [t for t in m.get("to") or [] if t not in (*ch.RIHMA_ROLES, "rihma")]
        if to and _open_ask(m, done) and (name is None or name.lower() in to or ANY in to):
            out.append({"id": m["id"], "to": to, "at": m["at"], "text": m["text"]})
    return out


def _open_ask(m: dict[str, Any], done: set[str]) -> bool:
    """Whether ``m`` is a person's or Rihma's question that no agent answered (nor the message it asks for)."""
    asked_for = (m.get("refs") or {}).get("message") if m["author"]["kind"] == "rihma" else None
    return m["kind"] == "question" and m["author"]["kind"] in ("rihma", "person") and m["id"] not in done \
        and asked_for not in done


def section_lines(project: Any, limit: int = 15) -> list[str]:
    """The questions waiting for coding agents, for the section the session-start hook prints (kernel/ide.py)."""
    asked = waiting(project)
    if not asked:
        return []
    return ["", "### Questions for you in the agent channel (answer each there, with reply_to its id)", "",
            *[f"- {m['id']} (to {', '.join(m['to'])}): {' '.join(m['text'].split())}" for m in asked[:limit]]]


def head(project: Any) -> dict[str, Any]:
    """The channel's head: what it is for, who is connected, what waits on an agent, how agents read it."""
    agents = connected(project)
    return {"connected": agents, "waiting_on_agents": len(waiting(project)), "connect": None if agents
            else connect_action(project), "setup": [s.format(pid=project.pid) for s in SETUP],
            "reads": {"mcp": "rihma_channel_read", "hook": f"rihmasto ide {project.pid} --section"}}


def connect_action(project: Any) -> dict[str, Any]:
    """Where a person connects a coding agent: an adopted or attached project's IDE setup, else the hand-off."""
    from kernel.ide import kind_of

    if kind_of(project):       # the "Work on it from your IDE" card's data-id (aitools.js), so the button lands on it
        return {"label": "Connect a coding agent", "view": "aitools", "focus": "ide_setup", "control": "ide_section",
                "command": f"rihmasto ide {project.pid}"}
    return {"label": "Connect a coding agent", "view": "overview", "control": "handoff",
            "command": f"rihmasto ide {project.pid}"}


# -- asking an agent ----------------------------------------------------------------------------------------

def asks_an_agent(text: str) -> re.Match[str] | None:
    """The words asking Rihma to consult a coding agent, or None: only a request to Rihma, never a question about
    asking one ("what should I ask the agent?"; FR-CHN3, kernel/channel_intent.py)."""
    return channel_intent.request(CONSULT, text or "")


def target(project: Any, word: str) -> dict[str, Any]:
    """The agent a word names: a connected agent of that harness, the harness itself, or the last agent seen."""
    low = " ".join(word.lower().split())
    agents = connected(project)
    for slug, label, rx in HARNESSES:
        if re.fullmatch(rx, low):
            hit = next((a for a in agents if slug in (a["name"], *(str(a.get("harness") or "").lower().split()))
                        or a["name"].startswith(slug.split("-")[0])), None)
            return {"name": hit["name"] if hit else slug, "label": label, "agent": hit}
    if agents:
        return {"name": agents[0]["name"], "label": agents[0]["name"], "agent": agents[0]}
    return {"name": ANY, "label": "a coding agent", "agent": None}


def question_of(text: str, m: re.Match[str]) -> str:
    """The question itself, without the request to consult; "" when nothing is left to ask (FR-CHN3)."""
    return channel_intent.question(text, m)


def said_now(project: Any, question: str) -> str:
    """What Rihma can say now from the records about the question."""
    from kernel.channel_rihma import _next, by_rule

    ruled = by_rule(project, question)
    if ruled is not None:
        return ruled[0]
    return _next(project)[0]


def consult(project: Any, msg: dict[str, Any], m: re.Match[str]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Post the person's question to the agent; Rihma's answer to the person, its trace and its buttons."""
    who = target(project, m.group("agent"))
    question = question_of(msg["text"], m)
    if not question:        # nothing to ask: Rihma asks the person what to ask, and posts nothing (FR-CHN3)
        return (channel_intent.what_to_ask(who["label"]), {"basis": "rule", "rests_on": "the request named an agent "
                "and no question", "sources": [msg["id"]]}, [])
    asked = ch.post(project, author=ch.rihma("assistant"), kind="question", thread=msg["thread"],
                    refs={"message": msg["id"]}, text=ask_text(project, msg, who, question))
    hook = f"rihmasto ide {project.pid} --section"
    if who["agent"]:
        did = (f"I put your question to {who['label']} in this channel ({asked['id']}). It sees it over MCP in "
               "`rihma_channel_read` (under asked_agents) the next time it reads the channel, and at its next "
               f"session start through the hook `{hook}`, under Questions for you. Its answer comes back here as a "
               f"reply, signed for {who['agent'].get('operator')}.")
        acts: list[dict[str, Any]] = []
    else:            # one sentence and a button, not the setup steps (FR-CHN3): Connect a coding agent shows them
        did = (f"I put your question in this channel ({asked['id']}), addressed to {who['label']}. No coding agent "
               f"is connected to this project yet, so it waits here until one reads the channel: Connect a coding "
               f"agent shows how (`rihmasto ide {project.pid}` prints the setup).")
        acts = [connect_action(project)]
    said = channel_guard.fit(f"{did} Meanwhile, from the records: {said_now(project, question)}")
    trace = {"basis": "rule", "rests_on": f"the channel: a question put to {who['name']} ({asked['id']})",
             "sources": [asked["id"], msg["id"]]}
    return said, trace, actions(project, question, acts)


def ask_text(project: Any, msg: dict[str, Any], who: dict[str, Any], question: str) -> str:
    """Rihma's question to the agent: the person's question (shortened when it would not fit, the whole of it in
    their message) and how to answer, with a command that runs as written (FR-CHN3)."""
    asker = msg["author"].get("name") or "A person"
    name = who["name"] if who["agent"] else "<agent>"
    operator = str((who["agent"] or {}).get("operator") or "<your name>").replace('"', "'")
    how = (f"\nReply in this channel with reply_to {msg['id']}: `rihma_channel_post` over MCP with kind answer and "
           f"reply_to {msg['id']}, or `rihmasto channel {project.pid} post --as {name} --person \"{operator}\" "
           f"--persona developer --kind answer --reply-to {msg['id']} --text \"...\"`.")
    head = f"@{who['name']} {asker} asks, through Rihma: "
    room = ch.MAX_TEXT - len(head) - len(how)
    quoted = channel_guard.shorten(question, room - 60)
    if quoted != question:
        quoted += f" (The whole question is in {msg['id']}.)"
    return head + quoted + how


# -- syncing and monitoring, by rule -----------------------------------------------------------------------

def _commits(project: Any) -> tuple[str, list[dict[str, Any]]]:
    from kernel.ide import kind_of

    pid = project.pid
    if not kind_of(project):
        return ("Commits come back through `rihmasto workspace submit`, which meets the gate a builder cell meets; "
                "a change pushed elsewhere is seen by `rihmasto sync`.", [])
    from kernel import adopt_watch

    w = adopt_watch.view(project)
    if w["watching"]:
        return (f"Commits: {w['line']}; each upstream commit opens an \"Upstream changed: review\" card.", [])
    return ("Commits: not watched yet. Set up the watch and each upstream commit opens an \"Upstream changed: "
            f"review\" card (until then `rihmasto sync {pid}`).",
            [{"label": "Set up the watch", "view": "overview", "control": "watch_setup",
              "command": f"rihmasto sync {pid}"}])


def _sources(project: Any) -> tuple[str, list[dict[str, Any]]]:
    from kernel.project_material import material

    added = len(material(project)["added"])
    return (f"The project's own sources: {added} added since intake. Add its plan, hand-off notes, rule files, test "
            "results and findings file as material, so the requirements, tasks and findings follow them.",
            [{"label": "Add the project's own sources", "view": "overview", "control": "add_material",
              "command": f"rihmasto material add {project.pid} --path <file> --reintake"}])


def _baseline(project: Any) -> tuple[str, list[dict[str, Any]]]:
    """An adopted (or attached) project's baseline as it is, and a way to state its test command when it measured
    nothing."""
    from kernel.ide import kind_of

    if not kind_of(project):
        return "", []
    from kernel.adopted_state import _baseline as base_of

    b = base_of(project)
    if b["verdict"] != "not measured":
        return f"Baseline: {b['verdict']}" + (f" ({b['command']})." if b["command"] else "."), []
    tried = f" (tried {b['command']})" if b["command"] else ""
    return (f"Baseline: not measured{tried}. State the project's own test command and the baseline and its checks "
            "run it.",
            [{"label": "State the test command", "view": "console", "control": "console_settings"}])


def _checks(project: Any) -> tuple[str, list[dict[str, Any]]]:
    try:
        from kernel import checks
    except ImportError:
        return "Checks are not in this Rihmasto, so nothing is measured continuously.", []
    rows = checks.last_results(project)
    act = [{"label": "Open the checks", "view": "checks", "command": f"rihmasto checks list {project.pid}"}]
    if not rows:
        return "Checks: none has run yet; turn on in Health the ones that measure what it promises.", act
    failed = [r["check"] for r in rows if r.get("verdict") == "failed"]
    unmeasured = [r["check"] for r in rows if r.get("verdict") not in ("passed", "failed")]
    said = f"Checks: {len(rows)} ran last" + (f", failing: {', '.join(failed)}" if failed else ", none failing")
    said += f"; not measured: {', '.join(unmeasured)}" if unmeasured else ""
    return said + ".", act


def _automations(project: Any) -> tuple[str, list[dict[str, Any]]]:
    from kernel import automation_suggest

    try:
        s = automation_suggest.scan(project.factory, project.pid)
    except (KeyError, ValueError, OSError) as exc:
        return f"Automations: the suggestions could not be read ({type(exc).__name__}).", []
    offered = [x["label"] for x in s["suggestions"] if x.get("state") == "offered"]
    running = [x["label"] for x in s["suggestions"] if x.get("state") == "set_up"]
    more = f" and {len(offered) - 2} more" if len(offered) > 2 else ""
    said = ("Automations to schedule: " + "; ".join(offered[:2]) + more + "." if offered
            else "Automations: nothing more is suggested for it now.")
    said += f" Set up already: {len(running)}." if running else ""
    return said, [{"label": "Schedule the automations", "view": "automations",
                   "command": "rihmasto automations list"}] if offered else []


def sync_rule(project: Any) -> tuple[str, list[str], str, list[dict[str, Any]]]:
    """How to keep the project in step with Rihmasto and what to monitor: text, sources, basis, buttons."""
    parts = [_commits(project), _baseline(project), _sources(project), _checks(project), _automations(project)]
    said = " ".join(p[0] for p in parts if p[0]) + (" Coding agents stay in step over MCP (`rihma_next`, "
                                                    "`rihma_channel_read`) and the session-start hook.")
    acts = [a for _, x in parts for a in x]
    return said, ["watch", "baseline", "material", "checks", "automation suggestions"], "the project's watch, " \
        "baseline, material, checks and automation suggestions", acts


# -- next steps as buttons ------------------------------------------------------------------------------

def actions(project: Any, text: str = "", lead: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The next steps from the project's real state, as buttons (kernel/channel_buttons.py): the answer's own
    (``lead``, then the sync steps when asked about syncing) first, at most ``MAX_ACTIONS``, none twice."""
    first = list(lead or [])
    if SYNC.search(text or ""):
        first += sync_rule(project)[3]
    return channel_buttons.actions(project, first)
