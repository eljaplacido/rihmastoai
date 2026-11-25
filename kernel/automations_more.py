"""What other features add to the automations' allow-list and templates (FR-AUT1 with FR-CHK1 and FR-ALN1).

kernel/automations.py imports this module last, so whatever uses automations (the cockpit, the command line,
the scheduler's tick) finds these actions and templates there:

- ``run_check`` (kernel/checks/automation_hook.py): run an enabled check on the firing's project, and the
  template "Notify when a check fails" (an event trigger on ``check_ran`` with the guard verdict = failed);
- ``align_scan``: re-read the project's repository for alignment (kernel/alignment_records.py), signed by the
  automation's owner; the scan records ``alignment_scanned`` with its drift since the scan before (new, changed
  and removed items), which the Alignment tab shows for a person to accept or reject and Insights counts. It
  decides nothing. The template "Re-read the repository for alignment when it changes" fires it on a repository
  change (the repo trigger);
- ``review_digest``: the owner's Review (kernel/review_digest.py) as one notice to a relay subscription, held back
  when nothing happened, from the template "Morning review digest" (the Review's own ``TEMPLATE``). The relay's
  digest round, set per person in the Review, stays the other path.
"""

from __future__ import annotations

from typing import Any

from kernel.people import PERSONAS

ALIGN = {"align_scan": {"label": "re-read the repository for alignment (its drift shows on the Alignment tab)",
                        "personas": ("business_owner", "product_owner", "developer", "it"), "per_project": True}}

TEMPLATES: list[dict[str, Any]] = [
    {"id": "check_failed_notify", "label": "Notify when a check fails", "needs": ["subscription"],
     "about": "When a check on Health fails (any project, any check), notify a channel with the project and check.",
     "draft": {"name": "A check failed", "trigger": {"kind": "event", "types": ["check_ran"]},
               "guard": {"kind": "field", "key": "verdict", "equals": "failed"},
               "action": {"kind": "notify", "subscription": "", "text": "A check failed on {project} ({verdict})"},
               "scope": {"kind": "factory"}}},
    {"id": "align_on_change", "label": "Re-read the repository for alignment when it changes", "needs": ["project"],
     "about": "When the project's repository changes, read it again for alignment: what drifted from what was "
              "accepted shows on its Alignment tab to accept or reject.",
     "draft": {"name": "Alignment after a change", "trigger": {"kind": "repo"}, "action": {"kind": "align_scan"},
               "scope": {"kind": "project", "projects": []}}},
]


DIGEST = {"review_digest": {"label": "send the owner's Review (since they last looked) to a channel",
                            "personas": PERSONAS, "per_project": False}}


def _digest_template() -> dict[str, Any]:
    """The Review's "Morning review digest" (kernel/review_digest.py TEMPLATE) as an automation: every morning, the
    owner's review to a receiver, held back when nothing happened. The relay's own digest round stays too."""
    from kernel.review_digest import TEMPLATE

    at = str((TEMPLATE.get("trigger") or {}).get("at") or "07:30")
    return {"id": "morning_review_digest", "label": TEMPLATE["label"], "needs": ["subscription"],
            "about": "Every morning, send your Review (what shipped, what went wrong, what waits on you since you last "
                     "looked) to a channel; nothing is sent when nothing happened.",
            "draft": {"name": TEMPLATE["label"], "trigger": {"kind": "schedule", "daily": at},
                      "action": {"kind": "review_digest", "subscription": ""}, "scope": {"kind": "factory"}}}


