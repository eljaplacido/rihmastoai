"""The delivery report: what a business owner reads at the end of a project, in plain language, as HTML and
Markdown (the `report` output of kernel/outputs.py).

It says what was asked and by whom, what was built, the decisions and who made them, what was assumed
and whether it was confirmed, the evidence in plain words (verified, claimed, held out, failing, not
measured), how to try it, what it cost where that was measured, and the known limits and next steps.
Every statement carries the record it rests on: a ledger number, a decision, an assumption, a criterion
or a release. Nothing is a model's summary: the kernel writes it from the records, so the same records
always give the same report.

"Not measured" stays "not measured": a criterion nothing checked is never counted as passed, and a cost
nobody priced is never shown as zero. A holdout scenario's content never appears; only its criterion's
state does (kernel/custody.py).
"""

from __future__ import annotations

import html
import re
from typing import Any

from kernel.canon import Canon
from kernel.custody import custody_safe
from kernel.notices import PERSONA_LABEL
from kernel.store import MATURITIES, STAGES

Item = tuple[str, str]  # a statement, and the record it rests on
# Records an output build appends: the report is the same however often outputs were built.
IGNORED = ("output_built", "evidence_exported", "cockpit_write")
PROVENANCE_WORDS = {
    "customer-confirmed": "confirmed by the customer",
    "customer-endorsed": "as the person who asked put it",
    "assumption": "resting on an assumption",
    "vendor-proposed": "proposed by the factory, not confirmed by a person",
    "withdrawn": "withdrawn",
}
EVIDENCE_WORDS = {
    "verified": "verified: a gate passed at the merged revision, and a test on main names it",
    "claimed": "claimed: a test names it, but no passing gate proved it",
    "held_out": "held out: a scenario the builder never saw passed against a release",
    "failing": "failing: its check fails",
    "not_measured": "not measured: nothing has checked it yet",
}
EVIDENCE_ORDER = ("verified", "held_out", "claimed", "failing", "not_measured")
MATURITY_WORDS = dict(zip(MATURITIES, ("a walking skeleton to explore the idea", "a demo for the owner to try",
                                       "a pilot real users try on staging", "a production service"), strict=True))
SECTIONS = ("What was asked, and by whom", "What was built", "Decisions, and who made them",
            "What was assumed, and whether it was confirmed", "The evidence, in plain words", "How to try it",
            "What it cost, where it was measured", "Known limits, and next steps")


def _who(person: Any, persona: Any) -> str:
    return f"{person} ({PERSONA_LABEL.get(str(persona), persona)})" if persona else str(person)


def _seqs(project: Any) -> dict[str, list[int]]:
    """Ledger numbers by kind, the records an output build appends left out."""
    out: dict[str, list[int]] = {}
    for rec in project.ledger().records():
        kind = rec.get("event", {}).get("kind") if isinstance(rec, dict) else None
        if kind and kind not in IGNORED:
            out.setdefault(kind, []).append(int(rec.get("seq", -1)))
    return out


def _ref(seqs: dict[str, list[int]], kind: str, last: bool = False) -> str:
    found = seqs.get(kind) or []
    return f"ledger #{found[-1 if last else 0]} {kind}" if found else "no ledger record"


def _asked(project: Any, seqs: dict, outputs: dict) -> list[Item]:
    meta, source = project.meta, project.read("source.json", {}) or {}
    who = source.get("requested_by") or meta.get("requested_by")
    text = " ".join(str(source.get("text", "")).split())
    items: list[Item] = [(f"{who or 'Nobody named'} asked for **{meta.get('title')}**"
                          + (f": \"{text[:600]}{'...' if len(text) > 600 else ''}\"" if text else "."),
                          "source.json; " + _ref(seqs, "project_created"))]
    profile = meta.get("profile") or "web_service"
    items.append((f"It was taken as {profile.replace('_', ' ')} work at **{meta.get('maturity')}** maturity: "
                  f"{MATURITY_WORDS.get(meta.get('maturity'), meta.get('maturity'))}.",
                  _ref(seqs, "profile_chosen", True)))
    if outputs.get("chosen"):
        by = outputs.get("chosen_by") or {}
        items.append((f"{_who(by.get('by'), by.get('persona'))} chose what it delivers: "
                      f"{', '.join(outputs['chosen'])}.", _ref(seqs, "outputs_chosen", True)))
    else:
        items.append(("Nobody has chosen what it delivers yet; its work profile proposes "
                      f"{', '.join(outputs.get('proposed') or []) or 'nothing'}.", "outputs.json: none yet"))
    return items


