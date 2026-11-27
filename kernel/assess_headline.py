"""The Assessment view's first two lines, and Ask Rihma's answers on them (FR-ASP1).

The owner (2026-11-26): "when I jump into [an adopted project] its not clear what should I do". So the view opens on
two lines, by rule and from the latest assessment as people judged it: what is worth acting on now, and what is
probably noise, each with why; then the next steps, each a button (guide, don't describe). Ask Rihma answers the
same by rule ("what is noise here?", "what should I act on?") and proposes the same writes the buttons make: a
finding marked not relevant with its reason, a secret confirmed real or marked a fixture, the project's own test
runner mapped. Each is a proposal the person confirms, signed (kernel/assistant_ops.py).
"""

from __future__ import annotations

import re
from typing import Any

from kernel.assess_precise import LIKELY_NOT, MARKERS, is_noise, secret_rule

ACT_SEVERITIES = ("critical", "high", "medium")
# Asked anywhere about a project: these name the assessment's own ideas.
ASKS = re.compile(r"(?i)\b(worth acting on|likely not a secret|map (its|the|our|this project's) (own )?(test )?"
                  r"runner|(stale|old) plans? in the assessment|[FP]-\d+ is (a fixture|real|not relevant|relevant)|"
                  r"gaps? to close)\b")
# Asked about the assessment (its view open, or the word said): the common words.
ASKS_THERE = re.compile(r"(?i)\b(noise|noisy|not relevant|irrelevant|false positives?|fixtures?|realistic picture|"
                        r"for later|"
                        r"what (should|do) i (do|act on)|act on)\b")
THERE = re.compile(r"(?i)\b(assessment|assess|findings?|[FP]-\d+)\b")
_FID = re.compile(r"\b([FP]-\d{1,4})\b", re.I)
_BECAUSE = re.compile(r"(?i)\b(?:because|since|as|reason:?)\s+(.{3,300})$")
_COMMAND = re.compile(r"`([^`]{2,300})`")
_RESULTS = re.compile(r"(?i)\bresults?\s+(?:in|at|file)\s+`?([\w./-]{3,200})`?")
WHY_ACT = ("Why: they are the rules' findings in this project's own files, rated critical, high or medium, and nobody "
           "marked them as fixtures or not relevant")
NOTHING = ("Nothing needs acting on now: every open finding is low, probably noise, or already filed as a change (the "
           "list below keeps them)")
WHY_NOISE = "Why: each says so on its row, by rule or by a person's mark"
UNMAPPED = ("the tests are not measured by Rihmasto yet: its own test runner is not mapped, so no test count here is "
            "a failure")
AGAIN = "its test runner was mapped after this assessment: assess again to read its results"


def _named(ids: list[str], titles: dict[str, str], limit: int = 3) -> str:
    shown = [f"{i} {titles.get(i, '')}".strip() for i in ids[:limit]]
    more = len(ids) - limit
    return "; ".join(shown) + (f"; and {more} more" if more > 0 else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word if n == 1 else word + 's'}"


def _title(c: dict[str, Any]) -> str:
    """A rule's title says what should hold and its summary what fails; the red team's title names what it found."""
    said = c.get("title") if str(c.get("key", "")).startswith("security.RT-") else c.get("summary") or c.get("title")
    return f"({said})"


def _likely_part(likely: list[dict[str, Any]]) -> str | None:
    if not likely:
        return None
    reasons = [c["likely"]["reason"] for c in likely]
    fixtures = sum(1 for r in reasons if "test fixture" in r or "fixture by" in r)
    urls = sum(1 for r in reasons if "URL path" in r)
    kinds = [k for k in (f"{fixtures} in test fixtures" if fixtures else "",
                         _plural(urls, "long URL path") if urls else "")
             if k]
    return f"{_plural(len(likely), 'secret finding')} likely not a secret" + (f" ({', '.join(kinds)})" if kinds else "")


