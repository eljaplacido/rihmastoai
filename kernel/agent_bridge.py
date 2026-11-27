"""The agent bridge, Rihmasto to agents (FR-BRG1, docs/guides/agentic-help.md): a project's hand-off brief for a
coding agent, and how each agent takes it.

The brief (``brief``) carries what an agent needs to work on the project the way Rihmasto governs it:

- the goal or the change (a change card's text), and the accepted contract's criteria relevant to it;
- the open questions and assumptions, never answered here; the plan (the tasks and their state) and, for a goal,
  the steps of its plan (kernel/copilot.py);
- the assessment's findings, review feedback, the gates that failed and the checks that fail, and the insights that
  matter (drift, failing gates), each when this build has it;
- the project's own conventions (its AGENTS.md and the commands it states, kernel/ide.py when present), how to run
  the tests, and how to report back: the MCP tools and the agent channel (kernel/agent_channel.py).

``for_agent`` gives the agent-specific way to use it: a prompt file, the MCP configuration (Rihmasto's own server,
signed with the operator's name) and the command line (`claude -p`, `codex exec`, `opencode run`; Cursor reads the
prompt and its MCP file). Building the brief writes nothing; ``record`` notes that a person gave a hand-off, in the
ledger and the channel, never the brief's text in the ledger. Holdout scenarios are never in a brief.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from kernel import agent_channel as ch
from kernel.bridge_open import failed_gates, still_open, task_scope  # only open feedback is handed on
from kernel.copilot_catalog import optional

AGENTS = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "cursor": "Cursor",
          "generic": "any coding agent"}
MAX_CRITERIA = 40
MAX_ITEMS = 12
CONFIDENTIAL_SAID = ("**Confidential: local models only.** This project is confidential: its code, its data and this "
                     "brief never go to a hosted model or service. Work with a local model only; a coding agent on a "
                     "hosted model (Claude Code, Codex, OpenCode or Cursor with their usual models) sends the "
                     "repository to that host, so it is not used here.")
REPORT_BACK = [
    "Post what you did to the project's agent channel: `rihma_progress` over MCP (what you did, the files you "
    "touched, the criteria you believe you addressed), or `rihmasto channel {pid} post --as <agent> --kind progress "
    "--text \"...\" --person <operator> --persona developer` without MCP.",
    "Ask Rihma when something is unclear: `rihma_ask_rihma` (a criterion, why the gate failed, what is next).",
    "Never answer an open question yourself: `rihma_propose_answer` suggests one, and a person confirms it.",
    "When a commit is ready, `rihma_request_gate` asks the gate to check it; its result comes back in the channel.",
    "A new requirement is a decision: file it with `rihma_report_change` before you build it.",
]


def _criteria(project: Any, wanted: set[str]) -> list[dict[str, Any]]:
    contract = project.read("contract.json") or {}
    out = []
    for r in contract.get("requirements", []):
        if wanted and r["id"] not in wanted:
            continue
        for c in r.get("acceptance", []):
            out.append({"id": c["id"], "requirement": r["id"], "statement": r["statement"][:300],
                        "given": c.get("given"), "when": c.get("when"), "then": c.get("then")})
    return out[:MAX_CRITERIA]


def _change(project: Any, card_id: str | None) -> dict[str, Any] | None:
    from kernel.canon import Canon

    if not card_id:
        return None
    if re.fullmatch(r"T-\d{1,6}", card_id.upper()):     # a contract task handed on its own ("hand off T-002")
        return task_scope(project, card_id.upper())
    try:
        card = Canon(project).get_card(card_id.upper())
    except (KeyError, ValueError, OSError):      # never a bare id as the whole answer
        raise ValueError(f"No change {card_id.upper()} in this project: give the id of one of its change cards, "
                         "or leave Change empty") from None
    if card["kind"] != "change":
        raise ValueError(f"{card['id']} is a {card['kind']} card, not a change")
    payload = card.get("payload") or {}
    decision = card.get("decision") or {}
    return {"id": card["id"], "title": card["title"], "state": card["state"],
            "verdict": decision.get("verdict"), "deciders": list(card.get("deciders") or []),
            "text": str(payload.get("text") or card.get("body") or card["title"])[:4000],
            "requirements": list((card.get("refs") or {}).get("requirements") or [])}


def change_said(card: dict[str, Any]) -> list[str]:
    """A change's text, whether a person has decided it, and that it alone is the work (FR-RPJ1)."""
    lines = [card["text"], ""]
    if card.get("kind") == "task":
        return [*lines, f"The scope is this task alone: the project's other work below is context, not part of "
                        f"{card['id']}."]
    if card.get("state") != "decided":
        who = " or ".join(str(d).replace("_", " ") for d in card.get("deciders") or []) or "a person"
        lines.append(f"**Not decided yet**: {card['id']} waits on {who}. Do not build it until a person approves it: "
                     "prepare and propose only, and say so in your channel post.")
    elif card.get("verdict") not in (None, "accept"):
        lines.append(f"**Decided: {card['verdict']}**. Do not build it; ask a person what changed.")
    lines.append(f"The scope is this change alone: the project's other findings below are context, not part of "
                 f"{card['id']}.")
    return lines


