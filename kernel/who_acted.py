"""Who acted (FR-NVL1): on every Ask Rihma answer and every run, which Rihma agent and role, which harness and model,
on this machine or hosted, and whether Gnomon's structure (the contract, its criteria, the gate) applied.

Everything here is read from the records and the routing, never from a model's own words: a round's runner and its
assurance come from the round's record (kernel/runners ``evidence_rows`` rules), a model call from its ``model_run``
in the ledger, an answer from how the assistant produced it (``by``).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")   # noqa: S104 - names a host, binds nothing
# Answers the assistant gives by rule, model or not (kernel/assistant.py and its rule modules): no model was asked.
BY_RULE = {"map", "rule", "goal", "context", "graph", "setup", "journey", "why", "triage"}
ROLE_AGENT = {"assistant": "Ask Rihma", "analyst": "Rihma's analyst", "verifier": "Rihma's verifier",
              "holdout_author": "Rihma's holdout author", "builder": "the builder cell"}


def _where_endpoint(routing: dict[str, Any], name: str | None) -> str:
    ep = (routing.get("endpoints") or {}).get(str(name or "")) or {}
    if not isinstance(ep, dict) or not ep:
        return "not recorded"
    if ep.get("kind") == "harness":
        from kernel.harness_model import HARNESSES

        hosted = HARNESSES.get(str(ep.get("harness")), {}).get("hosted") and not ep.get("private")
        return "hosted" if hosted else "on this machine"
    host = (urlsplit(str(ep.get("url") or "")).hostname or "").lower()
    local = ep.get("kind") == "ollama" or ep.get("private") is True or host in LOOPBACK
    return "on this machine" if local else "hosted"


def _enforced(factory: Any, project: Any) -> dict[str, Any]:
    from kernel import harness_enforcement as enforcement

    return enforcement.state(factory, project)


def _answer_model(routing: dict[str, Any], model: Any) -> tuple[str, str, str]:
    """The harness, model and where for an answer a model wrote."""
    from kernel import harness_model as hm

    route = hm.route_of(routing, "assistant")
    if route is not None:
        return route["label"], route.get("model") or "the model it is set to", _where_endpoint(
            routing, route.get("endpoint"))
    spec = (routing.get("roles") or {}).get("assistant") or {}
    harness = "Gnomon" if type(model).__name__ in ("GnomonModel", "AssistantModel") else "a model given to the cockpit"
    return harness, str(spec.get("model") or "not recorded"), _where_endpoint(routing, spec.get("endpoint"))


def for_answer(factory: Any, project: Any, out: dict[str, Any], model: Any = None) -> dict[str, Any]:
    """Who answered an Ask Rihma question: by rule (no model) or which model through which harness."""
    from kernel.harness_enforcement import routing_now

    st = _enforced(factory, project)
    if str(out.get("by") or "map") in BY_RULE or model is None or out.get("note"):
        return {"agent": "Ask Rihma", "role": "assistant", "how": "by rule", "harness": "Rihmasto's own rules",
                "model": "no model", "where": "on this machine",
                "gnomon": "no model call: the answer comes from the records and the cockpit's map; any action it "
                          "offers is checked against the Inbox rules and waits for your confirmation",
                "enforcement": st["said"]}
    harness, name, where = _answer_model(routing_now(), model)
    answered = (getattr(model, "last_record", None) or {}).get("model")    # the model that answered, not the route's
    name = str(answered) if answered else name                              # (FR-NVL3)
    lane = ("through Gnomon's lane: the call is in Gnomon's audit trail" if harness == "Gnomon"
            else f"answered by {harness}, not through Gnomon's lane: no Gnomon audit trail for this call")
    return {"agent": "Ask Rihma", "role": "assistant", "how": "model", "harness": harness, "model": name,
            "where": where, "gnomon": lane + "; every proposal is checked against the Inbox rules before you see it",
            "enforcement": st["said"]}


# -- runs ------------------------------------------------------------------------------------------------------------

def _criteria(project: Any) -> dict[str, list[str]]:
    contract = project.read("contract.json") or {}
    return {str(t.get("id")): list(t.get("criteria") or []) for t in contract.get("tasks") or []
            if isinstance(t, dict)}


def _then_said(then: dict[str, Any] | None) -> str:
    """The enforcement a run ran under, as its record carries it: never today's setting applied to the past."""
    if then is None:
        return "; Gnomon's enforcement when it ran is not recorded"
    return "" if then["on"] else f"; when it ran, Gnomon's enforcement was {then['said']} (the gate still ran)"


