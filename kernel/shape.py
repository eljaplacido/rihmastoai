"""Shape it in chat (D-0022, FR-SHP1, docs/guides/shape-in-chat.md): work out what is needed with Rihma, in
conversation, before a project exists.

A person opens a conversation with nothing, a sentence or a file, and talks with Rihma: the analyst role,
asked through the factory's usual model plumbing (Gnomon in the analyst lane; scripted models in tests).
Rihma asks one or two questions at a time and keeps a running draft brief (who it is for, the problem, the
outcomes, what is in and out of scope, the constraints, the data and systems, the open questions) that the
person sees beside the chat and may edit. A field the person edited is theirs: Rihma's later drafts leave it
as it is. Rihma says when the draft is good enough; by rule it is when it says who it is for, the problem,
an outcome and what is in scope.

"Create the project from this" turns the draft into a project: the draft, as a Markdown brief whose headings
name the checklist's facets, is the project's request, so intake reads those facets as given and never asks
them again (kernel/input_intake.py, FR-IK1). The person chooses the work profile, the mode and the maturity
then, with Rihma's suggestion and why.

The conversation is kept under the factory home's ``_shape/<id>/`` (``shape.json``, and the attached
material as text in ``files/``) and can be resumed. The factory's ledger records each signed step:
shape_started, shape_said, shape_attached, shape_draft_edited and shape_created; a message's words stay
in the conversation's file, the ledger has their length and hash.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.model import Model, ModelError, extract_json
from kernel.people import PERSONAS, is_person
from kernel.store import MATURITIES, MODES, Factory, Project, read_json, records_lock, updating_json, write_text

SCHEMA = "rihmasto.shape/1"
ID = re.compile(r"SH-\d{3,6}\Z")
# The draft's fields: (key, label, holds a list, the Markdown heading the brief gives it).
FIELDS: tuple[tuple[str, str, bool, str], ...] = (
    ("title", "Title", False, ""),
    ("for_whom", "Who it is for", False, "Users and roles"),
    ("problem", "The problem", False, "The problem"),
    ("outcomes", "Outcomes", True, "Goals and success measures"),
    ("scope_in", "In scope", True, "Scope: the first version"),
    ("scope_out", "Out of scope", True, "Out of scope"),
    ("constraints", "Constraints", True, "Constraints"),
    ("data_systems", "Data and systems", True, "Data and systems"),
    ("open_questions", "Open questions", True, "Open questions"),
)
KEYS = tuple(f[0] for f in FIELDS)
NEEDED = ("for_whom", "problem", "outcomes", "scope_in")
MAX_MESSAGE, MAX_ITEMS, MAX_ITEM = 8000, 12, 600
MAX_ATTACH = 200_000          # characters kept from one attachment
PROMPT_ATTACH = 24_000        # characters of attached material in a prompt
PROMPT_TURNS = 24             # the latest messages a prompt carries
STALE_SECONDS = 900          # a turn pending longer than this lost its answer (the model call times out sooner)
MODELS_LINK = "#/models"
OPENING = ("Hello, I'm Rihma. Tell me what you need in your own words: who it is for, and what problem it "
           "solves. You can attach a file or a folder too. I keep a draft brief beside our chat, and you can "
           "edit it at any time.")
NO_MODEL = ("No model is set up for me yet, so I cannot answer. Your message is kept. Set up the analyst's "
            "model in Models setup, then say it again.")


class ShapeRefused(ValueError):
    """A step the conversation does not take, with the reason."""


# -- where it is kept -----------------------------------------------------------------------------------

def shape_dir(factory: Factory) -> Path:
    return factory.home / "_shape"


def _file(factory: Factory, sid: str) -> Path:
    if not ID.match(sid or ""):
        raise KeyError(f"no conversation {sid!r}")
    return shape_dir(factory) / sid / "shape.json"


def _stale(factory: Factory, conv: dict[str, Any]) -> bool:
    """A turn still marked pending long after it began: its answer was lost (the cockpit stopped meanwhile)."""
    try:
        since = dt.datetime.fromisoformat(str(conv.get("pending_since")).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (factory.clock.now() - since).total_seconds() > STALE_SECONDS


def get(factory: Factory, sid: str) -> dict[str, Any]:
    """A conversation as it is kept; a turn whose answer was lost no longer reads as pending."""
    conv = read_json(_file(factory, sid), None)
    if not isinstance(conv, dict):
        raise KeyError(f"no conversation {sid}")
    if conv.get("pending") and _stale(factory, conv):
        conv["pending"] = False
    return conv


def conversations(factory: Factory) -> list[dict[str, Any]]:
    """Every conversation, newest first, as a line in a list."""
    out = []
    for path in sorted(shape_dir(factory).glob("SH-*/shape.json"), reverse=True):
        c = read_json(path, None)
        if isinstance(c, dict):
            out.append({k: c.get(k) for k in ("id", "state", "started", "started_by", "project", "pending")}
                       | {"title": title_of(c), "messages": len(c.get("messages") or [])})
    return out


def _log(factory: Factory, kind: str, payload: dict[str, Any]) -> None:
    from kernel.learn import factory_project

    factory_project(factory).log(kind, payload)


def _signed(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"refused: {person!r} is not a person; a conversation is signed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"refused: persona must be one of {', '.join(PERSONAS)}")


def _digest(text: str) -> str:
    """The sha256 the ledger keeps of words that stay in the conversation's own file."""
    digest = hashlib.sha256()
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def _message(factory: Factory, by: str, text: str, **extra: Any) -> dict[str, Any]:
    return {"from": by, "text": text, "at": factory.clock.stamp(), **{k: v for k, v in extra.items() if v}}


