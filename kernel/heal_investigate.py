"""Investigate with Rihma: a Rihma agent looks into an incident and proposes the next step (FR-HEAL1, D-0024).

From any incident (kernel/incidents.py) a person asks a Rihma agent to investigate. The agent works in the agent
channel (kernel/agent_channel.py), in the incident's own thread (``incident-i-0001``) of its project, or of the
factory's own canon when no project is involved:

- the person's request is posted, signed;
- the agent reads the incident's masked context (the request, the server log lines, a job's log tail, the ledger
  records named), its built-in class (kernel/immune.py) and the remedies Rihmasto already knows;
- it answers **by rule** when the class is known and no model is set up, or **through a model** in the analyst role
  (the cockpit's assistant model, a coding agent you already have, or a local one); a confidential project whose
  analyst role is hosted is answered by rule and nothing is sent;
- its diagnosis is posted with its **trace** (the basis, what it read, which records, the model and tokens, how long
  it took), and it **classifies** the incident: user setup, Rihmasto bug, project bug, external or unknown;
- it proposes the **next step**: a remedy, a configuration change, or a fix (a reproducing test and the change,
  which kernel/heal_fix.py takes through the gate).

The incident moves to investigating and the investigation is recorded in its ledger. The agent decides nothing.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from kernel import agent_channel as ch
from kernel import immune
from kernel import incidents as inc

CLASSIFICATIONS = ("user setup", "rihmasto bug", "project bug", "external", "unknown")
NEXT_KINDS = ("remedy", "config", "fix", "none")
# Frames of Rihmasto's own code in a traceback: a bug of Rihmasto's, unless the project's repository is named.
OWN_CODE = re.compile(r"[\\/](?:kernel|cockpit|mcp|gateway|embed|tools)[\\/][\w./\\-]+\.py")


def thread_of(iid: str) -> str:
    return "incident-" + iid.lower()


def _text_of(doc: dict[str, Any]) -> str:
    ctx = doc.get("context") or {}
    lines = list(ctx.get("trace") or []) + list(ctx.get("log") or [])
    lines += list((ctx.get("job") or {}).get("log_tail") or [])
    return "\n".join(str(x) for x in lines)


def _read_list(doc: dict[str, Any]) -> tuple[list[str], list[str]]:
    """What an investigation reads, and the ledger records it names."""
    ctx = doc.get("context") or {}
    read = [f"incident {doc['id']} ({doc['kind']} at {doc.get('where')})", f"its class: {doc.get('class')}"]
    for key, label in (("request", "the request summary"), ("log", "the server log lines"),
                       ("trace", "the traceback"), ("job", "the job's log tail"), ("view", "the view"),
                       ("browser", "the page's error")):
        if ctx.get(key):
            read.append(label)
    read.append("the remedies Rihmasto knows for this fingerprint")
    records = [f"{r.get('kind')}#{r.get('seq')}" for r in ctx.get("records") or [] if isinstance(r, dict)]
    return read, records[:20]


def by_rule(doc: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    """A diagnosis from the class and the context alone: no model."""
    text = _text_of(doc)
    classification = _classify(doc, offer, text)
    said = offer.get("explain") or doc.get("summary") or "Rihmasto has no built-in reading of this failure."
    if classification in ("rihmasto bug", "project bug"):
        frames = sorted({inc.normalise(m.group(0)) for m in OWN_CODE.finditer(text)})[:3]
        said += (" The traceback runs through " + ", ".join(frames) + "." if frames else "")
        nxt = {"kind": "fix", "target": "rihmasto" if classification == "rihmasto bug" else "project",
               "text": "A fix needs a reproducing test and the change: a model or a person writes them, and the "
                       "gate judges them before any pull request."}
    else:
        nxt = _remedy_next(offer)
    return {"classification": classification, "diagnosis": said, "next": nxt, "fix": None}


def _classify(doc: dict[str, Any], offer: dict[str, Any], text: str) -> str:
    """The class's reading; a traceback through the project's repository is a project bug, one through Rihmasto's
    own code a Rihmasto bug."""
    repo = str(((doc.get("context") or {}).get("repo")) or "")
    if repo and repo in text:
        return "project bug"
    known = offer["classification"] if offer["classification"] in CLASSIFICATIONS else "unknown"
    return "rihmasto bug" if known == "unknown" and OWN_CODE.search(text) else known


def _remedy_next(offer: dict[str, Any]) -> dict[str, Any]:
    first = next((r for r in offer["remedies"] if r["kind"] != "investigate"), None)
    if first is None:
        return {"kind": "none", "text": "Nothing is known to fix it yet: describe what you were doing and report it."}
    return {"kind": "remedy", "remedy": first["id"], "text": first["label"]}


def _prompt(doc: dict[str, Any], offer: dict[str, Any]) -> str:
    shown = {k: doc.get(k) for k in ("id", "kind", "where", "error_class", "message", "summary", "count", "words")}
    ctx = doc.get("context") or {}
    return (
        "You are Rihma's analyst, investigating an incident in Rihmasto, a governed AI solution factory. Read only "
        "what follows (secrets are already masked). Say what most likely happened in at most five sentences, "
        f"classify it as one of {json.dumps(list(CLASSIFICATIONS))}, and propose the next step: a remedy from the "
        "list by its id, a configuration change in words, or a fix. A fix is a test that reproduces the incident "
        "(it fails before the fix) and the change, each as a whole file with its path in the repository. You "
        "decide nothing: a person confirms every step.\n\n"
        f"The incident:\n{json.dumps(shown, ensure_ascii=False)}\n"
        f"Its context:\n{json.dumps(ctx, ensure_ascii=False)[:6000]}\n"
        f"Rihmasto's reading of its class: {offer.get('class')}: {offer.get('explain')}\n"
        f"Remedies known: {json.dumps([{'id': r['id'], 'label': r['label']} for r in offer['remedies']])}\n\n"
        "Answer with this JSON in a ```json block:\n"
        '{"classification": "...", "diagnosis": "...", "next": {"kind": "remedy|config|fix|none", "remedy": "<id or '
        'null>", "text": "..."}, "fix": null or {"summary": "...", "test": {"path": "tests/test_x.py", "content": '
        '"..."}, "change": [{"path": "...", "content": "..."}]}}\n')


def _checked(raw: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    """A model's answer as far as it holds: a classification and a next step of the known kinds."""
    if not isinstance(raw, dict) or not str(raw.get("diagnosis") or "").strip():
        return fallback
    given = raw.get("next")
    nxt: dict[str, Any] = given if isinstance(given, dict) else {}
    kind = str(nxt.get("kind")) if nxt.get("kind") in NEXT_KINDS else "none"
    proposed = raw.get("fix")
    fix: dict[str, Any] | None = proposed if isinstance(proposed, dict) else None
    if fix is not None and not (isinstance(fix.get("test"), dict) and isinstance(fix.get("change"), list)):
        fix = None
    said = {k: str(nxt[k])[:500] for k in ("remedy", "text", "target") if nxt.get(k)}
    return {"classification": raw.get("classification") if raw.get("classification") in CLASSIFICATIONS
            else fallback["classification"], "diagnosis": str(raw["diagnosis"])[:2000],
            "next": {"kind": "fix" if fix else kind, **said}, "fix": fix}


