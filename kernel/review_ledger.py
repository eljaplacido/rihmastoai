"""The review's pass over one project's ledger (FR-REV1): what shipped, what went wrong, what was decided in a
person's name and what was gated from a developer's IDE, in the period; and the period's cost.

One pass reads the ledger in order. What a record means can depend on what came before it (a merged task's
rounds, its first round's commit, the model and runner that built it), so that is kept as the pass goes;
only records inside the period become items. ``review_marked`` records say which items a person already
looked at: an item is reviewed when a mark for it comes after its own record.

Records other streams add are read by the kinds they really write (kernel/review_streams.py): an automation run
that failed, a check that failed, a console command that failed, a task a cell runner refused.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import quote

from kernel import review_diff
from kernel.canon import Canon
from kernel.review_items import action, actor, assumptions, delegated, href, item
from kernel.review_streams import WRONG_MORE


def _why(pl: dict[str, Any]) -> str:
    for key in ("why", "reason", "error", "stop_reason"):
        if isinstance(pl.get(key), str) and pl[key].strip():
            return pl[key].strip()[:300]
    objections = pl.get("objections")
    return str(objections[0])[:300] if isinstance(objections, list) and objections else ""


def _failed(pl: dict[str, Any]) -> bool:
    return pl.get("verdict") not in (None, "passed")


def _is_wrong(when: Any, pl: dict[str, Any]) -> bool:
    """A WRONG entry's test: always (False), its verdict not passed (True), or its own test of the payload."""
    return bool(when(pl)) if callable(when) else (not when or _failed(pl))


# kind -> (rank, title, when it is wrong: always (False), only when its verdict is not passed (True), or a test of
# its payload). Lower ranks come first. A title names the record's own fields; one a record lacks reads as "?".
WRONG: dict[str, tuple[int, str, Any]] = {
    "incident_opened": (0, "An incident opened on release {release} in {environment}", False),
    "escalated": (0, "{task} escalated to a person", False),
    "release_failed": (1, "Release {release} failed at {step}", False),
    "rolled_back": (1, "Release {release} was rolled back in {environment}", False),
    "probe_failed": (1, "A probe failed on release {release} in {environment}", False),
    "gate": (2, "{task} round {round}: the gate said {verdict}", True),
    "security_gate": (2, "The security gate said {verdict}", True),
    "holdouts_run": (2, "Holdouts {verdict}: {failed} of {scenarios} failed", True),
    "confidential_refused": (2, "Refused: a confidential step would have left for a hosted endpoint ({where})", False),
    "road_refused": (3, "A paved road was refused ({card})", False),
    "merge_rejected": (3, "{task} was not merged: {why}", False),
    "apparatus_failure": (3, "A model endpoint failed ({where})", False),
    "workspace_refused": (3, "A workspace submission was refused ({branch})", False),
    "accept_refused": (3, "Accepting {card} as is was refused", False),
    "upstream_sync_failed": (3, "The upstream sync failed", False),
    "embed_triage_failed": (4, "A website chat message could not be triaged", False),
    "gnomon_run_not_ingested": (4, "A Gnomon run of {task} could not be read back", False),
    **WRONG_MORE,       # automations, checks, the console and the cell runners, as they record (review_streams.py)
}
IDE_ASKED = ("gate my code",)


