"""The project's own pipeline, read and never written: GitHub environments and branch protection (FR-ENF1).

Rihmasto is a middle layer: the project's pipeline is taken as given. With the GitHub CLI's own sign-in it reads,
with ``gh api`` GET requests only:

- the repository and its default branch (``repos/<owner>/<name>``);
- its deployment environments and their protection rules (``repos/<owner>/<name>/environments``): required
  reviewers, a wait timer, which branches may deploy;
- the default branch's protection, from both places GitHub keeps it: classic branch protection
  (``repos/<owner>/<name>/branches/<branch>/protection``) and the repository rulesets in force on the branch
  (``repos/<owner>/<name>/rules/branches/<branch>``, named from ``repos/<owner>/<name>/rulesets``): a required pull
  request, required approving reviews, required status checks, whether admins are held too (FR-ENF2).

Each environment is placed in dev, test or prod by the whole words of its name, or as a person placed it; a name
Rihmasto does not know counts as production (kernel/enforcement_places.py). ``compare`` says,
per environment, whether Rihmasto's levels and the pipeline agree that a person checks a change before it goes
on, or which of the two is stricter, and what a person could do about it; Rihmasto never changes the pipeline.
Nothing read here is recorded: the view and Ask Rihma read it when asked.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from typing import Any

from kernel import enforcement as ke
from kernel import enforcement_places as kplaces

Runner = Callable[[list[str]], tuple[int, str, str]]
_SLUG = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
_REMOTE = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?\Z")
SIGN_IN = "Install the GitHub CLI and sign in once with `gh auth login`; Rihmasto then reads with your own sign-in"


def gh(args: list[str]) -> tuple[int, str, str]:
    """``gh <args>``: GET requests of ``gh api`` only (the callers pass nothing else)."""
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=20, check=False,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 127, "", "the GitHub CLI (gh) is not installed here"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stdout, done.stderr


def repo_of(project: Any) -> tuple[str | None, str]:
    """The project's GitHub repository (owner/name), else None and why."""
    named = str(ke.project_settings(project).get("repo") or "").strip()
    if named:
        ok = _SLUG.match(named)
        return (named, "named in the project's settings") if ok else (None, "the named repo is not owner/name")
    from kernel.attach import git
    from kernel.console import workspace

    try:
        ws = workspace(project)            # read only: the working copy is never made here
    except (ValueError, OSError):
        ws = {"exists": False}
    if not ws.get("exists") or not ws.get("path"):
        return None, "this project has no repository on this machine"
    m = _REMOTE.search(git(ws["path"], "remote", "get-url", "origin", check=False).strip())
    return (m.group(1), "its git remote origin") if m else (None, "its repository has no GitHub remote named origin")


def _get(run: Runner, path: str) -> tuple[Any, str | None]:
    code, out, err = run(["api", "-X", "GET", path])
    if code != 0:
        text = (err or out or "").strip().splitlines()
        return None, (text[-1] if text else f"gh answered {code}")[:200]
    try:
        return json.loads(out or "null"), None
    except ValueError:
        return None, "gh's answer was not JSON"


def _environment(doc: dict[str, Any], own: dict[str, Any], plat: dict[str, Any]) -> dict[str, Any]:
    rules = doc.get("protection_rules") or []
    reviewers = sum(len(r.get("reviewers") or []) for r in rules if r.get("type") == "required_reviewers")
    wait = next((r.get("wait_timer") for r in rules if r.get("type") == "wait_timer"), 0) or 0
    policy = doc.get("deployment_branch_policy") or {}
    placed = kplaces.place(doc.get("name"), own, plat)       # by whole words; unknown is held as production
    return {"name": str(doc.get("name") or ""), "env": placed["env"], "placed": placed["how"],
            "placed_says": placed["says"], "required_reviewers": reviewers,
            "wait_minutes": int(wait), "protected_branches_only": bool(policy.get("protected_branches")),
            "custom_branches": bool(policy.get("custom_branch_policies"))}


