"""Stages 1 and 2: from what someone asked for to a brief with its questions settled or assumed.

The input can be:
- a vague idea;
- a markdown spec;
- a Solution Factory output folder;
- a factoryctl demo folder.

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
MAX_SOURCE_CHARS = 40_000


class SendBack(RuntimeError):
    """Intake cannot go on: blocking questions are open (FR-A5). ``questions`` lists them."""

    def __init__(self, questions: list):
        self.questions = questions
        super().__init__("blocking questions are open: " + ", ".join(q["id"] for q in questions))


def load_source(source: str) -> tuple[str, str]:
    """Return (kind, text) for an idea, a markdown file, or a folder."""
    path = Path(source)
    try:
        exists = path.exists()
    except OSError:
        exists = False
    if not exists:
        return "idea", source.strip()
    if path.is_file():
        return "markdown", path.read_text(encoding="utf-8", errors="replace")
    if list(path.glob("specs/*/spec.md")) or (path / "PROJECT_STATE_INDEX.md").exists():
        kind, names = "solution_factory", sorted(path.glob("specs/*/spec.md")) + sorted(path.glob("specs/*/plan.md"))
    else:
        kind = "factoryctl_demo"
        names = [p for p in (path / "README.md", path / "SPEC.md", path / "spec.md", path / "brief.md", path / "input.md")
                 if p.exists()]
        names += [p for p in sorted(path.glob("*brief*.md")) if p not in names]
        names += sorted(path.glob("docs/*.md"))[:6]
    parts = []
    for p in names:
        parts.append(f"## {p.relative_to(path)}\n\n" + p.read_text(encoding="utf-8", errors="replace"))
    return kind, "\n\n".join(parts).strip()


def _cut_note(text: str) -> str:
    """What the panel is told when the request is longer than it may read: never a silent cut."""
    if len(text) <= MAX_SOURCE_CHARS:
        return ""
    return f"(The request was cut at {MAX_SOURCE_CHARS:,} of {len(text):,} characters: the rest is not shown.)\n"


def _panel_prefix(text: str, kind: str, maturity: str) -> str:
    """The part every perspective's prompt shares, word for word: the request and the instructions.
    It comes first, so an endpoint that caches prompt prefixes reads the request once per panel."""
    n = QUESTIONS_PER_PERSPECTIVE[maturity]
    return f"""Review a request for a software solution from one perspective, named at the end.

The request, verbatim ({kind}):
<<<
{text[:MAX_SOURCE_CHARS]}
>>>
{_cut_note(text)}
Target maturity: **{maturity}**: {MATURITY_MEANING[maturity]}.

Read the request from your perspective only. Ask at most {n} questions whose answers change what
gets built, and nothing the request already says. Mark a question blocking only if building
without its answer would probably build the wrong thing. Give each question the answer you would
assume if nobody answers, and two to four short options a person can pick, that answer first.

Answer with this JSON in a ```json block:
{{"reading": "two or three sentences: what this request means from your perspective",
  "questions": [{{"text": "...", "why": "...", "blocking": false, "proposed_answer": "...",
                  "options": ["the proposed answer", "a real alternative", "another alternative"]}}]}}

"""


def _perspective_prompt(perspective: str, text: str, kind: str, maturity: str, profile: dict | None = None) -> str:
    """One perspective's prompt: the panel's shared prefix, then this perspective last (FR-Z1-AC-3)."""
    from kernel.profiles import panel_focus

    return (_panel_prefix(text, kind, maturity)
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


def intake(project, source: str, *, model, requested_by: str | None = None,
           perspectives=PERSPECTIVES, literal: bool = False) -> dict:
    """Run the panel on ``source`` and settle each question by the project's mode. With ``literal``
    the source is the request's own text, never a path to read: a need that arrived from outside
    (a validated concept) or the contents of a request file."""
    meta = project.meta
    mode, maturity = meta["mode"], meta["maturity"]
    kind, text = ("idea", source.strip()) if literal else load_source(source)
    if not text:
        raise ValueError("the request is empty")
    from kernel.profiles import add_profile_question, choose, profile_of, propose_profile

    canon = Canon(project)
    _keep_source(project, kind, text, requested_by)
    proposal = None
    if not meta.get("profile"):  # a person's choice stands; otherwise propose one by rule
        proposal = propose_profile(text)
        unsure = {"confidence": "uncertain", "candidates": proposal["candidates"],
                  "why": proposal["uncertain_because"]} if proposal["confidence"] == "uncertain" else {}
        choose(project, proposal["profile"], basis={"by": "rule", "keywords": proposal["basis"], **unsure})
    profile = profile_of(project)

    readings, added = {}, []
    for perspective in perspectives:
        try:
            answer = _ask_json(model, _perspective_prompt(perspective, text, kind, maturity, profile))
        except ModelError as exc:
            canon.note("intake", f"perspective {perspective} gave no usable answer: {exc}")
            readings[perspective] = "(no usable answer; not measured)"
            continue
        readings[perspective] = str(answer.get("reading", "")).strip()
        for item in (answer.get("questions") or [])[:QUESTIONS_PER_PERSPECTIVE[maturity]]:
            if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                continue
            proposed = str(item.get("proposed_answer", "")).strip()
            q = canon.add_question(str(item["text"]).strip(), perspective, blocking=bool(item.get("blocking")),
                                   opinions={perspective: proposed} if proposed else {},
                                   rationale=str(item.get("why", "")).strip(),
                                   options=([proposed] if proposed else []) + [
                                       str(o).strip() for o in (item.get("options") or [])
                                       if str(o).strip() and str(o).strip() != proposed][:3])
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
        q = canon.add_question(seed["text"], seed["perspective"], blocking=False,
                               opinions={seed["perspective"]: seed["proposed"]}, options=seed["options"][:4],
                               rationale=f"Asked for every {profile['label'].lower()} project.")
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
    project.write("readings.json", readings)
    asked, assumed = [], []
    for q in canon.questions("open"):
        proposed = q["opinions"].get(q["perspective"], "")
        to_person = mode == "socratic" or (mode == "mixed" and q["blocking"]) or not proposed
        if to_person:
            asked.append(canon.ask(q["id"])["id"])
        else:
            assumed.append(canon.assume(q["id"], proposed)["id"])

    render_brief(project)
    project.update_meta(stage=2)
    project.log("intake_done", {"kind": kind, "mode": mode, "maturity": maturity, "questions": len(added),
                                "asked": len(asked), "assumed": len(assumed)})
    return {"kind": kind, "questions": len(added), "asked": asked, "assumed": assumed, "readings": readings}


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
    if readings:
        lines += ["## Readings by perspective [proposed]", ""]
        lines += [f"- **{p}**: {r} [proposed]" for p, r in readings.items()]
        lines.append("")
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
