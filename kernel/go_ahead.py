"""Look at the spec before building (FR-CHG1-AC-12; the owner's decision of 2026-11-24, "Agreed").

At explore and demo maturity no person approves the plan (kernel/plan.py approves it at pilot and up), so a
spec could go straight to the build. A project made by a person waits instead, once, before its first build:
a card "Look at the spec before building" asks for a single go-ahead, **Go** (I looked: build it) or **Skip**
(build without my look). What's next and the Inbox show it, and either verdict lets the run go on. Nothing
else waits on it: the questions, the gates and the change loop are as they were.

- A person turns it off for a project with "Build without waiting for me" (Project settings, or New project:
  `rihmasto new ... --build-without-waiting`, `rihmasto settings <pid> --build-without-waiting yes`). The
  setting is ``go_ahead`` in project.json: ``"wait"`` or ``"build"``, recorded as ``go_ahead_set``.
- New project (the cockpit, `rihmasto new`, Shape it in chat) sets it to wait unless the person says not to.
  A project made without saying (an older one, a validated concept, the scripted demo, which says ``build``
  outright: kernel/demo.py) builds as before.
- A delegation (kernel/delegation.py, the autopilot) may say Go by its rule ``go``.
- At pilot maturity and up, or whenever the plan needs a person's approval, the plan's approval is the look.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import Canon
from kernel.store import Project

MATURITIES = ("explore", "demo")
KIND = "go_ahead"
TITLE = "Look at the spec before building"
WAIT, BUILD = "wait", "build"
SAID = {"go": "looked at the spec: build it", "skip": "build it without looking at the spec"}


def waits_for_me(project: Project) -> bool:
    """Whether the project is set to wait for a person's go-ahead before its first build."""
    return project.meta.get(KIND) == WAIT


def choose(project: Project, *, wait: bool, person: str | None, persona: str | None, where: str,
           reason: str = "") -> None:
    """Set whether the project waits for a go-ahead, and record who set it, where and why. Turning it off
    withdraws an open go-ahead card: nothing waits on it any more."""
    project.update_meta(**{KIND: WAIT if wait else BUILD})
    project.log("go_ahead_set", {"wait": wait, "person": person, "persona": persona, "where": where,
                                 "reason": reason})
    if not wait:
        canon = Canon(project)
        for c in canon.cards(kind=KIND):
            canon.close(c["id"], f"{person or 'the factory'} set it to build without waiting")


def _built_once(project: Project) -> bool:
    from kernel.rewind import releases

    meta = project.meta
    return bool(meta.get("built")) or bool(releases(project)) or bool(project.ledger().of_kind("cell_ran"))


def asked(project: Project) -> bool:
    """Whether the run waits for a go-ahead now: set to wait, at explore or demo, a spec written and no build yet,
    and no approval of the plan, which is the look where one is needed. A project whose build module is off
    builds nothing here (kernel/modules.py), so nothing waits for a look before a build."""
    from kernel.modules import is_on
    from kernel.plan import required

    meta = project.meta
    return (waits_for_me(project) and meta.get("maturity") in MATURITIES and project.path("spec.json").exists()
            and meta.get("source_kind") != "adopted" and not _built_once(project) and not required(project)
            and is_on(project, "build"))


def open_card(project: Project) -> dict[str, Any] | None:
    """The open go-ahead card, or None. Reads only."""
    cards = Canon(project).cards(kind=KIND)
    return cards[0] if cards else None


def given(project: Project) -> dict[str, Any] | None:
    """The decided go-ahead card, or None."""
    cards = Canon(project).cards(state="decided", kind=KIND)
    return cards[-1] if cards else None


def _card(project: Project) -> dict[str, Any]:
    from kernel.plan import summary

    spec = project.read("spec.json") or {}
    body = (summary(spec) + "\n\nGo: you looked at the spec, build it. Skip: build it without your look. Either way "
            "the run goes on; nothing else waits on this. Turn it off for this project with Build without waiting "
            "for me in Project settings.")
    card = Canon(project).card(KIND, TITLE, body=body, blocking=True,
                               refs={"scope": "spec", "spec_version": int(project.meta.get("spec_version", 1)),
                                     "requirements": [r["id"] for r in spec.get("requirements") or []]})
    project.log("go_ahead_asked", {"card": card["id"], "maturity": project.meta.get("maturity")})
    return card


def gate(project: Project) -> dict[str, Any] | None:
    """None when the build may start; otherwise what the run waits on: the go-ahead card."""
    if not asked(project):
        return None
    done = given(project)
    if done is not None:
        if not any(r["event"]["payload"].get("card") == done["id"] for r in project.ledger().of_kind("go_ahead_given")):
            d = done["decision"]
            project.log("go_ahead_given", {"card": done["id"], "verdict": d["verdict"], "by": d["person"],
                                           "persona": d["persona"], "said": SAID.get(d["verdict"], d["verdict"])})
        return None
    card = open_card(project) or _card(project)
    return {"waiting_on": [card["id"]], "why": "a person looks at the spec before the first build: Go, or Skip"}


def impact_line(project: Project, without_waiting: bool) -> str:
    """What turning the setting on or off means, in the settings preview."""
    maturity = project.meta.get("maturity")
    if without_waiting:
        return "The factory builds the spec without waiting for you to look at it" + (
            "; an open Look at the spec card is withdrawn." if open_card(project) else ".")
    if maturity not in MATURITIES:
        return (f"At {maturity} maturity a person approves the plan before anything is built: that approval is the "
                "look. The go-ahead is asked at explore and demo.")
    if _built_once(project):
        return "It was built already: the go-ahead is asked only before the first build."
    return "Before the first build the factory waits for your go-ahead on the spec: Go or Skip, one click."
