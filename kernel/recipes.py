"""Recipes and sandbox trials: a proven capability is reused before anything new is built (FR-Q8).

A **recipe** is a delivered project whose latest capability pack is intact and valid, saved by a
product owner, a business owner or IT (`_factory/recipes.json`): its spec, a contract summary, the
profile, the pack's version and hash, and the **parameters** every new use must answer.
- `match` proposes recipes for a need by rule, with no model: two shared keywords, or one and the
  profile the need's own words name (the default profile, when no word stands out, does not count).
- `instantiate` starts an explore project from the recipe's spec, each parameter a question in the
  canon (answered when a value was given, else put to a person). Its plan waits for a person, so the
  pipeline builds nothing around an unanswered parameter.

A **sandbox trial** delivers an explore release as a local preview (`kernel/deliver.py`), runs its
holdouts (`kernel/operate.py`) and says the result in plain words, with scores only. A watchdog
process stops it when its time limit passes; `sweep` stops any whose watchdog did not. Its outcome
waits on an `approval` card for the named person: approve promotes the project (demo by default),
reject discards it. A decision by anyone else is not applied: the named person is asked again.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from typing import Any

from kernel.canon import CARD_DECIDERS, PERSPECTIVES, Canon, DecisionRefused
from kernel.filelock import locked
from kernel.people import PERSONAS, is_person
from kernel.store import MATURITIES, REPO_ROOT, slugify, write_text

SAVERS = ("product_owner", "business_owner", "it")
USERS = ("business_owner", "product_owner")
TRIAL_PERSONAS = CARD_DECIDERS["approval"]
MAX_TTL_MINUTES = 24 * 60
VERDICT_WORDS = {"approve": "promote", "reject": "discard"}
DECIDED_STATES = {"promote": "promoted", "discard": "discarded"}
_WATCHDOGS: dict = {}


def _check(person: str, persona: str, allowed: tuple, what: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in PERSONAS or persona not in allowed:
        raise DecisionRefused(f"a {persona} may not {what}; {', '.join(allowed)} may")


def _store(factory: Any) -> Any:
    from kernel.learn import factory_project

    return factory_project(factory)


def recipes(factory: Any) -> list:
    return list(_store(factory).read("recipes.json", []) or [])


def get(factory: Any, recipe_id: str) -> dict:
    found = next((r for r in recipes(factory) if r["id"] == recipe_id), None)
    if found is None:
        raise KeyError(recipe_id)
    return found


# -- saving a recipe -------------------------------------------------------------------------------

def _proven_pack(project: Any) -> dict:
    """The latest pack, when it is intact, valid and for the latest delivered release."""
    from kernel.deliver import releases
    from kernel.packs import latest_pack, pack_problems

    done = [r for r in releases(project) if r.get("state") == "done"]
    if not done:
        raise DecisionRefused("the project has no delivered release")
    pack = latest_pack(project)
    if pack is None:
        raise DecisionRefused(f"release {done[-1]['release']} has no capability pack yet: build it first")
    if pack.get("release") != done[-1]["release"]:
        raise DecisionRefused(f"the latest pack is for release {pack.get('release')}, not the delivered release "
                              f"{done[-1]['release']}: build its pack first")
    problems = pack_problems(project, pack)
    if problems:
        raise DecisionRefused("the latest pack does not match its record: " + "; ".join(problems))
    acc = pack.get("acceptance") or {}
    if not acc.get("valid"):
        why = ", ".join(f"{c['criterion']} {c['state']}" for c in acc.get("not_valid_because") or []) or "no criteria"
        raise DecisionRefused(f"the latest capability pack ({pack.get('version')}) is not valid: {why}")
    return pack


def _parameters(parameters: list) -> list:
    out: list = []
    for p in parameters or []:
        p = {"question": p} if isinstance(p, str) else p
        if not isinstance(p, dict) or not str(p.get("question", "")).strip():
            raise ValueError("each parameter needs a question")
        name = slugify(str(p.get("name") or p["question"]), 40)
        perspective = p.get("perspective", "business")
        if perspective not in PERSPECTIVES:
            raise ValueError(f"a parameter's perspective is one of {', '.join(PERSPECTIVES)}")
        if name in {x["name"] for x in out}:
            raise ValueError(f"two parameters are named {name!r}")
        out.append({"name": name, "question": str(p["question"]).strip(), "perspective": perspective,
                    "blocking": bool(p.get("blocking", True))})
    return out


def _contract_summary(project: Any) -> dict:
    contract = project.read("contract.json") or {}
    return {"revision": contract.get("revision"), "requirements": [
        {"id": r["id"], "statement": r.get("statement"), "criteria": [
            {"id": c["id"], "kind": (c.get("check") or {}).get("kind", "test")} for c in r.get("acceptance", [])]}
        for r in contract.get("requirements", [])]}


def _keywords(*texts: str) -> list:
    from kernel.signals import _words

    return sorted(set().union(*(_words(t or "") for t in texts)))[:40]


def save(project: Any, *, parameters: list, person: str, persona: str, title: str | None = None,
         keywords: list | None = None) -> dict:
    """Save a delivered project whose latest capability pack is valid as a recipe."""
    from kernel.profiles import profile_of

    _check(person, persona, SAVERS, "save a recipe")
    pack = _proven_pack(project)
    spec = project.read("spec.json")
    if not spec:
        raise DecisionRefused("the project has no spec for a recipe to start from")
    params = _parameters(parameters)
    items = recipes(project.factory)
    same = next((r for r in items if r["pack"]["content_sha256"] == pack["content_sha256"]), None)
    if same:
        raise ValueError(f"pack {pack['version']} of this project is already recipe {same['id']}")
    name = str(title or project.meta.get("title") or spec.get("title"))
    recipe = {"id": f"RC-{len(items) + 1:03d}", "title": name, "from_project": project.pid,
              "profile": profile_of(project)["id"], "spec": spec, "contract": _contract_summary(project),
              "pack": {k: pack.get(k) for k in ("version", "content_sha256", "release")}, "parameters": params,
              "keywords": _keywords(name, spec.get("title", ""), spec.get("summary", ""), " ".join(keywords or [])),
              "saved_by": person, "persona": persona, "at": project.factory.clock.stamp()}
    _store(project.factory).write("recipes.json", items + [recipe])
    event = {"recipe": recipe["id"], "project": project.pid, "pack": recipe["pack"]["version"], "by": person,
             "persona": persona}
    _store(project.factory).log("recipe_saved", event)
    project.log("recipe_saved", event)
    return recipe


# -- matching a need to a recipe --------------------------------------------------------------------

def match(factory: Any, text: str) -> list:
    """Recipes for a need, by rule: two shared keywords, or one and the same profile. The profile
    counts only when the need's own words name it, not when it is the default nothing stood out from."""
    from kernel.profiles import propose_profile

    words = set(_keywords(text))
    proposal = propose_profile(text)
    profile = proposal["profile"] if proposal["scores"][proposal["profile"]] else None
    out = []
    for r in recipes(factory):
        hits = sorted(words & set(r["keywords"]))
        same = r["profile"] == profile
        if len(hits) >= 2 or (hits and same):
            out.append({"recipe": r["id"], "title": r["title"], "profile": r["profile"], "pack": r["pack"]["version"],
                        "keywords": hits, "same_profile": same,
                        "parameters": [p["question"] for p in r["parameters"]],
                        "basis": "shares " + ", ".join(hits) + (f" and the profile {profile}" if same else "")})
    return sorted(out, key=lambda m: (-len(m["keywords"]), not m["same_profile"], m["recipe"]))


