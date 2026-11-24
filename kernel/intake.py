"""Stages 1 and 2: from what someone asked for to a brief with its questions settled or assumed.

The input can be:
- a vague idea;
- a written spec, in a file of any format kernel/material_read.py reads;
- any folder: it is scanned (kernel/material.py), and its request is built from the material map, the
  most telling files first, within MAX_SOURCE_CHARS. A folder a person confirmed from its scan arrives as
  the request's own text, and keeps its documents by the map the project holds (material.json);
- a confidential project's request goes only to a local model (kernel/confidential.py).

A panel of perspectives reads it (FR-A7): business, end user, IT and security, operations, and
delivery. Each proposes the questions whose answers change what gets built, with the answer
it would assume. The mode decides what happens to each question (FR-A6):
- `socratic`: every question goes to a person, as an Inbox card. Nothing is assumed.
- `assume`: the factory takes each proposed answer as an assumption with a due date.
- `mixed`: blocking questions go to a person, and the rest are assumed.

A person may answer any open question, or press "let the factory assume". Where perspectives
disagree, the opinions are kept side by side on the question.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel import input_intake as inputs
from kernel.canon import PERSPECTIVES, Canon
from kernel.model import ModelError, extract_json

PERSPECTIVE_VOICES = {
    "business": "the business owner who pays for this and measures its benefit: the goal, the value, "
                "the success metric and its baseline, scope, priority, and who decides",
    "end_user": "the people who will use it every day: their tasks and workflows, what frustrates them "
                "today, accessibility and language",
    "it_security": "the customer's IT or IT partner: where it runs, identity and access, data protection, "
                   "network and security rules, and integrations with existing systems",
    "operations": "the people who keep it running: availability, monitoring, backups, support, and how "
                  "changes and incidents are handled",
    "delivery": "the delivery team: what is unclear or contradictory, the smallest useful first version, "
                "the risks, and what can be tested",
}

MATURITY_MEANING = {
    "explore": "a walking skeleton to explore the idea; nobody depends on it",
    "demo": "a working demo for the owner to try; not for real users",
    "pilot": "a pilot that real users try on staging with realistic data before any production use",
    "production": "a production service that people depend on, deployed on the paved road behind IT's gate",
}

LOOK_QUESTION = "What look and feel should the product's screens have: neutral, warm or night?"
QUESTIONS_PER_PERSPECTIVE = {"explore": 2, "demo": 3, "pilot": 4, "production": 5}
MAX_SOURCE_CHARS = 40_000   # the request the panel reads; a folder's material map keeps to it (kernel/material.py)


class SendBack(RuntimeError):
    """Intake cannot go on: blocking questions are open (FR-A5). ``questions`` lists them."""

    def __init__(self, questions: list):
        self.questions = questions
        super().__init__("blocking questions are open: " + ", ".join(q["id"] for q in questions))


Material = tuple[str, str, list[tuple[str, str]] | None, dict[str, Any] | None]


def _one_file(path: Path) -> str:
    """A single file's text, by its format (kernel/material_read.py); a secret-looking file is refused."""
    from kernel import material_kinds, material_read

    rel = path.name
    if material_kinds.secret_by_name(rel):
        raise ValueError(f"{rel} may hold secrets: it is never read")
    ext = path.suffix.lower()
    got = material_read.extract(path.read_bytes(), ext if ext in material_read.READABLE else ".txt")
    if material_kinds.secret_in_text(rel, got.text):
        raise ValueError(f"{rel} may hold secrets: its text holds a credential, so it is not read")
    return got.text


def load_material(source: str, exclude: tuple[str, ...] | list[str] = ()) -> Material:
    """(kind, text, documents, material map) for an idea, a file, or a folder. A folder is scanned
    (kernel/material.py): its text is built from the map, each part headed with its file and kind."""
    path = Path(source)
    try:
        exists = path.exists()
    except (OSError, ValueError):
        exists = False
    if not exists:
        return "idea", source.strip(), None, None
    if path.is_file():
        return "markdown", _one_file(path), None, None
    from kernel import material

    mp, text, documents = material.gather(path, exclude)
    kind = "solution_factory" if list(path.glob("specs/*/spec.md")) or (path / "PROJECT_STATE_INDEX.md").exists() \
        else "folder"
    return kind, text, documents, mp


def load_source(source: str, exclude: tuple[str, ...] | list[str] = ()) -> tuple[str, str]:
    """Return (kind, text) for an idea, a file, or a folder (its material map's request)."""
    kind, text, _, _ = load_material(source, exclude)
    return kind, text


def _cut_note(text: str) -> str:
    """What the panel is told when the request is longer than it may read: never a silent cut."""
    if len(text) <= MAX_SOURCE_CHARS:
        return ""
    return f"(The request was cut at {MAX_SOURCE_CHARS:,} of {len(text):,} characters: the rest is not shown.)\n"


