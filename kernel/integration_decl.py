"""Data integrations a product declares: the databases, warehouses, cloud storage, ERPs and business
APIs, MCP servers and REST APIs it reaches (FR-DS1; D-0015; docs/guides/data-integrations.md).

A declaration (`rihma.integration/1`) says what the product needs, never where the system is or how to
sign in to it:

- `name`: lower case, such as `orders_db`. The product reads its settings by it (`ORDERS_DB_URL`,
  `ORDERS_DB_ACCESS`, `ORDERS_DB_KIND`) and each credential by the credential's own name;
- `kind`: postgres, mysql, sqlserver or sqlite (databases); snowflake, bigquery or databricks
  (warehouses); s3, azure_blob or gcs (cloud storage); openapi with a `system` (sap, dynamics, netsuite
  or generic: an ERP or business API its OpenAPI document describes); mcp (an MCP server); rest;
- `via`: how the product reaches it: `mcp` (an MCP server over HTTP, such as a database's), `http` (the
  system's HTTP API) or `sql` (a database connection: on today's standard-library road only a SQLite
  file opens without a driver). The first of the kind's ways is the default (`KINDS`);
- `access`: read or read-write; `data_classes`: what it touches, public to restricted;
- `credentials`: the names of the secrets it needs, each starting with its settings' prefix. No value is
  ever here: IT names where each one lives when it binds the integration on a road
  (kernel/integration_bind.py).

The spec lists them (`spec.json` `integrations`), and each becomes a requirement the kernel writes,
`INT-<NAME>`, with one criterion a test must name. The builder reads it in its envelope, the plan shows
it, the trace signal holds a test to it, and the gate runs the product's tests against a stand-in for it
(kernel/integration_standins.py). The criterion's `given` names the declaration in a fixed form that the
gate reads back from the contract, so the stand-in checks what the contract says.

An analyst may propose a declaration in its draft: the kernel validates it and gives it a provenance by
the spec's rules. A person declares one (`rihmasto integration declare`) while the plan is open: it is
theirs (customer-confirmed), the plan's version moves on, its open card is reissued and the ledger
records who declared what and why. Once the plan is compiled, a change goes through the change loop.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from typing import Any

from kernel.connectors import DATA_CLASSES, SECRETISH
from kernel.events import clean_text
from kernel.people import PERSONAS, is_person

SCHEMA = "rihma.integration/1"
ACCESS = ("read", "read-write")
VIAS = ("sql", "http", "mcp")
SYSTEMS = ("sap", "dynamics", "netsuite", "generic")
MAX_INTEGRATIONS = 8
# Each kind: its family, the ways a product may reach it (the first is the default), the URL schemes a
# `sql` endpoint uses, and the reference connector folder through which Rihmasto itself reaches it.
KINDS: dict[str, dict[str, Any]] = {
    "postgres": {"family": "database", "vias": ("mcp", "http", "sql"), "schemes": ("postgresql", "postgres"),
                 "connector": "postgres"},
    "mysql": {"family": "database", "vias": ("mcp", "http", "sql"), "schemes": ("mysql",), "connector": None},
    "sqlserver": {"family": "database", "vias": ("mcp", "http", "sql"), "schemes": ("sqlserver", "mssql"),
                  "connector": None},
    "sqlite": {"family": "database", "vias": ("sql",), "schemes": ("sqlite",), "connector": None},
    "snowflake": {"family": "warehouse", "vias": ("http", "sql", "mcp"), "schemes": ("snowflake",),
                  "connector": "snowflake"},
    "bigquery": {"family": "warehouse", "vias": ("http", "sql", "mcp"), "schemes": ("bigquery",), "connector": None},
    "databricks": {"family": "warehouse", "vias": ("http", "sql", "mcp"), "schemes": ("databricks",),
                   "connector": None},
    "s3": {"family": "storage", "vias": ("http",), "schemes": (), "connector": "s3"},
    "azure_blob": {"family": "storage", "vias": ("http",), "schemes": (), "connector": None},
    "gcs": {"family": "storage", "vias": ("http",), "schemes": (), "connector": None},
    "openapi": {"family": "business_api", "vias": ("http",), "schemes": (), "connector": "openapi"},
    "mcp": {"family": "mcp", "vias": ("mcp",), "schemes": (), "connector": None},
    "rest": {"family": "rest", "vias": ("http",), "schemes": (), "connector": None},
}
REQUIRED = ("name", "kind", "access", "data_classes")
OPTIONAL = ("via", "system", "credentials", "purpose", "sources", "provenance", "decided_by", "declared_by")
NAME = re.compile(r"[a-z][a-z0-9_]{1,30}\Z")
CREDENTIAL = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
SECRET_WORD = re.compile(r"(?i)(secret|passw|token|api[_-]?key|private[_-]?key|connection[_-]?string|credential)")
# The first words of what the kernel's own tools read from their environment: the docker CLI, a proxy, TLS,
# the loader. A credential goes to `docker run` in the CLI's environment, so it must not steer the CLI (FR-DS5).
TOOLING = ("DOCKER", "BUILDKIT", "BUILDX", "COMPOSE", "NOTARY", "HTTP", "HTTPS", "NO", "ALL", "FTP", "SSL", "TLS",
           "OPENSSL", "CURL", "REQUESTS", "LD", "DYLD", "SSH", "OTEL", "GRPC", "XDG", "LC", "TMP", "TEMP")
RESERVED = ("APP", "PORT", "DATA", "TRAFFIC", "HOST", "RIHMA", "PATH", "HOME", "PYTHON", "GNOMON", "GF", *TOOLING)
SETTINGS = ("URL", "ACCESS", "KIND")
SENSITIVE = ("confidential", "restricted")
_GIVEN = re.compile(r"integration ([a-z][a-z0-9_]{1,30}): ([a-z][a-z0-9_]*) via (sql|http|mcp), (read-write|read)"
                    r"(?:; secrets ([A-Z0-9_, ]+))?")


# -- one declaration ------------------------------------------------------------------------------------

def prefix(name: str) -> str:
    """The prefix of an integration's settings and credentials: its name in upper case."""
    return name.upper()


