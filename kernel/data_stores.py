"""The factory's data, as one view (FR-CTX1, D-0024 item 2): what the factory home keeps, how large, whether its
ledgers hold, how long each store is kept, and what can be cleaned safely.

- **Stores**: every folder and file of the factory home, named (projects, the holdout custody, job logs,
  snapshots of adopted folders, exports, the relay, the cockpit's layouts, ...), with bytes and files; the lanes
  folder too, which lives outside the home. The holdout custody shows its size only.
- **Integrity**: every ledger's hash chain verified now: each project's, Rihma's own and the relay's deliveries.
- **Retention**: what each store keeps and for how long. Records (ledgers, canon, specs, contracts, the custody)
  are kept for as long as the project is; nothing here ever proposes to remove them.
- **Clean-up**: what can go safely, by rule: job logs older than RETAIN_DAYS, and snapshots of adopted folders no
  project names any more and older than RETAIN_DAYS. A clean-up is a proposal a named person signs
  (``propose_cleanup``, in Rihma's own ledger), and it is carried out only when a person with the IT or operations
  persona applies it (``apply_cleanup``): each item is checked unchanged first, and what was removed is recorded.
"""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.context_map import ledger_state, size_of
from kernel.ledgerstore import LedgerStore
from kernel.people import PERSONAS, is_person
from kernel.store import read_json, write_json

RETAIN_DAYS = 30
CLEANERS = ("it", "operations")
CLEANUP_DIR = "_data/cleanup"
STORE_INFO: dict[str, tuple[str, str]] = {
    "projects": ("Projects", "each project's records, ledger and repository: kept as long as the project"),
    "holdouts": ("Holdout custody", "the hidden scenarios: kept as long as the project; sizes only here"),
    "jobs": ("Job logs", f"the cockpit's job logs: older than {RETAIN_DAYS} days may be cleaned"),
    "snapshots": ("Snapshots of adopted folders", f"baselines of folders adopted without git: one no project names "
                                                  f"and older than {RETAIN_DAYS} days may be cleaned"),
    "exports": ("Exports", "evidence packs and outputs a person exported: kept until a person removes them"),
    "scans": ("Scans", "folder scans shown before anything is sent"),
    "relay": ("Relay", "deliveries to the systems the factory reaches, hash-chained"),
    "_cockpit": ("Cockpit layouts", "each person's layout"), "cockpit": ("Cockpit state", "the cockpit's heads"),
    "automations": ("Automations", "what runs on its own, and its history"),
    "review": ("Review digests", "since you last looked"), "factory": ("Factory settings", "default checks"),
    "_shape": ("Shape it in chat", "conversations that shape a need"),
    "_walkthroughs": ("Walkthroughs", "walkthroughs in progress"), "hooks": ("Hooks", "incoming hook settings"),
    "_data": ("Clean-up proposals", "each proposal and what it removed"),
    "paved_roads.json": ("Paved roads", "IT's road settings"),
}


def _now(factory: Any) -> dt.datetime:
    now: dt.datetime = factory.clock.now()
    return now


def _mtime(path: Path) -> dt.datetime:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC)


def ledgers(factory: Any) -> list[dict[str, Any]]:
    """Every ledger of the home, its hash chain verified now."""
    out = []
    for p in factory.projects():
        led = p.ledger()
        out.append({"ledger": f"projects/{p.pid}/ledger.jsonl", "project": p.pid,
                    "title": p.meta.get("title")} | ledger_state(led.path, led.records()))
    relay = Path(factory.home) / "relay" / "deliveries.jsonl"
    if relay.exists():
        led = LedgerStore(relay)
        out.append({"ledger": "relay/deliveries.jsonl", "project": None, "title": "Relay deliveries"}
                   | ledger_state(relay, led.records()))
    return out


def _incidents(factory: Any) -> int:
    total = 0
    for p in factory.projects():
        doc = read_json(p.path("ops", "incidents.json"), [])
        total += len(doc.get("incidents", []) if isinstance(doc, dict) else doc or [])
    return total


def stores(factory: Any) -> list[dict[str, Any]]:
    """Every top-level folder and file of the home, named, with its size; and the lanes folder outside it."""
    from kernel.lanes import lanes_root

    home = Path(factory.home)
    rows = []
    for entry in sorted(home.iterdir()) if home.is_dir() else []:
        b, n = size_of(entry)
        label, keep = STORE_INFO.get(entry.name, (entry.name, "not named by the kernel: kept"))
        rows.append({"store": entry.name, "label": label, "bytes": b, "files": n, "retention": keep,
                     "custody": entry.name == "holdouts"})
    lanes = lanes_root()
    if lanes.is_dir():
        b, n = size_of(lanes)
        rows.append({"store": "lanes", "label": "Lanes (outside the home)", "bytes": b, "files": n,
                     "retention": "the lanes' working copies: prepared again when needed", "custody": False,
                     "outside": True})
    return rows


def _named_by_projects(factory: Any) -> str:
    return "\n".join(p.path("project.json").read_text(encoding="utf-8") for p in factory.projects()
                     if p.path("project.json").exists())