def _panel_prefix(text: str, kind: str, maturity: str, note: str = "", given: str = "") -> str:
    """The part every perspective's prompt shares, word for word: the request and the instructions.
    It comes first, so an endpoint that caches prompt prefixes reads the request once per panel.
    ``given`` is what the chosen outputs already settle (kernel/outputs.py given_for_panel)."""
    n = QUESTIONS_PER_PERSPECTIVE[maturity]
    return f"""Review a request for a software solution from one perspective, named at the end.

The request, verbatim ({kind}):
<<<
{text[:MAX_SOURCE_CHARS]}
>>>
{_cut_note(text)}{note}
Target maturity: **{maturity}**: {MATURITY_MEANING[maturity]}.
{given}
Read the request from your perspective only. Ask at most {n} questions whose answers change what
gets built, and nothing the request already says. Mark a question blocking only if building
without its answer would probably build the wrong thing. Give each question the answer you would
assume if nobody answers, and two to four short options a person can pick, that answer first.

Answer with this JSON in a ```json block:
{{"reading": "two or three sentences: what this request means from your perspective",
  "questions": [{{"text": "...", "why": "...", "blocking": false, "proposed_answer": "...",
                  "options": ["the proposed answer", "a real alternative", "another alternative"]}}]}}

"""


def _perspective_prompt(perspective: str, text: str, kind: str, maturity: str, profile: dict | None = None,
                        note: str = "", given: str = "") -> str:
    """One perspective's prompt: the panel's shared prefix, then this perspective last (FR-Z1-AC-3)."""
    from kernel.profiles import panel_focus

    return (_panel_prefix(text, kind, maturity, note, given)
            + f"You are the **{perspective}** perspective on a panel reviewing this request. "
            + f"You speak for {PERSPECTIVE_VOICES[perspective]}.\n"
            + (panel_focus(profile, perspective) if profile else ""))


def _opinions_prompt(questions: list) -> str:
    listing = "\n".join(f"- {q['id']} ({q['perspective']}): {q['text']}\n  proposed: {q['proposed']}"
                        for q in questions)
    return f"""A panel of perspectives ({', '.join(PERSPECTIVES)}) asked these questions about a
software request. Each has the proposed answer of the perspective that asked it.

{listing}

For each question where another perspective would answer differently, give that perspective's
opinion in one sentence. Include real disagreements only; an empty list is a fine answer.

Answer with this JSON in a ```json block:
{{"opinions": [{{"question": "Q-001", "perspective": "it_security", "opinion": "..."}}]}}
"""


def _ask_json(model, prompt: str, role: str = "analyst", retries: int = 1):
    last = None
    for _ in range(retries + 1):
        try:
            return extract_json(model.ask(prompt, role=role))
        except ModelError as exc:
            last = exc
    raise last


def _keep_source(project: Any, kind: str, text: str, requested_by: str | None) -> None:
    """Keep the request as the panel reads it. A request longer than the panel may read is cut,
    and the cut is recorded in the ledger and on the source, never silent (FR-Z1-AC-3)."""
    source: dict[str, Any] = {"kind": kind, "text": text[:MAX_SOURCE_CHARS], "requested_by": requested_by}
    if len(text) > MAX_SOURCE_CHARS:
        source["cut_from"] = len(text)
        project.log("request_cut", {"kind": kind, "kept": MAX_SOURCE_CHARS, "of": len(text)})
    project.write("source.json", source)
    project.update_meta(source_kind=kind, requested_by=requested_by)


def _request(project: Any, source: str, literal: bool) -> Material:
    """What intake reads: a request's own text (a folder's request a person confirmed from its scan keeps
    its documents, by the map in material.json), or an idea, a file or a folder, scanned now."""
    if not literal:
        return load_material(source)
    from kernel.material import recorded

    text = source.strip()
    documents = recorded(project, text)
    return ("folder" if documents else "idea"), text, documents, None


def _norm(text: str) -> str:
    """A question's words as compared for "asked before": case, spacing and the closing mark do not count."""
    return " ".join(str(text).lower().split()).rstrip("?.! ")


class KnownCanon(Canon):
    """A canon that never adds a question already on record, by its words: an intake run again (after going
    back to the questions, kernel/rewind.py) or over added material (kernel/project_material.py) asks only
    what is new. A settled question (answered or assumed) is known; an open one too with ``keep_open``.
    Adding a known question gives back the one on record."""

    def __init__(self, project: Any, *, keep_open: bool = False) -> None:
        super().__init__(project)
        self.known = {_norm(q["text"]): q for q in self.questions()
                      if q["status"] != "withdrawn" and (keep_open or q["status"] != "open")}

    def add_question(self, text: str, perspective: str, **kwargs: Any) -> dict:
        found: dict | None = self.known.get(_norm(text))
        return found if found is not None else super().add_question(text, perspective, **kwargs)


