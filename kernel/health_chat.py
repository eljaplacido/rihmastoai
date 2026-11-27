"""Ask Rihma on a project's health, by rule from the records (FR-CHK1 with FR-HEAL1): guide, don't describe.

"Is this project healthy?", "What failed and what should I do?", "What checks should this project have?" and
"Why did AU-001 fail?" are answered from what is recorded: the failing checks with their last result, the open
incidents with the remedy Rihmasto offers first, the checks suggested for the solution type and which are not on
yet, an automation's last runs. Each answer ends with the next step and opens the view where it is taken. Nothing
is changed here; a person acts on the view it opens.
"""

from __future__ import annotations

import re
from typing import Any

HEALTH = re.compile(r"\b(?:healthy|health of|how is (?:it|this|the project) doing|is (?:it|this|everything) (?:ok|fine|"
                    r"alright)|terve|kunnossa)\b", re.I)
FAILED = re.compile(r"\b(?:what (?:failed|fails|is failing|broke|went wrong)|what'?s (?:failing|broken|wrong)|"
                    r"what should i do (?:about|with) (?:it|that|this|the (?:failure|failures|error))|anything failing|"
                    r"mikä epäonnistui)", re.I)
CHECKS = re.compile(r"\b(?:what|which) checks\b|\bchecks? should\b|\brecommended checks\b|\bmitä tarkistuksia\b", re.I)
AUTOMATION = re.compile(r"\b(AU-\d{3,6})\b", re.I)


def _out(answer: str, route: str, control: str, why: str, pid: str | None, matches: list[str]) -> dict[str, Any]:
    return {"answer": answer, "navigate": {"route": route, "control": control},
            "propose": [{"action": "open", "args": {"route": route}, "why": why, "project": pid}],
            "dropped": [], "sources": [], "by": "rule", "matches": matches}


def _state(factory: Any, project: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """(failing checks, open incidents, the project's health)."""
    from kernel import immune
    from kernel import incidents as inc
    from kernel.checks import health as chealth

    health = chealth.project_health(project)
    failing = [r for r in health["checks"] if r["state"] in ("failed", "not measured")]
    open_ = [i for i in inc.incidents(factory, pid=project.pid) if i["state"] not in inc.DONE]
    for i in open_:
        i["first_remedy"] = next((r.get("label") for r in immune.offered(factory, i)["remedies"]
                                  if r.get("kind") != "investigate"), None)
    return failing, open_, health


def _check_line(r: dict[str, Any]) -> str:
    summary = str((r.get("last") or {}).get("summary") or "").strip()
    return f"{r['label']} {r['state']}" + (f" ({summary[:160]})" if summary else "")


def _health(factory: Any, project: Any, failures_only: bool) -> dict[str, Any]:
    failing, open_, health = _state(factory, project)
    pid, title = project.pid, project.meta.get("title") or project.pid
    if not failing and not open_:
        if not health["checks"]:
            rec = health["recommended"]
            return _out(f"{title} has no check enabled, so its health is not measured. Start with the checks "
                        f"suggested for {rec['label']}: {', '.join(rec['kinds'])}. Next step: enable them on its "
                        "Health tab.", f"#/p/{pid}/checks", "health_enable", "Enable the suggested checks", pid,
                        ["checks"])
        return _out(f"{title} looks healthy: {health['line']}, and no incident is open. Nothing needs you now.",
                    f"#/p/{pid}/checks", "health_run", "See its checks", pid, ["checks"])
    parts = [f"{title} is not healthy." if not failures_only else f"On {title}:"]
    if failing:
        parts.append("Failing: " + "; ".join(_check_line(r) for r in failing[:4]) + ".")
    if open_:
        parts.append("Open incidents: " + "; ".join(f"{i['id']} {i['summary'][:120]}" for i in open_[:3]) + ".")
    first = open_[0] if open_ else None
    if first is not None:
        step = (f"open {first['id']} on Incidents and press \"{first['first_remedy']}\"" if first.get("first_remedy")
                else f"open {first['id']} on Incidents and press Investigate: it reads the trace and proposes a fix")
        parts.append(f"Next step: {step}; when the cause is fixed, run the failing check again on Health before "
                     "you mark it fixed.")
        return _out(" ".join(parts), f"#/p/{pid}/incidents", "incidents_open", f"Open {first['id']}", pid,
                    ["incidents", "checks"])
    parts.append(f"Next step: open Health, read the {failing[0]['label']} evidence, fix what it names and press "
                 "Run now.")
    return _out(" ".join(parts), f"#/p/{pid}/checks", "health_run", "Open its failing check", pid, ["checks"])


def _checks(project: Any) -> dict[str, Any]:
    from kernel.checks import catalogue
    from kernel.checks import health as chealth

    health = chealth.project_health(project)
    rec, cat = health["recommended"], catalogue()
    name = {k: cat[k].label for k in rec["kinds"] if k in cat}
    said = (f"For {rec['label']} I suggest: " + ", ".join(name.get(k, k) for k in rec["kinds"]) + ". "
            + ("Not on yet: " + ", ".join(name.get(k, k) for k in rec["missing"]) + ". Next step: enable "
               f"{name.get(rec['missing'][0], rec['missing'][0])} on the Health tab (it is chosen first there)."
               if rec["missing"] else "All of them are on."))
    return _out(said, f"#/p/{project.pid}/checks", "health_enable", "Enable the suggested checks", project.pid,
                ["checks"])


def _automation(factory: Any, project: Any, aid: str) -> dict[str, Any] | None:
    from kernel import automations_run as run

    rows = [r for r in run.history(factory, aid) if r.get("kind") == "automation_ran"]
    route = f"#/p/{project.pid}/automations" if project is not None else "#/automations"
    pid = project.pid if project is not None else None
    if not rows:
        return _out(f"{aid} has not run yet, so nothing of it failed. Its Dry run says what its next tick would do.",
                    route, "automations_dry_run", f"Open {aid}", pid, ["automations"])
    last = rows[-1]
    bad = [r for r in rows if r.get("outcome") in ("failed", "refused", "error")]
    if not bad:
        return _out(f"{aid}'s runs did not fail: its last run was {last.get('outcome')}"
                    f" ({str(last.get('detail') or '')[:200]}).", route, "automations_run", f"Open {aid}", pid,
                    ["automations"])
    b = bad[-1]
    said = (f"{aid} ({b.get('action')}) {b.get('outcome')} at {str(b.get('at') or '')[:16]}: "
            f"{str(b.get('detail') or 'no detail recorded')[:240]}.")
    step = ("Next step: " + ("do what it names, then press Run now on it." if b.get("outcome") == "refused" else
                             "open its incident on Incidents (it was opened for this run), then press Run now."))
    return _out(f"{said} {step}", route, "automations_run", f"Open {aid}", pid, ["automations", "incidents"])


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """The answer by rule, or None when the question is not about health, failures, checks or an automation."""
    au = AUTOMATION.search(question)
    if au and re.search(r"\b(?:fail\w*|why|wrong|broke|epäonnistu\w*|miksi)\b", question, re.I):
        return _automation(factory, project, au.group(1).upper())
    if project is None or str(project.pid).startswith("_"):
        return None
    if CHECKS.search(question):
        return _checks(project)
    if FAILED.search(question):
        return _health(factory, project, True)
    if HEALTH.search(question):
        return _health(factory, project, False)
    return None
