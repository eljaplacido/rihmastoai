"""The intake's and the spec's side of reading what arrived (docs/guides/inputs.md).

kernel/intake.py and kernel/spec.py call these hooks:
- `record`: read the request by rule (kernel/input_kind.py) and keep the reading in the project's
  inputs.json, with a ledger record of who asked, the kind, every fact with its document and lines,
  and the request's sha256;
- `panel_note`: what the panel is told: what the request already states, and the gaps;
- `already_given`: a question that only restates what the request says is not asked again: every facet
  it asks about is given, and every word of its own is in those facets' stated facts or the request's
  titles. It is recorded with the facts it rests on; a question that asks anything more is asked. A
  blocking question always reaches the mode: when it restates, its rationale cites the facts. For a
  need, the profile's standing questions are still asked: one sentence rarely settles them;
- `tag`: the facets a question asks about, for the summary and the gaps;
- `ask_gaps`: the facet checklist's own question for each gap no question covers, at the project's
  maturity, for a specification, a plan or a folder (a need's gaps are the panel's to ask, within its
  budget). The mode then settles each one as it settles every question;
- `finish`: keep the screened reading and record what was not asked and which gaps were asked;
- `keep_authors` (kernel/spec.py): an expert's requirements keep their ids and wording, statement and
  criteria; one the analyst's draft left out is kept as the author wrote it.

The posture hook: `GAP_POSTURES` is where a posture preset (kernel/posture.py, built by another stream)
changes which gaps the checklist asks. A project's posture is read from its meta ("posture", a preset
name or {"preset": name}); a preset not named here asks what the maturity asks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from kernel import input_kind
from kernel.input_facets import CUES, FACET_IDS, FACETS, WORDS, facets_named, headings, required

MAX_BRIEF_FACTS = 40
# The posture hook: a preset may ask only some facets ("only") or more of them at any maturity ("add").
GAP_POSTURES: dict[str, dict[str, tuple[str, ...]]] = {
    "prototype": {"only": ("users_roles", "outcomes", "scope")},
    "regulated": {"add": ("data", "security", "privacy", "constraints", "acceptance")},
}
_REQ_ID = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")     # kernel/spec.py keeps such an id as the customer's
_GENERATED = re.compile(r"R-\d+")                           # an id the kernel gives, never the customer's
_WORD = re.compile(r"[^\W_]+")
# A question's words that say nothing of their own: asking words, links and pronouns (English and Finnish).
# Any other word must be in the stated facts, or the question asks something new and is asked.
_PLAIN = frozenset("""
a an the and or but nor of to in on at by for from with without into about as is are was were be been being
am do does did have has had will would shall should can could may might must it its they them their there
here this that these those which who whom whose what when where why how whether if any all each every some
many much more most other others such same own just only also too very so than then we our us you your i
me my one ones need needs needed want wants require requires required expect expected able use used uses
cover covers include includes included kind kinds type types way ways measure measured get make
mikä mitkä mitä kuka ketkä keitä kenen miten millä missä mihin onko ovat on ja tai se ne sen niiden pitää
pitäisi tulee kun jos myös ei että tämä nämä sitä niitä mitään kaikki
""".split())


def documents_of(text: str, source: str | None) -> tuple[list[tuple[str, str]], bool]:
    """The documents as intake read them: a folder's parts by its material map (kernel/material.py), a
    file, or the request's own text."""
    try:
        path = Path(source) if source else None
        kind = "folder" if path and path.is_dir() else "file" if path and path.is_file() else "text"
    except (OSError, ValueError):     # a request's own text is not a path the system can look at
        path, kind = None, "text"
    if path is not None and kind == "folder":
        from kernel.material import gather

        return gather(path)[2], True
    return [(path.name if path is not None and kind == "file" else "request", text)], False


def _place(reading: dict[str, Any], documents: list[tuple[str, str]], folder: bool) -> None:
    """Where each document starts in the request text the project keeps (source.json): a folder's
    documents follow each other under a "## <name>" line, as kernel.intake.load_source joins them."""
    start, first = 1, {}
    for name, text in documents:
        first[name] = start + 2 if folder else 1
        start += (f"## {name}\n\n" + text).count("\n") + 2
    for d in reading["documents"]:
        d["first_line"] = first.get(d["name"], 1)


