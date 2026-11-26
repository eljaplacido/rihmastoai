"""Workspaces: a real terminal beside the cockpit's chat, and the person in it as a cell.

A person opens a workspace on a project: a clone of the product's `repo.git` on a branch of
their own, `work/<person>/<n>`, under the lanes root (`<lanes root>/workspaces/<pid>/<person>-<n>`).
The kernel writes two files there, both kept out of every commit:

- `RIHMA_CONTEXT.md`: the brief, the spec, the open cards and questions, the `now` line, the
  evidence counts and the rules;
- `.mcp.json`: Rihma's MCP server for this factory home, signed with the person and persona, so
  the agent in the terminal (Gnomon, Claude Code, OpenCode) can read the factory and file
  proposals. It cannot decide anything: the server has no decision tools.

`open_workspace` returns the command a person runs to open their own terminal there. The kernel
never starts it. `launch` is a separate call the cockpit may make on a machine the person sits at.

`submit_workspace` makes the person a cell. The branch's commits meet the SAME gate a builder
cell's do (`kernel.gate`): the project's tests run by the kernel, the criterion trace and
fail-first for the task the person names, and the independent verifier. Warranted and permitted,
they merge into main; otherwise they escalate with every objection. The gate record names the
person as the author. A submission with no commits is refused, and so is one that touches what a
cell may not: the surface, the contract and the factory's files, under any name (a rename, a
quoted name, another case).

A workspace cannot push to the product's main itself: its branch tracks nothing, its `origin` has
no push URL, and the product repository refuses a push to main, a cell's branch or a judged head
that does not come from the kernel (`kernel.lanes.guard_repo`). Its work reaches main only through
`submit_workspace`.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from kernel.canon import Canon
from kernel.git_clone import clone_options
from kernel.lanes import GIT_ID, IGNORED, PROTECTED, Lane, Lanes, _git, guard_repo, lanes_root, protected_paths
from kernel.people import PERSONAS, is_person
from kernel.store import REPO_ROOT, Project, slugify, write_json, write_text

AGENTS = ("gnomon", "claude", "opencode", "shell")
CONTEXT_FILE = "RIHMA_CONTEXT.md"
MCP_FILE = ".mcp.json"
RULE = ("Your changes go through the same gate as an agent's: tests, an independent verifier, then merge; "
        "nothing you do here is a decision.")
# A workspace's `origin` push URL: a transport git does not have, so `git push` from the workspace
# fails; its work goes to the product repository through `submit_workspace` alone.
NO_PUSH = "rihma-submit-through-the-gate://main-is-read-only"


class WorkspaceRefused(ValueError):
    """A workspace that cannot be opened, or a submission the gate will not take."""


def workspaces_root(root=None) -> Path:
    return Path(root or lanes_root()) / "workspaces"


def _registry(project) -> list:
    return project.read("workspaces.json", []) or []


def _check_person(person: str, persona: str) -> None:
    if not is_person(person):
        raise WorkspaceRefused(f"{person!r} is not a person; a workspace belongs to a named person")
    if persona not in PERSONAS:
        raise WorkspaceRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")


# -- the terminal command -----------------------------------------------------------------------------

def agent_command(agent: str, *, system: str | None = None) -> list:
    """What runs inside the terminal: Gnomon (interactive), Claude Code, OpenCode, or the shell."""
    system = system or platform.system()
    if agent == "gnomon":
        from kernel.model import gnomon_cmd

        return gnomon_cmd()
    if agent in ("claude", "opencode"):
        return [agent]
    if agent == "shell":
        if system == "Windows":
            return [os.environ.get("COMSPEC") or "cmd.exe"]
        return [os.environ.get("SHELL") or "/bin/sh"]
    raise WorkspaceRefused(f"agent must be one of {', '.join(AGENTS)}, got {agent!r}")


def terminal_command(path, agent: str, *, system: str | None = None, which=shutil.which) -> list:
    """The argv a person runs to open their own terminal in ``path`` with ``agent`` in it. Run it
    with ``cwd=path``: the last fallback is the agent command alone."""
    system = system or platform.system()
    inner = agent_command(agent, system=system)
    path = str(path)
    if system == "Windows":
        if which("wt.exe") or which("wt"):
            return ["wt.exe", "-d", path, *inner]
        return ["cmd", "/c", "start", "", "/D", path, *inner]
    if which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", *inner]
    if which("gnome-terminal"):
        return ["gnome-terminal", f"--working-directory={path}", "--", *inner]
    if system == "Darwin" and which("open"):
        return ["open", "-a", "Terminal", path]
    return inner


# -- the files the kernel writes there ----------------------------------------------------------------

def mcp_config(factory, *, person: str, persona: str, lanes=None) -> dict:
    """The project-scoped MCP configuration (docs/mcp.md): Rihma's server, signed with the person."""
    args = [str(REPO_ROOT / "mcp" / "server.py"), "--home", str(Path(factory.home).resolve()),
            "--person", person, "--persona", persona]
    if lanes is not None:
        args += ["--lanes", str(Path(lanes).resolve())]
    return {"mcpServers": {"rihma": {"type": "stdio", "command": sys.executable or "python", "args": args}}}


