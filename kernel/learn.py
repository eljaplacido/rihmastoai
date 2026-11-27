"""How the factory itself gets stronger from what happens to its products (FR-K1, FR-K3, FR-F8).

A lesson is left by every defect. When one product's lessons recur in another product, they
are no longer one product's problem. The factory proposes a **default check** that every future
project's check plan carries. A proposal is applied only after a person accepts it: the factory
proposes changes to itself; people decide (FR-K3).

The ledgers also say how each builder model actually performs: cells run, first-round
warranted rate, escalations, and rounds to pass. That is the evidence a routing change must
rest on (FR-F8). The factory proposes a routing experiment; it never re-routes silently. A
round a person submitted from their own workspace is a person's work, not a model's: it is
reported apart, under people (FR-F8-AC-2).

Factory-level proposals and decisions live in a canon of their own, the project
`_factory`. So they go through the same Inbox, with the same rules about who may decide.
Reading it never creates it (FR-S1-AC-3).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from typing import Literal, overload

from kernel.canon import Canon
from kernel.store import Factory, Project, read_json, records_lock, write_json

FACTORY_PID = "_factory"
FACTORY_TITLE = "Rihmasto itself"   # the factory's own project, one name on every face
_WORDS = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "with", "and", "or", "of", "to", "is", "it", "in", "on", "for", "not", "be", "when",
         "then", "given", "returns", "return", "should", "must", "that", "this", "an", "as", "by", "at"}


@overload
def factory_project(factory: Factory, create: Literal[True] = ...) -> Project: ...


@overload
def factory_project(factory: Factory, create: bool) -> Project | None: ...


def factory_project(factory: Factory, create: bool = True) -> Project | None:
    """The factory's own canon. By default it is created on first use. A reader passes
    ``create=False`` and gets None while it does not exist yet, so reading never creates it.
    It is created once, under its canon's lock, however many writers ask for it at once: the canon
    first, then project.json, which says it exists."""
    p = Project(factory, FACTORY_PID)
    if p.path("project.json").exists():
        return p
    if not create:
        return None
    canon = Canon(p)
    with records_lock(canon.lock):
        if not p.path("project.json").exists():
            now = factory.clock.stamp()
            canon.init(goal="Make the factory stronger from what happens to its products.")
            p.write("project.json", {"id": FACTORY_PID, "title": FACTORY_TITLE, "maturity": "production",
                                     "mode": "mixed", "source_kind": "factory", "stage": 7, "created": now,
                                     "updated": now})
    return p


def signature(text: str) -> str:
    """A rough class for a lesson: its content words, sorted. Two lessons with the same words
    are the same class whatever their order or casing."""
    words = sorted({w for w in _WORDS.findall(text.lower()) if w not in _STOP and len(w) > 2})
    return " ".join(words[:8])


def lessons(factory) -> list:
    out = []
    for p in factory.projects():
        if p.pid == FACTORY_PID:
            continue
        contract = p.read("contract.json") or {}
        crit = {c["id"]: c for r in contract.get("requirements", []) for c in r["acceptance"]}
        for lesson in p.read("lessons.json", []) or []:
            c = crit.get(lesson.get("regression_criterion"), {})
            then = c.get("then") or lesson.get("text", "")
            out.append({"project": p.pid, "criterion": lesson.get("regression_criterion"), "then": then,
                        "given": c.get("given", "-"), "when": c.get("when", "-"), "class": signature(then)})
    return out


def immune_memory(factory) -> list:
    """Lesson classes and the projects they occurred in."""
    by_class = defaultdict(list)
    for item in lessons(factory):
        by_class[item["class"]].append(item)
    return [{"class": k, "projects": sorted({i["project"] for i in v}), "examples": v[:3]}
            for k, v in sorted(by_class.items())]


def default_checks(factory) -> list:
    """Checks every new project carries, accepted by a person."""
    return read_json(factory.home / "factory" / "default_checks.json", []) or []


def propose(factory: Factory) -> list:
    """Open a proposal card for every lesson class seen in two or more projects that has no
    proposal yet. The factory's canon is created only when there is a card to open."""
    fp = factory_project(factory, create=False)
    known = {c["payload"].get("class") for c in Canon(fp).cards(state=None, kind="approval")} if fp else set()
    accepted = {d.get("class") for d in default_checks(factory)}
    opened = []
    for entry in immune_memory(factory):
        if len(entry["projects"]) < 2 or entry["class"] in known or entry["class"] in accepted:
            continue
        fp = fp or factory_project(factory)
        canon = Canon(fp)
        ex = entry["examples"][0]
        card = canon.card("approval", f"Add a default check to every project: {ex['then'][:70]}",
                          body=f"Seen in {len(entry['projects'])} projects: {', '.join(entry['projects'])}.",
                          refs={"scope": "factory", "kind": "default_check"},
                          payload={"class": entry["class"], "given": ex["given"], "when": ex["when"],
                                   "then": ex["then"], "projects": entry["projects"]})
        fp.log("factory_proposal", {"card": card["id"], "class": entry["class"], "projects": entry["projects"]})
        opened.append(card)
    return opened


