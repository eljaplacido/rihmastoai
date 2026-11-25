"""A factory home for the review (FR-REV1): a night's work by agents and automations, from real records.

``build(factory, tmp)`` makes it, with git: on "Equipment loans" (assume mode, so the factory assumed answers)
a builder cell built and merged T-001 through the gate, T-002's lazy cell failed its gate and escalated, a
model endpoint failed once, a release went to the demo environment, and a model run was priced. On "Room
bookings" (socratic) an autopilot run assumed an open question in Aino's name, by its delegation. "Order
tracker" is a repository attached from a developer's machine, whose latest commit the gate judged when its
owner asked from her IDE. Every record is the kernel's own, written by the kernel's own functions where the
kernel has one; the IDE gate's record has the shape kernel/gate_external.py gives it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from factory_fakes import good_cell, lazy_cell, model, no_findings

from kernel import autopilot, delegation
from kernel.attach import attach
from kernel.canon import Canon
from kernel.compile import compile_project
from kernel.dispatch import build_task, gate_record
from kernel.intake import intake
from kernel.lanes import Lanes
from kernel.spec import make_spec
from kernel.store import write_json

IDEA = "Our team keeps losing track of who borrowed the drills and laptops. We want a simple way to lend and return things."
ROOMS = "People double-book the meeting rooms. We want to see which rooms are free and book one."
AINO = "Aino Virtanen"
BEA = "Bea Lund"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          check=True, capture_output=True, text=True)
    return done.stdout.strip()


def ide_repo(folder: Path) -> tuple[str, str]:
    """A developer's repository with two commits: the second is the change she asks the gate about."""
    folder.mkdir(parents=True, exist_ok=True)
    _git(folder, "init", "-q", "-b", "main")
    (folder / "orders.py").write_text("def total(rows):\n    return sum(rows)\n", encoding="utf-8", newline="\n")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "first")
    base = _git(folder, "rev-parse", "HEAD")
    (folder / "orders.py").write_text("def total(rows):\n    return sum(r for r in rows if r > 0)\n\n\n"
                                      "def count(rows):\n    return len(rows)\n", encoding="utf-8", newline="\n")
    (folder / "README.md").write_text("# Orders\n", encoding="utf-8", newline="\n")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "count orders")
    return base, _git(folder, "rev-parse", "HEAD")


def build(factory: Any, tmp: Path) -> dict[str, Any]:
    lanes = Lanes(tmp / "lanes", size=1)
    loans = factory.new_project("Equipment loans", mode="assume", maturity="demo")
    intake(loans, IDEA, model=model(), requested_by=AINO)
    make_spec(loans, model=model())
    compile_project(loans)
    build_task(loans, "T-001", lanes=lanes, cell_runner=good_cell, verifier_runner=no_findings)
    build_task(loans, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings, max_rounds=0)
    loans.log("apparatus_failure", {"where": "pipeline", "error": "the analyst's endpoint timed out"})
    revision = (loans.read("tasks.json") or {})["T-001"]["revision"]
    write_json(loans.path("releases", "1.json"), {"release": 1, "maturity": "demo", "state": "done",
                                                    "revision": revision, "environments": ["demo"], "steps": []})
    loans.log("release_done", {"release": 1, "revision": revision, "environment": "demo"})
    loans.log("gnomon_run", {"run": "run-1", "task": "T-001", "round": 0, "role": "builder", "model": "fake-builder",
                             "verdict": "not measured", "tokens": {"in": 12000, "out": 3400},
                             "cost": {"measured": True, "kind": "cloud", "amount": 0.0421, "currency": "USD"}})

    rooms = factory.new_project("Room bookings", mode="socratic", maturity="demo")
    intake(rooms, ROOMS, model=model(), requested_by=BEA)
    autopilot.start(rooms, until="8h", kinds=["question"], person=AINO, persona="developer")
    waiting = [c["id"] for c in Canon(rooms).cards(kind="question")]
    decided = delegation.consult(rooms, waiting[:1])

    base, head = ide_repo(tmp / "order-tracker")
    orders = attach(factory, "Order tracker", repo=tmp / "order-tracker", person=AINO, persona="developer")

    class _Result:      # what kernel.gate returns, as far as gate_record reads it
        verdict, head, objections = "failed", "", ["tests: 1 failed (test_count)"]
        signals: list[Any] = []

    result = _Result()
    result.head = head
    orders.log("gate", gate_record(f"repo:{head[:12]}", 0, result, repository=str(tmp / "order-tracker"), base=base,
                                   person=AINO, persona="developer", asked_as="gate my code",
                                   uncommitted_left_out=False))
    return {"loans": loans, "rooms": rooms, "orders": orders, "decided": decided, "base": base, "head": head,
            "revision": revision}