def match_signal(factory: Any, signal_id: str) -> list:
    """Recipes for a signal in the delivery square (a concept card's payload names its signal)."""
    from kernel.signals import signals

    found = next((s for s in signals(factory) if s["id"] == signal_id), None)
    if found is None:
        raise KeyError(signal_id)
    return match(factory, found["text"])


# -- a new project from a recipe --------------------------------------------------------------------

def _spec_from(recipe: dict, title: str, maturity: str) -> dict:
    """The recipe's spec for a new use: its requirements are proposals until this owner confirms them."""
    spec = json.loads(json.dumps(recipe["spec"]))
    origin = {"recipe": recipe["id"], "pack": recipe["pack"]["version"], "project": recipe["from_project"]}
    spec.update(title=title, maturity=maturity, from_recipe=origin)
    for r in spec.get("requirements", []):
        r.pop("decided_by", None)
        r.update(provenance="vendor-proposed", sources=["proposed"],
                 basis=f"recipe {recipe['id']}, proven by pack {recipe['pack']['version']}")
    return spec


def instantiate(factory: Any, recipe_id: str, *, title: str, parameters: dict | None, person: str,
                persona: str) -> Any:
    """A new explore project whose spec starts from the recipe, with its parameters as questions."""
    from kernel.intake import render_brief
    from kernel.spec import render_spec_md

    _check(person, persona, USERS, "start a project from a recipe")
    recipe = get(factory, recipe_id)
    given = dict(parameters or {})
    unknown = sorted(set(given) - {p["name"] for p in recipe["parameters"]})
    if unknown:
        raise ValueError(f"recipe {recipe_id} has no parameter {', '.join(unknown)}")
    project = factory.new_project(title, maturity="explore", mode="mixed", profile=recipe["profile"])
    text = f"From recipe {recipe['id']}, {recipe['title']}: {recipe['spec'].get('summary', '')}"
    project.write("source.json", {"kind": "recipe", "text": text, "requested_by": person, "recipe": recipe["id"]})
    spec = _spec_from(recipe, title, "explore")
    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    canon = Canon(project)
    for p in recipe["parameters"]:
        q = canon.add_question(p["question"], p["perspective"], blocking=p["blocking"],
                               rationale=f"A parameter of recipe {recipe['id']}: every new use answers it.")
        if p["name"] in given:
            canon.answer(q["id"], str(given[p["name"]]), person=person, persona=persona)
        else:
            canon.ask(q["id"])
    render_brief(project)
    still_open = [q["id"] for q in canon.questions("open")]
    project.update_meta(source_kind="recipe", requested_by=person, approve_plan=True, stage=2 if still_open else 4,
                        recipe={"id": recipe["id"], "pack": recipe["pack"]["version"], "from": recipe["from_project"]})
    event = {"recipe": recipe["id"], "project": project.pid, "by": person, "persona": persona, "open": still_open}
    project.log("created_from_recipe", event)
    _store(factory).log("recipe_used", event)
    return project


