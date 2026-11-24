"""The intake summary and the `rihmasto inputs` command (docs/guides/inputs.md).

The summary sets three things side by side: what the input stated ("from your input": each fact with its
document and lines, the author's decisions and requirements), what was asked (to a person, with the
answer once given) and what was assumed (with its due date). Beside them: the questions not asked because
the input already says it, every facet of the checklist with its state, and the model's proposal when a
model refined the reading. The cockpit's Questions view shows it (cockpit/static/inputs.js).

    rihmasto inputs read <text or path> [--maturity M]     how a request would be read; writes nothing
    rihmasto inputs summary <pid> [--text]                 the intake summary (JSON, or readable text)
    rihmasto inputs refine <pid> --person P --persona X    the analyst's model refines the reading: model_proposed
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from kernel import input_intake, input_kind
from kernel.canon import Canon, DecisionRefused
from kernel.input_facets import FACET_IDS, FACETS
from kernel.model import ModelError
from kernel.people import PERSONAS, is_person

STATES = ("given", "answered", "asked", "assumed", "left open", "open")


def _question_row(q: dict[str, Any], facets: list[str], checklist: set[str], due: dict[str, Any]) -> dict[str, Any]:
    row = {"id": q["id"], "text": q["text"], "perspective": q["perspective"], "blocking": q["blocking"],
           "status": q["status"], "facets": facets, "checklist": q["id"] in checklist}
    answer = q.get("answer") or {}
    if q["status"] == "assumed":
        a = due.get(str(answer.get("assumption") or ""), {})
        row.update(answer=answer.get("text"), assumption=answer.get("assumption"), chosen_by=answer.get("chosen_by"),
                   due=a.get("due"), assumption_status=a.get("status"))
    elif q["status"] == "answered":
        row.update(answer=answer.get("text"), by=answer.get("by"), persona=answer.get("persona"), card=q.get("card"))
    else:
        row.update(card=q.get("card"))
    return row


def _state(facet: str, reading: dict[str, Any], qs: list[dict[str, Any]], left: set[str]) -> str:
    """A facet's state: given by the input, else what became of its questions, else open (or left open by
    the input's author, with a "TBD")."""
    if facet in reading["given"]:
        return "given"
    for state, status in (("answered", "answered"), ("asked", "open"), ("assumed", "assumed")):
        if any(r["status"] == status for r in qs):
            return state
    return "left open" if facet in left else "open"


def _facet_rows(reading: dict[str, Any], rows: list[dict[str, Any]], maturity: str, posture: str | None
                ) -> list[dict[str, Any]]:
    """Every facet of the checklist with its state: given, answered, asked, assumed, left open or open."""
    need = reading["kind"] == "need"
    asks = [] if need else input_intake.asked_facets(maturity, posture)
    left = {o["facet"] for o in reading.get("left_open") or []}
    out = []
    for facet in FACET_IDS:
        qs = [r for r in rows if facet in r["facets"]]
        state = _state(facet, reading, qs, left)
        note = ("" if state not in ("open", "left open") or facet in asks else
                "a need's gaps are the panel's to ask" if need else "not asked at this maturity")
        out.append({"facet": facet, "label": FACETS[facet]["label"], "state": state, "note": note,
                    "facts": [f["id"] for f in reading["facts"] if f["facet"] == facet],
                    "questions": [r["id"] for r in qs], "checklist_asks": facet in asks})
    return out


def _head(reading: dict[str, Any]) -> dict[str, Any]:
    """How the input was read: its kind and language with their labels, by whom it came, and its documents."""
    return {"kind": reading["kind"], "kind_label": input_kind.KIND_LABEL.get(reading["kind"], reading["kind"]),
            "kind_by": reading["kind_by"], "confidence": reading["confidence"], "basis": reading["basis"],
            "language": reading["language"], "language_label": input_kind.LANGUAGE_LABEL.get(reading["language"], ""),
            "by": reading.get("by"), "at": reading.get("at"), "sha256": reading["sha256"],
            "documents": [{k: d.get(k) for k in ("name", "kind", "confidence", "language", "first_line", "lines")}
                          for d in reading["documents"]]}


def _from_input(reading: dict[str, Any]) -> dict[str, Any]:
    """What the input states: its facts with their facet's label, its decisions and its requirements."""
    return {"facts": [{**f, "label": FACETS[f["facet"]]["label"]} for f in reading["facts"]],
            "decisions": reading["decisions"],
            "requirements": [{k: r[k] for k in ("id", "statement", "document", "lines")}
                             | {"criteria": len(r["acceptance"])} for r in reading["requirements"]]}


