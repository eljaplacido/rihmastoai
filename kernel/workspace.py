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
cell may not: the surface, the contract and the factory's files.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from kernel.canon import Canon
from kernel.lanes import GIT_ID, IGNORED, Lanes, _git, lanes_root
from kernel.people import PERSONAS, is_person
from kernel.store import REPO_ROOT, slugify, write_json, write_text

AGENTS = ("gnomon", "claude", "opencode", "shell")
CONTEXT_FILE = "RIHMA_CONTEXT.md"
MCP_FILE = ".mcp.json"
RULE = ("Your changes go through the same gate as an agent's: tests, an independent verifier, then merge; "
        "nothing you do here is a decision.")
# What a builder cell may not write (kernel/lanes.py PRODUCT_RULES): a person's submission may not either.
PROTECTED = (".gnomon/", "contract.json", "factory/")


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
    _git(folder, "clone", "-q", str(repo), path.name)
    _git(path, "checkout", "-q", "-b", branch, "origin/main")
    base = _git(path, "rev-parse", "HEAD")
    exclude = path / ".git" / "info" / "exclude"
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    write_text(exclude, text + "".join(f"{i}\n" for i in [CONTEXT_FILE, MCP_FILE, *IGNORED] if i not in text))
    write_text(path / CONTEXT_FILE, context_md(project, person=person, persona=persona, branch=branch, base=base,
                                               path=path))
    write_json(path / MCP_FILE, mcp_config(project.factory, person=person, persona=persona, lanes=root))
    command = terminal_command(path, agent)
    items.append({"n": n, "slug": slug, "path": str(path), "branch": branch, "agent": agent, "person": person,
                  "persona": persona, "base": base, "opened": project.factory.clock.stamp(), "submissions": []})
    project.write("workspaces.json", items)
    project.log("workspace_opened", {"person": person, "persona": persona, "agent": agent, "branch": branch})
    return {"path": str(path), "branch": branch, "agent": agent, "command": command}


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

def _refuse(project, branch: str, person: str, persona: str, reason: str):
    project.log("workspace_refused", {"branch": branch, "person": person, "persona": persona, "reason": reason})
    raise WorkspaceRefused(reason)


def _save_submission(project, branch: str, entry: dict) -> None:
    items = _registry(project)
    for w in items:
        if w["branch"] == branch:
            w.setdefault("submissions", []).append(entry)
    project.write("workspaces.json", items)


def submit_workspace(project, workspace_path, *, person: str, persona: str, task: str | None = None,
                     lanes: Lanes | None = None, verifier_runner=None, lane_wait: float = 3600) -> dict:
    """Judge the workspace branch's commits with the gate a builder cell meets; merge them when
    warranted and permitted, or escalate with every objection."""
    from kernel.dispatch import AUTONOMY, _set_task, gate_record
    from kernel.gate import judge_change

    _check_person(person, persona)
    ws = _find(project, workspace_path)
    branch, path = ws["branch"], Path(ws["path"])
    contract = project.read("contract.json")
    if not contract:
        _refuse(project, branch, person, persona, "the project has no contract: nothing to judge against")
    if task is not None and task not in {t["id"] for t in contract["tasks"]}:
        _refuse(project, branch, person, persona, f"{task} is not a task of the contract")
    _git(path, "fetch", "-q", "origin")
    ahead = int(_git(path, "rev-list", "--count", f"origin/main..refs/heads/{branch}"))
    if ahead == 0:
        _refuse(project, branch, person, persona, f"{branch} has no commits ahead of main: nothing to submit")
    touched = [f for f in _git(path, "diff", "--name-only", f"origin/main...refs/heads/{branch}").splitlines()
               if f.startswith(PROTECTED)]
    if touched:
        _refuse(project, branch, person, persona, "the change touches what a cell may not: " + ", ".join(touched[:10]))
    uncommitted = bool(_git(path, "status", "--porcelain"))
    # The branch goes to the product repository as committed: the gate judges exactly that.
    _git(path, "push", "-q", "-f", "origin", f"refs/heads/{branch}:refs/heads/{branch}")

    author = {"type": "person", "name": person, "persona": persona}
    label = task or f"workspace:{branch}"
    round_no = len([r for r in project.ledger().of_kind("gate") if r["event"]["payload"].get("task") == label])
    lanes = lanes or Lanes()
    with lanes.lease(f"{project.pid}:{label}", wait=lane_wait) as lane:
        lane.checkout(project.path("repo.git"), branch=branch, base=branch)
        main = lane.git("rev-parse", "origin/main")
        if subprocess.run(["git", "merge-base", "--is-ancestor", main, "HEAD"], cwd=lane.path,
                          capture_output=True).returncode != 0:
            # main moved since the workspace was opened: bring it in, as a kernel commit, so what is
            # judged is exactly what would land on main.
            proc = subprocess.run(["git", *GIT_ID, "merge", "-q", "--no-edit", "origin/main"], cwd=lane.path,
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                subprocess.run(["git", "merge", "--abort"], cwd=lane.path, capture_output=True)
                _refuse(project, branch, person, persona,
                        "the branch conflicts with main: merge main into it in the workspace and submit again")
        head = lane.head()
        result = judge_change(lane.path, contract, main, head, label=label, author=f"{person} ({persona})",
                              task_id=task, verifier_runner=verifier_runner)
        project.log("gate", gate_record(label, round_no, result, author=author, workspace=branch))
        entry = {"round": round_no, "head": head, "verdict": result.verdict, "task": task,
                 "at": project.factory.clock.stamp(), "uncommitted_left_out": uncommitted}
        if result.warranted:
            permitted_by = AUTONOMY[project.meta["maturity"]]
            lane.push(branch, "main")
            project.log("merged", {"task": label, "revision": head, "warranted": result.verdict,
                                   "permitted_by": permitted_by, "author": author, "workspace": branch})
            if task is not None:
                _set_task(project, task, status="merged", revision=head, permitted_by=permitted_by, author=author,
                          rounds=[{"round": round_no, "cell": {"author": author}, "gate": result.to_dict()}])
            canon = Canon(project)
            for card in canon.cards(kind="escalation"):
                if card["refs"].get("workspace") == branch:
                    canon.close(card["id"], f"a later submission of {branch} passed its gate and merged at "
                                            f"{head[:12]}", state="resolved")
            _save_submission(project, branch, entry | {"status": "merged"})
            return {"status": "merged", "revision": head, "branch": branch, "task": label, "author": author,
                    "uncommitted_left_out": uncommitted, "gate": result.to_dict()}
        reqs = sorted({c.rsplit("-AC-", 1)[0] for t in contract["tasks"] if t["id"] == task for c in t["criteria"]})
        card = Canon(project).card(
            "escalation", f"{person}'s workspace change on {branch} did not pass its gate",
            body="\n".join(f"- {o}" for o in result.objections),
            refs={"workspace": branch, "person": person, **({"task": task, "requirements": reqs} if task else {})},
            payload={"objections": result.objections, "branch": branch, "author": author}, blocking=True)
        project.log("escalated", {"task": label, "card": card["id"], "objections": result.objections,
                                  "author": author, "workspace": branch})
        _save_submission(project, branch, entry | {"status": "escalated", "card": card["id"]})
        return {"status": "escalated", "card": card["id"], "branch": branch, "task": label, "author": author,
                "objections": result.objections, "uncommitted_left_out": uncommitted, "gate": result.to_dict()}
