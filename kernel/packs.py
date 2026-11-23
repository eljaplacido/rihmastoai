"""Capability packs: one manifest per release that says exactly what was delivered.

After the agentic capability layer: "pack version equals behaviour version". A pack names every
part of what was delivered by its hash: the contract, the product revision, the image, the harness
surfaces that built it, the models that built and judged it. It also carries its acceptance: the
criteria with their evidence, and the holdouts' results as scores only, never the scenarios (the
eval set stays where it is; only scores leave).

- If any hash changes, the version changes. The same content keeps its version.
- A pack is valid only while its acceptance holds: every criterion verified or held out and
  passing. Otherwise it says which criteria are not, and why.
- What is not there is said: no SBOM generated, not signed (no signer configured), runtime
  models not declared by the product template, "not measured: no security scan". Nothing is
  claimed that was not done.
- It names the latest security scan per tool (`kernel/security.py`): its counts and the risks a
  person accepted, with their expiry.

The same format serves every deliverable: a product, an agent or assistant, a model, or an ops
agent's report.

Each pack also **declares** (FR-Q6-AC-3), apart from what was measured:
- the workload classes it uses (interactive, batch, specialist), by role (`kernel/fit.py`);
- the site mode, from the factory's policy: `connected` (the default), `restricted` or
  `air-gapped`;
- the fallback ladder, filtered by the site mode: L1 the same pack elsewhere, L2 a smaller model,
  degraded, L3 the cloud, only for the data classes the policy allows, L4 queue and defer.

The declarations decide where the capability may run when something fails, so they are part of
its behaviour: they are hashed, and when they change the version changes. Where the site mode
came from (the default or a person's policy) is not behaviour and is not hashed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from kernel.canon import DecisionRefused
from kernel.ledger import canonical_json
from kernel.people import is_person
from kernel.store import read_json

PACK_FORMAT = "rihma.capability-pack.v1"
SITE_MODES = ("connected", "restricted", "air-gapped")
DEFAULT_SITE_MODE = "connected"
DEFAULT_CLOUD_DATA_CLASSES = ("public",)
SITE_SETTERS = ("it", "compliance")
LADDER = (
    ("L1", "same pack elsewhere", "the same pinned pack, on another endpoint or host"),
    ("L2", "smaller model, degraded", "a smaller model; the capability says what it no longer does"),
    ("L3", "cloud, allowed data classes only", "a cloud endpoint, only for the data classes the policy allows"),
    ("L4", "queue and defer", "the work waits in a queue and is answered later"),
)
# Not part of the content hash: when the pack was built, evidence about the release (the latest
# security scan), and the version and hash themselves.
_UNHASHED = ("acceptance", "provenance", "security", "version", "content_sha256")


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_sha256(pack: dict) -> str:
    """The hash a pack's version rests on: what it pins and declares, and its acceptance's criteria
    and holdout scores. Recomputable from a pack as it was written."""
    body = {k: v for k, v in pack.items() if k not in _UNHASHED}
    body["provenance"] = {k: v for k, v in (pack.get("provenance") or {}).items() if k != "ledger_head"}
    acc = pack.get("acceptance") or {}
    body["acceptance"] = {"criteria": acc.get("criteria"), "holdout_scores": acc.get("holdout_scores")}
    if isinstance(body.get("declared"), dict) and isinstance(body["declared"].get("site_mode"), dict):
        site = {k: v for k, v in body["declared"]["site_mode"].items() if k != "source"}
        body["declared"] = {**body["declared"], "site_mode": site}
    return _sha(body)


# -- site mode and the fallback ladder --------------------------------------------------------------

def site_policy(factory: Any) -> dict:
    """The site mode and the data classes the cloud may see, from the factory's policy. Reads only."""
    from kernel.learn import FACTORY_PID

    policy = read_json(factory.projects_dir / FACTORY_PID / "policy.json", {}) or {}
    mode, classes = policy.get("site_mode"), policy.get("cloud_data_classes")
    return {"mode": mode if mode in SITE_MODES else DEFAULT_SITE_MODE,
            "source": "factory policy" if mode in SITE_MODES else "default: no site mode is set",
            "cloud_data_classes": sorted(str(c) for c in classes) if isinstance(classes, list)
            else list(DEFAULT_CLOUD_DATA_CLASSES)}