def _rows(canon: Canon, reading: dict[str, Any]) -> list[dict[str, Any]]:
    """Every question of the canon, with the facets it asks about and what became of it; a question withdrawn
    when the project changed (kernel/rewind.py) is left out."""
    facets_of = reading.get("question_facets") or {}
    checklist = {g["question"] for g in reading.get("gap_questions") or []}
    due = {a["id"]: a for a in canon.assumptions()}
    return [_question_row(q, facets_of.get(q["id"], []), checklist, due) for q in canon.questions()
            if q["status"] != "withdrawn"]


def summary(project: Any, reading: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The intake summary of a project, or None before its request was read."""
    reading = project.read("inputs.json", None) if reading is None else reading
    if not isinstance(reading, dict) or reading.get("schema") != input_kind.SCHEMA:
        return None
    rows = _rows(Canon(project), reading)
    asked = [r for r in rows if r["status"] in ("open", "answered")]
    assumed = [r for r in rows if r["status"] == "assumed"]
    facets = _facet_rows(reading, rows, project.meta.get("maturity", "demo"), input_intake.posture_of(project))
    not_asked = reading.get("not_asked") or []
    return {**_head(reading), "from_input": _from_input(reading), "asked": asked, "assumed": assumed,
            "not_asked": not_asked, "facets": facets, "model_proposed": reading.get("model_proposed"),
            "counts": {"given": len(reading["given"]), "facts": len(reading["facts"]), "asked": len(asked),
                       "assumed": len(assumed), "not_asked": len(not_asked),
                       "open": sum(1 for f in facets if f["state"] in ("open", "left open"))}}


def _lines(at: list[int]) -> str:
    return f"line {at[0]}" if at[0] == at[1] else f"lines {at[0]}-{at[1]}"


def _asked_line(r: dict[str, Any]) -> str:
    if r["status"] == "answered":
        return f"  {r['id']} {r['text']} (answered by {r['by']}: {r['answer']})"
    return f"  {r['id']} {r['text']} (open{', blocking' if r['blocking'] else ''})"


def render_text(s: dict[str, Any]) -> str:
    """The summary as a person reads it on a terminal: three blocks, then what was not asked and the facets."""
    out = [f"Read as {s['kind_label']} (by {s['kind_by']}, {s['confidence']}), in {s['language_label']}: "
           + "; ".join(s["basis"]) + ".", "", f"From your input, given by {s['by'] or 'the request'} "
           "(never asked again):"]
    out += [f"  {f['id']} {f['label']} ({f['document']}, {_lines(f['lines'])}): {f['text'][:120]}"
            for f in s["from_input"]["facts"]] or ["  (nothing the checklist reads)"]
    out += [f"  decision {d['id']} ({d['document']}, {_lines(d['lines'])}): {d['text'][:120]}"
            for d in s["from_input"]["decisions"]]
    out += [f"  requirement {r['id']} ({r['document']}, {_lines(r['lines'])}): {r['statement'][:120]}"
            for r in s["from_input"]["requirements"]]
    out += ["", "Asked:"] + ([_asked_line(r) for r in s["asked"]] or ["  (nothing)"])
    out += ["", "Assumed:"] + ([f"  {r['id']} {r['text']} -> {r['answer']} ({r['assumption']}, due {r['due']})"
                                for r in s["assumed"]] or ["  (nothing)"])
    if s["not_asked"]:
        out += ["", "Not asked, because your input already says it:"]
        out += [f"  \"{x['text']}\" ({', '.join(x['facets'])}: {', '.join(x['because'])})" for x in s["not_asked"]]
    out += ["", "Facets:"] + [f"  {f['label']}: {f['state']}" + (f" ({f['note']})" if f["note"] else "")
                              for f in s["facets"]]
    return "\n".join(out) + "\n"


# -- the model refines the reading: model_proposed, never a decision -----------------------------------------

def _locate(reading: dict[str, Any], span: list[int]) -> tuple[str, list[int]] | None:
    """A span of the request text's lines as one document's own lines, or None across documents."""
    for d in reading["documents"]:
        first = d.get("first_line", 1)
        if first <= span[0] and span[1] < first + d["lines"]:
            return d["name"], [span[0] - first + 1, span[1] - first + 1]
    return None


def refine(project: Any, model: Any, *, person: str, persona: str) -> dict[str, Any]:
    """Ask the analyst's model to refine the reading of the project's request. What it proposes is kept beside
    the rule's reading as model_proposed, with lines the kernel checked and quoted; it changes no kind, no
    question and no decision. Asked by a named person; not measured when no model answers."""
    if not is_person(person) or persona not in PERSONAS:
        raise DecisionRefused(f"{person!r} as {persona!r}: a refinement is asked by a named person with a persona")
    reading = project.read("inputs.json", None)
    if not isinstance(reading, dict):
        raise ValueError(f"{project.pid} has no reading yet: its intake has not run")
    from kernel.confidential import require_local
    from kernel.intake import _ask_json

    require_local(project, ("analyst",), where="inputs refine")
    lines = input_kind.split_lines((project.read("source.json", {}) or {}).get("text") or "")
    numbered = "\n".join(f"{n}: {x}" for n, x in enumerate(lines, 1))
    try:
        answer = _ask_json(model, input_kind.refine_prompt(reading, numbered))
    except ModelError as exc:
        return {"measured": False, "why": f"no model answered: {exc}"}
    proposal = input_kind.refinement(answer, reading, lines)
    for item in list(proposal["stated"]):
        placed = _locate(reading, item["lines"])
        if placed is None:
            proposal["stated"].remove(item)
            proposal["dropped"].append({"item": str(item)[:200], "why": "it spans more than one document"})
        else:
            item["document"], item["lines"] = placed
    proposal.update(measured=True, rule_kind=reading["kind"], asked_by=person, persona=persona,
                    at=project.factory.clock.stamp())
    reading["model_proposed"] = proposal
    project.write("inputs.json", reading)
    stated = [{k: x[k] for k in ("facet", "document", "lines")} for x in proposal["stated"]]
    project.log("input_refined", {"asked_by": person, "persona": persona, "rule_kind": reading["kind"],
                                  "model_kind": proposal["kind"], "stated": stated,
                                  "dropped": len(proposal["dropped"])})
    return proposal


# -- `rihmasto inputs` ---------------------------------------------------------------------------------------

def read_source(source: str, maturity: str = "demo") -> dict[str, Any]:
    """How a request would be read, by rule, and which gaps the checklist would ask at a maturity: nothing is
    written."""
    from kernel.intake import load_source

    kind, text = load_source(source)
    if not text.strip():
        raise ValueError("the request is empty")
    documents, folder = input_intake.documents_of(text, source)
    reading = input_kind.read(documents, folder=folder)
    asks = input_intake.asked_facets(maturity)
    would = [f for f in reading["gaps"] if f in asks] if reading["kind"] != "need" else []
    return {**{k: reading[k] for k in ("kind", "confidence", "basis", "language", "given", "gaps", "facts",
                                       "requirements", "decisions", "left_open")},
            "source_kind": kind, "documents": [{k: d[k] for k in ("name", "kind", "confidence", "language")}
                                               for d in reading["documents"]],
            "checklist_would_ask": would, "maturity": maturity}


def add_parsers(sub: Any) -> None:
    """`rihmasto inputs read | summary | refine`, as the command line's parser adds them."""
    group = sub.add_parser("inputs", help="what arrived at intake, read by rule (docs/guides/inputs.md)")
    cmds = group.add_subparsers(dest="sub", required=True)
    p = cmds.add_parser("read", help="how a request would be read: kind, facts with lines, gaps; writes nothing")
    p.add_argument("source", help="the request's text, or a path to a file or a folder")
    p.add_argument("--maturity", choices=("explore", "demo", "pilot", "production"), default="demo")
    p = cmds.add_parser("summary", help="from your input, asked and assumed, side by side")
    p.add_argument("pid")
    p.add_argument("--text", action="store_true", help="readable text instead of JSON")
    p = cmds.add_parser("refine", help="the analyst's model refines the reading, kept as model_proposed")
    p.add_argument("pid")
    p.add_argument("--person", required=True)
    p.add_argument("--persona", required=True, choices=PERSONAS)


def _summary(factory: Any, args: argparse.Namespace) -> dict[str, Any]:
    s = summary(factory.project(args.pid))
    if s is None:
        raise ValueError(f"{args.pid} has no reading: its intake has not run, or ran before inputs were read")
    return s


def handlers(emit: Callable[[Any], None], model: Callable[[], Any], say: Callable[[str], Any]
             ) -> dict[str, Callable[[Any, argparse.Namespace], None]]:
    """The `rihmasto inputs` handlers. ``emit`` prints JSON, ``say`` prints text, ``model`` makes the analyst's
    model (only `refine` asks one)."""
    return {
        "inputs read": lambda f, a: emit(read_source(a.source, a.maturity)),
        "inputs summary": lambda f, a: say(render_text(_summary(f, a))) if a.text else emit(_summary(f, a)),
        "inputs refine": lambda f, a: emit(refine(f.project(a.pid), model(), person=a.person, persona=a.persona)),
    }