def _findings(project: Any) -> list[str]:
    from kernel.assess import history, load, summary

    if not history(project):
        return []
    try:
        return [finding_said(f) for f in summary(load(project))["findings"]][:MAX_ITEMS]
    except (LookupError, OSError, KeyError, ValueError):
        return []


def finding_said(f: Any) -> str:
    """An assessment finding as a sentence an agent reads: its id, severity and area, what is wrong, where, and
    the suggested change (never the record's raw form)."""
    if not isinstance(f, dict):
        return str(f)
    head = f"{f.get('id') or '?'} ({', '.join(str(f[k]) for k in ('severity', 'perspective') if f.get(k))})"
    said = f"{head}: {f.get('title') or f.get('key') or ''}"
    said += f": {f['summary']}" if f.get("summary") else ""
    where = [str(e) for e in f.get("evidence") or []][:2]
    said += f" (evidence: {'; '.join(where)})" if where else ""
    return said + (f". Suggested: {f['suggestion']}" if f.get("suggestion") else "")


def insight_lines(found: dict[str, Any] | None) -> list[str]:
    """The insights that are measured, one line per lens ("health: at risk 0, failures 0"); a lens with nothing
    measured is left out."""
    out = []
    for lens, figures in (found or {}).items():
        if not isinstance(figures, dict):
            continue
        said = [f"{k.replace('_', ' ')} {v}" for k, v in figures.items()
                if str(v) not in ("", "None") and not str(v).startswith("not measured")]
        if said:
            out.append(f"- {lens}: {', '.join(said)}")
    return out


def goal_of(project: Any, canon_goal: str | None) -> str:
    """The project's goal: its canon goal, or, when that only repeats the title (an adoption names the project, not
    what it is for), the title with what its spec says it is (an adopted project's README, kernel/adopt.py)."""
    title = str(project.meta.get("title") or "")
    goal = str(canon_goal or title).strip()
    if goal.casefold() != title.strip().casefold():
        return goal
    summary = str((project.read("spec.json", {}) or {}).get("summary") or "").strip()
    return f"{title}: {summary}" if summary and summary.casefold() != title.casefold() else goal


def failed_checks(project: Any) -> list[dict[str, Any]] | None:
    store = optional("kernel.checks.store")
    if store is None:
        return None
    try:
        rows = []
        for key in store.enabled(project):
            last = (store.results(project, key, limit=1) or [None])[-1]
            if last and last.get("verdict") == "failed":
                rows.append({"check": key, "summary": str(last.get("summary") or "")[:300], "at": last.get("at")})
        return rows
    except Exception:  # noqa: BLE001 - a check store that cannot be read is "not available", never a crash
        return None


def insights(factory: Any, pid: str) -> dict[str, Any] | None:
    mod = optional("kernel.insights")
    if mod is None:
        return None
    try:
        return mod.summary(factory, pid=pid)
    except Exception:  # noqa: BLE001
        return None


