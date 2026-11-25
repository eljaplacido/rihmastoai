"""Fix and pull request: a bug an investigation found, fixed through the gate and sent as a pull request on a
person's approval (FR-HEAL1, D-0024 item 1).

A fix is a **reproducing test** and the **change**, each a whole file with its path (written by a Rihma agent in
an investigation, kernel/heal_investigate.py, or handed in by a person). ``prepare`` takes it the normal way:

- into a working clone under the factory home (``heal/fixes/F-0001/work``), never the person's own working tree,
  on a branch of its own, ``rihmasto/fix-i-0001``;
- **fail-first**: the test is committed first and must fail there (it reproduces the incident), then the change
  is committed and the test must pass;
- the **suite**: the repository's whole unittest suite for a project's repository; for Rihmasto's own repository
  only the reproducing test runs here, and the whole suite runs in CI on the pull request;
- **protected** paths (the contract, a ``.gnomon/`` surface) refused, and the **independent verifier** asked about
  the change (no verifier: not measured, and a gate without its verifier never passes).

Where it goes: a project bug goes to the project's attached repository (its ``origin``), or an adopted one's
upstream; a Rihmasto bug to Rihmasto's development repository (``RIHMASTO_DEV_REPO``, else this checkout).

``open_pr`` needs a person's approval, given in the call, by a persona that may approve (for Rihmasto's own
repository only the owner of this Rihmasto: the IT persona, or the solo person of a solo home, kernel/
heal_approval.py; in team mode the team's roles) and a gate that passed. It pushes the fix's branch only
(never a default branch), and opens the pull request with ``gh`` when it is installed and signed in
(``RIHMASTO_GH`` may name another command); otherwise it returns the branch and the exact commands. Nothing is
merged: the repository's own review decides. Every step is recorded.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from kernel import incidents as inc
from kernel.people import PERSONAS, is_person
from kernel.store import REPO_ROOT, Factory, read_json, records_lock, write_json, write_text

DEV_REPO_ENV = "RIHMASTO_DEV_REPO"
GH_ENV = "RIHMASTO_GH"
PROJECT_APPROVERS = ("developer", "it", "product_owner")
RIHMASTO_APPROVERS = ("it",)
BRANCH_PREFIX = "rihmasto/fix-"
DEFAULT_BRANCHES = ("main", "master", "trunk", "develop")
GIT_ID = ["-c", "user.name=Rihmasto", "-c", "user.email=rihmasto@localhost.invalid", "-c", "commit.gpgsign=false"]
PROTECTED = re.compile(r"(?i)(?:^|/)(?:contract\.json|\.gnomon/|\.git/)")


class FixRefused(ValueError):
    """A fix or a pull request the kernel will not take, with the reason."""


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL)
    if check and proc.returncode != 0:
        raise FixRefused(f"git {args[0]} failed: {inc.mask_text(proc.stderr.strip(), 400)}")
    return proc.stdout.strip()


def _dir(factory: Factory) -> Path:
    return inc.heal_dir(factory) / "fixes"


def get(factory: Factory, fid: str) -> dict[str, Any]:
    if not re.fullmatch(r"F-\d{4,9}", fid or ""):
        raise KeyError(f"no fix {fid}")
    doc = read_json(_dir(factory) / f"{fid}.json", None)
    if not isinstance(doc, dict):
        raise KeyError(f"no fix {fid}")
    return doc


def fixes(factory: Factory, *, incident: str | None = None) -> list[dict[str, Any]]:
    folder = _dir(factory)
    rows = [d for f in sorted(folder.glob("F-*.json")) if isinstance(d := read_json(f, None), dict)] \
        if folder.is_dir() else []
    return [r for r in reversed(rows) if incident is None or r["incident"] == incident]


def target_of(factory: Factory, doc: dict[str, Any], target: str) -> dict[str, Any]:
    """Which repository a fix goes to, its base branch and the remote a pull request opens on."""
    if target == "rihmasto":
        repo = Path(os.environ.get(DEV_REPO_ENV) or REPO_ROOT)
        branch = _git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False) or "main"
        return {"target": "rihmasto", "repo": str(repo), "branch": branch,
                "remote": _git(repo, "remote", "get-url", "origin", check=False) or None}
    if target != "project":
        raise FixRefused("a fix goes to the project's repository (project) or to Rihmasto's own (rihmasto)")
    if not doc.get("project"):
        raise FixRefused(f"{doc['id']} belongs to no project: a project fix needs the project's repository")
    project = factory.project(doc["project"])
    attached = project.meta.get("attached") or {}
    if attached.get("repo"):
        repo = Path(attached["repo"])
        return {"target": "project", "repo": str(repo), "branch": attached.get("branch") or "main",
                "remote": _git(repo, "remote", "get-url", "origin", check=False) or None}
    bare = project.path("repo.git")
    if bare.is_dir():
        return {"target": "project", "repo": str(bare), "branch": "main",
                "remote": _git(bare, "config", "--get", "remote.upstream.url", check=False) or None}
    raise FixRefused(f"{project.pid} has no repository of its own (attached or adopted) to fix")


def _checked_files(fix: Any) -> tuple[dict[str, str], list[dict[str, str]], str]:
    if not isinstance(fix, dict) or not isinstance(fix.get("test"), dict) or not isinstance(fix.get("change"), list):
        raise FixRefused("a fix is a reproducing test {path, content} and the change [{path, content}]")
    files = [fix["test"], *fix["change"]]
    for f in files:
        path = str((f or {}).get("path") or "")
        pure = PurePosixPath(path.replace("\\", "/"))
        if not path or pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", path):
            raise FixRefused(f"{path!r} is not a path inside the repository")
        if PROTECTED.search(pure.as_posix()):
            raise FixRefused(f"{path} is protected: a fix never changes the contract, a .gnomon/ surface or .git")
        if not isinstance(f.get("content"), str):
            raise FixRefused(f"{path} has no content")
    names = re.findall(r"def (test_\w+)\s*\(", fix["test"]["content"])
    if not names:
        raise FixRefused("the reproducing test names no test_ function")
    return fix["test"], fix["change"], names[0]


def _write(work: Path, f: dict[str, str]) -> None:
    write_text(work / PurePosixPath(f["path"].replace("\\", "/")), f["content"])


def _outcome(run: dict[str, Any], name: str) -> str | None:
    return (run.get("tests") or {}).get(name)


def _gate(work: Path, base: str, head: str, name: str, test_sha: str, target: str, verifier: Any,
          label: str) -> dict[str, Any]:
    from kernel.gate import (
        GateResult,
        Signal,
        _conclude,
        _verifier_signal,
        change_verifier_prompt,
        run_suite,
        signal_protected,
        signal_tests,
    )

    _git(work, "checkout", "-q", test_sha)
    before = run_suite(work, pattern=name)
    _git(work, "checkout", "-q", head)
    after = run_suite(work, pattern=name)
    b, a = _outcome(before, name), _outcome(after, name)
    if b in ("FAIL", "ERROR") and a == "ok":
        ff = Signal("fail_first", "passed", {"before": b, "after": a}, f"{name} fails before the change, passes after")
    elif b is None or a is None:
        ff = Signal("fail_first", "not measured", {"before": b, "after": a}, f"{name} did not run")
    else:
        ff = Signal("fail_first", "failed", {"before": b, "after": a},
                    f"{name} is {b} before the change and {a} after: it must fail first, then pass")
    if target == "project":
        tests = signal_tests(work, run=run_suite(work))
    else:
        tests = Signal("tests", "passed" if a == "ok" else "failed", {"ran": after.get("ran")},
                       "the reproducing test here; the whole suite runs in CI on the pull request")
    guard = signal_protected(work, base, head)
    if guard is not None:
        verdict = guard
    elif verifier is None:
        verdict = Signal("verifier", "not measured", {}, "no verifier was set up for fixes: a gate without its "
                                                         "independent verifier is never passed")
    else:
        prompt = change_verifier_prompt({"requirements": []}, base, "a Rihma agent's fix")
        verdict = _verifier_signal(work, prompt, runner=verifier)
    result = _conclude(GateResult(task=label, base=base, head=head, signals=[tests, ff, verdict]))
    return {"verdict": result.verdict, "warranted": result.warranted, "objections": result.objections,
            "signals": [{"name": s.name, "verdict": s.verdict, "detail": s.detail} for s in result.signals]}


def _commits(work: Path, where: dict[str, Any], branch: str, test: dict[str, str], change: list[dict[str, str]],
             said: str) -> tuple[str, str, str]:
    """A working clone on its own branch: the reproducing test committed, then the change. (base, test, head)."""
    shutil.rmtree(work, ignore_errors=True)
    work.parent.mkdir(parents=True, exist_ok=True)
    _git(work.parent, "clone", "-q", "--no-hardlinks", "--branch", where["branch"], where["repo"], "work")
    base = _git(work, "rev-parse", "HEAD")
    _git(work, "checkout", "-q", "-b", branch)
    shas = []
    for files, message in (([test], f"Reproduce {said}"), (change, f"Fix {said}")):
        for f in files:
            _write(work, f)
        _git(work, "add", "-A")
        _git(work, *GIT_ID, "commit", "-q", "-m", message)
        shas.append(_git(work, "rev-parse", "HEAD"))
    return base, shas[0], shas[1]


def _number(factory: Factory, iid: str) -> str:
    """The next fix's id, its record made at once so two fixes never share one."""
    with records_lock(inc.heal_dir(factory) / "fixes.lock"):
        fid = f"F-{max([int(f['id'][2:]) for f in fixes(factory)] or [0]) + 1:04d}"
        write_json(_dir(factory) / f"{fid}.json", {"id": fid, "incident": iid, "state": "preparing"})
    return fid


