"""Stage 6 to 7: delivery on the paved road the maturity decides (FR-A8, FR-Q4, FR-Q5, FR-H3, FR-H4).

The maturity decides the plan:

| Maturity | Plan |
|---|---|
| explore | build_image, deploy:preview, smoke:preview |
| demo | build_image, deploy:demo, smoke:demo, holdouts:demo, owner_acceptance |
| pilot | build_image, deploy:staging, smoke:staging, holdouts:staging, user_validation |
| production | the pilot plan, deploy_gate, deploy_candidate:production, shadow:production, canary:production, promote:production |

`deliver(project)` takes main's revision as a release and advances its plan as far as it can.
It stops at a card that waits for a person and returns `waiting`; the next call, after the
person decided, goes on from there. The release record (`releases/<n>.json`) keeps every step's
outcome with its native values, the holdout results, the cards waited on and their decisions,
the artifact and the contract revision. When the release ends (done or failed) it also keeps its
criteria with their evidence states as they stood then (`criteria_at_end`): its capability pack
lists those criteria, so a criterion a later contract adds is never shown as part of it.
Transitions go to the ledger.

Before anything is built, every environment of the plan needs a ready paved road. A road that is
missing or not configured opens a `road` card for IT, and nothing is deployed.

After the deploy gate, a production release runs as a candidate beside the current release:
shadow replays recorded traffic, the canary compares error rates, and the candidate is promoted
or rolled back. A rollback needs no person; it opens an incident card.

When the product's main moves while a release waits, the waiting release is superseded (its
open cards are withdrawn) and the new revision becomes a new release: an approval is for one
revision. A finished release is not repeated for the same revision unless ``new=True``.

The stage follows what was delivered (FR-Q7): a release that lands in preview, demo or staging
puts the project at stage 6, user validation; a release promoted to production puts it at
stage 7 and marks it released. Each change of stage is recorded in the ledger.

Before a release enters staging or production, the security gate (`kernel/security.py`) is asked
(FR-H8-AC-2). An open finding at a blocking level holds the release: it waits, naming the
findings, until a clean scan arrives or a person with the it or compliance persona accepts the
risk. In demo and preview the gate's verdict is only recorded. "Not measured: no security scan"
never holds a release; it is recorded too.

An image built on a docker road that names a `registry` is tagged for it on the deploying host and
never pushed by Rihmasto: every external write goes through Gnomon's integration lane (D-0015),
which is planned, so IT pushes the tag with its own tools. A person with the it persona then pins
the release by the digest the registry gave it (`pin_image`, `rihmasto pack pin`), read from the
deploying host's docker: the release, the site's deploy package and the capability pack name that
digest, and the road runs the image by it from then on (FR-PT1). Every gate card (the demo's
acceptance, staging's validation, production's deploy gate) carries the governance map of the road
its environment runs on (kernel/evidence_pack.py).

Holdout scenarios write their own data. They run against a twin of the environment, deployed
from the same revision and stopped afterwards, so the slot end users try never holds holdout
data (FR-H9). A road that cannot host a twin runs them in the shared slot and says so.
"""

from __future__ import annotations

import re
import traceback

from kernel import holdouts, integration_bind, operate
from kernel.canon import Canon
from kernel.custody import custody_safe
from kernel.enforcement_guard import at_deploy
from kernel.filelock import locked
from kernel.lanes import _git
from kernel.roads import PavedRoads, Road, RoadError, slot_state, validate_package
from kernel.store import MATURITIES, Project, read_json, write_json

LANDING = {"explore": "preview", "demo": "demo", "pilot": "staging", "production": "production"}

# Card steps: the card kind, the verdict that lets the plan go on, and who must give it.
CARD_STEPS = {
    "owner_acceptance": ("approval", "approve", "business_owner"),
    "user_validation": ("validation", "accept", None),
    "deploy_gate": ("deploy_gate", "approve", "it"),
}
CARD_ENV = {"owner_acceptance": "demo", "user_validation": "staging", "deploy_gate": "staging"}
CANDIDATE_STEPS = ("deploy_candidate:production", "shadow:production", "canary:production", "promote:production")
# Outcomes after which the plan goes on. A shadow that differs is reported, not blocking: the
# canary decides on error rates.
CONTINUES = ("passed", "differs", "not applicable", "not measured")
# A failed holdout's reason quotes what its scenario expected. The release record and the ruling card
# keep it for the person who rules; anywhere else (the ledger, the one-line status) it is held out by
# kernel.custody.custody_safe, imported above (kernel/status.py and kernel/recipes.py import it from here).
# Where a release lands for people to try or validate (stage 6), and where an open security
# finding holds it.
TRYING_ENVS = ("preview", "demo", "staging")
GATED_ENVS = ("staging", "production")
NO_TWIN = "holdouts ran in the shared slot: this road has no twin"


