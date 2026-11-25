"""An assessment's findings into the change loop, and the assessment as the cockpit, the MCP server and the
evidence pack read it (kernel/assess.py).

- **A person chooses.** `to_changes` files each chosen finding, a rule's (F-n) or the panel's (P-n), as a
  change card signed by that person: its text names the assessment, the revision, the perspective, the
  severity, who found it (the rules, or the panel's model as an opinion) and its evidence, and ends with the
  suggested change. The card carries its origin (`refs.origin: "assessment"`, and `payload.origin` with the
  assessment, the finding and its key), and is triaged by rule like any change, as a new requirement unless
  the person names another class: a new requirement waits on a business decision, so nothing is built
  until a person who decides changes accepts it.
- **Once per open card.** `filed.json` keeps the card each finding's key was filed as. A finding whose card
  is still open is skipped and says so; once that card is decided, the finding may be filed again.
- **In the ledger.** Each card is `assessment_change_opened`, with the finding, its key, who filed it and
  the class triage gave it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from kernel.assess import (
    CLASS_DEFAULT,
    FOLDER,
    AssessmentRefused,
    _check_asker,
    checked,
    finding_line,
    history,
    intact,
    is_adopted,
    load,
    summary,
)
from kernel.assess_repo import PERSPECTIVES, SEVERITIES
from kernel.store import read_json, updating_json

MAX_IDS = 50


def card_text(record: dict[str, Any], f: dict[str, Any]) -> str:
    """The change a finding asks for, in words a person decides on: its first line is the card's title."""
    line = finding_line(f)
    by = ("the rules (a measured fact)" if f.get("by") == "rule" else
          f"the panel's {str(f.get('panel', '')).replace('_', ' ')} perspective (model_proposed: an opinion, "
          "not a fact)")
    lines = [f"{f['title']} [{record['id']} {f['id']}]", "",
             f"From assessment {record['id']} of revision {record['revision'][:12]}: finding {f['id']}, "
             f"{PERSPECTIVES.get(f['perspective'], f['perspective'])}, severity {f.get('severity')}, found by {by}."]
    lines += [f"Found: {line['summary']}."] if line.get("summary") else []
    lines += [f"Why: {line['why']}"] if line.get("why") else []
    if line["evidence"]:
        lines += ["", "Evidence:", *(f"- {e}" for e in line["evidence"])]
    lines += ["", f"Suggested change: {f.get('suggestion') or 'not given'}"]
    return "\n".join(lines)


