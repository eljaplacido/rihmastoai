"""Outputs per audience: what each person receives from a project, built from its records and its release.

People expect different results. A developer wants a container, the people who use it a web app they sign
in to, an integrator an API description or an MCP server, a business owner a plain report of what was done,
a reviewer an evidence pack, a team the source on a branch. Each is an output target (TARGETS):

| Target | For | Holds |
|---|---|---|
| `login_web_app` | the people who use it | the product with the paved road's sign-in (kernel/scaffold_auth.py) |
| `container` | a developer | the source at the release, its Dockerfile, compose.yaml, a README |
| `api` | an integrator | an OpenAPI 3.1 document from the product's routes and criteria |
| `mcp_server` | an integrator's agents | planned: from the small-capability faces (kernel/output_builders.py hook) |
| `report` | a business owner | the delivery report, HTML and Markdown (kernel/report.py) |
| `evidence_pack` | a reviewer | the evidence pack (kernel/evidence_pack.py) |
| `source` | a team | the product's git history as a bundle, with how to put it on a branch |

**Choosing.** A person chooses the targets, at intake (the cockpit's new-project request may name them) or
later, and may change them: `choose` keeps the choice in `outputs.json` with its history and records
`outputs_chosen` in the ledger with who chose, as which persona, what was chosen before and why. Until
someone chooses, the work profile only proposes (kernel/profiles.py OUTPUTS); a proposal is never shown as
a choice. Choosing `login_web_app` before the contract is compiled gives the product its sign-in from the
start (`wants_sign_in`, read by kernel/compile.py); once the product's repository exists, choosing it adds
the road's sign-in to main, and main moves only when the product's whole suite passes with it
(`add_sign_in`). Dropping it later is recorded; the sign-in stays until a change removes it.

**Building.** `build` makes each chosen target from the project's records and one release (the latest that
was not superseded, unless named), into one zip per target named by its content's sha256. No model and no
clock: the same records give the same bytes, so a rebuild names the same file. A target that cannot be built
yet says why, plainly. Every build, made or not, is recorded as `output_built` with who asked. The evidence
pack is the existing export, a fresh one each time.

`rihmasto output <pid>` shows the targets; `--choose a,b` chooses; `--target a --target b` builds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import output_builders as ob
from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person

TARGETS: dict[str, dict[str, Any]] = {
    "login_web_app": {"label": "Web app with sign-in", "audience": "the people who use it", "icon": "users",
                      "contains": ["the product with the paved road's sign-in: accounts with salted PBKDF2-SHA256 "
                                   "hashes, a session cookie, CSRF tokens, a lockout, the first admin from the "
                                   "environment", "SIGN-IN.md: setting it up, and the organisation's own sign-in "
                                   "through a proxy",
                                   "the sign-in's checks, run with the product's suite at every gate"]},
    "container": {"label": "Container", "audience": "a developer", "icon": "package",
                  "contains": ["the product's source and Dockerfile at the release", "compose.yaml: the service on "
                               "127.0.0.1:8080", "image.json: the image the road built", "README.md: how to run it"]},
    "api": {"label": "API description", "audience": "an integrator", "icon": "plug",
            "contains": ["openapi.json: OpenAPI 3.1 from the product's routes", "each operation's criteria and their "
                         "evidence", "README.md"]},
    "mcp_server": {"label": "MCP server", "audience": "an integrator's agents", "icon": "bot",
                   "contains": ["the product's operations as MCP tools, from the small-capability faces"]},
    "report": {"label": "Delivery report", "audience": "a business owner", "icon": "file-check",
               "contains": ["report.html and report.md in plain language: what was asked and by whom, what was built, "
                            "the decisions, the assumptions, the evidence, how to try it, the cost, the limits"]},
    "evidence_pack": {"label": "Evidence pack", "audience": "a reviewer", "icon": "shield",
                      "contains": ["the capability pack, contract, decisions, gates, holdout scores and the ledger "
                                   "with its chain check; an attestation, never a claim of conformity"]},
    "source": {"label": "Source", "audience": "a team", "icon": "code",
               "contains": ["product.bundle: the product's git history", "README.md: how to clone it and put it on "
                            "a branch of your own"]},
}
CHOOSERS = ("business_owner", "product_owner", "developer", "it")
BUILDERS = ("business_owner", "product_owner", "developer", "it", "compliance")
RECORD = "outputs.json"
_STAMP = (1980, 1, 1, 0, 0, 0)  # every zip entry's time: the bytes depend on the content only
# The hook to the postures (built in parallel): a posture preset may propose outputs, never choose them.
POSTURE_MODULE, POSTURE_HOOK = "kernel.posture", "proposed_outputs"


def known_targets(targets: Any) -> list[str]:
    if isinstance(targets, str):
        targets = [t for t in targets.replace(" ", ",").split(",") if t]
    if not isinstance(targets, (list, tuple)) or not all(isinstance(t, str) for t in targets):
        raise ValueError("targets are a list of names: " + ", ".join(TARGETS))
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        raise ValueError(f"no output target {', '.join(unknown)}: the targets are {', '.join(TARGETS)}")
    return [t for t in TARGETS if t in targets]


def _signer(project: Any, person: Any, persona: Any, allowed: tuple[str, ...], act: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: whoever {act} is named")
    if persona not in allowed:
        raise DecisionRefused(f"a {persona} may not {act}; {', '.join(allowed)} may")
    from kernel.access import require

    require(project, person, persona)


def proposed_targets(project: Any) -> list[str]:
    """What is proposed before anyone chose: the posture's proposal when the postures offer one (the hook
    POSTURE_MODULE.POSTURE_HOOK, `proposed_outputs(project) -> list | None`), else the work profile's
    (kernel/profiles.py OUTPUTS). A proposal is never a choice."""
    from kernel.profiles import OUTPUTS, profile_of

    hook = ob.module_hook(POSTURE_MODULE, POSTURE_HOOK)
    offered = hook(project) if hook else None
    if isinstance(offered, (list, tuple)) and all(t in TARGETS for t in offered):
        return [t for t in TARGETS if t in offered]
    return list(OUTPUTS.get(profile_of(project).get("deliverable", "product"), []))


def chosen(project: Any) -> list[str]:
    return [t for t in (project.read(RECORD) or {}).get("targets") or [] if t in TARGETS]


def wants_sign_in(project: Any) -> bool:
    """Whether a person chose the web app with sign-in: kernel/compile.py scaffolds the product with it."""
    return "login_web_app" in chosen(project)


def choose(project: Any, targets: Any, *, person: str, persona: str, reason: str = "", when: str = "later") -> dict:
    """A person chooses what the project delivers; see the module's docstring. Returns the view."""
    from kernel.filelock import locked

    wanted = known_targets(targets)
    _signer(project, person, persona, CHOOSERS, "chooses outputs")
    with locked(project.path(".outputs.lock")):
        record = project.read(RECORD) or {}
        before = [t for t in record.get("targets") or [] if t in TARGETS]
        added = [t for t in wanted if t not in before]
        sign_in = None
        if "login_web_app" in added and project.path("repo.git").exists():
            sign_in = add_sign_in(project, person=person, persona=persona)
        entry = {"targets": wanted, "by": person, "persona": persona, "at": project.factory.clock.stamp(),
                 "when": when, "reason": reason}
        project.write(RECORD, {**entry, "history": [*(record.get("history") or []), entry]})
        project.log("outputs_chosen", {"targets": wanted, "before": before, "added": added,
                                       "removed": [t for t in before if t not in wanted], "by": person,
                                       "persona": persona, "when": when, "reason": reason,
                                       **({"sign_in": sign_in} if sign_in else {})})
    return view(project)


