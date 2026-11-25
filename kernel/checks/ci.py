"""CI/CD status (FR-CHK1): the latest workflow runs on the repository's default branch.

In this order:
1. the GitHub API, when a token is configured: the variable this check's ``token_env`` names (default
   ``GITHUB_TOKEN``), the same ``env:`` reference a connector's credentials use. Its value is sent as the
   bearer token to the API and nowhere else; it is never shown, recorded or put in a command line. ``api``
   may name a GitHub Enterprise address (https, or a loopback address for a test);
2. else ``gh run list``, when the GitHub CLI is installed (it uses its own sign-in);
3. else not measured, saying which of these was missing.

The repository is ``repo`` (``owner/name``), else read from the workspace's ``origin``. The branch is
``branch``, else the repository's default branch. The latest finished run decides: success passes; failure,
a timeout or a cancellation fails; no finished run is not measured.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from kernel.checks import Check, Ctx, not_measured, result
from kernel.checks.tools import json_of, run_tool

DEFAULT_API = "https://api.github.com"
_SLUG = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
_REMOTE = re.compile(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?\Z")
_ENV = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
PASS = ("success",)
FAIL = ("failure", "timed_out", "cancelled", "startup_failure", "action_required")


def _api(ctx: Ctx) -> str:
    api = str(ctx.config.get("api") or DEFAULT_API).rstrip("/")
    parts = urllib.parse.urlsplit(api)
    loopback = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise ValueError("the CI check's api is an https address (or a loopback http one, for a test)")
    return api


def _repo(ctx: Ctx) -> str | None:
    named = str(ctx.config.get("repo") or "").strip()
    if named:
        if not _SLUG.match(named):
            raise ValueError("repo is owner/name")
        return named
    from kernel.attach import git

    try:
        root, _ = ctx.workspace()
    except ValueError:
        return None
    url = git(root, "remote", "get-url", "origin", check=False)
    m = _REMOTE.search(url.strip())
    return m.group(1) if m else None


def _get(url: str, token: str, timeout: float = 20) -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "rihmasto-checks",
               "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def _name(run: dict[str, Any], default: str = "run") -> str:
    return str(run.get("name") or run.get("workflowName") or default)


def _line(run: dict[str, Any]) -> str:
    sha = str(run.get("head_sha") or run.get("headSha") or "")[:12]
    return f"{_name(run)}: {run.get('status')} / {run.get('conclusion')} ({sha})"


def _verdict(runs: list[dict[str, Any]], source: str, branch: str) -> dict[str, Any]:
    finished = [r for r in runs if str(r.get("status") or "").lower() == "completed"]
    lines = [_line(r) for r in runs[:5]]
    if not finished:
        return not_measured(f"no finished run on {branch} ({source})", lines, source=source)
    latest = finished[0]
    conclusion = str(latest.get("conclusion") or "").lower()
    name = _name(latest, "the latest run")
    if conclusion in PASS:
        return result("passed", f"{name} on {branch}: {conclusion} ({source})", lines, source=source)
    if conclusion in FAIL:
        return result("failed", f"{name} on {branch}: {conclusion} ({source})", lines, source=source)
    return not_measured(f"{name} on {branch} ended {conclusion or 'without a conclusion'} ({source})", lines,
                        source=source)


def _by_api(ctx: Ctx, repo: str, token: str) -> dict[str, Any]:
    api = _api(ctx)
    try:
        branch = str(ctx.config.get("branch") or _get(f"{api}/repos/{repo}", token).get("default_branch") or "")
        if not branch:
            return not_measured(f"{repo} names no default branch", source="GitHub API")
        query = urllib.parse.urlencode({"branch": branch, "per_page": 10})
        doc = _get(f"{api}/repos/{repo}/actions/runs?{query}", token)
    except urllib.error.HTTPError as exc:
        exc.close()
        return not_measured(f"the GitHub API answered {exc.code} for {repo}", source="GitHub API")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return not_measured(f"the GitHub API could not be reached ({type(exc).__name__})", source="GitHub API")
    runs = doc.get("workflow_runs") if isinstance(doc, dict) else None
    return _verdict(runs if isinstance(runs, list) else [], "GitHub API", branch)


def _by_gh(ctx: Ctx, repo: str | None) -> dict[str, Any]:
    branch = str(ctx.config.get("branch") or "")
    if not branch:
        ran = run_tool(ctx, ["gh", "repo", "view", *([repo] if repo else []), "--json", "defaultBranchRef"],
                       timeout=60)
        doc = json_of(ran.out) if ran.code == 0 else None
        branch = str(((doc or {}).get("defaultBranchRef") or {}).get("name") or "") if isinstance(doc, dict) else ""
        if not branch:
            return not_measured(ran.why or "gh could not say the repository's default branch", ran.tail(3),
                                source="gh run list")
    ran = run_tool(ctx, ["gh", "run", "list", *(["--repo", repo] if repo else []), "--branch", branch, "--limit", "10",
                         "--json", "name,workflowName,status,conclusion,headSha,createdAt"], timeout=60)
    runs = json_of(ran.out) if ran.code == 0 else None
    if not isinstance(runs, list):
        return not_measured(ran.why or "gh run list gave no runs it could read", ran.tail(3), source="gh run list")
    return _verdict(runs, "gh run list", branch)


def ci(ctx: Ctx) -> dict[str, Any]:
    env_name = str(ctx.config.get("token_env") or "GITHUB_TOKEN").removeprefix("env:")   # a connector's reference
    if not _ENV.match(env_name):
        raise ValueError("token_env names an environment variable (GITHUB_TOKEN)")
    repo = _repo(ctx)
    token = ctx.environ.get(env_name)
    if token and repo:
        return _by_api(ctx, repo, token)
    if ctx.which("gh"):
        return _by_gh(ctx, repo)
    missing = [f"{env_name} is not set" if not token else "", "" if repo else "the repository is not known (give "
               "repo as owner/name, or a workspace whose origin is on GitHub)", "the GitHub CLI (gh) is not installed"]
    return not_measured("; ".join(m for m in missing if m))


CHECKS = (Check("ci", "CI/CD status", "the latest CI/CD runs on the repository's default branch: the GitHub API with "
                "a token, else gh run list", ci, options=("repo", "branch", "token_env", "api"), every="1h"),)
