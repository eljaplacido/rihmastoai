"""When a holdout fails, a person rules whether the product or the scenario is wrong (FR-H3-AC-2).

A holdout is written outside the build, so the factory cannot tell by itself whether a failure
means the product is wrong or the scenario is. The first live run showed both are possible: a
scenario assumed an empty store, while other scenarios on the same deployment had left data in
it. A person decides on a `holdout_ruling` card:

- **product_defect:** the failure becomes a defect in the change loop. A regression criterion
  is added, the task reopens, and a new revision is built and delivered. The criterion is one
  the builder sees, so it says only that a held-out check of the requirement failed on that
  release: never the scenario's request, what it expected or what it observed.
- **scenario_defect:** the holdout author, never the builder, rewrites that scenario. The
  reason and the person are recorded, and the same revision is delivered again.

A person's reason on a ruling may describe the scenario, and so may the reason a rewrite records.
Both are kept in the holdout custody (`rulings.jsonl` in the project's holdout folder), never in
the canon or the ledger, which the evidence pack exports whole. Those keep only the reason's
sha256, its length and a pointer to the custody (FR-O3-AC-3).
"""

from __future__ import annotations

import hashlib
import json

from kernel.canon import Canon
from kernel.store import Project

CUSTODY_FILE = "rulings.jsonl"
HELD_REASON = "held in the holdout custody"


def hold_reason(project: Project, text: str, *, ref: str) -> dict:
    """Keep a reason that may describe a holdout scenario in the holdout custody. Returns what the
    canon and the ledger hold instead: its sha256, its length and where it is kept."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if held_reason(project, digest) is None:
        path = project.holdouts_dir / CUSTODY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {"sha256": digest, "length": len(text), "ref": ref, "reason": text,
                "at": project.factory.clock.stamp()}
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return {"custody": "holdout", "file": CUSTODY_FILE, "sha256": digest, "length": len(text)}


def held_reason(project: Project, digest: str) -> str | None:
    """A reason from the holdout custody by its sha256, or None when the custody does not hold it.
    A line whose text no longer matches its sha256 is not returned."""
    path = project.holdouts_dir / CUSTODY_FILE
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        text = rec.get("reason") if isinstance(rec, dict) else None
        if isinstance(text, str) and rec.get("sha256") == digest == hashlib.sha256(text.encode("utf-8")).hexdigest():
            return text
    return None


def ruling_reason(project: Project, decision: dict) -> str | None:
    """The reason a person gave on a ruling: from the custody, or, for a ruling decided before
    reasons were held there, as the canon recorded it."""
    held = decision.get("reason_custody")
    if isinstance(held, dict):
        return held_reason(project, str(held.get("sha256", "")))
    return decision.get("reason") or None


def failing_holdouts(release: dict) -> list:
    for step in release.get("steps", []):
        if str(step.get("step", "")).startswith("holdouts:") and step.get("outcome") == "failed":
            return [f for f in (step.get("native") or {}).get("failing", [])]
    return []


def open_ruling(project, release_no, release: dict) -> dict | None:
    failing = failing_holdouts(release)
    if not failing:
        return None
    canon = Canon(project)
    for c in canon.cards(state=None, kind="holdout_ruling"):
        if c["refs"].get("release") == release_no:
            return c
    lines = []
    for f in failing:
        lines.append(f"- {f['criterion']}: step {f.get('failed_step')} {f.get('request', {}).get('method', '')} "
                     f"{f.get('request', {}).get('path', '')}; expected {f.get('expected')}; observed "
                     f"{str(f.get('observed'))[:300]}")
    card = canon.card("holdout_ruling", f"Release {release_no}: {len(failing)} holdout(s) failed. Product or scenario?",
                      body="\n".join(lines),
                      refs={"release": release_no, "criteria": [f["criterion"] for f in failing],
                            "requirements": sorted({f["criterion"].rsplit("-AC-", 1)[0] for f in failing})},
                      payload={"failing": failing, "revision": release.get("revision")}, blocking=True)
    project.log("holdout_ruling_opened", {"card": card["id"], "release": release_no,
                                          "criteria": card["refs"]["criteria"]})
    return card


def defect_regression(card: dict) -> tuple[str, dict]:
    """The change text and the regression criterion a product-defect ruling files. They say only
    that a holdout failed, on which release, and the requirement it covers: never the scenario's
    request, what it expected or what it observed (FR-B4-AC-2), because the regression criterion is
    a visible test criterion the builder's envelope shows. The scenario stays in the custody and the
    ruling card, for the person who ruled."""
    release, crits = card["refs"].get("release"), list(card["refs"].get("criteria") or [])
    reqs = sorted({str(c).rsplit("-AC-", 1)[0] for c in crits}) or list(card["refs"].get("requirements") or [])
    text = (f"A held-out end-to-end check of {', '.join(reqs)} failed on release {release}, and a person ruled it a "
            f"product defect (ruling {card['id']}; held-out criteria {', '.join(crits)}).")
    then = (f"{reqs[0] if reqs else 'the requirement'} holds as its statement says: an end-to-end check the factory "
            f"holds out failed against release {release}")
    return text, {"given": "-", "when": "-", "then": then}


def apply_rulings(project, *, model) -> list:
    """Carry out every decided ruling once. Returns what was done."""
    from kernel.change import apply_change, submit, triage
    from kernel.compile import author_holdouts

    canon, done = Canon(project), []
    applied = set(project.read("rulings_applied.json", []) or [])
    for card in canon.cards(state="decided", kind="holdout_ruling"):
        if card["id"] in applied:
            continue
        d = card["decision"]
        crits = card["refs"]["criteria"]
        if d["verdict"] == "product_defect":
            text, regression = defect_regression(card)
            change = submit(project, persona=d["persona"], person=d["person"], text=text, kind_hint="defect")
            triage(project, change["id"], model=model)
            # The factory knows which requirement's scenario failed: that is not a model's guess.
            from kernel.store import write_json

            changed = canon.get_card(change["id"])
            changed["payload"]["triage"].update(requirements=card["refs"]["requirements"], by="ruling",
                                                regression=regression)
            write_json(canon.dir / "inbox" / f"{change['id']}.json", changed)
            out = apply_change(project, change["id"], model=model)
            done.append({"card": card["id"], "verdict": "product_defect", "change": change["id"], **out})
        else:
            saved = author_holdouts(project, model=model, only=crits, person=d["person"],
                                    reason=ruling_reason(project, d) or f"scenario defect ruled on {card['id']}",
                                    evidence=card["payload"].get("failing", []))
            project.update_meta(redeliver=True)
            done.append({"card": card["id"], "verdict": "scenario_defect", "reauthored": saved})
        applied.add(card["id"])
        project.write("rulings_applied.json", sorted(applied))
        project.log("holdout_ruling_applied", done[-1] | {"person": d["person"]})
    return done