def steers_tooling(name: object) -> bool:
    """Whether a variable of this name is one the kernel's own tools read (its first word is in TOOLING)."""
    return str(name).upper().split("_")[0] in TOOLING


def settings(decl: dict[str, Any]) -> dict[str, str]:
    """The settings the product reads for an integration: its endpoint, its access and its kind."""
    p = prefix(decl["name"])
    return {"url": f"{p}_URL", "access": f"{p}_ACCESS", "kind": f"{p}_KIND"}


def _fail(rep: list[dict[str, str]], path: str, expected: str, got: object) -> None:
    rep.append({"path": path, "expected": expected, "got": repr(got)[:120]})


def _check_name(decl: dict[str, Any], rep: list[dict[str, str]]) -> None:
    name = decl.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        _fail(rep, "/name", "lower-case letters, digits and _, starting with a letter, such as orders_db", name)
    elif SECRET_WORD.search(name) or prefix(name).split("_")[0] in RESERVED:
        _fail(rep, "/name", "a name whose settings look like no secret, no setting the road sets and no variable "
                            "the deploy tools read (DOCKER_, HTTP_, SSL_, LD_ ...)", name)


def _check_kind(decl: dict[str, Any], rep: list[dict[str, str]]) -> None:
    kind, via, system = decl.get("kind"), decl.get("via"), decl.get("system")
    if kind not in KINDS:
        _fail(rep, "/kind", f"one of {tuple(KINDS)}", kind)
        return
    if via is not None and via not in KINDS[kind]["vias"]:
        _fail(rep, "/via", f"one of {KINDS[kind]['vias']} for {kind}", via)
    if kind == "openapi" and system not in SYSTEMS:
        _fail(rep, "/system", f"one of {SYSTEMS}: the ERP or business system the OpenAPI document describes", system)
    elif kind != "openapi" and system is not None:
        _fail(rep, "/system", "no system: only an openapi integration names one", system)


def _check_credentials(decl: dict[str, Any], rep: list[dict[str, str]]) -> None:
    creds = decl.get("credentials", [])
    if not isinstance(creds, list):
        _fail(rep, "/credentials", "a list of credential names", creds)
        return
    name = decl["name"] if isinstance(decl.get("name"), str) else ""
    for i, c in enumerate(creds):
        if not isinstance(c, str) or not CREDENTIAL.match(c):
            _fail(rep, f"/credentials/{i}", "a credential's name, A_NAME_LIKE_THIS, never its value", "a value")
        elif not c.startswith(prefix(name) + "_") or c in {f"{prefix(name)}_{s}" for s in SETTINGS}:
            _fail(rep, f"/credentials/{i}", f"a name that starts with {prefix(name)}_ and is not a setting", c)
    if len(set(map(str, creds))) != len(creds):
        _fail(rep, "/credentials", "each credential named once", creds)