def delivery_plan(maturity: str) -> list:
    if maturity not in MATURITIES:
        raise ValueError(f"maturity must be one of {MATURITIES}, got {maturity!r}")
    if maturity == "explore":
        return ["build_image", "deploy:preview", "smoke:preview"]
    if maturity == "demo":
        return ["build_image", "deploy:demo", "smoke:demo", "holdouts:demo", "owner_acceptance"]
    pilot = ["build_image", "deploy:staging", "smoke:staging", "holdouts:staging", "user_validation"]
    if maturity == "pilot":
        return pilot
    return pilot + ["deploy_gate", *CANDIDATE_STEPS]


def plan_environments(plan) -> list:
    envs = []
    for step in plan:
        name, _, env = step.partition(":")
        if name in ("deploy", "deploy_candidate") and env not in envs:
            envs.append(env)
    return envs


def release_path(project, n: int):
    return project.path("releases", f"{n}.json")


def releases(project) -> list:
    folder = project.path("releases")
    if not folder.exists():
        return []
    found = [read_json(p) for p in folder.glob("*.json") if p.stem.isdigit()]
    return sorted((r for r in found if r), key=lambda r: r["release"])


def latest_release(project) -> dict | None:
    found = releases(project)
    return found[-1] if found else None


def cap_now(project: Project) -> int:
    """The autonomy cap in force for the project (`kernel.autonomy.cap_of`), read without creating
    the factory's own canon when no policy was ever set."""
    from kernel.autonomy import DEFAULT_CAP
    from kernel.learn import factory_project

    store = factory_project(project.factory, create=False)
    policy = (store.read("policy.json", {}) or {}) if store is not None else {}
    cap = int(policy.get("autonomy_cap", DEFAULT_CAP))
    own = project.meta.get("autonomy_cap")
    return min(cap, int(own)) if own is not None else cap


CRITERIA_AT_END = "criteria_at_end"
# What reading the criteria raises on records not shaped as the kernel writes them.
_UNREADABLE = (KeyError, TypeError, AttributeError, ValueError, IndexError, RecursionError)


def criteria_now(project: Project) -> dict | None:
    """Each criterion's evidence state as it stands now (`kernel.status.evidence`), with the contract
    revision it was read under. A release keeps it when it ends, so its capability pack lists the
    criteria it delivered, not a later contract's. None when there is no contract or its records
    cannot be read."""
    from kernel.status import evidence

    if not project.path("contract.json").exists():
        return None
    try:
        rows = evidence(project)
    except _UNREADABLE:
        return None
    contract = project.read("contract.json") or {}
    return {"at": project.factory.clock.stamp(), "contract_revision": contract.get("revision"),
            "criteria": [{k: row.get(k) for k in ("criterion", "requirement", "kind", "state")} for row in rows]}


def summary(rel: dict) -> dict:
    out = {"state": rel["state"] if rel["state"] in ("done", "waiting", "failed") else "failed",
           "waiting_on": rel.get("waiting_on"), "release": rel["release"], "env": LANDING[rel["maturity"]],
           "revision": rel["revision"], "steps": rel["steps"]}
    for key in ("failed_step", "reason", "handoff", "incident", "blocked"):
        if rel.get(key) is not None:
            out[key] = rel[key]
    return out


def in_production(project: Project) -> bool:
    """Whether the project runs in production: its production slot holds a current release, or it
    is an adopted solution the factory monitors where it already runs."""
    if slot_state(project, "production", "current"):
        return True
    meta = project.meta
    return meta.get("source_kind") == "adopted" and meta.get("intent") == "monitor"


def release_reach(rel: dict) -> str | None:
    """How far one release got with the people who try it: `pilot` while it is validated or being
    validated on staging, `trying` while a demo is accepted or waits for its acceptance (or a
    preview is done), else None. A superseded release reached nothing."""
    if rel.get("state") == "superseded":
        return None
    outcomes = {s["step"]: s["outcome"] for s in rel.get("steps", []) if isinstance(s, dict)}
    if outcomes.get("user_validation") in ("waiting", "passed"):
        return "pilot"
    if outcomes.get("owner_acceptance") in ("waiting", "passed"):
        return "trying"
    if rel.get("maturity") == "explore" and rel.get("state") == "done":
        return "trying"
    return None


def deliver(project, *, roads=None, docker=None, az=None, new: bool = False) -> dict:
    """Advance the delivery of main's revision as far as it can go.

    Returns ``{"state": "done" | "waiting" | "failed", "waiting_on": card id or None, "release": n,
    "env": the landing environment, "revision": ..., "steps": [...]}``. When a validation is
    decided `fix` or `change`, the state is `failed`, ``waiting_on`` is that validation card and
    ``handoff`` names the change loop, which takes the card from there. A rollback adds
    ``incident``. ``roads`` is a PavedRoads, a config dict or a path (default: the factory's
    `paved_roads.json`); ``docker`` and ``az`` replace the CLIs (tests)."""
    if not project.path("repo.git").exists():
        raise FileNotFoundError("no product repository: compile the project before delivering it")
    with locked(project.path("releases", ".deliver.lock")):
        return _Delivery(project, roads, docker, az).run(new=new)


