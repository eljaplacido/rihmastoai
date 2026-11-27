"""The Alignment view's triage: what to do with many items to decide, from the real state (FR-ORG1).

The owner (2026-11-26): "Code plan highlights 124 to decide, how do I know what should I do with these results? ...
Do I just spend accepting changes that forces project to rihmasto structure or actually moving the needle with dev.
Ofc I can enforce those where I should if beneficial, but not blindsided".

`enrich` adds to the view (kernel/alignment_records.py ``view``) by rule, writing nothing:

- each item's **origin** (kernel/alignment_origin.py) and its **impact line** (kernel/alignment_impact.py), whether
  it is **deferred**, and each group's counts by origin; each suggested change's origin and impact;
- the **triage head**: how many items to decide come from the project and how many from Rihmasto's convention,
  which may be from an old plan, a recommendation in plain words, and the actions, each with its impact:
  **Reject stale** (the open items of planning files much older than the code), **Defer convention items** (set
  aside, one click from coming back), **Accept from current sources** (the project's own items from files that are
  not behind the code, but test traces too weak to take unseen).

`act` does one of them, signed by a person: rejecting and accepting go through ``decide`` (the contract, the
records, the ledger); deferring is kept in `alignment/deferred.json` with `alignment_deferred` in the ledger, and
Bring back undoes it (`alignment_restored`). The repository is never written.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from kernel import alignment_advice as adv
from kernel import alignment_evidence as ev
from kernel import alignment_impact as imp
from kernel import alignment_origin as org
from kernel import alignment_records as ar
from kernel import alignment_suggest as sg
from kernel.attach import check_signer
from kernel.store import Project, updating_json

DEFERRED = "alignment/deferred.json"
ACTIONS = ("reject_stale", "defer_convention", "accept_current", "defer", "restore")
LABELS = {"reject_stale": "Reject stale", "defer_convention": "Defer convention items",
          "accept_current": "Accept from current sources", "restore": "Bring back deferred"}
CONTRACT_GROUPS = ("requirements", "criteria")


def deferred(project: Project) -> dict[str, dict[str, Any]]:
    return project.read(DEFERRED, {}) or {}


_plural = imp._plural


# -- the view --------------------------------------------------------------------------------------------

def _set_of(i: dict[str, Any]) -> str:
    """Which part of the triage an open, not deferred item is in: convention, risk (a convention that may be a real
    risk), stale, weak, dangling (a test trace to a rejected criterion) or current."""
    o = i["origin"]
    if o["kind"] == org.CONVENTION:
        return "risk" if o.get("risk") else "convention"
    if i.get("criterion_status") == "rejected":
        return "dangling"
    return "stale" if o.get("old") else "weak" if i.get("weak") else "current"


SETS = ("convention", "risk", "stale", "weak", "dangling", "current")


def _sets(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    live = [i for i in items if i["status"] == "open" and not i.get("deferred")]
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in SETS}
    for i in live:
        out[_set_of(i)].append(i)
    return out | {"open": live, "deferred": [i for i in items if i.get("deferred") and i["status"] == "open"],
                  "changed": [i for i in items if i["status"] == "changed"]}


def _by_group(items: list[dict[str, Any]]) -> str:
    c = Counter(i["group"] for i in items)
    return ", ".join(f"{n} {ar.al.GROUP_LABEL[g].lower().replace('api ', 'API ')}" for g, n in c.most_common())


def _conventions(items: list[dict[str, Any]]) -> str:
    c = Counter(i["origin"]["rule_said"] for i in items)
    return "; ".join(f"{n} by \"{rule}\"" for rule, n in c.most_common())


def _stale_files(items: list[dict[str, Any]]) -> str:
    files = {i["origin"]["path"]: i["origin"]["days_behind"] for i in items}
    return ", ".join(f"{p} ({d} days behind the code)" for p, d in sorted(files.items())[:4]) \
        + (f" and {len(files) - 4} more" if len(files) > 4 else "")


def _advice(s: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    conv = s["convention"]
    if conv:
        loose = sum(len(i["proposal"]["refs"]) for i in conv if i.get("kind") == "no_requirement")
        out.append({"do": "defer_convention", "text": (
            f"Leave the {_plural(len(conv), 'item')} of Rihmasto's convention for now ({_conventions(conv)}). They say "
            "how Rihmasto would keep the project; none of them is a defect found in your code"
            + (f"; the {_plural(loose, 'test')} that trace{'s' if loose == 1 else ''} to no requirement close once "
               "your project's own tests are mapped to its requirements (accept the test traces, or name tests after "
               "their criteria)"
               if loose else "")
            + ". Defer them to clear the list: they stay one click away (deciding the requirement one belongs to "
              "decides it too, and its impact says so first), and you enforce the ones worth it.")})
    if s["stale"]:
        out.append({"do": "reject_stale", "text": (
            f"{_plural(len(s['stale']), 'item')} ({_by_group(s['stale'])}) come from planning files committed long "
            f"before the code's latest change: {_stale_files(s['stale'])}. They may describe an old plan: reject "
            "them, or wait for the current plan and read the repository again.")})
    if s["current"]:
        out.append({"do": "accept_current", "text": (
            f"Accept the {_plural(len(s['current']), 'item')} from current sources ({_by_group(s['current'])}): they "
            "record what your project already says. Your repository is never written."
            + (f" Look at the {_plural(len(s['weak']), 'weak test trace')} one by one." if s["weak"] else ""))})
    out += adv.dangling(s["dangling"])
    if not out and not s["risk"]:
        out.append({"do": None, "text": "Nothing left to decide" + (
            f": {_plural(len(s['deferred']), 'item')} deferred, Bring back to look again." if s["deferred"] else
            ". Read the repository again after it changes: the drift shows what is new.")})
        return out
    return adv.development(s) + adv.risks(s["risk"]) + out


def _actions(project: Project, s: dict[str, list[dict[str, Any]]], ctx: imp.Context) -> list[dict[str, Any]]:
    want = {"reject_stale": ("stale", "reject"), "defer_convention": ("convention", "defer"),
            "accept_current": ("current", "accept"), "restore": ("deferred", None)}
    out = []
    for do, (key, verdict) in want.items():
        ids = [i["id"] for i in s[key]]
        if not ids:
            continue
        said = (imp.impact(project, ids, verdict, ctx)["said"] if verdict else
                f"{_plural(len(ids), 'deferred item')} back in the list to decide. Nothing else changes.")
        out.append({"do": do, "label": LABELS[do], "count": len(ids), "items": ids, "impact": said})
    return out


def head(project: Project, items: list[dict[str, Any]], ctx: imp.Context) -> dict[str, Any]:
    """The triage at the top of the view: counts by origin, a recommendation and its actions."""
    s = _sets(items)
    n = len(s["open"])
    conv, risk = len(s["convention"]), len(s["risk"])
    said = (f"{n} to decide: {n - conv - risk} taken from your project "
            f"({len(s['stale'])} may be from an old plan), {conv + risk} by Rihmasto's convention"
            + (f" ({risk} may be a real risk)" if risk else "")
            + (f"; {len(s['deferred'])} deferred" if s["deferred"] else "")
            + (f"; {len(s['changed'])} changed since accepted" if s["changed"] else "") + ".")
    return {"to_decide": n, "project": n - conv - risk, "convention": conv, "risk": risk,
            "stale": len(s["stale"]), "current": len(s["current"]), "weak": len(s["weak"]),
            "dangling": len(s["dangling"]), "deferred": len(s["deferred"]), "changed": len(s["changed"]),
            "said": said, "advice": _advice(s), "actions": _actions(project, s, ctx)}


def _item(i: dict[str, Any], ctx: imp.Context, shut: list[str], shown: dict[str, str], later: dict[str, Any]) -> None:
    """One item's origin (with the current tests' evidence), its closing by a rejection, its impact line and its
    deferral (FR-ORG1, FR-ORG2)."""
    i["origin"] = ctx.origin(i["id"])
    i["origin_tags"] = org.tags(i["origin"])
    if shut:                                      # a gap about what a person rejected is closed (FR-ORG2)
        i["status"], i["closed_by"] = "closed", shut
        i["closed_said"] = (f"Closed: it is about {', '.join(shut)}, which you rejected. Accept "
                            f"{'it' if len(shut) == 1 else 'them'} again and the gap opens again.")
    if i["group"] == "trace":
        i["criterion_status"] = shown.get(i["proposal"]["criterion"])
    i["impact"] = imp.line(ctx, i)
    if i["id"] in later and i["status"] == "open":
        i["deferred"] = {k: later[i["id"]][k] for k in ("person", "at")}


def _suggestions(project: Project, raw: list[dict[str, Any]], structure: dict[str, Any], ctx: imp.Context
                 ) -> list[dict[str, Any]]:
    """The suggested changes about what nobody rejected; a spec's suggestion names the specs it edits (FR-ORG2)."""
    out = sg.suggestions({"items": ev.about_kept(raw, ctx.decided)}, structure)
    for s in out:
        s["files"] = ev.suggestion_files(s, raw)
        s["origin"] = org.of_suggestion(s)
        s["impact"] = imp.of_suggestion(project, s)
    return out