def prepare(factory: Factory, iid: str, *, person: str, persona: str, fix: dict[str, Any] | None = None,
            target: str | None = None, verifier: Any = None) -> dict[str, Any]:
    """Take a fix for incident ``iid`` through the gate on a branch of its own. Returns the fix record."""
    if not is_person(person) or persona not in PERSONAS:
        raise FixRefused(f"{person!r} is not a person with a persona: a person asks for a fix")
    doc = inc.get(factory, iid)
    found = doc.get("investigation") or {}
    fix = fix or found.get("fix") or {}
    test, change, name = _checked_files(fix)
    target = target or ("rihmasto" if found.get("classification") == "rihmasto bug" else "project")
    where = target_of(factory, doc, target)
    fid = _number(factory, iid)
    work = _dir(factory) / fid / "work"
    branch = BRANCH_PREFIX + iid.lower()
    summary = str(fix.get("summary") or "")[:500]
    base, test_sha, head = _commits(work, where, branch, test, change, f"{iid}: {(summary or doc['summary'])[:60]}")
    gate = _gate(work, base, head, name, test_sha, target, verifier, f"fix:{iid}")
    _git(work, "checkout", "-q", branch)
    record = {"id": fid, "incident": iid, "project": doc.get("project"), "target": target, "repo": where["repo"],
              "remote": inc.mask_text(where["remote"] or "", 300) or None, "base_branch": where["branch"],
              "branch": branch, "base": base, "test_commit": test_sha, "head": head, "test": name,
              "files": [test["path"], *[f["path"] for f in change]], "summary": summary, "gate": gate,
              "state": "gated" if gate["verdict"] == "passed" else "gate_not_passed",
              "prepared": {"person": person, "persona": persona, "at": factory.clock.stamp()}, "pr": None}
    write_json(_dir(factory) / f"{fid}.json", record)
    inc.update(factory, iid, event="incident_fix_prepared", person=person, persona=persona,
               note=f"{fid} on {branch}: the gate says {gate['verdict']}",
               fix={"id": fid, "verdict": gate["verdict"], "target": target, "branch": branch})
    return record