def _trace(reading: dict[str, Any]) -> dict[str, Any]:
    """The ledger's record of a reading: who asked, what kind, what it states and where, its sha256."""
    return {"kind": reading["kind"], "kind_by": reading["kind_by"], "confidence": reading["confidence"],
            "language": reading["language"], "requested_by": reading.get("by"), "sha256": reading["sha256"],
            "documents": [{"name": d["name"], "kind": d["kind"]} for d in reading["documents"]],
            "given": reading["given"], "gaps": reading["gaps"],
            "facts": [{k: f[k] for k in ("id", "facet", "document", "lines", "how")} for f in reading["facts"]],
            "requirements": [r["id"] for r in reading["requirements"]],
            "decisions": [d["id"] for d in reading["decisions"]]}


def record(project: Any, kind: str, text: str, source: str | None, requested_by: str | None,
           documents: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Read what arrived by rule, keep the reading (inputs.json) and record it in the ledger. A folder's
    ``documents`` come with it when intake built the request from its material map."""
    documents, folder = (documents, True) if documents else documents_of(text, source)
    reading = input_kind.read(documents, folder=folder)
    _place(reading, documents, folder)
    reading.update(source_kind=kind, by=requested_by, at=project.factory.clock.stamp(), not_asked=[],
                   restated_blocking=[], question_facets={}, gap_questions=[], model_proposed=None,
                   titles=[t for t in (_title(text) for _, text in documents) if t])
    project.write("inputs.json", reading)
    project.log("input_read", _trace(reading))
    return reading


def _title(text: str) -> str:
    """A document's first heading: what the work is called, which any question may name."""
    marks = headings(text.splitlines())
    return marks[0][2] if marks else ""


def _where(f: dict[str, Any]) -> str:
    a, b = f["lines"]
    return f"{f['document']}, line {a}" if a == b else f"{f['document']}, lines {a}-{b}"


def panel_note(reading: dict[str, Any]) -> str:
    """What every perspective is told, word for word: what the request states, its decisions, and the gaps."""
    out = [f"The factory read the request by rule as {input_kind.KIND_LABEL[reading['kind']]} "
           f"({reading['confidence']})."]
    if reading["given"]:
        out.append("It already states these, in its author's words. Never ask about them again:")
        for facet in reading["given"]:
            f = next(x for x in reading["facts"] if x["facet"] == facet)
            out.append(f"- {FACETS[facet]['label']}: \"{f['text'][:160]}\" ({_where(f)})")
    if reading["decisions"]:
        out.append("Decisions it already made, which stand: " + "; ".join(
            f"{d['id']} {d['text'][:100]}" for d in reading["decisions"][:12]))
    if reading["requirements"]:
        out.append(f"It names {len(reading['requirements'])} requirements of its own ("
                   + ", ".join(r["id"] for r in reading["requirements"][:20]) + "); their ids and wording are kept.")
    out.append("The gaps, what it does not state: " + (", ".join(FACETS[f]["label"] for f in reading["gaps"])
                                                       or "none") + ".")
    out.append('Give each question the facet it is about, as "facet": one of ' + ", ".join(FACET_IDS) + ".")
    return "\n".join(out) + "\n"


def _facets_of(item: dict[str, Any]) -> list[str]:
    """The facets a question asks about: the model's tag, if it is a facet, and those its words name."""
    tagged = [item["facet"]] if item.get("facet") in FACETS else []
    return list(dict.fromkeys(tagged + facets_named(str(item.get("text", "")))))


def _held(word: str, vocab: set[str]) -> bool:
    """Whether the stated words hold ``word``, as itself or with another ending (register, registers)."""
    return word in vocab or any(len(os.path.commonprefix([word, v])) >= max(4, min(len(word), len(v)) - 3)
                                for v in vocab)


def new_words(reading: dict[str, Any], item: dict[str, Any], named: list[str]) -> list[str]:
    """The question's own words that the stated facts of its facets and the request's titles do not hold.
    A word that names one of its facets, or says nothing of its own (who, should, the), is never new."""
    text = str(item.get("text", ""))
    for f in named:
        text = CUES[f].sub(" ", WORDS[f].sub(" ", text))
    vocab = {w.lower() for f in reading["facts"] if f["facet"] in named for w in _WORD.findall(f["text"])}
    vocab |= {w.lower() for t in reading.get("titles", []) for w in _WORD.findall(t)}
    return [w for w in (x.lower() for x in _WORD.findall(text)) if w not in _PLAIN and not _held(w, vocab)]


def already_given(reading: dict[str, Any], item: dict[str, Any], perspective: str, *, seed: bool = False) -> bool:
    """Whether a question only restates what the request says: every facet it asks about is given, and it
    has no word of its own the stated facts lack. Such a question is not asked; the reading records it with
    the facts it rests on. A blocking question always reaches the mode, so a person can still decide it:
    when it restates, its rationale ("why") cites the facts and the reading records it as restated."""
    named = _facets_of(item)
    if (seed and reading["kind"] == "need") or not named or any(f not in reading["given"] for f in named):
        return False
    if new_words(reading, item, named):          # it asks something the request does not state
        return False
    facts = [f for f in reading["facts"] if f["facet"] in named][:6]
    because = [f["id"] for f in facts]
    if item.get("blocking"):
        cite = "; ".join(f"\"{f['text'][:120]}\" ({_where(f)})" for f in facts[:2])
        item["why"] = (str(item.get("why") or "").strip() + f" Your input already states: {cite}.").strip()
        reading.setdefault("restated_blocking", []).append(
            {"text": str(item.get("text", ""))[:300], "perspective": perspective, "facets": named, "because": because})
        return False
    reading["not_asked"].append({"text": str(item.get("text", ""))[:300], "perspective": perspective,
                                 "facets": named, "because": because, "from": "profile" if seed else "panel"})
    return True


def tag(reading: dict[str, Any], qid: str, item: dict[str, Any]) -> None:
    """Remember the facets question ``qid`` asks about."""
    reading["question_facets"][qid] = _facets_of(item)


def posture_of(project: Any) -> str | None:
    """The project's posture preset, when the posture stream has set one in its meta."""
    p = project.meta.get("posture")
    return (p.get("preset") if isinstance(p, dict) else p) if isinstance(p, (dict, str)) else None


def asked_facets(maturity: str, posture: str | None = None) -> list[str]:
    """The facets whose gaps the checklist asks at a maturity, as a posture preset changes them."""
    rule = GAP_POSTURES.get(posture or "", {})
    if "only" in rule:
        return [f for f in FACET_IDS if f in rule["only"]]
    return [f for f in FACET_IDS if required(f, maturity) or f in rule.get("add", ())]


def ask_gaps(canon: Any, reading: dict[str, Any], maturity: str, posture: str | None = None) -> list[dict[str, Any]]:
    """The checklist's own question for each gap no question covers (a specification, a plan or a folder).
    Its proposal comes first, so the mode can assume it; a blocking facet's gap goes to a person in mixed mode."""
    if reading["kind"] == "need":
        return []
    covered = {f for facets in reading["question_facets"].values() for f in facets}
    added = []
    for facet in asked_facets(maturity, posture):
        if facet in reading["given"] or facet in covered:
            continue
        spec = FACETS[facet]
        proposed = spec["options"][0]
        q = canon.add_question(spec["question"], spec["perspective"], blocking=spec["blocking"],
                               opinions={spec["perspective"]: proposed}, options=spec["options"],
                               rationale=f"Your input does not state its {spec['label']}: the facet checklist asks it.")
        reading["question_facets"][q["id"]] = [facet]
        reading["gap_questions"].append({"question": q["id"], "facet": facet})
        added.append({"id": q["id"], "perspective": spec["perspective"], "text": q["text"], "proposed": proposed})
    return added


def finish(project: Any, reading: dict[str, Any]) -> None:
    """Keep the screened reading, and record what was not asked (and why) and which gaps the checklist asked."""
    project.write("inputs.json", reading)
    project.log("input_screened", {
        "kind": reading["kind"], "requested_by": reading.get("by"),
        "not_asked": [{"text": x["text"][:160], "facets": x["facets"], "because": x["because"], "from": x["from"]}
                      for x in reading["not_asked"]],
        "restated_blocking": reading.get("restated_blocking", []),
        "gap_questions": reading["gap_questions"], "gaps": reading["gaps"]})


def outcome(reading: dict[str, Any]) -> dict[str, Any]:
    """What intake returns about the reading."""
    return {"input_kind": reading["kind"], "given": reading["given"], "not_asked": len(reading["not_asked"]),
            "gap_questions": [g["question"] for g in reading["gap_questions"]]}


def brief_lines(project: Any) -> list[str]:
    """The brief's section on what the input states: each fact, decision and requirement with its lines,
    tagged as the author's. Nothing when the input states nothing the checklist reads."""
    reading = project.read("inputs.json", None)
    if not isinstance(reading, dict) or not (reading.get("facts") or reading.get("decisions")
                                             or reading.get("requirements")):
        return []
    by = reading.get("by") or "the request's author"
    out = ["## From your input [owner]", "",
           f"Read as {input_kind.KIND_LABEL.get(reading['kind'], reading['kind'])} (by {reading['kind_by']}, "
           f"{reading['confidence']}), in {input_kind.LANGUAGE_LABEL.get(reading['language'], 'its language')}. "
           f"Given by {by}, and never asked again:", ""]
    out += [f"- {f['id']} {FACETS[f['facet']]['label']} ({_where(f)}): {f['text'][:200]} [owner: given by {by}]"
            for f in reading["facts"][:MAX_BRIEF_FACTS]]
    out += [f"- Decision {d['id']} ({_where(d)}): {d['text'][:200]} [owner: decided in the input]"
            for d in reading["decisions"]]
    out += [f"- Requirement {r['id']} ({_where(r)}): {r['statement'][:200]} [owner: the author's id and wording]"
            for r in reading["requirements"]]
    return out + [""]


# -- the spec: an expert's own ids and wording -----------------------------------------------------------

def _authors_criteria(a: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    """The author's criteria word for word, at most three, each with the draft's kind at its place; at least
    one is a visible test. The draft's own criteria when the author wrote none."""
    kinds = [c.get("kind", "test") for c in draft.get("acceptance", [])]
    criteria = [{"id": f"{a['id']}-AC-{n}", "given": c["given"], "when": c["when"], "then": c["then"],
                 "kind": kinds[n - 1] if n <= len(kinds) else "test"} for n, c in enumerate(a["acceptance"][:3], 1)]
    if criteria and not any(c["kind"] == "test" for c in criteria):
        criteria[0]["kind"] = "test"
    return criteria or draft.get("acceptance", [])


def _as_authored(a: dict[str, Any], draft: dict[str, Any] | None, canon: Any, requested_by: str | None
                 ) -> dict[str, Any]:
    """The author's requirement as the spec keeps it: their id, statement and criteria word for word; the
    draft's criterion kinds by position, its priority and its other sources; provenance by the kernel's rule."""
    from kernel.spec import _provenance

    shaped = draft or {}
    sources = list(dict.fromkeys(["request"] + [s for s in shaped.get("sources", []) if s != "proposed"]))
    prov, by = _provenance(sources, canon, requested_by)
    req = {"id": a["id"], "statement": a["statement"], "sources": sources, "priority": shaped.get("priority", "must"),
           "provenance": prov, "acceptance": _authors_criteria(a, shaped), "wording": "author",
           "author": {"document": a["document"], "lines": a["lines"]}}
    if by:
        req["decided_by"] = by
    if draft is None:
        req["restored"] = "the analyst's draft left it out: kept as the author wrote it"
    return req


def keep_authors(project: Any, reqs: list[dict[str, Any]], limit: int, dropped: list[dict[str, Any]]
                 ) -> list[dict[str, Any]]:
    """The spec's requirements with the author's own first: each keeps its id and wording, and one the
    analyst's draft left out is kept as written. Beyond the maturity's limit the analyst's own go first,
    and each requirement left out is named in ``dropped``, never silently."""
    reading = project.read("inputs.json", None)
    authors = [r for r in (reading or {}).get("requirements", [])
               if _REQ_ID.match(r["id"]) and not _GENERATED.fullmatch(r["id"])] if isinstance(reading, dict) else []
    if not authors:
        return reqs
    from kernel.canon import Canon

    canon, requested_by = Canon(project), (project.read("source.json", {}) or {}).get("requested_by")
    by_id = {r["id"]: r for r in reqs}
    kept = []
    for a in authors:
        draft = by_id.pop(a["id"], None)
        if draft is None and not a["acceptance"]:
            dropped.append({"what": "requirement", "requirement": a["id"], "statement": a["statement"][:200],
                            "why": "the author's requirement has no criterion the kernel could read, and the "
                                   "analyst's draft did not carry it"})
            continue
        kept.append(_as_authored(a, draft, canon, requested_by))
    out = kept + [r for r in reqs if r["id"] in by_id]
    for r in out[limit:]:
        dropped.append({"what": "requirement", "requirement": r["id"], "statement": r["statement"][:200],
                        "why": f"beyond the {limit} requirements this maturity may have; the author's own come first"})
    return out[:limit]