def alignment_gaps(project: Any) -> list[dict[str, Any]] | None:
    mod = optional("kernel.alignment_records")
    if mod is None:
        return None
    try:
        # Only gaps about what a person accepted as the product's own: a gap about an item nobody accepted (a
        # demo's output found in the repository, say) is not the agent's to close.
        taken = {k for k, d in mod.decisions(project).items() if d.get("verdict") == "accept"}
        gaps = [g for g in mod.open_gaps(project)
                if set(((g.get("proposal") or {}).get("refs")) or []) <= taken]
        return [{"id": g.get("id"), "title": g.get("title"), "detail": str(g.get("detail") or "")[:300]}
                for g in gaps][:MAX_ITEMS]
    except Exception:  # noqa: BLE001
        return None


def review_feedback(project: Any) -> list[dict[str, Any]] | None:
    """What the Review says went wrong and waits on a person for this project (kernel/review.py ``review``, the
    last seven days, without diffs): the agent's feedback. None when the Review is not in this build."""
    mod = optional("kernel.review")
    if mod is None:
        return None
    try:
        out = mod.review(project.factory, project=project.pid, since="7d", diffs=False)
    except (KeyError, ValueError, OSError):
        return None
    still = still_open(project)
    return [{"group": g["id"], "kind": it["kind"], "title": str(it["title"])[:300], "at": it.get("at")}
            for g in out["groups"] if g["id"] in ("wrong", "waiting") for it in g["items"] if still(it)][:MAX_ITEMS]


def conventions(project: Any) -> dict[str, Any] | None:
    ide = optional("kernel.ide")
    if ide is None or ide.kind_of(project) is None:
        return None
    try:
        ctx = ide.context(project)
    except Exception:  # noqa: BLE001
        return None
    return {"read_from": ctx.get("read_from"), "stated": ctx.get("stated") or [],
            "instructions": [str(i.get("path") or i) for i in ctx.get("instructions") or []][:MAX_ITEMS]}


def _tests(project: Any, conv: dict[str, Any] | None) -> list[str]:
    stated = [s["command"] for s in (conv or {}).get("stated") or [] if isinstance(s, dict) and s.get("kind") == "test"]
    if stated:
        return stated
    if project.meta.get("source_kind") == "attached":
        return [f"the repository's own test command; `rihmasto repo gate {project.pid} --head <commit>` runs the gate"]
    submit = f"`rihmasto workspace submit {project.pid} <folder>` sends your commits through the gate"
    if project.meta.get("source_kind") == "adopted":    # its own suite, as adoption's baseline ran it
        return [*_adopted_tests(project), submit]
    return ["python -m unittest discover -s tests (the paved road's product suite)", submit]


def _adopted_tests(project: Any) -> list[str]:
    """An adopted project has its own suite, or none: never the paved road's (FR-RPJ1)."""
    ran = _baseline_tests(project)
    if ran:
        return ran
    from kernel.adopted_state import state

    held = state(project) or {}
    stated = [f"`{o['command']}` (stated in the project's instructions; not run yet)" for o in held.get("stated") or []
              if isinstance(o, dict) and o.get("command")]
    if stated:
        return stated
    base = project.read("baseline.json", {}) or {}
    why = str(base.get("reason") or "the baseline is not measured")
    return [f"No test command is known for this project: no test command was found by rule ({why}). Ask a person "
            "which command checks it (they state it in the Console's settings or as a Health test-suite check), and "
            "do not invent one; say in your channel post what you checked and how."]


def _baseline_tests(project: Any) -> list[str]:
    """The test commands an adopted project's baseline ran, each with its verdict (baseline.json)."""
    base = project.read("baseline.json", {}) or {}
    at = str(base.get("revision") or "")[:12]
    out = []
    for run in base.get("runs") or []:
        if isinstance(run, dict) and run.get("command"):
            line = " ".join(str(w) for w in run["command"])
            out.append(f"`{line}` ({run.get('runner') or 'its suite'}: {run.get('verdict') or 'not measured'} at the "
                       f"adoption's baseline{' ' + at if at else ''})")
    if not out and base.get("command"):
        out.append(f"`{base['command']}` ({base.get('verdict') or 'not measured'} at the adoption's baseline)")
    return out


