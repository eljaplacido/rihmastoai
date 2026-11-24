"""What arrived at intake, read by rule: its kind, its language and what it states (docs/guides/inputs.md).

Any input, from any author, is one of:
- a **need**: a business user's need, often a sentence or two, and vague;
- a **specification**: an expert's requirements, with the author's own ids and given / when / then criteria;
- a **plan**: a complete plan in sections, with decisions, that leaves a few things open;
- **reference** material: a table that supports the other documents of a folder;
- a **folder** of documents: each is read on its own, and the folder states what any of them states.

The reading is deterministic first. Length, headings, lists, tables, requirement-like sentences,
acceptance language, the author's requirement ids and numbered decisions decide the kind, and the
reading's basis names every rule that fired. What the input states is read against the facet checklist
(kernel/input_facets.py), each fact with its document and lines. A model may refine the reading
afterwards (`refine`): its proposal is recorded as model_proposed, the lines it cites are checked
against the input and quoted by the kernel, and it decides nothing.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from kernel.input_facets import CUES, FACET_IDS, FACETS, LIST_ITEM, facts_of, headings

SCHEMA = "rihmasto.input-reading/1"
KINDS = ("need", "specification", "plan", "reference", "folder")
KIND_LABEL = {"need": "a need", "specification": "a specification", "plan": "a plan",
              "reference": "reference material", "folder": "a folder of documents"}
LANGUAGE_LABEL = {"en": "English", "fi": "Finnish", "mixed": "more than one language", "unknown": "no language read"}
NEED_WORDS = 150       # a need is short: at most this many words, and at most one heading
MAX_LINES_CITED = 40   # a model's citation spans at most this many lines

WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
MODAL = re.compile(r"\b(?:must|shall|should|needs? to|has to|have to|is required to|pitää|täytyy|tulee|on oltava"
                   r"|pitäisi)\b", re.IGNORECASE)
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
FI_WORDS = {"ja", "että", "ei", "se", "tai", "kun", "niin", "jotta", "ovat", "olla", "myös", "kanssa", "mutta", "nyt",
            "joka", "jossa", "tämä", "voi", "pitää", "haluamme", "meidän", "sekä", "kaikki", "eivät", "kuin"}
EN_WORDS = {"the", "and", "is", "are", "to", "of", "a", "an", "that", "we", "it", "in", "for", "with", "be", "must",
            "should", "our", "by", "as", "when", "then", "who", "what", "which"}


def split_lines(text: str) -> list[str]:
    """The input's lines as people number them: the first is line 1."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def language(text: str) -> str:
    """fi, en, mixed or unknown: by the share of common Finnish and English words."""
    words = [w.lower() for w in WORD.findall(text)]
    fi = sum(w in FI_WORDS for w in words) + sum(("ä" in w or "ö" in w) for w in words) / 2
    en = sum(w in EN_WORDS for w in words)
    if fi < 1 and en < 1:
        return "unknown"
    if fi >= 2 * en:
        return "fi"
    return "en" if en >= 2 * fi else "mixed"


def signals(lines: list[str], read: dict[str, Any]) -> dict[str, int]:
    """The deterministic signals the kind is decided by."""
    text = "\n".join(lines)
    acceptance = sum(len(r["acceptance"]) for r in read["requirements"])
    acceptance += sum(1 for line in lines if CUES["acceptance"].search(line)) if not acceptance else 0
    return {
        "chars": len(text.strip()), "words": len(WORD.findall(text)), "lines": sum(1 for x in lines if x.strip()),
        "headings": len(headings(lines)), "list_items": sum(1 for x in lines if LIST_ITEM.match(x)),
        "table_rows": sum(1 for x in lines if TABLE_ROW.match(x)),
        "requirement_sentences": sum(1 for x in lines if MODAL.search(x)), "acceptance": acceptance,
        "requirement_ids": len(read["requirements"]), "decisions": len(read["decisions"]),
        "facets_stated": len({f["facet"] for f in read["facts"]}),
    }