def context_md(project, *, person: str, persona: str, branch: str, base: str, path) -> str:
    from kernel.status import evidence, now

    meta, canon = project.meta, Canon(project)
    spec = project.read("spec.json") or {}
    contract = project.read("contract.json")
    state = now(project)
    rows = evidence(project) if contract else []
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    tasks = project.read("tasks.json", {}) or {}
    submit = (f'python -m kernel.cli workspace submit {project.pid} "{Path(path).as_posix()}" --person "{person}" '
              f"--persona {persona} [--task T-00n]")
    lines = [f"# Rihma workspace: {meta.get('title')}", "",
             f"{person} ({persona}) on project `{project.pid}`, branch `{branch}`, from main at `{base[:12]}`. "
             f"Maturity {meta.get('maturity')}, stage {meta.get('stage')}.", "",
             "## Rules", "",
             f"- {RULE}",
             "- Commit your work on this branch, then submit it from the Rihma repository "
             f"({REPO_ROOT.as_posix()}):", "", f"      {submit}", "",
             "  Name the task you serve with `--task`: its criteria are then traced and must fail first, as for a "
             "builder cell. Without one, the suite and the verifier still judge the change.",
             "- A submission with no commits ahead of main is refused. Uncommitted changes are not submitted.",
             f"- Like a builder cell, you may not change {', '.join(PROTECTED)}: the kernel compiles the surface, "
             "and the contract changes only through the change loop.",
             "- Decisions (answers, approvals, accepting a change, granting trust) are made by people in the "
             "cockpit's Inbox, never here. The `rihma` MCP server in `.mcp.json` reads the factory and files "
             "proposals: a change, a comment, a signal.",
             "- Holdout scenarios are not in this workspace, and never will be.", "",
             "## Now", "", f"{state['state']}: {state['line']}", "",
             "## Evidence", ""]
    if rows:
        lines.append(", ".join(f"{k.replace('_', ' ')} {counts.get(k, 0)}"
                               for k in ("verified", "held_out", "claimed", "failing", "not_measured"))
                     + f" (of {len(rows)} criteria)")
    else:
        lines.append("not measured: no contract yet")
    lines += ["", "## Brief", "", canon.brief.strip() or "(no brief yet)", "", "## Spec", ""]
    if spec:
        lines += [f"{spec.get('title', '')}: {spec.get('summary', '')}", ""]
        for r in spec.get("requirements", []):
            lines.append(f"- **{r['id']}** ({r.get('priority', 'must')}, {r.get('provenance')}): {r['statement']}")
            lines += [f"    - {c['id']} [{c['kind']}]: given {c.get('given') or '-'}; when {c.get('when') or '-'}; "
                      f"then {c['then']}" for c in r.get("acceptance", [])]
    else:
        lines.append("(no spec yet)")
    if contract:
        lines += ["", "## Tasks", ""]
        lines += [f"- {t['id']} ({tasks.get(t['id'], {}).get('status', 'pending')}): {t['title']} "
                  f"[{', '.join(t['criteria'])}]" for t in contract["tasks"]]
    cards = canon.cards()
    lines += ["", "## Open cards", ""]
    lines += [f"- {c['id']} [{c['kind']}]: {c['title']} (decided by {', '.join(c['deciders'])})" for c in cards] \
        or ["(none)"]
    questions = canon.questions("open")
    lines += ["", "## Open questions", ""]
    lines += [f"- {q['id']}{' (blocking)' if q.get('blocking') else ''}: {q['text']}" for q in questions] or ["(none)"]
    return "\n".join(lines) + "\n"


# -- open, launch, list ---------------------------------------------------------------------------------

