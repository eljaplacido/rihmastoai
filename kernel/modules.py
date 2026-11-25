"""Modules: use a very small part of Rihmasto, or the whole of it, and change that later (FR-MOD1).

Rihmasto is a catalogue of modules with their dependencies. A factory chooses the set it uses; a
project may override it; the choice is a named person's, recorded in the ledger, and editable later:

- **core**, always on: projects, the Inbox and decisions, the ledger, personas and access, the autonomy
  cap, the knowledge graph, settings and jobs, and attaching a repository of your own;
- **the modules**, below, each with what it adds, what it needs, and what you get from it;
- **presets** for the usual starting points, each saying what you bring and what you get.

Nothing chosen means the full factory, so a home made before modules existed works as it always did.
The full factory chosen by its preset stays the full factory when a module is added to the catalogue
later. Reading a set never creates the factory's own canon.

What a set does (FR-MOD2): the command line refuses a command of a module that is not enabled where it
acts, and names the command that enables it (`allowed`); the pipeline stops at the edge of the set
(`stop_before`): spec only stops once the contract is compiled; the cockpit refuses a write of a
disabled module (`require_route`), and the page shows only what is enabled (cockpit/static/modules.js),
the assistant's map included (`hidden_ids`). A refusal is a refusal like an access refusal: exit 2 on
the command line, 403 in the cockpit. Reads are never refused, and neither is a safety switch: what
stops something still live (revoking a website's chat, removing a webhook source, ending a subscription,
disabling a connector) is core, so turning a module off never leaves a thing running that nobody may
stop (FR-MOD5). The other surfaces ask the same set: the MCP server's write tools (mcp/server.py), a
website's chats (kernel/embeds.py) and webhooks (kernel/hooks.py) through `first_off`, and the
assistant's proposals (kernel/assistant.py).

Hooks for work that plugs in (docs/guides/use-only-what-you-need.md lists the wiring):
- `extend(module, ...)` adds commands, outputs, pages, views, widgets, controls or routes to a module (a
  capability's faces add their command and output to `capabilities`; the brownfield assessment adds its
  report to `assessment`). A name two modules list is shown while either is on;
- each preset's `posture` is a hint for the posture presets (prototype, balanced, production,
  regulated): `suggested_posture(factory)` reads it, and nothing here enforces it.
"""

from __future__ import annotations

import argparse
import contextlib
from collections.abc import Iterable, Iterator
from typing import Any

from kernel.access import AccessRefused
from kernel.people import is_person
from kernel.store import Factory, Project, updating_json

SETTERS = ("business_owner", "product_owner", "it", "developer", "compliance")
KINDS = ("pages", "views", "widgets", "controls", "commands", "routes")
DEFAULT_PRESET = "full"


def _module(label: str, adds: str, *, depends: tuple = (), outputs: tuple = (), planned: tuple = (),
            **parts: tuple) -> dict[str, Any]:
    return {"label": label, "adds": adds, "depends": tuple(depends), "outputs": tuple(outputs),
            "planned": tuple(planned), **{k: tuple(parts.get(k, ())) for k in KINDS}}


# What is always on. A command, page, view, widget or control no module names is core too.
CORE = _module(
    "Core", "projects, the Inbox where people decide, the hash-chained ledger, personas and access, the autonomy "
    "cap, the knowledge graph, settings and jobs, and attaching a repository of your own",
    pages=("home", "projects", "inbox_all", "jobs", "settings"), views=("overview", "inbox", "ledger"),
    widgets=("kpi_strip", "pipeline", "decisions", "activity", "health", "autonomy", "spend"),
    controls=("persona", "lens", "pause", "resume", "decide", "comment", "palette", "customize", "theme", "density",
              "autonomy", "modules", "assistant"),
    commands=("status", "decide", "run", "doctor", "demo", "lanes", "autonomy show", "autonomy set", "modules show",
              "modules set", "modules presets", "repo attach", "repo list", "embed list", "embed revoke",
              "hooks list", "hooks remove", "relay list", "relay unsubscribe", "connector status",
              "connector disable"),
    routes=("post_embed_revoke",))   # a safety switch, and the list it is found in, is never refused (FR-MOD5)