def review_digest(factory: Any, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    """The owner's Review as one notice through the subscription, through the automations' own transport."""
    import os

    from kernel import automations_actions as acts
    from kernel import relay
    from kernel.review import last_reviewed
    from kernel.review_digest import notice

    sub_id, owner = a["action"]["subscription"], a["owner"]
    sub = next((s for s in relay.subscriptions(factory) if s["id"] == sub_id), None)
    if sub is None:
        return {"outcome": "refused", "detail": f"no active relay subscription {sub_id}"}
    env = tools.environ if tools.environ is not None else os.environ
    missing = relay._missing(sub, env)
    if missing:
        return {"outcome": "refused", "detail": f"{sub_id} is not configured here: {', '.join(missing)} not set"}
    entry = {"person": owner["person"], "persona": owner["persona"]}
    n = notice(factory, entry, cockpit=relay.config(factory)["cockpit"], subscription=sub,
               day=factory.clock.today().isoformat(), since=last_reviewed(factory, owner["person"]))
    if not n["happened"]:
        return {"outcome": "nothing", "detail": "nothing happened since the last review: the digest is held back"}
    status = acts._deliver(sub, n, env, tools, factory.clock.now())
    if not 200 <= int(status or 0) < 300:
        return {"outcome": "failed", "detail": f"{sub_id}: HTTP {status}"}
    return {"outcome": "done", "detail": f"{n['headline']} (to {sub_id})"[:300], "refs": {"subscription": sub_id}}


def align_scan(factory: Any, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    """Read the firing project's repository for alignment with the owner's rights; the drift for the history."""
    from kernel import alignment_records as ar

    if not f.get("project"):
        raise ValueError("align_scan acts on a project, and the firing names none")
    project = factory.project(f["project"])
    if not ar.applies(project):
        return {"outcome": "nothing", "detail": f"{project.pid} has no repository of its own to align with"}
    owner = a["owner"]
    view = ar.scan(project, person=owner["person"], persona=owner["persona"])
    drift = {k: len(v) for k, v in (view.get("drift") or {}).items() if isinstance(v, list)}
    moved = sum(drift.values())
    detail = (f"{moved} item(s) drifted since the scan before: " + ", ".join(f"{n} {k}" for k, n in drift.items())
              if moved else "nothing drifted since the scan before")
    return {"outcome": "done", "detail": detail[:300], "refs": {"head": (f.get("event") or {}).get("head")}}


def register() -> None:
    """Add the actions, their handlers and the templates (idempotent). A module still loading (it imported the
    automations first) adds its part itself when it is done: kernel/automations_actions.py the handlers
    (``handlers``), kernel/automations_text.py the templates (``templates``)."""
    import types

    from kernel import automations, automations_actions, gnomon_evals_auto  # run_eval: Gnomon's audits (FR-EVL1)
    from kernel import automations_text as words
    from kernel.checks import automation_hook

    loaded = hasattr(automations_actions, "HANDLERS")
    automation_hook.register(automations, automations_actions if loaded else types.SimpleNamespace(HANDLERS={}))
    gnomon_evals_auto.register(automations, automations_actions if loaded else types.SimpleNamespace(HANDLERS={}))
    automations.ACTIONS.update(ALIGN)
    automations.ACTIONS.update(DIGEST)       # the Review's morning digest (FR-REV1)
    automations._ACTION_FIELDS["review_digest"] = lambda factory, a: {
        "subscription": automations._subscription(factory, a.get("subscription"))}
    if loaded:
        automations_actions.HANDLERS.update(handlers())
    if hasattr(words, "TEMPLATES"):
        have = {t["id"] for t in words.TEMPLATES}
        words.TEMPLATES.extend(t for t in templates() if t["id"] not in have)


def handlers() -> dict[str, Any]:
    """The handlers of the actions this module adds."""
    from kernel import gnomon_evals_auto
    from kernel.checks import automation_hook

    return {"run_check": automation_hook.handle, "align_scan": align_scan, "review_digest": review_digest,
            "run_eval": gnomon_evals_auto.handle}


def templates() -> list[dict[str, Any]]:
    """The templates this module adds to kernel/automations_text.py's."""
    from kernel.gnomon_evals_auto import TEMPLATE

    return [*TEMPLATES, _digest_template(), TEMPLATE]


register()
