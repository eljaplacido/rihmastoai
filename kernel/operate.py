"""Stage 7: operation. Holdout runs, probes, shadow comparison, the canary decision, rollback and
incidents (FR-H3, FR-H4, FR-H7, FR-I2).

- **Holdouts** are the scenarios the holdout author wrote (`project.holdouts_dir`). They run
  against a deployed environment over HTTP, never inside the builder's lane. A scenario's
  result keeps its first failing step with the observed status and body.
- **Probes** are `/health` plus the scenarios of kind `probe`. `tick` probes production; a
  failing probe opens one incident card per release and environment, however many ticks fail.
- **Shadow** replays the production traffic log against the current release and the candidate
  and reports every response that differs, ignoring volatile keys.
- **Canary** compares the candidate's error rate (5xx and failed probes over the replayed and
  probe sample) with the current release's, and aborts when it is higher beyond a tolerance.
- **Rollback** stops the candidate, keeps (or restores) the current release, records it and
  opens an incident card. No person is needed for it.

Results are kept under `project.path("ops")`; transitions go to the project's ledger.
"""

from __future__ import annotations

import json
import math
import re

from kernel.canon import Canon
from kernel.filelock import locked
from kernel.roads import (PavedRoads, RoadError, http_request, road_for_slot, slot_state)
from kernel.store import read_json, write_json

VOLATILE = ("id", "created", "updated", "at", "version")
# Methods replayed against a slot that holds real data. PUT and DELETE are idempotent in HTTP's
# sense, but replaying them still changes the data, so only methods that read are safe.
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
EXPECT_KEYS = ("expect_status", "expect_json", "expect_contains", "expect_not_contains", "max_ms")
_PREV = re.compile(r"\{\{\s*prev\.([A-Za-z0-9_.\-]+)\s*\}\}")


def _stamp(project) -> str:
    return project.factory.clock.stamp()


def _append(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _observed(r: dict) -> dict:
    out = {"status": r["status"], "body": r["json"] if r["is_json"] else r["text"][:2000], "ms": r["ms"]}
    if r.get("error"):
        out["error"] = r["error"]
    return out


# -- scenarios ------------------------------------------------------------------------------------

def load_scenarios(project, kinds=None) -> list:
    """The holdout custody's scenarios, optionally only those of the given kinds."""
    out = []
    folder = project.holdouts_dir
    if not folder.exists():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            doc = read_json(path)
        except json.JSONDecodeError:
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("steps"), list):
            continue
        doc.setdefault("kind", "holdout")
        doc.setdefault("criterion", path.stem)
        if kinds is None or doc["kind"] in kinds:
            out.append(doc)
    return out


class _MissingPrev(KeyError):
    pass


def _lookup(prev, dotted: str):
    value = prev
    for part in dotted.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise _MissingPrev(dotted)
    return value


def _subst(value, prev):
    """Put `{{prev.<key>}}` values from the previous step's JSON into a step. A string that is
    only the placeholder takes the value with its JSON type."""
    if isinstance(value, str):
        whole = _PREV.fullmatch(value.strip())
        if whole:
            return _lookup(prev, whole.group(1))
        return _PREV.sub(lambda m: str(_lookup(prev, m.group(1))), value)
    if isinstance(value, dict):
        return {k: _subst(v, prev) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, prev) for v in value]
    return value


