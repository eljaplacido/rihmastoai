"""Binding a product's declared integrations on the paved roads, and handing them to the product (FR-DS2).

A declaration (kernel/integration_decl.py) names what the product needs. Where that system is for one
environment is IT's: the road that serves the environment binds it in `paved_roads.json`, beside the
road's other settings:

    "team-docker": {"kind": "docker", ..., "integrations": {
        "orders_db": {"endpoint": "https://orders-data.internal/api",
                      "secrets": [{"name": "ORDERS_DB_PASSWORD", "ref": "env:ORDERS_STAGING_PASSWORD"}]},
        "erp": {"staging": {"endpoint": "https://erp-test.internal/odata"},
                "production": {"endpoint": "https://erp.internal/odata"}}}}

A binding gives the endpoint (no user's password and no secret in it) and, for every credential the
declaration names, where its value lives (`env:`, `os:`, `cmd:` or a vault URL, never the value).

**IT approves each binding on a road card.** Before anything is built, delivery checks every declared
integration in every environment of its plan. A binding that is missing or wrong, and a valid one no card
has approved, opens a `road` card for IT that shows what the product reaches, with which access, which
data classes, and where each credential lives, and the release waits. `configured` lets it go on,
`declined` stops it. The card pins the sha256 of the road, the environment, the declaration and the
binding: a later change to any of them withdraws an open card and opens a new one, and a release never
runs on a binding nobody approved as it stands.

**Delivery wires them.** Each deploy package gets an `integrations` list (what was approved, by which
card), the settings `<NAME>_URL`, `<NAME>_ACCESS` and `<NAME>_KIND`, and each credential as a secret
reference. A site's Compose file gives the product each setting, and each secret by its name from the
deployer's environment (kernel/roads.py `render_compose`). A local process gets the settings, and a
secret whose reference is `env:` from the kernel host's environment; a docker product gets the settings
as values and each such secret by name only (`docker run --env NAME`), its value handed to the docker CLI
in that command's environment, so it never appears in an argument, a package or a record (FR-DS5).
"""

from __future__ import annotations

import hashlib
import os
import urllib.parse
from typing import Any

from kernel.connectors import SECRETISH
from kernel.integration_decl import KINDS, SECRET_WORD, note, requirement_id, settings, steers_tooling
from kernel.ledger import canonical_json

BINDING_KEYS = ("endpoint", "secrets", "note")
LOOPBACK = ("127.0.0.1", "localhost", "::1")
DECL_KEYS = ("name", "kind", "via", "access", "data_classes", "credentials", "system")


def declared(project: Any) -> list[dict[str, Any]]:
    """The integrations the project's spec declares."""
    return list((project.read("spec.json") or {}).get("integrations") or [])


def binding_of(cfg: dict[str, Any], name: str, env: str) -> dict[str, Any] | None:
    """A road's binding of an integration for an environment: one for every environment the road serves,
    or one per environment."""
    found = (cfg.get("integrations") or {}).get(name) if isinstance(cfg.get("integrations"), dict) else None
    if isinstance(found, dict) and "endpoint" not in found:
        found = found.get(env)
    return found if isinstance(found, dict) else None


def endpoint_problems(decl: dict[str, Any], endpoint: Any) -> list[str]:
    """What is wrong with an endpoint for this declaration: its scheme, and any credential it carries."""
    if not isinstance(endpoint, str) or not endpoint.strip():
        return ["the binding gives no endpoint"]
    url = urllib.parse.urlsplit(endpoint.strip())
    problems = []
    if decl["via"] == "sql":
        schemes = KINDS[decl["kind"]]["schemes"]
        if url.scheme not in schemes:
            problems.append(f"a {decl['kind']} endpoint reached via sql is a {' or '.join(schemes)}: URL")
    elif not (url.scheme == "https" or url.scheme == "http" and url.hostname in LOOPBACK):
        problems.append(f"an endpoint reached via {decl['via']} is https (plain http only on loopback)")
    if url.password is not None or SECRETISH.search(endpoint):
        problems.append("the endpoint carries a password or a token: name it as a credential instead")
    keys = [k for k, _ in urllib.parse.parse_qsl(url.query)]
    if any(SECRET_WORD.search(k) or k.lower() in ("sig", "signature", "key", "sas") for k in keys):
        problems.append("the endpoint's query carries a secret: name it as a credential instead")
    return problems


