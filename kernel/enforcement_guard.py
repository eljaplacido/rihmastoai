"""What an enforcement level does when something crosses into an environment (D-0026, FR-ENF1, FR-ENF2).

Rihmasto's gate (a change judged in an attached repository), the deploy step of a release and an automation that
changes something ask ``guard`` before they go on. For each check family with a say, the level of that cell
(kernel/enforcement.py) decides:

- ``advise``: a note in the project's ledger (``enforcement``, outcome ``noted``) that the view and Ask Rihma show
  as a nudge; the work goes on;
- ``require_review``: a card of kind ``enforcement`` for the cell's reviewer (only that persona may decide it); the
  work goes on and the card stays until decided;
- ``enforce``: the same card, blocking; the work is refused until the reviewer approves it. An approval is the
  override, recorded with its person and reason. It covers what the reviewer saw (kernel/enforcement_cards.py): a
  new finding asks again, and an automation's approval lets one firing through.

A family has a say when it has a finding (a failed check of its kind, an open security finding, a gate verdict
that is not passed). Governance has a say on every change that enters test or production, and in development only
once its level there is above advise: development stays free unless the owner turns it on. An environment's name
Rihmasto does not know counts as production (kernel/enforcement_places.py), and the answer says so.
"""

from __future__ import annotations

from typing import Any

from kernel import enforcement_cards as kcards
from kernel.canon import Canon
from kernel.enforcement import FAMILIES, RANK, cell, gate_env, place

OUTCOMES = ("passed", "cleared", "noted", "review", "refused")     # from least to most held
LEVEL_OUTCOME = {"off": "passed", "advise": "noted", "require_review": "review", "enforce": "refused"}
CHECK_FAMILY = {"tests": "quality", "custom": "quality", "ci": "quality", "probe": "quality", "repo_gate": "quality",
                "dependencies": "security", "secrets": "security", "security_gate": "security",
                "licences": "legal", "sbom": "legal", "destinations": "governance"}
CHANGING_ACTIONS = {"advance": "governance", "command": "quality"}   # automations that change something


def family_of_check(kind: str) -> str | None:
    return "governance" if str(kind).startswith("gnomon") else CHECK_FAMILY.get(str(kind))


def findings(project: Any) -> dict[str, list[str]]:
    """The project's open findings by family: every enabled check whose latest result failed."""
    from kernel.checks.store import enabled, results

    out: dict[str, list[str]] = {f: [] for f in FAMILIES}
    for key, entry in enabled(project).items():
        last = (results(project, key, 1) or [{}])[-1]
        family = family_of_check(entry.get("kind") or key.split(":")[0])
        if family and last.get("verdict") == "failed":
            out[family].append(f"check {key}: {str(last.get('summary') or 'failed')[:120]}")
    return out


def applies(env: str, family: str, level: str, items: list[str]) -> bool:
    if level == "off":
        return False
    if items:
        return True
    return family == "governance" and (env != "dev" or RANK[level] > RANK["advise"])


def _one(project: Any, c: dict[str, Any], items: list[str], source: str, subject: str,
         once: bool) -> dict[str, Any]:
    key = f"{c['env']}:{c['family']}:{subject}"
    seen = kcards.seen_of(c, items)
    card = None
    if c["level"] in ("require_review", "enforce"):
        card = (kcards.card_for(Canon(project), key, seen, once=once)
                or kcards.open_card(project, c, key, items, source, subject, seen, once))
    outcome = kcards.outcome(c["level"], card)
    row = {"env": c["env"], "family": c["family"], "level": c["level"], "scope": c["scope"], "outcome": outcome,
           "reviewer": c["reviewer"], "subject": subject, "source": source, "items": items[:5],
           "card": card["id"] if card else None}
    decision = (card or {}).get("decision") or {}
    if outcome == "cleared":       # an approval let it through: the override, with who and why
        row["override"] = {"by": decision.get("person"), "persona": decision.get("persona"),
                           "reason": decision.get("reason"), "decision": decision.get("id")}
        if once and card is not None:
            kcards.spend(project, card)
    project.log("enforcement", row)
    return row | {"_card": card}


def says(out: dict[str, Any]) -> str:
    """The guard's answer in one sentence or two, saying who decides, where, and what lets the work on."""
    note = (" " + out["placed"]["says"]) if out["placed"].get("says") else ""
    if not out["checked"]:
        return f"Nothing to check in {out['env']}.{note}"
    held = [x for x in out["checked"] if x["outcome"] in ("refused", "review")]
    if out["outcome"] == "refused":
        x = next(x for x in held if x["outcome"] == "refused")
        return kcards.held_words(x, x.get("_card")) + note
    if held:
        return f"Went on; {', '.join(x['card'] for x in held)} asks for a review in {out['env']}.{note}"
    return f"Went on in {out['env']}; noted for {', '.join(x['family'] for x in out['checked'])}.{note}"