def _check_secrets(value: Any, path: str, rep: list[dict[str, str]]) -> None:
    if isinstance(value, str) and SECRETISH.search(value):
        _fail(rep, path, "no secret: a declaration names credentials, never holds one", "a secret-looking value")
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_secrets(v, f"{path}/{k}", rep)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_secrets(v, f"{path}/{i}", rep)


def check(decl: Any) -> list[dict[str, str]]:
    """Every way a declaration breaks `rihma.integration/1`, each with its JSON path; empty when it holds."""
    rep: list[dict[str, str]] = []
    if not isinstance(decl, dict):
        _fail(rep, "", "a JSON object", type(decl).__name__)
        return rep
    for key in REQUIRED:
        if key not in decl:
            _fail(rep, f"/{key}", "a required key", "missing")
    for key in sorted(set(decl) - set(REQUIRED) - set(OPTIONAL)):
        _fail(rep, f"/{key}", "no unknown keys", key)
    _check_name(decl, rep)
    _check_kind(decl, rep)
    if decl.get("access") not in ACCESS:
        _fail(rep, "/access", f"one of {ACCESS}", decl.get("access"))
    classes = decl.get("data_classes")
    if not isinstance(classes, list) or not classes or not set(map(str, classes)) <= set(DATA_CLASSES):
        _fail(rep, "/data_classes", f"one or more of {DATA_CLASSES}", classes)
    _check_credentials(decl, rep)
    if "purpose" in decl and not isinstance(decl["purpose"], str):
        _fail(rep, "/purpose", "a sentence", decl["purpose"])
    _check_secrets(decl, "", rep)
    return rep


def normalize(decl: dict[str, Any], *, provenance: str, decided_by: str | None = None,
              sources: list[str] | None = None) -> dict[str, Any]:
    """A valid declaration as the spec keeps it: its way filled in, its classes and credentials in order,
    its purpose cleaned (it may come from a model), and who stands behind it."""
    kind = decl["kind"]
    out: dict[str, Any] = {"name": decl["name"], "kind": kind, "via": decl.get("via") or KINDS[kind]["vias"][0],
                           "access": decl["access"],
                           "data_classes": [c for c in DATA_CLASSES if c in decl["data_classes"]],
                           "credentials": sorted(set(decl.get("credentials") or [])),
                           "purpose": clean_text(decl.get("purpose", ""), 300, one_line=True)}
    if kind == "openapi":
        out["system"] = decl["system"]
    out |= {"sources": list(sources or ["proposed"]), "provenance": provenance}
    if decided_by:
        out["decided_by"] = decided_by
    return out


def note(decl: dict[str, Any]) -> str | None:
    """What a person should know before approving: a SQL connection to anything but SQLite needs a driver
    that the standard-library paved road does not carry yet."""
    if decl["via"] == "sql" and decl["kind"] != "sqlite":
        return (f"{decl['kind']} via sql needs a database driver the paved road's standard-library template does "
                "not carry yet: reach it via http or mcp, or wait for a road whose template pins a driver (planned)")
    return None


def standin_phrase(decl: dict[str, Any]) -> str:
    """Where the gate's stand-in for an integration comes from, as the builder reads it."""
    name = decl["name"]
    if decl["via"] == "sql":
        return f"a SQLite file (sqlite:/// and its absolute path), seeded from tests/standins/{name}.sql when that " \
               "file exists"
    shape = "an object store" if KINDS[decl["kind"]]["family"] == "storage" else \
        "an MCP server over HTTP" if decl["via"] == "mcp" else "an HTTP API"
    # No loopback address here: the plan review would read one as the service's own bind (kernel/roads.py).
    return f"{shape} the gate runs beside the tests, answering from tests/standins/{name}.json when that file exists"


def requirement_id(name: str) -> str:
    return "INT-" + name.upper().replace("_", "-")