def _classic(doc: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    """The classic branch protection: on or off, and what it asks; ``readable`` False when it was not read."""
    if doc is None:
        unprotected = bool(error and "not protected" in error.lower())
        return {"protected": False, "readable": unprotected, "why": None if unprotected else error,
                "pull_request": False, "required_reviews": 0, "required_checks": [], "admins_too": False}
    reviews = doc.get("required_pull_request_reviews")
    checks = doc.get("required_status_checks") or {}
    names = [c.get("context") for c in checks.get("checks") or [] if c.get("context")]
    names = names or list(checks.get("contexts") or [])
    return {"protected": True, "readable": True, "why": None, "pull_request": reviews is not None,
            "required_reviews": int((reviews or {}).get("required_approving_review_count") or 0),
            "required_checks": names[:20], "admins_too": bool((doc.get("enforce_admins") or {}).get("enabled"))}


def _rules(rules: Any, error: str | None, named: Any) -> dict[str, Any]:
    """The repository rulesets in force on the branch (``rules/branches/<b>``): a pull request, reviews, checks."""
    if not isinstance(rules, list):
        return {"readable": False, "why": error, "any": False, "pull_request": False, "required_reviews": 0,
                "required_checks": [], "rulesets": []}
    pr = [_params(r) for r in rules if r.get("type") == "pull_request"]
    reviews = max((int(p.get("required_approving_review_count") or 0) for p in pr), default=0)
    checks = [c.get("context") for r in rules if r.get("type") == "required_status_checks"
              for c in _params(r).get("required_status_checks") or []]
    return {"readable": True, "why": None, "any": bool(rules), "pull_request": bool(pr), "required_reviews": reviews,
            "required_checks": [c for c in checks if c][:20], "rulesets": _named(rules, named)}


def _params(rule: dict[str, Any]) -> dict[str, Any]:
    return rule.get("parameters") or {}


def _named(rules: list[dict[str, Any]], named: Any) -> list[dict[str, Any]]:
    """The rulesets in force on the branch, by name where the rulesets' list says it."""
    names = {r.get("id"): str(r.get("name") or "") for r in named or [] if isinstance(r, dict)}
    ids = sorted({str(r["ruleset_id"]) for r in rules if r.get("ruleset_id") is not None})
    names = {str(k): v for k, v in names.items()}
    return [{"id": i, "name": names.get(i) or f"ruleset {i}"} for i in ids]


def _protection(classic: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """The branch's protection from both places GitHub keeps it: classic protection and repository rulesets."""
    sources = (["branch protection"] if classic["protected"] else []) + [
        f"ruleset {r['name']}" for r in rules["rulesets"]]
    checks = list(dict.fromkeys(classic["required_checks"] + rules["required_checks"]))
    readable = classic["readable"] or (rules["readable"] and rules["any"])
    return {"protected": classic["protected"] or rules["any"], "readable": readable,
            "why": None if readable else classic["why"],
            "pull_request": classic["pull_request"] or rules["pull_request"],
            "required_reviews": max(classic["required_reviews"], rules["required_reviews"]),
            "required_checks": checks[:20], "admins_too": classic["admins_too"], "sources": sources,
            "rulesets": rules["rulesets"], "rulesets_why": rules["why"]}


def read(project: Any, run: Runner | None = None) -> dict[str, Any]:
    """What the project's GitHub pipeline holds, or why it was not read and how it could be."""
    run = run or gh
    slug, source = repo_of(project)
    if slug is None:
        return {"read": False, "why": source, "how": "Name the repository (owner/name) in this view, or adopt the "
                                                     "project from a folder with a GitHub remote"}
    repo, error = _get(run, f"repos/{slug}")
    if repo is None:
        return {"read": False, "repo": slug, "why": error, "how": SIGN_IN}
    branch = str(repo.get("default_branch") or "main")
    envs, env_error = _get(run, f"repos/{slug}/environments")
    prot, prot_error = _get(run, f"repos/{slug}/branches/{branch}/protection")
    rules, rules_error = _get(run, f"repos/{slug}/rules/branches/{branch}")
    named = _get(run, f"repos/{slug}/rulesets")[0] if rules else None
    own, plat = ke.project_settings(project), ke.platform_settings(project.factory)
    return {"read": True, "repo": slug, "from": source, "branch": branch,
            "environments": [_environment(e, own, plat) for e in (envs or {}).get("environments") or []],
            "environments_why": env_error,
            "protection": _protection(_classic(prot, prot_error), _rules(rules, rules_error, named)),
            "url": f"https://github.com/{slug}/settings"}


# -- where Rihmasto and the pipeline agree or differ -------------------------------------------------------

def _main_line(pipe: dict[str, Any]) -> tuple[bool | None, str]:
    """Whether the main line asks a person before a merge, from classic protection and rulesets together."""
    prot, branch = pipe["protection"], pipe["branch"]
    if not prot["readable"]:
        return None, f"the branch protection of {branch} could not be read ({prot['why']})"
    by = f" ({', '.join(prot.get('sources') or [])})" if prot.get("sources") else ""
    checks = f" and the checks {', '.join(prot['required_checks'])}" if prot["required_checks"] else ""
    n = prot["required_reviews"]
    if n:
        return True, f"{branch} needs {ke.count(n, 'approving review')}{checks} before a merge{by}"
    if prot.get("pull_request"):
        return False, (f"{branch} takes changes only through a pull request{checks}, without a required approving "
                       f"review{by}")
    if prot["protected"]:
        return False, f"{branch} is protected{checks}{by}, without a pull request or a review"
    return False, f"{branch} takes a merge without a review"


def _pipeline_human(env: str, pipe: dict[str, Any]) -> tuple[bool | None, str]:
    if env == "dev":
        return _main_line(pipe)
    mine = [e for e in pipe["environments"] if e["env"] == env]
    if not mine:
        return None, f"no GitHub environment is named for {env}"
    held = [e for e in mine if e["required_reviewers"]]
    if held:
        return True, ", ".join(f"{e['name']} needs a reviewer before a deployment" for e in held)
    return False, ", ".join(f"{e['name']} deploys without a reviewer" for e in mine)


def _row(env: str, strictest: str, pipe: dict[str, Any]) -> dict[str, Any]:
    ours = ke.RANK[strictest] >= ke.RANK["require_review"]
    theirs, said = _pipeline_human(env, pipe)
    if theirs is None:
        state, todo = "unknown", "Nothing to compare: " + said + "."
    elif theirs == ours:
        state, todo = "agree", "Both ask for a person here." if ours else "Neither asks for a person here."
    elif theirs:
        state, todo = "pipeline_stricter", ("The pipeline holds it for a person; Rihmasto only " + strictest.replace(
            "_", " ") + "s here. Take the pipeline's split to match, or keep it: the pipeline still holds.")
    else:
        state, todo = "rihmasto_stricter", ("Rihmasto asks for a person; the pipeline does not. To make GitHub agree, "
                                            "add required reviewers in the repository's settings (Rihmasto never "
                                            "changes them), or keep Rihmasto as the check.")
    return {"env": env, "state": state, "rihmasto": strictest, "rihmasto_human": ours, "pipeline_human": theirs,
            "pipeline_says": said, "todo": todo}


def compare(described: dict[str, Any], pipe: dict[str, Any]) -> dict[str, Any]:
    if not pipe.get("read"):
        return {"rows": [], "suggested": None}
    rows = [_row(e, described["strictest"][e], pipe) for e in ke.ENVIRONMENTS]
    suggested = {r["env"]: {"governance": "enforce" if r["pipeline_human"] else "advise"}
                 for r in rows if r["pipeline_human"] is not None}
    return {"rows": rows, "suggested": suggested or None}