def recount(project: Project, view: dict[str, Any]) -> None:
    """The triage head and the status chips again for what is left to decide once Rihmasto's conventions follow
    their levels: one at Advise is a suggestion and one at Off is hidden, neither counted (kernel/structure_policy.py,
    FR-STR1), so the head, the chips and the policy line give the same number (FR-ORG2)."""
    found = project.read(ar.SCAN)
    if not found or "triage" not in view:
        return
    counted = [i for g in view["groups"] for i in g["items"] if not i.get("folded")]
    view["triage"] = head(project, counted, imp.Context(project, found)) | {"filters": ev.filters(counted)}
    view["status"] = dict(view["status"], open=view["triage"]["to_decide"], deferred=view["triage"]["deferred"])


def enrich(project: Project, out: dict[str, Any], found: dict[str, Any]) -> dict[str, Any]:
    """The view with each item's origin, impact line and deferral, group counts by origin and the triage head."""
    structure = found["structure"]
    newest = org.code_newest(structure)
    ctx = imp.Context(project, found)
    later = deferred(project)
    raw = found["proposal"]["items"]
    index = {i["id"]: i for i in raw}
    no = ev.rejected(ctx.decided)
    shown = {i["id"]: i["status"] for g in out["groups"] for i in g["items"]}
    every = []
    for g in out["groups"]:
        for i in g["items"]:
            _item(i, ctx, ev.closed_by(i, index, no) if i["status"] == "open" else [], shown, later)
        live = [i for i in g["items"] if i["status"] in ("open", "changed") and not i.get("deferred")]
        g["origins"] = org.counts(live)
        g["deferred"] = sum(1 for i in g["items"] if i.get("deferred"))
        g["open"] = len(live)
        every += g["items"]
    out["suggestions"] = _suggestions(project, raw, structure, ctx)
    out["triage"] = head(project, every, ctx)
    out["triage"]["filters"] = ev.filters(every)     # each filter counts the rows it shows (FR-ORG2)
    # one number to decide: open and not deferred; deferred and closed counted apart (FR-ORG2)
    out["status"] = {st: sum(1 for i in every if i["status"] == st) for st in (*ar.STATUSES, "closed")}
    out["status"]["open"] = out["triage"]["to_decide"]
    out["status"]["deferred"] = out["triage"]["deferred"]
    out["origin_rules"] = {"old_days": org.OLD_DAYS, "code_date": org.day(newest),
                           "said": f"An item from a planning file committed {org.OLD_DAYS} or more days before the "
                                   "code's latest change may be from an old plan."}
    return out