# -- what a choice already says: to the intake panel, the brief and the builder (kernel/intake.py, dispatch.py) --------

# A chosen output is the chooser's word: the panel is told, the brief keeps it (so the spec reads it), and a panel
# question whose `topic` it settles is never asked again (FR-OUT7-AC-2).
GIVEN: dict[str, dict[str, str]] = {
    "login_web_app": {"fact": "People sign in to the product: local accounts on the paved road's sign-in, or the "
                              "organisation's own single sign-on (OIDC) through an identity-aware proxy that whoever "
                              "runs it sets up.",
                      "topic": r"\b(signs?[- ]?(in|on)|single[- ]sign|logs?[- ]?in|login|sso|oidc|openid|saml|"
                               r"identity provider)\b"},
    "container": {"fact": "A developer receives the product as a container with a Compose file."},
    "api": {"fact": "An integrator receives an OpenAPI 3.1 description of the product's interface."},
    "mcp_server": {"fact": "An integrator's agents reach the product as an MCP server."},
    "report": {"fact": "The business owner receives a plain delivery report."},
    "evidence_pack": {"fact": "A reviewer receives the evidence pack."},
    "source": {"fact": "The team receives the source as a git bundle, to put on a branch of its own."},
}
SIGN_IN_NOTES = """People sign in to this product. The paved road owns `app/sign_in.py` and
`tests/test_road_sign_in.py`: never edit them. Every request but GET /health, /static/ and the sign-in page
needs a signed-in person.
- In a handler, `req.user` is {"name": ..., "role": "admin" or "user", "csrf": ...}. With
  `from app.sign_in import csrf_field, require_role`, `require_role(req, "admin")` is the answer that refuses
  anyone else (None for an admin), and every form you build includes `csrf_field(req)`.
- In a test, `handle()` runs a handler without the guard (`req.user` is None there: a handler reads it as
  `req.user or {}`); `respond(method, path, body, session_headers("ada"))` sends it signed in, through the guard."""