def _built(project: Any, rel: dict | None, contract: dict) -> list[Item]:
    stage = project.meta.get("stage", 1)
    if rel is None:
        return [(f"Nothing has been released yet. The project is at stage {stage}, "
                 f"{STAGES.get(stage, '?')}.", "project.json")]
    n = rel.get("release")
    envs = ", ".join(rel.get("environments") or []) or "no environment"
    items: list[Item] = [(f"Release {n} took the product at revision `{str(rel.get('revision'))[:12]}` to {envs}; "
                          f"it is {str(rel.get('state')).replace('_', ' ')}.", f"release {n}")]
    merged = sorted(t for t, s in (rel.get("tasks") or {}).items() if s == "merged")
    if merged:
        items.append((f"{len(merged)} build task(s) passed the gate and were merged: {', '.join(merged)}.",
                      f"release {n}"))
    for r in contract.get("requirements") or []:
        if r.get("provenance") == "withdrawn":
            continue
        items.append((f"{r['id']}: {r['statement']} ({PROVENANCE_WORDS.get(r.get('provenance'), r.get('provenance'))})",
                      f"contract {str(contract.get('revision', ''))[:19]}"))
    return items


def _decisions(canon: Canon) -> list[Item]:
    items: list[Item] = []
    for d in canon.decisions():
        what = f"{d.get('verdict')} on the {str(d.get('kind')).replace('_', ' ')}" + (
            f" {d['card']}" if d.get("card") else "")
        reason = custody_safe(str(d.get("reason") or "").strip())
        stale = " It no longer holds: a requirement it rested on changed." if d.get("stale") else ""
        items.append((f"{_who(d.get('person'), d.get('persona'))} decided {what} on {str(d.get('at'))[:10]}"
                      + (f": \"{reason[:300]}\"" if reason else ".") + stale, f"decision {d.get('id')}"))
    return items or [("No decision has been recorded yet.", "canon/decisions.json")]


def _assumptions(canon: Canon) -> list[Item]:
    items: list[Item] = []
    for a in canon.assumptions():
        settled = a.get("settled") or {}
        if a.get("status") == "confirmed":
            state = f"confirmed by {_who(settled.get('by'), settled.get('persona'))} on {str(settled.get('at'))[:10]}"
        elif a.get("status") == "refuted":
            state = (f"refuted by {_who(settled.get('by'), settled.get('persona'))}: "
                     f"\"{str(settled.get('correction') or '')[:300]}\"")
        else:
            state = f"not confirmed yet: a person should confirm or refute it by {a.get('due')}"
        items.append((f"Assumed: \"{a.get('text')}\". {state[0].upper() + state[1:]}.", f"assumption {a.get('id')}"))
    return items or [("Nothing was assumed: every question was answered by a person.", "canon/assumptions.json")]


def _proof(row: dict) -> str:
    """Where a criterion's evidence comes from: the gate that proved it, the release a holdout ran on."""
    first = (row.get("evidence") or [{}])[0]
    if first.get("kind") == "gate":
        return f"{row['criterion']}, gate of {first.get('task')}"
    if first.get("kind") == "holdout":
        return f"{row['criterion']}, release {first.get('release')}"
    return f"{row['criterion']}, criterion"