# -- acting ----------------------------------------------------------------------------------------------

def _defer(project: Project, ids: list[str], *, person: str, persona: str, undo: bool, scan: int) -> list[str]:
    at = project.factory.clock.stamp()
    with updating_json(project.path(DEFERRED), {}) as book:
        done = [i for i in ids if (i in book) == undo]
        for i in done:
            if undo:
                book.pop(i)
            else:
                book[i] = {"person": person, "persona": persona, "at": at, "scan": scan}
    project.log("alignment_restored" if undo else "alignment_deferred",
                {"items": done, "person": person, "persona": persona, "scan": scan,
                 "note": "set aside, not decided: nothing went into the contract or the records; the repository "
                         "was not written" if not undo else "back in the list to decide"})
    return done


def _offered(view: dict[str, Any], do: str, items: list[str] | None) -> list[str]:
    """What the action would take now: the triage's own items, or for Defer every open item not deferred."""
    every = [i for g in view["groups"] for i in g["items"]]
    unknown = sorted(set(items or []) - {x["id"] for x in every})
    if unknown:
        raise ar.AlignRefused(f"no item {', '.join(unknown)} in scan {view['scan']['n']}")
    if do == "defer":
        if not items:
            raise ar.AlignRefused("name the items to defer")
        return [i["id"] for i in every if i["status"] == "open" and not i.get("deferred")]
    return next((a["items"] for a in view["triage"]["actions"] if a["do"] == do), [])


