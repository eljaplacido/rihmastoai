"""What each output target holds (kernel/outputs.py), built from the project's records and one release.

Each builder returns the files of its output by name, or raises NotReady with the reason it cannot be
built yet. None of them calls a model, reads the clock or writes the product: the same records and the
same release give the same files.

- `container_files`: the product's source at the release, its Dockerfile, a compose.yaml that runs it
  on 127.0.0.1, `image.json` (the image the road built, by digest once IT pinned it) and a README for a
  developer.
- `api_files`: an OpenAPI 3.1 document from the spec's interface, the road's own routes and the
  criteria, each operation with the criteria that name it and their evidence state.
- `source_files`: the product's git history as a bundle, with how to clone it and put it on a branch.
- `login_files`: what the release's sign-in is and how to set it up, read from the release itself.
- `face_files`: an MCP server or another face, from the small-capability faces (FACES_MODULE), when
  that module offers FACES_HOOK; until then it is not built, and says so.
"""

from __future__ import annotations

import importlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from kernel.scaffold_auth import ROAD_SIGN_IN_TESTS, SIGN_IN_FILE, SIGN_IN_GUIDE

Files = dict[str, str | bytes]
# The hook to the small-capability faces: `output_files(project, release, face)` in this module returns a
# face's files by name ({} or LookupError when it has none). Until it exists, a face output is planned.
FACES_MODULE, FACES_HOOK = "kernel.faces", "output_files"
ROAD_ROUTES = [{"method": "GET", "path": "/health", "purpose": "the road's health check: status and release version"}]
SIGN_IN_ROUTES = [{"method": "GET", "path": "/sign-in", "purpose": "the sign-in form, or its CSRF token as JSON"},
                  {"method": "POST", "path": "/sign-in", "purpose": "sign in with a name, a password and the token"},
                  {"method": "POST", "path": "/sign-out", "purpose": "end the session"},
                  {"method": "GET", "path": "/account", "purpose": "who is signed in"},
                  {"method": "POST", "path": "/account/password", "purpose": "set a new password"},
                  {"method": "POST", "path": "/accounts", "purpose": "an admin adds an account"}]
_STATUS = re.compile(r"\b([1-5][0-9][0-9])\b")


class NotReady(LookupError):
    """An output cannot be built yet; the message says why, in plain words."""