# -- the draft ------------------------------------------------------------------------------------------

def _clean(key: str, value: Any) -> Any:
    listed = dict((f[0], f[2]) for f in FIELDS)[key]
    if listed:
        items = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        return [" ".join(str(x).split())[:MAX_ITEM] for x in items if str(x).strip()][:MAX_ITEMS]
    return " ".join(str(value or "").split())[:MAX_ITEM if key == "title" else MAX_MESSAGE]


def empty_draft() -> dict[str, Any]:
    return {k: [] if listed else "" for k, _, listed, _ in FIELDS}


def missing(draft: dict[str, Any]) -> list[str]:
    """The labels of the fields a draft still needs to be good enough, by rule."""
    labels = {k: label for k, label, _, _ in FIELDS}
    return [labels[k] for k in NEEDED if not draft.get(k)]


def title_of(conv: dict[str, Any]) -> str:
    draft = conv.get("draft") or {}
    first = next((m["text"] for m in conv.get("messages") or [] if m.get("from") == "person"), "")
    return draft.get("title") or conv.get("title") or " ".join(first.split()[:8]) or "A new need"


def brief(conv: dict[str, Any]) -> str:
    """The draft as the project's request: a Markdown brief whose headings name the checklist's facets, so
    intake reads them as given. Open questions stay in a block intake does not read as stated."""
    draft, out = conv.get("draft") or {}, [f"# {title_of(conv)}", ""]
    for key, _, listed, heading in FIELDS:
        value = draft.get(key)
        if key in ("title", "open_questions") or not value:
            continue
        out += [f"## {heading}", ""] + ([f"- {x}" for x in value] if listed else [value]) + [""]
    if draft.get("open_questions"):
        asked = [f"- {q.replace(':', ' -')}" for q in draft["open_questions"]]
        out += ["## Still to decide", "", "Not yet decided (questions, not answers):", "", "```text", *asked, "```", ""]
    out += [f"(Shaped in conversation with Rihma: {conv.get('id')}, {len(conv.get('messages') or [])} messages.)"]
    return "\n".join(out) + "\n"