def _plan(project: Any) -> list[dict[str, Any]]:
    """The contract's tasks with their state, then any task the records hold beyond them."""
    tasks = project.read("tasks.json", {}) or {}
    titles = {t["id"]: t for t in (project.read("contract.json") or {}).get("tasks", [])}
    ids = [*titles, *(t for t in tasks if t not in titles)]
    return [{"id": t, "title": (titles.get(t) or {}).get("title"), "criteria": (titles.get(t) or {}).get("criteria"),
             "status": (tasks.get(t) or {}).get("status") or "pending"} for t in ids][:30]


def _open(project: Any) -> dict[str, Any]:
    from kernel.canon import Canon

    canon = Canon(project)
    return {"questions": [{"id": q["id"], "text": q["text"][:300], "blocking": q["blocking"]}
                          for q in canon.questions("open")][:MAX_ITEMS],
            "assumptions": [{"id": a["id"], "text": a["text"][:300], "due": a.get("due")}
                            for a in canon.assumptions("open")][:MAX_ITEMS],
            "canon_goal": canon.goal}


def _feedback(project: Any) -> dict[str, Any]:
    """What came back on the work: findings, review, failed gates and checks, insights, alignment gaps."""
    return {"findings": _findings(project), "review": review_feedback(project), "failed_gates": failed_gates(project),
            "failed_checks": failed_checks(project), "insights": insights(project.factory, project.pid),
            "alignment": alignment_gaps(project)}


def _goal_steps(project: Any, goal: str | None) -> list[str] | None:
    if not goal:
        return None
    from kernel.copilot import rule_plan

    return [s["title"] for s in rule_plan(project.factory, project, goal)["steps"]]


def brief(project: Any, *, change: str | None = None, goal: str | None = None) -> dict[str, Any]:
    """The hand-off brief for a coding agent: everything above, from the records, never a holdout."""
    from kernel.next_step import next_step

    meta = project.meta
    card = _change(project, change)
    opened = _open(project)
    conv = conventions(project)
    said = goal or goal_of(project, opened.pop("canon_goal"))    # a change has its own section below the goal
    opened.pop("canon_goal", None)
    return {
        "project": {"id": project.pid, "title": meta.get("title"), "stage": meta.get("stage"),
                    "maturity": meta.get("maturity"), "source_kind": meta.get("source_kind"),
                    "confidential": bool(meta.get("confidential")), "adopted": _adopted_said(project)},
        "goal": said, "change": card,
        "criteria": _criteria(project, set(card["requirements"]) if card else set()),
        **opened, "plan": _plan(project), "plan_steps": _goal_steps(project, goal),
        "waits_for": next_step(project).get("waits_for"), **_feedback(project),
        "conventions": conv, "tests": _tests(project, conv),
        "report_back": [line.format(pid=project.pid) for line in REPORT_BACK],
    }


def _adopted_said(project: Any) -> str | None:
    """An adopted project's real state ("adopted to improve: improving"), not the seven stages (FR-RPJ1)."""
    if project.meta.get("source_kind") != "adopted":
        return None
    from kernel.adopted_state import state

    s = state(project)
    return f"adopted to {s['intent']}: {s['state']}" if s else None


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"## {title}", "", *(lines or ["- None."]), ""]


def _head(b: dict[str, Any]) -> list[str]:
    p = b["project"]
    kind = f", {p['source_kind']}" if p.get("source_kind") and not p.get("adopted") else ""
    where = p.get("adopted") or f"stage {p['stage']}"
    governed = f"Governed in Rihmasto: {where}, maturity {p['maturity']}{kind}. It waits for {b['waits_for']}."
    out = [f"# Hand-off: {p['title']} (`{p['id']}`)", "", governed, ""]
    if p.get("confidential"):
        out += [CONFIDENTIAL_SAID, ""]
    out += _section("The goal", [b["goal"] or "None stated."])
    if b["change"]:
        out += _section(f"The {b['change'].get('kind') or 'change'} {b['change']['id']}", change_said(b["change"]))
    return out