def set_site_mode(factory: Any, mode: str, *, person: str, persona: str, reason: str,
                  cloud_data_classes: list | None = None) -> dict:
    """IT or compliance sets the site mode (and, optionally, the data classes the cloud may see)."""
    from kernel.learn import factory_project

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in SITE_SETTERS:
        raise DecisionRefused(f"a {persona} may not set the site mode; {', '.join(SITE_SETTERS)} may")
    if mode not in SITE_MODES:
        raise ValueError(f"the site mode is one of {', '.join(SITE_MODES)}")
    if not str(reason).strip():
        raise ValueError("a site mode change needs a reason")
    store = factory_project(factory)
    policy = store.read("policy.json", {}) or {}
    before = policy.get("site_mode", DEFAULT_SITE_MODE)
    policy["site_mode"] = mode
    if cloud_data_classes is not None:
        policy["cloud_data_classes"] = sorted({str(c).strip() for c in cloud_data_classes if str(c).strip()})
    store.write("policy.json", policy)
    store.log("site_mode_set", {"from": before, "to": mode, "cloud_data_classes": policy.get("cloud_data_classes"),
                                "by": person, "persona": persona, "reason": reason})
    return site_policy(factory)


def ladder(site: dict) -> list:
    """The fallback ladder with each level's place at this site: whether it applies, and why not."""
    mode = site["mode"]
    classes = [c for c in site["cloud_data_classes"] if mode == "connected" or c == "public"]
    out = []
    for level, name, rule in LADDER:
        step: dict = {"level": level, "name": name, "rule": rule, "applies": True}
        if level == "L1" and mode != "connected":
            step["scope"] = "inside the site only"
        if level == "L3":
            if mode == "air-gapped":
                step.update(applies=False, why="nothing leaves an air-gapped site")
            elif not classes:
                step.update(applies=False, why=f"no data class may go to the cloud from a {mode} site")
            else:
                step["data_classes"] = classes
        out.append(step)
    return out


def declarations(project: Any, models: dict) -> dict:
    """What the pack declares: its workload classes, the site mode and the fallback ladder."""
    from kernel.fit import workload_of

    by_role = {role: workload_of(role) for role in sorted(models.get("by_role") or {})}
    site = site_policy(project.factory)
    steps = ladder(site)
    return {"workload_classes": {"used": sorted({c for c in by_role.values() if c}), "by_role": by_role,
                                 "runtime": "not declared: the product template does not declare runtime roles"},
            "site_mode": {"mode": site["mode"], "source": site["source"],
                          "levels": [s["level"] for s in steps if s["applies"]]},
            "fallback_ladder": steps}


def _latest_release(project, release_no: int | None):
    from kernel.deliver import releases

    rels = releases(project)
    if release_no is not None:
        rels = [r for r in rels if r["release"] == release_no]
    return rels[-1] if rels else None


def _models(project) -> dict:
    """The models that built and judged this product, from the ledger's Gnomon runs: by role, with
    the harness surface hashes they ran under."""
    by_role, surfaces = {}, set()
    for rec in project.ledger().of_kind("gnomon_run"):
        pl = rec["event"]["payload"]
        if pl.get("role") and pl.get("model"):
            by_role.setdefault(pl["role"], set()).add(f"{pl['model']}@{pl.get('endpoint') or '?'}")
        if pl.get("surface_hash"):
            surfaces.add(pl["surface_hash"])
    for rec in project.ledger().of_kind("cell_ran"):
        pl = rec["event"]["payload"]
        if pl.get("final_model"):
            by_role.setdefault("builder", set()).add(str(pl["final_model"]))
    return {"by_role": {k: sorted(v) for k, v in sorted(by_role.items())}, "surfaces": sorted(surfaces)}


def acceptance(project, rel: dict | None) -> dict:
    from kernel.status import evidence

    crits = evidence(project) if project.path("contract.json").exists() else []
    holdouts = (rel or {}).get("holdouts") or {}
    results = holdouts.get("results") if isinstance(holdouts, dict) else None
    scores = None
    if isinstance(results, list):
        scores = {"passed": sum(1 for r in results if r.get("verdict") == "passed"),
                  "failed": sum(1 for r in results if r.get("verdict") not in ("passed", None)), "total": len(results),
                  "by_criterion": {r.get("criterion"): r.get("verdict") for r in results}}
    not_ok = [{"criterion": c["criterion"], "state": c["state"]} for c in crits
              if c["state"] not in ("verified", "held_out")]
    return {"criteria": [{"id": c["criterion"], "kind": c.get("kind"), "state": c["state"]} for c in crits],
            "holdout_scores": scores, "valid": bool(crits) and not not_ok, "not_valid_because": not_ok}