def settled_note(canon: Canon) -> str:
    """What the panel is told was asked and settled before ("" when nothing was): never asked again."""
    rows = [q for q in canon.questions() if q["status"] in ("answered", "assumed")][:40]
    return ("\nAlready asked and settled (never ask these again):\n"
            + "".join(f"- {q['text']}: {str((q.get('answer') or {}).get('text', ''))[:160]}\n" for q in rows)) \
        if rows else ""


def intake(project, source: str, *, model, requested_by: str | None = None,
           perspectives=PERSPECTIVES, literal: bool = False, kind: str | None = None) -> dict:
    """Run the panel on ``source`` and settle each question by the project's mode. With ``literal``
    the source is the request's own text, never a path to read: a need that arrived from outside
    (a validated concept) or the contents of a request file; ``kind`` names what it was (an intake run
    again keeps its source's kind, kernel/rewind.py). A question settled before is never asked again."""
    meta = project.meta
    mode, maturity = meta["mode"], meta["maturity"]
    found, text, documents, mp = _request(project, source, literal)
    kind = (kind or found) if literal else found        # an intake run again keeps its source's kind
    if not text:
        raise ValueError("the request is empty")
    from kernel.confidential import require_local
    from kernel.profiles import add_profile_question, choose, profile_of, propose_profile

    require_local(project, ("analyst",), where="intake")     # confidential: nothing leaves for a hosted endpoint
    canon = KnownCanon(project)     # what a person settled before is never asked again
    if mp is not None:
        from kernel.material import record

        record(project, mp, person=requested_by)
    _keep_source(project, kind, text, requested_by)
    reading = inputs.record(project, kind, text, None if literal else source, requested_by,   # read by rule
                            documents=documents)
    proposal = None
    if not meta.get("profile"):  # a person's choice stands; otherwise propose one by rule
        proposal = propose_profile(text)
        unsure = {"confidence": "uncertain", "candidates": proposal["candidates"],
                  "why": proposal["uncertain_because"]} if proposal["confidence"] == "uncertain" else {}
        choose(project, proposal["profile"], basis={"by": "rule", "keywords": proposal["basis"], **unsure})
    profile = profile_of(project)
    from kernel.outputs import asked_again, given_for_panel  # what the chosen outputs settle is never asked again

    readings, added, given = {}, [], given_for_panel(project) + settled_note(canon)
    for perspective in perspectives:
        try:
            answer = _ask_json(model, _perspective_prompt(perspective, text, kind, maturity, profile,
                                                          inputs.panel_note(reading), given))
        except ModelError as exc:
            canon.note("intake", f"perspective {perspective} gave no usable answer: {exc}")
            readings[perspective] = "(no usable answer; not measured)"
            continue
        readings[perspective] = str(answer.get("reading", "")).strip()
        for item in (answer.get("questions") or [])[:QUESTIONS_PER_PERSPECTIVE[maturity]]:
            if not isinstance(item, dict) or not str(item.get("text", "")).strip() or asked_again(
                    project, str(item["text"]).strip(), perspective):
                continue
            if inputs.already_given(reading, item, perspective):   # the input states it: never asked again
                continue
            proposed = str(item.get("proposed_answer", "")).strip()
            q = canon.add_question(str(item["text"]).strip(), perspective, blocking=bool(item.get("blocking")),
                                   opinions={perspective: proposed} if proposed else {},
                                   rationale=str(item.get("why", "")).strip(),
                                   options=([proposed] if proposed else []) + [
                                       str(o).strip() for o in (item.get("options") or [])
                                       if str(o).strip() and str(o).strip() != proposed][:3])
            inputs.tag(reading, q["id"], item)
            added.append({"id": q["id"], "perspective": perspective, "text": q["text"], "proposed": proposed})

    if len(added) > 1:
        try:
            ops = _ask_json(model, _opinions_prompt(added)).get("opinions") or []
        except ModelError:
            ops = []
        known = {q["id"] for q in added}
        for op in ops:
            if (isinstance(op, dict) and op.get("question") in known and op.get("perspective") in PERSPECTIVES
                    and str(op.get("opinion", "")).strip()):
                canon.add_opinion(op["question"], op["perspective"], str(op["opinion"]).strip())

    # The profile's own questions, asked once: the ones its kind of work always needs answered.
    for seed in profile.get("seed_questions", []):
        if inputs.already_given(reading, seed, seed["perspective"], seed=True):
            continue
        q = canon.add_question(seed["text"], seed["perspective"], blocking=False,
                               opinions={seed["perspective"]: seed["proposed"]}, options=seed["options"][:4],
                               rationale=f"Asked for every {profile['label'].lower()} project.")
        inputs.tag(reading, q["id"], seed)
        added.append({"id": q["id"], "perspective": seed["perspective"], "text": q["text"], "proposed": seed["proposed"]})
    # Ask the look once, at setup (after Astryx): every product with screens gets one, so it is
    # worth a question rather than screens rebuilt around the wrong look later.
    if profile.get("screens", True):
        look = canon.add_question(LOOK_QUESTION, "end_user", blocking=False,
                                  opinions={"end_user": "neutral: the paved road's default look"},
                                  options=["neutral: the paved road's default look", "warm", "night (dark only)"],
                                  rationale="Asked once at setup, so screens are not rebuilt around the wrong look.")
        added.append({"id": look["id"], "perspective": "end_user", "text": look["text"], "proposed": "neutral"})
    # A proposal the rule is unsure of, where the request's words point to more than one kind of work,
    # asks a person which it is, with the top candidates (FR-DF4-AC-2). Words pointing to one profile
    # or none keep it, and its basis says it is uncertain.
    if proposal and proposal["confidence"] == "uncertain" and sum(n > 0 for n in proposal["scores"].values()) > 1:
        add_profile_question(canon, proposal)
    added += inputs.ask_gaps(canon, reading, maturity, inputs.posture_of(project))   # the checklist's gaps
    inputs.finish(project, reading)
    project.write("readings.json", readings)
    asked, assumed = [], []
    for q in (x for x in canon.questions("open") if not x.get("card")):   # one put to a person stays so
        proposed = q["opinions"].get(q["perspective"], "")
        to_person = mode == "socratic" or (mode == "mixed" and q["blocking"]) or not proposed
        if to_person:
            asked.append(canon.ask(q["id"])["id"])
        else:
            assumed.append(canon.assume(q["id"], proposed)["id"])

    render_brief(project)
    project.update_meta(stage=2)
    project.log("intake_done", {"kind": kind, "mode": mode, "maturity": maturity, "questions": len(added),
                                "asked": len(asked), "assumed": len(assumed), "input_kind": reading["kind"]})
    return {"kind": kind, "questions": len(added), "asked": asked, "assumed": assumed, "readings": readings,
            **inputs.outcome(reading)}