Kind = tuple[str, str, list[str]]      # the kind, certain or uncertain, and the rules that decided it


def _structured(sig: dict[str, int]) -> Kind | None:
    """A specification by its ids and criteria, or a plan by its decisions or its sections: certain."""
    if sig["requirement_ids"] >= 2 and (sig["acceptance"] >= 1 or sig["requirement_sentences"] >= 2):
        sure = sig["acceptance"] >= 1
        return "specification", "certain" if sure else "uncertain", [
            f"{sig['requirement_ids']} requirements with the author's own ids",
            f"{sig['acceptance']} acceptance criteria" if sure else "no acceptance criteria"]
    if sig["decisions"] >= 2 or (sig["headings"] >= 4 and sig["facets_stated"] >= 5):
        return "plan", "certain", [f"{sig['decisions']} decisions", f"{sig['headings']} headings",
                                   f"{sig['facets_stated']} facets of the checklist stated"]
    return None


def kind_of(sig: dict[str, int]) -> Kind:
    """The kind by fixed rules, in order: its name, certain or uncertain, and the rule that decided it."""
    found = _structured(sig)
    if found:
        return found
    if sig["table_rows"] >= 3 and sig["table_rows"] * 2 >= sig["lines"]:
        return "reference", "certain", [f"{sig['table_rows']} of {sig['lines']} lines are table rows"]
    if sig["words"] <= NEED_WORDS and sig["headings"] <= 1:
        return "need", "certain", [f"{sig['words']} words", "no sections" if not sig["headings"] else "one heading"]
    if sig["requirement_sentences"] >= 3 or sig["acceptance"] >= 2:
        return "specification", "uncertain", [f"{sig['requirement_sentences']} requirement-like sentences, "
                                              "but no requirement ids of the author's own"]
    if sig["headings"] >= 2:
        return "plan", "uncertain", [f"{sig['headings']} headings, but few decisions or facets stated"]
    return "need", "uncertain", [f"{sig['words']} words with little structure: a need told at length"]


def read_document(name: str, text: str) -> dict[str, Any]:
    """One document's reading: its kind, language, signals, facts, requirements and decisions."""
    lines = split_lines(text)
    read = facts_of(lines)
    sig = signals(lines, read)
    kind, confidence, basis = kind_of(sig)
    return {"name": name, "kind": kind, "confidence": confidence, "basis": basis, "language": language(text),
            "lines": len(lines), "signals": sig, **read}


def _placed(items: list[dict[str, Any]], doc: str) -> list[dict[str, Any]]:
    """Each item with the document it was read in."""
    return [{**x, "document": doc} for x in items]


