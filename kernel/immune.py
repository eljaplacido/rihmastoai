"""Immune memory: what fixes a failure Rihmasto has seen before (FR-HEAL1, D-0024 item 1).

Two kinds of remedy answer an incident (kernel/incidents.py):

- **built-in** remedies for the classes of failure Rihmasto knows (``CLASSES``): a product that is not running
  ("Start it on its road", "Why it is not running"), a model endpoint that does not answer (Models setup, or the
  coding agent you already have), a folder outside the allowed roots (how to allow it), a hosted role on a
  confidential project (use a local model), a job lost on a restart (run it again), a tool a check needs that is
  missing (how to install it: the check stays not measured until then), a failed job, a view or a request that
  broke (try again);
- **learned** remedies: when an incident is resolved (a person's action, a retry that worked, an agent's fix) its
  fingerprint and what resolved it are proposed as a remedy for next time. A person approves it once, signed (the
  approval records a hash of the remedy it approved); from then on it is offered first ("Rihmasto has seen this
  before: last time ... fixed it"), and applied on its own only when it is **safe**: a read-only or idempotent
  action (opening a view, trying a read again, an explanation, an investigation). Anything that changes code,
  policy or state stays a proposal a person confirms each time. A remedy can be retired; every use is counted and
  recorded.

The remedies live in ``heal/remedies.json`` under the factory home; their proposals, approvals, uses and
retirements are recorded in the factory's ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from kernel.people import PERSONAS, is_person
from kernel.store import Factory, read_json, updating_json

APPROVERS = ("it", "developer", "operations", "product_owner", "business_owner")
STATES = ("proposed", "approved", "retired")
# Actions that only read or can be repeated without changing anything: the only ones applied on their own.
SAFE_KINDS = ("link", "explain", "investigate", "retry_read")
ACTION_KINDS = ("link", "explain", "investigate", "retry_read", "retry", "retry_job", "api", "fix", "config")


def _a(aid: str, label: str, kind: str, **more: Any) -> dict[str, Any]:
    return {"id": aid, "label": label, "kind": kind, "safe": kind in SAFE_KINDS, **more}


INVESTIGATE = _a("investigate", "Investigate with Rihma", "investigate",
                 why="A Rihma agent reads the incident's context and the records, says what it thinks happened and "
                     "proposes the next step.")
TRY_AGAIN = _a("try_again", "Try again", "retry_read", why="Read the view again: most passing failures clear.")
RUN_AGAIN = _a("run_again", "Run it again", "retry_job",
               why="Start the same job again with the same request. Nothing it already recorded is repeated.")


def _match(*patterns: str, kinds: tuple[str, ...] = (), wheres: tuple[str, ...] = (),
           only: tuple[str, ...] = ()) -> Any:
    """A class's test: one of ``kinds`` always matches; otherwise every pattern must be found in the incident's
    message, error class, words or job log, where ``wheres`` (when given) and among the kinds ``only`` names."""
    found = [re.compile(p, re.I) for p in patterns]

    def test(doc: dict[str, Any]) -> bool:
        kind, where = doc.get("kind"), str(doc.get("where") or "")
        if kind in kinds:
            return True
        allowed = (not only or kind in only) and (not wheres or any(w in where for w in wheres))
        return allowed and bool(found) and all(p.search(_said(doc)) for p in found)
    return test


def _said(doc: dict[str, Any]) -> str:
    """What an incident says: its message, error class, a person's words and a job's log tail."""
    job = (doc.get("context") or {}).get("job") or {}
    return " ".join([*(str(doc.get(k) or "") for k in ("message", "error_class", "words")),
                     *(str(x) for x in job.get("log_tail") or [])])


CLASSES: list[dict[str, Any]] = [
    {"id": "product_not_running", "title": "The product is not running", "classification": "user setup",
     "explain": "The release's environment was stopped or never started, so its address does not answer.",
     "match": _match(r"nothing runs there|not running|was stopped|connection refused",
                     kinds=("product_not_running",), wheres=("try", "release", "outputs", "live")),
     "remedies": [_a("start_on_road", "Start it on its road", "api", method="POST", path="/api/projects/{pid}/advance",
                     why="Run the project's delivery step again: it starts the release on its paved road."),
                  _a("why_not_running", "Why it is not running", "investigate",
                     why="A Rihma agent reads the release's slot, the last delivery and the probes.")]},
    {"id": "hosted_on_confidential", "title": "A confidential project refused a hosted model",
     "classification": "user setup",
     "explain": "This project is confidential, so its material never goes to a hosted model.",
     "match": _match(r"confidential", r"hosted|local or private|nothing was sent", kinds=("confidential_refused",)),
     "remedies": [_a("use_local_model", "Use my local model", "link", href="#/models",
                     why="Set the role to a local or private endpoint in Models setup.")]},
    {"id": "model_unreachable", "title": "A model endpoint did not answer", "classification": "external",
     "explain": "The model a role uses did not answer: its endpoint is down, unreachable or not set up.",
     "match": _match(r"model|endpoint|apparatus|gnomon|analyst|assistant role",
                     r"unreachable|refused|timed? ?out|did not answer|no answer|gave no|not set up|apparatus failure|"
                     r"connection"),
     "remedies": [_a("models_setup", "Open Models setup", "link", href="#/models",
                     why="Test each role's endpoint, set a key, or choose another endpoint."),
                  _a("use_coding_agent", "Use the coding agent you already have", "link", href="#/models",
                     why="Claude Code, Codex or OpenCode can answer the text roles with your own login.")]},
    {"id": "folder_outside_roots", "title": "That folder is outside the folders the cockpit may read",
     "classification": "user setup",
     "explain": "The cockpit reads folders under your home folder or the roots the operator configured.",
     "match": _match(r"outside your home folder|RIHMASTO_SOURCE_ROOTS|system folder"),
     "remedies": [_a("allow_folder", "Allow it", "explain",
                     text="Add the folder, or a folder above it, to RIHMASTO_SOURCE_ROOTS where the cockpit runs "
                          "(folders separated by the system's path separator), then start the cockpit again. It is "
                          "the operator's setting: Rihmasto never widens it on its own.",
                     command="RIHMASTO_SOURCE_ROOTS=<the folder>  python -m cockpit.server --home <home>")]},
    {"id": "job_lost", "title": "A job was lost when the cockpit restarted", "classification": "user setup",
     "explain": "The cockpit keeps its jobs in memory: a restart forgets the ones that were running.",
     "match": _match(r"lost on (?:a )?restart|unknown job", kinds=("job_lost",)), "remedies": [RUN_AGAIN]},
    {"id": "tool_missing", "title": "A tool a check needs is not installed", "classification": "user setup",
     "explain": "The check could not run its tool, so it is marked not measured: never passed.",
     "match": _match(r"not installed|not found on (?:the )?path|command not found|is not recognized|no such file or "
                     r"directory|missing tool|tool .{0,40} not found",
                     only=("check_failed", "job_failed", "runner_failed", "automation_failed", "action_failed",
                           "report")),
     "not_measured": True,
     "remedies": [_a("install_tool", "How to install it", "explain",
                     text="Install the tool on the machine the cockpit runs on (the check's own page names it), then "
                          "run the check again. Until then the check says not measured, never passed.")]},
    {"id": "job_failed", "title": "A background job failed", "classification": "unknown",
     "explain": "The job's process ended with an error. Its log's last lines are in the incident.",
     "match": _match(kinds=("job_failed",)),
     "remedies": [RUN_AGAIN, _a("open_jobs", "Open the job's log", "link", href="#/jobs",
                                why="The Jobs page shows the whole log.")]},
    # Agent observability (FR-OBS1) and Gnomon's audits and the role evals (FR-EVL1), kernel/heal_evals.py.
    {"id": "agent_failed", "title": "An IDE agent failed and did not recover", "classification": "unknown",
     "explain": "The observability hub saw a coding agent's tool call fail in a session that never recovered.",
     "match": _match(kinds=("agent_failed",)),
     "remedies": [_a("open_agent_sessions", "Open Agent sessions", "link", href="#/p/{pid}/agent_sessions",
                     why="The unrecovered sessions, with a link into the hub for each.")]},
    {"id": "role_eval_failed", "title": "A model answered a role's eval wrongly", "classification": "unknown",
     "explain": "Rihma's own eval of a role found wrong answers: each case and what was wrong is in the incident.",
     "match": _match(r".", only=("eval_failed",), wheres=("role_eval",)),
     "remedies": [_a("models_on_evals", "Compare models on our evals", "link", href="#/models",
                     why="Models setup shows each role's models on these evals: choose another, or run it again.")]},
    {"id": "eval_failed", "title": "A Gnomon audit failed", "classification": "unknown",
     "explain": "The audit's findings are in the incident: each can become a change proposal in one click.",
     "match": _match(kinds=("eval_failed",)),
     "remedies": [_a("open_audits", "Open Audits & evals", "link", href="#/p/{pid}/checks",
                     why="The findings, the trend, and Make a change from a finding.")]},
    {"id": "view_broken", "title": "A view could not be drawn", "classification": "rihmasto bug",
     "explain": "The page met an error while drawing this view.",
     "match": _match(kinds=("view_broken", "view_empty")), "remedies": [TRY_AGAIN]},
    {"id": "server_error", "title": "The cockpit hit a bug", "classification": "rihmasto bug",
     "explain": "The server met an error it did not expect while answering. It kept serving.",
     "match": _match(kinds=("server_error",)), "remedies": [TRY_AGAIN]},
]
UNKNOWN = {"id": "unknown", "title": "", "classification": "unknown", "explain": "", "remedies": []}


def classify(doc: dict[str, Any]) -> dict[str, Any]:
    """The built-in class an incident belongs to (the first that matches), or ``UNKNOWN``."""
    return next((c for c in CLASSES if c["match"](doc)), UNKNOWN)


def _fill(action: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    pid = doc.get("project") or "_factory"
    out = {k: (v.replace("{pid}", pid) if isinstance(v, str) else v) for k, v in action.items()}
    if out["kind"] == "retry_read" and ((doc.get("context") or {}).get("request") or {}).get("method") not in \
            (None, "GET"):
        out = out | {"kind": "retry", "safe": False, "why": "Send the same request again: it was a write, so you "
                                                            "confirm it."}
    return out


# -- the learned store ------------------------------------------------------------------------------------------

def _path(factory: Factory) -> Any:
    from kernel.incidents import heal_dir

    return heal_dir(factory) / "remedies.json"


def remedies(factory: Factory) -> list[dict[str, Any]]:
    return list((read_json(_path(factory), {}) or {}).get("remedies") or [])


def _same(r: dict[str, Any], action: dict[str, Any]) -> bool:
    a = r["action"]
    return all(a.get(k) == action.get(k) for k in ("id", "kind", "href", "path"))


def resolution_action(how: dict[str, Any] | None) -> dict[str, Any]:
    """What resolved an incident, as an action: a built-in remedy by its id, a retry, an agent's fix, a person's
    own act (an explanation of what they did)."""
    how = how if isinstance(how, dict) else {}
    kind = str(how.get("kind") or "explain")
    if kind not in ACTION_KINDS:
        raise ValueError(f"how a resolution went is one of {', '.join(ACTION_KINDS)}")
    keep = {k: str(how[k])[:500] for k in ("id", "label", "href", "path", "method", "text", "command", "why")
            if how.get(k)}
    keep.setdefault("id", kind)
    keep.setdefault("label", {"retry_read": "Try again", "retry": "Send it again", "retry_job": "Run it again",
                              "fix": "Apply the fix", "investigate": "Investigate with Rihma"}.get(kind,
                                                                                                  "What fixed it"))
    return keep | {"kind": kind, "safe": kind in SAFE_KINDS}


def _digest(fp: str, action: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({"fingerprint": fp, "action": action}, sort_keys=True).encode()).hexdigest()


def _log(factory: Factory, kind: str, payload: dict[str, Any]) -> None:
    """A remedy's step, in the factory's own ledger (an incident's own steps go to its project's)."""
    from kernel.incidents import ledger_of

    ledger_of(factory, None).log(kind, payload)


def learn(factory: Factory, incident: dict[str, Any], action: dict[str, Any], *, person: str,
          persona: str) -> dict[str, Any]:
    """Propose what resolved ``incident`` as a remedy for its fingerprint (or count it on the same remedy)."""
    fp = incident["fingerprint"]
    with updating_json(_path(factory), {"remedies": []}) as doc:
        rows = doc["remedies"]
        same = next((r for r in rows if r["fingerprint"] == fp and _same(r, action) and r["state"] != "retired"), None)
        if same is not None:
            same["learned_from"] = sorted(set(same["learned_from"]) | {incident["id"]})
            same["resolved"] = int(same.get("resolved", 1)) + 1
            return dict(same)
        n = max([int(r["id"][3:]) for r in rows] or [0]) + 1
        rem = {"id": f"RM-{n:04d}", "fingerprint": fp, "class": incident.get("class"), "title":
               incident.get("summary"), "project": incident.get("project"), "action": action, "state": "proposed",
               "learned_from": [incident["id"]], "resolved": 1, "proposed": {"person": person, "persona": persona,
                                                                             "at": factory.clock.stamp()},
               "approved": None, "retired": None, "uses": 0, "used_at": [], "auto_uses": 0}
        rows.append(rem)
    _log(factory, "remedy_proposed", {"id": rem["id"], "fingerprint": fp, "incident": incident["id"],
                                      "action": action["kind"], "person": person, "persona": persona})
    return rem


def _signs(factory: Factory, person: str, persona: str) -> None:
    """A person with a persona that may approve, or the solo person of a solo home (kernel/heal_approval.py)."""
    from kernel.heal_approval import approvers, may_approve

    if not is_person(person) or persona not in PERSONAS:
        raise PermissionError(f"{person!r} is not a person with a persona: a person approves a remedy")
    if not may_approve(factory, person, persona, APPROVERS):
        raise PermissionError(f"a remedy is approved or retired by {approvers(APPROVERS)}, not {persona}")


def _change(factory: Factory, rid: str, fn: Any) -> dict[str, Any]:
    with updating_json(_path(factory), {"remedies": []}) as doc:
        rem = next((r for r in doc["remedies"] if r["id"] == rid), None)
        if rem is None:
            raise KeyError(f"no remedy {rid}")
        fn(rem)
        return dict(rem)


def approve(factory: Factory, rid: str, *, person: str, persona: str) -> dict[str, Any]:
    """A person approves a learned remedy once, signed: offered first from now on, applied on its own if safe."""
    from kernel.incidents import mark_learned

    _signs(factory, person, persona)

    def go(rem: dict[str, Any]) -> None:
        if rem["state"] != "proposed":
            raise PermissionError(f"{rid} is {rem['state']}, not proposed")
        rem["state"] = "approved"
        rem["approved"] = {"person": person, "persona": persona, "at": factory.clock.stamp(),
                           "sha256": _digest(rem["fingerprint"], rem["action"])}
    rem = _change(factory, rid, go)
    learned = mark_learned(factory, rem["fingerprint"], rid)
    _log(factory, "remedy_approved", {"id": rid, "fingerprint": rem["fingerprint"],
                                      "sha256": rem["approved"]["sha256"], "safe": rem["action"]["safe"],
                                      "incidents": learned, "person": person, "persona": persona})
    return rem


def retire(factory: Factory, rid: str, *, person: str, persona: str, reason: str = "") -> dict[str, Any]:
    _signs(factory, person, persona)

    def go(rem: dict[str, Any]) -> None:
        if rem["state"] == "retired":
            raise PermissionError(f"{rid} is already retired")
        rem["state"] = "retired"
        rem["retired"] = {"person": person, "persona": persona, "at": factory.clock.stamp(), "reason": reason[:500]}
    rem = _change(factory, rid, go)
    _log(factory, "remedy_retired", {"id": rid, "fingerprint": rem["fingerprint"], "person": person,
                                     "persona": persona, "reason": reason[:300]})
    return rem


def note_used(factory: Factory, rid: str, *, incident: str, person: str | None, persona: str | None,
              auto: bool = False) -> dict[str, Any]:
    """A learned remedy was used on ``incident``: by a person, or on its own (``auto``) on its approver's word."""
    def go(rem: dict[str, Any]) -> None:
        rem["uses"] = int(rem.get("uses", 0)) + 1
        rem["auto_uses"] = int(rem.get("auto_uses", 0)) + (1 if auto else 0)
        rem["used_at"] = (rem.get("used_at") or [])[-99:] + [factory.clock.stamp()]
    rem = _change(factory, rid, go)
    who = {"person": person, "persona": persona} if person else \
        {"by": "Rihmasto, on its approver's word", "approved_by": (rem.get("approved") or {}).get("person")}
    _log(factory, "remedy_used", {"id": rid, "incident": incident, "auto": auto, **who})
    return rem


