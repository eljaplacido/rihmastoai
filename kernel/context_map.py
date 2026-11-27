"""What Rihmasto knows about a project, and where it came from: the context map (FR-CTX1, D-0024 item 2).

One read of a project's records, never a store of its own and never a model's view:

- **sources**: the request, the folder's material map, the adopted or attached repository, the project's own
  conventions for its AI tools, and the alignment with the repository's own specs and tests;
- **records**: the canon's questions, assumptions, decisions and cards, and the ledger's size and integrity;
- **the graph**: its nodes and edges by kind, and what its check found (kernel/graph.py), contradictions included;
- **the contract and the spec**: their versions and the superseded ones;
- **usage**: the model runs per role (model_run, gnomon_run);
- **freshness**: when each was last updated, by the ledger, and which are stale, with why;
- **stores**: what the project keeps on disk, by store, in bytes, and the holdout custody's size (never its
  content).

Reading it writes nothing.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Any

# What makes a record stale: an event of these kinds after the record was last written (ledger order).
SETTLES = ("question_answered", "question_assumed", "assumption_settled", "request_replaced", "change_applied",
           "plan_edited")
OLD_DAYS = 30           # a source not refreshed in this many days is flagged as old, not wrong
CONTRADICTIONS = ("ambiguous_after_amendment", "edge_breaks_ontology", "rests_on_refuted", "unknown_kind")
STORES = (("canon", "canon"), ("ledger", "ledger.jsonl"), ("repository", "repo.git"), ("releases", "releases"),
          ("operations", "ops"), ("alignment", "alignment"), ("agent channel", "channel.json"))


def size_of(path: Path) -> tuple[int, int]:
    """(bytes, files) under ``path``: a file's size, or a folder's whole; (0, 0) when absent. Lock files count."""
    path = Path(path)
    if path.is_file():
        return path.stat().st_size, 1
    total = files = 0
    if path.is_dir():
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
                    files += 1
            except OSError:
                continue
    return total, files


def _index(records: list[Any]) -> dict[str, tuple[int, str | None]]:
    """The last (seq, at) of each event kind in the ledger."""
    out: dict[str, tuple[int, str | None]] = {}
    for r in records:
        if isinstance(r, dict) and isinstance(r.get("event"), dict):
            out[str(r["event"].get("kind"))] = (int(r.get("seq", 0)), r["event"].get("at"))
    return out


def _last(idx: dict[str, tuple[int, str | None]], *kinds: str) -> tuple[int, str | None]:
    found = [idx[k] for k in kinds if k in idx]
    return max(found, default=(-1, None))


def _request(project: Any) -> tuple[bool, str]:
    source = project.read("source.json", None) or {}
    if not source:
        return False, "no request yet"
    cut = f" (cut from {source['cut_from']:,})" if source.get("cut_from") else ""
    by = f", from {source['requested_by']}" if source.get("requested_by") else ""
    return bool(source.get("text")), f"{source.get('kind', '?')}, {len(source.get('text') or ''):,} characters{cut}{by}"


def _material(project: Any) -> tuple[bool, str]:
    mp = project.read("material.json", None) or {}
    t = mp.get("totals") or {}
    return bool(mp), (f"{t.get('files', 0)} files: {t.get('read', 0)} read, {t.get('summarised', 0)} summarised, "
                      f"{t.get('listed', 0)} listed, {t.get('skipped', 0)} skipped ({t.get('secrets', 0)} may hold "
                      "secrets, never read)") if mp else "not a folder source"


def _repository(project: Any) -> tuple[bool, str]:
    from kernel.graph_build import main_revision

    if not project.path("repo.git").exists():
        return False, "no repository yet"
    return True, f"{project.meta.get('source_kind') or 'built here'}; main at {(main_revision(project) or '-')[:12]}"


def _conventions(project: Any) -> tuple[bool, str]:
    mp = project.read("material.json", None) or {}
    ctx = mp.get("agent_context") if isinstance(mp.get("agent_context"), dict) else \
        project.read("agent_context.json", None)
    if not isinstance(ctx, dict):
        return False, "none found"
    n = {k: len(ctx.get(k) or []) for k in ("instructions", "stated", "skills")}
    return bool(n["instructions"] or n["stated"]), (f"{n['instructions']} instruction file(s), {n['stated']} stated "
                                                    f"command(s), {n['skills']} skill(s)")


def _alignment(project: Any) -> tuple[bool, str]:
    scan = project.read("alignment/scan.json", None)
    return (True, f"{len(scan.get('items') or [])} item(s) from the last scan") if isinstance(scan, dict) \
        else (False, "not scanned")


# Each source: its id, label, file, how it is read, and the ledger events that update it.
SOURCES = (("request", "The request", "source.json", _request, ("intake_done", "request_replaced")),
           ("material", "The folder's material map", "material.json", _material, ("material_scanned",
                                                                                  "material_added")),
           ("repository", "The repository", "repo.git", _repository, ("merged", "repo_created", "synced", "adopted")),
           ("conventions", "The project's own conventions for its AI tools", "material.json, agent_context.json",
            _conventions, ("material_scanned", "agent_context_read")),
           ("alignment", "Alignment with the repository's own specs and tests", "alignment/scan.json", _alignment,
            ("repo_alignment_scanned", "alignment_scanned")))


def _sources(project: Any, idx: dict[str, tuple[int, str | None]]) -> list[dict[str, Any]]:
    rows = []
    for sid, label, file, read, kinds in SOURCES:
        present, detail = read(project)
        rows.append({"id": sid, "label": label, "present": present, "file": file, "detail": detail,
                     "updated": _last(idx, *kinds)[1]})
    return rows


def _records(project: Any) -> dict[str, Any]:
    from kernel.canon import Canon

    canon = Canon(project)
    cards = canon.cards(state=None)
    return {"questions": dict(Counter(q["status"] for q in canon.questions())),
            "assumptions": dict(Counter(a["status"] for a in canon.assumptions())),
            "assumptions_overdue": len(canon.overdue()),
            "decisions": {"total": len(canon.decisions()), "stale": len(canon.decisions(stale=True))},
            "cards": {"open": dict(Counter(c["kind"] for c in cards if c["state"] == "open")),
                      "decided": sum(1 for c in cards if c["state"] != "open")},
            "comments": len(canon.comments())}


def ledger_state(path: Path, records: list[Any]) -> dict[str, Any]:
    """A ledger's size and integrity: its hash chain verified now."""
    from kernel.ledger import verify

    check = verify(records)
    ats = [r["event"].get("at") for r in records if isinstance(r, dict) and isinstance(r.get("event"), dict)]
    return {"records": len(records), "bytes": size_of(path)[0], "intact": check.intact, "broken_seq": check.broken_seq,
            "first": next((a for a in ats if a), None), "last": next((a for a in reversed(ats) if a), None)}