def given(project: Any) -> list[dict]:
    """Each chosen output's fact, with the person who chose it: what intake never asks again."""
    record = project.read(RECORD) or {}
    return [{"target": t, "fact": GIVEN[t]["fact"], "by": record.get("by"), "persona": record.get("persona")}
            for t in chosen(project)]


def given_for_panel(project: Any) -> str:
    """The intake panel's lines on what the outputs already settle ("" when nothing is chosen)."""
    facts = given(project)
    return ("\nAlready given by the person who chose this project's outputs (never ask about it again):\n"
            + "".join(f"- {g['fact']}\n" for g in facts)) if facts else ""


def asked_again(project: Any, text: str, perspective: str) -> bool:
    """Whether a panel question asks what a chosen output settled. Then it is not asked, and the ledger keeps
    `question_not_asked` with the question, the fact, and who chose it (the outputs_chosen record it rests on)."""
    for g in given(project):
        topic = GIVEN[g["target"]].get("topic")
        if topic and re.search(topic, text, re.IGNORECASE):
            project.log("question_not_asked", {"text": text[:300], "perspective": perspective, "target": g["target"],
                                               "given": g["fact"], "by": g["by"], "persona": g["persona"],
                                               "rests_on": "outputs_chosen"})
            return True
    return False


def brief_lines(project: Any) -> list[str]:
    """The brief's section on the chosen outputs, each the chooser's word ([] when nothing is chosen)."""
    facts = given(project)
    return ["## Outputs chosen [owner]", "", *[f"- {g['fact']} [owner: {g['by']}]" for g in facts], ""] if facts else []


def builder_notes(project: Any, base: str) -> list[str]:
    """The builder's envelope's section on the sign-in, when the product at ``base`` has it ([] otherwise)."""
    from kernel.scaffold_auth import SIGN_IN_FILE

    try:
        ob._run_git(project, "cat-file", "-e", f"{base}:{SIGN_IN_FILE}")
    except (ob.NotReady, OSError):
        return []
    return ["", "## Sign-in (the paved road's)", "", SIGN_IN_NOTES]


