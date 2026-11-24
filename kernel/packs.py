"""Capability packs: one manifest per release that says exactly what was delivered.

After the agentic capability layer: "pack version equals behaviour version". A pack names every
part of what was delivered by its hash: the contract, the product revision, the image, the harness
surfaces that built it, the models that built and judged it. It also carries its acceptance: the
criteria with their evidence, and the holdouts' results as scores only, never the scenarios (the
eval set stays where it is; only scores leave).

- If any hash changes, the version changes. The same content keeps its version, even when other
  content was versioned in between.
- A pack is pinned to its release: the models that ran up to the release's start, the autonomy
  cap it started under, the criteria the release kept when it ended (`kernel/deliver.py`), so a
  criterion a later contract adds is never listed, and holdout evidence from it and earlier
  releases only. Later runs, caps, contract changes and holdouts leave an ended release's pack as
  it was. What can still move it: a test criterion's state is today's evidence (gates and the
  tests on main), because `kernel/status.py` reads no state as of a release; and the site's
  policy, because what it declares (below) is behaviour. A release that kept no criteria (it has
  not ended, or ended before releases kept them) lists today's. The acceptance's `as_of` says
  where its criteria and their states were read from.
- A release that failed, was superseded or is still running delivered nothing: its pack is never
  valid, and its acceptance says the release's state.
- A pack is valid only while its acceptance holds: every criterion verified or held out and
  passing. Otherwise it says which criteria are not, and why.
- What is not there is said: no SBOM generated, not signed (no signer configured), no runtime
  declared (only a small capability declares one, kernel/faces.py), "not measured: no security
  scan". Nothing is claimed that was not done.
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

What travels (docs/portability.md, phase 1): an image is pinned by the digest the registry gave it
once IT pushed it and it was pinned (`kernel.deliver.pin_image`), never by its tag (`pin_of`); an
image not pushed and pinned is pinned by its local image id, and `pinned.not_by_digest` says why a
site cannot pull it. The pack also pins the product's file trees
(`app_files_sha256`, `runtime_files_sha256`, from `kernel.bundle.product_trees`) and carries the
public smoke set, so `pack_guard` in the image can check both at start. The pack travels beside the
image, never inside it: it pins the image's digest.
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
# The public smoke set pack_guard runs in-process before the product reports ready: read-only checks
# the paved-road template answers. Holdouts never travel; a smoke kind of the product's own is planned.
SMOKE = {"source": "the paved-road template", "checks": [
    {"method": "GET", "path": "/static/product.css", "expect_status": 200},
    {"method": "GET", "path": "/rihmasto-smoke-no-such-path", "expect_status": 404}]}


def pin_of(artifact: Any) -> tuple[Any, str]:
    """How a release's artifact is pinned, and by what: an image by its registry digest, else its
    local image id; a process by its source revision. A movable tag is kept only when nothing else is
    known, and then it says `tag`."""
    if not isinstance(artifact, dict):
        return artifact, "as recorded"
    ref, digest = artifact.get("ref"), artifact.get("digest")
    if artifact.get("type") != "image":
        return artifact.get("image") or ref or artifact.get("id"), "source revision"
    if digest:
        return (ref if str(ref).endswith(f"@{digest}") else f"{str(ref).rsplit(':', 1)[0]}@{digest}"), "digest"
    if artifact.get("id"):
        return artifact["id"], "local image id"
    return ref, "tag"


NOT_BY_DIGEST = {"local image id": "pinned by the local image id: it was not pushed and pinned (IT pushes it with its "
                                   "own tools, then `rihmasto pack pin`), so a site cannot pull it by digest",
                 "tag": "pinned by a movable tag: the road reported no digest"}


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


DELIVERED = "done"


def _latest_release(project: Any, release_no: int | None) -> dict | None:
    """The release a pack is for: the one named, or else the latest, whatever its state. Only a
    delivered one can have a valid pack (`acceptance`)."""
    from kernel.deliver import releases

    rels = releases(project)
    if release_no is not None:
        rels = [r for r in rels if r["release"] == release_no]
    return rels[-1] if rels else None


def _payloads(records: list, kind: str) -> list:
    """The payloads of one kind's records, skipping any record not shaped as the kernel writes it."""
    return [r["event"]["payload"] for r in records
            if isinstance(r, dict) and isinstance(r.get("event"), dict) and r["event"].get("kind") == kind
            and isinstance(r["event"].get("payload"), dict)]


def _until_release(records: list, release: Any) -> list:
    """The ledger up to the start of ``release``: what built and judged it. Runs after it started
    belong to later work. A release whose start is not recorded keeps the whole ledger."""
    for i, rec in enumerate(records):
        started = _payloads([rec], "release_started")
        if started and started[0].get("release") == release:
            return records[:i]
    return records