def _same(a, b) -> bool:
    """JSON equality: true is not 1, but 1 is 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    return a == b


def _subset(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(any(_subset(e, a) for a in actual) for e in expected)
    return _same(expected, actual)


def _check(step: dict, r: dict) -> str | None:
    if r["status"] is None:
        return f"no answer: {r.get('error')}"
    if step.get("expect_status") is not None:
        try:
            expected = int(step["expect_status"])
        except (TypeError, ValueError):
            return f"expect_status {step['expect_status']!r} is not a status code"
        if r["status"] != expected:
            return f"status {r['status']}, expected {step['expect_status']}"
    if "expect_json" in step and (not r["is_json"] or not _subset(step["expect_json"], r["json"])):
        return "the JSON response does not hold what expect_json names"
    if step.get("expect_contains") is not None and str(step["expect_contains"]) not in r["text"]:
        return f"the response does not contain {step['expect_contains']!r}"
    if step.get("expect_not_contains") is not None and str(step["expect_not_contains"]) in r["text"]:
        return f"the response still contains {step['expect_not_contains']!r}"
    if step.get("max_ms") is not None and r["ms"] > float(step["max_ms"]):
        return f"answered in {r['ms']} ms, over the {step['max_ms']} ms limit"
    return None


def run_scenario(base_url: str, scenario: dict, *, timeout: float = 10.0) -> dict:
    """Run one scenario's steps in order. Stops at the first failing step and keeps what it saw."""
    steps = scenario.get("steps") or []
    out = {"criterion": scenario.get("criterion"), "kind": scenario.get("kind", "holdout"), "steps": len(steps),
           "trail": []}
    prev = None
    for i, raw in enumerate(steps, 1):
        request = {"method": str(raw.get("method", "GET")).upper(), "path": raw.get("path"), "body": raw.get("body")}
        try:
            step = _subst(raw, prev)
        except _MissingPrev as exc:
            return {**out, "verdict": "failed", "failed_step": i, "request": request, "observed": None,
                    "reason": f"the previous step's JSON has no {exc.args[0]!r}"}
        request = {"method": str(step.get("method", "GET")).upper(), "path": str(step.get("path", "/")),
                   "body": step.get("body")}
        r = http_request(request["method"], base_url + request["path"], request["body"], timeout=timeout)
        reason = _check(step, r)
        if reason:
            return {**out, "verdict": "failed", "failed_step": i, "request": request,
                    "expected": {k: step[k] for k in EXPECT_KEYS if k in step}, "observed": _observed(r),
                    "reason": reason}
        out["trail"].append({"step": i, "status": r["status"], "ms": r["ms"]})
        prev = r["json"] if r["is_json"] else None
    out["verdict"] = "passed" if steps else "not measured"
    return out


def run_holdouts(project, base_url: str, *, kinds=("holdout", "probe")) -> dict:
    """Every holdout scenario against one deployment. Passed only when every scenario the check
    plan expects exists and passes."""
    scenarios = load_scenarios(project, kinds)
    plan = project.read("checkplan.json") or {}
    expected = sorted({r["criterion"] for r in plan.get("checks", []) if r.get("kind") in kinds})
    missing = [c for c in expected if c not in {s["criterion"] for s in scenarios}]
    results = [run_scenario(base_url, s) for s in scenarios]
    failed = [r for r in results if r["verdict"] == "failed"]
    if failed:
        verdict = "failed"
    elif missing or any(r["verdict"] != "passed" for r in results):
        verdict = "not measured"
    elif not results:
        verdict = "not applicable"
    else:
        verdict = "passed"
    return {"verdict": verdict, "base_url": base_url, "scenarios": len(results),
            "passed": sum(1 for r in results if r["verdict"] == "passed"), "failed": len(failed),
            "missing": missing, "results": results}


# -- health and probes -----------------------------------------------------------------------------

def smoke(base_url: str, *, version: str | None = None, timeout: float = 5.0) -> dict:
    """`/health` answers 200 with status ok, from the expected version."""
    r = http_request("GET", base_url + "/health", timeout=timeout)
    body = r["json"] if isinstance(r["json"], dict) else {}
    reason = None
    if r["status"] is None:
        reason = f"no answer: {r.get('error')}"
    elif r["status"] != 200 or body.get("status") != "ok":
        reason = f"status {r['status']}"
    elif version is not None and body.get("version") != version:
        reason = f"version {body.get('version')!r} answers, expected {version!r}"
    return {"ok": reason is None, "url": base_url + "/health", "status": r["status"],
            "body": r["json"] if r["is_json"] else r["text"][:500], "ms": r["ms"], "expected_version": version,
            "reason": reason}


def _probe_round(base_url: str, version: str | None, scenarios: list) -> dict:
    health = smoke(base_url, version=version)
    results = [run_scenario(base_url, s) for s in scenarios]
    failed = (0 if health["ok"] else 1) + sum(1 for s in results if s["verdict"] != "passed")
    return {"checks": 1 + len(results), "failed": failed, "health": health, "scenarios": results}


def probe(project, env: str = "production", *, slot: str = "current", record: bool = True) -> dict:
    """Probe what runs in ``env``: `/health` (and its latency) and every probe scenario."""
    state = slot_state(project, env, slot)
    at = _stamp(project)
    if not state:
        return {"environment": env, "slot": slot, "at": at, "ok": False, "verdict": "not applicable",
                "reason": f"nothing is deployed in {env}"}
    rnd = _probe_round(state["base_url"], state["rev12"], load_scenarios(project, ("probe",)))
    result = {"environment": env, "slot": slot, "release": state["release"], "revision": state["revision"],
              "base_url": state["base_url"], "at": at, "health": rnd["health"], "scenarios": rnd["scenarios"],
              "checks": rnd["checks"], "failed": rnd["failed"], "ok": rnd["failed"] == 0,
              "verdict": "passed" if rnd["failed"] == 0 else "failed"}
    if record:
        _append(project.path("ops", "probes.jsonl"), result)
    return result