def _suite(work: Path) -> tuple[str | None, dict]:
    """The product's whole suite with the sign-in, run as the gate runs it (kernel.gate.run_suite): why it
    failed, or None, and what it ran."""
    from kernel.gate import run_suite

    result = run_suite(work, timeout=900)
    checks = sorted(n for n, outcome in result.get("tests", {}).items() if n.startswith("test_ROAD_SIGNIN_")
                    and outcome == "ok")
    ran = {"ran": result.get("ran", 0), "sign_in_checks": len(checks)}
    if result.get("exit") == 0 and ran["ran"] and checks:
        return None, ran
    tail = " ".join(result.get("tail") or []) or (f"timed out after {result.get('timeout')} s" if result.get(
        "timeout") else "no test ran")
    return "the product's suite fails with the sign-in: " + tail[-400:], ran


def add_sign_in(project: Any, *, person: str, persona: str) -> dict:
    """Add the road's sign-in to the product's main. The product's whole suite runs with it first, as the gate
    runs it, and main moves only when it passes with the sign-in's own checks; a product whose app/server.py
    predates the sign-in hook is refused. Either way the ledger says so (`sign_in_added`, `sign_in_refused`),
    with who asked. The Dockerfile then runs the service as the unprivileged user that owns /data, as a product
    with sign-in from the start does, so the red team's static rules scan it clean; a deployment's data volume
    made before may belong to root, and `factory/SIGN-IN.md` says how to hand it over once (the record says so)."""
    from kernel.lanes import GIT_ID, _git
    from kernel.scaffold_auth import README_SECTION, SIGN_IN_FILE, has_sign_in_hook, sign_in_files, unprivileged
    from kernel.scaffold_auth_docs import VOLUME_NOTE
    from kernel.store import write_text

    ran: dict = {}
    with tempfile.TemporaryDirectory(prefix="gf-sign-in-") as tmp:
        work = Path(tmp) / "w"
        _git(Path(tmp), "clone", "-q", str(project.path("repo.git")), "w")
        if (work / SIGN_IN_FILE).exists():
            return {"revision": _git(work, "rev-parse", "HEAD"), "added": False}
        server = work / "app" / "server.py"
        why = None if server.exists() and has_sign_in_hook(server.read_text(encoding="utf-8")) else (
            "the product's app/server.py predates the road's sign-in hook: it would never load the sign-in")
        if why is None:
            for rel, text in sign_in_files().items():
                write_text(work / rel, text)
            readme, docker = work / "README.md", work / "Dockerfile"
            write_text(readme, (readme.read_text(encoding="utf-8") if readme.exists() else "").rstrip("\n") + "\n"
                       + README_SECTION)
            if docker.exists() and "USER 10001:10001" not in docker.read_text(encoding="utf-8"):
                try:
                    write_text(docker, unprivileged(docker.read_text(encoding="utf-8")))
                except ValueError as exc:
                    why = f"the product's Dockerfile cannot be given an unprivileged user: {exc}"
            why, ran = (why, ran) if why else _suite(work)
        if why is not None:
            project.log("sign_in_refused", {"why": why, "by": person, "persona": persona})
            raise DecisionRefused(f"the sign-in was not added: {why}")
        _git(work, "add", "-A")
        _git(work, *GIT_ID, "commit", "-q", "-m", f"The paved road's sign-in, chosen by {person} ({persona})")
        _git(work, "push", "-q", "origin", "main")
        revision = _git(work, "rev-parse", "HEAD")
    project.log("sign_in_added", {"revision": revision, "suite": "passed", **ran, "user": "10001",
                                  "data_volume": VOLUME_NOTE, "by": person, "persona": persona})
    return {"revision": revision, "added": True, **ran}