def _run_git(project: Any, *args: str) -> bytes:
    """git in the product's repository, with the files as committed: no line-ending conversion (a Windows
    host's core.autocrlf would hand a Linux container CRLF), and one pack thread, so a bundle is the same."""
    settings = ["-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "pack.threads=1"]
    proc = subprocess.run(["git", *settings, *args], cwd=project.path("repo.git"), capture_output=True,
                          timeout=300, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise NotReady(f"git {args[0]} failed in the product repository: "
                       f"{proc.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return proc.stdout


def tree(project: Any, revision: str) -> dict[str, bytes]:
    """The product's files at ``revision``, by path."""
    if not project.path("repo.git").exists():
        raise NotReady("the product has no repository yet: it is made when the contract is compiled")
    with tarfile.open(fileobj=io.BytesIO(_run_git(project, "archive", "--format=tar", revision))) as tar:
        return {m.name: (tar.extractfile(m) or io.BytesIO()).read() for m in tar.getmembers() if m.isfile()}


def _needs(rel: dict | None, what: str) -> dict:
    if rel is None:
        raise NotReady(f"no release yet: {what} is built from a release")
    return rel


def has_sign_in(files: dict[str, bytes]) -> bool:
    return SIGN_IN_FILE in files and ROAD_SIGN_IN_TESTS in files


# -- container ------------------------------------------------------------------------------------------

def _image(rel: dict) -> dict:
    """The image the release's road built: by digest once pinned, else its tag, else none (a process road)."""
    for road, art in sorted((rel.get("artifacts") or {}).items()):
        if isinstance(art, dict) and art.get("type") == "image":
            return {"road": road, "ref": art.get("ref"), "digest": art.get("digest"), "pinned": bool(art.get("digest"))}
    return {"road": None, "ref": None, "digest": None, "pinned": False,
            "note": "no image: the release ran on a road that starts the product as a process"}


def compose_yaml(project: Any, rel: dict, image: dict, sign_in: bool) -> str:
    """A compose.yaml a developer runs on their own machine: the product on 127.0.0.1:8080, data on a
    named volume; the pinned image when IT pinned one, else built from the source beside it."""
    source = f"    image: {image['ref']}\n" if image.get("pinned") else "    build: ./product\n"
    env = [f'      APP_VERSION: "{str(rel["revision"])[:12]}"', '      PORT: "8080"', '      DATA_DIR: "/data"']
    if sign_in:
        env += [f'      {name}: "${{{name}:-}}"' for name in ("FIRST_ADMIN_USER", "FIRST_ADMIN_PASSWORD", "PUBLIC_URL")]
    name = re.sub(r"[^a-z0-9-]+", "-", project.pid.lower())[:60]
    return (f"# {project.meta.get('title')}: release {rel['release']} (revision {str(rel['revision'])[:12]}), "
            "built by Rihmasto from its records.\n# Run it: docker compose up --build (README.md says more).\n"
            f"name: {name}\nservices:\n  app:\n{source}    ports:\n      - \"127.0.0.1:8080:8080\"\n"
            "    environment:\n" + "\n".join(env) + "\n    volumes:\n      - data:/data\nvolumes:\n  data: {}\n")


def _container_readme(project: Any, rel: dict, image: dict, sign_in: bool) -> str:
    rev = str(rel["revision"])[:12]
    lines = [f"# {project.meta.get('title')}: the container", "",
             f"Release {rel['release']} of `{project.pid}`, at revision `{rev}`, as a developer runs it. Rihmasto "
             "built this folder from the project's records; `MANIFEST.json` holds the sha256 of every file.", "",
             "## Run it", "", "```sh", "docker compose up --build", "curl http://127.0.0.1:8080/health", "```", "",
             "Without Docker: `cd product && python3 -m app.server` (Python 3.11 or later, standard library only).", "",
             "## What is here", "",
             "- `product/`: the product's source at the release, its `Dockerfile` and its tests "
             "(`python3 -m unittest discover -s tests` in `product/`).",
             "- `compose.yaml`: the service on 127.0.0.1:8080, its data on the named volume `data`.",
             "- `image.json`: " + (f"the image the road built, pinned by digest: `{image['ref']}`." if image["pinned"]
                                   else "the image the road built is not pinned by digest, so compose builds "
                                        "from `product/`." if image.get("ref") else image.get("note", "")), ""]
    if sign_in:
        lines += ["## Sign-in", "",
                  "People sign in to this product. At the first start set `FIRST_ADMIN_USER` and "
                  "`FIRST_ADMIN_PASSWORD` (12 characters or more) in your shell before `docker compose up`; "
                  "`product/factory/SIGN-IN.md` says the rest, the organisation's own sign-in included.", ""]
    lines += ["## Change it", "", "Changes go through the factory (a change card), so the ledger links every "
              "release to the requirement, the criterion and the test it rests on.", ""]
    return "\n".join(lines)


def container_files(project: Any, rel: dict | None) -> Files:
    rel = _needs(rel, "the container")
    files = tree(project, str(rel["revision"]))
    image, sign_in = _image(rel), has_sign_in(files)
    out: Files = {f"product/{name}": data for name, data in files.items()}
    out["compose.yaml"] = compose_yaml(project, rel, image, sign_in)
    out["image.json"] = json.dumps({"release": rel["release"], "revision": rel["revision"], **image}, indent=2) + "\n"
    out["README.md"] = _container_readme(project, rel, image, sign_in)
    return out


# -- api ---------------------------------------------------------------------------------------------------

def _path_pattern(path: str) -> re.Pattern:
    parts = [r"[^\s/]+" if re.fullmatch(r"\{\w+\}", seg) else re.escape(seg) for seg in path.strip("/").split("/")]
    return re.compile(r"(?<![A-Za-z])/" + "/".join(parts) + r"(?![A-Za-z0-9_/{-])")


def _criteria_of(method: str, path: str, criteria: list[dict]) -> list[dict]:
    """The criteria whose action names this operation: METHOD and the path, in its given or when."""
    pattern = _path_pattern(path)
    out = []
    for c in criteria:
        action = f"{c.get('given', '')} {c.get('when', '')}"
        if any(m.start() >= 0 and re.search(rf"\b{method}\s*$", action[:m.start()]) for m in pattern.finditer(action)):
            out.append(c)
    return out


def _operation(row: dict, criteria: list[dict], states: dict[str, str], open_route: bool) -> dict:
    method, path = row["method"].upper(), row["path"]
    named = _criteria_of(method, path, criteria)
    codes = sorted({code for c in named for code in _STATUS.findall(str(c.get("then", "")))})
    responses = {code: {"description": "; ".join(c["then"] for c in named if code in str(c["then"]))[:400]}
                 for code in codes} or {"default": {"description": "as the product's criteria describe"}}
    op: dict[str, Any] = {"operationId": re.sub(r"[^A-Za-z0-9]+", "_", f"{method} {path}").strip("_").lower(),
                          "summary": row.get("purpose") or f"{method} {path}", "responses": responses,
                          "x-rihmasto-criteria": [{"id": c["id"], "then": c["then"],
                                                   "evidence": states.get(c["id"], "not_measured")} for c in named]}
    params = re.findall(r"\{(\w+)\}", path)
    if params:
        op["parameters"] = [{"name": p, "in": "path", "required": True, "schema": {"type": "string"}} for p in params]
    if method in ("POST", "PUT", "PATCH"):
        op["requestBody"] = {"required": False, "content": {"application/json": {"schema": {"type": "object"}}}}
    if open_route:
        op["security"] = []
    return op


SECURITY_SCHEMES = {
    "session": {"type": "apiKey", "in": "cookie", "name": "session",
                "description": "the session cookie POST /sign-in sets"},
    "csrf": {"type": "apiKey", "in": "header", "name": "X-CSRF-Token",
             "description": "the session's CSRF token, on every POST, PUT, PATCH and DELETE"}}


def _criteria_and_states(project: Any, contract: dict) -> tuple[list[dict], dict[str, str]]:
    """The live criteria of the contract, and each one's evidence state."""
    from kernel.status import evidence

    criteria = [c for r in contract.get("requirements") or [] if r.get("provenance") != "withdrawn"
                for c in r.get("acceptance") or []]
    return criteria, ({e["criterion"]: e["state"] for e in evidence(project)} if contract else {})


def _routes(spec: dict, sign_in: bool) -> list[dict]:
    from kernel.spec import interface_of

    rows = [dict(r, kind="product") for r in interface_of(spec)] + [dict(r, kind="road") for r in ROAD_ROUTES]
    return rows + ([dict(r, kind="sign-in") for r in SIGN_IN_ROUTES] if sign_in else [])


def openapi(project: Any, rel: dict | None, sign_in: bool) -> dict:
    """The OpenAPI 3.1 document of the product's interface, its road routes and, with sign-in, its sign-in."""
    contract = project.read("contract.json") or {}
    criteria, states = _criteria_and_states(project, contract)
    paths: dict[str, dict] = {}
    for row in _routes(project.read("spec.json") or {}, sign_in):
        open_route = sign_in and (row["kind"] == "road" or row["path"] == "/sign-in")
        paths.setdefault(row["path"], {})[row["method"].lower()] = _operation(row, criteria, states, open_route)
    rel = rel or {}
    doc: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": str(project.meta.get("title")),
                 "version": f"release-{rel['release']}" if rel.get("release") else "unreleased",
                 "description": f"Derived by Rihmasto from the spec's interface and the contract "
                                f"{str(contract.get('revision', 'not compiled yet'))[:19]}: each operation lists the "
                                "criteria that name it, with their evidence state."},
        "paths": dict(sorted(paths.items())),
        "x-rihmasto": {"project": project.pid, "release": rel.get("release"), "revision": rel.get("revision"),
                       "contract": contract.get("revision")},
    }
    if sign_in:
        doc["components"] = {"securitySchemes": SECURITY_SCHEMES}
        doc["security"] = [{"session": [], "csrf": []}]
    return doc


def api_files(project: Any, rel: dict | None) -> Files:
    if not (project.read("spec.json") or {}):
        raise NotReady("no spec yet: the API is described from the spec's interface")
    sign_in = has_sign_in(tree(project, str(rel["revision"]))) if rel else False
    doc = openapi(project, rel, sign_in)
    ops = sum(len(v) for v in doc["paths"].values())
    readme = (f"# {project.meta.get('title')}: the API\n\n`openapi.json` is an OpenAPI 3.1 document of {ops} "
              "operations, derived by Rihmasto from the spec's interface, the paved road's own routes and the "
              "contract. Each operation's `x-rihmasto-criteria` names the acceptance criteria that call it, with their "
              "evidence state "
              "(verified, claimed, held out, failing or not measured). Request and response bodies are JSON objects; "
              "the criteria say what they carry.\n")
    if sign_in:
        readme += ("\nThe product has sign-in: `POST /sign-in` with JSON gives the `session` cookie and a CSRF token "
                   "for the `X-CSRF-Token` header (product/factory/SIGN-IN.md in the container output).\n")
    return {"openapi.json": json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "README.md": readme}


# -- source, sign-in and faces ---------------------------------------------------------------------------------

def source_commands(pid: str, rel: dict | None) -> list[str]:
    """The README's commands, run from the folder the zip was unpacked into, outside any repository: the clone
    names its branch (it checks out `main` whatever the bundle's HEAD), `git bundle verify` runs inside the
    clone (it needs a repository), and with no release the push sends main's tip."""
    return [f"git clone --branch main product.bundle {pid}", f"cd {pid}", "git bundle verify ../product.bundle",
            *([f"git checkout -b release-{rel['release']} {rel['revision']}"] if rel else []),
            "git remote add team <your repository URL>", f"git push team HEAD:refs/heads/rihmasto/{pid}"]


def source_files(project: Any, rel: dict | None) -> Files:
    if not project.path("repo.git").exists():
        raise NotReady("the product has no repository yet: it is made when the contract is compiled")
    head = _run_git(project, "rev-parse", "main").decode().strip()
    with tempfile.TemporaryDirectory(prefix="gf-bundle-") as tmp:
        target = Path(tmp) / "product.bundle"
        # HEAD too, when it names main, so a plain `git clone` checks main out instead of an unborn branch.
        try:
            refs = ["HEAD", "main"] if _run_git(project, "symbolic-ref", "-q", "HEAD").strip() == b"refs/heads/main" \
                else ["main"]
        except NotReady:
            refs = ["main"]
        _run_git(project, "bundle", "create", str(target), *refs)
        data = target.read_bytes()
    at = f"release {rel['release']} is revision `{rel['revision']}`" if rel else "no release yet"
    pushed = f"release {rel['release']}" if rel else "main's latest commit"
    readme = (f"# {project.meta.get('title')}: the source\n\n`product.bundle` holds the product's git history, "
              f"branch `main` at `{head}`; {at}.\n\nRun these in the folder that holds `product.bundle` (no "
              f"repository needed); the last two put {pushed} on a branch of your team's repository:\n\n```sh\n"
              + "\n".join(source_commands(project.pid, rel))
              + "\n```\n\nRihmasto never pushes it anywhere itself: your team puts it on a branch of "
              "its own. Changes come back through the factory (a change card or `rihmasto workspace`), so the gate "
              "judges them.\n")
    return {"product.bundle": data, "README.md": readme}


def login_files(project: Any, rel: dict | None) -> Files:
    rel = _needs(rel, "the sign-in")
    files = tree(project, str(rel["revision"]))
    if not has_sign_in(files):
        raise NotReady(f"release {rel['release']} has no sign-in: it reaches a release once the road's sign-in is "
                       "on main (choosing this output adds it) and the product is delivered again")
    checks = re.findall(r"def (test_ROAD_SIGNIN_\w+)", files[ROAD_SIGN_IN_TESTS].decode("utf-8"))
    readme = (f"# {project.meta.get('title')}: a web app people sign in to\n\nRelease {rel['release']} (revision "
              f"`{str(rel['revision'])[:12]}`) carries the paved road's sign-in. `SIGN-IN.md` says how to set up "
              "the first admin and the organisation's own sign-in. The road's checks of it run with the product's "
              "whole suite at every gate:\n\n" + "".join(f"- `{c}`\n" for c in checks))
    return {"README.md": readme, "SIGN-IN.md": files.get(SIGN_IN_GUIDE, b""), "sign-in-checks.json":
            json.dumps({"release": rel["release"], "revision": rel["revision"], "checks": checks}, indent=2) + "\n"}


def module_hook(module_name: str, name: str) -> Any:
    """A function another part of the kernel offers, or None while that module or the function is not there."""
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    hook = getattr(module, name, None)
    return hook if callable(hook) else None


def face_hook() -> Any:
    """The faces module's output function, or None while it offers none."""
    return module_hook(FACES_MODULE, FACES_HOOK)


def face_files(project: Any, rel: dict | None, face: str) -> Files:
    hook = face_hook()
    if hook is None:
        raise NotReady(f"planned: the {face.replace('_', ' ')} comes from the small-capability faces "
                       f"({FACES_MODULE}.{FACES_HOOK}), which are not built yet")
    files = hook(project, rel, face)
    if not files:
        raise NotReady(f"the faces module has no {face.replace('_', ' ')} for this project")
    return dict(files)