def _model_reading(project: Any, doc: dict[str, Any], offer: dict[str, Any], model: Any,
                   fallback: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from kernel import model_usage
    from kernel.channel_rihma import _trace
    from kernel.model import ModelError, extract_json

    started = time.monotonic()
    try:
        with model_usage.for_project(project, task="investigate"):
            text = str(model.ask(_prompt(doc, offer), role="analyst") or "")
    except (ModelError, OSError, RuntimeError, ValueError) as exc:
        return fallback, {"basis": "rule", "rests_on": f"the model gave no answer ({type(exc).__name__}): read by rule"}
    try:
        raw = extract_json(text)
    except ValueError:
        raw = None
    return _checked(raw, fallback), _trace(model, "analyst", started)


def investigate(factory: Any, iid: str, *, person: str, persona: str, model: Any = None) -> dict[str, Any]:
    """Investigate incident ``iid``: post the request and the agent's diagnosis with its trace in the incident's
    thread, and move the incident to investigating with what it found. Returns the investigation."""
    from kernel.confidential import confidential, refusal

    doc = inc.get(factory, iid)
    if doc["state"] in inc.DONE:
        raise inc.IncidentRefused(f"{iid} is already {doc['state']}")
    project = inc.ledger_of(factory, doc.get("project"))
    thread = thread_of(iid)
    asked = ch.post(project, author=ch.person(person, persona), kind="question", thread=thread,
                    text=f"Investigate {iid}: {doc.get('summary')}", refs={"message": iid})
    offer = immune.offered(factory, doc)
    reading = by_rule(doc, offer)
    read, records = _read_list(doc)
    note = None
    if model is not None and confidential(project) and refusal(["analyst"]):
        note = "This project is confidential and the analyst's model is hosted, so nothing was sent: read by rule."
        trace: dict[str, Any] = {"basis": "rule", "rests_on": "the incident's class and context; no model asked"}
    elif model is not None:
        reading, trace = _model_reading(project, doc, offer, model, reading)
    else:
        trace = {"basis": "rule", "rests_on": "the incident's class and context; no model is set up"}
    trace |= {"read": read, "records": records,
              "context_chars": len(json.dumps(doc.get("context") or {}, ensure_ascii=False))}
    nxt = reading["next"]
    lines = [reading["diagnosis"], f"Classified as: {reading['classification']}.",
             f"Next step ({nxt['kind']}): {nxt.get('text') or nxt.get('remedy') or '-'}."]
    if reading.get("fix"):
        lines.append(f"A fix is proposed: {str(reading['fix'].get('summary') or 'a reproducing test and the change')}"
                     " It goes through the gate before any pull request.")
    if note:
        lines.append(note)
    answer = ch.post(project, author=ch.rihma("analyst"), kind="answer", thread=thread, text=" ".join(lines)[:7900],
                     refs={"message": asked["id"]}, trace=trace)
    found = {"classification": reading["classification"], "diagnosis": reading["diagnosis"], "next": nxt,
             "fix": reading.get("fix"), "trace": trace, "thread": thread, "project": project.pid,
             "message": answer["id"], "asked_by": person, "at": factory.clock.stamp()}
    inc.update(factory, iid, state="investigating", event="incident_investigated", person=person, persona=persona,
               note=f"{reading['classification']}: next {nxt['kind']}", investigation=found)
    return found
