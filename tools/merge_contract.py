"""Merge two versions of contract/contract.json by id: the union of requirements, criteria and tasks.

Used when parallel branches each added criteria and tasks. Ours wins on any id both sides changed;
theirs adds what ours lacks. A task id taken on both sides with different criteria is renumbered on
theirs, to the next free V-n, and reported.

    python tools/merge_contract.py OURS.json THEIRS.json > contract/contract.json
"""

from __future__ import annotations

import json
import re
import sys

# Requirement ids renumbered on main (22 November 2026), because the brief already used them for
# other requirements. Only a branch made BEFORE that renumbering carries the old ids with the new
# meaning: pass --renames for such a branch. Branches made after it use FR-B1, FR-T2 and FR-T3 in
# the brief's own meaning, so renaming them would drop real requirements (it did, once).
RENAMES = {"FR-T2": "FR-V1", "FR-T3": "FR-W1", "FR-B1": "FR-X1"}


def renamed(contract: dict, renames: dict = RENAMES) -> dict:
    text = json.dumps(contract, ensure_ascii=False)
    for old, new in renames.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return json.loads(text)


def _merge_requirements(ours: dict, theirs: dict, notes: list) -> list:
    reqs = {r["id"]: r for r in ours["requirements"]}
    order = [r["id"] for r in ours["requirements"]]
    theirs_order = [r["id"] for r in theirs["requirements"]]
    for r in theirs["requirements"]:
        if r["id"] not in reqs:
            i = theirs_order.index(r["id"])
            prev = theirs_order[i - 1] if i else None
            order.insert(order.index(prev) + 1 if prev in order else len(order), r["id"])
            reqs[r["id"]] = r
            notes.append(f"requirement {r['id']} added")
            continue
        have = {a["id"] for a in reqs[r["id"]]["acceptance"]}
        for a in r["acceptance"]:
            if a["id"] not in have:
                reqs[r["id"]]["acceptance"].append(a)
                notes.append(f"criterion {a['id']} added")
    return [reqs[i] for i in order]


def _merge_tasks(ours: dict, theirs: dict, notes: list) -> list:
    tasks = list(ours["tasks"])
    by_id = {t["id"]: t for t in tasks}
    numbers = [int(m.group(1)) for t in tasks if (m := re.fullmatch(r"V-(\d+)", t["id"]))]
    for t in theirs["tasks"]:
        if t["id"] in by_id:
            if by_id[t["id"]]["criteria"] == t["criteria"]:
                continue
            numbers.append(max(numbers or [0]) + 1)
            notes.append(f"task {t['id']} (theirs) renumbered to V-{numbers[-1]}")
            t = {**t, "id": f"V-{numbers[-1]}"}
        tasks.append(t)
        by_id[t["id"]] = t
    return tasks


def merge(ours: dict, theirs: dict, *, renames: bool = False) -> tuple[dict, list]:
    notes: list = []
    if renames:
        ours, theirs = renamed(ours), renamed(theirs)
    out = dict(ours)
    out["requirements"] = _merge_requirements(ours, theirs, notes)
    out["tasks"] = _merge_tasks(ours, theirs, notes)
    return out, notes


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    use_renames = "--renames" in argv
    files = [a for a in argv if a != "--renames"]
    with open(files[0], encoding="utf-8") as a, open(files[1], encoding="utf-8") as b:
        ours, theirs = json.load(a), json.load(b)
    merged, notes = merge(ours, theirs, renames=use_renames)
    for n in notes:
        print(n, file=sys.stderr)
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    sys.stdout.write(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