MODULES: dict[str, dict[str, Any]] = {
    "intake": _module(
        "Intake and spec", "the panel's questions and assumptions, then a spec whose every requirement says who "
        "stands behind it",
        outputs=("a confirmed spec with provenance", "the brief, tagged owner, assumed or proposed"),
        views=("questions", "assumptions"), controls=("answer", "assume", "new_project"),
        commands=("new", "intake", "answer", "assume", "spec"),
        routes=("post_project", "post_answer", "post_assume", "post_settle")),
    "plan": _module(
        "Plan and contract", "the plan a person approves, the contract compiled from the spec with no model and "
        "pinned by its hash, the check plan and the holdout custody",
        outputs=("a hashed contract and its check plan, exported as files", "a report of what was decided"),
        views=("plan", "spec"), widgets=("coverage",), commands=("compile", "contract export", "repo contract"),
        routes=("post_plan_requirement",)),
    "build": _module(
        "Build and gate", "builder cells in clean lanes, and the gate: the kernel runs the tests, traces each "
        "criterion to a test, checks fail-first, asks an independent verifier; escalations and workspaces; the "
        "same gate for your own repository, and holdouts against your running service", depends=("plan",),
        outputs=("gate verdicts per change, recorded", "merged code on the product's main"),
        pages=("floor", "insights_all"), views=("tasks", "cell", "insights"),     # Insights: FR-INS1
        widgets=("live", "timeline", "gate_trend", "models", "insight"),
        commands=("build", "resurface", "workspace open", "workspace submit", "workspace list", "repo gate",
                  "repo holdouts")),
    "delivery": _module(
        "Delivery", "paved roads, releases, holdouts against the release, user validation and IT's deploy gate",
        depends=("build",), outputs=("a running release on a paved road", "a container image on the docker road"),
        views=("releases", "try"), widgets=("try_it",), commands=("deliver",)),
    "operations": _module(
        "Operations", "probes, incidents, shadow and canary with rollback, and the updates inbox",
        depends=("delivery",), outputs=("incidents and rollbacks, recorded",), widgets=("updates",),
        commands=("operate", "observe", "updates apply")),
    "change": _module(
        "Change loop", "feedback and changes triaged back to their stage, amendments that make approvals stale, "
        "and lessons that become checks", depends=("plan",), outputs=("amended specs and contracts",),
        views=("changes",), controls=("report",), commands=("change", "apply", "learn"),
        routes=("post_change", "post_comment_promote")),
    "square": _module(
        "Delivery square and signals", "needs arriving as signals, routed to a project or turned into concepts a "
        "business owner validates", depends=("intake",), outputs=("validated concepts that become projects",),
        pages=("square",), widgets=("square",), controls=("log_signal", "validate_concept"),
        commands=("signal log", "signal list", "signal triage", "concept edit", "concept apply", "square", "tick"),
        routes=("post_signal", "post_signal_triage", "post_concept_edit")),
    "capabilities": _module(
        "Capability catalogue and packs", "every capability by its state, and a capability pack per release that "
        "pins it by hash", depends=("delivery",), outputs=("a capability pack per release",),
        planned=("faces: MCP, OpenAI-compatible and embed",),
        pages=("catalogue",), widgets=("catalogue", "eval_trend"), controls=("build_pack", "capability_faces"),
        commands=("catalogue", "pack", "capability check", "capability serve"), routes=("post_pack_build",)),
    "security": _module(
        "Security and red team", "Rihmasto's own static scan of any repository, SARIF from any scanner, the "
        "security gate, and risks a person accepts until a date",
        outputs=("findings in SARIF 2.1.0 and the security gate's verdict",),
        commands=("security ingest", "security accept", "security status", "repo scan")),
    "compliance": _module(
        "Compliance and evidence", "evidence packs for a reviewer: the attestation, the control table, the "
        "decisions, gates, a repository's own releases and the ledger with its chain check",
        outputs=("an evidence pack (a zip with a README) per export",), views=("evidence",),
        widgets=("evidence_packs",), controls=("export_evidence",), commands=("evidence", "repo releases"),
        routes=("post_evidence_export",)),
    "assessment": _module(
        "Assessment", "adopt an existing system: its tests characterised, an inventory by rule, its as-is "
        "contract, its upstream watched for drift, and the system judged from every perspective",
        outputs=("an adopted project with its baseline", "the brownfield assessment, versioned"),
        views=("spec", "assessment"), controls=("run_assessment", "assessment_changes"),
        commands=("adopt", "sync", "assess", "assessment list", "assessment show", "assessment compare",
                  "assessment change"), routes=("post_assessment", "post_assessment_changes")),
    "integrations": _module(
        "Integrations", "website chats (embeds), events and notices out, verified inbound webhooks, connectors "
        "through Gnomon", outputs=("embeds, webhooks and notices",), widgets=("feed_health",),
        controls=("create_embed",),
        commands=("embed create", "relay subscribe", "relay cockpit", "relay run", "relay log", "hooks add",
                  "connector validate", "connector enable", "connector check"), routes=("post_embed",)),
    "assistant": _module(
        "Assistant", "Ask Rihma: answers about your projects from an AI model through Gnomon (how a run goes, what "
        "waits, proposals you confirm); without it, Ask Rihma only shows the way around the cockpit",
        outputs=("answers and proposals you confirm",)),
}