def binding_problems(decl: dict[str, Any], binding: dict[str, Any] | None, road: str) -> list[str]:
    """Every way a binding fails its declaration; empty when IT may approve it."""
    if binding is None:
        return [f"the road {road} binds no {decl['name']} for this environment "
                f"(roads.{road}.integrations.{decl['name']} in paved_roads.json)"]
    problems = [f"the binding has an unknown key {k}" for k in sorted(set(binding) - set(BINDING_KEYS))]
    problems += endpoint_problems(decl, binding.get("endpoint"))
    named: dict[str, Any] = {}
    for s in binding.get("secrets") or []:
        if not isinstance(s, dict) or not isinstance(s.get("name"), str):
            problems.append("a binding secret has no name")
            continue
        if "value" in s:
            problems.append(f"the secret {s['name']} carries a value: a road names where a secret lives, never it")
        if not isinstance(s.get("ref"), str) or not s["ref"].strip() or SECRETISH.search(s["ref"]):
            problems.append(f"the secret {s['name']} needs a ref: env:NAME, os:NAME, cmd:<command> or a vault URL")
        named[s["name"]] = s.get("ref")
    problems += [f"the credential {c} is not given a ref (where its value lives)"
                 for c in decl.get("credentials") or [] if c not in named]
    problems += [f"{n} is not a credential the declaration names" for n in sorted(set(named) - set(
        decl.get("credentials") or []))]
    return problems + _steering(decl["name"], [*settings(decl).values(), *named])


def _steering(name: Any, names: Any) -> list[str]:
    """A credential or setting named like a variable the deploy tools read would steer them (FR-DS5-AC-2)."""
    return [f"{n} is named like a variable the deploy tools read (DOCKER_, HTTP_, SSL_, LD_ ...): rename "
            f"the integration {name}" for n in sorted(names) if steers_tooling(n)]


def pin_of(road: str, env: str, decl: dict[str, Any], binding: dict[str, Any] | None) -> str:
    """What a binding card pins: the road, the environment, the declaration and the binding as they stand."""
    pinned = {"road": road, "environment": env, "declaration": {k: decl.get(k) for k in DECL_KEYS},
              "binding": binding}
    return hashlib.sha256(canonical_json(pinned).encode("utf-8")).hexdigest()


def _cards(canon: Any, name: str, env: str) -> list[dict[str, Any]]:
    """An integration's binding cards for one environment. Their refs use the ontology's keys only
    (kernel/ontology.json, which the owner amends): the card rests on the integration's INT- requirement."""
    return [c for c in canon.cards(state=None, kind="road") if c["refs"].get("scope") == "integration"
            and c["refs"].get("requirement") == requirement_id(name) and c["refs"].get("environments") == [env]]


def _body(delivery: Any, decl: dict[str, Any], binding: dict[str, Any] | None, road: str, env: str,
          problems: list[str]) -> str:
    rel, b = delivery.rel, binding or {}
    secrets = [f"{s.get('name')} from {s.get('ref')}" for s in b.get("secrets") or [] if isinstance(s, dict)]
    who = f"declared by {decl['declared_by']}" if decl.get("declared_by") else f"proposed ({decl.get('provenance')})"
    lines = [f"Release {rel['release']} of {delivery.project.meta['title']} (revision {rel['rev12']}) reaches "
             f"{decl['name']} from {env}, on the road {road}.", "",
             f"What it reaches: {decl['kind']}" + (f" ({decl['system']})" if decl.get("system") else "")
             + f" via {decl['via']}, access {decl['access'].upper()}.",
             f"Endpoint: {b.get('endpoint') or '(none given)'}.",
             f"Data classes: {', '.join(decl['data_classes'])}.",
             "Credentials (names and where each lives, never a value): " + (", ".join(secrets) or "none") + ".",
             f"Why: {decl.get('purpose') or '(no purpose given)'}; {who}."]
    if note(decl):
        lines.append(f"Note: {note(decl)}.")
    if problems:
        lines += ["", "What is wrong with the binding:", *[f"- {p}" for p in problems], "",
                  f"Fix it in {delivery.project.factory.paved_roads_path}, then decide this card."]
    lines += ["", f"Decide `configured` to let the product reach {decl['name']} from {env}, or `declined` to stop "
              "the release. A later change to the binding or the declaration opens a new card."]
    return "\n".join(lines)


