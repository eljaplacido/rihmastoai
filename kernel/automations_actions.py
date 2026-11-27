"""The actions an automation may take (FR-AUT1), each through the kernel's own path, with its owner's rights.

Before any action runs, the owner's rights are checked again: the persona may still run it, and with access
enforced (D-0016) the owner's verified identity still holds that persona on the project (on the factory for
a factory-wide one) in IT's access file as it is now. A grant IT removed stops the automation's next run.
The action then runs signed as that identity, so its records name it, and untrusted code goes through IT's
isolation runner as anywhere else. A module that is not enabled where it acts refuses it (kernel/modules.py).

| Action | Kernel path |
|---|---|
| advance | kernel.pipeline.advance, which asks the autonomy cap, the posture and the project's pause itself |
| gate | kernel.gate_external.gate, on the commits since the last gate this automation ran |
| rescan | kernel.source_guard.check_folder, then kernel.project_material.add_material when the folder changed |
| notify | a notice (Teams, Slack, mail) or a signed CloudEvent through one of IT's relay subscriptions |
| change | kernel.change.submit, on the project or another one (cross-project) |
| signal | kernel.signals.receive, in the delivery square |
| output | kernel.outputs.build, of the chosen targets |
| command | the project's own test suite, detected by rule, in a temporary clone (kernel.adopt.characterise) |
| ask | a model (the assistant role), with the project's context; the answer is posted as a comment |

None decides a card: an advance waits on cards as a person's advance does, and only a person's delegation
(kernel/delegation.py) settles a card there, as it does today.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from kernel import access as kaccess
from kernel import automations as au
from kernel import automations_text as words
from kernel.canon import Canon, DecisionRefused
from kernel.enforcement_guard import at_automation
from kernel.people import Identity
from kernel.store import Factory, Project

MODULE = {"gate": "build", "command": "build", "notify": "integrations", "change": "change", "signal": "square",
          "rescan": "intake", "ask": "assistant", "probe": "operations"}
EXPORTS = ("_cockpit", "exports")


def _values(a: dict[str, Any], f: dict[str, Any]) -> dict[str, Any]:
    ev = f.get("event") or {}
    return {"project": f.get("project") or "the factory", "event": ev.get("kind") or f["trigger"],
            "automation": a["id"], "ref": ev.get("ref") or ev.get("release") or ev.get("card") or "",
            "verdict": ev.get("verdict") or "", "branch": ev.get("branch") or ""}


def rights(factory: Factory, a: dict[str, Any], pid: str | None) -> Identity | None:
    """The identity an automation acts as on ``pid``: its owner, while the owner may still do this."""
    owner = a["owner"]
    au.check_persona(a["action"]["kind"], owner["person"], owner["persona"])
    access = kaccess.load(factory)
    if not access.enforced:
        return None
    if not owner.get("identity"):
        raise au.AutomationRefused("access is enforced and no verified identity signed this automation: its owner "
                                   "sets it again, signed in")
    ident = Identity(owner["identity"], owner["person"], tuple(owner.get("groups") or ()))
    kaccess.sign(access, ident, owner["person"], owner["persona"], pid or kaccess.FACTORY_SCOPE)
    return ident


def run(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    """Carry out one firing: done, nothing (nothing to do), failed or refused, with why."""
    from kernel import access_isolation as kisolation
    from kernel import modules

    kind = a["action"]["kind"]
    pids = [p for p in (f.get("project"), a["action"].get("project")) if p] or [None]
    try:
        idents = [rights(factory, a, pid) for pid in pids]
        off = modules.first_off(factory, [MODULE[kind]], f.get("project")) if kind in MODULE else None
        if off:
            return {"outcome": "refused", "detail": f"the {modules.MODULES[off]['label']} module is not enabled"}
        with kaccess.signing(idents[0]), kisolation.serving(factory):
            held = at_automation(factory, a, f)      # the owner's enforcement level there (FR-ENF1)
            return held if held is not None else HANDLERS[kind](factory, a, f, tools)
    except (DecisionRefused, PermissionError) as exc:      # the owner's rights, the cap, access, isolation
        return {"outcome": "refused", "detail": str(exc)[:300]}
    except (ValueError, LookupError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"outcome": "failed", "detail": f"{type(exc).__name__}: {exc}"[:300]}


def plan(factory: Factory, a: dict[str, Any], f: dict[str, Any]) -> dict[str, Any]:
    """What a firing would do: a dry run's answer, with nothing done."""
    return {"outcome": "would", "detail": words.plan(a, f)}