def _preset(label: str, modules: tuple, brings: str, gets: str, posture: str | None = None) -> dict[str, Any]:
    return {"label": label, "modules": modules, "brings": brings, "gets": gets, "posture": posture}


PRESETS: dict[str, dict[str, Any]] = {
    "spec_only": _preset("Spec only", ("intake", "plan"),
                         "a need, vague or precise, or a plan with gaps to fill",
                         "a confirmed spec and a hashed contract, exported as files with a report; nothing is built"),
    "gate_my_code": _preset("Gate my code", ("plan", "build"),
                            "your own git repository, and a contract or a spec file",
                            "a gate verdict on each change: tests by criterion, fail-first, an independent verifier "
                            "and holdouts; you merge", "balanced"),
    "assess_only": _preset("Assess only", ("assessment",), "an existing system's repository",
                           "the system adopted: its tests characterised, an inventory, its upstream watched"),
    "security_only": _preset("Security only", ("security",), "any git repository, or another scanner's SARIF",
                             "findings in SARIF, the security gate's verdict and risks accepted until a date"),
    "evidence_only": _preset("Evidence only", ("compliance",), "a repository and its existing releases",
                             "evidence packs a reviewer can judge: what ran, who recorded it, the chain check",
                             "regulated"),
    "capability_only": _preset("Capability only", ("intake", "plan", "build", "delivery", "capabilities"),
                               "a need for one small capability",
                               "a running capability with its capability pack", "prototype"),
    "full": _preset("Full factory", tuple(MODULES), "any of the above",
                    "everything: a governed service or agent from need to production, and the loop after",
                    "balanced"),
}


class ModuleOff(AccessRefused):
    """A command or a write of a module that is not enabled where it acts. It is refused as access is:
    the command line exits 2, the cockpit answers 403."""


# -- the catalogue's rules ---------------------------------------------------------------------------

def extend(module: str, **parts: Iterable[str]) -> dict[str, Any]:
    """Add names to a module of the catalogue (the hook for work that plugs in). ``parts`` takes the
    KINDS and ``outputs`` or ``planned``; a name already there is kept once."""
    target = MODULES[module]
    for kind, names in parts.items():
        if kind not in (*KINDS, "outputs", "planned"):
            raise ValueError(f"a module has no {kind!r}; it has {', '.join((*KINDS, 'outputs', 'planned'))}")
        target[kind] = tuple(dict.fromkeys((*target[kind], *names)))
    return target


def owners(kind: str, name: str) -> list[str]:
    """The modules that name a page, view, widget, control, command or route; [] when it is core."""
    if name in CORE[kind]:
        return []
    return [m for m, spec in MODULES.items() if name in spec[kind]]


def owner(kind: str, name: str) -> str | None:
    """The first module that names it, or None when it is core."""
    found = owners(kind, name)
    return found[0] if found else None


def closure(ids: Iterable[str]) -> list[str]:
    """``ids`` with everything they need, in catalogue order. An unknown id is a ValueError."""
    want = list(ids)
    unknown = [i for i in want if i not in MODULES]
    if unknown:
        raise ValueError(f"no module {', '.join(map(repr, unknown))}; the modules are {', '.join(MODULES)}")
    seen: set[str] = set()
    while want:
        m = want.pop()
        if m not in seen:
            seen.add(m)
            want.extend(MODULES[m]["depends"])
    return [m for m in MODULES if m in seen]


