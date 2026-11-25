"""Destinations on the command line and in Ask Rihma (FR-DST1), part of `rihmasto` (kernel/cli.py adds them).

    rihmasto destinations <pid> [--json]                       every place the capability goes, grouped
    rihmasto destinations <pid> --check --person P --persona X  a feedback round: probe, then bring back failures
    rihmasto publish <pid> --to <registry> [--release N] --person P --persona X

Ask Rihma answers "where is this running?" (and "where is it published?", "missä tämä pyörii?") from the same
model, with Take me there to the project's Destinations, and proposes delivering or publishing there: a
proposal only opens the view, where the person presses Deliver, Promote or Publish, signed.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from typing import Any

from kernel import destinations, destinations_feedback, publish
from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person

DELIVERERS = ("developer", "it", "operations", "product_owner", "business_owner")
WHERE = re.compile(r"\bwhere\s+(?:is|are|does|do|did|has)\s+(?:this|it|the\s+(?:capability|product|app|service))\b"
                   r"[^?.!]*\b(running|runs|run|deployed|hosted|live|published|used|go|gone)\b"
                   r"|\bdestinations?\b|\bwhat runs where\b"
                   r"|\bmissä\b[^?.!]*\b(pyörii|ajossa|julkaistu|käytössä|tuotannossa)\b", re.I)
# Asked to do it: "deliver this to test", "please publish it", "voitko julkaista tämän".
DO = re.compile(r"^\s*(?:(?:please|hey|rihma|ok|can you|could you|would you|voitko|voisitko)[,\s]+)*"
                r"(deliver|promote|publish|deploy|ship|julkaise|julkaista|toimita|toimittaa)\b", re.I)


# -- the command line -----------------------------------------------------------------------------------

def add_parsers(sub: Any) -> None:
    p = sub.add_parser("destinations", help="every place the capability goes: deployed, data, channels, published "
                                            "(kernel/destinations.py, FR-DST1)")
    p.add_argument("pid")
    p.add_argument("--json", action="store_true", help="the whole model as JSON")
    p.add_argument("--check", action="store_true", help="run a feedback round first: probe, record what changed")
    p.add_argument("--person", help="who asks for the round (with --check)")
    p.add_argument("--persona", choices=PERSONAS)
    q = sub.add_parser("publish", help="publish a release to a registry IT named in registries.json "
                                       "(kernel/publish.py, FR-DST1)")
    q.add_argument("pid")
    q.add_argument("--to", required=True, help="the registry's name in registries.json")
    q.add_argument("--release", type=int, help="the release (default: the latest that was not superseded)")
    q.add_argument("--person", required=True, help="who publishes")
    q.add_argument("--persona", required=True, choices=PERSONAS)


def text(view: dict[str, Any]) -> list[str]:
    """The model as lines a person reads in a terminal."""
    lines = [f"Destinations of {view['title']} ({view['project']}), maturity {view['maturity']}",
             view["summary"]["line"]]
    for group in destinations.GROUPS:
        rows = view["groups"][group]
        if not rows:
            continue
        lines.append("")
        lines.append(view["labels"][group])
        for d in rows:
            where = f" ({d['environment']})" if d.get("environment") else ""
            last = (d.get("last_delivery") or {}).get("what")
            lines.append(f"  [{d['state']}] {d['label']}{where}" + (f": {last}" if last else "")
                         + (f" at {d['url']}" if d.get("url") else ""))
            why = (d.get("health") or {}).get("why") if d["state"] == "failing" else None
            lines += [f"      {m}" for m in d.get("missing") or []] + ([f"      {why}"] if why else [])
    return lines


def _destinations(show: Callable[[Any], None], echo: Callable[[str], None]) -> Callable[[Any, Any], int]:
    def run(f: Any, a: argparse.Namespace) -> int:
        project = f.project(a.pid)
        if a.check:
            if not (a.person and a.persona):
                raise DecisionRefused("a feedback round is signed: give --person and --persona")
            out = destinations_feedback.check(project, person=a.person, persona=a.persona, via="command line")
            view = out["view"]
        else:
            view = destinations.view(project)
        if a.json:
            show(view)
        else:
            for line in text(view):
                echo(line)
        return 0
    return run


def _publish(show: Callable[[Any], None]) -> Callable[[Any, Any], int]:
    def run(f: Any, a: argparse.Namespace) -> int:
        out = publish.publish(f.project(a.pid), to=a.to, person=a.person, persona=a.persona, release=a.release)
        show(out)
        return 1 if out.get("state") == "failed" else 0
    return run


def handlers(show: Callable[[Any], None], echo: Callable[[str], None]) -> dict[str, Callable[[Any, Any], int]]:
    return {"destinations": _destinations(show, echo), "publish": _publish(show)}


# -- the cockpit's Deliver to test and Promote to production ---------------------------------------------

def request_delivery(project: Any, *, to: str, person: str, persona: str) -> dict[str, Any]:
    """What a person asked of a deployed destination, checked and recorded before its job starts: delivery
    advances by the maturity's plan, and production goes through IT's deploy gate as always."""
    from kernel.deliver import delivery_plan, plan_environments

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a delivery is asked for by a named person")
    if persona not in DELIVERERS:
        raise DecisionRefused(f"a {persona} may not start a delivery; {', '.join(DELIVERERS)} may")
    if to not in ("test", "production"):
        raise ValueError("to is test or production")
    envs = plan_environments(delivery_plan(project.meta.get("maturity") or "explore"))
    if to == "production" and "production" not in envs:
        raise ValueError(f"{project.pid} is at maturity {project.meta.get('maturity')}: its plan does not reach "
                         "production. Raise the maturity to production in its settings first")
    record = {"to": to, "environments": [e for e in envs if (e == "production") == (to == "production")],
              "by": person, "persona": persona,
              "then": "IT's deploy gate decides production" if to == "production" else "the plan's test steps"}
    project.log("destination_delivery_requested", record)
    return record


# -- Ask Rihma ------------------------------------------------------------------------------------------

def _line(d: dict[str, Any]) -> str:
    said = f"{d['label']}: {d['state']}"
    last = (d.get("last_delivery") or {}).get("what")
    if last:
        said += f", {last}"
    if d.get("url"):
        said += f" at {d['url']}"
    if d["state"] == "failing":
        said += f" ({(d.get('health') or {}).get('why') or d.get('note')})"
    return said


def chat_answer(project: Any, question: str) -> dict[str, Any] | None:
    """"Where is this running?" from the destinations, or None when the question is about something else."""
    if project is None or str(project.pid).startswith("_"):
        return None
    wants = bool(DO.search(question))
    if not WHERE.search(question) and not wants:
        return None
    view = destinations.view(project)
    deployed = [d for d in view["groups"]["deployed"]]
    parts = [f"{project.meta.get('title')}: {view['summary']['line']}"]
    parts += [_line(d) + "." for d in deployed]
    published = [d for d in view["groups"]["published"] if d["kind"] == "registry"]
    if published:
        parts.append("Registries: " + "; ".join(_line(d) for d in published) + ".")
    parts.append("From Destinations you can deliver to test, promote to production through IT's deploy gate, or "
                 f"publish to a registry (rihmasto publish {project.pid} --to <registry>). Nothing is done until "
                 "you press one.")
    route = f"#/p/{project.pid}/destinations"
    why = ("Deliver or publish there: each button is signed by you, and production waits on IT's deploy gate"
           if wants else "See every destination, and deliver, promote or publish from there")
    return {"answer": " ".join(parts), "navigate": {"route": route, "control": "destinations_map"},
            "propose": [{"action": "open", "args": {"route": route}, "why": why, "project": project.pid}],
            "dropped": [], "sources": [], "by": "map", "matches": ["destinations"]}