def _assurance(key: str, then: dict[str, Any] | None) -> str:
    from kernel.runners import ASSURANCE, IN_RUN

    if key == IN_RUN and then is not None and not then["on"]:
        return "Gnomon ran it without its in-run policy"
    return ASSURANCE[key]


SCRIPTED = "scripted"
STAND_IN = "a scripted stand-in answered: no model was called"


def _runner_of(cell: dict[str, Any]) -> tuple[str, str]:
    """The round's runner and its label, from the round's record (a round recorded before runners were named was
    Gnomon's); a runner Rihmasto knows is named by Rihmasto's own label."""
    from kernel.runners import DEFAULT, RUNNERS, label_of

    runner: dict[str, Any] = cell["runner"] if isinstance(cell.get("runner"), dict) else {"name": DEFAULT}
    name = str(runner.get("name") or DEFAULT)
    return name, label_of(name) if name in RUNNERS else str(runner.get("label") or name)


def _round_row(task: str, rnd: dict[str, Any], criteria: list[str], then: dict[str, Any] | None, *,
               attempt: int | None = None, rid: str | None = None) -> dict[str, Any]:
    from kernel.runners import AFTER_RUN, DEFAULT, IN_RUN

    cell = rnd.get("cell") or {}
    name, label = _runner_of(cell)
    key = IN_RUN if name == DEFAULT else AFTER_RUN           # never taken from the record's own words
    verdict = (rnd.get("gate") or {}).get("verdict") or "not run"
    structure = (f"contract criteria {', '.join(criteria) or 'none named'}; gate {verdict}; {_assurance(key, then)}"
                 + _then_said(then) + (f"; {STAND_IN}" if name == SCRIPTED else ""))
    off = then is not None and not then["on"]
    rnd_no = int(rnd.get("round") or 0)
    return {"id": rid or f"{task}/{rnd_no}", "what": f"Build {task}, attempt {attempt or rnd_no + 1}", "task": task,
            "agent": "the builder cell", "role": "builder", "harness": label, "model": _model_of(cell),
            "where": "on this machine" if name in (DEFAULT, SCRIPTED) else "as the harness runs it",
            "gnomon": structure, "applied": key == IN_RUN and not off, "opted_out": off, "gate": verdict,
            "criteria": criteria, "round": rnd_no, "at": rnd.get("at"), "seq": rnd.get("seq")}


def _model_of(cell: dict[str, Any]) -> str:
    return str(cell.get("final_model") or cell.get("model") or "not recorded")


def _round_times(project: Any) -> dict[tuple[str, int], tuple[str | None, int]]:
    """When each build attempt ran: its ``cell_ran`` record (the first of them, else its gate's) in the ledger."""
    out: dict[tuple[str, int], tuple[str | None, int]] = {}
    for r in project.ledger().of_kind("cell_ran", "gate"):
        p = r["event"].get("payload") or {}
        key = (str(p.get("task")), int(p.get("round") or 0))
        out.setdefault(key, (r["event"].get("at"), int(r["seq"])))
    return out


def _kept_round(tasks: dict[str, Any], task: str, rnd: int) -> dict[str, Any]:
    got = tasks.get(task)
    t: dict[str, Any] = got if isinstance(got, dict) else {}
    return next((x for x in t.get("rounds") or [] if isinstance(x, dict) and int(x.get("round") or 0) == rnd), {})


def _ledger_rounds(project: Any, tasks: dict[str, Any]) -> list[dict[str, Any]]:
    """Every build attempt the ledger holds, failed rounds and a retry's rounds (numbered from 0 again) included,
    each with the verdict of its own gate."""
    out: list[dict[str, Any]] = []
    waiting: dict[tuple[str, int], dict[str, Any]] = {}
    for r in project.ledger().of_kind("cell_ran", "gate"):
        ev = r["event"]
        p = ev.get("payload") or {}
        key = (str(p.get("task")), int(p.get("round") or 0))
        if ev.get("kind") == "gate":
            if key in waiting:
                waiting.pop(key)["gate"] = {"verdict": p.get("verdict")}
            continue
        kept = _kept_round(tasks, *key)
        entry = {"round": key[1], "cell": {**(kept.get("cell") or {}), **p}, "gate": kept.get("gate"),
                 "at": ev.get("at"), "seq": int(r["seq"]), "task": key[0]}
        out.append(entry)
        waiting[key] = entry
    return out