def needed_by(module: str, among: Iterable[str]) -> list[str]:
    """The modules of ``among`` that need ``module``, directly or through another."""
    return [m for m in among if m != module and module in closure([m])]


def preset_of(modules: Iterable[str]) -> str | None:
    """The preset whose set is exactly ``modules``, or None for a set of one's own."""
    want = set(modules)
    return next((p for p, spec in PRESETS.items() if set(spec["modules"]) == want), None)


# -- reading a set -------------------------------------------------------------------------------------

def _store(factory: Factory, *, create: bool) -> Project | None:
    from kernel.learn import factory_project

    return factory_project(factory, create=create)


def _saved_modules(saved: dict[str, Any]) -> list[str] | None:
    """The modules a saved choice names: the whole catalogue for the full factory chosen by its preset."""
    if saved.get("preset") == DEFAULT_PRESET:
        return list(MODULES)
    return [m for m in MODULES if m in saved["modules"]] if isinstance(saved.get("modules"), list) else None


def factory_set(factory: Factory) -> dict[str, Any]:
    """The factory's set: what a person chose, or the full factory when nobody chose (``chosen`` False)."""
    store = _store(factory, create=False)
    saved = (store.read("modules.json") or {}) if store is not None else {}
    mods = _saved_modules(saved) if isinstance(saved, dict) else None
    if mods is None:
        return {"preset": DEFAULT_PRESET, "modules": list(MODULES), "chosen": False}
    return {"preset": preset_of(mods), "modules": mods, "chosen": True,
            **{k: saved.get(k) for k in ("set_by", "persona", "at", "reason")}}


def project_set(project: Project) -> dict[str, Any]:
    """A project's set: its own override, or the factory's (``inherited`` True)."""
    own = project.meta.get("modules")
    mods = _saved_modules(own) if isinstance(own, dict) else None
    if mods is not None:
        return {"preset": preset_of(mods), "modules": mods, "inherited": False}
    return factory_set(project.factory) | {"inherited": True}


def enabled(target: Factory | Project) -> list[str]:
    return (project_set(target) if isinstance(target, Project) else factory_set(target))["modules"]


def is_on(target: Factory | Project, module: str | None) -> bool:
    """Whether ``module`` is enabled for the factory or the project; core (None) always is."""
    return module is None or module in enabled(target)


def shown(target: Factory | Project, kind: str, name: str, *, among: list[str] | None = None) -> bool:
    """Whether the cockpit shows a page, view, widget or control: core, or a module naming it is on."""
    found = owners(kind, name)
    on = enabled(target) if among is None else among
    return not found or any(m in on for m in found)


def hidden_ids(target: Factory | Project) -> set[str]:
    """The ids of the cockpit map (cockpit/ui_map.json: its views are pages and views, its controls
    are controls) that no enabled module shows: the assistant leaves them out."""
    on = enabled(target)
    return {name for kind in ("pages", "views", "controls") for spec in MODULES.values() for name in spec[kind]
            if not shown(target, kind, name, among=on)}


def offering(name: str) -> dict[str, Any] | None:
    """The module that would show a map id, with what it adds: for the assistant's "not enabled here"."""
    for kind in ("pages", "views", "controls"):
        found = owners(kind, name)
        if found:
            return {"id": found[0], "label": MODULES[found[0]]["label"], "adds": MODULES[found[0]]["adds"]}
    return None


def suggested_posture(factory: Factory) -> str | None:
    """The posture the factory's preset suggests (a hint for kernel/posture.py), None for a set of one's own."""
    preset = factory_set(factory)["preset"]
    return PRESETS[preset]["posture"] if preset else None


# -- choosing a set ------------------------------------------------------------------------------------