def requirement(decl: dict[str, Any]) -> dict[str, Any]:
    """The requirement the kernel writes for a declaration, with the one criterion a test must name."""
    rid, s = requirement_id(decl["name"]), settings(decl)
    creds = decl.get("credentials") or []
    given = f"integration {decl['name']}: {decl['kind']} via {decl['via']}, {decl['access']}" + \
        (f"; secrets {', '.join(creds)}" if creds else "")
    reads = "reads and writes" if decl["access"] == "read-write" else "reads"
    then = f"a test named by this criterion {reads} {decl['name']} only through {s['url']} and passes" + \
        ("" if decl["access"] == "read-write" else f", and nothing writes to {decl['name']}")
    req = {"id": rid, "priority": "must", "sources": decl.get("sources") or ["proposed"],
           "statement": f"The product reaches {decl['name']} ({decl['kind']}"
                        + (f" {decl['system']}" if decl.get("system") else "")
                        + f", {decl['access']}) only through the settings {', '.join(s.values())}"
                        + (f" and the credentials {', '.join(creds)}" if creds else "")
                        + (f": {decl['purpose'].rstrip('.')}." if decl.get("purpose") else "."),
           "provenance": decl["provenance"],
           "acceptance": [{"id": f"{rid}-AC-1", "given": given, "kind": "test", "then": then,
                           "when": f"the gate runs the product's tests with {s['url']} set to its stand-in, "
                                   + standin_phrase(decl)}]}
    if decl.get("decided_by"):
        req["decided_by"] = decl["decided_by"]
    return req