def guard(project: Any, *, env: str, source: str, subject: str,
          found: dict[str, list[str]] | None = None, once: bool = False) -> dict[str, Any]:
    """What the levels say about ``subject`` entering ``env`` (a name of Rihmasto's or a pipeline's; one it does not
    know counts as production and the answer says so). ``once``: a recurring subject, one approval per go."""
    placed = place(project.factory, project, env)
    env3 = placed["env"]
    found = found if found is not None else findings(project)
    checked = []
    for family in FAMILIES:
        c = cell(project.factory, project, env3, family)
        items = list(found.get(family) or [])
        if applies(env3, family, c["level"], items):
            checked.append(_one(project, c, items or [], source, subject, once))
    out = {"env": env3, "named": env, "placed": placed, "source": source, "subject": subject, "checked": checked,
           "outcome": max((x["outcome"] for x in checked), key=OUTCOMES.index, default="passed")}
    out["says"] = says(out)
    for x in checked:
        x.pop("_card", None)
    return out


# -- the places that ask -----------------------------------------------------------------------------------

def at_deploy(project: Any, env: str, release: Any, security: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Before a release is deployed to ``env`` (kernel/deliver.py): None when it may go on, else the step's waiting
    outcome on the enforcement card. Every outcome is in the ledger."""
    found = findings(project)
    found["security"] += [str(b) for b in (security or {}).get("blocking") or []]
    out = guard(project, env=env, source="deploy", subject=f"release {release}", found=found)
    if out["outcome"] != "refused":
        return None
    card = next(x["card"] for x in out["checked"] if x["outcome"] == "refused")
    return {"outcome": "waiting", "card": card, "waiting_on": out["says"],
            "native": {"enforcement": out, "why": out["says"]}}


def at_gate(project: Any, verdict: str, label: str, head: str) -> dict[str, Any] | None:
    """After Rihmasto's gate judged a change of an attached repository: what the levels of the stage that change
    enters say (the project's ``gate_env``, development unless a person says otherwise). ``held`` is true when an
    enforce level refuses it until its reviewer decides: the gate then does not let it on."""
    found: dict[str, list[str]] = {f: [] for f in FAMILIES}
    if verdict == "violation":
        found["governance"].append(f"the gate found a violation on {label}")
    elif verdict != "passed":
        found["quality"].append(f"the gate's verdict on {label} is {verdict}")
    stage = gate_env(project.factory, project)
    out = guard(project, env=stage["env"], source="gate", subject=f"change {str(head)[:12]}", found=found)
    if not out["checked"]:
        return None
    return out | {"held": out["outcome"] == "refused", "stage_scope": stage["scope"]}


def gate_parts(out: dict[str, Any] | None) -> dict[str, Any]:
    """What the gate's result carries of ``at_gate``: ``enforcement`` when a level had a say, and ``held`` (the card
    and its words) when an enforce level holds the change until its reviewer decides."""
    if out is None:
        return {}
    if not out["held"]:
        return {"enforcement": out}
    card = next(x["card"] for x in out["checked"] if x["outcome"] == "refused")
    return {"enforcement": out, "held": {"card": card, "says": out["says"]}}


def at_automation(factory: Any, automation: dict[str, Any], firing: dict[str, Any]) -> dict[str, Any] | None:
    """Before an automation that changes something acts on a project: the refusal's words, or None to go on. Each
    firing is its own go: one approval lets one firing through."""
    kind = automation["action"]["kind"]
    pid = firing.get("project") or automation["action"].get("project")
    if kind not in CHANGING_ACTIONS or not pid:
        return None
    project = factory.project(pid)
    out = guard(project, env=str(automation["action"].get("env") or "dev"), source="automation",
                subject=f"automation {automation['id']}", found=findings(project), once=True)
    return None if out["outcome"] != "refused" else {"outcome": "refused", "detail": out["says"][:400],
                                                     "enforcement": out}


def recent(project: Any, limit: int = 30) -> list[dict[str, Any]]:
    """The guard's latest outcomes on this project, newest first."""
    rows = [{"at": r["event"].get("at"), **r["event"]["payload"]} for r in project.ledger().of_kind("enforcement")]
    return rows[-limit:][::-1]