def _next_set(current: list[str], *, preset: str | None, modules: Iterable[str] | None, enable: list[str],
              disable: list[str]) -> tuple[list[str], list[str]]:
    """The set asked for, closed under its needs, and the modules added because something needs them."""
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"no preset {preset!r}; the presets are {', '.join(PRESETS)}")
    closure([*enable, *disable])                      # an unknown name is refused before anything else
    if set(enable) & set(disable):
        raise ValueError(f"{', '.join(sorted(set(enable) & set(disable)))}: both turned on and off")
    base = list(PRESETS[preset]["modules"]) if preset else list(modules) if modules is not None else list(current)
    asked = [m for m in base if m not in disable]
    asked += [m for m in enable if m not in asked]
    out = closure(asked)
    for off in disable:
        if off in out:
            raise ValueError(f"{off} cannot be turned off while {', '.join(needed_by(off, out))} needs it: "
                             "turn those off too")
    if not out:
        raise ValueError("a set needs at least one module: choose a preset, or the modules you use")
    return out, [m for m in out if m not in asked]


def _check_setter(person: str, persona: str) -> None:
    from kernel.canon import DecisionRefused

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a module set is chosen by a named person")
    if persona not in SETTERS:
        raise DecisionRefused(f"a {persona} may not choose the modules; {', '.join(SETTERS)} may")


def _check_ask(target: Factory | Project, *, preset: str | None, modules: Iterable[str] | None, inherit: bool,
               named: list[str]) -> None:
    if (preset is not None) + (modules is not None) + bool(inherit) > 1:
        raise ValueError("name a preset, a list of modules, or inherit: one of them")
    if inherit and (not isinstance(target, Project) or named):
        raise ValueError("only a project inherits the factory's set, and as it is: name no module with it")


def set_modules(target: Factory | Project, *, person: str, persona: str, preset: str | None = None,
                modules: Iterable[str] | None = None, enable: Iterable[str] = (), disable: Iterable[str] = (),
                inherit: bool = False, reason: str = "") -> dict[str, Any]:
    """Choose the factory's set, or a project's own (``inherit`` drops a project's own). A named person
    with a setter persona chooses; the change is recorded in that ledger, and nothing is recorded when
    nothing changes. Enabling a module enables what it needs and says so; turning off one that another
    still needs is refused. Returns the set now in force and what changed."""
    _check_setter(person, persona)
    _check_ask(target, preset=preset, modules=modules, inherit=inherit, named=[*enable, *disable])
    before = enabled(target)
    added: list[str] = []
    if isinstance(target, Project):
        own = not project_set(target)["inherited"]
        if inherit:
            after, unchanged = factory_set(target.factory)["modules"], not own
        else:
            after, added = _next_set(before, preset=preset, modules=modules, enable=list(enable), disable=list(disable))
            unchanged = own and after == before
    else:
        after, added = _next_set(before, preset=preset, modules=modules, enable=list(enable), disable=list(disable))
        unchanged = factory_set(target)["chosen"] and after == before
    if unchanged:
        return {"changed": False, "modules": after, "preset": preset_of(after)}
    _record(target, before, after, added, person=person, persona=persona, reason=reason, inherit=inherit)
    return {"changed": True, "modules": after, "preset": preset_of(after), "added_for_dependencies": added,
            "turned_on": [m for m in after if m not in before], "turned_off": [m for m in before if m not in after]}


def _record(target: Factory | Project, before: list[str], after: list[str], added: list[str], *, person: str,
            persona: str, reason: str, inherit: bool) -> None:
    preset = preset_of(after)
    payload = {"from": before, "to": after, "preset": preset, "added_for_dependencies": added,
               "by": person, "persona": persona, "reason": reason}
    saved = {"modules": after, **({"preset": preset} if preset == DEFAULT_PRESET else {})}
    if isinstance(target, Project):
        with updating_json(target.path("project.json"), {}) as doc:
            if inherit:
                doc.pop("modules", None)
            else:
                doc["modules"] = saved
            doc["updated"] = target.factory.clock.stamp()
        target.log("modules_set", {"scope": "project", "inherit": inherit, **payload})
        return
    from kernel.learn import factory_project

    store = factory_project(target)
    store.write("modules.json", saved | {"set_by": person, "persona": persona, "at": target.clock.stamp(),
                                         "reason": reason})
    store.log("modules_set", {"scope": "factory", **payload})


# -- what a set does ------------------------------------------------------------------------------------

def _where(factory: Factory, pid: str | None) -> Factory | Project:
    if pid:
        with contextlib.suppress(KeyError):
            return factory.project(pid)
    return factory


def enable_hint(module: str, target: Factory | Project) -> str:
    scope = f" --project {target.pid}" if isinstance(target, Project) else ""
    return f"`rihmasto modules set --enable {module}{scope} --person ... --persona ...` enables it"