def _gathered(docs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The documents' facts (numbered F-001 on, in document order), requirements, decisions and the facets
    they leave open, each with its document. The documents keep only their own reading."""
    out: dict[str, list[dict[str, Any]]] = {"facts": [], "requirements": [], "decisions": [], "left_open": []}
    for d in docs:
        for key, items in out.items():
            items += _placed(d.pop(key), d["name"])
    out["facts"] = [{"id": f"F-{n:03d}", **f} for n, f in enumerate(out["facts"], 1)]
    return out


def _of_folder(docs: list[dict[str, Any]]) -> tuple[Kind, str]:
    """A folder's kind, basis and language: mixed when its documents are in more than one."""
    langs = {d["language"] for d in docs} - {"unknown"}
    lang = langs.pop() if len(langs) == 1 else ("mixed" if langs else "unknown")
    basis = [f"a folder of {len(docs)} documents: " + ", ".join(f"{d['name']} ({d['kind']})" for d in docs)]
    return ("folder", "certain", basis), lang


def read(documents: list[tuple[str, str]], *, folder: bool = False) -> dict[str, Any]:
    """The reading of what arrived: one document, or a folder's documents each read on its own."""
    docs = [read_document(name, text) for name, text in documents if text.strip()]
    if not docs:
        raise ValueError("the request is empty")
    found = _gathered(docs)
    given = [f for f in FACET_IDS if any(x["facet"] == f for x in found["facts"])]
    one = docs[0]
    (kind, confidence, basis), lang = (_of_folder(docs) if folder and len(docs) > 1 else
                                       ((one["kind"], one["confidence"], one["basis"]), one["language"]))
    return {"schema": SCHEMA, "kind": kind, "confidence": confidence, "kind_by": "rule", "basis": basis,
            "language": lang, "documents": docs, **found, "given": given,
            "gaps": [f for f in FACET_IDS if f not in given],
            "left_open": [o for o in found["left_open"] if o["facet"] not in given],
            "sha256": hashlib.sha256("\n\n".join(t for _, t in documents).encode("utf-8")).hexdigest()}


# -- a model refines the reading: proposed, checked, never decided -------------------------------------

def refine_prompt(reading: dict[str, Any], numbered: str) -> str:
    """What the analyst's model is asked: the request with its lines numbered, and the rule's reading."""
    facets = "\n".join(f"- {f}: {FACETS[f]['label']}" for f in FACET_IDS)
    return f"""You check how a factory read a request it received. The kernel read it by rule; you may see what
the rule missed. You decide nothing: a person reads your proposal beside the rule's reading.

The request, verbatim, each line numbered:
<<<
{numbered}
>>>

The rule read it as {KIND_LABEL[reading['kind']]} ({reading['confidence']}). It found these facets stated:
{', '.join(reading['given']) or 'none'}. And these not stated: {', '.join(reading['gaps']) or 'none'}.

The kinds: need (a business user's need, short or vague), specification (an expert's requirements with ids
or given / when / then criteria), plan (a complete plan in sections, with decisions), reference (a table or
a list that supports other documents).
The facets:
{facets}

Answer with this JSON in a ```json block:
{{"kind": "plan", "why": "one sentence", "stated": [{{"facet": "privacy", "lines": [12, 13]}}]}}
Name in "stated" only facets the rule did not find that the request states, with the lines that state them.
"""


def _cited(item: Any, reading: dict[str, Any], lines: list[str]) -> tuple[dict[str, Any] | None, str]:
    """A facet the model says the request states, checked: a facet of the checklist the rule did not
    find, on lines that exist and are not empty. The kernel quotes the lines; the model's words never."""
    if not isinstance(item, dict) or item.get("facet") not in FACETS:
        return None, "not a facet of the checklist"
    span = item.get("lines")
    if not (isinstance(span, list) and len(span) == 2 and all(isinstance(n, int) for n in span)):
        return None, "no line numbers"
    first, last = span
    if not 1 <= first <= last <= len(lines) or last - first >= MAX_LINES_CITED:
        return None, f"lines {first}-{last} are not lines of the request"
    if not any(x.strip() for x in lines[first - 1:last]):
        return None, f"lines {first}-{last} are empty"
    if item["facet"] in reading["given"]:
        return None, "the rule already found it"
    text = " ".join(x.strip() for x in lines[first - 1:last] if x.strip())
    return {"facet": item["facet"], "lines": [first, last], "text": text[:300]}, ""


def refinement(answer: Any, reading: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    """The model's proposal as the kernel records it: a kind it may propose (never a folder of one
    document), the facets it found with checked lines, and what was left out and why."""
    answer = answer if isinstance(answer, dict) else {}
    kind = answer.get("kind") if answer.get("kind") in KINDS and answer.get("kind") != "folder" else None
    stated, dropped = [], []
    for item in (answer.get("stated") or [])[:20]:
        fact, why = _cited(item, reading, lines)
        if fact:
            stated.append(fact)
        else:
            dropped.append({"item": str(item)[:200], "why": why})
    return {"kind": kind, "why": str(answer.get("why") or "")[:300], "stated": stated, "dropped": dropped}