# -- shadow -------------------------------------------------------------------------------------

def differences(a, b, volatile=VOLATILE, path: str = "$") -> list:
    """Paths where two JSON values differ, ignoring keys named in ``volatile`` at any depth."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k in volatile:
                continue
            if k not in a or k not in b:
                out.append(f"{path}.{k}")
            else:
                out += differences(a[k], b[k], volatile, f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path} (length {len(a)} != {len(b)})"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += differences(x, y, volatile, f"{path}[{i}]")
        return out
    return [] if _same(a, b) else [path]


def compare_responses(cur: dict, cand: dict, volatile=VOLATILE) -> list:
    out = []
    if cur["status"] != cand["status"]:
        out.append("status")
    if cur["is_json"] and cand["is_json"]:
        out += ["body " + p for p in differences(cur["json"], cand["json"], volatile)]
    elif cur["is_json"] != cand["is_json"]:
        out.append("body (JSON on one side only)")
    elif cur["text"] != cand["text"]:
        out.append("body (text)")
    return out


def replay(records: list, *, current_url: str, candidate_url: str, safe: bool, volatile=VOLATILE) -> dict:
    """Replay recorded requests against the current release and the candidate.

    The candidate is fresh, with its own data, so it gets every request in order. When the
    current is safe to change (``safe``), so does the current, in the same order, and every
    response is compared. When it is not, a request that writes is sent only to the candidate
    (to build the same state) and its status is compared with the status the log recorded; the
    reads are replayed after the writes, against both, so both answer from the same state."""
    if safe:
        order = [(i, r, True) for i, r in enumerate(records)]
    else:
        writes = [(i, r, False) for i, r in enumerate(records) if r["method"].upper() not in SAFE_METHODS]
        reads = [(i, r, True) for i, r in enumerate(records) if r["method"].upper() in SAFE_METHODS]
        order = writes + reads
    entries = []
    for i, rec, both in order:
        method, path, body = rec["method"].upper(), rec["path"], rec.get("body")
        cand = http_request(method, candidate_url + path, body)
        entry = {"index": i, "method": method, "path": path, "body": body, "candidate": _observed(cand)}
        if both:
            cur = http_request(method, current_url + path, body)
            entry["current"] = _observed(cur)
            entry["differences"] = compare_responses(cur, cand, volatile)
        else:
            entry["current"] = None
            entry["skipped_current"] = "writes, and the current is not shadow-safe"
            entry["recorded_status"] = rec.get("status")
            entry["differences"] = ["status (against the recorded status)"] \
                if rec.get("status") is not None and rec.get("status") != cand["status"] else []
        entries.append(entry)
    differing = [e for e in entries if e["differences"]]
    return {"replayed": len(entries), "sent_to_current": sum(1 for e in entries if e["current"] is not None),
            "differing": len(differing), "differences": differing, "entries": entries}


def shadow(project, env: str = "production", *, roads=None, docker=None, az=None, release=None,
           volatile=None, limit: int = 2000) -> dict:
    """Replay the environment's recorded traffic against its current release and the candidate,
    and report every response that differs. With the road's default `shadow_target` ("twin")
    the current side is a fresh copy of the current release, so the live slot sees no replay."""
    cand, cur = slot_state(project, env, "candidate"), slot_state(project, env, "current")
    if not cand:
        raise RoadError(f"no candidate runs in {env}")
    paved = PavedRoads.load(roads if roads is not None else project.factory)
    road = road_for_slot(cand, paved, docker=docker, az=az)
    volatile = tuple(volatile or road.volatile() or VOLATILE)
    release = release if release is not None else cand["release"]
    report = {"environment": env, "release": release, "at": _stamp(project), "volatile": list(volatile),
              "candidate": {"release": cand["release"], "revision": cand["revision"], "base_url": cand["base_url"]},
              "current": None, "replayed": 0, "sent_to_current": 0, "differing": 0, "differences": [], "entries": []}
    records = None
    if not cur:
        report.update(verdict="not applicable", reason=f"no current release in {env}: nothing to compare with")
    else:
        report["current"] = {"release": cur["release"], "revision": cur["revision"], "base_url": cur["base_url"]}
        records = road_for_slot(cur, paved, docker=docker, az=az).read_traffic(project, env, "current")
        if records is None:
            report.update(verdict="not measured", reason="this road cannot read the traffic log")
        elif not records:
            report.update(verdict="not measured", reason="no traffic is recorded yet")
    if records:
        records = records[-limit:]
        twin = None
        if road.shadow_target() == "twin":
            pkg = road.package(project, env=env, slot="twin", release=cur["release"], revision=cur["revision"],
                               artifact=cur["artifact"], contract_revision=cur["package"].get("contract_revision"))
            twin = road.deploy(project, pkg)
            current_url, safe, against = twin["base_url"], True, "twin"
        else:
            current_url, safe, against = cur["base_url"], road.shadow_safe(env), "live"
        try:
            report.update(replay(records, current_url=current_url, candidate_url=cand["base_url"], safe=safe,
                                 volatile=volatile))
        finally:
            if twin is not None:
                road.stop(project, env, "twin")
        report.update(against=against, safe=safe, verdict="failed" if report["differing"] else "passed")
    write_json(project.path("ops", "shadow", f"{release}.json"), report)
    project.log("shadow", {"release": release, "environment": env, "verdict": report["verdict"],
                           "replayed": report["replayed"], "differing": report["differing"],
                           "against": report.get("against")})
    return report


# -- canary -------------------------------------------------------------------------------------

def _is_error(observed: dict | None) -> bool:
    return observed is not None and (observed["status"] is None or observed["status"] >= 500)


def canary(project, env: str = "production", *, shadow_report: dict | None = None, release=None,
           tolerance: float = 0.02, min_sample: int = 5, probe_rounds: int = 2) -> dict:
    """Promote or abort. The sample is the replayed requests plus probe rounds (as many rounds as
    the minimum sample needs). Abort when the candidate's error rate is above the current's plus
    the tolerance. With no current release, the candidate's rate is held against zero."""
    cand, cur = slot_state(project, env, "candidate"), slot_state(project, env, "current")
    if not cand:
        raise RoadError(f"no candidate runs in {env}")
    release = release if release is not None else cand["release"]
    report = shadow_report if shadow_report is not None else read_json(project.path("ops", "shadow", f"{release}.json"), {})
    entries = (report or {}).get("entries") or []
    scenarios = load_scenarios(project, ("probe",))
    per_round = 1 + len(scenarios)
    rounds = max(probe_rounds, math.ceil(max(0, min_sample - len(entries)) / per_round))

    def side(state, key):
        replayed = [e[key] for e in entries if e.get(key) is not None]
        probes = [_probe_round(state["base_url"], state["rev12"], scenarios) for _ in range(rounds)] if state else []
        n = len(replayed) + sum(p["checks"] for p in probes)
        errors = sum(1 for o in replayed if _is_error(o)) + sum(p["failed"] for p in probes)
        return {"release": state["release"] if state else None, "replayed": len(replayed),
                "replay_errors": sum(1 for o in replayed if _is_error(o)), "probe_checks": sum(p["checks"] for p in probes),
                "probe_failures": sum(p["failed"] for p in probes), "sample": n, "errors": errors,
                "error_rate": round(errors / n, 4) if n else 0.0}

    c, b = side(cand, "candidate"), side(cur, "current")
    if c["sample"] < min_sample:
        decision, why = "abort", f"the sample ({c['sample']}) is below the minimum ({min_sample})"
    elif c["error_rate"] > b["error_rate"] + tolerance:
        decision, why = "abort", (f"the candidate's error rate {c['error_rate']} is above the current's "
                                  f"{b['error_rate']} + {tolerance}")
    else:
        decision, why = "promote", (f"the candidate's error rate {c['error_rate']} is within {tolerance} of "
                                    f"the current's {b['error_rate']}")
    result = {"environment": env, "release": release, "at": _stamp(project), "decision": decision, "reason": why,
              "tolerance": tolerance, "min_sample": min_sample, "probe_rounds": rounds,
              "candidate": c, "current": b}
    write_json(project.path("ops", "canary", f"{release}.json"), result)
    project.log("canary", {"release": release, "environment": env, "decision": decision,
                           "candidate_rate": c["error_rate"], "current_rate": b["error_rate"],
                           "sample": c["sample"]})
    return result


