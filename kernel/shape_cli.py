"""`rihmasto shape` and `rihmasto models`, part of the command line (kernel/cli.py).

    rihmasto shape --person Aino --persona business_owner [--attach PATH] [--resume SH-001]
                                                  talk it through with Rihma, interactively
    rihmasto shape start [--title T] [--text "..."] [--attach PATH] --person ... --persona ...
    rihmasto shape say SH-001 "text" --person ... --persona ...
    rihmasto shape attach SH-001 PATH --person ... --persona ...
    rihmasto shape edit SH-001 FIELD "text" --person ... --persona ...      (a list field: items split by ";")
    rihmasto shape show [SH-001] [--brief]
    rihmasto shape create SH-001 [--profile P] [--mode M] [--maturity M] --person ... --persona ...

    rihmasto models list [--no-probe] | models presets | models test <role>
    rihmasto models set <role> --base-url URL --model NAME [--family F] [--key-env NAME | --key-stdin]
                        [--no-fallback] --person ... --persona ...
    rihmasto models remove <role> --person ... --persona ...

A key given with --key-stdin is read from standard input, stored outside the repository and never printed.
"""

from __future__ import annotations

import argparse
import functools
import sys
from collections.abc import Callable
from typing import Any

from kernel import models_setup, shape
from kernel.people import PERSONAS
from kernel.store import MATURITIES, MODES, Factory

Args = argparse.Namespace
Show = Callable[[Any], None]
HELP = ("Type to talk with Rihma. /attach PATH adds a file or folder, /draft shows the draft, "
        "/edit FIELD TEXT changes a field, /create makes the project, /quit leaves (resume with --resume).")