def first_off(factory: Factory, needed: Iterable[str], pid: str | None = None) -> str | None:
    """The first of ``needed`` not enabled where ``pid`` (or the factory) acts, None when all are on: for a
    surface that runs on its own and files into a module, a website's chat or a webhook (FR-MOD5)."""
    target = _where(factory, pid)
    return next((m for m in needed if not is_on(target, m)), None)


def require(factory: Factory, kind: str, name: str, pid: str | None = None) -> None:
    """ModuleOff when ``name`` (a command or a route) belongs only to modules not enabled where it acts."""
    found = owners(kind, name)
    target = _where(factory, pid)
    if not found or any(is_on(target, m) for m in found):
        return
    scope = f"project {target.pid}" if isinstance(target, Project) else "this factory"
    label = MODULES[found[0]]["label"]
    raise ModuleOff(f"{name} is part of {label}, which is not enabled for {scope}: {enable_hint(found[0], target)}")


def _pid_of(args: argparse.Namespace) -> str | None:
    pid = getattr(args, "pid", None)
    if pid in ("withdraw", "pin") and getattr(args, "words", None):   # `pack withdraw <pid> "why"`
        return str(args.words[0])
    return pid if isinstance(pid, str) else getattr(args, "project", None)


@contextlib.contextmanager
def allowed(factory: Factory, command: str, args: argparse.Namespace) -> Iterator[None]:
    """The command line's check before a command runs: ModuleOff when its module is not enabled."""
    require(factory, "commands", command, _pid_of(args))
    yield


def require_route(factory: Factory, route: str, pid: str | None = None) -> None:
    """The cockpit's check before a write route of a module runs (reads are never refused)."""
    require(factory, "routes", route, pid)


STOPS = {"build": "the spec and the contract are ready; nothing is built here",
         "delivery": "the work is built and gated; nothing is delivered here"}
NEXT = {"build": "`rihmasto contract export {pid} --out DIR` writes the spec, the contract and a report",
        "delivery": "`rihmasto status {pid}` shows the gate's verdicts"}


def stop_before(project: Project, module: str, history: list) -> dict[str, Any] | None:
    """Where the pipeline stops because ``module`` is not enabled for the project: done, and why."""
    if is_on(project, module):
        return None
    preset, on = project_set(project)["preset"], enabled(project)
    said = f" ({PRESETS[preset]['label']})" if preset else ""
    record = {"before": module, "preset": preset, "modules": on}
    last = project.ledger().of_kind("stopped_by_modules")
    if not last or {k: last[-1]["event"]["payload"].get(k) for k in record} != record:   # once per edge and set
        project.log("stopped_by_modules", record)
    then = f"{NEXT[module].format(pid=project.pid)}; " if module in NEXT else ""
    return {"state": "done", "stage": project.meta.get("stage"), "history": history, "stopped_by_modules": module,
            "why": f"{STOPS.get(module, 'the next step is not enabled')}: {MODULES[module]['label']} is not "
                   f"enabled{said}. {then}{enable_hint(module, project)}."}


# -- for the cockpit and `modules show` ----------------------------------------------------------------

def _public(mid: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {"id": mid, **{k: list(v) if isinstance(v, tuple) else v for k, v in spec.items()}}


def view(factory: Factory) -> dict[str, Any]:
    """The catalogue, the presets, the factory's set, the projects' own sets, and whether the home is new
    (no project yet and no set chosen: the cockpit offers its first-run choice)."""
    from kernel.learn import FACTORY_PID

    products = [p for p in factory.projects() if p.pid != FACTORY_PID]
    own = {p.pid: project_set(p) for p in products}
    fac = factory_set(factory)
    return {"catalogue": [_public(m, s) for m, s in MODULES.items()], "core": _public("core", CORE),
            "presets": [{"id": p, **{k: list(v) if isinstance(v, tuple) else v for k, v in s.items()}}
                        for p, s in PRESETS.items()],
            "factory": fac, "setters": list(SETTERS),
            "projects": {pid: {"modules": s["modules"], "preset": s["preset"]} for pid, s in own.items()
                         if not s["inherited"]},
            "new_home": not products and not fac["chosen"]}