def pin_image(project, *, person: str, persona: str, release: int | None = None, docker=None) -> dict:
    """IT pushed the release's image, tagged for its registry at build, with its own tools; pin the
    release by the digest the registry gave it. The digest is read from the deploying host's docker
    (`RepoDigests`, which a push sets): a local read, so Rihmasto writes nothing to the registry
    (D-0015). Recorded as `image_pinned` with the person. A tag not pushed yet is said, not pinned."""
    from kernel.canon import DecisionRefused
    from kernel.people import is_person
    from kernel.roads import DockerCLI

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona != "it":
        raise DecisionRefused(f"a {persona} may not pin an image: it may, for the registry it named")
    with locked(project.path("releases", ".deliver.lock")):
        rel = read_json(release_path(project, release)) if release else latest_release(project)
        if not isinstance(rel, dict):
            raise LookupError("no release to pin")
        pinned, waiting = {}, {}
        for road, art in sorted((rel.get("artifacts") or {}).items()):
            push = art.get("push") if isinstance(art, dict) else None
            if not isinstance(push, dict) or art.get("digest"):
                continue
            seen = (docker or DockerCLI())("image", "inspect", "--format", "{{json .RepoDigests}}", push["tag"],
                                           check=False)
            found = re.search(re.escape(push["repository"]) + r"@(sha256:[0-9a-f]{64})", seen)
            if found is None:
                waiting[road] = f"{push['tag']} has no digest from {push['registry']} yet: push it first"
                continue
            digest = found.group(1)
            rel["artifacts"][road] = pinned[road] = dict(art, ref=f"{push['repository']}@{digest}", digest=digest,
                                                         tag=push["tag"], registry=push["registry"])
            project.log("image_pinned", {"release": rel["release"], "road": road, "tag": push["tag"],
                                         "digest": digest, "by": person, "persona": persona})
        if pinned:
            write_json(release_path(project, rel["release"]), rel)
    return {"release": rel["release"], "pinned": {r: a["ref"] for r, a in pinned.items()}, "not_pinned": waiting}


def pack_command(factory, args, show) -> None:
    """`rihmasto pack pin <pid> --person P --persona it [--release N]`: once IT pushed the tag, pin it."""
    from kernel.canon import DecisionRefused

    if len(args.words) != 1:
        raise ValueError("say it as: rihmasto pack pin <pid> --person <name> --persona it")
    if not (args.person and args.persona):
        raise DecisionRefused("a pin is signed: give --person and --persona")
    show(pin_image(factory.project(args.words[0]), person=args.person, persona=args.persona, release=args.release))


