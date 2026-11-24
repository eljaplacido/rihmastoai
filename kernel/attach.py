"""Attach a repository of your own: the start of "gate my code", "security only" and "evidence only"
(docs/guides/use-only-what-you-need.md; FR-MOD3).

`attach` makes a project that points at a git repository on this machine and leaves it where it is:

- **Your repository stays yours.** Rihmasto never writes to it, never pushes to it and never merges into
  it. Every check runs in a temporary clone of a committed revision (`checkout`), which is removed after;
  uncommitted changes are never judged, and a result says when some were left out. A URL is refused:
  clone it yourself first, as `rihmasto adopt` asks of a private repository.
- **The contract** is one of: a contract file (`--contract`), checked by `tools/contract_check.py` with
  its revision recomputed from its content (a stated revision that does not match is refused); a spec
  file (`--spec`) that the compiler turns into a contract with no model, each requirement endorsed by the
  person who brought it; or the repository's own `contract.json` at the tip of its branch. Without any,
  the project has no contract: the security scan and the release records still work, the gate does not.
  `rihmasto repo contract` gives one later.
- **The record** is the same as anywhere else (D-0017): who attached it as which persona, the repository,
  its branch and head, and the contract's revision and where it came from, in the project's ledger.

An attached project has no pipeline: `rihmasto run` says what it waits for (`attached_state`).
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from kernel import access as kaccess
from kernel.access import AccessRefused
from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, Project, write_text

SOURCE_KIND = "attached"
CONTRACT_FILE = "contract.json"
# Git without prompts, credential helpers or LFS downloads: the kernel only ever reads a local repository.
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "GIT_CONFIG_NOSYSTEM": "1"}
_GIT_SAFE = ["-c", "credential.helper=", "-c", "core.hooksPath=" + os.devnull]


class AttachRefused(ValueError):
    """A repository, a revision or a contract the kernel will not take."""


def git(cwd: Path | str, *args: str, check: bool = True) -> str:
    """git in ``cwd``, with no prompt, no credential helper, no hook and no LFS download."""
    env = dict(os.environ) | _GIT_ENV
    proc = subprocess.run(["git", *_GIT_SAFE, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)
    if check and proc.returncode != 0:
        raise AttachRefused(f"git {' '.join(args[:3])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def check_signer(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: an attached repository's records name a person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")


# -- the repository --------------------------------------------------------------------------------------

def _repository(path: str | Path) -> Path:
    text = str(path)
    if "://" in text or text.startswith("git@"):
        raise AttachRefused("attach a repository on this machine: clone it yourself first, then attach its folder")
    folder = Path(text).expanduser().resolve()
    if not folder.is_dir():
        raise AttachRefused(f"no folder {folder}")
    top = git(folder, "rev-parse", "--show-toplevel", check=False)
    if not top:
        raise AttachRefused(f"{folder} is not a git repository")
    return Path(top).resolve()


def repository(project: Project) -> Path:
    """The attached repository's folder, as it was attached."""
    attached = project.meta.get("attached") or {}
    if not attached.get("repo"):
        raise AttachRefused(f"{project.pid} is not an attached repository: `rihmasto repo attach` makes one")
    return Path(attached["repo"])


def commit_of(project: Project, revision: str | None) -> str:
    """The full commit a revision names in the attached repository (default: its HEAD)."""
    rev = revision or "HEAD"
    if rev.startswith("-"):
        raise AttachRefused(f"{rev!r} is not a revision")
    sha = git(repository(project), "rev-parse", "--verify", "-q", f"{rev}^{{commit}}", check=False)
    if not sha:
        raise AttachRefused(f"{rev!r} names no commit in {repository(project)}")
    return sha


def uncommitted(project: Project) -> bool:
    """Whether the attached repository has changes that are not committed (they are never judged)."""
    return bool(git(repository(project), "status", "--porcelain", check=False))


@contextlib.contextmanager
def checkout(project: Project, revision: str) -> Iterator[Path]:
    """A temporary clone of the attached repository at ``revision`` (a commit), removed afterwards. The
    person's own working tree is never touched."""
    tmp = Path(tempfile.mkdtemp(prefix="rihmasto-attached-"))
    try:
        git(tmp, "clone", "-q", "--no-checkout", str(repository(project)), "w")
        work = tmp / "w"
        if not git(work, "cat-file", "-t", revision, check=False):
            raise AttachRefused(f"{revision[:12]} is on no branch or tag of the repository: commit it to a branch")
        git(work, "checkout", "-q", "--detach", revision)
        yield work
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -- the repository's own code -----------------------------------------------------------------------------