def candidates(factory: Any) -> list[dict[str, Any]]:
    """What can be cleaned safely now, by rule: old job logs and unreferenced old snapshots."""
    home, now = Path(factory.home), _now(factory)
    limit = dt.timedelta(days=RETAIN_DAYS)
    out = []
    for log in sorted((home / "jobs").glob("*.log")) if (home / "jobs").is_dir() else []:
        if now - _mtime(log) > limit:
            out.append({"path": f"jobs/{log.name}", "bytes": log.stat().st_size, "mtime": log.stat().st_mtime,
                        "why": f"a job log older than {RETAIN_DAYS} days"})
    named = _named_by_projects(factory)
    for snap in sorted((home / "snapshots").iterdir()) if (home / "snapshots").is_dir() else []:
        if snap.is_dir() and snap.name not in named and now - _mtime(snap) > limit:
            out.append({"path": f"snapshots/{snap.name}", "bytes": size_of(snap)[0], "mtime": snap.stat().st_mtime,
                        "why": f"a snapshot no project names, older than {RETAIN_DAYS} days"})
    return out


def proposals(factory: Any) -> list[dict[str, Any]]:
    folder = Path(factory.home) / CLEANUP_DIR
    return [read_json(p) for p in sorted(folder.glob("CU-*.json"))] if folder.is_dir() else []


def view(factory: Any) -> dict[str, Any]:
    """The Data view: stores, ledgers and their integrity, retention, what can be cleaned and the proposals."""
    rows, chains, can = stores(factory), ledgers(factory), candidates(factory)
    broken = [c["ledger"] for c in chains if not c["intact"]]
    return {"home": "the factory home", "stores": rows, "bytes": sum(r["bytes"] for r in rows if not r.get("outside")),
            "ledgers": chains, "integrity": {"ledgers": len(chains), "intact": len(chains) - len(broken),
                                             "broken": broken},
            "incidents": _incidents(factory), "projects": len([p for p in factory.projects()
                                                               if not p.pid.startswith("_")]),
            "retain_days": RETAIN_DAYS, "cleanable": {"items": can, "bytes": sum(c["bytes"] for c in can)},
            "proposals": proposals(factory), "cleaners": list(CLEANERS),
            "never_cleaned": "ledgers, the canon, specs, contracts, releases and the holdout custody"}


def _signed(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"refused: {person!r} is not a person; a clean-up is signed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"refused: persona must be one of {', '.join(PERSONAS)}")
    if persona not in CLEANERS:
        raise DecisionRefused(f"refused: a clean-up is for the {' or '.join(CLEANERS)} persona, not {persona}")


def propose_cleanup(factory: Any, *, person: str, persona: str) -> dict[str, Any]:
    """A signed proposal of what can be cleaned now, kept in the home and recorded in Rihma's own ledger."""
    from kernel.learn import factory_project

    _signed(person, persona)
    items = candidates(factory)
    folder = Path(factory.home) / CLEANUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    n = max([int(p.stem[3:]) for p in folder.glob("CU-*.json") if p.stem[3:].isdigit()], default=0) + 1
    doc = {"id": f"CU-{n:04d}", "state": "proposed", "items": items, "bytes": sum(i["bytes"] for i in items),
           "person": person, "persona": persona, "at": factory.clock.stamp(), "retain_days": RETAIN_DAYS}
    write_json(folder / f"{doc['id']}.json", doc)
    factory_project(factory).log("data_cleanup_proposed", {"id": doc["id"], "items": len(items), "bytes": doc["bytes"],
                                                           "person": person, "persona": persona})
    return doc


def apply_cleanup(factory: Any, cid: str, *, person: str, persona: str) -> dict[str, Any]:
    """Carry out a proposal: each item still as proposed (same size and time, still cleanable by rule) is removed;
    any other is kept and named. Recorded in Rihma's own ledger, signed."""
    from kernel.learn import factory_project

    _signed(person, persona)
    path = Path(factory.home) / CLEANUP_DIR / f"{cid}.json"
    doc = read_json(path) if path.name.startswith("CU-") else None
    if not isinstance(doc, dict):
        raise KeyError(f"no clean-up proposal {cid}")
    if doc["state"] != "proposed":
        raise ValueError(f"{cid} was {doc['state']} already")
    now = {c["path"]: c for c in candidates(factory)}
    removed, kept = [], []
    for item in doc["items"]:
        target = Path(factory.home) / item["path"]
        still = now.get(item["path"])
        if still is None or still["mtime"] != item["mtime"] or still["bytes"] != item["bytes"]:
            kept.append({"path": item["path"], "why": "changed since the proposal, or no longer cleanable"})
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(item["path"])
    doc.update(state="applied", applied_by=person, applied_persona=persona, applied_at=factory.clock.stamp(),
               removed=removed, kept=kept)
    write_json(path, doc)
    freed = sum(i["bytes"] for i in doc["items"] if i["path"] in removed)
    factory_project(factory).log("data_cleanup_applied", {"id": cid, "removed": removed,
                                                          "kept": [k["path"] for k in kept], "bytes": freed,
                                                          "person": person, "persona": persona})
    return doc