def _graph(project: Any) -> dict[str, Any]:
    from kernel.graph import build

    try:
        g = build(project)
        checked = g.check()
    except Exception as exc:  # noqa: BLE001 - the map is still read; the graph says it was not measured
        return {"outcome": "not_measured", "why": f"{type(exc).__name__}: {exc}"[:200]}
    if checked.get("outcome") != "answered":
        return {"outcome": checked.get("outcome"), "why": checked.get("causes") or checked.get("why")}
    counts = checked.get("counts") or {}
    return {"outcome": "answered", "nodes": dict(Counter(v["kind"] for v in g.nodes.values())),
            "edges": dict(Counter(e["rel"] for e in g.edges)), "findings": counts,
            "contradictions": sum(n for k, n in counts.items() if k in CONTRADICTIONS)}


def _contract(project: Any, idx: dict[str, tuple[int, str | None]]) -> dict[str, Any]:
    spec, contract = project.read("spec.json", None), project.read("contract.json", None)
    versions = sorted(p.name for p in project.dir.glob("spec.v*.json"))
    return {"spec": {"present": isinstance(spec, dict), "requirements": len((spec or {}).get("requirements") or []),
                     "written": _last(idx, "spec_written", "change_applied")[1], "superseded": versions},
            "contract": {"present": isinstance(contract, dict),
                         "revision": (contract or {}).get("revision"),
                         "tasks": len((contract or {}).get("tasks") or []),
                         "compiled": _last(idx, "contract_compiled")[1]}}