def suggestion(conv: dict[str, Any]) -> dict[str, Any]:
    """The work profile, mode and maturity Rihma suggests, and why: the model's, where it named valid ones,
    else the profile by rule over the brief, a mixed mode and a demo."""
    from kernel.profiles import PROFILES, propose_profile

    said = conv.get("suggest") or {}
    rule = propose_profile(brief(conv))
    profile = said.get("profile") if said.get("profile") in PROFILES else rule["profile"]
    why = [said["why"]] if said.get("why") else []
    if profile == rule["profile"] and profile != said.get("profile"):
        why.append(f"the work profile by rule: {', '.join(rule['basis'])}")
    return {"profile": profile, "mode": said.get("mode") if said.get("mode") in MODES else "mixed",
            "maturity": said.get("maturity") if said.get("maturity") in MATURITIES else "demo",
            "why": "; ".join(why) or "the defaults: a demo, with blocking questions asked and the rest assumed"}


def view(conv: dict[str, Any]) -> dict[str, Any]:
    """A conversation as the cockpit and the command line show it."""
    draft = {**empty_draft(), **(conv.get("draft") or {})}
    gaps = missing(draft)
    return {**conv, "title": title_of(conv), "draft": draft, "missing": gaps, "good_enough": not gaps,
            "fields": [{"key": k, "label": label, "list": listed} for k, label, listed, _ in FIELDS],
            "suggestion": suggestion(conv), "brief": brief(conv)}


# -- the conversation's steps --------------------------------------------------------------------------

def _new_id(factory: Factory) -> str:
    root = shape_dir(factory)
    with records_lock(root / "ids.lock"):
        taken = [int(p.name[3:]) for p in root.glob("SH-*") if p.name[3:].isdigit()]
        sid = f"SH-{max(taken, default=0) + 1:03d}"
        (root / sid).mkdir(parents=True)
    return sid


def start(factory: Factory, *, person: str, persona: str, title: str = "") -> dict[str, Any]:
    """Open a conversation, with Rihma's opening words. Signed by a person."""
    _signed(person, persona)
    sid = _new_id(factory)
    conv = {"schema": SCHEMA, "id": sid, "title": _clean("title", title), "state": "open",
            "started": factory.clock.stamp(), "started_by": person, "persona": persona,
            "messages": [_message(factory, "rihma", OPENING)], "draft": empty_draft(), "edited": {},
            "attachments": [], "ready": False, "ready_why": "", "suggest": {}, "pending": False, "project": None}
    with updating_json(_file(factory, sid), {}) as stored:
        stored.update(conv)
    _log(factory, "shape_started", {"shape": sid, "person": person, "persona": persona})
    return conv


def _open(factory: Factory, conv: dict[str, Any]) -> None:
    if conv.get("state") != "open":
        raise ShapeRefused(f"{conv.get('id')} already became project {conv.get('project')}: open the project")
    if conv.get("pending") and not _stale(factory, conv):
        raise ShapeRefused("Rihma is still answering the last message; wait for the answer first")


def say(factory: Factory, sid: str, text: str, *, person: str, persona: str, pending: bool = True) -> dict[str, Any]:
    """The person's message, kept; Rihma's answer comes with ``answer`` (pending until then, unless ``pending``
    is False: another step follows before Rihma answers)."""
    _signed(person, persona)
    text = text.strip()
    if not text:
        raise ShapeRefused("say something first")
    if len(text) > MAX_MESSAGE:
        raise ShapeRefused(f"a message is at most {MAX_MESSAGE} characters; attach longer material as a file")
    with updating_json(_file(factory, sid), {}) as conv:
        if not conv:
            raise KeyError(f"no conversation {sid}")
        _open(factory, conv)
        conv["messages"].append(_message(factory, "person", text, person=person, persona=persona))
        conv.update(pending=pending, pending_since=factory.clock.stamp())
    _log(factory, "shape_said", {"shape": sid, "person": person, "persona": persona, "chars": len(text),
                                 "sha256": _digest(text)})
    return conv


