"""Stages 3 and 4: from the brief to a spec of requirements with acceptance criteria.

The analyst drafts the requirements. The kernel decides their ids and provenance by fixed rules,
never the model (FR-A3):
- a requirement resting on an answered question is customer-confirmed, decided by whoever
  answered it;
- one resting on the request itself is customer-endorsed, by whoever made the request;
- one resting on an assumption is an assumption;
- anything else is vendor-proposed.

A spec is not made while blocking questions are open. The send-back list goes to the people
who can answer (FR-A5).
"""

from __future__ import annotations

import re
from typing import Any

from kernel.canon import Canon
from kernel.intake import MATURITY_MEANING, SendBack, _ask_json, blocking_open
from kernel.people import is_person
from kernel.store import write_text

MAX_REQUIREMENTS = {"explore": 3, "demo": 5, "pilot": 7, "production": 8}
KINDS = ("test", "holdout", "probe")

STACK = """The product is built on the paved road: one Python 3 standard-library HTTP service
(`app/server.py` gives `route(method, pattern)`, `load_data(name, default)` and `save_data(name, value)`).
It serves a JSON API, plus plain HTML pages where people need a screen. Data is kept in JSON
files. Tests call `handle(method, path, body)` directly. No third-party packages, no external
database, no outbound network calls."""


def road_facts() -> str:
    """The paved road's platform facts as the analyst reads them (FR-DF1-AC-1): what no requirement
    may restate or contradict, and where a wish for less exposure belongs instead."""
    from kernel.roads import ROAD_FACTS

    return ("The paved road IT runs the product on owns these platform facts. No requirement may restate or\n"
            "contradict them. A wish for less exposure (\"localhost-only\", \"internal only\") is the road's\n"
            "rule: put it in \"out_of_scope\" as the road's job, never in a requirement.\n"
            + "\n".join(f"- {ROAD_FACTS[k]}" for k in ("bind", "exposure", "health")))


def spec_prompt(project, feedback: str | None = None) -> str:
    meta, canon = project.meta, Canon(project)
    n = MAX_REQUIREMENTS[meta["maturity"]]
    previous = ""
    if feedback:
        old = project.read("spec.json") or {"requirements": []}
        listing = "\n".join(f"- {r['id']}: {r['statement']}" for r in old["requirements"])
        previous = f"""
A person reviewed your previous plan and did not approve it. Their reason:
<<<
{feedback}
>>>
The previous plan's requirements were:
{listing}
Write a new plan that answers the reason. Keep what the reason does not touch.
"""
    from kernel.profiles import profile_of, spec_guidance

    return f"""You turn a brief into a software specification for a factory that builds and verifies it.

{canon.brief}
{previous}
Target maturity: **{meta['maturity']}**: {MATURITY_MEANING[meta['maturity']]}.
{spec_guidance(profile_of(project))}
The stack is fixed:
{STACK}

{road_facts()}

Write at most {n} requirements: the smallest set that delivers the goal at this maturity. If the
request names its own requirement ids (for example FR-KRIT-001), keep the id of each requirement
you take from it in "id"; otherwise leave "id" empty. Each requirement states one behaviour and
lists its sources: "request" if the request says it, a
question id (for example "Q-003") if an answer or assumption gave it, or "proposed" if neither
did. Give each requirement one to three acceptance criteria with given / when / then. The
"then" must be observable through the HTTP interface or a returned value.

Give each criterion a kind:
- "test": a unit test that calls handle() can check it. Use this for most criteria.
- "holdout": an end-to-end scenario checked against the running service by someone other
  than the builder. Use it for about one criterion in four, the ones that matter most to
  users.
- "probe": an operational property of the running service (for example "GET /health answers
  in under 500 ms").

Fix the product's HTTP interface in "interface": every endpoint with its method, path and
purpose, with path parameters in braces (for example "POST /loans/{{id}}/return"). The builder
and the people who write the end-to-end checks both work from this list, so every criterion
must use exactly these paths.

Answer with this JSON in a ```json block:
{{"title": "...", "summary": "two sentences",
  "users": ["who uses it"],
  "interface": [{{"method": "GET", "path": "/items", "purpose": "list items"}}],
  "requirements": [{{"id": "", "statement": "...", "sources": ["request"], "priority": "must",
     "acceptance": [{{"given": "...", "when": "...", "then": "...", "kind": "test"}}]}}],
  "out_of_scope": ["..."]}}
"""


METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_ENDPOINT = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s,;)\"'`]*)")
# Criteria written as calls to the product's handler: handle('POST', '/carriers/a/events', body).
_HANDLE = re.compile(r"""handle\(\s*['"](GET|POST|PUT|PATCH|DELETE)['"]\s*,\s*['"](/[^'"]*)['"]""")


def _generalise(path: str) -> str:
    """'/loans/7/return' -> '/loans/{id}/return': a literal id in a criterion is an example."""
    parts = [("{id}" if re.fullmatch(r"\d+|[0-9a-f]{8,}", seg) else seg) for seg in path.rstrip(".").split("/")]
    return "/".join(parts) or "/"


def interface_from_criteria(requirements) -> list:
    seen, out = set(), []
    for r in requirements:
        for c in r.get("acceptance", []):
            text = " ".join(str(c.get(k, "")) for k in ("given", "when", "then"))
            for method, path in _ENDPOINT.findall(text) + _HANDLE.findall(text):
                key = (method, _generalise(path.split("?")[0]))
                if key not in seen:
                    seen.add(key)
                    out.append({"method": key[0], "path": key[1], "purpose": "named in the spec's criteria"})
    return out


def look_of(canon) -> str:
    """The look chosen at intake: the first of the paved road's looks named in the answer."""
    from kernel.design_road import LOOKS
    from kernel.intake import LOOK_QUESTION

    for q in canon.questions():
        if q["text"] == LOOK_QUESTION and q.get("answer"):
            text = str(q["answer"].get("text", "")).lower()
            for look in LOOKS:
                if look in text:
                    return look
    return "neutral"


def interface_of(spec: dict) -> list:
    """The product's fixed HTTP interface: the spec's own, or (for specs written before the
    interface was part of the spec) the endpoints its criteria name."""
    return spec.get("interface") or interface_from_criteria(spec.get("requirements", []))


def render_interface(spec: dict) -> str:
    rows = interface_of(spec)
    if not rows:
        return "(no endpoints named yet)"
    return "\n".join(f"- {e['method']} {e['path']}: {e.get('purpose', '')}" for e in rows)


_QID = re.compile(r"^Q-\d+$")
_REQ_ID = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
_GENERATED = re.compile(r"R-\d+")  # an id the kernel gives, never one kept from the customer


def _provenance(sources, canon: Canon, requested_by) -> tuple[str, str | None]:
    answered = {q["id"]: q for q in canon.questions("answered")}
    assumed = {q["id"] for q in canon.questions("assumed")}
    for s in sources:
        if s in answered and is_person(answered[s]["answer"]["by"]):
            return "customer-confirmed", answered[s]["answer"]["by"]
    if "request" in sources and is_person(requested_by or ""):
        return "customer-endorsed", requested_by
    if any(s in assumed for s in sources):
        return "assumption", None
    return "vendor-proposed", None


def _requirement_id(item: dict[str, Any], reqs: list[dict[str, Any]]) -> str:
    """The customer's own id when the draft keeps one (so tests and the contract use their names),
    otherwise the next R-n."""
    given = str(item.get("id") or "").strip().upper()
    if _REQ_ID.match(given) and given not in {r["id"] for r in reqs} and not _GENERATED.fullmatch(given):
        return given
    return f"R-{1 + sum(1 for r in reqs if _GENERATED.fullmatch(r['id']))}"


