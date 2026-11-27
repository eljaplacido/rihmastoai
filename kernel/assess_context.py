"""What kind of project an assessment is of, what its findings are like, and where the landing leads (FR-ASP2).

An independent check of FR-ASP1 found "Worth acting on now" listing, for a local game, no pipeline, no SECURITY.md,
no licence and no read of the environment: every finding of medium or more, with no sense of the project's kind,
for the owner to dismiss one by one. Dismissing one proposed nothing, though the view promised the findings of the
same rule; and landing in the project said "Every task is merged" with no word of the assessment. By rule, no model:

- **The project's kind** (`project_kind`): a project with no HTTP route, no container file, no deploy file and a
  work profile that is not a service is a *local project*. Its findings that matter only once it is deployed,
  published or worked on by a team (`LATER`) read "for later", with why, out of "worth acting on now"
  (`put_off`). A person's "relevant" brings one back, kept by key like every verdict.
- **Findings of the same kind** (`family_of`): the red team's rule; else the kind of check (the delivery pipeline,
  running it elsewhere, documents a published project keeps, dependency upkeep, audit evidence); else the rule a
  keyed finding is one of (each open issue of the team's own log). Dismissing one proposes the rest of its kind.
- **The landing leads to the assessment** (`briefing_line`, `landing_step`): an adopted project's briefing says
  what is worth acting on now from its latest assessment; when no task is left to work on, the next step is the
  assessment's (or assessing it, when it never was).
"""

from __future__ import annotations

import re
from typing import Any

SERVICE_PROFILES = ("web_service", "integration", "ops_agent", "automation", "mobile_prototype", "agentic_workflow",
                    "ml_pipeline", "data_pipeline")
PUBLISHED_PROFILES = ("library_cli",)          # others use its code: what a published project keeps applies now
DEPLOY = re.compile(r"(?i)(^|/)(procfile|fly\.toml|app\.ya?ml|vercel\.json|netlify\.toml|serverless\.ya?ml"
                    r"|render\.ya?ml|railway\.(json|toml)|(docker-)?compose(\.[\w-]+)?\.ya?ml|chart\.ya?ml|[^/]+\.tf"
                    r"|(k8s|kubernetes|helm|deploy|deployment)/[^/]+\.(ya?ml|json))$")
KINDS = {
    "deliver": ("the delivery pipeline", "a pipeline matters once more than one person merges into it or it ships"),
    "deploy": ("running it somewhere else", "it matters once it runs somewhere other than this computer"),
    "publish": ("documents a published project keeps", "it matters once the code is published or shared"),
    "team": ("how a team keeps it", "it matters once a team works on it"),
    "dependencies": ("dependency upkeep", ""),
    "evidence": ("evidence for an audit", ""),
}
FAMILY_KEYS = {
    "deliver": ("cicd.pipeline", "cicd.tests_in_pipeline", "cicd.runs_before_merge", "cicd.pinned_actions",
                "cicd.token_permissions", "cicd.required_checks", "cicd.protected_main", "cicd.release"),
    "deploy": ("architecture.config", "architecture.container", "architecture.dockerignore", "architecture.health",
               "architecture.logging", "architecture.entry_points"),
    "publish": ("security.policy", "compliance.licence", "compliance.notice"),
    "team": ("maintenance.ownership",),
    "dependencies": ("maintenance.pinning", "maintenance.dependency_age", "maintenance.update_automation"),
    "evidence": ("compliance.audit_trail", "compliance.factory_evidence", "compliance.security_evidence"),
}
# A local project's findings for later, and the kind that says when they matter.
LATER = {k: kind for kind in ("deliver", "deploy", "publish", "team") for k in FAMILY_KEYS[kind]
         if k not in ("architecture.logging", "architecture.entry_points", "cicd.pinned_actions",
                      "cicd.token_permissions")} | {"maintenance.update_automation": "team"}
FALLBACK_STEPS = ("Every task is merged", "Get the requirements compiled")


# -- the project's kind ----------------------------------------------------------------------------------

def _signs(files: list[str], inventory: dict[str, Any]) -> list[str]:
    """What says a project runs somewhere else: its HTTP routes, a container file, deploy files."""
    found = inventory.get("routes")
    routes = len(found) if isinstance(found, list) else int(inventory.get("http_routes") or 0)
    docker = (inventory.get("dockerfile") or {}).get("files") or []
    deploy = [f for f in files if DEPLOY.search(f)][:3]
    out = [f"{routes} HTTP route{'s' if routes != 1 else ''}"] if routes else []
    out += [f"a container file ({docker[0]})"] if docker else []
    return out + ([f"deploy files ({', '.join(deploy)})"] if deploy else [])