class _Fields(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "?"


def said(template: str, pl: dict[str, Any]) -> str:
    """A title from a record's own fields; a field the record lacks reads as "?"."""
    return template.format_map(_Fields({k: v for k, v in pl.items() if isinstance(v, (str, int, float))}))


def _ide(pl: dict[str, Any]) -> bool:
    return pl.get("asked_as") in IDE_ASKED or isinstance(pl.get("author"), dict) or bool(pl.get("repository"))


class Pass:
    """One project's records in order, and the items of the period."""

    def __init__(self, project: Any, start: str, end: str, *, person: str, autopilots: dict[str, str],
                 diffs: bool = True, after: int = -1) -> None:
        self.p, self.start, self.end, self.person, self.autopilots = project, start, end, person, autopilots
        self.diffs, self.after = diffs, after
        self.items: list[dict[str, Any]] = []
        self.marks: dict[str, dict[str, Any]] = {}
        self.first_head: dict[str, Any] = {}
        self.rounds: dict[str, int] = defaultdict(int)
        self.model: dict[str, Any] = {}
        self.runner: dict[str, Any] = {}
        self.releases: dict[Any, dict[str, Any]] = {}
        contract = project.read("contract.json") or {}
        tasks = contract.get("tasks") if isinstance(contract, dict) else None
        self.tasks = {t["id"]: t for t in tasks or [] if isinstance(t, dict) and "id" in t}
        self._canon: Canon | None = None
        self._active: set[str] | None = None
        self.skip_assumptions: set[str] = set()

    @property
    def canon(self) -> Canon:
        if self._canon is None:
            self._canon = Canon(self.p)
        return self._canon

    def run(self) -> list[dict[str, Any]]:
        for rec in self.p.ledger().records():
            ev = rec.get("event") if isinstance(rec, dict) else None
            if not isinstance(ev, dict) or not isinstance(ev.get("payload"), dict):
                continue
            kind, pl, at = str(ev.get("kind") or ""), ev["payload"], str(ev.get("at") or "")
            seq = int(rec.get("seq", 0))
            self._before(kind, pl, at, seq)
            if seq > self.after and self.start <= at <= self.end:
                self._one(kind, pl, at, seq)
            if kind == "merged":
                self.first_head.pop(pl.get("task"), None)
                self.rounds.pop(pl.get("task"), None)
        self.items += list(self.releases.values())
        self.items += assumptions(self.p, self.canon, self.start, self.end, self.p.factory.clock.today(),
                                  self.skip_assumptions, strict=self.after >= 0)
        for i in self.items:
            mark = self.marks.get(i["id"])
            i["reviewed"] = mark if mark and mark["seq"] > (i["record"].get("seq") or -1) else None
        return self.items

    def _before(self, kind: str, pl: dict[str, Any], at: str, seq: int) -> None:
        task = pl.get("task")
        if kind == "cell_ran" and task:
            self.first_head.setdefault(task, pl.get("head"))
            self.model[task] = pl.get("final_model") or pl.get("model")
            self.runner[task] = pl.get("runner") or pl.get("harness")
        elif kind == "gate" and task and not _ide(pl):
            self.rounds[task] += 1
        elif kind == "review_marked" and isinstance(pl.get("item"), str):
            self.marks[pl["item"]] = {"seq": seq, "person": pl.get("person"), "persona": pl.get("persona"), "at": at}

    def _one(self, kind: str, pl: dict[str, Any], at: str, seq: int) -> None:
        if kind == "merged":
            self.items.append(self._merged(pl, at, seq))
        elif kind in ("release_done", "promoted"):
            self._release(kind, pl, at, seq)
        elif kind == "output_built" and pl.get("state") == "built":
            self.items.append(self._output(pl, at, seq))
        elif kind == "gate" and _ide(pl):
            self.items.append(self._commit(pl, at, seq))
        elif kind == "delegated_decision" and (not self.person or pl.get("person") == self.person):
            if self._active is None:
                from kernel.review_items import active_delegations

                self._active = active_delegations(self.p)
            it = delegated(self.p, pl, at=at, seq=seq, autopilots=self.autopilots, canon=self.canon,
                           active=self._active)
            if it.get("assumption"):
                self.skip_assumptions.add(it["assumption"])
            self.items.append(it)
        elif kind in WRONG:
            rank, title, when = WRONG[kind]
            if _is_wrong(when, pl):
                self.items.append(self._wrong(kind, pl, at, seq, rank, said(title, pl)))

    # -- shipped -------------------------------------------------------------------------------------

    def _change_action(self, what: str) -> dict[str, Any]:
        return action("change", "Report a change", path=f"/api/projects/{quote(self.p.pid, safe='')}/changes",
                      prefill=f"About {what}: ")

    def _merged(self, pl: dict[str, Any], at: str, seq: int) -> dict[str, Any]:
        pid, task, rev = self.p.pid, str(pl.get("task")), pl.get("revision")
        diff = review_diff.change(self.p, base=self.first_head.get(task), head=rev, parent_of_base=True) \
            if self.diffs else review_diff.not_measured("not read for this view")
        title = (self.tasks.get(task) or {}).get("title") or ""
        by = {"type": "agent", "name": "builder cell", "role": "builder", "model": self.model.get(task),
              "runner": self.runner.get(task) or "gnomon"}
        iid = f"{pid}/task/{task}"
        return item(iid, "shipped", "task_merged", f"{task} merged" + (f": {title}" if title else ""), self.p, at=at,
                    by=by, rank=2, record={"project": pid, "seq": seq, "kind": "merged", "task": task},
                    links=[{"label": "Task", "href": href(pid, "tasks", task)}, {"label": "Diff", "drawer": "diff"},
                           {"label": "Evidence", "href": href(pid, "evidence")},
                           {"label": "Ledger", "href": href(pid, "ledger")}],
                    actions=[action("reviewed", "Reviewed", key="r", path="/api/review/mark", body={"items": [iid]}),
                             self._change_action(f"{task} ({str(rev or '')[:12]})"),
                             action("open", "Open the task", key="o", link=href(pid, "tasks", task))],
                    task=task, verdict=pl.get("warranted"), rounds=self.rounds.get(task, 0), revision=rev,
                    permitted_by=pl.get("permitted_by"), diff=diff,
                    criteria=(self.tasks.get(task) or {}).get("criteria"))

    def _release(self, kind: str, pl: dict[str, Any], at: str, seq: int) -> None:
        pid, rel = self.p.pid, pl.get("release")
        env = str(pl.get("environment") or "")
        where = "to production" if env == "production" else "to test"
        iid = f"{pid}/release/{rel}"
        self.releases[rel] = item(
            iid, "shipped", "release", f"Release {rel} {where} ({env})", self.p, at=at,
            by={"type": "kernel", "name": "delivery", "role": "deliver"}, rank=0 if env == "production" else 1,
            record={"project": pid, "seq": seq, "kind": kind, "release": rel},
            links=[{"label": "Release", "href": href(pid, "releases")},
                   {"label": "Evidence", "href": href(pid, "evidence")}],
            actions=[action("reviewed", "Reviewed", key="r", path="/api/review/mark", body={"items": [iid]}),
                     self._change_action(f"release {rel}"),
                     action("open", "Open the releases", key="o", link=href(pid, "releases"))],
            release=rel, environment=env, where=where, revision=pl.get("revision"))

    def _output(self, pl: dict[str, Any], at: str, seq: int) -> dict[str, Any]:
        pid = self.p.pid
        iid = f"{pid}/ledger/{seq}"
        return item(iid, "shipped", "output", f"Output built: {pl.get('target')}"
                    + (f" for release {pl['release']}" if pl.get("release") else ""), self.p, at=at,
                    by=actor("output_built", pl), rank=3, record={"project": pid, "seq": seq, "kind": "output_built"},
                    links=[{"label": "Outputs", "href": href(pid, "outputs")}],
                    actions=[action("reviewed", "Reviewed", key="r", path="/api/review/mark", body={"items": [iid]}),
                             action("open", "Open the outputs", key="o", link=href(pid, "outputs"))],
                    target=pl.get("target"), file=pl.get("file"), sha256=pl.get("sha256"))

    # -- from your IDE -------------------------------------------------------------------------------

    def _commit(self, pl: dict[str, Any], at: str, seq: int) -> dict[str, Any]:
        pid, label = self.p.pid, str(pl.get("task") or "")
        head = str(pl.get("head") or "")
        task = self.tasks.get(label)
        diff = review_diff.change(self.p, base=pl.get("base"), head=head, repository=pl.get("repository")) \
            if self.diffs and pl.get("base") else review_diff.not_measured("the record names no base commit")
        what = f"{label} ({head[:12]})" if task else f"Commit {head[:12]}"
        iid = f"{pid}/gate/{seq}"
        return item(iid, "ide", "commit_gated", f"{what}: gate {pl.get('verdict')}", self.p, at=at,
                    by=actor("gate", pl) | {"via": pl.get("asked_as") or "a workspace"},
                    rank=(0 if _failed(pl) else 1) * 100_000 - seq,
                    record={"project": pid, "seq": seq, "kind": "gate"},
                    links=[{"label": "Diff", "drawer": "diff"}, {"label": "Ledger", "href": href(pid, "ledger")}]
                    + ([{"label": "Task", "href": href(pid, "tasks", label)}] if task else []),
                    actions=[action("reviewed", "Reviewed", key="r", path="/api/review/mark", body={"items": [iid]}),
                             self._change_action(what)],
                    verdict=pl.get("verdict"), signals=pl.get("signals") or {}, objections=pl.get("objections") or [],
                    criteria=(task or {}).get("criteria") or [], head=head, base=pl.get("base"),
                    repository=pl.get("repository"), diff=diff, round=pl.get("round"))

    # -- went wrong ----------------------------------------------------------------------------------

    def _wrong(self, kind: str, pl: dict[str, Any], at: str, seq: int, rank: int, title: str) -> dict[str, Any]:
        pid = self.p.pid
        links = [{"label": "Ledger", "href": href(pid, "ledger")}]
        if pl.get("task"):
            links.insert(0, {"label": "Task", "href": href(pid, "tasks", str(pl["task"]))})
        if pl.get("card"):
            links.insert(0, {"label": "Card", "href": href(pid, "inbox", str(pl["card"]))})
        if kind in ("release_failed", "rolled_back", "probe_failed", "incident_opened"):
            links.insert(0, {"label": "Release", "href": href(pid, "releases")})
        if kind == "eval_ran":           # Gnomon's audits are under Health, Audits & evals (FR-EVL1)
            links.insert(0, {"label": "Audits & evals", "href": href(pid, "checks", "evals")})
        iid = f"{pid}/ledger/{seq}"
        return item(iid, "wrong", kind, title, self.p, at=at, by=actor(kind, pl) if kind != "gate" else
                    {"type": "kernel", "name": "the gate"}, rank=rank * 100_000 - seq,
                    record={"project": pid, "seq": seq, "kind": kind}, links=links,
                    actions=[action("reviewed", "Seen", key="r", path="/api/review/mark", body={"items": [iid]}),
                             self._change_action(title),
                             action("open", "Open the record", key="o", link=links[0]["href"])],
                    detail=_why(pl), verdict=pl.get("verdict"))


def failed_jobs(jobs: list[dict[str, Any]] | None, start: str, end: str) -> list[dict[str, Any]]:
    """The cockpit's background jobs that failed in the period (the server keeps them while it runs)."""
    out = []
    for job in jobs or []:
        at = str(job.get("started") or "")
        if job.get("state") != "failed" or not start <= at <= end:
            continue
        tail = [line for line in job.get("log_tail") or [] if str(line).strip()]
        by = job.get("by") or {}
        who = {"type": "person", "name": by.get("person"), "persona": by.get("persona")} if by.get("person") \
            else {"type": "kernel", "name": "the cockpit"}
        out.append(item(f"job/{job.get('id')}", "wrong", "job_failed", f"The {job.get('kind')} job failed"
                        + (f" on {job['project']}" if job.get("project") else ""), None, at=at, by=who, rank=200_000,
                        links=[{"label": "Jobs", "href": "#/jobs"}], record={"job": job.get("id")},
                        actions=[action("open", "Open the jobs", key="o", link="#/jobs")],
                        detail=str(tail[-1])[:300] if tail else "", job_project=job.get("project")))
    return out


def _runs(projects: list[Any], start: str, end: str, heads: dict[str, int]) -> list[tuple[Any, dict[str, Any]]]:
    """The period's ``gnomon_run`` payloads, each with its project."""
    out = []
    for p in projects:
        after = heads.get(p.pid, -1)
        out += [(p, r["event"]["payload"]) for r in p.ledger().of_kind("gnomon_run")
                if start <= str(r["event"].get("at") or "") <= end and int(r.get("seq", 0)) > after]
    return out


def cost(projects: list[Any], start: str, end: str, heads: dict[str, int] | None = None) -> dict[str, Any]:
    """The period's model runs by project and role: runs, tokens and priced cost, from the ``gnomon_run``
    records (kernel/projections.py prices them). Nothing recorded: not measured, never zero."""
    from kernel.pricing import load_prices, spend

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    costs: list[Any] = []
    for p, pl in _runs(projects, start, end, heads or {}):
        role = str(pl.get("role") or "agent")
        row = rows.setdefault((p.pid, role), {"project": p.pid, "title": p.meta.get("title"), "role": role,
                                              "runs": 0, "tokens_in": 0, "tokens_out": 0, "costs": [],
                                              "tokens_measured": True})
        raw = pl.get("tokens")
        tokens: dict[str, Any] = raw if isinstance(raw, dict) else {}
        row["runs"] += 1
        row["tokens_measured"] = row["tokens_measured"] and tokens.get("in") is not None \
            and tokens.get("out") is not None
        row["tokens_in"] += int(tokens.get("in") or 0)
        row["tokens_out"] += int(tokens.get("out") or 0)
        row["costs"].append(pl.get("cost"))
        costs.append(pl.get("cost"))
    if not rows:
        return {"measured": False, "why": "no model run was recorded in this period", "rows": []}
    out = []
    for row in rows.values():
        out.append({k: v for k, v in row.items() if k != "costs"} | {"spend": spend(row.pop("costs"))})
    return {"measured": True, "rows": sorted(out, key=lambda r: (r["project"], r["role"])), "total": spend(costs),
            "runs": sum(r["runs"] for r in out), "currency": load_prices().get("currency", "USD")}