def _models(project: Any, release: Any = None) -> dict:
    """The models that built and judged this product up to the release, from the ledger's Gnomon
    runs: by role, with the harness surface hashes they ran under."""
    records = project.ledger().records()
    if release is not None:
        records = _until_release(records, release)
    by_role: dict[str, set] = {}
    surfaces = set()
    for pl in _payloads(records, "gnomon_run"):
        if pl.get("role") and pl.get("model"):
            by_role.setdefault(str(pl["role"]), set()).add(f"{pl['model']}@{pl.get('endpoint') or '?'}")
        if pl.get("surface_hash"):
            surfaces.add(str(pl["surface_hash"]))
    for pl in _payloads(records, "cell_ran"):
        if pl.get("final_model"):
            by_role.setdefault("builder", set()).add(str(pl["final_model"]))
    return {"by_role": {k: sorted(v) for k, v in sorted(by_role.items())}, "surfaces": sorted(surfaces)}


def _held_out_ids(project: Any) -> set:
    """The contract's held-out criteria (holdout or probe checks): what a passed holdout step that
    names no criteria ran, as `kernel.status.evidence` reads it."""
    contract = project.read("contract.json") or {}
    return {c.get("id") for r in contract.get("requirements") or [] if isinstance(r, dict)
            for c in r.get("acceptance") or []
            if isinstance(c, dict) and (c.get("check") or {}).get("kind") in ("holdout", "probe")}


def _holdout_steps(rel: dict) -> list:
    return [s for s in rel.get("steps") or []
            if isinstance(s, dict) and str(s.get("step", "")).startswith("holdouts:")]


def _step_held(step: dict, held_out_ids: set) -> dict:
    """What one holdout step showed of each criterion it ran: failing or held out. A passed step
    that names no criteria ran every held-out criterion, as `kernel.status.evidence` reads it."""
    native = step.get("native") or {}
    failing = {f.get("criterion") for f in native.get("failing") or [] if isinstance(f, dict)}
    ran = set(native.get("ran") or [])
    if step.get("outcome") == "passed" and not ran:
        ran = held_out_ids
    return {cid: "failing" if cid in failing else "held_out" for cid in ran | failing}


def _held_as_of(project: Any, release: int) -> dict:
    """Each held-out criterion's state from the holdout runs of releases up to ``release`` only: a
    later release's run is not evidence about this one."""
    from kernel.deliver import releases

    ids = _held_out_ids(project)
    held: dict = {}
    for rel in releases(project):
        if isinstance(rel.get("release"), int) and rel["release"] <= release:
            for step in _holdout_steps(rel):
                held.update({cid: (state, rel["release"]) for cid, state in _step_held(step, ids).items()})
    return held


def _pinned_rows(project: Any, rows: list, release: int | None) -> list:
    """The criteria rows with any holdout evidence from a release after ``release`` replaced by what
    the releases up to it showed (not measured when none of them ran it)."""
    if release is None:
        return rows
    held, out = None, []
    for row in rows:
        later = [e for e in row.get("evidence") or [] if isinstance(e, dict) and e.get("kind") == "holdout"
                 and isinstance(e.get("release"), int) and e["release"] > release]
        if later:
            held = _held_as_of(project, release) if held is None else held
            state, rel_no = held.get(row["criterion"], ("not_measured", None))
            row = dict(row, state=state, evidence=[{"kind": "holdout", "release": rel_no}] if rel_no else [])
        out.append(row)
    return out


def _kept_criteria(rel: dict) -> dict | None:
    """The criteria the release kept when it ended (`kernel.deliver.criteria_now`), or None when it
    kept none that can be read."""
    from kernel.deliver import CRITERIA_AT_END

    kept = rel.get(CRITERIA_AT_END)
    rows = kept.get("criteria") if isinstance(kept, dict) else None
    if not isinstance(rows, list):
        return None
    if not all(isinstance(c, dict) and isinstance(c.get("criterion"), str) and c.get("state") for c in rows):
        return None
    return kept


def _today(project: Any) -> list:
    from kernel.status import evidence

    return evidence(project) if project.path("contract.json").exists() else []


