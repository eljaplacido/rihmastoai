"""Since you last looked (FR-REV1): review what agents and automations shipped, instead of watching them work.

    rihmasto review [<pid>] [--since 24h] [--json]          what happened since you last looked
    rihmasto review mark <item>... --person P --persona X    a signed "reviewed" record per item
    rihmasto review done [--project <pid>] --person P --persona X    you looked at all of it: the marker moves

The owner (2026-11-24), quoting an engineer: "You're not supposed to watch Claude Code work. You're supposed
to wake up and review what it shipped." The review is one person's morning check, across their projects (or
one project), from the records alone, grouped and ranked by what needs that person:

1. **Waiting on you:** open cards the persona may decide, with their age (kernel/review_items.py);
2. **Went wrong:** gate failures, escalations, failed releases, jobs and checks, refusals, automations paused
   by their breaker (kernel/review_ledger.py);
3. **Decided for you:** decisions a delegation or an autopilot run made in the person's name, and the
   assumptions the factory made with their due dates, each with a way to overturn it;
4. **Shipped:** tasks merged with their gate verdict, rounds and diff stats; releases to test and to
   production; outputs built;
5. **From your IDE:** commits gated on attached or adopted repositories, with the verdict and the criteria
   the task touches; **From agents:** coding agents' progress, their proposals waiting on a person and the gate
   and check results they asked for, from the agent channel (kernel/review_streams.py);
6. **Cost and usage:** the period's model runs, tokens and priced cost by project and role, or not measured.

The period starts where the person last marked a review done (``review_done`` in the factory's ledger, or in
a project's for that project's review; the later of the two counts), else 24 hours back; ``since`` names
another start. Reading the review records nothing. Every item carries its record and who or what did it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import re
from typing import Any

from kernel.delegation import stamp
from kernel.review_items import waiting
from kernel.review_ledger import Pass, cost, failed_jobs
from kernel.review_streams import factory_wrong, from_agents

GROUPS = ("waiting", "wrong", "decided", "shipped", "ide", "agents")
GROUP_LABEL = {"waiting": "Waiting on you", "wrong": "Went wrong", "decided": "Decided for you",
               "shipped": "Shipped", "ide": "From your IDE", "agents": "From agents"}
GROUP_QUESTION = {"waiting": "What can only you decide, and how long has it waited?",
                  "wrong": "What failed, was refused or was stopped?",
                  "decided": "What did the factory decide or assume in your name? Overturn what you would not have.",
                  "shipped": "What did agents merge, release and build? Mark what you looked at.",
                  "ide": "Which commits from your IDE did the gate judge, and how?",
                  "agents": "What did coding agents report, propose and ask the gate for?"}
HEADLINE_WORDS = (("shipped", "shipped"), ("waiting", "waiting on you"), ("wrong", "failed"),
                  ("decided", "decided for you"), ("ide", "from your IDE"), ("agents", "from agents"))
DEFAULT_HOURS = 24
_SPAN = re.compile(r"(\d{1,5})([mhd])\Z")
MARKER_KIND = "review_done"


def parse_since(text: str, now: dt.datetime) -> dt.datetime:
    """A start: ``90m``, ``24h``, ``7d`` back from now, or a time such as 2026-11-24T06:00Z."""
    raw = str(text).strip()
    m = _SPAN.match(raw)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - dt.timedelta(minutes=n if unit == "m" else 0, hours=n if unit == "h" else 0,
                                  days=n if unit == "d" else 0)
    try:
        at = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"since is 90m, 24h, 7d or a time such as 2026-11-24T06:00Z, not {raw!r}") from None
    return at if at.tzinfo else at.replace(tzinfo=dt.UTC)


def _done_records(ledger: Any, person: str, scope: str) -> list[dict[str, Any]]:
    return [r["event"]["payload"] for r in ledger.of_kind(MARKER_KIND)
            if r["event"]["payload"].get("person") == person and r["event"]["payload"].get("scope") == scope]


def marker(factory: Any, person: str, pid: str | None = None) -> dict[str, Any] | None:
    """``person``'s latest ``review_done``: across their projects, or for ``pid`` (the later one counts). It
    holds ``until``, the time the next review starts, and ``heads``, each ledger's last record then."""
    from kernel.learn import factory_project

    if not person:
        return None
    found = []
    fp = factory_project(factory, create=False)     # a read never creates the factory's canon
    if fp is not None:
        found += _done_records(fp.ledger(), person, "all")
    if pid is not None:
        with contextlib.suppress(KeyError):
            found += _done_records(factory.project(pid).ledger(), person, pid)
    found = [f for f in found if isinstance(f.get("until"), str)]
    return max(found, key=lambda f: f["until"]) if found else None


