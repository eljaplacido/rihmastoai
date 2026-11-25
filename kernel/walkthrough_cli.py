"""`rihmasto walkthrough`, part of the command line (kernel/cli.py): the walkthroughs of Ask Rihma
(kernel/walkthrough.py, FR-WLK1) in a terminal.

    rihmasto walkthrough plug_in|documents|new_idea|model|tour --person Aino --persona developer [--resume WT-001]
    rihmasto walkthrough list

Rihma asks; type the number of an option, or your answer. A proposal waits for "yes" (or the number of its
Confirm), which carries it out through the command line's own commands (`rihmasto adopt`, `rihmasto new`,
`rihmasto models set`, `rihmasto settings`, `rihmasto shape`), signed with your name; an adoption or an intake
runs while you wait, with its progress on the terminal. "back" goes back a step, "/map" shows a scanned
folder's full map, "/cancel" ends the walkthrough and "/quit" leaves it to resume later.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

from kernel import walkthrough as wk
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace
Show = Callable[[str], None]
NAMES = ("plug_in", "documents", "new_idea", "model", "tour")


def add_parsers(sub: Any) -> None:
    """Add `walkthrough` to `rihmasto`'s subcommands."""
    p = sub.add_parser("walkthrough", help="Rihma walks you through it, step by step (docs/guides/walkthroughs.md)")
    p.add_argument("name", choices=(*NAMES, "list"), help="which walkthrough, or list: the walkthroughs and yours")
    p.add_argument("--person", help="the named person who signs each step (needed to walk through one)")
    p.add_argument("--persona", choices=PERSONAS, help="the persona you act as")
    p.add_argument("--resume", metavar="WT-ID", help="go on with a walkthrough you left")


def _ns(**kw: Any) -> Args:
    return argparse.Namespace(**kw)


def runner(factory: Factory, person: str, persona: str, model: Callable[[], Any]) -> wk.Runner:
    """A proposal carried out through the command line's own commands, signed by the person."""
    from kernel import material_cli, models_setup, project_settings, shape

    def run(prop: dict[str, Any]) -> dict[str, Any]:
        a, out = prop["args"], {}
        posture = a.get("posture")
        if prop["action"] == "adopt":
            material_cli._adopt(factory, _ns(
                title=a["title"], source=a["source"], intent=a["intent"], person=person, persona=persona,
                base_url=None, maturity=None, mode=None, posture=posture, weights=None, profile="auto",
                exclude=list(a.get("exclude") or []), confidential=bool(a.get("confidential"))), out.update)
            return {"job": {"id": None, "state": "done", "made": out["project"]}}
        if prop["action"] == "new_project":
            code = material_cli._new(factory, _ns(
                title=a["title"], source=a["source"], source_file=None, exclude=list(a.get("exclude") or []),
                yes=True, confidential=bool(a.get("confidential")), persona=persona, requested_by=person,
                maturity=a.get("maturity") or (None if posture else "demo"), mode=None if posture else "mixed",
                posture=posture, weights=None, profile="auto"), out.update, model)
            if code:
                raise wk.WalkRefused("the project was not created (the reason is above)")
            return {"project": {"id": out["project"]}, "job": {"id": None, "state": "done"}}
        if prop["action"] == "set_model":
            return {"role": models_setup.set_role(factory, a["role"], base_url=a["base_url"], model=a["model"],
                                                  person=person, persona=persona, key_env=a.get("key_env"),
                                                  private=bool(a.get("private")))}
        if prop["action"] == "set_kind":
            return project_settings.change(factory.project(a["project"]), person=person, persona=persona,
                                           reason="chosen in the walkthrough", kind=a["kind"])
        if prop["action"] == "shape":
            conv = shape.start(factory, person=person, persona=persona)
            shape.say(factory, conv["id"], a["text"], person=person, persona=persona)
            return {"shape": {"id": conv["id"]}}
        raise wk.WalkRefused(f"no such proposal: {prop['action']}")

    return run


def render(msg: dict[str, Any]) -> str:
    """One of Rihma's messages as a terminal shows it: the words, the options numbered, a proposal's lines."""
    out = [f"Rihma: {msg['text']}"]
    s = msg.get("scan")
    if s and s.get("languages"):
        out.append("  (the full map: /map)")
    for i, o in enumerate(msg.get("options") or [], 1):
        out.append(f"  {i}. {o['label']}" + (f": {o['hint']}" if o.get("hint") else ""))
    prop = msg.get("proposal")
    if prop:
        out += [f"  - {x}" for x in prop.get("lines") or []]
        out.append(f"  Type yes to {prop['label']}, or back.")
    for link in msg.get("links") or []:
        if link.get("route"):
            out.append(f"  {link['label']}: {link['route']}")
    return "\n".join(out)


