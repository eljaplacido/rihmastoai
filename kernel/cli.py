"""`rihmasto`: the operator's command line (FR-N2). `rihma` is the same command under its earlier
name (D-0013). Without installing it, run `python -m kernel.cli`.

The chain, from a need to a running product
    rihmasto new "Title" --source "idea text or a path" --mode mixed --maturity demo --requested-by Aino
    rihmasto intake <pid> --source-file request.md --requested-by Aino
    rihmasto run <pid>                  advance until a person is needed
    rihmasto tick                       carry out decided concepts (a validated one becomes a project); runs none
    rihmasto status [<pid>]
    rihmasto answer <pid> <Q-id> "text" --person Aino --persona business_owner
    rihmasto assume <pid> <Q-id> --person Aino --persona business_owner
    rihmasto decide <pid> <C-id> <verdict> --person Ilkka --persona it [--reason ...]
    rihmasto change <pid> "text" --person Tester --persona end_user
    rihmasto apply <pid> <C-id>         carry a triaged (and, if needed, accepted) change back
    rihmasto deliver <pid> [--new]      deliver on the paved road for the project's maturity (build and deliver
                                        ask the autonomy cap first)
    rihmasto operate <pid>              one operations round: probes, incidents
    rihmasto learn                      lessons across projects, proposals, model reliability
    rihmasto lanes                      prepare the analyst lane and show the pool
    rihmasto doctor                     Python, Gnomon (0.6.5 or later; 0.6.6 recommended), git, docker, the
                                        lanes root, endpoint keys (set or not); exit 1 when Gnomon is missing
                                        or too old
    rihmasto demo [--home DIR]          a demo factory home with no model keys, no network and no Gnomon
                                        (default: var/demo); then open the cockpit on it

An existing solution, or your own terminal (docs/brownfield.md)
    rihmasto adopt "Title" --source <path|url> --intent monitor|maintain|improve --person Aino --persona developer
    rihmasto sync <pid>                 fetch upstream, record drift (and probe it when it is monitored)
    rihmasto workspace open <pid> --person Aino --persona developer --agent gnomon|claude|opencode|shell
    rihmasto workspace submit <pid> <path> --person Aino --persona developer [--task T-001]
    rihmasto workspace list <pid>

The capability layer (a write is signed with --person and --persona)
    rihmasto security ingest <pid> <file.sarif> | security status <pid>
    rihmasto security accept <pid> <finding> --reason "..." --expires YYYY-MM-DD
    rihmasto pack <pid> [--yaml] | pack withdraw <pid> "why" | pack pin <pid> (once IT pushed it)  [--release N]
    rihmasto evidence <pid> --out DIR             an evidence pack (a zip) for a reviewer
    rihmasto embed create --kind feedback|need --origin URL [--origin URL] [--project PID] [--label ...]
                          [--brief ...] [--endpoint URL]   its key is printed once, never again
    rihmasto embed list | embed revoke <E-id>
    rihmasto autonomy show [<pid>] | autonomy set <1-4> [--project PID] --reason "..."
    rihmasto signal log --text "..." --channel chat --source "..." | signal list | signal triage <S-id>
    rihmasto concept edit <C-id> [--title ...] [--profile ...] [--maturity ...] [--mode ...] | concept apply
    rihmasto observe <trigger> --facts '{"project": "<pid>"}' --source "..." | updates apply <pid>
    rihmasto square | catalogue                   the delivery square; the capability catalogue

The factory home is --home, else $RIHMASTO_HOME, $RIHMA_HOME or $GNOMONFACTORY_HOME, else var/.
A refused capability or signed command prints why on stderr and exits 2 (access: docs/guides/access.md).
Models are reached only through Gnomon, in the lanes (`kernel/routing.json`).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters import sarif
from kernel import access, autonomy, embeds, evidence_pack, graph_ask, integrations, observations, packs
from kernel import autopilot_cli, input_summary, modules, outputs, security, signals, standalone
from kernel.canon import Canon, DecisionRefused
from kernel.dashboard import catalogue
from kernel.people import PERSONAS, is_person
from kernel.profiles import PROFILES
from kernel.store import HOME_ENVS, MATURITIES, MODES, STAGES, Factory

PROG = "rihmasto"  # the command's name (D-0013); `rihma` is installed as an alias of the same main
Args = argparse.Namespace
Handler = Callable[[Factory, Args], int | None]
# What the kernel raises to refuse a capability command: not a person, a persona that may not, a bad
# value (DecisionRefused and SarifError are ValueErrors), an unknown id, or a missing file.
REFUSED = (ValueError, LookupError, FileNotFoundError)


def _kernel(name: str) -> Any:
    """A kernel module, imported only when a command of the chain needs it."""
    return importlib.import_module(f"kernel.{name}")


def _model() -> Any:
    from kernel.lanes import ensure_analyst_lane, load_routing
    from kernel.model import GnomonModel

    return GnomonModel(ensure_analyst_lane(load_routing()), timeout=1200)


def _source(args: Args) -> dict[str, Any]:
    """The request as intake takes it: a request file's contents are its text, never a path to read."""
    if getattr(args, "source_file", None):
        return {"source": Path(args.source_file).read_text(encoding="utf-8"), "literal": True}
    return {"source": str(args.source)}


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def status(factory: Factory, pid: str | None) -> dict:
    projects = [factory.project(pid)] if pid else factory.projects()
    out = []
    for p in projects:
        meta, canon = p.meta, Canon(p)
        tasks = p.read("tasks.json", {}) or {}
        out.append({"id": p.pid, "title": meta["title"], "maturity": meta["maturity"], "mode": meta["mode"],
            "stage": f"{meta['stage']} {STAGES[meta['stage']]}",
            "open_cards": [{"id": c["id"], "kind": c["kind"], "title": c["title"][:80]} for c in canon.cards()],
            "questions": {s: len(canon.questions(s)) for s in ("open", "answered", "assumed")},
            "overdue_assumptions": [a["id"] for a in canon.overdue()],
            "tasks": {t: s.get("status") for t, s in tasks.items()}, "ledger_intact": p.ledger().verify().intact,
        })
    print(f"{PROG} status: access: {access.describe(access.load(factory))}", file=sys.stderr)   # stdout stays JSON
    return {"projects": out}