def _usage(records: list[Any]) -> dict[str, Any]:
    roles: dict[str, dict[str, Any]] = {}
    for r in records:
        ev = r.get("event") if isinstance(r, dict) else None
        if not isinstance(ev, dict) or ev.get("kind") not in ("model_run", "gnomon_run"):
            continue
        p = ev.get("payload") or {}
        role = str(p.get("role") or ("builder" if ev["kind"] == "gnomon_run" else "?"))
        row = roles.setdefault(role, {"runs": 0, "tokens_in": 0, "tokens_out": 0, "failed": 0, "last": None})
        toks = p.get("tokens") or {}
        row["runs"] += 1
        row["tokens_in"] += int(toks.get("in") or 0)
        row["tokens_out"] += int(toks.get("out") or 0)
        row["failed"] += p.get("verdict") == "failed"
        row["last"] = ev.get("at")
    return {"roles": roles, "runs": sum(r["runs"] for r in roles.values()),
            "note": "tokens as each run recorded them; a scripted or unrecorded run counts 0"}


def _age_days(at: str | None, now: dt.datetime) -> float | None:
    if not at:
        return None
    try:
        return (now - dt.datetime.fromisoformat(at.replace("Z", "+00:00"))).total_seconds() / 86400
    except ValueError:
        return None


def _freshness(project: Any, idx: dict[str, tuple[int, str | None]], sources: list[dict[str, Any]]) -> list[dict]:
    now = project.factory.clock.now()
    settled = _last(idx, *SETTLES)
    rows = []

    def row(what: str, written: tuple[int, str | None], stale_when: tuple[int, str | None], why: str) -> None:
        if written[0] < 0:
            return
        stale = stale_when[0] > written[0]
        rows.append({"what": what, "updated": written[1], "stale": stale, "why": why if stale else None})

    row("the brief", _last(idx, "brief_written"), settled, "a question or assumption was settled after it was written")
    row("the spec", _last(idx, "spec_written"), settled, "a question, an assumption or the request changed after it")
    row("the contract", _last(idx, "contract_compiled"), _last(idx, "spec_written", "change_applied", "plan_edited"),
        "the spec changed after it was compiled: compile again")
    for s in sources:
        if s["present"] and s["id"] in ("material", "conventions", "alignment"):
            age = _age_days(s["updated"], now)
            old = age is not None and age > OLD_DAYS
            rows.append({"what": s["label"].lower(), "updated": s["updated"], "stale": old,
                         "why": f"not read again for {int(age or 0)} days" if old else None})
    return rows


def stores(project: Any) -> dict[str, Any]:
    """What the project keeps on disk, by store, and the holdout custody's size (never its content)."""
    out: dict[str, Any] = {}
    named = set()
    for label, rel in STORES:
        b, n = size_of(project.path(rel))
        named.add(rel)
        if n:
            out[label] = {"bytes": b, "files": n, "path": rel}
    rest_b = rest_n = 0
    for p in project.dir.iterdir() if project.dir.exists() else []:
        if p.name not in named:
            b, n = size_of(p)
            rest_b, rest_n = rest_b + b, rest_n + n
    out["records"] = {"bytes": rest_b, "files": rest_n, "path": "*.json, *.md"}
    b, n = size_of(project.holdouts_dir)
    out["holdout custody"] = {"bytes": b, "files": n, "path": "holdouts/ (outside the project: sizes only)"}
    return {"by_store": out, "bytes": sum(v["bytes"] for v in out.values())}


def context_map(factory: Any, project: Any) -> dict[str, Any]:
    """Everything above, for one project. Writes nothing."""
    led = project.ledger()
    records = led.records()
    idx = _index(records)
    sources = _sources(project, idx)
    fresh = _freshness(project, idx, sources)
    return {"project": {"id": project.pid, "title": project.meta.get("title"), "stage": project.meta.get("stage"),
                        "source_kind": project.meta.get("source_kind")},
            "sources": sources, "records": _records(project), "ledger": ledger_state(led.path, records),
            "graph": _graph(project), **_contract(project, idx), "usage": _usage(records), "freshness": fresh,
            "stale": [f["what"] for f in fresh if f["stale"]], "stores": stores(project)}