def _show_map(w: dict[str, Any], show: Show) -> None:
    from kernel import confidential, material, material_cli

    folder = ((w.get("data") or {}).get("scan") or {}).get("folder")
    if not folder:
        show("No folder has been scanned in this walkthrough.")
        return
    show(material_cli.render(material.preview(folder, (w.get("data") or {}).get("exclude") or []),
                             confidential.send_to("analyst")))


def _turn(factory: Factory, w: dict[str, Any], said: str, run: wk.Runner, person: str,
          persona: str) -> dict[str, Any] | None:
    """One line typed at the prompt, carried out; None when the person leaves."""
    word = said.strip()
    if word in ("/quit", "/exit"):
        return None
    if word == "/cancel":
        return wk.cancel(factory, w["id"], person=person, persona=persona)
    options = wk.offered(w)
    if wk.proposal(w) is not None and word.lower() in ("yes", "y", "kyllä", "confirm"):
        return wk.confirm(factory, w["id"], person=person, persona=persona, run=run)
    if word.lower() in ("back", "takaisin") and any(o["id"] == "back" for o in options):
        return wk.reply(factory, w["id"], person=person, persona=persona, choice="back")
    if word.isdigit() and 1 <= int(word) <= len(options):
        return wk.reply(factory, w["id"], person=person, persona=persona, choice=options[int(word) - 1]["id"])
    return wk.reply(factory, w["id"], person=person, persona=persona, text=word)


def interactive(factory: Factory, args: Args, model: Callable[[], Any], show: Show = print,
                ask: Callable[[str], str] | None = None) -> int:
    ask = ask or (lambda prompt: input(prompt))
    person, persona = args.person, args.persona
    if not person or not persona:
        sys.stderr.write("rihmasto walkthrough: --person and --persona sign each step\n")
        return 2
    run = runner(factory, person, persona, model)
    w: dict[str, Any] | None = wk.get(factory, args.resume) if args.resume else \
        wk.start(factory, args.name, person=person, persona=persona, replace=True)
    seen = 0
    while w is not None:
        seen = _show_new(w, seen, show)
        if w.get("state") != "active":
            w, seen = _after_end(factory, w, show)
            continue
        said = _read(ask)
        if said.strip() == "/map":
            _show_map(w, show)
            continue
        try:
            nxt = _turn(factory, w, said, run, person, persona)
        except (wk.WalkRefused, ValueError, PermissionError) as exc:
            show(f"({exc})")
            continue
        if nxt is None:
            show(f"Left {w['id']}: resume it with --resume {w['id']}.")
            return 0
        seen = seen if nxt.get("id") == w["id"] else 0
        w = nxt
    return 0


def _show_new(w: dict[str, Any], seen: int, show: Show) -> int:
    """Rihma's messages the terminal has not shown yet; how many messages are shown now."""
    for msg in (w.get("messages") or [])[seen:]:
        if msg.get("from") == "rihma":
            show(render(msg))
    return len(w.get("messages") or [])


def _after_end(factory: Factory, w: dict[str, Any], show: Show) -> tuple[dict[str, Any] | None, int]:
    """A detour that ended goes back where the walkthrough it came from was; anything else ends here."""
    if w.get("resumed"):
        back = wk.get(factory, w["resumed"])
        return back, max(0, len(back.get("messages") or []) - 2)
    show(f"({w['id']} is {w.get('state')}.)")
    return None, 0


def _read(ask: Callable[[str], str]) -> str:
    try:
        return ask("> ")
    except EOFError:
        return "/quit"


def _list(factory: Factory, args: Args, emit: Callable[[Any], None]) -> int:
    going = wk.mine(factory, args.person) if args.person else None
    emit({"walkthroughs": wk.catalogue(), "yours": going and {k: going[k] for k in ("id", "name", "step")}})
    return 0


def handlers(emit: Callable[[Any], None], model: Callable[[], Any], show: Show = print
             ) -> dict[str, Callable[[Factory, Args], int | None]]:
    def walk(f: Factory, a: Args) -> int | None:
        return _list(f, a, emit) if a.name == "list" else interactive(f, a, model, show)

    return {"walkthrough": walk}