# -- sandbox trials ---------------------------------------------------------------------------------

def trials(project: Any) -> list:
    return list(project.read("trials.json", []) or [])


def _lock(project: Any) -> Any:
    return locked(project.path("trials", ".lock"))


def _update(project: Any, n: int, **changes: Any) -> dict:
    with _lock(project):
        items = trials(project)
        for t in items:
            if t["trial"] == n:
                t.update(changes)
                project.write("trials.json", items)
                return t
    raise KeyError(f"trial {n}")


def _ready(project: Any) -> None:
    meta = project.meta
    if meta.get("halted"):
        raise DecisionRefused("the project is stopped or discarded")
    if meta.get("maturity") != "explore":
        raise ValueError(f"a sandbox trial runs at explore maturity; this project is {meta.get('maturity')}")
    if not project.path("repo.git").exists():
        raise DecisionRefused("the project is not compiled yet: there is nothing to try")
    open_blocking = [q["id"] for q in Canon(project).questions("open") if q["blocking"]]
    if open_blocking:
        raise DecisionRefused("blocking questions are open: " + ", ".join(open_blocking))
    running = [t["trial"] for t in trials(project) if t["state"] == "running"]
    if running:
        raise DecisionRefused(f"trial {running[0]} still runs; it stops at its time limit or when it is decided")


def _scores(report: dict) -> dict:
    """Holdout scores only: never what a scenario expected."""
    return {"verdict": report["verdict"], "scenarios": report["scenarios"], "passed": report["passed"],
            "failed": report["failed"], "missing": list(report["missing"]),
            "by_criterion": {r["criterion"]: r["verdict"] for r in report["results"]}}


def _holdout_words(h: dict) -> str:
    n = h["scenarios"]
    if h["verdict"] == "passed":
        return "Its holdout scenario passed." if n == 1 else f"All {n} holdout scenarios passed."
    if h["verdict"] == "not applicable":
        return "It has no holdout scenarios to run."
    failing = sorted(c for c, v in h["by_criterion"].items() if v != "passed")
    words = f"{h['passed']} of {h['scenarios']} holdout scenarios passed"
    words += f"; not passing: {', '.join(failing)}." if failing else "."
    if h["missing"]:
        words += f" Scenarios are missing for {', '.join(h['missing'])}, so the holdouts are not measured."
    return words


def _plain(project: Any, t: dict, out: dict) -> str:
    from kernel.deliver import custody_safe

    title, who = project.meta.get("title"), t["person"]
    if t["preview"] is None:
        why = (f"it waits on card {out.get('waiting_on')}" if out.get("state") == "waiting"
               else custody_safe(out.get("reason") or f"delivery {out.get('state')}"))
        return (f"The sandbox of {title} did not start: {why}. Nothing runs. {who} decides whether to promote it "
                "to a normal project anyway, or to discard it.")
    return (f"Release {t['release']} of {title} (revision {t['revision'][:12]}) runs as a local preview at "
            f"{t['preview']}. {_holdout_words(t['holdouts'])} It stops by itself at {t['expires_at']}, after "
            f"{t['ttl_minutes']:g} minutes. {who} decides: promote it to a normal project, or discard it.")