def _source_line(meta: dict, source: dict) -> str:
    """The brief's first line: maturity, mode, where the request came from, and how much the panel
    read of it when it was cut."""
    line = f"Maturity: **{meta['maturity']}**. Mode: **{meta['mode']}**. Source: {source.get('kind', '?')}"
    if source.get("requested_by"):
        line += f", from {source['requested_by']}"
    line += "."
    if source.get("cut_from"):
        line += f" The panel read its first {MAX_SOURCE_CHARS:,} of {source['cut_from']:,} characters."
    return line


def render_brief(project) -> str:
    """The brief is generated from the canon, with every statement tagged by provenance (FR-A3)."""
    meta, canon = project.meta, Canon(project)
    source = project.read("source.json", {}) or {}
    readings = project.read("readings.json", {}) or {}
    lines = [f"# Brief: {meta['title']}", "", _source_line(meta, source), "", "## The request [owner]", ""]
    for para in [p.strip() for p in (source.get("text") or "").split("\n\n") if p.strip()][:40]:
        lines.append(para + " [owner]")
        lines.append("")
    lines += inputs.brief_lines(project)   # what the input states, by facet, with its lines
    if readings:
        lines += ["## Readings by perspective [proposed]", ""]
        lines += [f"- **{p}**: {r} [proposed]" for p, r in readings.items()]
        lines.append("")
    from kernel.outputs import brief_lines

    lines += brief_lines(project)  # the chosen outputs, the chooser's word: the spec reads them here
    answered = canon.questions("answered")
    if answered:
        lines += ["## Answers [owner]", ""]
        for q in answered:
            lines.append(f"- {q['id']} ({q['perspective']}): {q['text']}: **{q['answer']['text']}** "
                         f"[owner: {q['answer']['by']}]")
        lines.append("")
    assumptions = canon.assumptions()
    if assumptions:
        lines += ["## Assumptions [assumed]", ""]
        for a in assumptions:
            lines.append(f"- {a['id']} ({a['perspective']}, due {a['due']}, {a['status']}): {a['text']} [assumed]")
        lines.append("")
    open_qs = canon.questions("open")
    if open_qs:
        lines += ["## Open questions", ""]
        for q in open_qs:
            flag = " **blocking**" if q["blocking"] else ""
            lines.append(f"- {q['id']} ({q['perspective']}){flag}: {q['text']}")
            others = {p: o for p, o in q["opinions"].items() if p != q["perspective"]}
            for p, o in others.items():
                lines.append(f"  - opinion, {p}: {o}")
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    canon.write_brief(text)
    return text


def blocking_open(project) -> list:
    return [q for q in Canon(project).questions("open") if q["blocking"]]