def release_of(project: Any, number: int | None = None) -> dict | None:
    """The release outputs are built from: ``number``, or the latest one not superseded."""
    from kernel.deliver import releases

    found = [r for r in releases(project) if r.get("state") != "superseded"]
    if number is not None:
        match = [r for r in releases(project) if r.get("release") == number]
        if not match:
            raise LookupError(f"{project.pid} has no release {number}")
        return match[0]
    return found[-1] if found else None


def _files(project: Any, target: str, rel: dict | None) -> ob.Files:
    from kernel import report

    if target == "report":
        outputs = view(project, built=False)
        return {"report.md": report.markdown(project, rel, outputs),
                "report.html": report.html_page(project, rel, outputs)}
    builders: dict[str, Callable[[Any, dict | None], ob.Files]] = {
        "container": ob.container_files, "api": ob.api_files, "source": ob.source_files,
        "login_web_app": ob.login_files, "mcp_server": lambda p, r: ob.face_files(p, r, "mcp_server")}
    return builders[target](project, rel)


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def write_zip(out_dir: Path, stem: str, files: ob.Files) -> tuple[Path, str, dict[str, str]]:
    """The files as one zip with a manifest, named by its content's sha256: the same files, the same name and
    bytes. A zip already there with that name holds those very bytes, so it is kept."""
    manifest = {name: _sha(data) for name, data in sorted(files.items())}
    entries = {**files, "MANIFEST.json": json.dumps({"files": manifest}, indent=2) + "\n"}
    digest = _sha(json.dumps(manifest, sort_keys=True))
    out = Path(out_dir) / f"{stem}-{digest[:12]}.zip"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as z:
            for name, data in sorted(entries.items()):
                info = zipfile.ZipInfo(name, date_time=_STAMP)
                info.create_system, info.external_attr = 3, 0o644 << 16
                z.writestr(info, data)
        tmp.replace(out)
    return out, _sha(out.read_bytes()), manifest


def _build_one(project: Any, target: str, rel: dict | None, out_dir: Path, who: tuple[str, str]) -> dict:
    stem = f"{project.pid}-{'r' + str(rel['release']) if rel else 'unreleased'}-{target}"
    row: dict[str, Any]
    try:
        if target == "evidence_pack":
            from kernel import evidence_pack

            path = evidence_pack.export(project, out_dir, person=who[0], persona=who[1])
            row = {"state": "built", "file": path.name, "sha256": _sha(path.read_bytes())}
        else:
            path, digest, manifest = write_zip(out_dir, stem, _files(project, target, rel))
            row = {"state": "built", "file": path.name, "sha256": digest, "files": manifest}
    except ob.NotReady as exc:
        row = {"state": "not built", "why": str(exc)}
    row = {"target": target, "release": rel.get("release") if rel else None,
           "revision": rel.get("revision") if rel else None, **row}
    project.log("output_built", {**{k: v for k, v in row.items() if k != "files"}, "by": who[0], "persona": who[1]})
    return row


def build(project: Any, targets: Any, out_dir: str | Path, *, person: str, persona: str,
          release: int | None = None) -> dict:
    """Build each of ``targets`` (each must be chosen) from the records and one release, into ``out_dir``."""
    wanted = known_targets(targets)
    _signer(project, person, persona, BUILDERS, "builds outputs")
    missing = [t for t in wanted if t not in chosen(project)]
    if missing:
        raise DecisionRefused(f"{', '.join(missing)} is not chosen for {project.pid}: a person chooses it first "
                              f"({', '.join(CHOOSERS)})")
    rel = release_of(project, release)
    rows = [_build_one(project, t, rel, Path(out_dir), (person, persona)) for t in wanted]
    return {"project": project.pid, "release": rel.get("release") if rel else None, "outputs": rows}


def _last_builds(project: Any) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for rec in project.ledger().of_kind("output_built"):
        p = rec["event"]["payload"]
        if p.get("state") == "built":
            out[p.get("target")] = {k: p.get(k) for k in ("file", "sha256", "release", "by", "persona")} | {
                "at": rec["event"].get("at")}
    return out