def from_contract(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The integrations a contract declares, read back from each INT- requirement's criterion, and what
    could not be read (a criterion edited so that it no longer names its integration)."""
    found: list[dict[str, Any]] = []
    problems: list[str] = []
    for r in contract.get("requirements") or []:
        if not str(r.get("id", "")).startswith("INT-") or r.get("provenance") == "withdrawn":
            continue
        crit = (r.get("acceptance") or [{}])[0]
        m = _GIVEN.search(str(crit.get("given", "")))
        if m is None or m.group(2) not in KINDS:
            problems.append(f"{r['id']}: its criterion no longer names its integration as the kernel wrote it")
            continue
        creds = [c.strip() for c in (m.group(5) or "").split(",") if c.strip()]
        found.append({"name": m.group(1), "kind": m.group(2), "via": m.group(3), "access": m.group(4),
                      "credentials": creds, "requirement": r["id"], "criterion": crit.get("id")})
    return found, problems


# -- the spec and the plan ------------------------------------------------------------------------------

def guidance() -> str:
    """How the analyst declares the systems a product reaches (its spec prompt)."""
    return ("If the product must read or write a system outside it (a database, a data warehouse, cloud storage,\n"
            "an ERP or business API, an MCP server or a REST API), declare each one in \"integrations\"; else "
            "leave it\nempty. Each is {\"name\": \"orders_db\", \"kind\": \"" + "|".join(KINDS) + "\",\n"
            "\"access\": \"read\" or \"read-write\", \"data_classes\": [\"internal\"], \"credentials\": "
            "[\"ORDERS_DB_PASSWORD\"],\n\"purpose\": \"...\", \"sources\": [\"request\"]}, with \"system\": "
            "\"sap|dynamics|netsuite|generic\" for openapi.\nName credentials, never a value and never an address: IT "
            "binds each to a real system. Prefer read.\nThe kernel adds a requirement for each; do not write one.")


def spec_integrations(project: Any, raw: dict[str, Any], dropped: list[dict[str, Any]],
                      provenance: Callable[[list[str]], tuple[str, str | None]]
                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The spec's integrations and their INT- requirements: those a person declared (kept when the spec is
    drafted again), then the analyst's, each validated and given a provenance by the spec's rules. What
    cannot be used is dropped with the reason, never silently."""
    kept = [d for d in ((project.read("spec.json") or {}).get("integrations") or []) if d.get("declared_by")]
    out, names = list(kept), {d["name"] for d in kept}
    for n, item in enumerate(raw.get("integrations") or [], 1):
        name = str(item.get("name", ""))[:40] if isinstance(item, dict) else ""
        problems = check(item)
        why = "; ".join(f"{p['path'] or '/'}: expected {p['expected']}" for p in problems[:3]) if problems else \
            f"{name} is declared already" if name in names else \
            f"beyond the {MAX_INTEGRATIONS} integrations a spec may have" if len(out) >= MAX_INTEGRATIONS else None
        if why:
            dropped.append({"what": "integration", "requirement": "integrations", "item": n, "statement": name,
                            "why": why})
            continue
        sources = [str(s).strip() for s in (item.get("sources") or []) if str(s).strip()][:5] or ["proposed"]
        prov, by = provenance(sources)
        out.append(normalize(item, provenance=prov, decided_by=by, sources=sources))
        names.add(name)
    return out, [requirement(d) for d in out]


def lines(spec: dict[str, Any]) -> list[str]:
    """The spec's integrations as people read them in spec.md and on the plan card; empty when none."""
    rows = spec.get("integrations") or []
    if not rows:
        return []
    out = ["IT binds each one on the paved road of every environment it is delivered to; credentials are "
           "named here, never held."]
    for d in rows:
        who = f"; declared by {d['declared_by']}" if d.get("declared_by") else f"; {d.get('provenance')}"
        out.append(f"- {d['name']}: {d['kind']}" + (f" ({d['system']})" if d.get("system") else "")
                   + f" via {d['via']}, {d['access']}; data classes {', '.join(d['data_classes'])}; settings "
                   + ", ".join(settings(d).values())
                   + (f"; credentials {', '.join(d['credentials'])}" if d.get("credentials") else "") + who)
        if note(d):
            out.append(f"  - Note: {note(d)}.")
    return out


def needs_plan_approval(spec: dict[str, Any]) -> bool:
    """Whether a person approves the plan at any maturity: the product writes to a system it reaches, or
    touches confidential or restricted data there."""
    return any(d.get("access") == "read-write" or set(d.get("data_classes") or []) & set(SENSITIVE)
               for d in spec.get("integrations") or [])


def _edit_spec(project: Any, change: Callable[[dict[str, Any]], None], *, person: str, persona: str) -> int:
    """Apply a person's change to the open plan: the old version is kept, the plan's version moves on and
    its open approval card is withdrawn, so the card that follows is for the plan as it stands."""
    from kernel.canon import CARD_DECIDERS, Canon, DecisionRefused
    from kernel.spec import render_spec_md
    from kernel.store import write_text

    if project.path("contract.json").exists():
        raise DecisionRefused("the plan is approved and compiled: change an integration through the change loop")
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a declaration is signed by a named person")
    if persona not in CARD_DECIDERS["approval"]:
        raise DecisionRefused(f"a {persona} may not change the plan (editors: {CARD_DECIDERS['approval']})")
    spec = project.read("spec.json")
    if not spec:
        raise FileNotFoundError(f"{project.pid} has no spec yet: integrations are declared on its plan")
    version = int(project.meta.get("spec_version", 1))
    project.write(f"spec.v{version}.json", spec)
    change(spec)
    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    project.update_meta(spec_version=version + 1)
    canon = Canon(project)
    for c in canon.cards(kind="approval"):
        if c["refs"].get("scope") == "plan":
            canon.close(c["id"], f"the plan's integrations were changed by {person}; a new card follows")
    return version + 1


def declare(project: Any, decl: dict[str, Any], *, person: str, persona: str, reason: str = "") -> dict[str, Any]:
    """A person declares an integration on the open plan: it is theirs (customer-confirmed), replacing one
    of the same name, and its INT- requirement with it."""
    problems = check(decl)
    if problems:
        raise ValueError("the declaration is not valid: " + "; ".join(
            f"{p['path'] or '/'}: expected {p['expected']}, got {p['got']}" for p in problems[:5]))
    d = normalize(decl, provenance="customer-confirmed", decided_by=person, sources=[f"declared:{person}"])
    d["declared_by"] = person

    def change(spec: dict[str, Any]) -> None:
        spec["integrations"] = [x for x in spec.get("integrations") or [] if x["name"] != d["name"]] + [d]
        rid = requirement_id(d["name"])
        spec["requirements"] = [r for r in spec["requirements"] if r["id"] != rid] + [requirement(d)]

    version = _edit_spec(project, change, person=person, persona=persona)
    project.log("integration_declared", {k: d[k] for k in ("name", "kind", "via", "access", "data_classes")}
                | {"requirement": requirement_id(d["name"]), "by": person, "persona": persona,
                   "reason": clean_text(reason, 300, one_line=True), "spec_version": version})
    return d


def withdraw(project: Any, name: str, *, person: str, persona: str, reason: str) -> dict[str, Any]:
    """A person takes an integration off the open plan, with its INT- requirement."""
    spec = project.read("spec.json") or {}
    if not any(d.get("name") == name for d in spec.get("integrations") or []):
        raise KeyError(f"no integration {name!r} on the plan")
    if not reason.strip():
        raise ValueError("withdrawing an integration needs a reason")

    def change(spec: dict[str, Any]) -> None:
        spec["integrations"] = [d for d in spec.get("integrations") or [] if d["name"] != name]
        spec["requirements"] = [r for r in spec["requirements"] if r["id"] != requirement_id(name)]
        if not spec["integrations"]:
            spec.pop("integrations")

    version = _edit_spec(project, change, person=person, persona=persona)
    project.log("integration_withdrawn", {"name": name, "requirement": requirement_id(name), "by": person,
                                          "persona": persona, "reason": clean_text(reason, 300, one_line=True),
                                          "spec_version": version})
    return {"name": name, "withdrawn": True, "spec_version": version}


def kinds() -> list[dict[str, Any]]:
    """Every kind with its family, its ways (the default first), its stand-in and its reference connector."""
    return [{"kind": k, "family": v["family"], "via": list(v["vias"]),
             "standin": "sqlite file (via sql); local HTTP server (via http or mcp)",
             "connector": f"connectors/{v['connector']}" if v["connector"] else "none yet (planned)"}
            for k, v in KINDS.items()]


# -- `rihmasto integration ...` ---------------------------------------------------------------------------

def add_parsers(sub: Any) -> None:
    """`rihmasto integration <command>`, as the command line's parser adds it."""
    group = sub.add_parser("integration", help="the data systems a product reaches (kernel/integration_decl.py)")
    cmds = group.add_subparsers(dest="sub", required=True)
    cmds.add_parser("kinds", help="every kind of system, its ways, stand-in and reference connector")
    d = cmds.add_parser("declare", help="a person declares an integration on the open plan")
    d.add_argument("pid")
    d.add_argument("--name", required=True)
    d.add_argument("--kind", required=True, choices=list(KINDS))
    d.add_argument("--via", choices=VIAS)
    d.add_argument("--access", required=True, choices=ACCESS)
    d.add_argument("--data-class", dest="data_classes", action="append", required=True, choices=DATA_CLASSES)
    d.add_argument("--system", choices=SYSTEMS, help="for openapi: the ERP or business system")
    d.add_argument("--credential", dest="credentials", action="append", default=[],
                   help="a credential's NAME (never its value); IT names where it lives on the road")
    d.add_argument("--purpose", default="")
    w = cmds.add_parser("withdraw", help="a person takes an integration off the open plan")
    w.add_argument("pid")
    w.add_argument("name")
    for p in (d, w):
        p.add_argument("--person", required=True)
        p.add_argument("--persona", required=True, choices=PERSONAS)
        p.add_argument("--reason", required=p is w, default="")
    for name, about in (("list", "the project's integrations and each binding per environment"),
                        ("check", "the bindings on the paved roads, checked without opening a card")):
        p = cmds.add_parser(name, help=about)
        p.add_argument("pid")


def _declare(f: Any, a: argparse.Namespace) -> Any:
    decl = {"name": a.name, "kind": a.kind, "access": a.access, "data_classes": a.data_classes,
            "credentials": a.credentials, "purpose": a.purpose}
    decl |= {k: v for k, v in (("via", a.via), ("system", a.system)) if v}
    return declare(f.project(a.pid), decl, person=a.person, persona=a.persona, reason=a.reason)


def handlers(emit: Callable[[Any], None]) -> dict[str, Callable[[Any, argparse.Namespace], None]]:
    """The `rihmasto integration` handlers; ``emit`` prints what each returns."""
    from kernel import integration_bind

    return {
        "integration kinds": lambda f, a: emit({"kinds": kinds()}),
        "integration declare": lambda f, a: emit(_declare(f, a)),
        "integration withdraw": lambda f, a: emit(withdraw(f.project(a.pid), a.name, person=a.person,
                                                           persona=a.persona, reason=a.reason)),
        "integration list": lambda f, a: emit(integration_bind.status(f.project(a.pid))),
        "integration check": lambda f, a: emit(integration_bind.status(f.project(a.pid), problems_only=True)),
    }