def _work(b: dict[str, Any]) -> list[str]:
    crit = [f"- **{c['id']}** ({c['requirement']}): given {c['given']}, when {c['when']}, then {c['then']}"
            for c in b["criteria"]]
    asks = [f"- {q['id']}{' (blocking)' if q['blocking'] else ''}: {q['text']}" for q in b["questions"]]
    asks += [f"- {a['id']} (assumed, due {a['due']}): {a['text']}" for a in b["assumptions"]]
    plan = [f"- {t['id']}: {t['title'] or ''} ({t['status']})" for t in b["plan"]]
    plan += [f"- Goal step: {s}" for s in b["plan_steps"] or []]
    return (_section("Criteria to meet", crit) + _section("Open questions (people answer these; propose, never decide)",
                                                          asks) + _section("The plan", plan))


def _said_by_a_check(r: Any, checks: list[dict[str, Any]]) -> bool:
    """A Review item that only repeats a failed check the brief already lists ("Check secrets failed")."""
    title = str(r.get("title") if isinstance(r, dict) else r).lower()
    return "fail" in title and any(str(c["check"]).lower() in title for c in checks)


def _feedback_lines(b: dict[str, Any]) -> list[str]:
    checks = b["failed_checks"] or []
    lines = [f"- Finding: {f}" for f in b["findings"]]
    lines += [f"- Review ({r['group']}): {r['title']}" if isinstance(r, dict) else f"- Review: {r}"
              for r in b["review"] or [] if not _said_by_a_check(r, checks)]
    lines += [f"- Gate {g['task']} round {g['round']}: {g['verdict']}; failing {', '.join(g['failing']) or '-'}"
              for g in b["failed_gates"]]
    lines += [f"- Check {c['check']} failed: {c['summary']}" for c in checks]
    lines += [f"- Alignment gap: {g['title']}" for g in b["alignment"] or []]
    title = (f"Other feedback on the project (context, not part of {b['change']['id']})" if b.get("change")
             else "Feedback to address")
    out = _section(title, lines)
    measured = insight_lines(b["insights"])
    if measured:
        out += _section("Insights", measured)
    return out


def _conventions_lines(conv: dict[str, Any]) -> list[str]:
    """The project's own instructions for coding agents and the commands they state (with their file and line),
    which settle how it is built, tested and run, and where they were read from."""
    files = conv.get("instructions") or []
    lines = [f"- Follow the project's own instructions: {', '.join(f'`{f}`' for f in files)}." if files else
             "- No instructions for AI tools were found (no CLAUDE.md, AGENTS.md or rules)."]
    for s in conv.get("stated") or []:
        if isinstance(s, dict) and s.get("command"):
            at = f" ({s['file']}, line {s['line']})" if s.get("file") and s.get("line") else ""
            lines.append(f"- {s.get('kind') or 'command'}: `{s['command']}`{at}")
    return [*lines, *([f"- Read from {conv['read_from']}"] if conv.get("read_from") else [])]


def render(b: dict[str, Any]) -> str:
    """The brief as the Markdown an agent reads."""
    conv = b["conventions"] or {}
    out = _head(b) + _work(b) + _feedback_lines(b)
    out += _section("The project's conventions", _conventions_lines(conv) if conv else [])
    out += _section("How to run the tests", [f"- {t}" for t in b["tests"]])
    out += _section("How to report back", [f"- {line}" for line in b["report_back"]])
    out += ["Never edit `.gnomon/`, `contract.json` or `factory/`. Holdout scenarios are never given to an agent."]
    return "\n".join(out) + "\n"


def header(b: dict[str, Any]) -> dict[str, Any]:
    """The brief by reference, beside its Markdown in one answer (the MCP tool): the project, the goal, the change,
    the criteria's ids and how many of each kind of item the Markdown holds, so nothing is said twice (FR-CTX1)."""
    lists = ("questions", "assumptions", "plan", "findings", "failed_gates", "failed_checks", "review", "alignment")
    return {"project": b["project"], "goal": b["goal"], "change": b["change"], "waits_for": b["waits_for"],
            "criteria": [c["id"] for c in b["criteria"]], "counts": {k: len(b.get(k) or []) for k in lists},
            "in_markdown": "every item in full, as the agent reads it"}