ISOLATION = "kernel.access_isolation"   # IT's isolation runner (D-0016)


class IsolationNeeded(AccessRefused):
    """The attached repository's own code would run while access is enforced and nothing isolates it. The
    command line exits 2, the cockpit answers 403."""


def _isolation() -> Any:
    try:
        return importlib.import_module(ISOLATION)
    except ModuleNotFoundError as exc:
        if exc.name != ISOLATION:
            raise
        return None


@contextlib.contextmanager
def outside_code(project: Project) -> Iterator[None]:
    """Around every run of the attached repository's own tests (`repo gate`, `repo releases --check`): code
    from outside the factory. With access enforced it runs only through IT's isolation runner: required up
    front, before anything is cloned, and this factory served while it runs, so `kernel.gate.run_suite`
    takes the runner. Without a runner it is refused, and so it is while this Rihmasto has no isolation
    runner at all. A single operator's factory runs it as before."""
    iso = _isolation()
    if iso is None:
        if kaccess.load(project.factory).enforced:
            raise IsolationNeeded("access is enforced and this Rihmasto has no isolation runner, so an attached "
                                  "repository's tests do not run as the account that runs Rihmasto "
                                  "(docs/guides/access.md)")
        yield
        return
    iso.require(project.factory, iso.SUITE)
    with iso.serving(project.factory):
        yield


# -- the contract ----------------------------------------------------------------------------------------

def _load_json(path: str | Path, what: str) -> dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise AttachRefused(f"no {what} file {path}") from None
    except (ValueError, RecursionError) as exc:
        raise AttachRefused(f"the {what} file is not JSON: {type(exc).__name__}") from None
    if not isinstance(doc, dict):
        raise AttachRefused(f"the {what} file holds no JSON object")
    return doc


def contract_schema() -> str:
    from kernel.compile import contract_check

    return str(contract_check().SCHEMA)


def imported_contract(doc: dict[str, Any]) -> dict[str, Any]:
    """A contract file as the kernel keeps it: checked, its revision computed from its content."""
    from kernel.compile import contract_check

    cc = contract_check()
    stated = doc.get("revision")
    revision = cc.canonical_revision(doc)
    if stated is not None and stated != revision:
        raise AttachRefused(f"the contract states revision {str(stated)[:24]}, but its content hashes to "
                            f"{revision[:24]}: it changed after it was hashed")
    report, _ = cc.check(doc)
    if report.violations:
        rules = "; ".join(f"{v['rule']} {v['path']}" for v in report.violations[:5])
        raise AttachRefused(f"the contract does not pass tools/contract_check.py: {rules}")
    return doc | {"revision": revision}


def _from_spec(project: Project, raw: dict[str, Any], person: str) -> dict[str, Any]:
    """A spec file compiled with no model: ids and provenance by the kernel's rules, each requirement
    endorsed by the person who brought it."""
    from kernel.compile import to_contract
    from kernel.spec import normalize, render_spec_md

    project.write("source.json", {"kind": "spec file", "requested_by": person, "literal": True})
    items = [r | {"sources": r.get("sources") or ["request"]} for r in raw.get("requirements") or []
             if isinstance(r, dict)]
    try:
        spec = normalize(project, raw | {"requirements": items})
    except ValueError as exc:
        raise AttachRefused(f"the spec file: {exc}") from None
    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    return to_contract(project, spec)


