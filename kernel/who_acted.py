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


def _round_row(task: str, rnd: dict[str, Any], criteria: list[str], then: dict[str, Any] | None) -> dict[str, Any]:
    from kernel.runners import AFTER_RUN, DEFAULT, IN_RUN, label_of

    cell = rnd.get("cell") or {}
    runner: dict[str, Any] = cell["runner"] if isinstance(cell.get("runner"), dict) else {"name": DEFAULT}
    name = str(runner.get("name") or DEFAULT)
    key = IN_RUN if name == DEFAULT else AFTER_RUN           # never taken from the record's own words
    gate = rnd.get("gate") or {}
    verdict = gate.get("verdict") or "not run"
    structure = (f"contract criteria {', '.join(criteria) or 'none named'}; gate {verdict}; {_assurance(key, then)}"
                 + _then_said(then))
    off = then is not None and not then["on"]
    return {"id": f"{task}/{rnd.get('round', 0)}", "what": f"Build {task}, attempt {int(rnd.get('round') or 0) + 1}",
            "task": task, "agent": "the builder cell", "role": "builder", "harness": label_of(name),
            "model": cell.get("final_model") or cell.get("model") or "not recorded",
            "where": "on this machine" if name == DEFAULT else "as the harness runs it", "gnomon": structure,
            "applied": key == IN_RUN and not off, "opted_out": off, "gate": verdict, "criteria": criteria}


def _round_times(project: Any) -> dict[tuple[str, int], tuple[str | None, int]]:
    """When each build attempt ran: its ``cell_ran`` record (the first of them, else its gate's) in the ledger."""
    out: dict[tuple[str, int], tuple[str | None, int]] = {}
    for r in project.ledger().of_kind("cell_ran", "gate"):
        p = r["event"].get("payload") or {}
        key = (str(p.get("task")), int(p.get("round") or 0))
        out.setdefault(key, (r["event"].get("at"), int(r["seq"])))
    return out


def _model_row(i: int, rec: dict[str, Any], routing: dict[str, Any], criteria: dict[str, list[str]],
               then: dict[str, Any] | None) -> dict[str, Any]:
    p = rec["event"]["payload"]
    role = str(p.get("role") or "model")
    harness = p.get("harness")
    task = p.get("task")
    if harness:
        from kernel.harness_model import HARNESSES

        label = str(p.get("label") or harness)
        lane = f"run by {label}, not through Gnomon's lane: no Gnomon audit trail for this call"
        where = "hosted" if HARNESSES.get(str(harness), {}).get("hosted") else "on this machine"
    else:
        label, where = "Gnomon", _where_endpoint(routing, p.get("endpoint"))
        lane = "through Gnomon's lane: the call is in Gnomon's audit trail"
    if task:
        lane += f"; for {task} on contract criteria {', '.join(criteria.get(str(task), [])) or 'none named'}"
    off = then is not None and not then["on"]
    if not harness:
        lane += _then_said(then)
    return {"id": f"M-{i + 1}", "what": f"{ROLE_AGENT.get(role, role)} answered" + (f" on {task}" if task else ""),
            "task": task, "agent": ROLE_AGENT.get(role, f"Rihma's {role}"), "role": role, "harness": label,
            "model": p.get("model") or "not recorded", "where": where, "gnomon": lane,
            "applied": not harness and not off, "opted_out": off and not harness, "gate": p.get("verdict") or None,
            "at": rec["event"].get("at")}


def runs(factory: Any, project: Any, limit: int = 200) -> list[dict[str, Any]]:
    """Every run on the project, newest last: each builder round and each model call, with who acted and the
    enforcement it ran under (kernel/harness_enforcement.py ``timeline``)."""
    from kernel.harness_enforcement import routing_now, timeline

    then = timeline(factory, project)
    when = _round_times(project)
    crit = _criteria(project)
    tasks = project.read("tasks.json") or {}
    rows = [_round_row(tid, rnd, crit.get(tid, []), then(*when.get((tid, int(rnd.get("round") or 0)), (None, None))))
            for tid, t in sorted(tasks.items()) if isinstance(t, dict)
            for rnd in t.get("rounds") or [] if isinstance(rnd, dict)]
    routing = routing_now()
    rows += [_model_row(i, r, routing, crit, then(r["event"].get("at"), int(r["seq"])))
             for i, r in enumerate(project.ledger().of_kind("model_run"))]
    return rows[-limit:]
