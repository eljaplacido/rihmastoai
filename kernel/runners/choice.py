"""Which runner runs each role, for the factory and for a project, chosen by IT on a card (D-0019, FR-HRN1).

A choice names a role (the builder or the verifier), a runner, the runner's version (pinned: a run with another
version does not run), and what the runner needs: a model and its family, a command line for ``command``, and the
optional docker sandbox. Going back to Gnomon, the default and the reference, takes effect at once. Any other runner
waits on a ``runner`` card in the factory's Inbox that only IT decides; it applies from the decision on.

The choices are kept in the factory's own project (``runners.json``), signed and in its ledger. What applies to a
project and role is that project's latest approved choice, else the factory's, else Gnomon. The verifier must stay
another model family than the builder, whichever runners they use (FR-G6): a choice that breaks this is refused,
and a pair that breaks it at run time does not run.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import Canon, DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.runners import ASSURANCE, DEFAULT, ROLES, RUNNERS, RunnerRefused, assurance_of, label_of
from kernel.store import Factory, updating_json

FILE = "runners.json"
PROPOSERS = ("it", "developer")
SANDBOXES = ("off", "docker")
FACTORY = "factory"


def _fp(factory: Factory, create: bool = False) -> Any:
    from kernel.learn import factory_project

    return factory_project(factory, create)


def choices(factory: Factory) -> list[dict[str, Any]]:
    """Every choice ever made, each with its state now: active, waiting on IT, declined or withdrawn."""
    fp = _fp(factory)
    if fp is None:
        return []
    items = (fp.read(FILE, {}) or {}).get("choices") or []
    cards = {c["id"]: c for c in Canon(fp).cards(state=None, kind="runner")}
    return [c | {"state": _state(c, cards.get(c.get("card") or ""))} for c in items if isinstance(c, dict)]


def _state(choice: dict[str, Any], card: dict[str, Any] | None) -> str:
    if not choice.get("card"):
        return "active"
    if card is None:
        return "withdrawn"
    if card["state"] == "open":
        return "waiting"
    verdict = (card.get("decision") or {}).get("verdict")
    return {"approve": "active", "decline": "declined"}.get(str(verdict), str(card["state"]))


def effective(factory: Factory, pid: str | None, role: str, *, items: list[dict[str, Any]] | None = None) -> dict:
    """The choice that applies to ``pid`` (None: the factory) and ``role``: the project's latest active one, else
    the factory's, else Gnomon."""
    items = choices(factory) if items is None else items
    for scope in ([pid] if pid and pid != FACTORY else []) + [FACTORY]:
        mine = [c for c in items if c.get("scope") == scope and c.get("role") == role and c["state"] == "active"]
        if mine:
            return mine[-1] | {"from": "project" if scope != FACTORY else "factory"}
    return {"runner": DEFAULT, "role": role, "scope": FACTORY, "from": "default", "state": "active"}


def family_of(choice: dict[str, Any], role: str) -> str | None:
    """The model family a role's runner answers with: the routing's for Gnomon, the choice's for another."""
    if choice.get("runner", DEFAULT) == DEFAULT:
        from kernel.lanes import load_routing, model_family

        try:
            return model_family(load_routing(), role)
        except (FileNotFoundError, ValueError, KeyError):
            return None
    return choice.get("family") or RUNNERS.get(str(choice.get("runner")), {}).get("family")


def family_clash(builder: dict[str, Any], verifier: dict[str, Any]) -> str | None:
    """Why this builder and verifier may not run together: the same model family (FR-G6)."""
    b, v = family_of(builder, "builder"), family_of(verifier, "verifier")
    if b and v and b.lower() == v.lower():
        names = (label_of(builder.get("runner", DEFAULT)), label_of(verifier.get("runner", DEFAULT)))
        return f"the verifier must be another model family than the builder: {names[0]} and {names[1]} are both {b}"
    return None


def _signed(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"refused: {person!r} is not a person; a runner is chosen by a named person")
    if persona not in PERSONAS or persona not in PROPOSERS:
        raise DecisionRefused(f"refused: a {persona} may not choose a runner ({', '.join(PROPOSERS)} may; IT decides)")


def _scope(factory: Factory, scope: str | None) -> str:
    if not scope or scope == FACTORY:
        return FACTORY
    if scope not in {p.pid for p in factory.projects()} or scope.startswith("_"):
        raise RunnerRefused(f"there is no project {scope!r}")
    return scope


def _needs(runner: str, given: dict[str, Any]) -> dict[str, Any]:
    """What the runner needs, checked: its command line, its model family, the sandbox's image."""
    out = {k: v for k, v in given.items() if v not in (None, "", [])}
    if runner == "command" and "{prompt_file}" not in str(out.get("command") or ""):
        raise RunnerRefused("the command runner needs its command line, with {prompt_file} where the task goes")
    if runner != DEFAULT and not (out.get("family") or RUNNERS[runner].get("family")):
        if runner == "opencode" and out.get("model"):
            from kernel.models_setup import family_of as name_family

            out["family"] = name_family(str(out["model"]).rsplit("/", 1)[-1])
        else:
            raise RunnerRefused(f"name the model family {label_of(runner)} answers with (--family): the verifier must "
                                "be another family than the builder")
    sandbox = out.get("sandbox") or "off"
    if sandbox not in SANDBOXES:
        raise RunnerRefused(f"the sandbox is one of {', '.join(SANDBOXES)}")
    if sandbox == "docker" and not out.get("image"):
        raise RunnerRefused("the docker sandbox needs the image that holds the harness (--image)")
    return out | {"sandbox": sandbox}


