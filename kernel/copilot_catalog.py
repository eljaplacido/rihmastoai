"""What Rihmasto can do, read from the code at run time, for goal help (kernel/copilot.py, FR-CPL1).

A plan for "hook this to Google Drive" or "run it every night in our cloud" is only as honest as what it
rests on, so nothing here is a fixed list of features. Each part is read from the module that owns it:

- **roads**: the paved roads IT configured (kernel/roads.py, ``paved_roads.json``) with their kinds and
  environments, and the road kinds this build has (a Google Cloud road only when ``kernel.roads_gcp`` is in it);
- **connectors**: the connector folders and whether IT enabled each (kernel/connectors.py), and the data
  integration kinds a product may declare (kernel/integration_decl.py);
- **profiles** and **outputs**: the kinds of work and what each audience receives;
- **checks**, **automation templates**, **runners** and **walkthroughs**: from kernel/checks, kernel/automations_text,
  kernel/runners and kernel/walkthrough when this build has them, else ``available: False``;
- **views**: Insights, Review and Alignment, when their modules are in this build.

``system_support`` says how a named system (Google Drive, Postgres, SAP...) is reached today: a connector,
an integration kind, or a gap with the options there are. Reading the catalogue writes nothing.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import re
from typing import Any

# How a person names a system, and what Rihmasto knows it as: an integration kind, a connector folder, and
# the words that name it. Order matters: the first match wins ("google drive" before "google").
SYSTEMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("google_drive", "Google Drive", ("google drive", "gdrive", "g drive", "drive", "google docs", "google sheets")),
    ("sharepoint", "SharePoint or OneDrive", ("sharepoint", "onedrive", "one drive")),
    ("dropbox", "Dropbox", ("dropbox",)),
    ("s3", "Amazon S3", ("s3", "aws bucket", "amazon bucket")),
    ("gcs", "Google Cloud Storage", ("google cloud storage", "gcs", "gcp bucket")),
    ("azure_blob", "Azure Blob Storage", ("azure blob", "blob storage")),
    ("postgres", "PostgreSQL", ("postgres", "postgresql")),
    ("mysql", "MySQL", ("mysql", "mariadb")),
    ("sqlserver", "SQL Server", ("sql server", "mssql")),
    ("snowflake", "Snowflake", ("snowflake",)),
    ("bigquery", "BigQuery", ("bigquery", "big query")),
    ("databricks", "Databricks", ("databricks",)),
    ("sap", "SAP", ("sap",)),
    ("dynamics", "Dynamics 365", ("dynamics",)),
    ("netsuite", "NetSuite", ("netsuite",)),
    ("salesforce", "Salesforce", ("salesforce", "crm")),
    ("slack", "Slack", ("slack",)),
    ("teams", "Microsoft Teams", ("teams",)),
    ("jira", "Jira", ("jira",)),
    ("database", "a database", ("database", "tietokanta", "db")),
    ("api", "an API", ("rest api", "api", "rajapinta")),
)
# A system Rihmasto reaches as an integration kind of kernel/integration_decl.py (an ERP is openapi with a system).
AS_KIND = {"google_drive": "gdrive", "s3": "s3", "gcs": "gcs", "azure_blob": "azure_blob", "postgres": "postgres",
           "mysql": "mysql", "sqlserver": "sqlserver", "snowflake": "snowflake", "bigquery": "bigquery",
           "databricks": "databricks", "sap": "openapi", "dynamics": "openapi", "netsuite": "openapi", "api": "rest"}


def has(module: str) -> bool:
    """Whether this build has ``module`` (a stream that has not merged yet is simply not there)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def optional(module: str) -> Any:
    """The module when this build has it, else None: nothing here fails because a stream has not merged."""
    if not has(module):
        return None
    try:
        return importlib.import_module(module)
    except Exception:  # noqa: BLE001 - a module that does not import is as good as absent here
        return None