def build_pack(project, release_no: int | None = None) -> dict:
    """The pack for a release (the latest by default). Writes it beside the release and returns it."""
    from kernel.autonomy import cap_of
    from kernel.profiles import profile_of
    from kernel.security import summary as security_summary

    rel = _latest_release(project, release_no)
    if rel is None:
        raise LookupError("the project has no release yet")
    contract = project.read("contract.json") or {}
    profile = profile_of(project)
    head = project.ledger().head()
    models = _models(project)
    body = {
        "format": PACK_FORMAT, "pack": project.pid, "title": project.meta.get("title"),
        "profile": profile["id"], "deliverable": profile.get("deliverable", "product"),
        "release": rel["release"], "maturity": rel["maturity"], "autonomy_cap": cap_of(project),
        "pinned": {
            "contract_revision": rel.get("contract_revision") or contract.get("revision"),
            "product_revision": rel.get("revision"),
            "artifacts": {k: (v.get("image") or v.get("ref") or v.get("id")) if isinstance(v, dict) else v
                          for k, v in sorted((rel.get("artifacts") or {}).items())},
            "built_and_judged_by": models,
        },
        "runtime": {"declared": False, "note": "the product template does not declare runtime models yet"},
        "declared": declarations(project, models),
        "acceptance": acceptance(project, rel),
        "security": security_summary(project),
        "provenance": {"sbom": None, "sbom_note": "not generated", "signature": None,
                       "signature_note": "not signed: no signer configured",
                       "ledger_head": head.get("hash") if isinstance(head, dict) else None},
    }
    # The ledger head says when the pack was built, not what it holds, so it is not part of its content.
    # Nor is the latest security scan: it is evidence about the release, and a new scan of the same
    # release does not change its behaviour or its version.
    content = content_sha256(body)
    version = _version(project, rel["release"], content, body["acceptance"]["valid"])
    pack = {**body, "version": version, "content_sha256": content}
    project.write(f"releases/{rel['release']}/capability-pack.json", pack)
    return pack


def _version(project: Any, release: int, content: str, valid: bool) -> str:
    """The same content keeps its version; new content is the next minor version, recorded."""
    history = project.read("packs.json", []) or []
    if history and history[-1]["content_sha256"] == content:
        return str(history[-1]["version"])
    version = f"1.{len(history)}.0"
    history.append({"version": version, "content_sha256": content, "release": release,
                    "at": project.factory.clock.stamp()})
    project.write("packs.json", history)
    project.log("pack_versioned", {"version": version, "release": release, "content_sha256": content,
                                   "valid": valid})
    return version


def latest_pack(project: Any) -> dict | None:
    """The newest capability pack, as it was written beside its release. Reads only: nothing is
    built, versioned or logged."""
    folder = project.path("releases")
    if not folder.exists():
        return None
    found = [p for p in folder.glob("*/capability-pack.json") if p.parent.name.isdigit()]
    if not found:
        return None
    pack = read_json(max(found, key=lambda p: int(p.parent.name)))
    return pack if isinstance(pack, dict) else None


def pack_problems(project: Any, pack: dict) -> list:
    """Why a written pack cannot be trusted as recorded: its content no longer hashes to its
    `content_sha256`, or its version and hash are not in the project's `packs.json`. Empty when intact."""
    problems = []
    if content_sha256(pack) != pack.get("content_sha256"):
        problems.append("its content does not hash to its content_sha256")
    history = project.read("packs.json", []) or []
    if not any(h.get("version") == pack.get("version") and h.get("content_sha256") == pack.get("content_sha256")
               for h in history):
        problems.append(f"version {pack.get('version')} with this hash is not in packs.json")
    return problems


def render_yaml(pack: dict) -> str:
    """A readable YAML view of the pack, for people and auditors (the JSON is the record)."""
    def emit(value, indent=0):
        pad = "  " * indent
        if isinstance(value, dict):
            lines = []
            for k, v in value.items():
                if isinstance(v, (dict, list)) and v:
                    lines.append(f"{pad}{k}:")
                    lines.append(emit(v, indent + 1))
                else:
                    lines.append(f"{pad}{k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, (dict, list)) else json.dumps(v)}")
            return "\n".join(lines)
        if isinstance(value, list):
            out = []
            for item in value:
                if isinstance(item, dict):
                    first, *rest = emit(item, indent + 1).split("\n")
                    out.append(f"{pad}- {first.strip()}")
                    out += rest
                else:
                    out.append(f"{pad}- {json.dumps(item, ensure_ascii=False)}")
            return "\n".join(out)
        return f"{pad}{json.dumps(value, ensure_ascii=False)}"
    return f"# {PACK_FORMAT}: the JSON beside this file is the record\n" + emit(pack) + "\n"