def _card(project: Any, t: dict) -> dict:
    return Canon(project).card(
        "approval", f"Trial {t['trial']} of {project.meta.get('title')}: promote or discard?",
        body=t["result"] + f"\n\nApprove promotes it to a normal project; reject discards it. Only {t['person']} "
                           "decides this card.",
        refs={"scope": "trial", "trial": t["trial"], "release": t["release"]}, blocking=True,
        payload={"trial": t["trial"], "waits_for": t["person"], "verdicts": dict(VERDICT_WORDS),
                 "holdouts": t["holdouts"], "expires_at": t["expires_at"]})


def _spawn_watchdog(project: Any, n: int, ttl: float) -> dict:
    """A detached process that stops this trial's preview after its time limit, even when the
    process that started the trial has ended."""
    from kernel.roads import _detach

    argv = [sys.executable, "-m", "kernel.recipes", "expire", "--home", str(project.factory.home),
            "--project", project.pid, "--trial", str(n), "--after", str(ttl * 60)]
    log = project.path("trials", f"{n}-watchdog.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as fh:
        proc = subprocess.Popen(argv, cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                **_detach())
    _WATCHDOGS[proc.pid] = proc
    return {"pid": proc.pid, "after_seconds": ttl * 60}


def trial(project: Any, ttl_minutes: float, *, person: str, persona: str, roads: Any = None,
          watchdog: bool = True) -> dict:
    """Run an explore release as a time-boxed local preview with its holdouts. Its outcome waits on a
    card for ``person``: promote to a normal project, or discard."""
    from kernel import operate
    from kernel.autonomy import require
    from kernel.deliver import deliver
    from kernel.roads import slot_state

    _check(person, persona, TRIAL_PERSONAS, "start a sandbox trial")
    if isinstance(ttl_minutes, bool) or not isinstance(ttl_minutes, (int, float)) \
            or not 0 < ttl_minutes <= MAX_TTL_MINUTES:
        raise ValueError(f"the time limit is more than 0 and at most {MAX_TTL_MINUTES} minutes")
    _ready(project)
    require(project, 3, "a sandbox trial")
    out = deliver(project, roads=roads, new=True)
    state = slot_state(project, "preview", "current") if out["state"] == "done" else None
    now = project.factory.clock.now()
    ends = (now + dt.timedelta(minutes=ttl_minutes)).replace(microsecond=0)
    t = {"trial": len(trials(project)) + 1, "release": out["release"], "revision": out["revision"],
         "ttl_minutes": ttl_minutes, "started": project.factory.clock.stamp(),
         "expires_at": ends.isoformat().replace("+00:00", "Z"), "person": person, "persona": persona,
         "delivery": out["state"], "preview": state["base_url"] if state else None,
         "holdouts": _scores(operate.run_holdouts(project, state["base_url"])) if state else None,
         "state": "running" if state else "failed", "stopped": None, "decision": None, "watchdog": None}
    t["result"] = _plain(project, t, out)
    t["card"] = _card(project, t)["id"]
    with _lock(project):
        project.write("trials.json", trials(project) + [t])
    project.log("trial_started", {"trial": t["trial"], "release": t["release"], "state": t["state"],
                                  "expires_at": t["expires_at"], "person": person, "card": t["card"],
                                  "holdouts": {k: v for k, v in (t["holdouts"] or {}).items() if k != "by_criterion"}})
    if watchdog and state:
        t = _update(project, t["trial"], watchdog=_spawn_watchdog(project, t["trial"], float(ttl_minutes)))
    return t


def _stop_preview(project: Any, t: dict, roads: Any) -> bool:
    from kernel.roads import PavedRoads, road_for_slot, slot_state

    state = slot_state(project, "preview", "current")
    if not state or state.get("release") != t["release"]:
        return False
    paved = PavedRoads.load(roads if roads is not None else project.factory)
    road_for_slot(state, paved).stop(project, "preview", "current")
    return True


def _due(project: Any, t: dict) -> bool:
    ends = dt.datetime.fromisoformat(t["expires_at"].replace("Z", "+00:00"))
    return project.factory.clock.now() >= ends


def expire(project: Any, trial_no: int | None = None, *, roads: Any = None, force: bool = False,
           why: str = "its time limit passed") -> list:
    """Stop every running trial past its time limit (or ``trial_no``, at once with ``force``)."""
    stopped = []
    for t in trials(project):
        if t["state"] != "running" or (trial_no is not None and t["trial"] != trial_no):
            continue
        if not (force or _due(project, t)):
            continue
        _stop_preview(project, t, roads)
        at = project.factory.clock.stamp()
        stopped.append(_update(project, t["trial"], state="stopped", stopped={"at": at, "why": why},
                               result=t["result"] + f" It was stopped automatically at {at}: {why}."))
        project.log("trial_stopped", {"trial": t["trial"], "release": t["release"], "why": why})
    return stopped


def _apply(project: Any, t: dict, decision: dict, maturity: str, roads: Any) -> dict:
    word = VERDICT_WORDS[decision["verdict"]]
    _stop_preview(project, t, roads)
    at = project.factory.clock.stamp()
    stopped = t["stopped"] or {"at": at, "why": f"{DECIDED_STATES[word]} by {decision['person']}"}
    t = _update(project, t["trial"], state=DECIDED_STATES[word], stopped=stopped,
                decision={"verdict": word, "person": decision["person"], "persona": decision["persona"],
                          "reason": decision.get("reason"), "at": at,
                          "maturity": maturity if word == "promote" else None})
    if word == "promote":
        project.update_meta(maturity=maturity, redeliver=True)
    else:
        project.update_meta(halted=True, discarded={"trial": t["trial"], "by": decision["person"], "at": at})
    project.log("trial_decided", {"trial": t["trial"], "verdict": word, "person": decision["person"],
                                  "persona": decision["persona"], "maturity": t["decision"]["maturity"]})
    return t


def decide(project: Any, trial_no: int, verdict: str, *, person: str, persona: str, reason: str = "",
           maturity: str = "demo", roads: Any = None) -> dict:
    """The named person promotes the trial's project to a normal one, or discards it."""
    if verdict not in ("promote", "discard"):
        raise ValueError("a trial is promoted or discarded")
    if maturity not in MATURITIES or maturity == "explore":
        raise ValueError("a promoted project is demo, pilot or production")
    t = next((x for x in trials(project) if x["trial"] == trial_no), None)
    if t is None:
        raise KeyError(f"trial {trial_no}")
    if t["decision"]:
        raise DecisionRefused(f"trial {trial_no} is already {t['state']}")
    if person != t["person"]:
        raise DecisionRefused(f"trial {trial_no} waits for {t['person']}; {person} may not decide it")
    d = Canon(project).decide(t["card"], "approve" if verdict == "promote" else "reject", person=person,
                              persona=persona, reason=reason)
    return _apply(project, t, d, maturity, roads)


def settle(project: Any, *, roads: Any = None) -> list:
    """Carry out trial cards decided in the Inbox. A decision by someone other than the named person
    is not applied: the card is asked again of the named person."""
    done = []
    canon = Canon(project)
    for t in trials(project):
        if t["decision"]:
            continue
        card = canon.get_card(t["card"])
        if card["state"] != "decided":
            continue
        if card["decision"]["person"] == t["person"]:
            done.append(_apply(project, t, card["decision"], "demo", roads))
            continue
        note = f"decided by {card['decision']['person']}, but trial {t['trial']} waits for {t['person']}; asked again"
        t = _update(project, t["trial"], note=note)
        _update(project, t["trial"], card=_card(project, t)["id"])
        project.log("trial_asked_again", {"trial": t["trial"], "decided_by": card["decision"]["person"],
                                          "waits_for": t["person"]})
    return done


def sweep(factory: Any, *, roads: Any = None) -> dict:
    """One round for every project: stop the trials past their limit, and carry out decided cards."""
    stopped, decided = [], []
    for project in factory.projects():
        if project.path("trials.json").exists():
            stopped += [(project.pid, t["trial"]) for t in expire(project, roads=roads)]
            decided += [(project.pid, t["trial"]) for t in settle(project, roads=roads)]
    return {"stopped": stopped, "decided": decided}


def stop_watchdogs() -> int:
    """Stop every watchdog this process started (a safety net for tests)."""
    for proc in list(_WATCHDOGS.values()):
        if proc.poll() is None:
            proc.kill()
        proc.wait(10)
    n = len(_WATCHDOGS)
    _WATCHDOGS.clear()
    return n


def _main(argv: list | None = None) -> int:
    """The watchdog: `python -m kernel.recipes expire --home H --project P --trial N --after S` waits S
    seconds, then stops that trial."""
    import argparse
    import time

    from kernel.store import Factory

    parser = argparse.ArgumentParser(prog="python -m kernel.recipes", description="Wait, then stop a sandbox trial.")
    parser.add_argument("command", choices=["expire"])
    for name, kind in (("home", str), ("project", str), ("trial", int), ("after", float)):
        parser.add_argument(f"--{name}", type=kind, required=True)
    args = parser.parse_args(argv)
    time.sleep(max(0.0, args.after))
    expire(Factory(args.home).project(args.project), args.trial, force=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