def open_workspace(project, *, person: str, persona: str, agent: str, root=None) -> dict:
    """Clone the product's repository onto a branch of the person's own and prepare it. Launches
    nothing. Returns {"path", "branch", "agent", "command"}."""
    _check_person(person, persona)
    if agent not in AGENTS:
        raise WorkspaceRefused(f"agent must be one of {', '.join(AGENTS)}, got {agent!r}")
    repo = project.path("repo.git")
    if not repo.exists():
        raise WorkspaceRefused(f"{project.pid} has no repository yet: compile its contract first")
    slug = slugify(person, 24)
    items = _registry(project)
    n = 1 + max([w["n"] for w in items if w["slug"] == slug], default=0)
    folder = workspaces_root(root) / project.pid
    while (folder / f"{slug}-{n}").exists() or _git(repo, "rev-parse", "--verify", "-q",
                                                     f"refs/heads/work/{slug}/{n}", check=False):
        n += 1
    branch, path = f"work/{slug}/{n}", folder / f"{slug}-{n}"
    folder.mkdir(parents=True, exist_ok=True)
    guard_repo(repo)
    _git(folder, "clone", "-q", *clone_options(), str(repo), path.name)
    _git(path, "checkout", "-q", "--no-track", "-b", branch, "origin/main")  # its upstream is not main
    _seal(path)
    base = _git(path, "rev-parse", "HEAD")
    exclude = path / ".git" / "info" / "exclude"
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    write_text(exclude, text + "".join(f"{i}\n" for i in [CONTEXT_FILE, MCP_FILE, *IGNORED] if i not in text))
    write_text(path / CONTEXT_FILE, context_md(project, person=person, persona=persona, branch=branch, base=base,
                                               path=path))
    _merge_mcp(path, mcp_config(project.factory, person=person, persona=persona, lanes=root))
    command = terminal_command(path, agent)
    items.append({"n": n, "slug": slug, "path": str(path), "branch": branch, "agent": agent, "person": person,
                  "persona": persona, "base": base, "opened": project.factory.clock.stamp(), "submissions": []})
    project.write("workspaces.json", items)
    project.log("workspace_opened", {"person": person, "persona": persona, "agent": agent, "branch": branch})
    return {"path": str(path), "branch": branch, "agent": agent, "command": command}


def _merge_mcp(path: Path, ours: dict) -> None:
    """Rihma's MCP server put into the workspace's `.mcp.json`. A project that commits its own (other servers
    of its own, a game engine's, say) keeps them: Rihma's entry is merged in, and git is told to leave the
    file out of the person's commits, so `git commit -a` never sends the merge through the gate."""
    import json

    file = path / MCP_FILE
    tracked = bool(_git(path, "ls-files", MCP_FILE, check=False).strip())
    try:
        theirs = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
    except (OSError, ValueError):
        theirs = {}
    if not isinstance(theirs, dict) or not isinstance(theirs.get("mcpServers", {}), dict):
        theirs = {}
    merged = {**theirs, **{k: v for k, v in ours.items() if k != "mcpServers"},
              "mcpServers": {**(theirs.get("mcpServers") or {}), **(ours.get("mcpServers") or {})}}
    write_json(file, merged)
    if tracked:
        _git(path, "update-index", "--skip-worktree", MCP_FILE, check=False)