def project_kind(project: Any, files: list[str], inventory: dict[str, Any]) -> dict[str, Any]:
    """Local or deployed, by rule, with why: HTTP routes, a container or deploy file, or a service's work profile."""
    from kernel.profiles import PROFILES

    profile = project.meta.get("profile")
    label = (PROFILES.get(profile) or {}).get("label") if profile else None
    signs = _signs(files, inventory) + ([f"its work profile, {label}"] if profile in SERVICE_PROFILES else [])
    if signs:
        return {"kind": "deployed", "why": "; ".join(signs), "profile": profile}
    return {"kind": "local", "profile": profile, "published": profile in PUBLISHED_PROFILES,
            "why": "no HTTP route, container or deploy file" + (f"; its work profile, {label}" if label else "")}


def put_off(project: Any, record: dict[str, Any] | None) -> dict[str, Any] | None:
    """A local project's findings that matter later read "for later", with why; never one a person kept relevant
    or dismissed. The record on disk is not changed."""
    kind = ((record or {}).get("precise") or {}).get("kind") or {}
    if kind.get("kind") != "local":
        return record
    for c in (record or {}).get("checks") or []:
        later = LATER.get(str(c.get("key")))
        if c.get("verdict") != "failed" or not later or c.get("kept_relevant") or c.get("dismissed"):
            continue
        if later == "publish" and kind.get("published"):
            continue
        c["later"] = {"by": "rule", "kind": later, "local": kind["why"],
                      "reason": f"for later: {KINDS[later][1]}; this is a local project ({kind['why']})"}
    return record


# -- findings of the same kind ---------------------------------------------------------------------------

_BY_KEY = {k: name for name, keys in FAMILY_KEYS.items() for k in keys}


def family_of(key: str) -> str:
    """What makes two findings alike: the red team's rule, the kind of check, or the rule of a keyed finding."""
    base = key.split(":", 1)[0]
    if key.startswith("security.RT-"):
        return base
    return f"kind:{_BY_KEY[base]}" if base in _BY_KEY else base


def family_label(family: str) -> str:
    """A family in words, for the person who gave the verdict."""
    if family.startswith("kind:"):
        return KINDS[family[5:]][0]
    if family.startswith("security.RT-"):
        return f"the red team's rule {family.removeprefix('security.')}"
    if family == "maintenance.issue_log":
        return "open issues of the team's own log"
    return f"the rule {family}"


# -- the landing ------------------------------------------------------------------------------------------

def briefing_line(project: Any) -> dict[str, Any] | None:
    """What the latest assessment says is worth acting on now, for an adopted project's briefing."""
    from kernel.adopt import is_adopted
    from kernel.assess import history

    if not is_adopted(project):
        return None
    route = f"#/p/{project.pid}/assessment"
    if not history(project):
        return {"assessed": False, "act": "Not assessed yet: assess it to see what is worth acting on now and what "
                                          "is probably noise.", "gaps": None, "act_ids": [], "route": route,
                "label": "Assess it", "control": "run_assessment"}
    from kernel.assess_cards import view

    v = view(project)
    head = v.get("headline") or {}
    return {"assessed": True, "assessment": (v.get("latest") or {}).get("id"), "act": head.get("act"),
            "gaps": head.get("gaps"), "act_ids": head.get("act_ids") or [], "route": route,
            "label": "Open the assessment", "control": "assessment_ask"}


def landing_step(project: Any, step: dict[str, Any], line: dict[str, Any] | None = None) -> dict[str, Any]:
    """The briefing's next step, led to the assessment when nothing else is left to work on."""
    if not str(step.get("title", "")).startswith(FALLBACK_STEPS):
        return step
    line = line if line is not None else briefing_line(project)
    if not line or (line["assessed"] and not line["act_ids"] and not line.get("gaps")):
        return step
    action = {"label": line["label"], "route": line["route"], "control": line["control"]}
    if not line["assessed"]:
        return {"title": "Assess the project", "why": "no task is left to work on, and the project was never "
                "assessed: the assessment says what is worth acting on now", "task": None, "action": action}
    n = len(line["act_ids"])
    title = (f"Act on the assessment: {n} finding{'s' if n != 1 else ''} worth acting on now" if n
             else "Close the assessment's gaps")
    return {"title": title, "why": line["act"] if n else line["gaps"], "task": None, "action": action}


__all__ = ["DEPLOY", "FAMILY_KEYS", "KINDS", "LATER", "briefing_line", "family_label", "family_of", "landing_step",
           "project_kind", "put_off"]