def _by_id(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {c["id"]: c for c in record["checks"] if c.get("id")}
    return out | {p["id"]: p for p in record.get("proposals") or []}


def _state(canon: Any, card_id: str) -> str | None:
    try:
        return str(canon.get_card(card_id)["state"])
    except KeyError:
        return None


def _open_card(project: Any, record: dict[str, Any], f: dict[str, Any], *, person: str, persona: str,
               as_class: str) -> dict[str, Any]:
    from kernel.canon import Canon
    from kernel.change import submit, triage

    card = submit(project, persona=persona, person=person, text=card_text(record, f), kind_hint=as_class)
    origin = {"kind": "assessment", "assessment": record["id"], "finding": f["id"], "key": f["key"],
              "by": f.get("by"), "revision": record["revision"]}
    with Canon(project).edit_card(card["id"]) as c:
        c["refs"].update(origin="assessment", assessment=record["id"], finding=f["id"])
        c["payload"]["origin"] = origin
    routed = triage(project, card["id"], model=None)
    out = {"finding": f["id"], "card": card["id"], "class": routed.get("class"),
           "needs_decision": routed.get("needs_decision"), "way_back": routed.get("way_back")}
    project.log("assessment_change_opened", {**origin, "card": card["id"], "person": person, "persona": persona,
                                             "class": out["class"], "needs_decision": out["needs_decision"]})
    return out


def _wanted(ids: Iterable[str]) -> list[str]:
    wanted = list(dict.fromkeys(str(i).strip().upper() for i in ids if str(i).strip()))
    if not wanted:
        raise AssessmentRefused(f"name between 1 and {MAX_IDS} findings (F-1, P-2 and so on)")
    if len(wanted) > MAX_IDS:
        # Ticking every finding of a large assessment is normal; say the count, so it does not read
        # as a bad finding ID (the cockpit files in batches of MAX_IDS)
        raise AssessmentRefused(f"{len(wanted)} findings were named, and at most {MAX_IDS} are filed at a time: "
                                f"file them in batches of {MAX_IDS} or fewer")
    return wanted


def to_changes(project: Any, ids: Iterable[str], *, person: str, persona: str, version: int | str | None = None,
               as_class: str = CLASS_DEFAULT) -> dict[str, Any]:
    """File each chosen finding of an assessment (the latest by default) as a change card signed by
    ``person``; skip one whose earlier card is still open. Returns what was opened and what was skipped."""
    from kernel.canon import Canon
    from kernel.change import CLASSES

    _check_asker(person, persona)
    if as_class not in CLASSES:
        raise AssessmentRefused(f"a change is filed as one of {', '.join(CLASSES)}, not {as_class!r}")
    wanted = _wanted(ids)
    record = load(project, version)
    found = _by_id(record)
    unknown = [i for i in wanted if i not in found]
    if unknown:
        raise AssessmentRefused(f"no finding {', '.join(unknown)} in {record['id']}: its findings are "
                                f"{', '.join(found) or 'none'}")
    opened, skipped = [], []
    canon = Canon(project)
    for fid in wanted:
        f = found[fid]
        with updating_json(project.path(FOLDER, "filed.json"), {}) as filed:
            earlier = filed.get(f["key"])
            if earlier and _state(canon, earlier["card"]) == "open":
                skipped.append({"finding": fid, "card": earlier["card"], "why": "its change card is still open"})
                continue
            card = _open_card(project, record, f, person=person, persona=persona, as_class=as_class)
            filed[f["key"]] = {"card": card["card"], "assessment": record["id"], "finding": fid,
                               "person": person, "at": project.factory.clock.stamp()}
            opened.append(card)
    return {"assessment": record["id"], "opened": opened, "skipped": skipped}


def filed(project: Any) -> dict[str, Any]:
    """Each finding's key with the card it was filed as, and that card's state now."""
    from kernel.canon import Canon

    canon, out = Canon(project), {}
    for key, entry in (read_json(project.path(FOLDER, "filed.json"), {}) or {}).items():
        out[key] = dict(entry, state=_state(canon, entry.get("card", "")))
    return out


def view(project: Any) -> dict[str, Any]:
    """The assessment as the cockpit shows it: the latest record, every version (each checked against the
    sha256 in the ledger), what each finding was filed as, and whether the project has a repository to assess."""
    index = history(project)
    try:
        latest, problem = (load(project) if index else None), None
    except LookupError as exc:
        latest, problem = None, str(exc.args[0] if exc.args else exc)
    return {"project": project.pid, "adopted": is_adopted(project), "has_repo": project.path("repo.git").is_dir(),
            "perspectives": PERSPECTIVES, "severities": list(SEVERITIES),
            "history": checked(project),
            "latest": latest, "problem": problem, "filed": filed(project)}


def for_evidence(project: Any) -> dict[str, Any]:
    """What an evidence pack carries: the latest assessment in short, and every version with its sha256
    and whether the record still matches it."""
    index = history(project)
    if not index:
        return {"note": "no assessment recorded"}
    latest = load(project)
    return {"latest": summary(latest) | {"trace": latest.get("trace")},
            "history": checked(project)}


def evidence_line(project: Any) -> str:
    """The evidence pack README's line for the assessment."""
    index = history(project)
    if not index:
        return "no assessment recorded"
    e = index[-1]
    sev = ", ".join(f"{n} {s}" for s, n in (e.get("counts") or {}).get("by_severity", {}).items() if n)
    return (f"{e['id']} of revision {str(e['revision'])[:12]} ({len(index)} version(s)): "
            f"{(e.get('counts') or {}).get('findings', 0)} finding(s) by rule{' (' + sev + ')' if sev else ''}, "
            f"{(e.get('counts') or {}).get('proposed', 0)} proposed by the panel's model and kept apart; "
            f"record {'intact' if intact(project, e) else 'CHANGED since recorded'}")


__all__ = ["MAX_IDS", "card_text", "evidence_line", "filed", "for_evidence", "to_changes", "view"]