def _open(delivery: Any, decl: dict[str, Any], binding: dict[str, Any] | None, road: str, env: str, pin: str,
          problems: list[str]) -> dict[str, Any]:
    title = f"Bind {decl['name']} ({decl['kind']}, {decl['access']}) for {env} on {road}" + \
        (f": {len(problems)} {'problem' if len(problems) == 1 else 'problems'}" if problems else "")
    card = delivery.canon.card(
        "road", title, body=_body(delivery, decl, binding, road, env, problems), blocking=True,
        refs={"scope": "integration", "requirement": requirement_id(decl["name"]), "environments": [env],
              "roads": [road], "release": delivery.rel["release"]},
        payload={"pin": pin, "integration": decl["name"], "declaration": {k: decl.get(k) for k in DECL_KEYS},
                 "binding": binding, "problems": problems})
    delivery.rel["cards"].append({"step": f"integration:{decl['name']}:{env}", "card": card["id"], "kind": "road",
                                  "decision": None, "opened": delivery.now()})
    return card


def _state(delivery: Any, decl: dict[str, Any], road: str, cfg: dict[str, Any], env: str) -> dict[str, Any]:
    """Whether one integration is approved for one environment: approved, declined or waiting (on a card)."""
    binding = binding_of(cfg, decl["name"], env)
    problems = binding_problems(decl, binding, road)
    pin = pin_of(road, env, decl, binding)
    row: dict[str, Any] = {"road": road, "pin": pin, "declaration": {k: decl.get(k) for k in DECL_KEYS},
                           "binding": binding, "problems": problems}
    cards = _cards(delivery.canon, decl["name"], env)
    for c in cards:
        if c["state"] == "open" and c["payload"].get("pin") != pin:
            delivery.canon.close(c["id"], "the binding or the declaration changed: a new card follows")
    same = [c for c in cards if c["payload"].get("pin") == pin and c["state"] in ("open", "decided")]
    card = max(same, key=lambda c: int(c["id"].split("-")[1]), default=None)
    if card is not None and card["state"] == "decided":
        decision = card["decision"]
        if decision["verdict"] == "declined":
            return row | {"state": "declined", "card": card["id"], "by": decision["person"],
                          "reason": decision.get("reason")}
        if not problems:
            return row | {"state": "approved", "card": card["id"], "by": decision["person"]}
        card = None  # configured while the binding is still wrong: a new card names what is left
    if card is None:
        card = _open(delivery, decl, binding, road, env, pin, problems)
    return row | {"state": "waiting", "card": card["id"]}


def check(delivery: Any) -> str:
    """Every declared integration, in every environment of the release's plan, needs a binding IT approved
    on a road card: "ready", "waiting" (on the first card still open) or "failed" (IT declined one)."""
    decls = declared(delivery.project)
    if not decls:
        return "ready"
    rel = delivery.rel
    state: dict[str, dict[str, Any]] = {}
    for env in rel["environments"]:
        road = str(rel["roads"][env]["name"])
        cfg = delivery.paved.roads.get(road) or {}
        state[env] = {d["name"]: _state(delivery, d, road, cfg, env) for d in decls}
    rel["integrations"] = state
    rows = [(env, name, row) for env, names in state.items() for name, row in names.items()]
    declined = [(env, name, row) for env, name, row in rows if row["state"] == "declined"]
    if declined:
        env, name, row = declined[0]
        delivery.fail("integrations", {"outcome": "failed", "native": {
            "card": row["card"], "why": f"IT declined the binding of {name} for {env} ({row['by']}): {row['reason']}"}})
        return "failed"
    waiting = [row["card"] for _, _, row in rows if row["state"] == "waiting"]
    if waiting:
        rel["state"], rel["waiting_on"] = "waiting", waiting[0]
        delivery.save()
        delivery.log("integrations_waiting", cards=waiting)
        return "waiting"
    delivery.save()
    delivery.log("integrations_bound", bound={env: {n: r["card"] for n, r in names.items()}
                                              for env, names in state.items()})
    return "ready"


def wire(pkg: dict[str, Any], rel: dict[str, Any], env: str) -> dict[str, Any]:
    """Add the environment's approved integrations to a deploy package: what was approved and by which card,
    each one's settings, and each credential as a secret reference."""
    rows = (rel.get("integrations") or {}).get(env) or {}
    out = []
    for name, row in sorted(rows.items()):
        if row.get("state") != "approved":
            continue
        decl, binding = row["declaration"], row["binding"] or {}
        s = settings(decl)
        pkg["settings"] |= {s["url"]: binding["endpoint"], s["access"]: decl["access"], s["kind"]: decl["kind"]}
        refs = [{"name": x["name"], "ref": x["ref"]} for x in binding.get("secrets") or []]
        pkg["secrets"] = list(pkg.get("secrets") or []) + refs
        out.append({"name": name, "kind": decl["kind"], "via": decl["via"], "access": decl["access"],
                    "data_classes": decl["data_classes"], "endpoint": binding["endpoint"],
                    "settings": list(s.values()), "secrets": [r["name"] for r in refs], "card": row["card"],
                    "pin": row["pin"], "approved_by": row.get("by")})
    if out:
        pkg["integrations"] = out
    return pkg