# -- the parser ------------------------------------------------------------------------------------

def _add(sub: Any, name: str, *positionals: str, about: str | None = None) -> argparse.ArgumentParser:
    """A command with its positional arguments (and a line in its group's help when ``about`` is given)."""
    p: argparse.ArgumentParser = sub.add_parser(name, **({"help": about} if about else {}))
    for pos in positionals:
        p.add_argument(pos)
    return p


def _signed(p: argparse.ArgumentParser, *, required: bool = True, check: bool = False) -> argparse.ArgumentParser:
    """--person and --persona: who signs the write. ``check`` has the parser check the persona."""
    p.add_argument("--person", required=required)
    p.add_argument("--persona", required=required, choices=PERSONAS if check else None)
    return p


def _group(sub: Any, name: str, about: str) -> Any:
    """A command with commands of its own (`rihmasto security ingest`); the one chosen is ``args.sub``."""
    return sub.add_parser(name, help=about).add_subparsers(dest="sub", required=True)


def _sources(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--source")
    src.add_argument("--source-file")
    p.add_argument("--requested-by", required=True)
    p.add_argument("--persona", choices=PERSONAS, help="with access enforced: the persona you ask as (business_owner)")
    return p


def _chain_parsers(sub: Any) -> None:
    s = _sources(_add(sub, "new", "title"))
    s.add_argument("--mode", choices=MODES, default="mixed")
    s.add_argument("--maturity", choices=MATURITIES, default="demo")
    s.add_argument("--profile", default="auto",
                   help="the kind of work: auto (proposed from the request by rule), or one of the work profiles")
    _sources(_add(sub, "intake", "pid"))
    for name in ("run", "spec", "compile", "build", "operate"):
        _add(sub, name, "pid")
    _add(sub, "status").add_argument("pid", nargs="?")
    _signed(_add(sub, "answer", "pid", "qid", "text"))
    _signed(_add(sub, "assume", "pid", "qid"))
    _signed(_add(sub, "decide", "pid", "card", "verdict")).add_argument("--reason", default="")
    _signed(_add(sub, "change", "pid", "text")).add_argument("--hint")
    _add(sub, "apply", "pid", "card")
    _add(sub, "deliver", "pid").add_argument(
        "--new", action="store_true", help="start a new release even if this revision was delivered")
    _add(sub, "learn")
    _add(sub, "tick", about="carry out decided concept cards: a validated concept becomes a project")
    _add(sub, "resurface", "pid").add_argument("--reason", default="routing changed")
    _add(sub, "lanes")
    _add(sub, "doctor")
    _add(sub, "demo", about="build a demo factory home: no model keys, no network, no Gnomon").add_argument(
        "--home", dest="demo_home", help="where to build it (default: var/demo in this checkout). An earlier demo "
                                         "home there is replaced; any other folder that is not empty is refused")


def _brownfield_parsers(sub: Any) -> None:
    s = _signed(_add(sub, "adopt", "title"))
    s.add_argument("--source", required=True, help="a local git repository, or a URL git clones without credentials")
    s.add_argument("--intent", required=True, choices=("monitor", "maintain", "improve"))
    s.add_argument("--base-url", help="where the solution runs today, for probes")
    s.add_argument("--profile", default="auto", help="auto (proposed from the README by rule), or a work profile")
    s.add_argument("--maturity", choices=MATURITIES, default="production")
    _add(sub, "sync", "pid")
    ws = _group(sub, "workspace", "a branch of your own, for your own terminal and agent")
    _signed(_add(ws, "open", "pid")).add_argument(
        "--agent", required=True, choices=("gnomon", "claude", "opencode", "shell"))
    _signed(_add(ws, "submit", "pid", "path")).add_argument(
        "--task", help="the contract task the change serves: its criteria are traced and fail first")
    _add(ws, "list", "pid")


def _evidence_parsers(sub: Any) -> None:
    sec = _group(sub, "security", "SARIF findings and the risks a person accepts (kernel/security.py)")
    _signed(_add(sec, "ingest", "pid", "file", about="read a SARIF 2.1.0 file"), check=True)
    s = _signed(_add(sec, "accept", "pid", "finding", about="accept an open finding as a risk until a date"))
    s.add_argument("--reason", required=True)
    s.add_argument("--expires", required=True, metavar="YYYY-MM-DD")
    _add(sec, "status", "pid", about="each finding's state, the accepted risks and the gate's verdict")
    s = _add(sub, "pack", "pid", about="a release's capability pack, pinned by hash (kernel/packs.py)")
    s.add_argument("--release", type=int, help="the release number (default: the latest)")
    s.add_argument("--yaml", action="store_true", help="print the readable YAML view; the JSON is the record")
    _signed(s, required=False).add_argument("words", nargs="*", help='`pack withdraw <pid> "why"`, `pack pin <pid>`')
    _signed(_add(sub, "evidence", "pid", about="export an evidence pack, a zip for a reviewer")).add_argument(
        "--out", required=True, metavar="DIR")


def _embed_autonomy_parsers(sub: Any) -> None:
    emb = _group(sub, "embed", "website chats with one capability (kernel/embeds.py)")
    s = _signed(_add(emb, "create", about="create an embed: its key is printed once, never again"))
    s.add_argument("--kind", required=True, choices=embeds.KINDS)
    s.add_argument("--origin", required=True, action="append", help="a website that may use it; repeatable")
    s.add_argument("--project", help="the project a feedback embed files changes on")
    s.add_argument("--label", default="")
    s.add_argument("--brief", default="", help="all the chat knows about the product")
    s.add_argument("--endpoint", help="where the embed server is reachable: also print the snippet")
    _add(emb, "list", about="every embed, never its key")
    _signed(_add(emb, "revoke", "id", about="revoke an embed"))
    aut = _group(sub, "autonomy", "the autonomy ladder's cap (kernel/autonomy.py)")
    _add(aut, "show", about="the cap of the factory, or of one project").add_argument("pid", nargs="?")
    s = _signed(_add(aut, "set", about="set the factory's cap, or lower one project's"))
    s.add_argument("level", type=int, choices=sorted(autonomy.LEVELS))
    s.add_argument("--project", help="lower this project's cap, not the factory's")
    s.add_argument("--reason", required=True)


def _square_parsers(sub: Any) -> None:
    sig = _group(sub, "signal", "needs and remarks arriving in the delivery square (kernel/signals.py)")
    s = _signed(_add(sig, "log", about="record a signal as it arrived"), required=False, check=True)
    s.add_argument("--text", required=True)
    s.add_argument("--channel", required=True, choices=signals.CHANNELS)
    s.add_argument("--source", required=True, help="where it came from: a chat channel, a feed, a meeting")
    s.add_argument("--ref", help="its reference in the system it came from")
    _add(sig, "list", about="the signals, with their state").add_argument("--state", choices=signals.STATES)
    _add(sig, "triage", "id", about="route a signal by rule: a change on its project, or a concept").add_argument(
        "--with-model", action="store_true", help="let the analyst's model summarise the need; the rule still routes")
    con = _group(sub, "concept", "new needs waiting for a business owner (kernel/signals.py)")
    s = _signed(_add(con, "edit", "card", about="set a concept's title, profile, maturity or mode"))
    s.add_argument("--title")
    s.add_argument("--profile", choices=list(PROFILES))
    s.add_argument("--maturity", choices=MATURITIES)
    s.add_argument("--mode", choices=MODES)
    _add(con, "apply", about="carry out each decided concept once: a validated one becomes a project")
    s = _add(sub, "observe", about="record an outside event; within the cap it opens update cards")
    s.add_argument("trigger", choices=list(observations.TRIGGERS))
    s.add_argument("--facts", default="{}", help='a JSON object, for example {"project": "<pid>"}')
    s.add_argument("--source", required=True)
    _add(_group(sub, "updates", "the updates inbox (kernel/observations.py)"), "apply", "pid",
         about="record each decided update card once")
    _add(sub, "square", about="the delivery square at a glance")
    _add(sub, "catalogue", about="the capability catalogue")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    envs = ", ".join(f"${name}" for name in HOME_ENVS)
    ap.add_argument("--home", help=f"the factory home (default: the first set of {envs}, else ./var)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for add in (_chain_parsers, _brownfield_parsers, _evidence_parsers, _embed_autonomy_parsers, _square_parsers,
                graph_ask.add_parsers, input_summary.add_parsers, autopilot_cli.add_parsers, outputs.add_parsers,
                standalone.add_parsers):
        add(sub)
    return integrations.add_parsers(sub, ap)  # relay, hooks and connector (D-0015)


# -- handlers of more than one step (one-step handlers are in the tables below) ----------------------

def _new(factory: Factory, args: Args) -> None:
    p = factory.new_project(args.title, maturity=args.maturity, mode=args.mode,
                            profile=None if args.profile == "auto" else args.profile)
    out = _kernel("intake").intake(p, **_source(args), model=_model(), requested_by=args.requested_by)
    _print({"project": p.pid, **{k: v for k, v in out.items() if k != "readings"}})


def _intake(factory: Factory, args: Args) -> None:
    out = _kernel("intake").intake(factory.project(args.pid), **_source(args), model=_model(),
                                   requested_by=args.requested_by)
    _print({k: v for k, v in out.items() if k != "readings"})


def _compile(factory: Factory, args: Args) -> None:
    compiler = _kernel("compile")
    p = factory.project(args.pid)
    c = compiler.compile_project(p)
    _print({"revision": c["revision"], "counts": c["counts"], "holdouts": compiler.author_holdouts(p, model=_model())})


def _answer(factory: Factory, args: Args) -> None:
    p = factory.project(args.pid)
    _print(Canon(p).answer(args.qid, args.text, person=args.person, persona=args.persona))
    _kernel("intake").render_brief(p)


def _assume(factory: Factory, args: Args) -> None:
    p = factory.project(args.pid)
    q = Canon(p).question(args.qid)
    _print(Canon(p).assume(args.qid, q["opinions"].get(q["perspective"], "") or "as the panel proposed",
                           chosen_by=args.person, persona=args.persona))
    _kernel("intake").render_brief(p)


def _change(factory: Factory, args: Args) -> None:
    change = _kernel("change")
    p = factory.project(args.pid)
    card = change.submit(p, persona=args.persona, person=args.person, text=args.text, kind_hint=args.hint)
    _print({"card": card["id"], "triage": change.triage(p, card["id"], model=_model())})


def _learn(factory: Factory, args: Args) -> None:
    learn = _kernel("learn")
    _print({"added_default_checks": learn.apply_accepted(factory),
            "proposals_opened": [c["id"] for c in learn.propose(factory)],
            "immune_memory": learn.immune_memory(factory), "model_reliability": learn.model_reliability(factory)})


def _lanes(factory: Factory, args: Args) -> None:
    lanes = _kernel("lanes")
    routing = lanes.load_routing()
    _print({"analyst": str(lanes.ensure_analyst_lane(routing)), "pool": [str(p) for p in lanes.Lanes().paths()],
            "routing": routing["roles"]})


def _doctor(factory: Factory, args: Args) -> int:
    report = _kernel("doctor").doctor(factory.home)
    _print(report)
    return int(report["exit"])


def _demo(factory: Factory, args: Args) -> int | None:
    demo = _kernel("demo")
    try:
        demo.build_demo(args.demo_home or args.home or demo.default_home())
    except demo.DemoError as exc:
        print(f"{PROG} demo: {exc}", file=sys.stderr)
        return 2
    return None


def _adopt(factory: Factory, args: Args) -> None:
    p = _kernel("adopt").adopt(factory, args.title, source=args.source, intent=args.intent, person=args.person,
                               persona=args.persona, base_url=args.base_url, maturity=args.maturity,
                               profile=None if args.profile == "auto" else args.profile)
    meta = p.meta
    _print({"project": p.pid, "stage": meta["stage"], "intent": meta.get("intent"), "profile": meta.get("profile"),
            "baseline": (p.read("adopted.json") or {}).get("baseline"),
            "characterisation": {k: (p.read("baseline.json") or {}).get(k) for k in ("verdict", "reason")},
            "contract": meta.get("contract_revision")})


def _sync(factory: Factory, args: Args) -> None:
    adopt = _kernel("adopt")
    p = factory.project(args.pid)
    out = {"upstream": adopt.sync(p)}
    if p.meta.get("intent") == "monitor" and (p.read("adopted.json") or {}).get("base_url"):
        out["probe"] = {k: v for k, v in adopt.probe(p).items() if k != "scenarios"}
    _print(out)


def _security_status(factory: Factory, args: Args) -> None:
    p = factory.project(args.pid)
    rows = [{"id": f["id"], "rule": f["rule"], "level": f["level"], "tool": f["tool"]["name"], "state": f["state"],
             "location": f.get("location"), "acceptance": f.get("acceptance")} for f in security.findings(p)]
    _print(security.summary(p) | {"findings": rows})


def _pack(factory: Factory, args: Args) -> None:
    if args.pid in ("withdraw", "pin") and args.words:  # `pack withdraw <pid> "why"`, `pack pin <pid>`
        return _kernel("bundle" if args.pid == "withdraw" else "deliver").pack_command(factory, args, _print)
    pack = packs.build_pack(factory.project(args.pid), args.release)
    if args.yaml:
        print(packs.render_yaml(pack), end="")
    else:
        _print(pack)


def _evidence(factory: Factory, args: Args) -> None:
    path = evidence_pack.export(factory.project(args.pid), args.out, person=args.person, persona=args.persona)
    with zipfile.ZipFile(path) as z:
        att = json.loads(z.read("attestation.json"))
    _print({"file": str(path), "verdict": att["verdict"], "meaning": att["meaning"]})


def _embed_create(factory: Factory, args: Args) -> None:
    e = embeds.create(factory, kind=args.kind, origins=args.origin, person=args.person, persona=args.persona,
                      project_id=args.project, label=args.label, brief=args.brief)
    out = embeds.public(e) | {"key_note": "the key is shown this once: Rihmasto keeps only its sha256 hash"}
    if args.endpoint:
        out["snippet"] = embeds.snippet(e, args.endpoint, key=e["key"])
    _print(out)


def _autonomy_show(factory: Factory, args: Args) -> None:
    if args.pid is None:
        _print({"scope": "factory", **autonomy.describe(factory=factory)})
        return
    p = factory.project(args.pid)
    _print({"scope": "project", "project": p.pid, "factory_cap": autonomy.factory_cap(factory),
            **autonomy.describe(p)})


def _autonomy_set(factory: Factory, args: Args) -> None:
    target = factory.project(args.project) if args.project else factory
    _print(autonomy.set_cap(target, args.level, person=args.person, persona=args.persona, reason=args.reason))


def _concept_edit(factory: Factory, args: Args) -> None:
    names = ("title", "profile", "maturity", "mode")
    fields = {k: getattr(args, k) for k in names if getattr(args, k) is not None}
    if not fields:
        raise ValueError("name at least one of --title, --profile, --maturity or --mode")
    card = signals.edit_concept(factory, args.card, person=args.person, persona=args.persona, **fields)
    _print({"card": card["id"], "state": card["state"], **{k: card["payload"].get(k) for k in names}})


def _observe(factory: Factory, args: Args) -> None:
    facts = json.loads(args.facts)
    if not isinstance(facts, dict):
        raise ValueError('the facts are a JSON object, for example {"project": "<pid>"}')
    _print(observations.observe(factory, args.trigger, facts=facts, source=args.source))


# -- the tables and main -----------------------------------------------------------------------------

# Each command line selects one handler, by its command ("status") or its group and command
# ("workspace open"). A handler returns the exit code, or None for 0.
HANDLERS: dict[str, Handler] = {
    "new": _new, "intake": _intake, "compile": _compile, "answer": _answer, "assume": _assume,
    "change": _change, "learn": _learn, "lanes": _lanes, "doctor": _doctor, "demo": _demo,
    "adopt": _adopt, "sync": _sync,
    "run": lambda f, a: _print(_kernel("pipeline").advance(f.project(a.pid), model=_model())),
    "tick": lambda f, a: _print(_kernel("pipeline").tick(f)),
    "spec": lambda f, a: _print(
        {"requirements": len(_kernel("spec").make_spec(f.project(a.pid), model=_model())["requirements"])}),
    "build": lambda f, a: _print(_kernel("dispatch").build(autonomy.cleared_to_build(f.project(a.pid)))),
    "status": lambda f, a: _print(status(f, a.pid)),
    "decide": lambda f, a: _print(Canon(f.project(a.pid)).decide(a.card, a.verdict, person=a.person,
                                                                 persona=a.persona, reason=a.reason)),
    "apply": lambda f, a: _print(_kernel("change").apply_change(f.project(a.pid), a.card, model=_model())),
    "deliver": lambda f, a: _print(_kernel("deliver").deliver(autonomy.cleared_to_deliver(f.project(a.pid)),
                                                              new=a.new)),
    "operate": lambda f, a: _print(_kernel("operate").tick(f.project(a.pid))),
    "resurface": lambda f, a: _print(
        {"revision": _kernel("compile").update_repo_surface(f.project(a.pid), reason=a.reason)}),
    "workspace open": lambda f, a: _print(_kernel("workspace").open_workspace(
        f.project(a.pid), person=a.person, persona=a.persona, agent=a.agent)),
    "workspace submit": lambda f, a: _print(_kernel("workspace").submit_workspace(
        f.project(a.pid), a.path, person=a.person, persona=a.persona, task=a.task)),
    "workspace list": lambda f, a: _print({"workspaces": _kernel("workspace").workspaces(f.project(a.pid))}),
}
# The capability layer. A write is signed by a named person and persona, and a refusal from the
# kernel is a message on stderr and exit 2, never a traceback.
CAPABILITY: dict[str, Handler] = {
    "security ingest": lambda f, a: _print(sarif.ingest(f.project(a.pid), a.file, person=a.person,
                                                        persona=a.persona)),
    "security accept": lambda f, a: _print(security.accept_risk(
        f.project(a.pid), a.finding, person=a.person, persona=a.persona, reason=a.reason, expires=a.expires)),
    "security status": _security_status, "pack": _pack, "evidence": _evidence, "embed create": _embed_create,
    "embed list": lambda f, a: _print({"embeds": [embeds.public(e) for e in embeds.embeds(f)]}),
    "embed revoke": lambda f, a: _print(embeds.public(embeds.revoke(f, a.id, person=a.person, persona=a.persona))),
    "autonomy show": _autonomy_show, "autonomy set": _autonomy_set, **outputs.handlers(_print),
    "signal log": lambda f, a: _print(signals.receive(f, a.text, channel=a.channel, source=a.source,
                                                      person=a.person, persona=a.persona, ref=a.ref)),
    "signal list": lambda f, a: _print({"signals": signals.signals(f, a.state)}),
    "signal triage": lambda f, a: _print(signals.triage(f, a.id, model=_model() if a.with_model else None)),
    "concept edit": _concept_edit, "observe": _observe, **graph_ask.handlers(_print, _model),
    "concept apply": lambda f, a: _print({"applied": signals.apply_concepts(f)}), **integrations.handlers(_print),
    "updates apply": lambda f, a: _print({"project": a.pid, "applied": observations.apply_updates(f.project(a.pid))}),
    "square": lambda f, a: _print(signals.square(f)), "catalogue": lambda f, a: _print(catalogue(f)),
    **input_summary.handlers(_print, lambda: _model(), print), **autopilot_cli.handlers(_print, _model),
    **standalone.handlers(_print, _model)}


def command_of(args: Args) -> str:
    """The table key of a parsed command line."""
    sub = getattr(args, "sub", None)
    return f"{args.cmd} {sub}" if sub else str(args.cmd)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    factory = Factory(args.home)
    name = command_of(args)
    try:
        with access.cli_signing(factory, args, name), modules.allowed(factory, name, args):  # D-0016, FR-MOD2
            if name in HANDLERS:
                return HANDLERS[name](factory, args) or 0
            if getattr(args, "person", None) is not None and not is_person(args.person):
                raise DecisionRefused(f"{args.person!r} is not a person: a write is signed by a named person")
            return CAPABILITY[name](factory, args) or 0
    except (access.AccessRefused, *REFUSED) as exc:
        if name in HANDLERS and not isinstance(exc, access.AccessRefused):
            raise
        print(f"{PROG} {name}: {exc.args[0] if isinstance(exc, KeyError) and exc.args else exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
