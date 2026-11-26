"""Rihmasto's own evals of its agents: one eval set per Rihma role, to compare models and endpoints (FR-EVL1).

    rihmasto evals roles [--role analyst|assistant] [--model configured|<model>@<endpoint> ...] --person P --persona X

| Set | Role | What a good answer has (judged by rule, kernel/role_evals_fixtures.py) |
|---|---|---|
| intake_questions | analyst | a few distinct questions on a need, with proposed answers and options, on what matters |
| spec_testability | analyst | criteria for a requirement: given, when, then, an observable outcome, no vague words |
| ask_answers | assistant | Ask Rihma on a fixed snapshot: where things are, how things stand, how to do something |
| goal_plans | assistant | goal help's plan: steps of known kinds, routes and controls the cockpit has, plain commands |

Each case asks the role through the same prompt the feature uses (intake's panel prompt, Ask Rihma's prompt, goal
help's prompt; the spec set uses a short criteria prompt in the spec's shape) with neutral fixtures, never a
project's material. A **candidate** is the configured model of the role, its fallback, or ``<model>@<endpoint>`` of
the routing (a harness endpoint too, FR-HMD1); each is asked through its own Gnomon lane. Results are kept in the
factory's canon (``evals/roles.json``) and recorded per set and candidate as ``role_eval_ran``: the score and how
many cases were right, never a prompt or an answer. Models setup shows them ("on our evals, model A answers how-to
questions correctly 92% vs model B 71%"). Compared for a confidential project (``for_project``), a hosted candidate
is refused, recorded, and nothing is sent.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

from kernel import role_evals_fixtures as fx
from kernel.model import Model, ModelError, extract_json

SETS: dict[str, dict[str, str]] = {
    "intake_questions": {"role": "analyst", "label": "Intake panel questions", "what": "questions quality on needs"},
    "spec_testability": {"role": "analyst", "label": "Spec criteria testability", "what": "testable criteria"},
    "ask_answers": {"role": "assistant", "label": "Ask Rihma answers", "what": "map, status and how-to answers"},
    "goal_plans": {"role": "assistant", "label": "Goal help plans", "what": "valid plan steps"},
}
ROLES = ("analyst", "assistant")
ENABLERS = ("developer", "it", "operations", "compliance", "product_owner")
MAX_RUNS = 400
Emit = Callable[[str], None]


# -- the cases ---------------------------------------------------------------------------------------------------

def _intake(case: dict[str, Any]) -> str:
    from kernel.intake import _perspective_prompt

    return _perspective_prompt("business", case["text"], "text", "demo")


def _judge_intake(case: dict[str, Any], raw: Any) -> list[str]:
    from kernel.intake import QUESTIONS_PER_PERSPECTIVE

    qs = raw.get("questions") if isinstance(raw, dict) else None
    if not isinstance(qs, list) or not qs:
        return ["no questions"]
    texts = [str(q.get("text") or "").strip() for q in qs if isinstance(q, dict)]
    said = " ".join(texts).lower()
    rules = (("too many questions", len(qs) <= QUESTIONS_PER_PERSPECTIVE["demo"]),
             ("a question is not a question", all(t.endswith("?") for t in texts)),
             ("duplicate questions", len({t.lower() for t in texts}) == len(texts)),
             ("a question lacks its proposed answer or options", all(_offered(q) for q in qs)),
             ("touches nothing that matters for the need", any(t in said for t in case["topics"])))
    return [why for why, held in rules if not held]


def _offered(q: Any) -> bool:
    return isinstance(q, dict) and bool(q.get("proposed_answer")) and len(q.get("options") or []) >= 2


def _spec(case: dict[str, Any]) -> str:
    return ("You are the analyst. Write two to four acceptance criteria for this requirement, each one a person or a "
            "test can check.\n\nThe requirement:\n<<<\n" + case["text"] + "\n>>>\n\nAnswer with this JSON in a ```json "
            'block: {"criteria": [{"given": "...", "when": "...", "then": "...", "check": {"kind": "test"}}]}\n')


def _judge_spec(case: dict[str, Any], raw: Any) -> list[str]:
    crit = raw.get("criteria") if isinstance(raw, dict) else None
    if not isinstance(crit, list) or not crit:
        return ["no criteria"]
    failed = []
    for n, c in enumerate(crit, 1):
        if not isinstance(c, dict) or not all(str(c.get(k) or "").strip() for k in ("given", "when", "then")):
            failed.append(f"criterion {n} lacks given, when or then")
            continue
        then = str(c["then"]).lower()
        if any(re.search(rf"\b{re.escape(v)}\b", then) for v in fx.VAGUE):
            failed.append(f"criterion {n}'s outcome is vague")
        elif not any(re.search(p, then) for p in fx.OBSERVABLE):
            failed.append(f"criterion {n}'s outcome is not observable")
    return failed


def _ask(case: dict[str, Any]) -> str:
    from kernel.assistant import find_in_map, prompt

    return prompt(case["q"], fx.SNAPSHOT, persona="product_owner", view=None, hints=find_in_map(case["q"]))


def _judge_ask(case: dict[str, Any], raw: Any) -> list[str]:
    if not isinstance(raw, dict) or not str(raw.get("answer") or "").strip():
        return ["no answer"]
    text = str(raw["answer"]).lower()
    got = raw.get("navigate")
    nav: dict[str, Any] = got if isinstance(got, dict) else {}
    route, control = str(nav.get("route") or ""), str(nav.get("control") or "")
    if case["kind"] == "status":
        return [] if any(f in text for f in case["figures"]) else ["the figure in the snapshot is not in the answer"]
    hit = (any(route.endswith(e) for e in case.get("route_ends", ())) or control in case.get("controls", ())
           or any(w in text for w in case.get("words", ())))
    return [] if hit else ["it does not lead to the right place"]


def _goal(case: dict[str, Any], factory: Any) -> str:
    from kernel.copilot import prompt
    from kernel.copilot_catalog import catalogue

    return prompt(case["goal"], fx.FACTS, catalogue(factory, None), {"steps": []})


def _route_shape(route: str) -> bool:
    from kernel.assistant_rules import ui_map

    return any(re.fullmatch(re.escape(v["route"]).replace(re.escape("{pid}"), "[a-z0-9_-]+"), route)
               for v in ui_map()["views"])


def _step_fault(s: Any, controls: set[str]) -> str | None:
    """Why one plan step is not one the cockpit can take, or None."""
    from kernel.copilot_steps import STEP_KINDS

    a = s.get("action") if isinstance(s, dict) else None
    if not isinstance(a, dict) or a.get("kind") not in STEP_KINDS or not str(s.get("title") or "").strip():
        return "is not a known kind of step"
    if a.get("route") and not _route_shape(str(a["route"])):
        return "has a route that is not the cockpit's"
    if a.get("control") and a["control"] not in controls:
        return "has a control that is not the cockpit's"
    cmd = str(a.get("command") or "")
    if cmd and (not cmd.startswith("rihmasto ") or re.search(r"[;&|`$<>\n]", cmd)):
        return "has a command that is not a plain rihmasto command"
    return None


def _judge_goal(case: dict[str, Any], raw: Any) -> list[str]:
    from kernel.assistant_rules import ui_map

    steps = raw.get("steps") if isinstance(raw, dict) else None
    if not isinstance(steps, list) or not steps:
        return ["no steps"]
    controls = {c["id"] for c in ui_map()["controls"]}
    return [f"step {n} {why}" for n, s in enumerate(steps, 1) if (why := _step_fault(s, controls))]


def cases(name: str, factory: Any) -> list[tuple[str, str, Callable[[Any], list[str]]]]:
    """(case id, prompt, judge) for one set."""
    from functools import partial

    if name == "intake_questions":
        return [(c["id"], _intake(c), partial(_judge_intake, c)) for c in fx.NEEDS]
    if name == "spec_testability":
        return [(c["id"], _spec(c), partial(_judge_spec, c)) for c in fx.REQUIREMENTS]
    if name == "ask_answers":
        return [(c["id"], _ask(c), partial(_judge_ask, c)) for c in fx.QUESTIONS]
    if name == "goal_plans":
        return [(c["id"], _goal(c, factory), partial(_judge_goal, c)) for c in fx.GOALS]
    raise ValueError(f"an eval set is one of {', '.join(SETS)}, got {name!r}")


# -- the candidates ---------------------------------------------------------------------------------------------

def candidates(role: str, wanted: list[str] | None = None, routing: dict[str, Any] | None = None) -> list[dict]:
    """The models compared for ``role``: the configured one and its fallback, or those named."""
    from kernel.confidential import is_local
    from kernel.lanes import read_routing

    routing = routing if routing is not None else (read_routing() or {"roles": {}, "endpoints": {}})
    spec = (routing.get("roles") or {}).get(role)
    if not isinstance(spec, dict):
        raise ValueError(f"the routing has no {role} role")
    picks = []
    for w in wanted or ["configured", *(["fallback"] if spec.get("fallback") else [])]:
        if w == "configured":
            model, ep = spec["model"], spec["endpoint"]
        elif w == "fallback" and spec.get("fallback"):
            model, ep = spec["fallback"]["model"], spec["fallback"]["endpoint"]
        elif "@" in w:
            model, ep = w.rsplit("@", 1)
        else:
            raise ValueError(f"a candidate is configured, fallback or <model>@<endpoint>, got {w!r}")
        endpoint = (routing.get("endpoints") or {}).get(ep)
        if not isinstance(endpoint, dict):
            raise ValueError(f"the routing has no endpoint {ep!r}")
        picks.append({"id": f"{model}@{ep}", "role": role, "model": model, "endpoint": ep,
                      "local": is_local(endpoint.get("url"), endpoint), "kind": endpoint.get("kind", "openai")})
    return picks


def lane_model(cand: dict[str, Any]) -> Model:
    """A Gnomon model in a lane of its own where ``cand`` answers the role."""
    from kernel.lanes import ensure_analyst_lane, lanes_root, read_routing
    from kernel.model import GnomonModel
    from kernel.models_setup import family_of

    routing = copy.deepcopy(read_routing() or {})
    routing["roles"][cand["role"]] = {"model": cand["model"], "endpoint": cand["endpoint"]}
    routing.setdefault("models", {}).setdefault(cand["model"], {"family": family_of(cand["model"])})
    slug = re.sub(r"[^a-z0-9-]+", "-", cand["id"].lower()).strip("-")[:60]
    return GnomonModel(ensure_analyst_lane(routing, root=lanes_root() / "evals" / slug), timeout=300)


# -- running ------------------------------------------------------------------------------------------------------

def _score(model: Model, name: str, role: str, factory: Any, emit: Emit) -> dict[str, Any]:
    rows = []
    for cid, text, judge in cases(name, factory):
        try:
            failed = judge(extract_json(model.ask(text, role=role)))
        except (ModelError, OSError, RuntimeError, ValueError) as exc:
            failed = [f"no usable answer ({type(exc).__name__})"]
        rows.append({"case": cid, "passed": not failed, "failed": failed[:3]})
        emit(f"  {cid}: {'right' if not failed else 'wrong: ' + '; '.join(failed[:2])}")
    right = sum(1 for r in rows if r["passed"])
    return {"cases": len(rows), "correct": right, "score_pct": round(right / len(rows) * 100, 1) if rows else None,
            "rows": rows}


def _refuse(fp: Any, secret: Any, cand: dict[str, Any], names: list[str], person: str, persona: str,
            emit: Emit) -> list[dict[str, Any]]:
    """A hosted candidate compared for a confidential project: never asked, the refusal recorded."""
    emit(f"{cand['id']}: refused, {secret.pid} is confidential and {cand['endpoint']} is hosted")
    secret.log("confidential_refused", {"where": "role evals", "hosted": [
        {"role": cand["role"], "which": "candidate", "endpoint": cand["endpoint"]}]})
    return [_keep(fp, n, cand, None, person, persona, refused="confidential") for n in names]


def _confidential(factory: Any, pid: str | None) -> Any:
    """The project the comparison is for, when it is confidential; else None."""
    from kernel.confidential import confidential

    target = factory.project(pid) if pid else None
    return target if target is not None and confidential(target) else None


def _compare(fp: Any, cand: dict[str, Any], names: list[str], model: Model, person: str, persona: str,
             emit: Emit) -> list[dict[str, Any]]:
    out = []
    for n in names:
        emit(f"{SETS[n]['label']} with {cand['id']}")
        out.append(_keep(fp, n, cand, _score(model, n, cand["role"], fp.factory, emit), person, persona))
    return out


def _allowed(person: str, persona: str, role: str | None) -> None:
    from kernel.gnomon_evals_run import EvalsRefused
    from kernel.people import PERSONAS, is_person

    if not is_person(person) or persona not in PERSONAS or persona not in ENABLERS:
        raise EvalsRefused(f"role evals are run by a named person as {', '.join(ENABLERS)}")
    if role is not None and role not in ROLES:
        raise ValueError(f"a role with an eval set is one of {', '.join(ROLES)}")


def run(factory: Any, *, person: str, persona: str, role: str | None = None, models: list[str] | None = None,
        sets: list[str] | None = None, model_for: Callable[[dict[str, Any]], Model] | None = None,
        for_project: str | None = None, emit: Emit = lambda _: None) -> dict[str, Any]:
    """Run the eval sets of ``role`` (or both roles) for each candidate, record and keep each result."""
    from kernel.learn import factory_project
    from kernel.store import updating_json

    _allowed(person, persona, role)
    names = sets or [n for n, s in SETS.items() if role in (None, s["role"])]
    secret = _confidential(factory, for_project)
    fp, out = factory_project(factory), []
    for r in sorted({SETS[n]["role"] for n in names}):
        mine = [n for n in names if SETS[n]["role"] == r]
        for cand in candidates(r, models):
            if secret is not None and not cand["local"]:
                out += _refuse(fp, secret, cand, mine, person, persona, emit)
            else:
                out += _compare(fp, cand, mine, (model_for or lane_model)(cand), person, persona, emit)
    with updating_json(fp.path("evals", "roles.json"), {"runs": []}) as kept:
        kept["runs"] = (kept.get("runs") or []) + out
        kept["runs"] = kept["runs"][-MAX_RUNS:]
    return {"runs": out, "lines": lines(out)}


def _keep(fp: Any, name: str, cand: dict[str, Any], scored: dict[str, Any] | None, person: str, persona: str,
          refused: str | None = None) -> dict[str, Any]:
    row = {"set": name, "role": cand["role"], "candidate": cand["id"], "model": cand["model"],
           "endpoint": cand["endpoint"], "local": cand["local"], "at": fp.factory.clock.stamp(),
           "by": {"person": person, "persona": persona}, **({"refused": refused} if refused else {}),
           **(scored or {"cases": 0, "correct": 0, "score_pct": None, "rows": []})}
    kept = {k: row[k] for k in ("set", "role", "candidate", "model", "endpoint", "local", "cases", "correct",
                                "score_pct")}
    fp.log("role_eval_ran", kept | {"person": person, "persona": persona, **({"refused": refused} if refused else {})})
    from kernel.heal_evals import role_eval_failed  # wrong answers open an incident with them (FR-HEAL1)

    opened = role_eval_failed(fp.factory, row)
    return row | ({"incident": opened["id"]} if opened else {})


def latest(factory: Any) -> list[dict[str, Any]]:
    """The latest result of each set and candidate, as Models setup shows them."""
    from kernel.learn import factory_project

    fp = factory_project(factory, create=False)
    runs = (fp.read("evals/roles.json", {}) or {}).get("runs", []) if fp is not None else []
    last: dict[tuple[str, str], dict[str, Any]] = {}
    for r in runs:
        last[(r["set"], r["candidate"])] = r
    return [{k: v for k, v in r.items() if k != "rows"} for r in last.values()]


def lines(rows: list[dict[str, Any]]) -> list[str]:
    """One sentence per set compared across candidates: "on our evals, A answers ... 92% vs B 71%"."""
    out = []
    for name, s in SETS.items():
        scored = sorted((r for r in rows if r["set"] == name and r.get("score_pct") is not None),
                        key=lambda r: -r["score_pct"])
        if not scored:
            continue
        said = " vs ".join(f"{r['model']} ({r['endpoint']}) {r['score_pct']:g}%" for r in scored)
        out.append(f"On our evals, {s['label'].lower()} ({s['what']}): {said}.")
    return out


def request(factory: Any, *, person: str, persona: str, role: str | None = None, models: list[str] | None = None,
            for_project: str | None = None) -> dict[str, Any]:
    """A signed request to run the role evals, recorded in the factory's canon; the cockpit's job carries it out."""
    from kernel.learn import factory_project
    from kernel.store import updating_json

    _allowed(person, persona, role)
    for r in [role] if role else ROLES:
        candidates(r, models or None)                 # a candidate the routing does not have is refused now
    fp = factory_project(factory)
    with updating_json(fp.path("evals", "requests.json"), {}) as kept:
        rid = f"RR-{len(kept) + 1:04d}"
        kept[rid] = {"kind": "roles", "role": role, "models": models or [], "for_project": for_project,
                     "person": person, "persona": persona, "at": factory.clock.stamp(), "state": "requested"}
    fp.log("role_eval_requested", {"request": rid, "role": role, "models": models or [], "person": person,
                                   "persona": persona})
    return {"request": rid, "role": role}


def carry(factory: Any, rid: str, emit: Emit = lambda _: None) -> dict[str, Any]:
    from kernel.learn import factory_project
    from kernel.store import updating_json

    fp = factory_project(factory)
    with updating_json(fp.path("evals", "requests.json"), {}) as kept:
        req = kept.get(rid)
        if req is None or req.get("kind") != "roles":
            raise KeyError(f"no role eval request {rid}")
        if req.get("state") != "requested":
            raise ValueError(f"{rid} was already carried out ({req.get('state')})")
        req["state"] = "running"
    try:
        return run(factory, person=req["person"], persona=req["persona"], role=req.get("role"),
                   models=req.get("models") or None, for_project=req.get("for_project"), emit=emit)
    finally:
        with updating_json(fp.path("evals", "requests.json"), {}) as kept:
            kept[rid]["state"] = "done"


def view(factory: Any) -> dict[str, Any]:
    rows = latest(factory)
    return {"sets": [{"id": k, **v} for k, v in SETS.items()], "results": rows, "lines": lines(rows),
            "roles": list(ROLES)}