def _readiness(project: Any, target: str, rel: dict | None) -> str | None:
    """Why ``target`` cannot be built now, or None when it can."""
    if target in ("report", "evidence_pack"):
        return None
    if target == "mcp_server":
        return None if ob.face_hook() else "planned: it comes from the small-capability faces, not built yet"
    if target == "api":
        return None if project.read("spec.json") else "no spec yet"
    if not project.path("repo.git").exists():
        return "added when the contract is compiled" if target == "login_web_app" else "no product repository yet"
    if target == "source":
        return None
    if rel is None:
        return "no release yet"
    if target == "login_web_app":
        try:
            files = ob.tree(project, str(rel["revision"]))
        except ob.NotReady as exc:
            return str(exc)
        if not ob.has_sign_in(files):
            return f"release {rel['release']} has no sign-in yet: the next release carries it"
    return None


def view(project: Any, *, built: bool = True) -> dict:
    """The targets with what each holds, which are chosen and by whom, what is proposed, and the last builds."""
    record = project.read(RECORD) or {}
    picked, proposal = chosen(project), proposed_targets(project)
    rel = release_of(project)
    builds = _last_builds(project) if built else {}
    rows = []
    for tid, t in TARGETS.items():
        why = _readiness(project, tid, rel) if built else None
        rows.append({"id": tid, **t, "status": "planned" if tid == "mcp_server" and not ob.face_hook() else "available",
                     "chosen": tid in picked, "proposed": tid in proposal, "ready": why is None, "why": why,
                     "last_build": builds.get(tid)})
    by = {k: record.get(k) for k in ("by", "persona", "at", "when", "reason")} if record else None
    return {"project": project.pid, "targets": rows, "chosen": picked, "chosen_by": by, "proposed": proposal,
            "history": (record.get("history") or [])[-10:], "choosers": list(CHOOSERS), "builders": list(BUILDERS),
            "release": {k: rel.get(k) for k in ("release", "revision", "state")} if rel else None}


# -- the command line: `rihmasto output <pid> [--choose a,b] [--target a ...]` -----------------------------------

def add_parsers(sub: Any) -> None:
    p = sub.add_parser("output", help="what each audience receives: show, choose or build (kernel/outputs.py)")
    p.add_argument("pid")
    p.add_argument("--target", action="append", choices=list(TARGETS), help="build this chosen target (repeatable)")
    p.add_argument("--choose", help="choose the targets, separated by commas: " + ", ".join(TARGETS))
    p.add_argument("--reason", default="", help="why, recorded with a choice")
    p.add_argument("--release", type=int, help="build from this release (default: the latest)")
    p.add_argument("--out", help="the folder to build into (default: <home>/exports)")
    # Left out unless given, so showing needs no signer; a choice or a build refuses without one.
    p.add_argument("--person", default=argparse.SUPPRESS, help="who chooses or builds")
    p.add_argument("--persona", default=argparse.SUPPRESS, choices=PERSONAS)


def _command(factory: Any, args: argparse.Namespace) -> dict:
    project = factory.project(args.pid)
    person, persona = str(getattr(args, "person", "") or ""), str(getattr(args, "persona", "") or "")
    if (args.choose is not None or args.target) and not (person and persona):
        raise DecisionRefused("a choice or a build is signed: give --person and --persona")
    out: dict[str, Any] = {}
    if args.choose is not None:
        out["chosen"] = choose(project, args.choose, person=person, persona=persona, reason=args.reason)["chosen"]
    if args.target:
        folder = Path(args.out) if args.out else factory.home / "exports"
        out.update(build(project, args.target, folder, person=person, persona=persona, release=args.release))
        out["folder"] = str(folder)
    return out or view(project)


def handlers(show: Callable[[Any], None]) -> dict[str, Callable[[Any, argparse.Namespace], None]]:
    return {"output": lambda f, a: show(_command(f, a))}