# -- rollback and incidents -----------------------------------------------------------------------

def open_incident(project, *, release, env: str, title: str, body: str = "", payload: dict | None = None) -> dict:
    """One incident card per release and environment: a repeat adds an occurrence to it."""
    with locked(project.path("ops", ".incidents.lock")):
        path = project.path("ops", "incidents.json")
        incidents = read_json(path, {}) or {}
        key = f"{release}:{env}"
        entry = incidents.get(key)
        if entry:
            entry["occurrences"] += 1
            entry["last"] = _stamp(project)
            entry["new"] = False
        else:
            card = Canon(project).card("incident", title, body=body,
                                       refs={"release": release, "environment": env},
                                       payload=dict(payload or {}), blocking=True)
            entry = {"card": card["id"], "release": release, "environment": env, "title": title,
                     "opened": _stamp(project), "last": _stamp(project), "occurrences": 1, "new": True}
            project.log("incident_opened", {"card": card["id"], "release": release, "environment": env})
        incidents[key] = entry
        write_json(path, incidents)
        return dict(entry)


def rollback(project, env: str = "production", *, release, reason: str, roads=None, docker=None, az=None,
             restore: dict | None = None, evidence: dict | None = None) -> dict:
    """Stop the candidate (and any twin), keep the current release, or restore ``restore`` (a
    slot state) if the current no longer serves it. Records the rollback and opens an incident."""
    paved = PavedRoads.load(roads if roads is not None else project.factory)
    stopped = []
    for slot in ("candidate", "twin"):
        state = slot_state(project, env, slot)
        if state:
            road_for_slot(state, paved, docker=docker, az=az).stop(project, env, slot)
            stopped.append({"slot": slot, "release": state["release"], "revision": state["revision"]})
    cur, restored = slot_state(project, env, "current"), None
    if restore and (cur is None or cur.get("revision") != restore["revision"]):
        cur = road_for_slot(restore, paved, docker=docker, az=az).deploy(project, restore["package"])
        restored = {"release": cur["release"], "revision": cur["revision"]}
    health = smoke(cur["base_url"], version=cur["rev12"]) if cur else None
    record = {"release": release, "environment": env, "reason": reason, "at": _stamp(project),
              "by": "factory: automatic rollback, no person involved", "stopped": stopped, "restored": restored,
              "kept": {"release": cur["release"], "revision": cur["revision"]} if cur else None,
              "current_health": health, "evidence": evidence or {}}
    _append(project.path("ops", "rollbacks.jsonl"), record)
    project.log("rolled_back", {"release": release, "environment": env, "reason": reason,
                                "kept": record["kept"], "restored": restored})
    kept = f"release {cur['release']} keeps serving {env}" if cur else f"nothing serves {env}"
    incident = open_incident(project, release=release, env=env, title=f"Release {release} was rolled back in {env}",
                             body=f"{reason}\n\nThe factory stopped the candidate; {kept}.",
                             payload={"rollback": {k: record[k] for k in ("reason", "stopped", "kept", "restored")}})
    record["incident"] = incident["card"]
    return record


