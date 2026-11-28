"""A precise assessment of an adopted project: what is worth acting on, and what is probably noise (FR-ASP1).

The owner (2026-11-26), after adopting a project of their own: "Im still not happy with clarity, when I jump into
[an adopted project] its not clear what should I do and claude code in IDE didnt find most of insights relevant".
Their coding agent's review found test fixtures reported as critical secrets, long URL paths read as tokens, and
findings that did not apply to the project with no way to say so. This module keeps the rules' findings honest
for any adopted project, by rule and with no model:

- **Secrets judged by their context.** A secret finding of the red team (a known format or a high-entropy value)
  is read again on its own line: in a test fixture's file with an obviously fake value (fixture, example, dummy,
  test, all one character, an identifier in a test file), or inside a long URL path with no credential-shaped
  query and no user info, it is "likely not a secret", with the reason, never critical. Its evidence stays
  masked. A person confirms it real or marks it a fixture; the mark is remembered for that file, signed, in the
  ledger (`assessment_secret_marked`), and every later assessment reads it.
- **Not relevant to this project.** Any finding can be marked not relevant with a reason. The verdict is kept by
  the finding's key (`assessments/relevance.json`, `assessment_finding_dismissed` in the ledger): it stays out of
  the priorities in this version and the next, and the findings of the same rule in this project are proposed
  for the same verdict (a feedback loop a person settles, never applied on its own).
- **A baseline that never ran is not a failure.** Errors while collecting and nothing else means no test ran:
  that is "not measured by Rihmasto yet", with what to do, never "the suite could not run" as a finding.

Checked again (FR-ASP2): a URL that is itself a credential, or holds a known format, and a value beside a URL are
possibly real; fake words count only in a test suite's files (kernel/assess_secret_context.py); a mark covers the
values marked, by a fingerprint of each line; only the secret markers mark a secret not relevant; findings alike are
those of the same kind (kernel/assess_context.py), and a "relevant" verdict is kept, bringing back a finding the
rule put off for later.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kernel import assess_context as kinds
from kernel import assess_secret_context as ctx
from kernel.modules import extend
from kernel.redteam.masking import assigned_secrets, known_secrets
from kernel.redteam.secretscan import test_path
from kernel.store import updating_json

SECRET_RULES = ("RT-SECRET-PATTERN", "RT-SECRET-ENTROPY")
MARKS = "assessments/marks.json"
RELEVANCE = "assessments/relevance.json"
SECRET_MARKS = ("fixture", "real")
RELEVANCE_VERDICTS = ("not_relevant", "relevant")
VERDICTS = (*RELEVANCE_VERDICTS, *SECRET_MARKS)
MARKERS = ("developer", "it", "compliance", "operations", "product_owner")   # who may judge a secret
LIKELY_NOT = "likely not a secret"
CONFIRMED = "confirmed real"
POSSIBLY = "possibly real"
MAX_REASON = 400
MAX_ALSO = 50
QUOTED = re.compile(r"""(["'`])([^"'`\s]{6,})\1""")
ASSIGNED = re.compile(r"""[:=]\s*([^\s"'`,;)]{6,})""")
URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s\"'`<>)]+", re.I)
CREDENTIAL_QUERY = re.compile(r"(?i)[?&#;][a-z0-9_.-]*(token|key|sig|signature|secret|password|passwd|pwd|auth|"
                              r"credential|session|code)[a-z0-9_.-]*=")
USERINFO = re.compile(r"^[a-z][a-z0-9+.-]*://[^/@\s]+@", re.I)
UUID = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# Part of the Assessment module (kernel/modules.py): off with it, refused with it.
extend("assessment", controls=("assessment_not_relevant", "assessment_secret_mark", "assessment_runner_map"),
       commands=("assessment verdict", "assessment runner"),
       routes=("post_assessment_verdict", "post_assessment_runner"))


class VerdictRefused(ValueError):
    """A verdict the kernel will not take: not a person, an unknown finding, a mark on a finding that is no secret."""


class SecretJudgeRefused(VerdictRefused, PermissionError):
    """A secret judged by a persona that does not judge secrets: refused as access is (a 403), FR-ASP2."""


# -- secrets, judged by their context ----------------------------------------------------------------

def secret_rule(check: dict[str, Any]) -> str | None:
    """The red team's secret rule a check is a finding of, or None."""
    rule = str(check.get("key", "")).removeprefix("security.").split(":", 1)[0]
    return rule if rule in SECRET_RULES else None


def _values(line: str) -> list[str]:
    # a quoted name followed by ":" is a JSON key, not a value (``"refresh_token": "eyJ..."`` holds one value)
    quoted = [m.group(2) for m in QUOTED.finditer(line) if not re.match(r"\s*:", line[m.end():])]
    return quoted or [m.group(1) for m in ASSIGNED.finditer(line)]


def fake_value(value: str, *, in_tests: bool = True) -> str | None:
    """Why a value is obviously not a real secret, or None: in a test suite's file only, a word of its own that says
    so, or one character over and over; never a known credential format (kernel/assess_secret_context.py)."""
    return ctx.fake_value(value, in_tests=in_tests)


def _credentialed(url: str) -> bool:
    return bool(CREDENTIAL_QUERY.search(url) or USERINFO.match(url))


EXPIRES = re.compile(r"[?&]Expires=(\d{9,11})(?:&|$)")


def _expired(urls: list[str]) -> str | None:
    """Why signed links are no longer a credential, or None: every credentialed URL on the line is a signed link
    (an ``Expires`` epoch) whose time has passed, and no URL carries user info. The date is named, never the link."""
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    stamps = []
    for url in urls:
        if not _credentialed(url):
            continue
        found = EXPIRES.search(url)
        if found is None or USERINFO.match(url):
            return None
        try:
            stamps.append(dt.datetime.fromtimestamp(int(found.group(1)), dt.UTC))
        except (OverflowError, OSError, ValueError):
            return None
    if not stamps or max(stamps) >= now:
        return None
    return (f"a signed link that expired on {max(stamps).date().isoformat()}: nothing is left to revoke; take it out "
            "of the file when convenient")


def _url_only(line: str) -> str | None:
    """Why a secret on ``line`` is a URL path, or None: every secret-shaped value sits inside a URL that has no
    credential-shaped query and no user info."""
    urls = URL.findall(line)
    if not urls or any(_credentialed(u) for u in urls):
        return None
    rest = URL.sub(" ", line)
    if known_secrets(rest) or assigned_secrets(rest, config=True) or ctx.loose_values(rest):
        return None             # a value beside the URL is judged on its own (FR-ASP2)
    longest = max(urls, key=len)
    return (f"the match is inside a URL path ({len(longest)} characters) with no credential-shaped query and no user "
            "info: a long path, not a credential")


def _credentialed_urls(urls: list[str]) -> tuple[str, str]:
    """A signed link past its expiry is nothing left to revoke; any other credentialed URL is treated as real."""
    gone = _expired(urls)
    if gone:
        return LIKELY_NOT, gone
    return POSSIBLY, "a URL that carries a credential-shaped query or user info: treat it as real"


def judge_line(rel: str, line: str) -> tuple[str, str]:
    """(verdict, reason) for a secret found on ``line`` of ``rel``, by rule."""
    urls = URL.findall(line)
    if any(_credentialed(u) for u in urls):
        return _credentialed_urls(urls)
    in_url = ctx.url_reason(urls)        # a webhook or bot URL, or a known format inside the URL (FR-ASP2)
    if in_url:
        return POSSIBLY, in_url
    url = _url_only(line)
    if url:
        return LIKELY_NOT, url
    values = _values(line)
    in_tests = test_path(rel)
    fakes = [(v, fake_value(v, in_tests=in_tests)) for v in values]
    where = f"a test fixture's file ({rel})" if in_tests else rel
    if values and all(why for _, why in fakes):
        return LIKELY_NOT, f"{where} with an obviously fake value: {fakes[0][1]}"
    if in_tests and values and all(UUID.match(v) or why for v, why in fakes):
        return LIKELY_NOT, f"{where}: an identifier made for a test (a UUID), not a credential"
    return POSSIBLY, "no sign it is a fixture or a URL path: treat it as real until a person says otherwise"


def _line_of(root: Path, rel: str, n: int) -> str:
    try:
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return lines[n - 1] if 0 < n <= len(lines) else ""


def _likely(check: dict[str, Any], verdict: str, reason: str, by: str) -> None:
    """Annotate a secret finding; one likely not a secret is never critical (its first severity is kept)."""
    check["likely"] = {"verdict": verdict, "reason": reason, "by": by}
    if verdict == LIKELY_NOT and check.get("severity") != "info":
        check.setdefault("severity_was", check.get("severity"))
        check["severity"] = "info"


def _apply_mark(check: dict[str, Any], mark: dict[str, Any]) -> None:
    if not ctx.covers(mark, check):          # a value added to the file after the mark: the rule judges it (FR-ASP2)
        likely = check.get("likely") or {}
        if likely.get("by") == "rule" and "not this one" not in str(likely.get("reason")):
            likely["reason"] = str(likely.get("reason", "")) + ctx.not_covered(mark)
        return
    who =f"{mark.get('person')} ({mark.get('persona')}) on {str(mark.get('at', ''))[:10]}"
    if mark.get("mark") == "fixture":
        _likely(check, LIKELY_NOT, f"marked as a fixture by {who}: {mark.get('reason') or 'no reason given'}", "person")
    else:
        if check.get("severity_was"):
            check["severity"] = check.pop("severity_was")
        check["likely"] = {"verdict": CONFIRMED, "reason": f"confirmed real by {who}", "by": "person"}


def _file_of(check: dict[str, Any]) -> str:
    ev = (check.get("evidence") or [{}])[0]
    return str(ev.get("file") or "")


def judge_secrets(checks: list[dict[str, Any]], root: Path, project: Any) -> list[dict[str, Any]]:
    """Each secret finding judged on its own line (read from the revision written under ``root``), and the marks
    people made per file applied over the rule. The evidence stays the red team's masked line."""
    marks = project.read(MARKS, {}) or {}
    for c in checks:
        if c.get("verdict") != "failed" or not secret_rule(c):
            continue
        rel = _file_of(c)
        line = _line_of(root, rel, int((c.get("evidence") or [{}])[0].get("line") or 0))
        verdict, reason = judge_line(rel, line)
        c["line_mark"] = ctx.line_mark(project.pid, line)     # what a person's mark on this file covers (FR-ASP2)
        _likely(c, verdict, reason, "rule")
        if rel in marks:
            _apply_mark(c, marks[rel])
    return checks


def never_ran(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A baseline that failed with errors while collecting and no test passed or failed: no test ran, so it is
    not measured by Rihmasto yet (a test root of each package's own, or a runner of the project's own)."""
    for c in checks:
        if c.get("key") != "maintenance.baseline" or c.get("verdict") != "failed":
            continue
        if not str(c.get("summary", "")).startswith("the suite could not run"):    # kernel/adopt.py _failed_said
            continue
        c.update(verdict="not measured", severity=None, reason=(
            "not measured by Rihmasto yet: no test ran (errors while collecting the tests from where they were "
            "started). Each package may keep its own test root, or the project runs its tests with a tool of its "
            "own: map its runner"))
        c.pop("suggestion", None)
    return checks


# -- verdicts people give ------------------------------------------------------------------------------

def _finding(record: dict[str, Any], fid: str) -> dict[str, Any]:
    found = {c["id"]: c for c in record.get("checks") or [] if c.get("id")}
    found |= {p["id"]: p for p in record.get("proposals") or [] if p.get("id")}
    want = str(fid).strip().upper()
    if want not in found:
        raise VerdictRefused(f"no finding {fid} in {record['id']}")
    return found[want]


def family(f: dict[str, Any]) -> str:
    """What makes two findings alike, by rule: the red team's rule, the kind of check (kernel/assess_context.py), or
    the rule a keyed finding is one of (an issue of the team's own log)."""
    return kinds.family_of(str(f.get("key", "")))


def _reason(reason: str | None, *, required: bool) -> str:
    text = " ".join(str(reason or "").split())[:MAX_REASON]
    if required and len(text) < 3:
        raise VerdictRefused("say why, in a few words: the reason is kept with the verdict")
    return text


def _judged(record: dict[str, Any], f: dict[str, Any], also: list[str] | None, verdict: str,
            persona: str) -> list[dict[str, Any]]:
    """The findings a verdict is given to: ``f`` and those of ``also``; a secret among them marked not relevant only
    by a persona that judges secrets (FR-ASP2)."""
    extra = [_finding(record, i) for i in (also or [])[:MAX_ALSO]]
    keys = [f, *[x for x in extra if x["key"] != f["key"]]]
    if verdict == "not_relevant" and persona not in MARKERS and any(secret_rule(x) for x in keys):
        raise SecretJudgeRefused(f"a secret is judged by a {', '.join(MARKERS)}, not {persona}: marking it not "
                                 "relevant is judging it")
    return keys


def give(project: Any, finding: str, verdict: str, *, person: str, persona: str, reason: str | None = None,
         also: list[str] | None = None) -> dict[str, Any]:
    """A person's verdict on a finding of the latest assessment, signed and in the ledger: not relevant (with a
    reason, and the same for ``also``), relevant again, or, for a secret, a fixture or confirmed real (for its file).
    Returns what was kept and the findings like it a person may give the same verdict."""
    from kernel.assess import _check_asker, load

    _check_asker(person, persona)
    if verdict not in VERDICTS:
        raise VerdictRefused(f"a verdict is one of {', '.join(VERDICTS)}, not {verdict!r}")
    record = load(project)
    f = _finding(record, finding)
    at = project.factory.clock.stamp()
    if verdict in SECRET_MARKS:
        return _mark_secret(project, record, f, verdict, person=person, persona=persona, at=at,
                            reason=_reason(reason, required=False))
    why = _reason(reason, required=verdict == "not_relevant")
    keys = _judged(record, f, also, verdict, persona)
    with updating_json(project.path(RELEVANCE), {}) as kept:
        for x in keys:       # relevant is kept too: it brings back a finding the rule put off for later (FR-ASP2)
            kept[x["key"]] = {"verdict": verdict, "reason": why, "person": person, "persona": persona, "at": at,
                              "finding": x["id"], "title": x.get("title"), "assessment": record["id"],
                              "family": family(x), "like": f["id"] if x is not f else None}
    kind = "assessment_finding_dismissed" if verdict == "not_relevant" else "assessment_finding_restored"
    project.log(kind, {"assessment": record["id"], "findings": [x["id"] for x in keys],
                       "keys": [x["key"] for x in keys], "reason": why, "person": person, "persona": persona})
    return {"assessment": record["id"], "verdict": verdict, "findings": [x["id"] for x in keys],
            "similar": similar(project, record, f) if verdict == "not_relevant" else [],
            "family": kinds.family_label(family(f))}


def judges_secret(project: Any, body: dict[str, Any]) -> bool:
    """Whether a verdict judges a secret: a fixture or real mark, or a secret finding (or one of ``also``) marked
    not relevant, in the latest assessment. Only the secret markers give it (FR-ASP2)."""
    from kernel.assess import history, load

    verdict = body.get("verdict")
    if verdict in SECRET_MARKS:
        return True
    if verdict != "not_relevant" or not history(project):
        return False
    record = load(project)
    ids = [str(body.get("finding") or ""), *[str(i) for i in (body.get("also") or []) if isinstance(i, str)]]
    found = {c.get("id"): c for c in record.get("checks") or [] if c.get("id")}
    return any(secret_rule(found.get(i.strip().upper(), {})) for i in ids)


def _mark_secret(project: Any, record: dict[str, Any], f: dict[str, Any], mark: str, *, person: str, persona: str,
                 at: str, reason: str) -> dict[str, Any]:
    if not secret_rule(f):
        raise VerdictRefused(f"{f['id']} is not a secret finding: only a secret is confirmed real or marked a fixture")
    if persona not in MARKERS:
        raise SecretJudgeRefused(f"a secret is judged by a {', '.join(MARKERS)}, not {persona}")
    rel = _file_of(f)
    lines = sorted({c["line_mark"] for c in record.get("checks") or [] if secret_rule(c) and _file_of(c) == rel
                    and c.get("line_mark")})
    with updating_json(project.path(MARKS), {}) as marks:
        marks[rel] = {"mark": mark, "person": person, "persona": persona, "at": at, "reason": reason,
                      "finding": f["id"], "key": f["key"], "assessment": record["id"]} \
            | ({"lines": lines} if lines else {})          # the values marked, never one added later (FR-ASP2)
    project.log("assessment_secret_marked", {"assessment": record["id"], "finding": f["id"], "file": rel,
                                             "mark": mark, "reason": reason, "person": person, "persona": persona})
    same = [c["id"] for c in record.get("checks") or [] if c.get("id") and secret_rule(c) and _file_of(c) == rel]
    return {"assessment": record["id"], "verdict": mark, "file": rel, "findings": same, "similar": []}


def similar(project: Any, record: dict[str, Any], f: dict[str, Any]) -> list[str]:
    """The open findings of the same rule as ``f`` that no person has judged yet: proposed, never marked."""
    kept = project.read(RELEVANCE, {}) or {}
    fam = family(f)
    return [c["id"] for c in record.get("checks") or [] if c.get("verdict") == "failed" and c.get("id")
            and c["id"] != f["id"] and family(c) == fam and c["key"] not in kept]


def _kept_overlay(c: dict[str, Any], kept: dict[str, Any]) -> bool:
    """A person's verdict on ``c``, as people see it now: relevant (never put off for later) or not relevant."""
    said = kept.get(str(c.get("key"))) or {}
    if said.get("verdict") == "relevant":
        c["kept_relevant"] = said
    elif said:
        c["dismissed"] = said
    return bool(said)


def overlay(project: Any, record: dict[str, Any] | None) -> dict[str, Any] | None:
    """The latest record as people see it now: each finding marked not relevant carries that verdict, one like a
    finding marked not relevant carries the proposal, and a secret's file mark made since applies. The record
    on disk is never changed (its sha256 is in the ledger)."""
    if not record:
        return record
    kept = project.read(RELEVANCE, {}) or {}
    marks = project.read(MARKS, {}) or {}
    dismissed_families = {v.get("family"): (k, v) for k, v in kept.items() if v.get("verdict") == "not_relevant"}
    for c in [*(c for c in record.get("checks") or [] if c.get("verdict") == "failed"),
              *(record.get("proposals") or [])]:
        if _kept_overlay(c, kept):
            pass
        elif family(c) in dismissed_families:
            key, v = dismissed_families[family(c)]
            c["propose_dismiss"] = {"like": v.get("finding"), "key": key, "reason": v.get("reason"),
                                    "person": v.get("person")}
        rel = _file_of(c)
        if secret_rule(c) and rel in marks:          # the mark as it stands now, over the one recorded
            _apply_mark(c, marks[rel])
    return kinds.put_off(project, record)         # a local project's deploy and publish findings, for later (FR-ASP2)


def is_noise(c: dict[str, Any]) -> str | None:
    """Why a finding is probably noise, or None: marked not relevant, or likely not a secret."""
    if c.get("dismissed"):
        return "marked not relevant"
    if (c.get("likely") or {}).get("verdict") == LIKELY_NOT:
        return LIKELY_NOT
    if c.get("later"):
        return "for later"
    return None


__all__ = ["CONFIRMED", "LIKELY_NOT", "MARKERS", "MARKS", "POSSIBLY", "RELEVANCE", "SECRET_MARKS", "VERDICTS",
           "SecretJudgeRefused", "VerdictRefused", "family", "judges_secret",
           "fake_value", "give", "is_noise", "judge_line", "judge_secrets", "never_ran",
           "overlay", "secret_rule", "similar"]