def _signer(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """--person and --persona, both needed: who signs the step."""
    for flag, extra in (("--person", {"help": "the named person who signs it"}), ("--persona", {"choices": PERSONAS})):
        p.add_argument(flag, required=True, **extra)
    return p


def _choices(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", help="the work profile (default: Rihma's suggestion)")
    p.add_argument("--mode", choices=MODES)
    p.add_argument("--maturity", choices=MATURITIES)


def add_parsers(sub: Any) -> None:
    """Add `shape` and `models` to `rihmasto`'s subcommands."""
    top = sub.add_parser("shape", help="work out a need with Rihma in a chat (docs/guides/shape-in-chat.md)")
    top.add_argument("--person", help="the named person who signs it (the chat needs it)")
    top.add_argument("--persona", choices=PERSONAS)
    top.add_argument("--attach", help="a file or folder to start from")
    top.add_argument("--resume", metavar="SH-ID", help="go on with a conversation")
    _choices(top)
    sh = top.add_subparsers(dest="sub", required=False)
    s = _signer(sh.add_parser("start", help="open a conversation"))
    s.add_argument("--title", default="")
    s.add_argument("--text", default="", help="the first message")
    s.add_argument("--attach", help="a file or folder to start from")
    _signer(sh.add_parser("say", help="say something; Rihma answers")).add_argument("id")
    sh.choices["say"].add_argument("text")
    a = _signer(sh.add_parser("attach", help="attach a file or a folder; Rihma reads it"))
    a.add_argument("id")
    a.add_argument("path")
    e = _signer(sh.add_parser("edit", help="change a field of the draft in your own words"))
    for name in ("id", "field", "text"):
        e.add_argument(name)
    w = sh.add_parser("show", help="a conversation and its draft, or every conversation")
    w.add_argument("id", nargs="?")
    w.add_argument("--brief", action="store_true", help="the draft as the project's request, in Markdown")
    c = _signer(sh.add_parser("create", help="create the project from the draft and run its intake"))
    c.add_argument("id")
    _choices(c)
    md = sub.add_parser("models", help="which model answers for each role (docs/guides/models-setup.md)"
                        ).add_subparsers(dest="sub", required=True)
    md.add_parser("list", help="each role's model, endpoint and readiness").add_argument(
        "--no-probe", action="store_true", help="do not check whether local servers answer")
    md.add_parser("presets", help="the common choices")
    md.add_parser("test", help="send a role's endpoint a tiny prompt").add_argument("role")
    m = _signer(md.add_parser("set", help="point a role at an OpenAI-compatible endpoint"))
    m.add_argument("role")
    m.add_argument("--base-url", required=True, help="for example http://127.0.0.1:8080/v1")
    m.add_argument("--model", required=True)
    m.add_argument("--family", help="the model family (default: from the model's name)")
    key = m.add_mutually_exclusive_group()
    key.add_argument("--key-env", help="the NAME of the environment variable that holds the key")
    key.add_argument("--key-stdin", action="store_true", help="read the key from standard input and store it")
    m.add_argument("--no-fallback", action="store_true", help="drop the role's fallback")
    m.add_argument("--private", action="store_true",
                   help="the host is on your own network (a tailnet, a VPN): confidential projects may use it")
    _signer(md.add_parser("remove", help="take a role back to the shipped routing")).add_argument("role")


# -- shape ---------------------------------------------------------------------------------------------

def _changes(conv: dict[str, Any], field: str, text: str) -> dict[str, Any]:
    listed = {k: lst for k, _, lst, _ in shape.FIELDS}
    if field not in listed:
        raise shape.ShapeRefused(f"the draft's fields are {', '.join(listed)}")
    return {field: [x.strip() for x in text.split(";") if x.strip()] if listed[field] else text}


def _turn(f: Factory, conv: dict[str, Any], model: Callable[[], Any]) -> dict[str, Any]:
    return shape.answer(f, conv["id"], model())


def _start(f: Factory, a: Args, model: Callable[[], Any]) -> dict[str, Any]:
    conv = shape.start(f, person=a.person, persona=a.persona, title=a.title)
    if a.attach:
        conv = shape.attach(f, conv["id"], path=a.attach, person=a.person, persona=a.persona)
    if a.text:
        if conv.get("pending"):
            conv = _turn(f, conv, model)
        conv = shape.say(f, conv["id"], a.text, person=a.person, persona=a.persona)
    return shape.view(_turn(f, conv, model) if conv.get("pending") else conv)


def _show(f: Factory, a: Args) -> Any:
    if not a.id:
        return {"conversations": shape.conversations(f)}
    conv = shape.view(shape.get(f, a.id))
    return conv["brief"] if a.brief else conv


def _draft_text(conv: dict[str, Any]) -> str:
    v = shape.view(conv)
    lines = [f"{label}: {'; '.join(v['draft'][k]) if lst else v['draft'][k] or '-'}"
             for k, label, lst, _ in shape.FIELDS]
    gaps = v["missing"]
    return "\n".join(lines + [f"Still needed: {', '.join(gaps)}" if gaps else "Good enough to create the project."])


def _last(conv: dict[str, Any]) -> str:
    m = conv["messages"][-1]
    note = "  (Set up a model: rihmasto models list)" if m.get("link") else ""
    return f"Rihma: {m['text']}{note}"


def _command(f: Factory, a: Args, conv: dict[str, Any], line: str, model: Callable[[], Any],
             out: Callable[[str], Any]) -> dict[str, Any] | None:
    """One /command of the interactive chat; None ends it."""
    word, _, rest = line.partition(" ")
    if word == "/quit":
        out(f"Kept as {conv['id']}: rihmasto shape --resume {conv['id']} goes on with it.")
        return None
    if word == "/draft":
        out(_draft_text(conv))
    elif word == "/attach":
        conv = _turn(f, shape.attach(f, conv["id"], path=rest.strip(), person=a.person, persona=a.persona), model)
        out(_last(conv))
    elif word == "/edit":
        field, _, text = rest.strip().partition(" ")
        conv = shape.edit_draft(f, conv["id"], _changes(conv, field, text), person=a.person, persona=a.persona)
        out(_draft_text(conv))
    elif word == "/create":
        made = shape.create(f, conv["id"], person=a.person, persona=a.persona, model=model(), profile=a.profile,
                            mode=a.mode, maturity=a.maturity)
        out(f"Project {made['project']} is created ({made['profile']}, {made['mode']}, {made['maturity']}): "
            f"rihmasto status {made['project']} shows its intake.")
        return None
    else:
        out(HELP)
    return conv


def _chat(f: Factory, a: Args, model: Callable[[], Any], out: Callable[[str], Any],
          read: Callable[[str], str]) -> None:
    if not a.person or not a.persona:
        raise ValueError("the chat is signed: give --person and --persona")
    conv = shape.get(f, a.resume) if a.resume else shape.start(f, person=a.person, persona=a.persona)
    out(f"{conv['id']}. {HELP}")
    out(_last(conv))
    if a.attach:
        conv = _turn(f, shape.attach(f, conv["id"], path=a.attach, person=a.person, persona=a.persona), model)
        out(_last(conv))
    while True:
        try:
            line = read("You: ").strip()
        except EOFError:
            line = "/quit"
        if not line:
            continue
        try:
            nxt = _command(f, a, conv, line, model, out) if line.startswith("/") else \
                _turn(f, shape.say(f, conv["id"], line, person=a.person, persona=a.persona), model)
        except (shape.ShapeRefused, KeyError) as exc:
            out(f"(not done: {exc})")
            continue
        if nxt is None:
            return
        if not line.startswith("/"):
            out(_last(nxt))
        conv = nxt


def commands(model: Callable[[], Any]) -> dict[str, Callable[[Factory, Args], Any]]:
    return {
        "shape start": lambda f, a: _start(f, a, model),
        "shape say": lambda f, a: shape.view(_turn(f, shape.say(f, a.id, a.text, person=a.person, persona=a.persona),
                                                   model)),
        "shape attach": lambda f, a: shape.view(_turn(f, shape.attach(f, a.id, path=a.path, person=a.person,
                                                                      persona=a.persona), model)),
        "shape edit": lambda f, a: shape.view(shape.edit_draft(f, a.id, _changes(shape.get(f, a.id), a.field, a.text),
                                                               person=a.person, persona=a.persona)),
        "shape show": _show,
        "shape create": lambda f, a: shape.create(f, a.id, person=a.person, persona=a.persona, model=model(),
                                                  profile=a.profile, mode=a.mode, maturity=a.maturity),
        "models list": lambda f, a: models_setup.models_view(probe=not a.no_probe),
        "models presets": lambda f, a: {"presets": models_setup.PRESETS},
        "models test": lambda f, a: models_setup.probe_role(a.role),
        "models set": lambda f, a: models_setup.set_role(
            f, a.role, base_url=a.base_url, model=a.model, family=a.family, key_env=a.key_env,
            key=sys.stdin.readline().strip() if a.key_stdin else None, keep_fallback=not a.no_fallback,
            private=a.private,
            person=a.person, persona=a.persona),
        "models remove": lambda f, a: models_setup.remove_role(f, a.role, person=a.person, persona=a.persona),
    }


def _shown(show: Show, command: Callable[[Factory, Args], Any], f: Factory, a: Args) -> None:
    show(command(f, a))


def _typed(prompt: str) -> str:
    return input(prompt)


def handlers(show: Show, model: Callable[[], Any], say: Callable[[str], Any],
             read: Callable[[str], str] | None = None) -> dict[str, Callable[[Factory, Args], None]]:
    """The commands as `rihmasto` runs them. ``show`` prints JSON, ``say`` prints a line, ``read`` reads one
    (the interactive chat; standard input by default), ``model`` makes the analyst's model when Rihma answers."""
    out: dict[str, Callable[[Factory, Args], None]] = {
        name: functools.partial(_shown, show, command) for name, command in commands(model).items()}
    out["shape"] = lambda f, a: _chat(f, a, model, say, read or _typed)
    return out