def last_reviewed(factory: Any, person: str, pid: str | None = None) -> str | None:
    """When ``person`` last marked a review done, or None."""
    m = marker(factory, person, pid)
    return str(m["until"]) if m else None


def window(factory: Any, person: str, pid: str | None, since: str | None) -> tuple[str, str, str, dict[str, int]]:
    """(start, end, basis, heads): the person's marker, the start they asked for, or the last 24 hours. After a
    marker, only records past the ledger heads it kept count, so one done at the same second shows nothing twice."""
    now = factory.clock.now()
    if since:
        return stamp(parse_since(since, now)), stamp(now), "asked", {}
    m = marker(factory, person, pid)
    if m:
        raw = m.get("heads")
        heads: dict[str, Any] = raw if isinstance(raw, dict) else {}
        return str(m["until"]), stamp(now), "last review", {str(k): int(v) for k, v in heads.items()}
    return stamp(now - dt.timedelta(hours=DEFAULT_HOURS)), stamp(now), "last 24 hours", {}


def heads_of(factory: Any, pid: str | None = None) -> dict[str, int]:
    """Each covered ledger's last record now: what a review done keeps beside its time."""
    return {p.pid: len(p.ledger().records()) - 1 for p in projects_of(factory, pid) if not p.pid.startswith("_")}


def _autopilots(project: Any) -> dict[str, str]:
    """Each autopilot run's delegation, so a decision it made says the autopilot made it."""
    runs = project.read("autopilot.json", []) or []
    runs = runs.get("runs", []) if isinstance(runs, dict) else runs
    return {str(r.get("delegation")): f"autopilot {r.get('id')}"
            for r in runs if isinstance(r, dict) and r.get("delegation")}


def projects_of(factory: Any, pid: str | None, visible: Any = None) -> list[Any]:
    """The projects a review covers: one, or every project (the factory's own canon for its cards)."""
    if pid is not None:
        return [factory.project(pid)]
    return [p for p in factory.projects() if visible is None or visible(p.pid)]


def headline(counts: dict[str, int]) -> str:
    said = [f"{counts[g]} {word}" for g, word in HEADLINE_WORDS if counts.get(g)]
    return "Since you last looked: " + (", ".join(said) if said else "nothing new")


def happened(counts: dict[str, int]) -> bool:
    """Whether anything new happened in the period: a new card, or a new item in any other group (an old card
    still waiting, or an old assumption now overdue, is not news)."""
    return bool(counts.get("new"))


def review(factory: Any, *, person: str = "", persona: str = "", project: str | None = None,
           since: str | None = None, jobs: list[dict[str, Any]] | None = None, visible: Any = None,
           diffs: bool = True) -> dict[str, Any]:
    """The review for ``person`` as ``persona``: every group with its items ranked, the counts, a headline,
    and the period's cost. ``jobs`` are the cockpit's background jobs; ``visible`` limits the projects."""
    person = (person or "").strip()
    start, end, basis, heads = window(factory, person, project, since)
    covered = projects_of(factory, project, visible)
    products = [p for p in covered if not p.pid.startswith("_")]
    groups = _collect(factory, covered, (start, end), heads, person=person, persona=persona, diffs=diffs)
    groups["wrong"] += [j for j in failed_jobs(jobs, start, end) if project is None or j.get("job_project") == project]
    for items in groups.values():
        items.sort(key=lambda i: (bool(i.get("reviewed")), i["rank"], i.get("at") or ""))
    counts = _counts(groups)
    return {"person": person or None, "persona": persona or None, "project": project, "since": start, "until": end,
            "basis": basis, "headline": headline(counts), "happened": happened(counts), "counts": counts,
            "groups": [{"id": g, "label": GROUP_LABEL[g], "question": GROUP_QUESTION[g], "items": groups[g],
                        "count": len(groups[g])} for g in GROUPS],
            "cost": cost(products, start, end, heads), "projects": [p.pid for p in products]}