def _evidence(project: Any) -> tuple[list[Item], dict[str, int]]:
    from kernel.status import evidence

    rows = evidence(project) if project.path("contract.json").exists() else []
    counts = {k: sum(1 for r in rows if r["state"] == k) for k in EVIDENCE_ORDER}
    if not rows:
        return [("No criterion exists yet, so nothing can be shown as checked.", "contract.json: none yet")], counts
    shown = [k for k in EVIDENCE_ORDER if counts[k]]
    words = " ".join(f"*{EVIDENCE_WORDS[k].split(':')[0]}* means{EVIDENCE_WORDS[k].split(':', 1)[1]}." for k in shown)
    items: list[Item] = [(f"Of {len(rows)} acceptance criteria: "
                          f"{', '.join(str(counts[k]) + ' ' + k.replace('_', ' ') for k in shown)}. {words}",
                          "kernel.status.evidence over the ledger's gates and the releases")]
    then = {c["id"]: c["then"] for r in (project.read("contract.json") or {}).get("requirements", [])
            for c in r.get("acceptance", [])}
    items += [(f"{row['criterion']}: {then.get(row['criterion'], '')}: **{row['state'].replace('_', ' ')}**.",
               _proof(row)) for row in rows]
    return items, counts


def _security(project: Any) -> Item:
    from kernel.security import summary

    sec = summary(project)
    if sec.get("verdict") == "not measured":
        return f"Security: not measured ({sec.get('note')}).", "security/: no scan"
    open_counts = ", ".join(f"{n} {level}" for level, n in sorted((sec.get("open") or {}).items()) if n) or "none open"
    return (f"Security: the security gate says {sec.get('verdict')}; findings {open_counts}; "
            f"{len(sec.get('accepted_risks') or [])} risk(s) accepted by a person.", "security/ scans")


def _try(project: Any, rel: dict | None) -> list[Item]:
    from kernel.status import try_it

    if rel is None:
        return [("There is nothing to try until a release lands.", "releases/: none yet")]
    t = try_it(project)
    items: list[Item] = []
    if t.get("url"):
        items.append((f"Release {t.get('release')} ran on {t.get('env')} at {t['url']}; it may have been "
                      "stopped since.", f"release {t.get('release')}"))
    items.append(("To run it yourself, a developer asks for the container output; an integrator, the API "
                  "description.", "outputs.json"))
    for it in (t.get("items") or [])[:12]:
        items.append((it["text"], it["criterion"]))
    return items


def _cost(project: Any, seqs: dict) -> list[Item]:
    from kernel.pricing import load_prices, spend
    from kernel.projections import cell

    runs = cell(project)
    if not runs:
        return [("Not measured: no model run was recorded, so nothing was priced.", "no gnomon_run in the ledger")]
    s = spend([r.get("cost") for r in runs])
    where = f"{len(runs)} model run(s); " + _ref(seqs, "gnomon_run")
    if s["cloud"] is None:
        return [(f"Not measured: {s['unmeasured_runs']} of {len(runs)} model runs had no price, so the cloud total is "
                 f"unknown (the priced part is {s['cloud_measured_part']} {load_prices().get('currency', 'USD')}).",
                 where)]
    return [(f"Cloud models cost {s['cloud']} {load_prices().get('currency', 'USD')}; local models used "
             f"{s['local_tokens']} tokens.", where)]


def _limits(project: Any, canon: Canon, counts: dict[str, int], outputs: dict) -> list[Item]:
    items: list[Item] = [(f"Waiting on a person: {c['id']} ({c['kind'].replace('_', ' ')}), "
                          f"\"{custody_safe(c['title'])}\".", f"card {c['id']}") for c in canon.cards()]
    open_assumptions = canon.assumptions("open")
    if open_assumptions:
        items.append((f"{len(open_assumptions)} assumption(s) still wait for a person to confirm them.",
                      "canon/assumptions.json"))
    for state, words in (("not_measured", "are not measured: no gate or release has checked them"),
                         ("claimed", "are claimed only: a test names them, no gate proved them"),
                         ("failing", "fail their checks")):
        if counts.get(state):
            items.append((f"{counts[state]} criteria {words}.", "kernel.status.evidence"))
    items += [(f"The {t['label']} output was chosen and is planned, not built yet.", "outputs.json")
              for t in outputs.get("targets", []) if t.get("chosen") and t.get("status") == "planned"]
    return items or [("Nothing known is open.", "canon/: no open card")]