def _ids(view: dict[str, Any], do: str, items: list[str] | None) -> tuple[list[str], list[str]]:
    """The items an action takes, and those named that it skips. Named items (a proposal of Ask Rihma carries the
    ones its impact was said for, FR-ORG2) are taken only while the action would still take them: an item decided,
    deferred or closed since is skipped, and said."""
    offered = _offered(view, do, items)
    asked = list(dict.fromkeys(items)) if items else offered
    take = [i for i in asked if i in set(offered)]
    skipped = [i for i in asked if i not in set(offered)]
    if not take:
        raise ar.AlignRefused(
            f"nothing left of the {_plural(len(asked), 'item')} proposed: decided, deferred or closed since; read the "
            "Alignment view again" if skipped else
            f"nothing to {LABELS.get(do, do).lower()} now: the triage has no such items")
    return take, skipped


def _skipped(skipped: list[str], asked: int) -> str:
    return (f"; {len(skipped)} of the {asked} proposed {'was' if len(skipped) == 1 else 'were'} skipped: decided, "
            "deferred or closed since they were proposed" if skipped else "")


REASONS = {"reject_stale": "from a planning file much older than the code: may be an old plan",
           "accept_current": "from the project's current sources"}


def _decided(project: Project, do: str, ids: list[str], groups: dict[str, str], *, person: str, persona: str
             ) -> tuple[list[str], str | None]:
    """Reject or accept through the alignment's decide: the contract's items first, in one write, then the rest."""
    verdict = "reject" if do == "reject_stale" else "accept"
    firm = [i for i in ids if verdict == "accept" and groups[i] in CONTRACT_GROUPS]
    decided: list[str] = []
    contract = None
    for part in (p for p in (firm, [i for i in ids if i not in firm]) if p):
        out = ar.decide(project, part, verdict, person=person, persona=persona, reason=REASONS[do])
        decided += out["items"]
        contract = out.get("contract") or contract
    return decided, contract


def act(project: Project, do: str, *, person: str, persona: str, items: list[str] | None = None) -> dict[str, Any]:
    """One triage action, signed: reject_stale, defer_convention, accept_current, restore (every deferred item, or
    those named), defer (the items named)."""
    check_signer(person, persona)
    if do not in ACTIONS:
        raise ar.AlignRefused(f"the triage action is one of {', '.join(ACTIONS)}, got {do!r}")
    view = ar.view(project)
    if not view.get("scanned"):
        raise ar.AlignRefused(f"{project.pid} has not been aligned yet: read the repository first")
    ids, skipped = _ids(view, do, items)
    gone = _skipped(skipped, len(ids) + len(skipped))
    if do in ("defer_convention", "defer", "restore"):
        done = _defer(project, ids, person=person, persona=persona, undo=do == "restore", scan=view["scan"]["n"])
        said = (f"{'Brought back' if do == 'restore' else 'Deferred'} {_plural(len(done), 'item')}, signed by {person}"
                f"{gone}.")
        return {"project": project.pid, "done": do, "items": done, "skipped": skipped, "said": said,
                "alignment": ar.view(project)}
    groups = {i["id"]: g["id"] for g in view["groups"] for i in g["items"]}
    decided, contract = _decided(project, do, ids, groups, person=person, persona=persona)
    said = (f"{'Rejected' if do == 'reject_stale' else 'Accepted'} {_plural(len(decided), 'item')}, signed by {person}"
            + (f"; the contract is now {contract}" if contract else "") + gone + ". Your repository was not written.")
    return {"project": project.pid, "done": do, "items": decided, "skipped": skipped, "contract": contract,
            "said": said, "alignment": ar.view(project)}