def edit_draft(factory: Factory, sid: str, changes: dict[str, Any], *, person: str, persona: str) -> dict[str, Any]:
    """The person's own words in the draft. A field they edited is theirs: Rihma's drafts leave it be."""
    _signed(person, persona)
    unknown = sorted(set(changes) - set(KEYS))
    if unknown or not changes:
        raise ShapeRefused(f"the draft's fields are {', '.join(KEYS)}"
                           + (f", not {', '.join(unknown)}" if unknown else ""))
    with updating_json(_file(factory, sid), {}) as conv:
        if not conv:
            raise KeyError(f"no conversation {sid}")
        if conv.get("state") != "open":
            raise ShapeRefused(f"{sid} already became project {conv.get('project')}")
        changed = [k for k in changes if _clean(k, changes[k]) != conv["draft"].get(k)]
        for k in changed:
            conv["draft"][k] = _clean(k, changes[k])
            conv["edited"][k] = {"by": person, "at": factory.clock.stamp()}
    _log(factory, "shape_draft_edited", {"shape": sid, "person": person, "persona": persona, "fields": changed})
    return conv


# -- attached material ----------------------------------------------------------------------------------

def read_material(name: str, data: bytes) -> str:
    """The text of one attached file, read by the folder scanner's rules (kernel/material_read.py): text,
    Markdown, Word, PowerPoint, Excel, OpenDocument, HTML, CSV, JSON, YAML and PDF with a text layer. A file
    it cannot read (a scanned PDF, an image, another binary) is refused with why, never skipped in silence."""
    from kernel.material_read import READABLE, extract

    ext = Path(name).suffix.lower()
    if ext not in READABLE and (b"\x00" in data[:4096] or data.startswith(b"%PDF")):
        raise ShapeRefused(f"{name} is not a document Rihmasto can read: paste its text into the chat")
    got = extract(data, ".pdf" if data.startswith(b"%PDF") else ext)
    if not got.text.strip():
        why = f" ({got.note})" if getattr(got, "note", "") else ""
        raise ShapeRefused(f"{name} could not be read{why}: paste its text into the chat")
    return got.text


def _read_path(path: Path) -> tuple[str, str, list[str]]:
    """(kind, text, the files read) for a file or a folder on this machine: a folder through the scanner,
    as intake reads one (kernel/material.py), so it is read, summarised or skipped by the same rules."""
    from kernel.intake import load_material

    if path.is_file():
        return "file", read_material(path.name, path.read_bytes()), [path.name]
    if not path.is_dir():
        raise ShapeRefused(f"{path} is neither a file nor a folder on this machine")
    _, text, documents, _ = load_material(str(path))
    if not text.strip():
        raise ShapeRefused(f"{path} holds nothing Rihmasto can read")
    return "folder", text, [name for name, _ in (documents or [])]


def attach(factory: Factory, sid: str, *, person: str, persona: str, path: str | None = None, name: str | None = None,
           text: str | None = None, data_base64: str | None = None, pending: bool = True) -> dict[str, Any]:
    """Attach a file or a folder on this machine (``path``), or a file's contents sent by the cockpit (``name``
    with ``text`` or ``data_base64``). Its text is kept with the conversation and Rihma reads it next."""
    _signed(person, persona)
    if path:
        kind, body, files = _read_path(Path(path).expanduser())
        name = Path(path).name or str(path)
    elif name and (text is not None or data_base64):
        raw = text.encode("utf-8") if text is not None else base64.b64decode(data_base64 or "", validate=True)
        kind, body, files = "file", read_material(name, raw), [name]
    else:
        raise ShapeRefused("attach a file or a folder: a path on this machine, or a file's contents")
    body = body.strip()
    if not body:
        raise ShapeRefused(f"{name} holds no text")
    cut = len(body) > MAX_ATTACH
    with updating_json(_file(factory, sid), {}) as conv:
        if not conv:
            raise KeyError(f"no conversation {sid}")
        _open(factory, conv)
        n = len(conv["attachments"]) + 1
        stored = f"files/{n:02d}.txt"
        write_text(_file(factory, sid).parent / stored, body[:MAX_ATTACH] + "\n")
        item = {"n": n, "name": str(name)[:200], "kind": kind, "files": files[:40], "chars": len(body), "cut": cut,
                "sha256": _digest(body), "stored": stored}
        conv["attachments"].append(item)
        note = f"Attached {item['name']} ({kind}, {len(body):,} characters" + (", cut for reading)" if cut else ")")
        conv["messages"].append(_message(factory, "person", note, person=person, persona=persona, attachment=n))
        conv.update(pending=pending, pending_since=factory.clock.stamp())
    _log(factory, "shape_attached", {"shape": sid, "person": person, "persona": persona, "name": item["name"],
                                     "kind": kind, "chars": len(body), "sha256": item["sha256"]})
    return conv