def _noise_line(likely: list[dict[str, Any]], dismissed: int, proposed: int, later: list[dict[str, Any]]) -> str:
    """What is probably noise: never a gap to close (tests not measured, old plans), which has its own line."""
    parts = [_likely_part(likely),
             f"{_plural(dismissed, 'finding')} marked not relevant" if dismissed else None,
             f"{_plural(proposed, 'finding')} like one marked not relevant" if proposed else None,
             f"{_plural(len(later), 'finding')} for later, since this is a local project "
             f"({later[0]['later']['local']}): they matter once it is deployed, published or worked on by a team"
             if later else None]
    said = [p for p in parts if p]
    if not said:
        return "Probably noise: nothing found by rule: no fixture, URL path or finding for later stands out."
    return "Probably noise: " + "; ".join(said) + f". {WHY_NOISE}."


def _gaps_line(runner_state: str | None, reason: str, plans: dict[str, Any]) -> str | None:
    """Gaps to close: what keeps the picture from being whole (FR-ASP2), each with what closes it."""
    runs = {"unmapped": UNMAPPED, "assess_again": AGAIN,
            "unread": "the mapped runner's results are not read yet: " + reason.split(". ", 1)[-1].rstrip(".")}
    parts = [runs.get(runner_state or ""),
             f"{_plural(plans['stale'], 'imported plan')} older than the code by {plans.get('stale_days')} days or "
             "more: check them before accepting them" if plans.get("stale") else None]
    said = [p for p in parts if p]
    return "Gaps to close: " + "; ".join(said) + "." if said else None


def headline(view: dict[str, Any]) -> dict[str, Any] | None:
    """What is worth acting on now and what is probably noise, each in one line with why, and the next steps."""
    latest = view.get("latest")
    if not latest:
        return None
    failed = [c for c in latest.get("checks") or [] if c.get("verdict") == "failed" and c.get("id")]
    titles = {c["id"]: _title(c) for c in failed}
    noise = {c["id"] for c in failed if is_noise(c)}
    act = _worth(view.get("priority") or [], titles, noise)
    state, reason = _runner_state(latest, view.get("runner"))
    plans = (latest.get("precise") or {}).get("plans") or {}
    likely, proposed, dismissed = _sorted_out(failed)
    later = _put_off(failed)
    first = f"Worth acting on now: {_named(act, titles)}. {WHY_ACT}." if act else NOTHING + "."
    return {"act": first, "gaps": _gaps_line(state, reason, plans),
            "noise": _noise_line(likely, dismissed, len(proposed), later), "act_ids": act,
            "noise_ids": sorted(noise) + proposed, "later_ids": [c["id"] for c in later],
            "next": _next(act, len(likely), len(proposed), state, bool(plans.get("stale_open")))}