def _pin(runner: str, given: dict[str, Any]) -> str | None:
    """The version to pin: the one named, else the one on this machine. A runner that is not here is refused."""
    if runner == DEFAULT:
        return given.get("version")
    from kernel.runners.detect import detect

    found = detect(runner, given)
    if not found["found"] and not given.get("version"):
        raise RunnerRefused(found["why"] + " (or name the version to pin with --version)")
    return str(given.get("version") or found["version"])


def propose(factory: Factory, *, role: str, runner: str, person: str, persona: str, scope: str | None = None,
            reason: str = "", **given: Any) -> dict[str, Any]:
    """Choose ``runner`` for ``role``: Gnomon at once; another runner on an IT card, its version pinned."""
    _signed(person, persona)
    if role not in ROLES:
        raise RunnerRefused(f"the role is one of {', '.join(ROLES)}")
    if runner not in RUNNERS:
        raise RunnerRefused(f"there is no runner {runner!r}; the runners are {', '.join(RUNNERS)}")
    where = _scope(factory, scope)
    need = _needs(runner, given)
    entry = {"scope": where, "role": role, "runner": runner, **need, "version": _pin(runner, need),
             "reason": reason.strip()[:2000], "by": person, "persona": persona, **assurance_of(runner)}
    items = choices(factory)
    pid = None if where == FACTORY else where
    other = "verifier" if role == "builder" else "builder"
    pair = {role: entry | {"state": "active"}, other: effective(factory, pid, other, items=items)}
    clash = family_clash(pair["builder"], pair["verifier"])
    if clash:
        raise RunnerRefused(f"refused: {clash}")
    fp = _fp(factory, True)
    if runner != DEFAULT:
        entry["card"] = _card(fp, entry)["id"]
    with updating_json(fp.path(FILE), {"choices": []}) as data:
        kept = data.setdefault("choices", [])
        entry = {"id": f"RN-{len(kept) + 1:03d}", "at": factory.clock.stamp(), **entry}
        kept.append(entry)
    fp.log("runner_chosen" if runner == DEFAULT else "runner_proposed",
           {k: entry.get(k) for k in ("id", "scope", "role", "runner", "version", "family", "sandbox", "card",
                                      "assurance", "reason")} | {"person": person, "persona": persona})
    return entry | {"state": "active" if runner == DEFAULT else "waiting"}


def _card(fp: Any, entry: dict[str, Any]) -> dict[str, Any]:
    runner, where = entry["runner"], entry["scope"]
    label = f"{label_of(runner)} {entry.get('version') or ''}".strip()
    body = "\n".join([
        f"Runs the {entry['role']} for {'every project' if where == FACTORY else where}, "
        f"pinned at {entry.get('version')}.",
        f"Assurance: {ASSURANCE[entry['assurance']]}. Gnomon's in-run enforcement does not apply; the write scope, "
        "the protected paths, fail-first, the verifier and the holdouts are checked after every run.",
        f"Sandbox: {entry['sandbox']}" + (f" (image {entry.get('image')})." if entry.get("image") else "."),
        f"Model family: {entry.get('family') or RUNNERS[runner].get('family') or '-'}.",
        f"Reason: {entry.get('reason') or '-'}. Proposed by {entry['by']} ({entry['persona']})."])
    return Canon(fp).card("runner", f"Run the {entry['role']} with {label}?", body=body,
                          refs={"runner": runner, "role": entry["role"],
                                **({} if where == FACTORY else {"project": where})},
                          payload={k: v for k, v in entry.items() if k not in ("by", "persona")})


def view(factory: Factory, *, pid: str | None = None, look: bool = True) -> dict[str, Any]:
    """What the Runners page and `rihmasto runners list` show: each runner (found here or not, its version), what
    applies to the factory and to each project that has its own choice, every choice and its state."""
    from kernel.runners.detect import detect

    items = choices(factory)
    latest = {c["runner"]: c for c in items}
    runners = [{"id": n, **{k: m[k] for k in ("label", "about", "assurance")},
                "assurance_label": ASSURANCE[m["assurance"]], "family": m["family"],
                **({"detected": detect(n, latest.get(n))} if look else {})} for n, m in RUNNERS.items()]
    pids = sorted({c["scope"] for c in items if c.get("scope") not in (None, FACTORY)} | ({pid} if pid else set()))
    applies = {p: _applies(factory, p, items) for p in [FACTORY, *pids]}
    out = {"runners": runners, "applies": applies, "choices": items[::-1], "roles": list(ROLES),
           "assurance": ASSURANCE, "default": DEFAULT, "proposers": list(PROPOSERS), "deciders": ["it"]}
    if look:
        from kernel.runners.sandbox import docker_status

        out["docker"] = docker_status()
    return out


def _applies(factory: Factory, pid: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    roles = {r: effective(factory, pid, r, items=items) for r in ROLES}
    shown = {r: {k: c.get(k) for k in ("id", "runner", "version", "family", "sandbox", "from", "model")}
             | {"label": label_of(c.get("runner", DEFAULT)), **assurance_of(c.get("runner"))} for r, c in roles.items()}
    return shown | {"clash": family_clash(roles["builder"], roles["verifier"])}
