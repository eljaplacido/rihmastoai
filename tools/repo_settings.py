"""Check that the public repository's GitHub settings are what docs/maintainers.md says (FR-PUB2). Read only.

    python tools/repo_settings.py check                         # the public repository
    python tools/repo_settings.py check --repo owner/name
    python tools/repo_settings.py check --write-fix rs.json     # also writes the corrected ruleset body

It reads the settings with the GitHub CLI (`gh api`, GET only) and lists every one that differs from
the documented one, with the command that sets it. It changes nothing on GitHub: the settings are the
owner's to set, so the owner runs the commands it prints. ``--write-fix`` writes the ruleset as it
should be to a local file, for ``gh api -X PUT repos/<repo>/rulesets/<id> --input <file>``.

Exit 0 when every setting matches, 1 when one differs, 2 when the settings cannot be read.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = "eljaplacido/rihmastoai"
REQUIRED_CHECKS = ("ubuntu-latest, Python 3.11", "ubuntu-latest, Python 3.12", "windows-latest, Python 3.11",
                   "windows-latest, Python 3.12", "DCO sign-off")
PULL_REQUEST = {"required_approving_review_count": 1, "require_code_owner_review": True,
                "dismiss_stale_reviews_on_push": True, "allowed_merge_methods": ["squash"]}
REPO_FLAGS = {"allow_squash_merge": True, "allow_merge_commit": False, "allow_rebase_merge": False,
              "delete_branch_on_merge": True, "has_discussions": True,
              "squash_merge_commit_title": "COMMIT_OR_PR_TITLE", "squash_merge_commit_message": "COMMIT_MESSAGES"}
SECURITY = ("secret_scanning", "secret_scanning_push_protection", "dependabot_security_updates")
# What a ruleset GET returns that a PUT does not take.
READ_ONLY = ("id", "node_id", "source", "source_type", "created_at", "updated_at", "_links", "current_user_can_bypass")

Fetch = Callable[[str], tuple[int, Any]]


def gh_fetch(path: str) -> tuple[int, Any]:
    """GET ``path`` with the GitHub CLI: (HTTP status, JSON body or None)."""
    proc = subprocess.run(["gh", "api", "--include", path], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    head, _, body = (proc.stdout or "").replace("\r\n", "\n").partition("\n\n")
    first = head.split("\n", 1)[0].split()
    if len(first) < 2 or not first[1].isdigit():
        raise RuntimeError(f"gh api {path}: {(proc.stderr or proc.stdout).strip() or 'no answer'}")
    try:
        data = json.loads(body) if body.strip() else None
    except ValueError:
        data = None
    return int(first[1]), data


def _gap(setting: str, found: Any, wanted: Any, fix: str) -> dict[str, Any]:
    return {"setting": setting, "found": found, "wanted": wanted, "fix": fix}


def main_ruleset(fetch: Fetch, repo: str) -> dict[str, Any] | None:
    """The active branch ruleset that covers the default branch, read in full, or None."""
    status, listed = fetch(f"repos/{repo}/rulesets")
    for r in listed if status == 200 and isinstance(listed, list) else []:
        if r.get("target") == "branch" and r.get("enforcement") == "active":
            status, full = fetch(f"repos/{repo}/rulesets/{r['id']}")
            include = ((full or {}).get("conditions") or {}).get("ref_name", {}).get("include", [])
            if status == 200 and ("~DEFAULT_BRANCH" in include or "refs/heads/main" in include):
                return full
    return None


def _rule(ruleset: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((r for r in ruleset.get("rules") or [] if r.get("type") == kind), None)


def _pull_request_gaps(ruleset: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    params = (_rule(ruleset, "pull_request") or {}).get("parameters")
    if params is None:
        return [("require a pull request", None, "on")]
    out = []
    for key, wanted in PULL_REQUEST.items():
        found = params.get(key)
        bad = (found or 0) < wanted if key == "required_approving_review_count" else found != wanted
        if bad:
            out.append((f"pull request: {key}", found, wanted))
    return out


def _checks_gaps(ruleset: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    params = (_rule(ruleset, "required_status_checks") or {}).get("parameters") or {}
    have = {c.get("context") for c in params.get("required_status_checks") or []}
    out = [("required checks", sorted(have), list(REQUIRED_CHECKS))] if not set(REQUIRED_CHECKS) <= have else []
    if params.get("strict_required_status_checks_policy") is not True:
        out.append(("required checks: branches up to date", params.get("strict_required_status_checks_policy"), True))
    return out


def ruleset_gaps(ruleset: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """What the ruleset for main lacks: (setting, found, wanted)."""
    out = [(f"rule {k}", None, "on") for k in ("deletion", "non_fast_forward") if _rule(ruleset, k) is None]
    out += _pull_request_gaps(ruleset) + _checks_gaps(ruleset)
    modes = [a.get("bypass_mode") for a in ruleset.get("bypass_actors") or []]
    if any(m != "pull_request" for m in modes):
        out.append(("bypass list: pull requests only", modes, ["pull_request"] * len(modes)))
    return out


def _params(rules: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    """The parameters of the rule of this kind, added when the ruleset lacks it."""
    rule = next((r for r in rules if r.get("type") == kind), None)
    if rule is None:
        rule = {"type": kind, "parameters": {}}
        rules.append(rule)
    return rule.setdefault("parameters", {})


def fixed_ruleset(ruleset: dict[str, Any]) -> dict[str, Any]:
    """The ruleset as docs/maintainers.md says it should be, as a PUT body."""
    body = {k: v for k, v in json.loads(json.dumps(ruleset)).items() if k not in READ_ONLY}
    rules = [r for r in body.get("rules") or [] if r.get("type") not in ("deletion", "non_fast_forward")]
    rules = [{"type": "deletion"}, {"type": "non_fast_forward"}] + rules
    _params(rules, "pull_request").update(PULL_REQUEST)
    params = _params(rules, "required_status_checks")
    have = {c.get("context") for c in params.get("required_status_checks") or []}
    params["required_status_checks"] = (params.get("required_status_checks") or []) + [
        {"context": c} for c in REQUIRED_CHECKS if c not in have]
    params["strict_required_status_checks_policy"] = True
    body["rules"] = rules
    body["bypass_actors"] = [{**a, "bypass_mode": "pull_request"} for a in body.get("bypass_actors") or []]
    return body


def _ruleset_section(fetch: Fetch, repo: str, fix_file: str) -> tuple[list[dict[str, Any]], dict | None]:
    ruleset = main_ruleset(fetch, repo)
    if ruleset is None:
        return [_gap("a ruleset for main", None, "active",
                     "Settings, Rules, Rulesets: add one as docs/maintainers.md says")], None
    put = f"gh api -X PUT repos/{repo}/rulesets/{ruleset['id']} --input {fix_file}"
    gaps = [_gap(s, f, w, put) for s, f, w in ruleset_gaps(ruleset)]
    return gaps, (fixed_ruleset(ruleset) if gaps else None)


def _repo_section(fetch: Fetch, repo: str) -> list[dict[str, Any]]:
    status, data = fetch(f"repos/{repo}")
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError(f"cannot read repos/{repo} (HTTP {status})")
    out = [_gap(k, data.get(k), v, f"gh api -X PATCH repos/{repo} -F {k}={json.dumps(v).strip(chr(34))}")
           for k, v in REPO_FLAGS.items() if data.get(k) != v]
    sa = data.get("security_and_analysis") or {}
    for key in SECURITY:
        found = (sa.get(key) or {}).get("status")
        if found != "enabled":
            fix = (f"gh api -X PUT repos/{repo}/automated-security-fixes" if key == "dependabot_security_updates"
                   else f"gh api -X PATCH repos/{repo} -f 'security_and_analysis[{key}][status]=enabled'")
            out.append(_gap(key, found, "enabled", fix))
    return out


def _endpoint_section(fetch: Fetch, repo: str) -> list[dict[str, Any]]:
    out = []
    status, _ = fetch(f"repos/{repo}/vulnerability-alerts")       # 204: on, 404: off
    if status != 204:
        out.append(_gap("Dependabot alerts", "off" if status == 404 else f"HTTP {status}", "on",
                        f"gh api -X PUT repos/{repo}/vulnerability-alerts"))
    status, pvr = fetch(f"repos/{repo}/private-vulnerability-reporting")
    if not (status == 200 and (pvr or {}).get("enabled") is True):
        out.append(_gap("private vulnerability reporting", (pvr or {}).get("enabled"), True,
                        f"gh api -X PUT repos/{repo}/private-vulnerability-reporting"))
    _, wf = fetch(f"repos/{repo}/actions/permissions/workflow")
    token = (wf or {}).get("default_workflow_permissions")
    if token != "read":
        fix = f"gh api -X PUT repos/{repo}/actions/permissions/workflow -f default_workflow_permissions=read"
        out.append(_gap("workflow token: read-only", token, "read", fix))
    return out


def check(fetch: Fetch, repo: str = REPO, fix_file: str = "rs.json") -> dict[str, Any]:
    """Every documented setting that differs, with its fix, and the corrected ruleset body when it needs one."""
    gaps, fixed = _ruleset_section(fetch, repo, fix_file)
    gaps += _repo_section(fetch, repo) + _endpoint_section(fetch, repo)
    return {"repo": repo, "ok": not gaps, "gaps": gaps, "fixed_ruleset": fixed}


def report(result: dict[str, Any]) -> str:
    if result["ok"]:
        return f"{result['repo']}: every documented setting matches.\n"
    lines = [f"{result['repo']}: {len(result['gaps'])} setting(s) differ from docs/maintainers.md. The owner sets "
             "them; run each command below (nothing here changed GitHub):"]
    for g in result["gaps"]:
        lines.append(f"- {g['setting']}: found {json.dumps(g['found'])}, wanted {json.dumps(g['wanted'])}")
    for fix in dict.fromkeys(g["fix"] for g in result["gaps"]):
        lines.append(f"    {fix}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, fetch: Fetch = gh_fetch) -> int:
    ap = argparse.ArgumentParser(prog="repo_settings", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="compare the live settings with the documented ones (read only)")
    c.add_argument("--repo", default=REPO)
    c.add_argument("--write-fix", metavar="FILE", help="write the corrected ruleset body to this local file")
    c.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)
    try:
        result = check(fetch, args.repo, args.write_fix or "rs.json")
    except (RuntimeError, OSError) as exc:
        print(f"repo_settings: {exc}", file=sys.stderr)
        return 2
    if args.write_fix and result["fixed_ruleset"] is not None:
        Path(args.write_fix).write_text(json.dumps(result["fixed_ruleset"], indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2) if args.json else report(result), end="" if not args.json else "\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