def _put_off(failed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The open findings a local project puts off for later, by rule (kernel/assess_context.py)."""
    return [c for c in failed if c.get("later") and not c.get("dismissed")]


def _sorted_out(failed: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], int]:
    """The open findings likely not a secret, those proposed as not relevant, and how many were marked so."""
    open_ = [c for c in failed if not c.get("dismissed")]
    likely = [c for c in open_ if (c.get("likely") or {}).get("verdict") == LIKELY_NOT]
    return likely, [c["id"] for c in open_ if c.get("propose_dismiss")], len(failed) - len(open_)


def _worth(priority: list[dict[str, Any]], titles: dict[str, str], noise: set[str]) -> list[str]:
    """The open findings in priority order that are not noise and are rated critical, high or medium."""
    return [r["id"] for r in priority if r.get("id") in titles and r["id"] not in noise
            and r.get("severity") in ACT_SEVERITIES]


def _runner_state(latest: dict[str, Any], now: dict[str, Any] | None) -> tuple[str | None, str]:
    """Where measuring the project's own tests stands (FR-ASP2): None when measured; "unmapped" with no runner;
    "assess_again" when one was mapped (or changed) after this assessment; "unread" when its results were not read."""
    check = next((c for c in latest.get("checks") or [] if c.get("key") == "maintenance.tests_measured"), None)
    if not check or check.get("verdict") != "not measured":
        return None, ""
    used = (latest.get("precise") or {}).get("runner") or {}
    if now and (now.get("command"), now.get("results"), now.get("at")) != (used.get("command"), used.get("results"),
                                                                           used.get("at")):
        return "assess_again", ""
    return ("unread" if used else "unmapped"), str(check.get("reason") or "")


def _next(act: list[str], likely: int, proposed: int, runner_state: str | None,
          old_open: bool) -> list[dict[str, str]]:
    """The next steps from the state, most useful first: each a button in the view and a step in Ask Rihma."""
    steps = [(act, "select_act", f"Tick the {len(act[:5])} worth acting on", "assessment_changes"),
             (runner_state == "unmapped", "map_runner", "Map its test runner", "assessment_runner_map"),
             (runner_state == "assess_again", "assess_again", "Assess again", "run_assessment"),
             (runner_state == "unread", "runner_results", "Get its results read", "assessment_runner_map"),
             (likely, "review_secrets", f"Check the {likely} likely fixtures", "assessment_secret_mark"),
             (proposed, "review_similar", f"Settle {proposed} like one marked not relevant", "assessment_not_relevant"),
             (old_open, "align", "Check the old plans before accepting them", "align_decide")]
    return [{"do": do, "label": label, "control": control} for on, do, label, control in steps if on]


# -- Ask Rihma -----------------------------------------------------------------------------------------------

def asks(question: str, view: str | None = None) -> bool:
    """Whether a question is about what to act on or what is noise in the assessment."""
    q = question or ""
    return bool(ASKS.search(q) or (ASKS_THERE.search(q) and (view == "assessment" or THERE.search(q))))


def _offer(factory: Any, project: Any, persona: str, op: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    from kernel import assistant_ops

    p = assistant_ops.proposal(factory, op, {"project": project.pid, **args}, persona=persona, project=project)
    return [p] if p else []


def _out(project: Any, answer: str, propose: list[dict[str, Any]] | None = None,
         control: str = "assessment_ask") -> dict[str, Any]:
    return {"answer": answer, "navigate": {"route": f"#/p/{project.pid}/assessment", "control": control},
            "propose": propose or [], "dropped": [], "sources": [], "by": "rule", "matches": ["assessment"]}


def _secret(factory: Any, project: Any, persona: str, question: str, f: str, c: dict[str, Any]) -> dict | None:
    """A secret named as a fixture, or as real."""
    if not secret_rule(c):
        return None
    if re.search(r"(?i)\b(fixture|fake|not a (real )?secret)\b", question):
        where = (c.get("evidence") or [{}])[0].get("file")
        return _out(project, f"I can mark {f} as a fixture: every secret finding in {where} is then read as likely "
                             "not a secret, now and in later assessments, signed with your name.",
                    _offer(factory, project, persona, "mark_secret", {"finding": f, "verdict": "fixture"}),
                    "assessment_secret_mark")
    if re.search(r"(?i)\b(real|confirm)\b", question):
        return _out(project, f"I can confirm {f} as a real secret: it stays critical, whatever the rule thought.",
                    _offer(factory, project, persona, "mark_secret", {"finding": f, "verdict": "real"}),
                    "assessment_secret_mark")
    return None


def _dismiss(factory: Any, project: Any, persona: str, question: str, f: str, c: dict[str, Any]) -> dict | None:
    """A finding said not to be relevant here, with its reason (or the ask for one)."""
    if not re.search(r"(?i)\b(not relevant|irrelevant|noise|does not apply|doesn't apply)\b", question):
        return _restore(factory, project, persona, question, f, c)
    if secret_rule(c) and persona not in MARKERS:        # marking a secret not relevant is judging it (FR-ASP2)
        return _out(project, f"{f} is a secret finding: a {', '.join(MARKERS)} judges it, marked not relevant too. "
                             "Ask one of them, or switch persona if you hold one.", control="assessment_not_relevant")
    why = _BECAUSE.search(question)
    if not why:
        return _out(project, f"Say why {f} is not relevant to this project (\"... because ...\"): the reason is kept "
                             "with the verdict, and findings like it are proposed for the same.",
                    control="assessment_not_relevant")
    args = {"finding": f, "verdict": "not_relevant", "reason": why.group(1).strip()}
    return _out(project, f"I can mark {f} ({c.get('title')}) not relevant to this project, with your reason. It "
                         "leaves the priorities, and the open findings of the same kind are proposed for the same "
                         "verdict.", _offer(factory, project, persona, "dismiss_finding", args),
                "assessment_not_relevant")


def _restore(factory: Any, project: Any, persona: str, question: str, f: str, c: dict[str, Any]) -> dict | None:
    """A finding said to matter here after all: one put off for later, or one marked not relevant (FR-ASP2)."""
    if not re.search(r"(?i)\b(is relevant|relevant (now|here|after all)|matters (now|here)|bring (it )?back)\b",
                     question):
        return None
    was = ("put off for later by rule" if c.get("later") else "marked not relevant" if c.get("dismissed")
           else "open")
    return _out(project, f"I can bring {f} back as relevant to this project now (it is {was}): it counts in what is "
                         "worth acting on, signed with your name.",
                _offer(factory, project, persona, "dismiss_finding",      # the same verdict, given back (FR-ASP2)
                       {"finding": f, "verdict": "relevant", "summary": f"Bring {f} back as relevant to this project"}),
                "assessment_not_relevant")


def _act_on(factory: Any, project: Any, persona: str, question: str, view: dict[str, Any]) -> dict | None:
    """A named finding: marked not relevant (with the reason said), or a secret marked a fixture or confirmed real."""
    fid = _FID.search(question)
    if not fid:
        return None
    f = fid.group(1).upper()
    latest = view["latest"]
    known = {c.get("id"): c for c in (latest.get("checks") or []) + (latest.get("proposals") or [])}
    if f not in known:
        return _out(project, f"{latest['id']} has no finding {f}: its findings are listed in the Assessment view.")
    return (_secret(factory, project, persona, question, f, known[f])
            or _dismiss(factory, project, persona, question, f, known[f]))


def _runner(factory: Any, project: Any, persona: str, question: str) -> dict[str, Any]:
    cmd = _COMMAND.search(question)
    if not cmd:
        return _out(project, "Tell me the command this project runs its own tests with, in backticks, and where it "
                             "writes its results (\"map the runner `make gates` results in build/gates.xml\"). "
                             "Rihmasto never runs it: it reads the results file from the repository as this project's "
                             "test runs. Or press Map its test runner in the Assessment view.",
                    control="assessment_runner_map")
    command, results = cmd.group(1).strip(), _RESULTS.search(question)
    args = {"command": command, **({"results": results.group(1)} if results else {})}
    return _out(project, f"I can map `{command}` as this project's own test runner"
                         + (f", its results read from {results.group(1)}" if results else "")
                         + ". The next assessment reads them as its test runs.",
                _offer(factory, project, persona, "map_runner", args), "assessment_runner_map")


def answer(factory: Any, question: str, project: Any, persona: str, *, view: str | None = None) -> dict | None:
    """The rule's answer on what to act on and what is noise in the assessment, or None when not asked."""
    question = question.rsplit("\n\nNow: ", 1)[-1]
    if project is None or not (asks(question, view) or (view == "assessment" and _FID.search(question))):
        return None
    if re.search(r"(?i)\bmap\b.{0,40}\brunner\b", question):
        return _runner(factory, project, persona, question)
    from kernel.assess_cards import view as assessment_view

    v = assessment_view(project)
    if not v.get("latest"):
        return _out(project, f"{project.meta.get('title')} has not been assessed yet: press Assess now in the "
                             "Assessment view (or ask me to assess it), then ask again.", control="run_assessment")
    acted = _act_on(factory, project, persona, question, v)
    if acted or not asks(question, view):
        return acted
    head = v.get("headline") or {}
    steps = head.get("next") or []
    gaps = f"\n{head['gaps']}" if head.get("gaps") else ""
    out = _out(project, f"{head.get('act')}{gaps}\n{head.get('noise')}"
               + (f"\nNext, each with its own button below: {'; '.join(s['label'] for s in steps)}." if steps else "")
               + "\nTo mark a finding, say \"F-3 is not relevant because ...\", \"F-4 is a fixture\" or "
                 "\"F-4 is real\".")
    return out | {"steps": _steps(project, steps)}


ROUTED = {"align": "align"}      # a step's control is on the Assessment view unless it says otherwise


def _steps(project: Any, steps: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Each next step as Ask Rihma shows it: its words and its own button to the control (guide, don't describe)."""
    return [{"text": s["label"], "label": s["label"], "do": s["do"],
             "navigate": {"route": f"#/p/{project.pid}/{ROUTED.get(s['do'], 'assessment')}", "control": s["control"]}}
            for s in steps]


__all__ = ["answer", "asks", "headline"]