def _material(factory: Factory, conv: dict[str, Any]) -> str:
    left, parts = PROMPT_ATTACH, []
    for a in conv.get("attachments") or []:
        if left <= 0:
            parts.append(f"(Attachment {a['name']} is not shown: the material is longer than a prompt holds.)")
            continue
        text = (_file(factory, conv["id"]).parent / a["stored"]).read_text(encoding="utf-8")
        parts.append(f"### {a['name']}\n{text[:left]}")
        left -= len(text)
    return "\n\n".join(parts)


# -- Rihma's turn -------------------------------------------------------------------------------------------

PROMPT_HEAD = """You are Rihma, the analyst of a software factory. You help a person work out what they need,
in conversation, before a project starts. The factory builds it later from the brief you shape together.

How you talk:
- Plain language, in the person's own language, and short. Restate what you understood in one sentence
  when it helps, then ask at most two questions: the ones whose answers change most what gets built.
- Never put words in the person's mouth. The draft holds only what the person said or clearly agreed to;
  what you only suppose is an open question, never a fact.
- A field the person edited themselves is theirs: return it as it is. If you would change it, say so in
  your reply and let them edit it.
- Say plainly when the draft is good enough to create the project: it says who it is for, the problem,
  the outcomes and what is in scope for a first version.

Answer with this JSON in a ```json block, and nothing after it:
{"reply": "your words to the person",
 "draft": {"title": "...", "for_whom": "...", "problem": "...", "outcomes": ["..."], "scope_in": ["..."],
           "scope_out": ["..."], "constraints": ["..."], "data_systems": ["..."], "open_questions": ["..."]},
 "ready": false, "ready_why": "what is still missing, or why it is enough",
 "suggest": {"profile": "%s", "mode": "%s", "maturity": "%s", "why": "..."}}
"""


def prompt(factory: Factory, conv: dict[str, Any]) -> str:
    """Rihma's prompt: the rules first, word for word every turn, then this conversation."""
    from kernel.profiles import PROFILES

    head = PROMPT_HEAD % (" | ".join(PROFILES), " | ".join(MODES), " | ".join(MATURITIES))
    turns = "\n".join(f"{'Person' if m['from'] == 'person' else 'Rihma'}: {m['text']}"
                      for m in (conv.get("messages") or [])[-PROMPT_TURNS:])
    material = _material(factory, conv)
    return (head + "\nThe draft so far:\n" + json.dumps(conv.get("draft") or {}, ensure_ascii=False, indent=1)
            + f"\nFields the person edited: {', '.join(conv.get('edited') or {}) or 'none'}\n"
            + (f"\nAttached material, verbatim (it may be cut):\n<<<\n{material}\n>>>\n" if material else "")
            + f"\nThe conversation so far:\n{turns}\n")


def _merge(conv: dict[str, Any], answer: dict[str, Any]) -> None:
    raw, given = answer.get("draft"), answer.get("suggest")
    proposed: dict[str, Any] = raw if isinstance(raw, dict) else {}
    said: dict[str, Any] = given if isinstance(given, dict) else {}
    for key in KEYS:
        if key in proposed and key not in (conv.get("edited") or {}):
            conv["draft"][key] = _clean(key, proposed[key])
    conv["ready"] = answer.get("ready") is True
    conv["ready_why"] = _clean("problem", answer.get("ready_why") or "")
    conv["suggest"] = {k: str(said[k])[:MAX_ITEM] for k in ("profile", "mode", "maturity", "why") if said.get(k)}


def _finish(factory: Factory, sid: str, text: str, answer: dict[str, Any] | None, note: str | None) -> dict[str, Any]:
    with updating_json(_file(factory, sid), {}) as conv:
        if answer is not None:
            _merge(conv, answer)
        conv["messages"].append(_message(factory, "rihma", text, note=note,
                                         link=MODELS_LINK if note in ("no_model", "error") else None))
        conv["pending"] = False
    return conv


