"""The insight engine: one observation, rendered for three readers, and an updates inbox.

Triggers come from outside the projects: a new model is released, a CVE names a component, a
product's evals drift, a compliance deadline approaches, a capability is barely used. The engine
assesses which projects the observation touches, chooses who should hear it, and caps what it may
do by the autonomy ladder. Then it renders the same observation three ways:

- **developer:** JSON (for the API, MCP or a script);
- **expert:** a short report sentence with the facts;
- **business:** a proposal in plain words, with the decision it asks for.

At autonomy level 2 or higher, it opens an `update` card on each touched project: trial, decline
or defer, decided by a named person. A trial is a change in behaviour, so v1 records the approval
and the operator re-measures. Nothing updates itself.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import Canon

# Each kind of observation: what it says (`label`), who should hear it (`who`) and the autonomy
# level it acts at (`level`). Plain records: the cockpit reads them with `.get`.
TRIGGERS: dict[str, dict[str, Any]] = {
    "model_release": {"label": "A new model is available", "who": ("developer", "it", "product_owner"), "level": 2},
    "cve": {"label": "A vulnerability names a component", "who": ("it", "developer", "compliance"), "level": 2},
    "eval_drift": {"label": "A product's evals are drifting", "who": ("developer", "product_owner"), "level": 2},
    "compliance_deadline": {"label": "A compliance deadline approaches", "who": ("compliance", "business_owner"),
                            "level": 2},
    "usage_low": {"label": "A capability is barely used", "who": ("business_owner", "it"), "level": 1},
}


def _store(factory, *, create: bool = True):
    from kernel.learn import factory_project

    return factory_project(factory, create=create)


def _touched(factory, trigger: str, facts: dict) -> list:
    projects = [p for p in factory.projects() if not p.pid.startswith("_")]
    named = set(facts.get("projects") or ([facts["project"]] if facts.get("project") else []))
    if named:
        return [p for p in projects if p.pid in named]
    if trigger == "model_release" and facts.get("replaces"):
        old = str(facts["replaces"])
        return [p for p in projects if any(old in str(r["event"]["payload"].get("model") or
                                                      r["event"]["payload"].get("final_model") or "")
                                           for r in p.ledger().of_kind("gnomon_run", "cell_ran"))]
    if trigger in ("cve", "compliance_deadline"):
        return [p for p in projects if p.meta.get("stage", 1) >= 6]   # what is delivered or about to be
    return []


def render(trigger: str, facts: dict, project) -> dict:
    t = TRIGGERS[trigger]
    title = project.meta.get("title") if project is not None else "the factory"
    delta = facts.get("eval_delta")
    if trigger == "model_release":
        expert = (f"{facts.get('model')} is available" + (f", {delta} on this product's evals" if delta else
                  ", not yet measured on this product's evals") + (f"; it would replace {facts['replaces']}" if
                  facts.get("replaces") else "") + ".")
        business = (f"A newer AI model may build {title} better. Test it on this project's checks first "
                    "(changes nothing live)?")
    elif trigger == "cve":
        expert = f"{facts.get('id', 'A CVE')} ({facts.get('severity', 'severity unknown')}) names {facts.get('component')}."
        business = f"A security fix may be needed for {title}. Start a trial with the patched version?"
    elif trigger == "eval_drift":
        expert = f"Criterion {facts.get('criterion')} moved from {facts.get('before')} to {facts.get('after')}."
        business = f"{title} is not performing as it did. Start a trial to find and fix the cause?"
    elif trigger == "compliance_deadline":
        expert = f"{facts.get('framework')} deadline on {facts.get('date')}."
        business = f"{facts.get('framework')} applies to {title} from {facts.get('date')}. Prepare the evidence?"
    else:
        expert = f"{title} was used {facts.get('uses', 'rarely')} times in {facts.get('window', 'the last period')}."
        business = f"{title} is barely used. Worth asking its users why?"
    developer = {"trigger": trigger, "project": project.pid if project is not None else None, "facts": facts,
                 "action": "trial" if t["level"] >= 2 else "inform"}
    return {"developer": developer, "expert": expert, "business": business}


def observe(factory, trigger: str, *, facts: dict, source: str) -> dict:
    """Record an observation and act on it within the autonomy cap."""
    from kernel.autonomy import cap_of

    if trigger not in TRIGGERS:
        raise ValueError(f"trigger must be one of {', '.join(TRIGGERS)}")
    store = _store(factory)
    items = store.read("observations.json", []) or []
    obs: dict[str, Any] = {"id": f"O-{len(items) + 1:03d}", "trigger": trigger,
                           "label": TRIGGERS[trigger]["label"], "facts": facts, "source": str(source)[:200],
                           "at": factory.clock.stamp(), "touched": []}
    for p in _touched(factory, trigger, facts):
        level = min(TRIGGERS[trigger]["level"], cap_of(p))
        views = render(trigger, facts, p)
        entry = {"project": p.pid, "level": level, "views": views, "card": None}
        if level >= 2:
            card = Canon(p).card("update", views["business"], body=views["expert"],
                                 refs={"observation": obs["id"], "trigger": trigger},
                                 payload={"observation": obs["id"], "trigger": trigger, "facts": facts,
                                          "views": views, "who": list(TRIGGERS[trigger]["who"])})
            entry["card"] = card["id"]
        obs["touched"].append(entry)
    if not obs["touched"]:
        obs["views"] = render(trigger, facts, None)
    items.append(obs)
    store.write("observations.json", items)
    store.log("observation", {"id": obs["id"], "trigger": trigger, "source": obs["source"],
                              "touched": [t["project"] for t in obs["touched"]]})
    return obs


def observations(factory) -> list:
    store = _store(factory, create=False)  # a reader never creates the factory's canon (FR-S1-AC-3)
    return (store.read("observations.json", []) or []) if store is not None else []


def apply_updates(project) -> list:
    """Record decided update cards once: a trial is approved for the operator to run; declined and
    deferred are noted. Nothing changes behaviour without that re-measure."""
    applied = set(project.read("updates_applied.json", []) or [])
    done = []
    for card in Canon(project).cards(state="decided", kind="update"):
        if card["id"] in applied:
            continue
        d = card["decision"]
        out = {"card": card["id"], "verdict": d["verdict"], "trigger": card["payload"]["trigger"]}
        if d["verdict"] == "trial":
            project.update_meta(trial={"card": card["id"], "facts": card["payload"]["facts"],
                                       "approved_by": d["person"]})
        done.append(out)
        applied.add(card["id"])
        project.write("updates_applied.json", sorted(applied))
        project.log("update_applied", out | {"person": d["person"]})
    return done