# -- what an incident is offered --------------------------------------------------------------------------------

def offered(factory: Factory, doc: dict[str, Any]) -> dict[str, Any]:
    """The remedies for an incident: approved learned ones first (with "seen before"), then the built-in ones of
    its class, then Investigate with Rihma. ``auto`` is the first approved, safe learned remedy: applied on its
    own."""
    cls = classify(doc)
    learned = [r for r in remedies(factory) if r["fingerprint"] == doc["fingerprint"] and r["state"] != "retired"]
    approved = [r for r in learned if r["state"] == "approved"]
    out = _ordered(cls, approved, doc)
    return {"class": cls["id"], "classification": cls["classification"], "title": cls.get("title") or None,
            "explain": cls.get("explain") or None, "not_measured": bool(cls.get("not_measured")),
            "seen_before": _seen_before(approved), "remedies": out,
            "auto": next((o for o in out if o.get("learned") and o["safe"]), None),
            "proposed": [{"id": r["id"], "label": r["action"]["label"]} for r in learned if r["state"] == "proposed"]}


def _ordered(cls: dict[str, Any], approved: list[dict[str, Any]], doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Approved learned remedies first, then the class's own, then Investigate with Rihma."""
    out = [_fill(r["action"], doc) | {"learned": r["id"], "uses": r["uses"]} for r in approved]
    taken = {o["id"] for o in out}
    out += [_fill(a, doc) for a in cls["remedies"] if a["id"] not in taken]
    if all(o["kind"] != "investigate" for o in out):
        out.append(dict(INVESTIGATE))
    return out


def _seen_before(approved: list[dict[str, Any]]) -> str | None:
    if not approved:
        return None
    first = approved[0]
    return (f"Rihmasto has seen this before: last time “{first['action']['label']}” fixed it "
            f"(approved by {first['approved']['person']}).")


def learned_list(factory: Factory, *, pid: str | None = None) -> list[dict[str, Any]]:
    """What Rihmasto learned: each remedy with its counts, last use, who approved it and its state."""
    rows = remedies(factory)
    if pid is not None:
        want = None if pid == "_factory" else pid
        rows = [r for r in rows if r.get("project") == want]
    return [r | {"last_used": (r.get("used_at") or [None])[-1]} for r in reversed(rows)]