def _say(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def system_named(text: str) -> tuple[str, str] | None:
    """The system a sentence names (its key and label), or None."""
    said = " " + re.sub(r"[^a-z0-9åäö ]+", " ", _say(text)) + " "
    for key, label, names in SYSTEMS:
        if any(f" {n} " in said for n in names):
            return key, label
    return None


# -- the parts -----------------------------------------------------------------------------------------

def roads(factory: Any) -> dict[str, Any]:
    from kernel.roads import BUILTIN_ROADS, ENVIRONMENTS, KINDS, PavedRoads

    paved = PavedRoads.load(factory)
    rows = [{"name": name, "kind": cfg.get("kind"), "configured": cfg.get("configured") is True,
             "environments": cfg.get("environments") or list(ENVIRONMENTS), "builtin": name in BUILTIN_ROADS}
            for name, cfg in paved.roads.items()]
    gcp = optional("kernel.roads_gcp")
    kinds = list(dict.fromkeys([*KINDS, *([str(getattr(gcp, "KIND", "gcp-cloudrun"))] if gcp is not None else [])]))
    return {"roads": rows, "kinds": kinds, "gcp": gcp is not None, "file": paved.source,
            "configured": [r["name"] for r in rows if r["configured"] and not r["builtin"]],
            "problems": list(paved.problems)}


def connectors(factory: Any) -> list[dict[str, Any]]:
    from kernel import connectors as kconnectors

    out = []
    for state in kconnectors.status(factory):
        system = state["system"]
        title = system
        with contextlib.suppress(OSError, ValueError, KeyError):   # a folder that does not load keeps its name
            title = str(kconnectors.load(kconnectors.DEFAULT_ROOT, system).get("title") or system)
        out.append({"system": system, "title": title, "state": state.get("state"), "card": state.get("card")})
    return out


def integration_kinds() -> list[dict[str, Any]]:
    from kernel.integration_decl import KINDS

    return [{"kind": k, "family": v["family"], "vias": list(v["vias"]), "connector": v.get("connector"),
             "client": v.get("client")} for k, v in KINDS.items()]


def _checks() -> dict[str, Any]:
    mod = optional("kernel.checks")
    if mod is None:
        return {"available": False, "kinds": []}
    try:
        return {"available": True, "kinds": [{"kind": c["kind"], "label": c["label"]} for c in mod.public()]}
    except Exception:  # noqa: BLE001
        return {"available": False, "kinds": []}


def _automations() -> dict[str, Any]:
    mod = optional("kernel.automations_text")
    if mod is None:
        return {"available": False, "templates": []}
    return {"available": True, "templates": [{"id": t["id"], "label": t["label"], "about": t.get("about", "")}
                                             for t in getattr(mod, "TEMPLATES", [])]}


def _runners(factory: Any, project: Any) -> dict[str, Any]:
    mod = optional("kernel.runners")
    if mod is None:
        return {"available": False, "runners": [], "builder": "gnomon"}
    builder = "gnomon"
    choice = optional("kernel.runners.choice")
    if choice is not None and project is not None:
        try:
            builder = str(choice.effective(factory, project.pid, "builder").get("runner") or "gnomon")
        except Exception:  # noqa: BLE001
            builder = "gnomon"
    return {"available": True, "builder": builder,
            "runners": [{"name": n, "label": r.get("label", n)} for n, r in getattr(mod, "RUNNERS", {}).items()]}


def _walkthroughs() -> dict[str, Any]:
    mod = optional("kernel.walkthrough")
    if mod is None:
        return {"available": False, "flows": []}
    try:
        return {"available": True, "flows": mod.catalogue()}
    except Exception:  # noqa: BLE001
        return {"available": False, "flows": []}


def _models() -> dict[str, Any]:
    """Whether a model Rihma talks with answers (Models setup, read without asking any endpoint) and the coding
    agents on this machine that could answer the text roles instead (kernel/harness_setup.py, FR-HMD1)."""
    setup, models = optional("kernel.harness_setup"), optional("kernel.models_setup")
    if setup is None or models is None:
        return {"ready": True, "harnesses": [], "available": False}
    try:
        ready = bool(models.models_view(probe=False).get("ready"))
        found = [{"id": h["id"], "label": h["label"], "version": h.get("version")} for h in setup.found_harnesses()]
    except Exception:  # noqa: BLE001 - Models setup that cannot be read offers nothing here
        return {"ready": True, "harnesses": [], "available": False}
    return {"ready": ready, "harnesses": found, "available": True}


def catalogue(factory: Any, project: Any = None) -> dict[str, Any]:
    """Everything a plan may point at, as this build and this factory have it now."""
    from kernel.outputs import TARGETS
    from kernel.profiles import PROFILES

    return {
        "roads": roads(factory),
        "connectors": connectors(factory),
        "integration_kinds": integration_kinds(),
        "profiles": [{"id": k, "label": v.get("label")} for k, v in PROFILES.items()],
        "outputs": [{"id": k, "label": v["label"]} for k, v in TARGETS.items()],
        "checks": _checks(),
        "automations": _automations(),
        "runners": _runners(factory, project),
        "walkthroughs": _walkthroughs(),
        "models": _models(),
        "views": {"insights": has("kernel.insights"), "review": has("kernel.review"),
                  "alignment": has("kernel.alignment_records"), "console": has("kernel.console")},
        "agent_context": has("kernel.ide"),
        "evals": _evals(),            # Gnomon's audits, benchmarks and evals, and the role evals (FR-EVL1)
    }


def _evals() -> dict[str, Any]:
    goal = optional("kernel.gnomon_evals_goal")
    return goal.catalogue() if goal is not None else {"available": False, "evals": [], "role_sets": []}


# -- how a system is reached ----------------------------------------------------------------------------

def _connector_for(cat: dict[str, Any], key: str, label: str) -> dict[str, Any] | None:
    words = {key.replace("_", "-"), key.replace("_", ""), *_say(label).split()}
    for c in cat["connectors"]:
        name = _say(c["system"] + " " + c["title"])
        if c["system"] in words or (key == "google_drive" and "drive" in name) or c["system"] == AS_KIND.get(key):
            return c
    return None


def system_support(cat: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    """How ``key`` is reached today: ``connector`` (a folder IT enables), ``kind`` (a data integration the
    product declares), or ``gap`` with the options there are. Never a guess presented as a feature."""
    conn = _connector_for(cat, key, label)
    kind = AS_KIND.get(key)
    if conn is not None:
        return {"how": "connector", "system": key, "label": label, "connector": conn, "kind": kind,
                "enabled": conn["state"] == "enabled"}
    if kind is not None:
        return {"how": "kind", "system": key, "label": label, "kind": kind, "enabled": True}
    options = [
        f"declare it as a REST integration (kind rest, via http) against {label}'s own API, with the credential's "
        "name only; IT binds where the credential lives on the road",
        f"declare an MCP integration (kind mcp) to an MCP server for {label} that your IT runs and pins",
        "copy the files to storage Rihmasto already reaches (Google Cloud Storage or Amazon S3) and declare that",
        f"ask for a {label} connector: a change to Rihmasto itself, filed as a signal in the delivery square",
    ]
    return {"how": "gap", "system": key, "label": label, "kind": None, "enabled": False,
            "gap": f"There is no {label} connector in this Rihmasto yet.", "options": options}