def secret_values(pkg: dict[str, Any]) -> dict[str, str]:
    """Each credential of the package's integrations whose reference is `env:` and that this host's
    environment holds, by the credential's name; read at deploy time and kept in memory only (FR-DS5)."""
    out: dict[str, str] = {}
    for item in pkg.get("integrations") or []:
        for s in pkg.get("secrets") or []:
            ref = str(s.get("ref", ""))
            if s.get("name") in item["secrets"] and ref.startswith("env:") and ref[4:] in os.environ:
                out[str(s["name"])] = os.environ[ref[4:]]
    return out


def env_of(pkg: dict[str, Any], *, resolve: bool = False) -> dict[str, str]:
    """The environment a product gets for its integrations: each setting; with ``resolve``, also each
    secret whose reference is `env:` (read from this host's environment, kept in memory only)."""
    out: dict[str, str] = {}
    for item in pkg.get("integrations") or []:
        out |= {k: str(pkg["settings"][k]) for k in item["settings"] if k in pkg["settings"]}
    return out | (secret_values(pkg) if resolve else {})


def package_problems(pkg: dict[str, Any]) -> list[str]:
    """What is wrong with a package's integrations: one not approved by a card, an endpoint that carries a
    credential, a setting that does not match, or a credential with no reference."""
    problems = []
    refs = {s.get("name"): s.get("ref") for s in pkg.get("secrets") or [] if isinstance(s, dict)}
    for item in pkg.get("integrations") or []:
        name = item.get("name")
        if not item.get("card") or not item.get("pin"):
            problems.append(f"integration {name} was approved by no card")
        if item.get("kind") not in KINDS or item.get("via") not in KINDS.get(item.get("kind"), {}).get("vias", ()):
            problems.append(f"integration {name} has an unknown kind or way")
            continue
        problems += [f"integration {name}: {p}" for p in endpoint_problems(item, item.get("endpoint"))]
        if [pkg["settings"].get(k) for k in item.get("settings", [])[:1]] != [item.get("endpoint")]:
            problems.append(f"integration {name}: its endpoint setting is not the approved endpoint")
        problems += [f"integration {name}: the credential {c} has no reference" for c in item.get("secrets") or []
                     if not refs.get(c)]
        problems += [f"integration {name}: {p}" for p in _steering(name, [*item.get("settings", []),
                                                                         *(item.get("secrets") or [])])]
    return problems


def status(project: Any, *, problems_only: bool = False) -> dict[str, Any]:
    """The project's integrations and, for each environment its maturity delivers to, the road that serves
    it and whether the binding there is valid and approved; nothing is opened or changed."""
    from kernel.canon import Canon
    from kernel.deliver import delivery_plan, plan_environments
    from kernel.roads import PavedRoads

    paved, canon = PavedRoads.load(project.factory), Canon(project)
    envs = plan_environments(delivery_plan(project.meta["maturity"]))
    rows = []
    for decl in declared(project):
        for env in envs:
            road = paved.name_for(project, env)
            binding = binding_of(paved.roads.get(road) or {}, decl["name"], env) if road else None
            problems = binding_problems(decl, binding, str(road)) if road else ["no paved road serves " + env]
            pin = pin_of(str(road), env, decl, binding)
            cards = [c for c in _cards(canon, decl["name"], env) if c["payload"].get("pin") == pin]
            card = max(cards, key=lambda c: int(c["id"].split("-")[1]), default=None)
            state = "invalid" if problems else (card or {}).get("state") or "not approved"
            if card is not None and card["state"] == "decided" and not problems:
                state = "approved" if card["decision"]["verdict"] == "configured" else "declined"
            if not problems_only or problems:
                rows.append({"integration": decl["name"], "environment": env, "road": road, "state": state,
                             "card": card["id"] if card else None, "problems": problems})
    return {"project": project.pid, "integrations": declared(project), "bindings": rows}