def tick(project, *, roads=None, docker=None, az=None) -> dict:
    """One round of operation: probe production. A failing probe opens (or adds to) the incident
    card for that release and environment. The result is kept in `ops/tick.json`."""
    results, incidents = [], []
    for env in ("production",):
        state = slot_state(project, env, "current")
        if not state:
            results.append({"environment": env, "verdict": "not applicable", "reason": f"nothing is deployed in {env}"})
            continue
        res = probe(project, env)
        if not res["ok"]:
            why = res["health"]["reason"] or "; ".join(
                f"{s['criterion']}: {s.get('reason')}" for s in res["scenarios"] if s["verdict"] != "passed")
            inc = open_incident(project, release=state["release"], env=env,
                                title=f"Probe failing for release {state['release']} in {env}",
                                body=f"{res['failed']} of {res['checks']} probe checks failed: {why}",
                                payload={"probe": {"health": res["health"], "failed": res["failed"],
                                                   "checks": res["checks"]}})
            res["incident"] = inc["card"]
            incidents.append(inc)
            if inc["new"]:
                project.log("probe_failed", {"release": state["release"], "environment": env, "card": inc["card"]})
        results.append(res)
    summary = {"at": _stamp(project), "probes": results, "incidents": incidents}
    write_json(project.path("ops", "tick.json"), summary)
    return summary