def sections(project: Any, rel: dict | None, outputs: dict) -> list[tuple[str, list[Item]]]:
    """The report's sections, each a list of (statement, record) pairs, from the project's records."""
    canon, seqs = Canon(project), _seqs(project)
    contract = project.read("contract.json") or {}
    evidence_items, counts = _evidence(project)
    bodies = [_asked(project, seqs, outputs), _built(project, rel, contract), _decisions(canon),
              _assumptions(canon), evidence_items + [_security(project)], _try(project, rel), _cost(project, seqs),
              _limits(project, canon, counts, outputs)]
    return list(zip(SECTIONS, bodies, strict=True))


def _as_of(project: Any) -> int:
    seqs = [n for found in _seqs(project).values() for n in found]
    return max(seqs) if seqs else -1


def markdown(project: Any, rel: dict | None, outputs: dict) -> str:
    """The report in Markdown."""
    head = (f"# Delivery report: {project.meta.get('title')}\n\nProject `{project.pid}`"
            + (f", release {rel.get('release')}" if rel else ", no release yet")
            + f". Written by Rihmasto's kernel from the project's records, up to ledger #{_as_of(project)}; each "
            "line names the record it rests on.\n")
    parts = [head]
    for title, items in sections(project, rel, outputs):
        parts.append(f"\n## {title}\n\n" + "".join(f"- {text} *({ref})*\n" for text, ref in items))
    return "".join(parts)


CSS = ("body{font:16px/1.55 system-ui,sans-serif;margin:0;background:#fafaf8;color:#1c1c1a}"
       "main{max-width:880px;margin:0 auto;padding:32px 16px}h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:2rem}"
       "li{margin:.35rem 0}.ref{color:#5f5f59;font-size:.85rem;margin-left:.4rem}code{font-size:.9em}"
       "@media (prefers-color-scheme:dark){body{background:#151513;color:#ecece8}.ref{color:#a3a39c}}")
_CODE = re.compile(r"`([^`]*)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_EMPH = re.compile(r"\*([^*]+)\*")


def _inline(text: str) -> str:
    """Escaped text, with the report's three marks: `code`, **bold** and *emphasis*."""
    out = _CODE.sub(r"<code>\1</code>", html.escape(text, quote=False))
    return _EMPH.sub(r"<i>\1</i>", _BOLD.sub(r"<b>\1</b>", out))


def html_page(project: Any, rel: dict | None, outputs: dict) -> str:
    """The report as one self-contained HTML page: no script, no outside resource."""
    title = html.escape(f"Delivery report: {project.meta.get('title')}")
    body = [f"<h1>{title}</h1><p>Project <code>{html.escape(project.pid)}</code>"
            + (f", release {rel.get('release')}" if rel else ", no release yet")
            + f". Written by Rihmasto's kernel from the project's records, up to ledger #{_as_of(project)}; each "
            "line names the record it rests on.</p>"]
    for heading, items in sections(project, rel, outputs):
        rows = "".join(f"<li>{_inline(text)}<span class=\"ref\">({html.escape(ref)})</span></li>"
                       for text, ref in items)
        body.append(f"<h2>{html.escape(heading)}</h2><ul>{rows}</ul>")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\"><meta http-equiv=\"Content-Security-Policy\" "
            "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            f"<title>{title}</title><style>{CSS}</style></head><body><main>{''.join(body)}</main></body></html>\n")