def give_contract(project: Project, *, person: str, persona: str, contract: str | Path | None = None,
                  spec: str | Path | None = None, branch_file: bool = False) -> dict[str, Any] | None:
    """Give an attached project its contract, from a contract file, a spec file, or the repository's
    own `contract.json` (``branch_file``). Records where it came from and who gave it."""
    from kernel.compile import check_plan

    check_signer(person, persona)
    if contract is not None and spec is not None:
        raise AttachRefused("name a contract file or a spec file, not both")
    if contract is not None:
        doc, source = imported_contract(_load_json(contract, "contract")), {"file": str(Path(contract).resolve())}
    elif spec is not None:
        doc, source = _from_spec(project, _load_json(spec, "spec"), person), {"spec": str(Path(spec).resolve())}
    elif branch_file:
        branch = (project.meta.get("attached") or {}).get("branch") or "HEAD"
        text = git(repository(project), "show", f"{branch}:{CONTRACT_FILE}", check=False)
        try:
            found = json.loads(text) if text else None
        except (ValueError, RecursionError):
            found = None
        if not isinstance(found, dict) or found.get("schema") != contract_schema():
            return None                      # no contract of Rihmasto's there: the project has none yet
        doc = imported_contract(found)
        source = {"repository": f"{branch}:{CONTRACT_FILE}"}
    else:
        raise AttachRefused("name a contract file (--contract) or a spec file (--spec)")
    project.write("contract.json", doc)
    project.write("checkplan.json", check_plan(doc))
    project.update_meta(contract_revision=doc["revision"], stage=5)
    project.log("contract_imported", {"revision": doc["revision"], "from": source, "by": person, "persona": persona,
                                      **(doc.get("counts") or {})})
    return doc


# -- attaching ---------------------------------------------------------------------------------------------

def attach(factory: Factory, title: str, *, repo: str | Path, person: str, persona: str,
           contract: str | Path | None = None, spec: str | Path | None = None, branch: str | None = None) -> Project:
    """Make a project for a repository on this machine. Nothing is copied into the factory and nothing is
    written to the repository; the contract is taken as `give_contract` says."""
    check_signer(person, persona)
    folder = _repository(repo)
    branch = branch or git(folder, "symbolic-ref", "-q", "--short", "HEAD", check=False) or "main"
    if branch.startswith("-") or not git(folder, "rev-parse", "--verify", "-q", f"{branch}^{{commit}}", check=False):
        raise AttachRefused(f"the repository has no branch {branch!r} with a commit: commit to it first")
    head = git(folder, "rev-parse", f"{branch}^{{commit}}")
    project = factory.new_project(title, maturity="production", mode="mixed", source_kind=SOURCE_KIND)
    try:
        project.update_meta(attached={"repo": str(folder), "branch": branch, "head_at_attach": head}, stage=5)
        project.log("repo_attached", {"repo": str(folder), "branch": branch, "head": head, "person": person,
                                      "persona": persona})
        _agent_context(project, folder, head)
        give_contract(project, person=person, persona=persona, contract=contract, spec=spec,
                      branch_file=contract is None and spec is None)
    except BaseException:
        shutil.rmtree(project.dir, ignore_errors=True)        # nothing is left half-attached
        raise
    return project


def _agent_context(project: Project, folder: Path, head: str) -> None:
    """How the team's AI tools are set up, read from the attached commit's objects (never the working tree,
    and nothing found is run): kept for the project page and `rihmasto ide` (kernel/ide.py, FR-AGC1)."""
    from kernel.agent_context import from_git
    from kernel.ide import record

    try:
        ctx = from_git(folder, head)
    except (RuntimeError, OSError, ValueError):
        return
    record(project, ctx, at=head)


def attached(factory: Factory) -> list[dict[str, Any]]:
    """Every attached repository, with its contract revision (or none)."""
    return [{"project": p.pid, "title": p.meta.get("title"), **(p.meta.get("attached") or {}),
             "contract": p.meta.get("contract_revision")}
            for p in factory.projects() if p.meta.get("source_kind") == SOURCE_KIND]


def attached_state(project: Project) -> dict[str, Any] | None:
    """What an attached repository waits for when the pipeline is run: a person's command, never a build.
    None for any other project."""
    if project.meta.get("source_kind") != SOURCE_KIND:
        return None
    has = project.meta.get("contract_revision") is not None
    return {"state": "waiting", "stage": project.meta.get("stage"), "attached": True,
            "waiting_for": ["a gate on a change" if has else "a contract", "a security scan", "a release record"],
            "why": f"an attached repository: Rihmasto never builds or merges here. "
                   f"`rihmasto repo {'gate' if has else 'contract'} {project.pid}` "
                   f"{'judges a change' if has else 'gives it a contract'}; `repo scan` scans it; "
                   "`repo releases` records its releases"}