def apply_accepted(factory: Factory) -> list:
    """Accepted proposals become default checks. Rejected ones are remembered, not re-proposed."""
    fp = factory_project(factory, create=False)
    if fp is None:                        # no canon yet: nothing was proposed, so nothing was accepted
        return []
    checks = default_checks(factory)
    have = {c["class"] for c in checks}
    added = []
    for card in Canon(fp).cards(state="decided", kind="approval"):
        d, pl = card["decision"], card["payload"]
        if d["verdict"] != "approve" or pl.get("class") in have:
            continue
        check = {"class": pl["class"], "given": pl["given"], "when": pl["when"], "then": pl["then"],
                 "accepted_by": d["person"], "card": card["id"], "from_projects": pl["projects"]}
        checks.append(check)
        have.add(pl["class"])
        added.append(check)
    if added:
        write_json(factory.home / "factory" / "default_checks.json", checks)
        fp.log("default_checks_added", {"classes": [c["class"] for c in added]})
    return added


def _person(gate: dict) -> str | None:
    """Who submitted a gate round from their own workspace (kernel/workspace.py), or None for a
    builder cell's round."""
    author = gate.get("author")
    if isinstance(author, dict) and author.get("type") == "person":
        return str(author.get("name") or "a person")
    return None


def _ledgers(factory: Factory) -> Iterator[list[tuple[str, dict]]]:
    """Each product ledger's cell runs and gate rounds as (kind, payload), in ledger order. The
    factory's own canon has none."""
    for p in factory.projects():
        if p.pid != FACTORY_PID:
            yield [(r["event"]["kind"], r["event"]["payload"]) for r in p.ledger().of_kind("cell_ran", "gate")]


def model_reliability(factory: Factory) -> dict:
    """Per builder model, from every product ledger: cells run, first-round warranted rate,
    escalations to another model, and the mean number of rounds a merged task took (FR-F8).
    A round a person submitted is not a model's: people_reliability reports it (FR-F8-AC-2).
    A gate is the work of the cell that ran its task and round just before it in the ledger: a
    task built again after a retry starts at round 0 again, maybe with another model."""
    stats: defaultdict[str, Counter] = defaultdict(Counter)
    rounds_to_pass: defaultdict[str, list] = defaultdict(list)
    for events in _ledgers(factory):
        cells: dict = {}
        for kind, pl in events:
            if kind == "cell_ran":
                model = pl.get("final_model") or pl.get("model") or "unknown"
                stats[model]["cells"] += 1
                stats[model]["escalated"] += 1 if pl.get("escalated") else 0
                cells[(pl["task"], pl["round"])] = model
                continue
            if _person(pl) is not None:
                continue
            model = cells.get((pl["task"], pl["round"]), "unknown")
            if pl["round"] == 0:
                stats[model]["first_round"] += 1
                stats[model]["first_round_warranted"] += 1 if pl["verdict"] == "passed" else 0
            if pl["verdict"] == "passed":
                rounds_to_pass[model].append(pl["round"] + 1)
    out = {}
    for model, c in stats.items():
        fr, passed = c["first_round"], rounds_to_pass[model]
        out[model] = {"cells": c["cells"], "escalated": c["escalated"],
                      "first_round_warranted_rate": (c["first_round_warranted"] / fr) if fr else None,
                      "mean_rounds_to_pass": (sum(passed) / len(passed)) if passed else None,
                      "measured": fr > 0}
    return out


def people_reliability(factory: Factory) -> dict:
    """Per person, the gate rounds they submitted from their own workspaces, apart from every
    model's (FR-F8-AC-2): rounds judged, rounds the gate warranted, the warranted rate, and the
    personas they submitted as."""
    out: dict = {}
    for events in _ledgers(factory):
        for kind, pl in events:
            name = _person(pl) if kind == "gate" else None
            if name is None:
                continue
            row = out.setdefault(name, {"rounds": 0, "warranted": 0, "personas": []})
            row["rounds"] += 1
            row["warranted"] += 1 if pl["verdict"] == "passed" else 0
            persona = pl["author"].get("persona")
            if persona and persona not in row["personas"]:
                row["personas"].append(persona)
    for row in out.values():
        row["warranted_rate"] = row["warranted"] / row["rounds"]
    return out