def _build_rows(project: Any, tasks: dict[str, Any], crit: dict[str, list[str]], then: Any) -> list[dict[str, Any]]:
    """Each build attempt with who acted: from the ledger, and from tasks.json for a task the ledger has no round of."""
    rows: list[dict[str, Any]] = []
    attempts: dict[str, int] = {}
    seen: dict[str, int] = {}
    ledger = _ledger_rounds(project, tasks)
    for e in ledger:
        task, base = e["task"], f"{e['task']}/{e['round']}"
        attempts[task] = attempts.get(task, 0) + 1
        seen[base] = seen.get(base, 0) + 1
        rows.append(_round_row(task, e, crit.get(task, []), then(e["at"], e["seq"]), attempt=attempts[task],
                               rid=base if seen[base] == 1 else f"{base}~{seen[base]}"))
    built, when = {e["task"] for e in ledger}, _round_times(project)
    for tid, t in sorted(tasks.items()):
        for rnd in (t.get("rounds") or []) if isinstance(t, dict) and tid not in built else []:
            at, seq = when.get((tid, int(rnd.get("round") or 0)), (None, None))
            rows.append(_round_row(tid, dict(rnd, at=at, seq=seq), crit.get(tid, []), then(at, seq)))
    return rows


def _verifier_gates(project: Any) -> dict[int, Any]:
    """The verdict of the gate each verifier answer on a task fed: the next gate on that task."""
    out: dict[int, Any] = {}
    waiting: dict[str, list[int]] = {}
    for r in project.ledger().of_kind("model_run", "gate"):
        p = r["event"].get("payload") or {}
        if r["event"].get("kind") == "gate":
            for seq in waiting.pop(str(p.get("task")), []):
                out[seq] = p.get("verdict")
        elif p.get("role") == "verifier" and p.get("task"):
            waiting.setdefault(str(p["task"]), []).append(int(r["seq"]))
    return out


def _lane_of(p: dict[str, Any], routing: dict[str, Any]) -> tuple[str, str, str, bool]:
    """(harness, where, how it ran, through Gnomon's lane) of a model call, from its own record: a coding agent's
    harness, a scripted stand-in or another runner, or Gnomon's lane."""
    harness, runner = p.get("harness"), str(p.get("runner") or "")
    if harness:
        from kernel.harness_model import HARNESSES

        label = str(p.get("label") or harness)
        where = "hosted" if HARNESSES.get(str(harness), {}).get("hosted") else "on this machine"
        return label, where, f"run by {label}, not through Gnomon's lane: no Gnomon audit trail for this call", False
    if runner and runner != "gnomon":
        said = STAND_IN if runner == SCRIPTED else f"answered by {runner}"
        return (runner, "on this machine" if runner == SCRIPTED else "not recorded",
                f"{said}; not through Gnomon's lane: no Gnomon audit trail for this call", False)
    return ("Gnomon", _where_endpoint(routing, p.get("endpoint")),
            "through Gnomon's lane: the call is in Gnomon's audit trail", True)


def _model_row(i: int, rec: dict[str, Any], routing: dict[str, Any], criteria: dict[str, list[str]],
               then: dict[str, Any] | None, gate: Any = None) -> dict[str, Any]:
    p = rec["event"]["payload"]
    role = str(p.get("role") or "model")
    task = p.get("task")
    label, where, lane, gnomon = _lane_of(p, routing)
    if task:
        lane += f"; for {task} on contract criteria {', '.join(criteria.get(str(task), [])) or 'none named'}"
    off = then is not None and not then["on"]
    if gnomon:
        lane += _then_said(then)
    return {"id": f"M-{i + 1}", "what": f"{ROLE_AGENT.get(role, role)} answered" + (f" on {task}" if task else ""),
            "task": task, "agent": ROLE_AGENT.get(role, f"Rihma's {role}"), "role": role, "harness": label,
            "model": p.get("model") or "not recorded", "where": where, "gnomon": lane,
            "applied": gnomon and not off, "opted_out": off and gnomon, "gate": gate,
            "outcome": p.get("verdict") or None, "at": rec["event"].get("at"), "seq": int(rec.get("seq") or 0)}


def runs(factory: Any, project: Any, limit: int = 200) -> list[dict[str, Any]]:
    """Every run on the project: each build attempt the ledger holds (failed rounds and a retry's included), then
    each model call, oldest first, with who acted, the gate it fed and the enforcement it ran under
    (kernel/harness_enforcement.py ``timeline``)."""
    from kernel.harness_enforcement import routing_now, timeline

    then = timeline(factory, project)
    crit = _criteria(project)
    rows = _build_rows(project, project.read("tasks.json") or {}, crit, then)
    routing, gates = routing_now(), _verifier_gates(project)
    rows += [_model_row(i, r, routing, crit, then(r["event"].get("at"), int(r["seq"])), gates.get(int(r["seq"])))
             for i, r in enumerate(project.ledger().of_kind("model_run"))]
    return rows[-limit:]