def _criteria(project: Any, rel: dict | None) -> tuple[list, dict]:
    """The criteria rows a pack's acceptance rests on, and as of when (`as_of`).

    The criteria are the release's own: those it kept when it ended (kernel/deliver.py), so a
    criterion a later contract added is never listed. Each one's state is today's evidence, with
    holdout evidence from later releases replaced by what the releases up to it showed; one that
    today's contract no longer has keeps the state it ended with. A release that kept none (it has
    not ended, or ended before releases kept them) lists today's criteria."""
    if rel is None:
        return _today(project), {"criteria": "today", "states": "today"}
    release = rel.get("release")
    today = _pinned_rows(project, _today(project), release)
    states = f"today, with holdout evidence from releases up to {release} only"
    kept = _kept_criteria(rel)
    if kept is None:
        why = "has not ended" if rel.get("state") in ("running", "waiting") else "kept no criteria when it ended"
        return today, {"criteria": f"today: release {release} {why}", "states": states}
    now = {row["criterion"]: row for row in today}
    rows = [now.get(c["criterion"], c) for c in kept["criteria"]]
    return rows, {"criteria": f"the end of release {release} ({kept.get('at')})", "states": states}


def acceptance(project, rel: dict | None) -> dict:
    """The criteria with their evidence as of the release, its holdout scores, and whether it is
    valid: only a delivered release whose every criterion is verified or held out is. A release that
    failed, was superseded or is still running says so in `release_state` and `not_delivered`.
    `as_of` says where the criteria and their states were read from."""
    crits, as_of = _criteria(project, rel)
    not_ok = [{"criterion": c["criterion"], "state": c["state"]} for c in crits
              if c["state"] not in ("verified", "held_out")]
    out: dict[str, Any] = {
        "criteria": [{"id": c["criterion"], "kind": c.get("kind"), "state": c["state"]} for c in crits],
        "as_of": as_of, "holdout_scores": _scores(rel), "valid": bool(crits) and not not_ok,
        "not_valid_because": not_ok}
    if rel is not None:
        state = rel.get("state")
        out["release_state"] = state
        if state != DELIVERED:
            out["valid"] = False
            out["not_delivered"] = (f"release {rel.get('release')} delivered nothing: its state is "
                                    f"{state or 'not recorded'}")
    return out


def _scores(rel: dict | None) -> dict | None:
    """The release's holdout results as scores only, never the scenarios."""
    holdouts = (rel or {}).get("holdouts") or {}
    results = holdouts.get("results") if isinstance(holdouts, dict) else None
    if not isinstance(results, list):
        return None
    return {"passed": sum(1 for r in results if r.get("verdict") == "passed"),
            "failed": sum(1 for r in results if r.get("verdict") not in ("passed", None)), "total": len(results),
            "by_criterion": {r.get("criterion"): r.get("verdict") for r in results}}


def build_pack(project, release_no: int | None = None) -> dict:
    """The pack for a release (the latest by default). Writes it beside the release and returns it.
    Only a delivered release's pack can be valid. What it pins is the release's own: the models
    that ran up to its start, the autonomy cap it started under, the criteria it kept when it
    ended, and holdout evidence from it and earlier releases only (see `acceptance`)."""
    from kernel.autonomy import cap_of
    from kernel.bundle import product_trees
    from kernel.faces import pack_runtime
    from kernel.profiles import profile_of
    from kernel.security import summary as security_summary

    rel = _latest_release(project, release_no)
    if rel is None:
        raise LookupError("the project has no release yet")
    contract = project.read("contract.json") or {}
    profile = profile_of(project)
    head = project.ledger().head()
    models = _models(project, rel["release"])
    # The cap the release started under; a release recorded before it was kept takes today's cap.
    cap = rel.get("autonomy_cap") if isinstance(rel.get("autonomy_cap"), int) else cap_of(project)
    pins = {k: pin_of(v) for k, v in sorted((rel.get("artifacts") or {}).items())}
    unpinned = {k: NOT_BY_DIGEST[how] for k, (_, how) in pins.items() if how in NOT_BY_DIGEST}
    body = {
        "format": PACK_FORMAT, "pack": project.pid, "title": project.meta.get("title"),
        "profile": profile["id"], "deliverable": profile.get("deliverable", "product"),
        "release": rel["release"], "maturity": rel["maturity"], "autonomy_cap": cap,
        "pinned": {
            "contract_revision": rel.get("contract_revision") or contract.get("revision"),
            "product_revision": rel.get("revision"),
            "artifacts": {k: ref for k, (ref, _) in pins.items()},
            **({"not_by_digest": unpinned} if unpinned else {}),
            "built_and_judged_by": models,
            **product_trees(project, rel.get("revision")),
        },
        "smoke": SMOKE,
        "runtime": pack_runtime(project, rel.get("revision")),   # app/runtime.json, judged (kernel/runtime_decl.py)
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
    """The same content keeps its version, whenever it was first versioned; new content is the next
    minor version, recorded."""
    history = project.read("packs.json", []) or []
    same = next((h for h in history if isinstance(h, dict) and h.get("content_sha256") == content), None)
    if same is not None:
        return str(same["version"])
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