def _project(factory: Factory, f: dict[str, Any]) -> Project:
    if not f.get("project"):
        raise ValueError("this action acts on a project, and the firing names none")
    return factory.project(f["project"])


def _who(a: dict[str, Any]) -> dict[str, Any]:
    return {"person": a["owner"]["person"], "persona": a["owner"]["persona"]}


def _model(tools: Any) -> Any:
    model = tools.model() if tools.model is not None else None
    if model is None:
        raise RuntimeError("no model is set up for automations: Models setup, or `rihmasto models`")
    return model


# -- advance, gate, command ------------------------------------------------------------------------------

def _advance(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel import access_isolation as kisolation
    from kernel.pipeline import advance

    project = _project(factory, f)
    kisolation.require(factory)       # a run starts Gnomon cells and the gate's tests: isolated, or refused
    out = advance(project, model=_model(tools))
    state = str(out.get("state"))
    outcome = "failed" if state in ("failed", "apparatus_failure") else "refused" if state in ("capped", "refused") \
        else "done"
    why = str(out.get("why") or "")[:200]
    return {"outcome": outcome, "verdict": state, "detail": f"the run reached {state} at stage {out.get('stage')}"
                                                            + (f": {why}" if why else "")}


def repo_head(project: Project, branch: str | None, *, fetch: bool = True) -> tuple[str, str]:
    """(branch, commit) of an attached repository's branch, or of an adopted project's upstream (fetched)."""
    from kernel import adopt, attach

    attached = project.meta.get("attached") or {}
    if attached.get("repo"):
        name = branch or attached.get("branch") or "main"
        sha = attach.git(Path(attached["repo"]), "rev-parse", "--verify", "-q", f"refs/heads/{name}^{{commit}}",
                         check=False)
    elif adopt.is_adopted(project):
        name = branch or project.read("adopted.json")["default_branch"]
        bare = project.path("repo.git")
        if fetch:
            adopt._net(bare, "fetch", "-q", "--prune", "upstream", timeout=120)
        sha = adopt._upstream_head(bare, name) or ""
    else:
        raise ValueError(f"{project.pid} is neither an attached nor an adopted repository")
    if not sha:
        raise LookupError(f"no branch {name} in {project.pid}'s repository")
    return name, sha


def _last_head(project: Project, aid: str) -> str | None:
    rows = [r["event"]["payload"] for r in project.ledger().of_kind("automation_ran")]
    heads = [r["refs"]["head"] for r in rows if r.get("id") == aid and (r.get("refs") or {}).get("head")]
    return heads[-1] if heads else None


def _gate(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel import gate_external

    project = _project(factory, f)
    attached = project.meta.get("attached") or {}
    if not attached.get("repo"):
        return {"outcome": "refused", "detail": f"{project.pid} is not an attached repository"}
    ev = f.get("event") or {}
    branch, head = repo_head(project, ev.get("branch") or a["trigger"].get("branch"), fetch=False)
    base = _last_head(project, a["id"]) or ev.get("before") or attached.get("head_at_attach")
    if not base or base == head:
        return {"outcome": "nothing", "detail": f"nothing new on {branch} since {head[:12]}", "refs": {"head": head}}
    out = gate_external.gate(project, **_who(a), head=head, base=base, verifier=a["action"].get("verifier", True),
                             verifier_runner=tools.verifier_runner)
    return {"outcome": "done", "verdict": out["verdict"], "refs": {"head": head, "base": base, "round": out["round"]},
            "detail": f"the gate judged {base[:12]}..{head[:12]} on {branch}: {out['verdict']}"
                      + (f"; {out['held']['says']}" if out.get("held") else "")}


@contextlib.contextmanager
def _clone(project: Project) -> Iterator[tuple[Path, str]]:
    """A temporary clone of the project's repository at its branch's head, removed afterwards."""
    from kernel import attach

    attached = project.meta.get("attached") or {}
    if attached.get("repo"):
        _, sha = repo_head(project, None, fetch=False)
        with attach.checkout(project, sha) as work:
            yield work, sha
        return
    _, sha = repo_head(project, None, fetch=False)
    tmp = Path(tempfile.mkdtemp(prefix="rihmasto-automation-"))
    try:
        attach.git(tmp, "clone", "-q", "--no-checkout", str(project.path("repo.git")), "w")
        attach.git(tmp / "w", "checkout", "-q", "--detach", sha)
        yield tmp / "w", sha
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _built_suite(project: Project, a: dict[str, Any]) -> dict[str, Any]:
    """A project built here has no repository to clone: its tests run as Health's Test suite check (run_check)."""
    from kernel.checks import store as cstore

    if "tests" not in cstore.enabled(project):
        return {"outcome": "refused", "detail": f"{project.pid} was built here: its tests run as the Test suite "
                                                "check, which is not enabled on its Health tab. Enable it there"}
    owner = a["owner"]
    row = cstore.run(project, "tests", person=owner["person"], persona=owner["persona"], via=f"automation {a['id']}")
    return {"outcome": "done", "verdict": row["verdict"], "detail": f"Test suite: {row['summary']}"[:300],
            "refs": {"check": "tests"}}


def _command(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel import adopt, attach
    from kernel.native_guide import run_own_roots

    project = _project(factory, f)
    wait = getattr(tools, "suite_timeout", None)
    own = run_own_roots(project, **_who(a), timeout=wait)   # its own mapped test roots (FR-SRC2)
    if own is not None:
        return own
    if not (project.meta.get("attached") or {}).get("repo") and not adopt.is_adopted(project):
        return _built_suite(project, a)
    with attach.outside_code(project) if project.meta.get("attached") else contextlib.nullcontext(), \
            _clone(project) as (work, sha):
        files = [x for x in attach.git(work, "ls-files", "-z").split("\0") if x]
        result = adopt.characterise(work, adopt.detect_tests(work, files), timeout=tools.suite_timeout)
    verdict = str(result["verdict"])
    project.log("automation_suite", {"automation": a["id"], "revision": sha, "verdict": verdict,
                                     "runs": [{k: r.get(k) for k in ("runner", "verdict", "counts")}
                                              for r in result.get("runs", [])], **_who(a)})
    return {"outcome": "done", "verdict": verdict, "refs": {"head": sha},
            "detail": f"the project's own tests at {sha[:12]}: {verdict}; {str(result.get('reason'))[:160]}"}


# -- material, change, signal, output, ask ----------------------------------------------------------------

def _rescan(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel.project_material import add_material, read_material
    from kernel.source_guard import check_folder

    project = _project(factory, f)
    if project.meta.get("source_kind") in ("adopted", "attached"):   # its repository is its material
        return {"outcome": "nothing", "detail": f"{project.pid} is {project.meta['source_kind']}: its repository is "
                "its material, so a folder re-scan adds nothing. 'Re-read the repository for alignment when it "
                "changes' follows its new commits instead."}
    folder = check_folder(a["action"]["folder"], a["owner"]["persona"], factory.home)  # its allowed roots too
    body = read_material(path=str(folder))[1]
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    added = (project.read("material.json") or {}).get("added") or []
    if any(m.get("sha256") == digest for m in added if m.get("path") == str(folder)):
        return {"outcome": "nothing", "detail": f"nothing new in {folder}"}
    out = add_material(project, **_who(a), path=str(folder), note=f"re-scan by automation {a['id']}")
    return {"outcome": "done", "detail": f"added {folder} as material {out.get('n', '')}".strip(),
            "refs": {"sha256": digest}}


def _change(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel.change import submit

    target = factory.project(a["action"].get("project") or _project(factory, f).pid)
    text = words.fill(a["action"]["text"], _values(a, f))
    if any(c["payload"].get("text", "").startswith(text) for c in Canon(target).cards(kind="change")):
        return {"outcome": "nothing", "detail": f"a change with these words is still open on {target.pid}"}
    body = f"{text}\n\n(Opened by automation {a['id']}, {a['name']}, in {a['owner']['person']}'s name.)"
    card = submit(target, **_who(a), text=body)
    return {"outcome": "done", "detail": f"opened change {card['id']} on {target.pid}",
            "refs": {"card": card["id"], "project": target.pid}}


def _signal(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel import signals

    text = words.fill(a["action"]["text"], _values(a, f))
    sig = signals.receive(factory, text, channel="feed", source=f"automation {a['id']}", **_who(a),
                          ref=f"automation:{a['id']}")
    return {"outcome": "done", "detail": f"logged signal {sig['id']}", "refs": {"signal": sig["id"]}}


def _output(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel import outputs

    project = _project(factory, f)
    targets = a["action"].get("targets") or outputs.chosen(project)
    if not targets:
        return {"outcome": "nothing", "detail": f"no output is chosen for {project.pid}"}
    out = outputs.build(project, targets, factory.home.joinpath(*EXPORTS), **_who(a))
    built = [r["target"] for r in out["outputs"] if r.get("state") == "built"]
    return {"outcome": "done" if built else "nothing", "refs": {"built": built},
            "detail": f"built {', '.join(built) or 'nothing'} of {', '.join(targets)}"}


def _context(project: Project) -> str:
    meta, canon = project.meta, Canon(project)
    cards = [f"- {c['id']} {c['kind']}: {str(c.get('title'))[:100]}" for c in canon.cards()][:15]
    recent = [f"- {r['event'].get('at')} {r['event']['kind']}" for r in project.ledger().records()[-20:]
              if isinstance(r, dict)]
    return "\n".join([f"Project {meta.get('title')} ({project.pid}), stage {meta.get('stage')}, maturity "
                      f"{meta.get('maturity')}.", "Open cards:", *(cards or ["- none"]), "Recent records:", *recent])


def _ask(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    from kernel.confidential import require_local

    project = _project(factory, f)
    require_local(project, ["assistant"], where=f"automation {a['id']}")
    question = words.fill(a["action"]["text"], _values(a, f))
    prompt = ("You answer a team's question about one of their projects, from its records below. Answer in at "
              "most 120 words, plainly. You decide nothing and propose no decision.\n\n"
              f"{_context(project)}\n\nThe question: {question}\n")
    answer = str(_model(tools).ask(prompt, role="assistant")).strip()
    if not answer:
        return {"outcome": "failed", "detail": "the model gave no answer"}
    text = f"[Automation {a['id']}, {a['name']}] {question}\n\n{answer[:4000]}"
    c = Canon(project).comment({"kind": "project", "id": project.pid}, text, **_who(a))
    return {"outcome": "done", "detail": f"posted comment {c['id']}", "refs": {"comment": c["id"]}}


# -- notify --------------------------------------------------------------------------------------------

def _notify(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    v = _values(a, f)
    headline = words.fill(a["action"].get("text") or "{event} on {project}", v)
    detail = f"Automation {a['id']} ({a['name']}), in {a['owner']['person']}'s name."
    return send_notice(factory, a["action"]["subscription"], a, f, headline, detail, tools)


def notify_result(factory: Factory, a: dict[str, Any], f: dict[str, Any], result: dict[str, Any], tools: Any) -> None:
    """Tell a channel how a run went, when the automation asks (``notify``: if it fails, or always)."""
    verdict = f" ({result['verdict']})" if result.get("verdict") else ""
    headline = f"{a['name']}: {result['outcome']}{verdict} on {f.get('project') or 'the factory'}"
    with contextlib.suppress(DecisionRefused, PermissionError, ValueError, LookupError, OSError):
        send_notice(factory, a["notify"]["subscription"], a, f, headline, str(result.get("detail") or ""), tools)


def send_notice(factory: Factory, sub_id: str, a: dict[str, Any], f: dict[str, Any], headline: str, detail: str,
                tools: Any) -> dict[str, Any]:
    """One notice through one of IT's subscriptions, logged in the relay's delivery log. A project an autopilot
    binds to its sandbox sends nothing to a receiver that is not a sandbox one (kernel/autopilot.py)."""
    import os

    from kernel import relay
    from kernel.autopilot import outbound_hold

    sub = next((s for s in relay.subscriptions(factory) if s["id"] == sub_id), None)
    if sub is None:
        return {"outcome": "refused", "detail": f"no active relay subscription {sub_id}"}
    project = factory.project(f["project"]) if f.get("project") else None
    held = outbound_hold(project, sub) if project is not None else None
    if held:
        return {"outcome": "nothing", "detail": f"held for the autopilot's sandbox: {held}"}
    env = tools.environ if tools.environ is not None else os.environ
    missing = relay._missing(sub, env)
    if missing:
        return {"outcome": "refused", "detail": f"{sub_id} is not configured here: {', '.join(missing)} not set"}
    notice = _notice(factory, a, f, headline, detail)
    try:
        status: int | None = _deliver(sub, notice, env, tools, factory.clock.now())
        error = None if status is not None and 200 <= status < 300 else f"HTTP {status}"
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        status, error = None, relay._scrub(f"{type(exc).__name__}: {exc}", sub, env)
    from kernel.ledgerstore import LedgerStore

    LedgerStore(factory.home / "relay" / "deliveries.jsonl", clock=factory.clock).append(
        "automation_notice", {"subscription": sub_id, "sink": sub["sink"], "automation": a["id"],
                              "webhook_id": notice["event_id"], "project": f.get("project"),
                              "outcome": "delivered" if error is None else "failed", "status": status, "error": error})
    if error:
        return {"outcome": "failed", "detail": f"{sub_id}: {error}"}
    return {"outcome": "done", "detail": f"notified {sub_id} ({sub['sink']})", "refs": {"subscription": sub_id}}


def _notice(factory: Factory, a: dict[str, Any], f: dict[str, Any], headline: str, detail: str) -> dict[str, Any]:
    from kernel import relay
    from kernel.notices import NOT_HERE, defang

    base = relay.config(factory)["cockpit"].rstrip("/")
    link = f"{base}/#/p/{f['project']}/automations" if f.get("project") else f"{base}/#/automations"
    seq = (f.get("event") or {}).get("seq")
    marker = f"{f.get('project') or 'factory'}-{seq}" if seq is not None else factory.clock.stamp()
    return {"digest": True, "event_id": f"automation-{a['id']}-{marker}", "card_kind": None,
            "headline": defang(headline)[:200], "detail": defang(detail)[:1000] + "\n" + NOT_HERE, "link": link}


def _deliver(sub: dict[str, Any], notice: dict[str, Any], env: Any, tools: Any, now: dt.datetime) -> int:
    from kernel import notices, relay
    from kernel.hooks import secret_bytes, sign_standard

    post: Callable[..., int] = tools.post or relay.post_json
    if sub["sink"] == "email":
        mail = sub["mail"]
        (tools.send or relay.smtp_send)(mail, notices.render_email(notice, sender=mail["from"], to=mail["to"],
                                                                   now=now), env)
        return 250
    url = sub.get("url") or env.get(sub.get("url_env") or "", "")
    if sub["sink"] in ("teams", "slack"):
        render = notices.render_teams if sub["sink"] == "teams" else notices.render_slack
        return int(post(relay.check_url(url), json.dumps(render(notice)).encode("utf-8"),
                        {"Content-Type": "application/json"}))
    stamp = int(now.timestamp())
    body = json.dumps({"specversion": "1.0", "id": notice["event_id"], "source": "rihmasto/automations",
                       "type": "rihma.automation.notice", "datacontenttype": "application/json",
                       "data": {k: notice[k] for k in ("headline", "detail", "link")}}, sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/cloudevents+json; charset=utf-8", "User-Agent": "rihmasto-relay",
               "webhook-id": notice["event_id"], "webhook-timestamp": str(stamp),
               "webhook-signature": sign_standard(secret_bytes(env[sub["secret_env"]]), notice["event_id"], stamp,
                                                  body)}
    return int(post(relay.check_url(url), body, headers))


def _probe(factory: Factory, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    """The probe check where the release runs (kernel/operate.py): /health and every probe scenario. On
    production it is an operations round, so a failing probe opens the incident card; elsewhere it is recorded."""
    from kernel import operate

    project = _project(factory, f)
    env = a["action"].get("environment") or (f.get("event") or {}).get("environment") or "production"
    res = operate.tick(project)["probes"][0] if env == "production" else operate.probe(project, env)
    refs = {"environment": env, **({"incident": res["incident"]} if res.get("incident") else {})}
    if res.get("verdict") == "not applicable":
        return {"outcome": "nothing", "detail": str(res.get("reason") or f"nothing runs in {env}"), "refs": refs}
    return {"outcome": "done", "verdict": res["verdict"], "refs": refs | {"release": res.get("release")},
            "detail": f"the probe check on {env}: {res.get('failed', 0)} of {res.get('checks', 0)} checks failed"}


HANDLERS: dict[str, Callable[[Factory, dict[str, Any], dict[str, Any], Any], dict[str, Any]]] = {
    "advance": _advance, "gate": _gate, "rescan": _rescan, "notify": _notify, "change": _change, "signal": _signal,
    "output": _output, "command": _command, "ask": _ask, "probe": _probe,
    "watch": lambda factory, a, f, tools: __import__("kernel.adopt_watch", fromlist=["fire"]).fire(
        _project(factory, f), str(a["action"].get("what") or "commits"))}
# run_check, align_scan and review_digest (kernel/automations_more.py), whichever module loads first.
from kernel.automations_more import handlers as _more  # noqa: E402

HANDLERS.update(_more())
with contextlib.suppress(ImportError):   # agent observability's snapshot (kernel/agentobs/automation_hook.py)
    from kernel.agentobs.automation_hook import register_handler

    register_handler(HANDLERS, MODULE)