def launch(workspace: dict, *, project=None, popen=None) -> dict:
    """Start the terminal a workspace names. The kernel never calls this by itself; the cockpit may,
    for a person at this machine."""
    path = Path(workspace["path"])
    if not path.is_dir():
        raise WorkspaceRefused(f"no workspace at {path}")
    popen = popen or subprocess.Popen
    kwargs = {"cwd": str(path), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    proc = popen(list(workspace["command"]), **kwargs)
    if project is not None:
        project.log("workspace_launched", {"branch": workspace.get("branch"), "agent": workspace.get("agent")})
    return {"pid": getattr(proc, "pid", None), "command": list(workspace["command"])}


def _find(project, workspace_path) -> dict:
    want = Path(workspace_path).resolve()
    for w in _registry(project):
        if Path(w["path"]).resolve() == want:
            return w
    raise WorkspaceRefused(f"{workspace_path} is not a workspace of {project.pid}")


def workspaces(project) -> list:
    """The open workspaces: branch, agent, person, and commits ahead of main."""
    out = []
    for w in _registry(project):
        path = Path(w["path"])
        if not (path / ".git").exists():
            continue
        _git(path, "fetch", "-q", "origin", check=False)
        ahead = _git(path, "rev-list", "--count", f"origin/main..refs/heads/{w['branch']}", check=False)
        out.append({"path": w["path"], "branch": w["branch"], "agent": w["agent"], "person": w["person"],
                    "persona": w["persona"], "opened": w["opened"], "ahead": int(ahead) if ahead.isdigit() else None,
                    "submissions": len(w.get("submissions", []))})
    return out


# -- submit: the person as a cell ---------------------------------------------------------------------

def _seal(path: Path) -> None:
    """A workspace's `origin` fetches from the product repository and pushes nowhere."""
    _git(path, "config", "remote.origin.pushurl", NO_PUSH)


def _refuse(project: Project, branch: str, person: str, persona: str, reason: str) -> NoReturn:
    project.log("workspace_refused", {"branch": branch, "person": person, "persona": persona, "reason": reason})
    raise WorkspaceRefused(reason)


def _save_submission(project: Project, branch: str, entry: dict) -> None:
    items = _registry(project)
    for w in items:
        if w["branch"] == branch:
            w.setdefault("submissions", []).append(entry)
    project.write("workspaces.json", items)


def own_suites(project) -> list[dict]:
    """The test commands an adopted project's baseline ran (baseline.json): the gate runs them when unittest's
    discovery finds no test, so a pytest or npm project's submission is judged by its own suite."""
    base = project.read("baseline.json", {}) or {}
    return [r for r in base.get("runs") or [] if isinstance(r, dict) and r.get("command")
            and r.get("verdict") in ("passed", "failed")]


def submit_workspace(project, workspace_path, *, person: str, persona: str, task: str | None = None,
                     lanes: Lanes | None = None, verifier_runner=None, lane_wait: float = 3600) -> dict:
    """Judge the workspace branch's commits with the gate a builder cell meets; merge them when
    warranted and permitted, or escalate with every objection."""
    from kernel.dispatch import gate_record
    from kernel.gate import judge_change

    _check_person(person, persona)
    ws = _find(project, workspace_path)
    branch, path = ws["branch"], Path(ws["path"])

    def refuse(reason: str) -> NoReturn:
        _refuse(project, branch, person, persona, reason)

    contract = project.read("contract.json")
    if not contract:
        refuse("the project has no contract: nothing to judge against")
    if task is not None and task not in {t["id"] for t in contract["tasks"]}:
        refuse(f"{task} is not a task of the contract")
    submitted, uncommitted = _prepare(project, path, branch, refuse)
    author = {"type": "person", "name": person, "persona": persona}
    label = task or f"workspace:{branch}"
    round_no = len([r for r in project.ledger().of_kind("gate") if r["event"]["payload"].get("task") == label])
    lanes = lanes or Lanes()
    with lanes.lease(f"{project.pid}:{label}", wait=lane_wait) as lane:
        main, head = _judged_head(project, lane, branch, submitted, refuse)
        _refuse_protected(lane.path, main, head, refuse)
        result = judge_change(lane.path, contract, main, head, label=label, author=f"{person} ({persona})",
                              task_id=task, verifier_runner=verifier_runner, own_suites=own_suites(project))
        project.log("gate", gate_record(label, round_no, result, author=author, workspace=branch))
        entry = {"round": round_no, "head": head, "verdict": result.verdict, "task": task,
                 "at": project.factory.clock.stamp(), "uncommitted_left_out": uncommitted}
        out = {"branch": branch, "task": label, "author": author, "uncommitted_left_out": uncommitted,
               "gate": result.to_dict()}
        if result.warranted:
            return _merge_submission(project, lane, branch, task, label, head, author, entry, out["gate"]) | out
        return _escalate_submission(project, lane, contract, branch, task, label, head, author, result.objections,
                                    entry) | out


def _prepare(project: Project, path: Path, branch: str, refuse: Callable[[str], NoReturn]) -> tuple[str, bool]:
    """Check what the workspace submits and put it in the product repository as committed: the
    gate judges exactly that commit. Returns it, and whether uncommitted changes were left out."""
    repo = project.path("repo.git")
    guard_repo(repo)
    _seal(path)
    _git(path, "fetch", "-q", "origin")
    ahead = int(_git(path, "rev-list", "--count", f"origin/main..refs/heads/{branch}"))
    if ahead == 0:
        refuse(f"{branch} has no commits ahead of main: nothing to submit")
    _refuse_protected(path, "origin/main", f"refs/heads/{branch}", refuse)
    uncommitted = bool(_git(path, "status", "--porcelain"))
    submitted = _git(path, "rev-parse", f"refs/heads/{branch}")
    _git(path, "push", "-q", "-f", str(repo), f"{submitted}:refs/heads/{branch}")
    return submitted, uncommitted


def _refuse_protected(repo_dir: Path, base: str, head: str, refuse: Callable[[str], NoReturn]) -> None:
    touched = protected_paths(repo_dir, base, head)
    if touched:
        refuse("the change touches what a cell may not: " + ", ".join(touched[:10]))


def _judged_head(project: Project, lane: Lane, branch: str, submitted: str,
                 refuse: Callable[[str], NoReturn]) -> tuple[str, str]:
    """Check out the submitted commit in the lane. When main moved since the workspace was opened,
    the kernel merges it in, so what is judged is exactly what would land on main. Returns main
    and the head to judge."""
    lane.checkout(project.path("repo.git"), branch=branch, base=branch)
    if lane.head() != submitted:
        refuse(f"{branch} changed in the product repository while it was submitted: submit again")
    main = lane.git("rev-parse", "origin/main")
    if subprocess.run(["git", "merge-base", "--is-ancestor", main, "HEAD"], cwd=lane.path,
                      capture_output=True).returncode != 0:
        proc = subprocess.run(["git", *GIT_ID, "merge", "-q", "--no-edit", "origin/main"], cwd=lane.path,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=lane.path, capture_output=True)
            refuse("the branch conflicts with main: merge main into it in the workspace and submit again")
    return main, lane.head()


def _merge_submission(project: Project, lane: Lane, branch: str, task: str | None, label: str, head: str,
                      author: dict, entry: dict, gate: dict) -> dict[str, Any]:
    """Push a warranted submission to main. When main moved while the gate ran, the push is
    refused: the ledger says so beside the passed gate, and the person submits again."""
    from kernel.dispatch import AUTONOMY, _set_task

    permitted_by = AUTONOMY[project.meta["maturity"]]
    try:
        lane.push(branch, "main")
    except RuntimeError as exc:
        project.log("merge_rejected", {"task": label, "revision": head, "why": "main moved during the gate",
                                       "error": str(exc), "author": author, "workspace": branch})
        _save_submission(project, branch, entry | {"status": "stale_main"})
        raise WorkspaceRefused("main moved while the gate judged the change: submit again") from exc
    project.log("merged", {"task": label, "revision": head, "warranted": "passed", "permitted_by": permitted_by,
                           "author": author, "workspace": branch})
    if task is not None:
        _set_task(project, task, status="merged", revision=head, permitted_by=permitted_by, author=author,
                  rounds=[{"round": entry["round"], "cell": {"author": author}, "gate": gate}])
    canon = Canon(project)
    for card in canon.cards(kind="escalation"):
        refs = card["refs"]
        if refs.get("workspace") == branch:
            canon.close(card["id"], f"a later submission of {branch} passed its gate and merged at {head[:12]}",
                        state="resolved")
        elif task is not None and refs.get("task") == task:
            canon.close(card["id"], f"{task} merged from {branch} at {head[:12]}, its gate passed", state="resolved")
    _save_submission(project, branch, entry | {"status": "merged"})
    return {"status": "merged", "revision": head}


def _escalate_submission(project: Project, lane: Lane, contract: dict, branch: str, task: str | None, label: str,
                         head: str, author: dict, objections: list, entry: dict) -> dict[str, Any]:
    """Keep the judged head in the product repository under a ref of its own (accept as is merges
    exactly that commit), and open the escalation card with every objection."""
    from kernel.dispatch import JUDGED_REF

    try:
        lane.git("push", "-q", "-f", "origin", f"{head}:{JUDGED_REF}{head}")
    except RuntimeError as exc:
        project.log("escalated_branch_not_kept", {"task": label, "workspace": branch, "error": str(exc)})
    person = author["name"]
    reqs = sorted({c.rsplit("-AC-", 1)[0] for t in contract["tasks"] if t["id"] == task for c in t["criteria"]})
    card = Canon(project).card(
        "escalation", f"{person}'s workspace change on {branch} did not pass its gate",
        body="\n".join(f"- {o}" for o in objections),
        refs={"workspace": branch, "person": person, **({"task": task, "requirements": reqs} if task else {})},
        payload={"objections": objections, "branch": branch, "author": author, "head": head}, blocking=True)
    project.log("escalated", {"task": label, "card": card["id"], "objections": objections,
                              "author": author, "workspace": branch})
    _save_submission(project, branch, entry | {"status": "escalated", "card": card["id"]})
    return {"status": "escalated", "card": card["id"], "objections": objections}