def _sources(item: dict[str, Any], rid: str, known: set[str], dropped: list[dict[str, Any]]) -> list[str]:
    """A requirement's sources: the request, a question the canon holds, or "proposed". A source
    naming no question in the canon, or nothing a source can be, is dropped and recorded."""
    sources: list[str] = []
    for s in (str(x).strip() for x in (item.get("sources") or [])):
        if s in ("request", "proposed") or s in known:
            sources.append(s)
        elif s:
            why = "names no question in the canon" if _QID.match(s) else "is not the request, a question or proposed"
            dropped.append({"what": "source", "requirement": rid, "source": s[:80], "why": why})
    return sources or ["proposed"]


def _criteria_of(item: dict[str, Any], rid: str, dropped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most three criteria, each with a then; the first is a visible test when none is. What is
    left out is recorded."""
    criteria: list[dict[str, Any]] = []
    for n, ac in enumerate(item.get("acceptance") or [], 1):
        if n > 3:
            then = str(ac.get("then", "")).strip()[:200] if isinstance(ac, dict) else ""
            dropped.append({"what": "criterion", "requirement": rid, "item": n, "then": then,
                            "why": "beyond the three criteria a requirement may have"})
        elif not isinstance(ac, dict) or not str(ac.get("then", "")).strip():
            dropped.append({"what": "criterion", "requirement": rid, "item": n, "why": "it has no then"})
        else:
            kind = ac.get("kind") if ac.get("kind") in KINDS else "test"
            criteria.append({"id": f"{rid}-AC-{len(criteria) + 1}", "given": str(ac.get("given", "")).strip(),
                             "when": str(ac.get("when", "")).strip(), "then": str(ac["then"]).strip(),
                             "kind": kind})
    if criteria and not any(c["kind"] == "test" for c in criteria):
        criteria[0]["kind"] = "test"  # every requirement gets at least one visible check
    return criteria


def _requirement(item: Any, n: int, reqs: list[dict[str, Any]], canon: Canon, requested_by: str | None,
                 dropped: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The draft's ``n``-th requirement with a kernel id, rule-based provenance and usable criteria,
    or None (recorded in ``dropped``) when it has no statement or no usable criterion."""
    statement = str(item.get("statement", "")).strip() if isinstance(item, dict) else ""
    if not statement:
        dropped.append({"what": "requirement", "item": n, "why": "it has no statement"})
        return None
    rid = _requirement_id(item, reqs)
    lost: list[dict[str, Any]] = []  # kept only when the requirement is: its own drop says it all
    sources = _sources(item, rid, {q["id"] for q in canon.questions()}, lost)
    criteria = _criteria_of(item, rid, lost)
    if not criteria:
        dropped.append({"what": "requirement", "item": n, "statement": statement[:200],
                        "why": "it has no usable acceptance criterion"})
        return None
    dropped.extend(lost)
    prov, by = _provenance(sources, canon, requested_by)
    req = {"id": rid, "statement": statement, "sources": sources,
           "priority": item.get("priority") if item.get("priority") in ("must", "should", "could") else "must",
           "provenance": prov, "acceptance": criteria}
    if by:
        req["decided_by"] = by
    return req


def normalize(project, raw: dict) -> dict:
    """Give the analyst's draft fixed ids and rule-based provenance. What cannot be used is dropped,
    never silently: the spec's ``dropped`` list names each requirement, criterion and source left out
    and why (FR-P3-AC-2)."""
    meta, canon = project.meta, Canon(project)
    requested_by = (project.read("source.json", {}) or {}).get("requested_by")
    limit = MAX_REQUIREMENTS[meta["maturity"]]
    reqs: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for n, item in enumerate(raw.get("requirements") or [], 1):
        if n > limit:
            statement = str(item.get("statement", "")).strip()[:200] if isinstance(item, dict) else ""
            dropped.append({"what": "requirement", "item": n, "statement": statement,
                            "why": f"beyond the {limit} requirements a {meta['maturity']} spec may have"})
            continue
        req = _requirement(item, n, reqs, canon, requested_by, dropped)
        if req is not None:
            reqs.append(req)
    from kernel.input_intake import keep_authors

    reqs = keep_authors(project, reqs, limit, dropped)   # an expert's own ids and wording (docs/guides/inputs.md)
    if not reqs:
        raise ValueError("the analyst's draft holds no usable requirement")
    spec = {"title": str(raw.get("title") or meta["title"]).strip(), "summary": str(raw.get("summary", "")).strip(),
            "users": [str(u) for u in (raw.get("users") or [])][:8], "maturity": meta["maturity"],
            "stack": "python-stdlib-http", "look": look_of(canon), "interface": _interface(raw, reqs),
            "requirements": reqs, "out_of_scope": [str(o) for o in (raw.get("out_of_scope") or [])][:12]}
    if dropped:
        spec["dropped"] = dropped
    return spec


def _interface(raw: dict[str, Any], reqs: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The draft's HTTP interface, or (when it gives none that can be used) the endpoints its
    criteria name."""
    interface = []
    for e in raw.get("interface") or []:
        if isinstance(e, dict) and str(e.get("method", "")).upper() in METHODS and str(e.get("path", "")).startswith("/"):
            interface.append({"method": str(e["method"]).upper(), "path": str(e["path"]).strip(),
                              "purpose": str(e.get("purpose", "")).strip()})
    return interface or interface_from_criteria(reqs)


def render_spec_md(spec: dict) -> str:
    lines = [f"# Spec: {spec['title']}", "", spec.get("summary", ""), "",
             f"Maturity: **{spec['maturity']}**. Stack: {spec['stack']}.", "",
             "## Interface", "", render_interface(spec), ""]
    for r in spec["requirements"]:
        who = f", decided by {r['decided_by']}" if r.get("decided_by") else ""
        lines += [f"## {r['id']} ({r['priority']}, {r['provenance']}{who})", "", r["statement"], "",
                  f"Sources: {', '.join(r['sources'])}", ""]
        for c in r["acceptance"]:
            lines.append(f"- **{c['id']}** [{c['kind']}] given {c['given']}; when {c['when']}; then {c['then']}")
        lines.append("")
    if spec.get("out_of_scope"):
        lines += ["## Out of scope", ""] + [f"- {o}" for o in spec["out_of_scope"]] + [""]
    from kernel.roads import conflict_lines

    conflicts = conflict_lines(spec)
    lines += ["## Conflicts with the paved road", "", *conflicts, ""] if conflicts else []
    if spec.get("dropped"):
        lines += ["## Dropped from the analyst's draft", ""]
        for d in spec["dropped"]:
            where = d.get("requirement") or f"requirement {d.get('item')}"
            what = d.get("source") or d.get("statement") or d.get("then") or ""
            lines.append(f"- {d['what']} ({where}{', ' + what if what else ''}): {d['why']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def make_spec(project, *, model, feedback: str | None = None) -> dict:
    from kernel.confidential import require_local

    require_local(project, ("analyst",), where="spec")     # a confidential project's spec stays on local models
    still_open = blocking_open(project)
    if still_open:
        project.log("send_back", {"questions": [q["id"] for q in still_open]})
        raise SendBack(still_open)
    from kernel.profiles import settle_profile_question
    from kernel.roads import road_conflicts

    settle_profile_question(project)  # a person's answer to "which kind of work is this?" shapes the spec
    raw = _ask_json(model, spec_prompt(project, feedback))
    spec = normalize(project, raw)
    conflicts = road_conflicts(spec)
    if conflicts:  # the plan review flags them for a person (kernel/plan.py)
        project.log("spec_road_conflicts", {"conflicts": [{k: c[k] for k in ("requirement", "criterion", "fact")}
                                                          for c in conflicts]})
    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    project.update_meta(stage=4)
    project.log("spec_written", {"requirements": len(spec["requirements"]),
                                 "criteria": sum(len(r["acceptance"]) for r in spec["requirements"]),
                                 "dropped": len(spec.get("dropped", []))})
    return spec