def for_agent(factory: Any, project: Any, b: dict[str, Any], *, to: str = "generic", operator: str = "<your name>",
              persona: str = "developer") -> dict[str, Any]:
    """How ``to`` takes the brief: the prompt file, the MCP configuration and the command line."""
    from kernel.workspace import mcp_config

    if to not in AGENTS:
        raise ValueError(f"to is one of {', '.join(AGENTS)}")
    pid = project.pid
    prompt_file = f".rihmasto/handoff-{pid}.md"
    cfg = mcp_config(factory, person=operator, persona=persona)
    server = cfg["mcpServers"]["rihma"]
    run = {"claude-code": f'claude -p "$(cat {prompt_file})" --mcp-config .mcp.json',
           "codex": f'codex exec "$(cat {prompt_file})"', "opencode": f'opencode run "$(cat {prompt_file})"',
           "cursor": f"open the chat in Cursor and attach {prompt_file}; Rihma's tools come from .cursor/mcp.json",
           "generic": f"give your agent {prompt_file} as its task, and Rihma's MCP server for its tools"}[to]
    mcp = {"claude-code": {"file": ".mcp.json", "json": cfg},
           "cursor": {"file": ".cursor/mcp.json", "json": {"mcpServers": {"rihma": {k: v for k, v in server.items()
                                                                                    if k != "type"}}}},
           "codex": {"file": "~/.codex/config.toml", "toml": "[mcp_servers.rihma]\n"
                     f"command = {json.dumps(server['command'])}\nargs = ["
                     + ", ".join(json.dumps(a) for a in server["args"]) + "]\n"}}.get(to, {"file": ".mcp.json",
                                                                                         "json": cfg})
    return {"to": to, "label": AGENTS[to], "prompt_file": prompt_file, "mcp": mcp, "run": run,
            "note": "Save the brief as the prompt file in your working copy. Rihmasto never writes into your folder, "
                    "and the agent's writes come back as proposals and channel posts, signed for its operator."}


def digest(text: str) -> str:
    """The brief's fingerprint as the ledger keeps it."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def handoff_said(to: str, via: str, change: str | None, filed: str | None, runner: str | None) -> str:
    """The channel's line for a hand-off: to whom it went and how, never "any coding agent (run)"."""
    if via == "run":
        who = "Gnomon's builder cell" if (runner or "gnomon") == "gnomon" else f"the builder cell ({runner})"
        return f"Handed to {who} through {filed}: it waits for {filed} to be accepted before the cell runs it."
    how = {"copy": "brief copied", "download": "brief downloaded"}.get(via, via)
    return f"Handed off to {AGENTS.get(to, to)} ({how})" + (f", for {change}" if change else "") + "."


def record(project: Any, b: dict[str, Any], *, to: str, person_name: str, persona: str, via: str,
           filed: str | None = None, runner: str | None = None) -> dict[str, Any]:
    """A person gave a hand-off: the ledger notes who, to which agent (or the builder cell, with the change it was
    filed as) and the brief's sha256; the channel shows it."""
    text = render(b)
    change = b["change"]["id"] if b["change"] else None
    task = change if (b["change"] or {}).get("kind") == "task" else None     # a task's hand-off is on its card
    msg = ch.post(project, author=ch.person(person_name, persona), kind="handoff",
                  text=handoff_said(to, via, change, filed, runner),
                  refs={"cards": [c for c in (change, filed) if c and c != task], "tasks": [task] if task else [],
                        "criteria": [c["id"] for c in b["criteria"]][:20]})
    project.log("agent_handoff", {"to": to, "via": via, "person": person_name, "persona": persona, "change": change,
                                  "sha256": digest(text), "message": msg["id"],
                                  **({"filed": filed, "runner": runner or "gnomon"} if via == "run" else {})})
    return msg