def answer(factory: Factory, sid: str, model: Model | None) -> dict[str, Any]:
    """Rihma's turn: the model reads the conversation and answers, with the draft it would keep. With no
    model, or one that fails, the chat says so and points at Models setup; the person's words stay."""
    conv = get(factory, sid)
    if model is None:
        return _finish(factory, sid, NO_MODEL, None, "no_model")
    try:
        raw = model.ask(prompt(factory, conv), role="analyst")
    except ModelError as exc:
        return _finish(factory, sid, f"I could not answer: {str(exc)[:300]}. Check the analyst's model in Models "
                                     "setup, then say it again.", None, "error")
    except Exception as exc:  # a model that breaks in any other way must not leave the chat waiting for ever
        return _finish(factory, sid, f"I could not answer ({type(exc).__name__}). Your words are kept; say it "
                                     "again.", None, "error")
    try:
        parsed = extract_json(raw)
    except ModelError:
        parsed = None
    if not isinstance(parsed, dict) or not str(parsed.get("reply") or "").strip():
        return _finish(factory, sid, " ".join(raw.split())[:MAX_MESSAGE] or "(no answer)", None, None)
    return _finish(factory, sid, str(parsed["reply"]).strip()[:MAX_MESSAGE], parsed, None)


# -- the project ----------------------------------------------------------------------------------------

def choice(conv: dict[str, Any], *, profile: str | None = None, mode: str | None = None,
           maturity: str | None = None) -> dict[str, Any]:
    """The person's choice, with Rihma's suggestion for what they left out."""
    from kernel.profiles import PROFILES

    s = suggestion(conv)
    out = {"profile": profile or s["profile"], "mode": mode or s["mode"], "maturity": maturity or s["maturity"]}
    for key, allowed in (("profile", PROFILES), ("mode", MODES), ("maturity", MATURITIES)):
        if out[key] not in allowed:
            raise ShapeRefused(f"{key} must be one of {', '.join(allowed)}")
    return out


def ready_to_create(conv: dict[str, Any]) -> None:
    if conv.get("state") != "open":
        raise ShapeRefused(f"{conv.get('id')} already became project {conv.get('project')}")
    if not any(conv.get("draft", {}).get(k) for k in KEYS if k != "title"):
        raise ShapeRefused("the draft is empty: tell Rihma what you need first")


def mark_created(factory: Factory, sid: str, project: Project, *, person: str, persona: str,
                 chose: dict[str, Any]) -> dict[str, Any]:
    """The conversation became ``project``: kept with the project as its request, and on record in both ledgers."""
    with updating_json(_file(factory, sid), {}) as conv:
        conv.update(state="created", project=project.pid, created_by=person, created=factory.clock.stamp())
    project.write("shape.json", conv)
    project.log("shaped_in_chat", {"shape": sid, "person": person, "persona": persona,
                                   "messages": len(conv["messages"]), "sha256": _digest(brief(conv))})
    _log(factory, "shape_created", {"shape": sid, "project": project.pid, "person": person, "persona": persona,
                                    **chose})
    return conv


def create(factory: Factory, sid: str, *, person: str, persona: str, model: Model, profile: str | None = None,
           mode: str | None = None, maturity: str | None = None) -> dict[str, Any]:
    """Create the project from the draft and run its intake (the command line; the cockpit runs intake as a job)."""
    from kernel.intake import intake

    _signed(person, persona)
    conv = get(factory, sid)
    ready_to_create(conv)
    chose = choice(conv, profile=profile, mode=mode, maturity=maturity)
    project = factory.new_project(title_of(conv), maturity=chose["maturity"], mode=chose["mode"],
                                  profile=chose["profile"])
    mark_created(factory, sid, project, person=person, persona=persona, chose=chose)
    out = intake(project, brief(conv), model=model, requested_by=person, literal=True)
    return {"project": project.pid, "shape": sid, **chose, **{k: v for k, v in out.items() if k != "readings"}}