def _gh() -> list[str] | None:
    raw = os.environ.get(GH_ENV)
    if raw:
        try:
            cmd = json.loads(raw)
            return [str(x) for x in cmd] if isinstance(cmd, list) and cmd else None
        except ValueError:
            return None
    found = shutil.which("gh")
    return [found] if found else None


def _github_repo(remote: str | None) -> str | None:
    m = re.search(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", remote or "")
    return m.group(1) if m else None


def _may_open(factory: Factory, fix: dict[str, Any], person: str, persona: str, approve: bool) -> None:
    """Refuse a pull request without a person's approval, a permitted persona (or the solo person, kernel/
    heal_approval.py), a passed gate and a fix branch."""
    from kernel.heal_approval import approvers, may_approve

    if not is_person(person) or persona not in PERSONAS:
        raise FixRefused(f"{person!r} is not a person with a persona: a person approves a pull request")
    if approve is not True:
        raise FixRefused("a pull request opens only on a person's approval: approve it first")
    allowed = RIHMASTO_APPROVERS if fix["target"] == "rihmasto" else PROJECT_APPROVERS
    if not may_approve(factory, person, persona, allowed):
        who = ("the owner of this Rihmasto (the IT persona, or the solo person)" if fix["target"] == "rihmasto"
               else approvers(allowed))
        raise FixRefused(f"a pull request from this fix is approved by {who}, not {persona}")
    if fix["gate"]["verdict"] != "passed":
        raise FixRefused(f"the gate did not pass {fix['id']} ({fix['gate']['verdict']}): "
                         + "; ".join(fix["gate"]["objections"][:3]))
    if (fix.get("pr") or {}).get("url"):
        raise FixRefused(f"{fix['id']} already has its pull request: {fix['pr']['url']}")
    branch = fix["branch"]
    if not branch.startswith(BRANCH_PREFIX) or branch in (*DEFAULT_BRANCHES, fix["base_branch"]):
        raise FixRefused(f"{branch} is not a fix branch: Rihmasto never pushes to a default branch")


def _create_args(factory: Factory, fix: dict[str, Any], remote: str, person: str, persona: str) -> list[str]:
    """``gh pr create``'s arguments, its body in a file (a body has new lines, which a launcher may not pass)."""
    said = re.sub(r"[^\w .,:()/-]", "", fix.get("summary") or "a bug Rihmasto found")[:80]
    signals = "; ".join(f"{s['name']} {s['verdict']}" for s in fix["gate"]["signals"])
    body = (f"Prepared by Rihmasto from incident {fix['incident']} and approved by {person} ({persona}).\n\n"
            f"Gate: {fix['gate']['verdict']} - {signals}\nReproducing test: {fix['test']}\n\n"
            "Nothing is merged by Rihmasto: review it here.\n")
    body_file = _dir(factory) / fix["id"] / "PR_BODY.md"
    write_text(body_file, body)
    repo = _github_repo(remote)
    return ["pr", "create", "--base", fix["base_branch"], "--head", fix["branch"], "--title",
            f"Fix {fix['incident']}: {said}", "--body-file", str(body_file), *(["--repo", repo] if repo else [])]


def _push_and_create(work: Path, remote: str, branch: str, gh: list[str], create: list[str]) -> str:
    """Push the fix's branch (only it) and open the pull request; its address."""
    _git(work, "push", "-q", remote, f"refs/heads/{branch}:refs/heads/{branch}")
    made = subprocess.run([*gh, *create], cwd=work, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace")
    if made.returncode != 0:
        raise FixRefused(f"gh pr create failed: {inc.mask_text(made.stderr.strip(), 300)}; the branch {branch} "
                         "is pushed: open its pull request by hand")
    return next((w for w in made.stdout.split() if w.startswith("http")), made.stdout.strip()[:300])


def open_pr(factory: Factory, fid: str, *, person: str, persona: str, approve: bool = False) -> dict[str, Any]:
    """On a person's approval, push the fix's branch and open its pull request (or say exactly how)."""
    fix = get(factory, fid)
    _may_open(factory, fix, person, persona, approve)
    branch = fix["branch"]
    work = _dir(factory) / fid / "work"
    remote = (target_of(factory, inc.get(factory, fix["incident"]), fix["target"]) or {}).get("remote")
    if not remote:
        raise FixRefused("the repository has no remote to open a pull request on: add one (git remote add origin ...)")
    gh, create = _gh(), _create_args(factory, fix, remote, person, persona)
    commands = [f"git -C {work} push {inc.mask_text(remote, 300)} {branch}:{branch}",
                "gh " + " ".join(a if " " not in a else json.dumps(a) for a in create)]
    signed_in = gh is not None and subprocess.run([*gh, "auth", "status"], capture_output=True, text=True,
                                                  stdin=subprocess.DEVNULL).returncode == 0
    pr: dict[str, Any] = {"approved_by": person, "persona": persona, "at": factory.clock.stamp(), "branch": branch}
    if gh is None or not signed_in:
        pr |= {"state": "ready", "url": None, "commands": commands,
               "why": "gh is not installed or not signed in here: run these to open it yourself"}
    else:
        pr |= {"state": "opened", "url": _push_and_create(work, remote, branch, gh, create)}
    fix = fix | {"pr": pr, "state": "pr_opened" if pr["state"] == "opened" else "pr_ready"}
    write_json(_dir(factory) / f"{fid}.json", fix)
    inc.ledger_of(factory, fix.get("project")).log(
        "fix_pr_opened" if pr["state"] == "opened" else "fix_pr_ready",
        {"fix": fid, "incident": fix["incident"], "target": fix["target"], "branch": branch, "url": pr.get("url"),
         "person": person, "persona": persona})
    return fix