def _collect(factory: Any, covered: list[Any], period: tuple[str, str], heads: dict[str, int], *, person: str,
             persona: str, diffs: bool) -> dict[str, list[dict[str, Any]]]:
    """Every project's items of the period, by group: its open cards, then one pass over its ledger."""
    start, end = period
    now = factory.clock.now()
    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUPS}
    for p in covered:
        groups["waiting"] += waiting(p, persona, now, start, strict=bool(heads))
        if p.pid.startswith("_"):     # the factory's own: automations paused, factory-wide runs failed
            groups["wrong"] += factory_wrong(p, start, end, heads.get(p.pid, -1))
            continue
        groups["agents"] += from_agents(p, start, end)     # the "From agents" hook: the agent channel
        for it in Pass(p, start, end, person=person, autopilots=_autopilots(p), diffs=diffs,
                       after=heads.get(p.pid, -1)).run():
            groups[it["group"]].append(it)
    return groups


def _counts(groups: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts = {g: len(items) for g, items in groups.items()}
    counts["new_waiting"] = sum(1 for i in groups["waiting"] if i.get("new"))
    counts["new"] = sum(1 for items in groups.values() for i in items if i.get("new", True))
    counts["unreviewed"] = sum(1 for g in ("shipped", "ide") for i in groups[g] if not i.get("reviewed"))
    return counts


def find(factory: Any, item_id: str, *, person: str = "", persona: str = "") -> dict[str, Any] | None:
    """One item of the review by its id, read over all time (an item stays findable after its period)."""
    from kernel.review_marks import parse_item

    pid = parse_item(item_id)[0]
    out = review(factory, person=person, persona=persona, project=pid, since="2000-01-01T00:00:00Z")
    return next((i for g in out["groups"] for i in g["items"] if i["id"] == item_id), None)


def detail(factory: Any, item_id: str, *, person: str = "", persona: str = "") -> dict[str, Any]:
    """What the preview drawer shows for one item: the item, its record's facts, the diff when it has one
    (with each file's counts and the diff itself, cut at a readable size), and the gate's signals."""
    from kernel import review_diff
    from kernel.review_marks import parse_item

    pid = parse_item(item_id)[0]
    found = find(factory, item_id, person=person, persona=persona)
    if found is None:
        raise KeyError(f"no review item {item_id}")
    project = factory.project(pid)
    record = _payload(project, found["record"].get("seq"))
    facts = [[k, v] for k, v in record.items() if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 300]
    diff = found.get("diff")
    stats = diff if isinstance(diff, dict) and diff.get("measured") else None
    if stats and found["kind"] in ("task_merged", "commit_gated"):
        base = str(stats["base"])
        diff = review_diff.change(project, base=base.rstrip("^"), head=stats["head"], parent_of_base=base.endswith("^"),
                                  repository=found.get("repository"), preview=True)
    return {"item": found, "facts": facts, "diff": diff, "signals": record.get("signals") or found.get("signals"),
            "objections": record.get("objections") or found.get("objections") or []}


def _payload(project: Any, seq: Any) -> dict[str, Any]:
    """One ledger record's payload by its number ({} when the item has none)."""
    if not isinstance(seq, int):
        return {}
    rec = next((r for r in project.ledger().records() if isinstance(r, dict) and r.get("seq") == seq), None)
    payload = (rec or {}).get("event", {}).get("payload")
    return dict(payload) if isinstance(payload, dict) else {}
