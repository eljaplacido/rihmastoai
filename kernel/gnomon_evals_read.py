"""How each Gnomon audit, benchmark or eval's output is read (FR-EVL1, kernel/gnomon_evals.py).

A reader takes what the run printed (its JSON on stdout, or the JSON file it wrote, or its text) and its exit code,
and answers in one shape: a verdict (passed, failed, or not measured with why: never passed when nothing was
measured), a one-line summary, the scores, and the findings, each with a stable key, a title, a severity (an
``issue`` counts as a new issue in Review; ``advice`` does not) and a few lines of evidence. Only Gnomon's own
words and figures are kept: never a prompt, never source code.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

MAX_FINDINGS, MAX_EVIDENCE, MAX_LINE = 50, 5, 300
Doc = dict[str, Any]


def finding(eid: str, key: str, title: str, severity: str = "issue", evidence: list[Any] | None = None) -> Doc:
    fid = "F-" + hashlib.sha256(f"{eid}|{key}".encode()).hexdigest()[:10]
    return {"id": fid, "key": str(key)[:120], "title": str(title)[:MAX_LINE], "severity": severity,
            "evidence": [str(e)[:MAX_LINE] for e in (evidence or []) if e not in (None, "")][:MAX_EVIDENCE]}


def answer(verdict: str, summary: str, scores: Doc | None = None, findings: list[Doc] | None = None,
           why: str | None = None) -> Doc:
    if verdict not in ("passed", "failed", "not measured"):
        raise ValueError(f"unknown verdict {verdict!r}")
    if verdict == "not measured" and not summary.startswith("not measured"):
        summary = f"not measured: {summary}"
    return {"verdict": verdict, "summary": summary[:MAX_LINE], "scores": {k: v for k, v in (scores or {}).items()
                                                                          if isinstance(v, (int, float))},
            "findings": (findings or [])[:MAX_FINDINGS], **({"why": why[:MAX_LINE]} if why else {})}


def pct(part: float, whole: float) -> float | None:
    """A share in percent with one decimal; None when there is nothing to share."""
    from kernel.insights.base import share

    return share(part, whole)


def _by_exit(code: int, ok: int = 0, bad: tuple[int, ...] = (2,)) -> str:
    return "passed" if code == ok else "failed" if code in bad else "not measured"


def _schema(doc: Any, prefix: str) -> Doc:
    if not isinstance(doc, dict) or not str(doc.get("schema") or "").startswith(prefix):
        raise ValueError(f"the output is not {prefix} JSON")
    return doc


def security(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.security/")
    found = [finding("security", f["id"], f.get("message") or f["id"], "issue" if f.get("severity") == "risk"
                     else "advice", [f.get("fix") and f"fix: {f['fix']}"]) for f in d.get("findings") or []]
    risks = sum(1 for f in found if f["severity"] == "issue")
    audit = d.get("audit") or {}
    scores = {"risks": risks, "advice": len(found) - risks,
              "trails_verified_pct": pct(audit.get("verified") or 0, audit.get("trails") or 0)}
    return answer(_by_exit(code), f"{risks} risk(s), {len(found) - risks} advice; audit trail "
                  f"{'on' if audit.get('enabled') else 'off'}", scores, found)


def security_test(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.security_test/")
    passed, total = int(d.get("passed") or 0), int(d.get("total") or 0)
    found = [finding("security_test", f"{c.get('host')}:{c.get('id')}", f"{c.get('story') or c.get('id')}: expected "
                     f"{c.get('expect')}, got {c.get('decision')}", "issue",
                     [f"host {c.get('host')}, tool {c.get('tool')}", c.get("rule") and f"rule {c['rule']}",
                      c.get("detail"), "OWASP " + ", ".join(c.get("owasp") or [])])
             for c in d.get("cases") or [] if c.get("pass") is False]
    if not total:
        return answer("not measured", "the attack corpus ran no case", why="no case ran")
    return answer(_by_exit(code), f"{passed} of {total} attack cases held", {"held_pct": pct(passed, total),
                                                                            "failed": total - passed}, found)


def compliance(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.compliance/")
    counts = {"evidence": 0, "partial": 0, "gap": 0}
    found = []
    for c in d.get("controls") or []:
        status = c.get("status")
        if status in counts:
            counts[status] += 1
        if status in ("gap", "partial"):
            fixes = [p.get("fix") for p in c.get("probes") or [] if not p.get("holds") and p.get("fix")]
            found.append(finding("compliance", f"{c.get('framework')}:{c.get('id')}", f"{c.get('framework')} "
                                 f"{c.get('id')} {c.get('title')}: {status}", "issue",
                                 [f"fix: {f}" for f in fixes]))
    judged = sum(counts.values())
    return answer(_by_exit(code), f"{counts['evidence']} of {judged} controls with evidence, {counts['partial']} "
                  f"partial, {counts['gap']} gap(s) (a mapping, never an assessment)",
                  {"evidence_pct": pct(counts["evidence"], judged), "gaps": counts["gap"],
                   "partial": counts["partial"]}, found)


def dataflow(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.dataflow/")
    dests = d.get("destinations") or []
    hosted = [x for x in dests if x.get("locality") not in (None, "local", "private", "loopback")]
    def users(x: Doc) -> str:
        return "used by " + ", ".join(str(u.get("role", "?")) for u in x.get("used_by") or [])

    found = [finding("dataflow", f"{x.get('kind')}:{x.get('name')}", f"{x.get('name')} ({x.get('host')}) is "
                     "refused by the residency rule", "issue", [users(x), x.get("note")])
             for x in dests if any(u.get("admitted") is False for u in x.get("used_by") or [])]
    found += [finding("dataflow", f"hosted:{x.get('name')}", f"{x.get('name')} sends {x.get('sends')} to "
                      f"{x.get('host')}", "advice", [f"locality {x.get('locality')}, region {x.get('region')}"])
              for x in hosted]
    res = d.get("residency") or {}
    return answer(_by_exit(code), f"{len(dests)} destination(s), {len(hosted)} hosted, {res.get('refused', 0)} "
                  "refused by the residency rule", {"hosted": len(hosted), "destinations": len(dests),
                                                    "refused": res.get("refused") or 0}, found)


def metrics(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.metrics/")
    t = d.get("totals") or {}
    process = t.get("process") or {}
    after = process.get("verified_after_last_write") or {}
    yes, no = int(after.get("yes") or 0), int(after.get("no") or 0)
    calls = t.get("model_calls") or {}
    found = [finding("metrics", f"chain:{s.get('trail')}", f"the audit trail {s.get('trail')} failed verification",
                     "issue") for s in d.get("sessions") or [] if s.get("chain_ok") is False]
    sessions = int(t.get("sessions") or 0)
    if not sessions and code != 2:
        return answer("not measured", "no Gnomon session trail to read yet", why="no session recorded")
    scores = {"verified_pct": pct(yes, yes + no), "sessions": sessions,
              "tokens": int(calls.get("prompt_tokens") or 0) + int(calls.get("completion_tokens") or 0),
              "refusal_rate": process.get("refusal_rate"), "apparatus_rate": process.get("apparatus_rate")}
    return answer(_by_exit(code), f"{sessions} session(s); a check passed after the last write in {yes} of "
                  f"{yes + no}", scores, found)


_TRAIL = re.compile(r"^(?P<name>\S+): (?P<n>\d+) records? — (?P<rest>.*)$")


def audit_verify(text: str, code: int, err: str = "") -> Doc:
    trails, found = 0, []
    intact = 0
    for line in text.splitlines():
        m = _TRAIL.match(line.strip())
        if not m:
            continue
        trails += 1
        rest = m.group("rest")
        if "BROKEN" in rest:
            found.append(finding("audit_verify", f"broken:{m.group('name')}", f"{m.group('name')}: {rest}", "issue"))
        else:
            intact += 1
        if "NOT SEALED" in rest:
            found.append(finding("audit_verify", f"unsealed:{m.group('name')}", f"{m.group('name')} is not sealed "
                                 "(truncated, or the run was killed)", "advice"))
    for line in err.splitlines():
        if "anchor: BROKEN" in line or "anchor: UNVERIFIABLE" in line:
            found.append(finding("audit_verify", "anchor", line.strip(), "issue"))
    if "nothing to verify" in err or (code != 0 and not trails and not found):
        return answer("not measured", "there is no audit trail to verify (turn on [audit] in the surface)",
                      why="no audit trail")
    verdict = "failed" if code != 0 or any(f["severity"] == "issue" for f in found) else "passed"
    return answer(verdict, f"{intact} of {trails} trail(s) intact", {"intact_pct": pct(intact, trails),
                                                                       "trails": trails}, found)


def _rule(c: Doc) -> Doc:
    reason = f" ({c['reason']})" if c.get("reason") else ""
    return finding("check", c.get("id") or "?", f"{c.get('id')}: {c.get('status')}{reason}", "issue",
                   [str(x)[:200] for x in (c.get("findings") or [])[:3]])


def check(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.check/")
    judged = [c for c in d.get("checks") or [] if c.get("status") in ("pass", "fail", "error")]
    if code == 10 or not judged:
        return answer("not measured", d.get("error") or "gnomon check gave no verdict", why="no verdict")
    held = sum(1 for c in judged if c["status"] == "pass")
    head, base = str(d.get("head") or "head")[:12], str(d.get("base") or "?")[:12]
    return answer(_by_exit(code), f"{held} of {len(judged)} rules held on {head} against {base}",
                  {"passed_pct": pct(held, len(judged))}, [_rule(c) for c in judged if c["status"] != "pass"])


def _arm(d: Doc, arm: str) -> tuple[int, int]:
    got = ((d.get("endpoints") or {}).get("pass") or {}).get(arm) or {}
    return int(got.get("passes") or 0), int(got.get("n") or 0)


def eval_(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.eval/")
    (passes, n), (cpass, cn) = _arm(d, "base"), _arm(d, "candidate")
    meets = d.get("meets_thresholds")
    if d.get("status") == "apparatus_failure" or not n or meets == "undetermined":
        return answer("not measured", f"the eval could not decide ({d.get('status')}, {n} valid cell(s))",
                      {"pass_rate": pct(passes, n)}, why="undetermined")
    found = [finding("eval", f"reason:{r}", r, "issue") for r in d.get("reasons") or []] if meets is False else []
    scores = {"pass_rate": pct(passes, n), "candidate_pass_rate": pct(cpass, cn),
              "requests": (d.get("budget") or {}).get("requests_used")}
    spec = (d.get("spec") or {}).get("name")
    said = f"{passes} of {n} tasks passed on spec {spec}" + (" (meets its thresholds)" if meets is True else "")
    return answer("passed" if meets is True else "failed", said, scores, found)


def chaos(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.chaos/")
    s = d.get("summary") or {}
    if code == 2:
        return answer("not measured", "the chaos run is void: " + "; ".join((d.get("apparatus") or {}).get("problems")
                                                                           or ["see its report"]), why="void run")
    silent = [f for f in d.get("faults") or [] if f.get("verdict") == "silent"]
    found = [finding("chaos", f["id"], f"fault {f['id']} ({f.get('injects')}) was silent in {f.get('silent')} of "
                     f"{f.get('fired')} case(s)", "issue") for f in silent]
    return answer(_by_exit(code, bad=(1,)), f"{s.get('faults_announced', 0)} of {s.get('faults', 0)} faults announced; "
                  f"silent-failure share {round((s.get('silent_failure_share') or 0) * 100, 1)}%",
                  {"announced_pct": pct(s.get("faults_announced") or 0, s.get("faults") or 0),
                   "silent_share_pct": round((s.get("silent_failure_share") or 0) * 100, 1)}, found)


def doctor(doc: Any, code: int) -> Doc:
    d = _schema(doc, "gnomon.doctor/")
    found = [finding("doctor", f"{f.get('kind')}:{f.get('message')}", f.get("message") or "", "issue"
                     if f.get("severity") == "problem" else "advice", [f.get("fix") and f"fix: {f['fix']}"])
             for f in d.get("findings") or []]
    routes = ((d.get("surface") or {}).get("routes")) or []
    problems = sum(1 for f in found if f["severity"] == "issue")
    return answer(_by_exit(code, bad=(1,)), f"{problems} problem(s); {sum(1 for r in routes if r.get('ready'))} of "
                  f"{len(routes)} route(s) ready", {"problems": problems,
                                                    "routes_ready_pct": pct(sum(1 for r in routes if r.get("ready")),
                                                                            len(routes))}, found)


def claim_check(doc: Any, code: int) -> Doc:
    if not isinstance(doc, dict) or "counts" not in doc:
        raise ValueError("the output is not the claim check's JSON")
    c = doc["counts"]
    found = [finding("claim_check", f"{x.get('kind')}:{x.get('raw')}", f"refuted {x.get('kind')}: {x.get('raw')}",
                     "issue", [x.get("detail")]) for x in doc.get("claims") or [] if x.get("verdict") == "refuted"]
    acc = doc.get("accuracy")
    if acc is None:
        return answer("not measured", "the report has no checkable claim", why="no checkable claim")
    return answer("failed" if code == 1 or found else "passed", f"{c.get('verified', 0)} verified, "
                  f"{c.get('refuted', 0)} refuted, {c.get('unverifiable', 0)} unverifiable",
                  {"accuracy": round(float(acc) * 100, 1) if acc <= 1 else float(acc)}, found)


def context_cost(doc: Any, code: int, cfg: Doc | None = None) -> Doc:
    g = (doc or {}).get("gnomon") if isinstance(doc, dict) else None
    if code == 1 or not isinstance(g, dict) or not g.get("requests"):
        return answer("not measured", "the context-cost run is void (no request reached the canary)", why="void run")
    total = int(g.get("total_bytes") or 0)
    limit = (cfg or {}).get("max_bytes")
    over = isinstance(limit, int) and total > limit
    found = [finding("context_cost", "over", f"{total} bytes per prompt, over the {limit} allowed", "issue")] if over \
        else []
    return answer("failed" if over else "passed", f"{total} bytes over {g['requests']} request(s) for one prompt",
                  {"total_bytes": total, "requests": int(g["requests"]), "tool_count": g.get("turn_tool_count")}, found)


def degradation(doc: Any, code: int) -> Doc:
    rows = (doc or {}).get("rows") if isinstance(doc, dict) else None
    if code == 2 or not isinstance(rows, list) or not rows:
        return answer("not measured", "the degradation contract run is void", why="void run")
    done = sum(1 for r in rows if r.get("complete"))
    found = [finding("degradation", r.get("id"), f"degradation {r.get('id')}: announced {r.get('announced')}, "
                     f"recorded {r.get('recorded')}", "issue") for r in rows if not r.get("complete")]
    return answer(_by_exit(code, bad=(1,)), f"{done} of {len(rows)} degradations announced and recorded",
                  {"complete_pct": pct(done, len(rows))}, found)


JSON_READERS: dict[str, Callable[..., Doc]] = {
    "security": security, "security_test": security_test, "compliance": compliance, "dataflow": dataflow,
    "metrics": metrics, "check": check, "eval": eval_, "chaos": chaos, "doctor": doctor, "claim_check": claim_check,
    "degradation": degradation}


def read(eid: str, out: str, err: str, code: int, *, doc: Any = None, cfg: Doc | None = None) -> Doc:
    """The result of one run of ``eid``. Output that cannot be read is not measured, with why."""
    from kernel.checks.tools import json_of

    if eid == "audit_verify":
        return audit_verify(out, code, err)
    parsed = doc if doc is not None else json_of(out)
    if parsed is None:
        tail = (err or out).strip().splitlines()[-1:] or ["no output"]
        return answer("not measured", f"no report came back (exit {code}): {tail[0][:200]}", why="no report")
    try:
        if eid == "context_cost":
            return context_cost(parsed, code, cfg)
        return JSON_READERS[eid](parsed, code)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return answer("not measured", f"the report could not be read ({exc})", why="unreadable report")