class _Delivery:
    def __init__(self, project, roads, docker, az):
        self.project = project
        self.paved = PavedRoads.load(roads if roads is not None else project.factory)
        self.docker, self.az = docker, az
        self.canon = Canon(project)
        self.rel: dict = {}
        self._roads: dict = {}
        self._previous = None
        self._shadow = None

    # -- the record -----------------------------------------------------------------------------

    def now(self) -> str:
        return self.project.factory.clock.stamp()

    def save(self) -> None:
        self.rel["updated"] = self.now()
        write_json(release_path(self.project, self.rel["release"]), self.rel)

    def keep_criteria(self) -> None:
        """At the release's end (done or failed), keep its criteria as they stand: its capability pack
        lists them (kernel/packs.py), whatever a later contract adds. The record is saved first, so
        the step that ended the release (a failing holdout) is part of what is read."""
        self.save()
        kept = criteria_now(self.project)
        if kept is not None:
            self.rel[CRITERIA_AT_END] = kept

    def log(self, kind: str, **payload) -> None:
        self.project.log(kind, {"release": self.rel["release"], **payload})

    def outcome(self, step: str) -> str | None:
        for s in self.rel["steps"]:
            if s["step"] == step:
                return s["outcome"]
        return None

    def record(self, step: str, outcome: dict) -> None:
        entry = {"step": step, "outcome": outcome["outcome"], "native": outcome.get("native", {}), "at": self.now()}
        if outcome.get("card"):
            entry["card"] = outcome["card"]
        steps = [s for s in self.rel["steps"] if s["step"] != step]
        self.rel["steps"] = steps + [entry]
        self.log("release_step", step=step, outcome=entry["outcome"])
        name, _, env = step.partition(":")
        if name == "smoke" and env != "production" and entry["outcome"] == "passed":   # deployed and answering
            self.log("release_reached_test", environment=env, revision=self.rel["revision"])

    def card_entry(self, step: str) -> dict | None:
        found = [c for c in self.rel["cards"] if c["step"] == step]
        return found[-1] if found else None

    # -- the run ----------------------------------------------------------------------------------

    def run(self, *, new: bool) -> dict:
        revision = _git(self.project.path("repo.git"), "rev-parse", "main")
        maturity = self.project.meta["maturity"]
        rel = latest_release(self.project)
        if rel and rel["state"] in ("waiting", "running") and (rel["revision"], rel["maturity"]) != (revision, maturity):
            self.rel = rel
            self.supersede(revision, maturity)
            rel = None
        if rel and rel["state"] in ("done", "failed") and rel["revision"] == revision and not new:
            return summary(rel)
        self.rel = rel if rel and rel["state"] in ("waiting", "running") else self.start(revision)
        rel = self.rel
        rel["state"], rel["waiting_on"] = "running", None
        rel.pop("blocked", None)
        roads = self.check_roads()
        if roads == "ready":  # each declared integration bound on its road and approved by IT (FR-DS2)
            roads = integration_bind.check(self)
        if roads != "ready":
            return summary(rel)
        for step in rel["plan"]:
            if self.outcome(step) in CONTINUES:
                continue
            outcome = self.run_step(step)
            self.record(step, outcome)
            if outcome["outcome"] == "waiting":
                return self.wait(step, outcome)
            if outcome["outcome"] not in CONTINUES:
                return self.fail(step, outcome)
            self.save()
        rel["state"], rel["done"] = "done", self.now()
        self.keep_criteria()
        self.save()
        self.log("release_done", revision=rel["revision"], environment=LANDING[rel["maturity"]])
        return summary(rel)

    def start(self, revision: str) -> dict:
        existing = releases(self.project)
        n = existing[-1]["release"] + 1 if existing else 1
        meta, contract = self.project.meta, self.project.read("contract.json") or {}
        plan = delivery_plan(meta["maturity"])
        tasks = self.project.read("tasks.json", {}) or {}
        self.rel = {
            "release": n, "project": self.project.pid, "maturity": meta["maturity"], "plan": plan,
            "environments": plan_environments(plan), "revision": revision, "rev12": revision[:12],
            "contract_revision": contract.get("revision") or meta.get("contract_revision"),
            "requirements": [r["id"] for r in contract.get("requirements", [])],
            "built": bool(meta.get("built")), "tasks": {t: s.get("status") for t, s in sorted(tasks.items())},
            "roads": {}, "artifacts": {}, "packages": {}, "steps": [], "holdouts": None, "cards": [],
            "state": "running", "waiting_on": None, "created": self.now(), "updated": self.now(),
            # the cap the release runs under: its capability pack pins it (kernel/packs.py)
            "autonomy_cap": cap_now(self.project),
        }
        self.save()
        self.log("release_started", revision=revision, maturity=meta["maturity"], plan=plan,
                 contract=self.rel["contract_revision"])
        return self.rel

    def wait(self, step: str, outcome: dict) -> dict:
        """The release waits: on a card a person decides, or, with no card that fits, on what
        ``blocked`` names (an open security finding), with ``waiting_on`` saying why."""
        rel = self.rel
        rel["state"], rel["waiting_on"] = "waiting", outcome.get("card") or outcome["waiting_on"]
        if outcome.get("blocked"):
            rel["blocked"] = outcome["blocked"]
        self.save()
        if outcome.get("card"):
            self.log("release_waiting", step=step, card=outcome["card"])
        else:
            self.log("release_waiting", step=step, card=None, blocked=outcome.get("blocked"),
                     why=outcome["waiting_on"])
        return summary(rel)

    def stage_to(self, stage: int, why: str, **meta: object) -> None:
        """Move the project to the stage this release reached, and record the move in the ledger."""
        before = self.project.meta.get("stage")
        if before != stage or any(self.project.meta.get(k) != v for k, v in meta.items()):
            self.project.update_meta(stage=stage, **meta)
        if before != stage:
            self.project.log("stage_changed", {"release": self.rel["release"], "from": before, "to": stage,
                                               "why": why})

    def supersede(self, revision: str, maturity: str) -> None:
        """Main moved, or the maturity was raised, while this release waited: its approvals were
        for another revision or plan, so it stops and its open cards are withdrawn."""
        why = f"release {self.rel['release']} was superseded by revision {revision[:12]} at maturity {maturity}"
        for entry in self.rel["cards"]:
            if entry.get("decision") is None and self.canon.get_card(entry["card"])["state"] == "open":
                self.canon.close(entry["card"], why, state="withdrawn")
        self.rel.update(state="superseded", superseded_by={"revision": revision, "maturity": maturity},
                        waiting_on=None)
        self.save()
        self.log("release_superseded", by_revision=revision, maturity=maturity)

    def fail(self, step: str, outcome: dict) -> dict:
        rel, native = self.rel, outcome.get("native", {})
        rel.update(state="failed", failed_step=step, waiting_on=None,
                   reason=native.get("why") or native.get("error") or f"{step}: {outcome['outcome']}")
        if step == "user_validation" and native.get("verdict") in ("fix", "change"):
            rel["handoff"] = {"to": "change", "card": native["card"], "verdict": native["verdict"]}
            rel["waiting_on"] = native["card"]
        if step in CANDIDATE_STEPS:
            evidence = {"step": step, "outcome": outcome["outcome"],
                        "why": rel["reason"], "canary": rel.get("canary"), "shadow": rel.get("shadow")}
            try:
                rb = operate.rollback(self.project, "production", release=rel["release"], reason=rel["reason"],
                                      roads=self.paved, docker=self.docker, az=self.az, restore=self._previous,
                                      evidence=evidence)
                rel["rollback"], rel["incident"] = rb, rb["incident"]
            except Exception as exc:  # the rollback itself failed: a person must look now
                inc = operate.open_incident(self.project, release=rel["release"], env="production",
                                            title=f"Rollback of release {rel['release']} failed",
                                            body=f"{rel['reason']}\n\nThe rollback failed: {exc}",
                                            payload={"error": str(exc)})
                rel["rollback"], rel["incident"] = {"error": f"{type(exc).__name__}: {exc}"}, inc["card"]
        self.keep_criteria()
        self.save()
        self.log("release_failed", step=step, reason=custody_safe(rel["reason"]), incident=rel.get("incident"),
                 handoff=rel.get("handoff"))
        return summary(rel)

    # -- roads ------------------------------------------------------------------------------------

    def check_roads(self) -> str:
        """Every environment of the plan needs a ready road before anything is built."""
        rel, gaps = self.rel, {}
        for env in rel["environments"]:
            name = self.paved.name_for(self.project, env)
            cfg = self.paved.roads.get(name) or {} if name else {}
            missing = self.paved.missing(name, env, docker=self.docker, az=self.az)
            rel["roads"][env] = {"name": name, "kind": cfg.get("kind"), "ready": not missing, "missing": missing,
                                 "rules": cfg.get("rules") or {}}
            if missing:
                gaps[env] = missing
        entry = self.card_entry("road")
        if not gaps:
            if entry and entry.get("decision") is None and self.canon.get_card(entry["card"])["state"] == "open":
                self.canon.close(entry["card"], "the road is configured", state="resolved")
                entry["closed"] = "resolved"
            self.save()
            return "ready"
        if entry and entry.get("decision") is None:
            card = self.canon.get_card(entry["card"])
            if card["state"] == "open":
                rel["state"], rel["waiting_on"] = "waiting", card["id"]
                self.save()
                return "waiting"
            if card["state"] == "decided":
                entry["decision"] = card["decision"]
                if card["decision"]["verdict"] == "declined":
                    self.fail("road", {"outcome": "failed", "native": {
                        "card": card["id"], "missing": gaps,
                        "why": f"IT declined the road ({card['decision']['person']}): {card['decision']['reason']}"}})
                    return "failed"
        lines = [f"Release {rel['release']} of {self.project.meta['title']} (revision {rel['rev12']}) needs a paved "
                 "road for: " + ", ".join(gaps) + ".", "", "What is missing:"]
        lines += [f"- {env}: {m}" for env, ms in gaps.items() for m in ms]
        if self.paved.problems:
            lines += ["", "Problems in paved_roads.json:"] + [f"- {p}" for p in self.paved.problems]
        lines += ["", f"Configure it in {self.project.factory.paved_roads_path}, then decide this card "
                  "`configured` (or `declined`). Nothing is deployed until then."]
        card = self.canon.card("road", f"Configure the paved road for {', '.join(gaps)}", body="\n".join(lines),
                               refs={"release": rel["release"], "environments": list(gaps),
                                     "roads": sorted({str(rel["roads"][e]["name"]) for e in gaps})},
                               payload={"missing": gaps, "paved_roads": str(self.project.factory.paved_roads_path),
                                        "problems": self.paved.problems}, blocking=True)
        rel["cards"].append({"step": "road", "card": card["id"], "kind": "road", "decision": None, "opened": self.now()})
        rel["state"], rel["waiting_on"] = "waiting", card["id"]
        self.save()
        self.log("road_refused", card=card["id"], missing=gaps)
        return "waiting"

    def road(self, env: str):
        name = self.rel["roads"][env]["name"]
        if name not in self._roads:
            self._roads[name] = self.paved.road(name, docker=self.docker, az=self.az)
        return self._roads[name]

    def package(self, env: str, slot: str):
        rel, road = self.rel, self.road(env)
        pkg = road.package(self.project, env=env, slot=slot, release=rel["release"], revision=rel["revision"],
                           artifact=rel["artifacts"][road.name], contract_revision=rel["contract_revision"])
        integration_bind.wire(pkg, rel, env)  # its approved integrations: settings and secret references
        road.render(self.project, pkg)        # so a rendered YAML holds them too (FR-GCP1)
        name =f"releases/{rel['release']}/package-{env}-{slot}.json"
        write_json(self.project.dir / name, pkg)
        rel["packages"][f"{env}:{slot}"] = name
        return road, pkg

    # -- steps ------------------------------------------------------------------------------------

    def run_step(self, step: str) -> dict:
        name, _, env = step.partition(":")
        try:
            own = self.road_step(name, env)   # a road's own step: a scheduled job's (FR-GCP1)
            if own is not None:
                return own
            if name == "build_image":
                return self.build()
            if name in ("deploy", "deploy_candidate"):
                return self.deploy(env, "current" if name == "deploy" else "candidate")
            if name == "smoke":
                return self.smoke(env)
            if name == "holdouts":
                return self.holdouts(env)
            if name in CARD_STEPS:
                return self.card_step(step)
            if name == "shadow":
                return self.shadow(env)
            if name == "canary":
                return self.canary(env)
            if name == "promote":
                return self.promote(env)
            raise ValueError(f"unknown step {step!r}")
        except RoadError as exc:
            return {"outcome": "failed", "native": {"error": str(exc), **exc.native}}
        except Exception as exc:
            return {"outcome": "failed", "native": {"error": f"{type(exc).__name__}: {exc}",
                                                    "traceback": traceback.format_exc()[-2000:]}}

    def road_step(self, name: str, env: str) -> dict | None:
        """The outcome of a step the environment's road runs itself, or None (kernel/roads_gcp_ops.py)."""
        hook = getattr(self.road(env), "delivery_step", None) if env else None
        return hook(self, name, env) if hook is not None else None

    def build(self) -> dict:
        rel = self.rel
        for env in rel["environments"]:
            road = self.road(env)
            if road.name not in rel["artifacts"]:
                rel["artifacts"][road.name] = self.pin(road, road.build(self.project, rel["revision"]))
        return {"outcome": "passed", "native": {"artifacts": dict(rel["artifacts"])}}

    def pin(self, road: Road, artifact: dict) -> dict:
        """Tag an image for the registry IT names on its docker road, on the deploying host only.
        Rihmasto pushes nothing (D-0015): IT pushes the tag with its own tools, and `pin_image` then pins
        the release by the digest the registry gave it. Until then the pack pins the local image id and
        says a site cannot pull it by digest."""
        registry, docker = str(road.cfg.get("registry") or "").rstrip("/"), getattr(road, "docker", None)
        if artifact.get("type") != "image" or not registry or docker is None:
            return artifact
        tag = f"{registry}/{str(artifact['ref']).rsplit('/', 1)[-1]}"
        repository = tag.rsplit(":", 1)[0] if ":" in tag.rsplit("/", 1)[-1] else tag
        docker("tag", artifact["ref"], tag)
        self.log("image_tagged", road=road.name, tag=tag, pushed_by="it, with its own tools")
        return dict(artifact, push={"registry": registry, "tag": tag, "repository": repository,
                                    "by": "it, with its own tools: Rihmasto writes nothing to a registry (D-0015)",
                                    "then": f"rihmasto pack pin {self.project.pid} --person <name> --persona it"})

    def deploy(self, env: str, slot: str) -> dict:
        security, held = self.security(env)
        if held is not None:
            return held
        held = at_deploy(self.project, env, self.rel["release"], security)   # the owner's levels there (FR-ENF1)
        if held is not None:
            return held
        road, pkg = self.package(env, slot)
        native = {"road": road.name, "kind": road.kind, "slot": slot, "artifact": pkg["artifact"]["ref"],
                  "package": self.rel["packages"][f"{env}:{slot}"], "security": security}
        problems = validate_package(pkg)
        if problems:
            return {"outcome": "failed", "native": {**native, "problems": problems,
                                                    "why": "the deploy package is not valid: " + "; ".join(problems)}}
        state = road.deploy(self.project, pkg)
        native.update(base_url=state["base_url"], health=state.get("health"))
        if slot == "current" and env in TRYING_ENVS:
            self.stage_to(6, f"release {self.rel['release']} landed in {env} for people to try")
        return {"outcome": "passed", "native": native}

    def security(self, env: str) -> tuple[dict, dict | None]:
        """Ask the security gate before the release enters ``env``. Returns what the step records, and
        the waiting outcome when an open finding holds the release (staging and production only)."""
        from kernel.security import security_gate

        gate = security_gate(self.project)
        seen = {"verdict": gate["verdict"], "reason": gate["reason"], "blocking": [b["id"] for b in gate["blocking"]],
                "accepted": [a["id"] for a in gate["accepted"]], "scans": gate["scans"],
                "holds": env in GATED_ENVS and gate["blocked"]}
        if not seen["holds"]:
            if gate["blocked"]:
                seen["note"] = ("recorded, not held: an open finding holds a release only before "
                                + " or ".join(GATED_ENVS))
            return seen, None
        named = ", ".join(f"{b['id']} ({b['rule']}, {b['tool']}" + (f", {b['where']})" if b.get("where") else ")")
                          for b in gate["blocking"])
        required = (gate.get("posture") or {}).get("then")   # what a posture requires is no risk to accept
        found = [b for b in gate["blocking"] if not str(b["id"]).startswith("POSTURE-")]
        why = (f"the security gate holds release {self.rel['release']} before {env}: {gate['reason']}: {named}."
               + (" It goes on when a scan no longer reports them, or a person with the it or compliance persona "
                  "accepts the risk until a date." if found else "") + (f" {required}" if required else ""))
        blocked = {"by": "security", "environment": env, "findings": seen["blocking"], "scans": gate["scans"]}
        return seen, {"outcome": "waiting", "waiting_on": why, "blocked": blocked, "native": {"security": seen,
                                                                                                "why": why}}

    def smoke(self, env: str) -> dict:
        state = slot_state(self.project, env, "current")
        if not state:
            return {"outcome": "failed", "native": {"why": f"nothing runs in {env}"}}
        res = operate.smoke(state["base_url"], version=self.rel["rev12"])
        if not res["ok"]:
            res["why"] = f"smoke check failed in {env}: {res['reason']}"
        return {"outcome": "passed" if res["ok"] else "failed", "native": res}

    def twin(self, env: str) -> dict | None:
        """A twin of ``env`` for the holdouts: the same revision on its own empty data, or None when
        the road cannot host one."""
        road = self.road(env)
        if not road.hosts_twin():
            return None
        _, pkg = self.package(env, "twin")
        problems = validate_package(pkg)
        if problems:
            raise RoadError("the twin's deploy package is not valid: " + "; ".join(problems), {"problems": problems})
        return road.deploy(self.project, pkg)

    def holdouts(self, env: str) -> dict:
        state = slot_state(self.project, env, "current")
        if not state:
            return {"outcome": "failed", "native": {"why": f"nothing runs in {env}"}}
        twin = self.twin(env)
        try:  # a signed step is signed with the secrets this environment's road names (FR-DF2)
            report = operate.run_holdouts(self.project, twin["base_url"] if twin else state["base_url"],
                                          secrets=holdouts.environment_secrets(self.road(env)))
        finally:
            if twin is not None:
                self.road(env).stop(self.project, env, "twin")
        where = {"slot": "twin", "twin_stopped": True} if twin else {"slot": "current", "note": NO_TWIN}
        self.rel["holdouts"] = {"environment": env, **where, **report}
        native = {k: report[k] for k in ("verdict", "scenarios", "passed", "failed", "missing")} | where
        # The criteria whose scenarios ran, passed or failed: a scenario that passed in a run that
        # failed elsewhere is still evidence (kernel/status.py reads it).
        native["ran"] = [r["criterion"] for r in report["results"] if r["verdict"] in ("passed", "failed")]
        native["failing"] = [r for r in report["results"] if r["verdict"] != "passed"]
        if report["verdict"] in ("passed", "not applicable"):
            return {"outcome": "passed", "native": native}
        first = native["failing"][0] if native["failing"] else None
        native["why"] = (f"holdout {first['criterion']} failed at step {first.get('failed_step')}: {first.get('reason')}"
                         if first else f"holdouts not measured: missing {', '.join(report['missing'])}")
        return {"outcome": "failed", "native": native}

    def card_step(self, step: str) -> dict:
        kind, approving, persona = CARD_STEPS[step]
        entry = self.card_entry(step)
        if entry:
            card = self.canon.get_card(entry["card"])
            if card["state"] == "open":
                return {"outcome": "waiting", "card": card["id"]}
            if card["state"] == "decided":
                d = card["decision"]
                entry["decision"] = d
                native = {"card": card["id"], "kind": kind, "verdict": d["verdict"], "person": d["person"],
                          "persona": d["persona"], "decision_reason": d.get("reason")}
                stale = any(x["id"] == d["id"] and x.get("stale") for x in self.canon.decisions())
                if stale:
                    entry["note"] = "the decision went stale; asked again"
                elif persona and d["persona"] != persona:
                    entry["note"] = f"decided by {d['persona']}, but this card needs {persona}; asked again"
                elif d["verdict"] == approving:
                    return {"outcome": "passed", "native": native}
                else:
                    native["why"] = f"{kind} card {card['id']}: {d['verdict']} by {d['person']} ({d['persona']})"
                    return {"outcome": "failed", "native": native}
        card = self.open_card(step, kind, persona)
        return {"outcome": "waiting", "card": card["id"]}

    def open_card(self, step: str, kind: str, persona: str | None) -> dict:
        rel = self.rel
        n, env = rel["release"], CARD_ENV[step]
        state = slot_state(self.project, env, "current")
        url = (state["base_url"] or state.get("console")) if state else None   # a scheduled job: its console page
        ho = rel.get("holdouts") or {}
        holdouts = {k: ho.get(k) for k in ("environment", "slot", "verdict", "scenarios", "passed", "failed")}
        payload = {"release": n, "revision": rel["revision"], "environment": env, "url": url, "holdouts": holdouts,
                   "persona": persona}
        held = (f"{ho.get('passed', 0)} of {ho.get('scenarios', 0)} holdout scenarios passed against "
                + ("a twin of it, so its data holds none of theirs" if ho.get("slot") == "twin" else "it"))
        if step == "owner_acceptance":
            title = f"Accept the demo of release {n}"
            body = (f"Release {n} (revision {rel['rev12']}) runs in the demo environment at {url}; {held}. "
                    "Try it, then approve or reject it. The business owner decides.")
        elif step == "user_validation":
            title = f"Validate release {n} on staging"
            body = (f"Release {n} (revision {rel['rev12']}) runs on staging at {url}; {held}. Let the users try it, "
                    "then decide: accept (it may go on), fix (something is broken), change (it should work "
                    "differently) or keep (keep what runs now and stop this release).")
        else:
            env = "production"
            road, pkg = self.package(env, "candidate")
            problems = validate_package(pkg)
            title = f"Deploy release {n} to production?"
            body = (f"Release {n} (revision {rel['rev12']}) passed staging ({held}) and its user validation. "
                    f"Approving deploys {pkg['artifact']['ref']} on the paved road {road.name} ({road.kind}) as a "
                    "candidate beside the current release; shadow and canary then decide between promotion and "
                    "rollback. Refusing stops the release.")
            payload.update(road=road.name, kind=road.kind, artifact=pkg["artifact"]["ref"], rules=pkg["rules"],
                           package=rel["packages"]["production:candidate"], package_problems=problems)
        governance, line = self.governance(env)
        payload["governance"] = governance
        card = self.canon.card(kind, title, body=f"{body} {line}", payload=payload, blocking=True,
                               refs={"release": n, "requirements": rel["requirements"]})
        rel["cards"].append({"step": step, "card": card["id"], "kind": kind, "decision": None, "opened": self.now()})
        return card

    def governance(self, env: str) -> tuple[list, str]:
        """The governance map where ``env`` runs this release (by its road's kind), and the card's line."""
        from kernel.evidence_pack import governance_line, governance_map

        gmap = governance_map(self.road(env).kind, self.rel["artifacts"])
        return gmap, f"Governance there: {governance_line(gmap)}."

    def shadow(self, env: str) -> dict:
        n = self.rel["release"]
        report = operate.shadow(self.project, env, roads=self.paved, docker=self.docker, az=self.az, release=n)
        self._shadow = report
        self.rel["shadow"] = {k: report.get(k) for k in ("verdict", "against", "safe", "replayed", "sent_to_current",
                                                         "differing", "reason")}
        self.rel["shadow"]["report"] = f"ops/shadow/{n}.json"
        native = dict(self.rel["shadow"])
        native["differences"] = [{"index": e["index"], "method": e["method"], "path": e["path"],
                                  "differences": e["differences"],
                                  "current": (e.get("current") or {}).get("status"),
                                  "candidate": e["candidate"]["status"]} for e in report["differences"]]
        outcome = {"passed": "passed", "failed": "differs"}.get(report["verdict"], report["verdict"])
        return {"outcome": outcome, "native": native}

    def canary(self, env: str) -> dict:
        settings = {k: v for k, v in (self.road(env).cfg.get("canary") or {}).items()
                    if k in ("tolerance", "min_sample", "probe_rounds")}
        decision = operate.canary(self.project, env, shadow_report=self._shadow, release=self.rel["release"],
                                  **settings)
        self.rel["canary"] = decision
        native = {**decision, "why": f"canary aborted: {decision['reason']}"} if decision["decision"] == "abort" \
            else decision
        return {"outcome": "passed" if decision["decision"] == "promote" else "failed", "native": native}

    def promote(self, env: str) -> dict:
        road = self.road(env)
        previous = slot_state(self.project, env, "current")
        self._previous = previous
        road.stop(self.project, env, "candidate")
        _, pkg = self.package(env, "current")
        problems = validate_package(pkg)
        if problems:
            return {"outcome": "failed", "native": {"problems": problems, "why": "the production package is not valid"}}
        state = road.deploy(self.project, pkg)
        res = operate.smoke(state["base_url"], version=self.rel["rev12"])
        if not res["ok"]:
            return {"outcome": "failed", "native": {"smoke": res, "why": f"the promoted release failed its smoke "
                                                                         f"check: {res['reason']}"}}
        before = {"release": previous["release"], "revision": previous["revision"]} if previous else None
        self.rel["promoted"] = {"environment": env, "previous": before, "base_url": state["base_url"], "at": self.now()}
        self.log("promoted", environment=env, previous=before, revision=self.rel["revision"])
        self.stage_to(7, f"release {self.rel['release']} was promoted to {env}", released=True)
        return {"outcome": "passed", "native": {"previous": before, "base_url": state["base_url"],
                                                "health": state.get("health")}}
