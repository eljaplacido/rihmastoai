"""What each Rihma agent role is given right now: its context pack (FR-CTX1, docs/guides/context-and-data.md).

Each builder calls the same function the real code path calls to build the prompt (intake's panel, the spec, the
holdout author, the builder's envelope, the verifier), so a pack is the prompt that role would read in its next
call, cut into parts (kernel/context_parts.py). The surfaces a person or a coding agent talks to (Ask Rihma, goal
help, the agent channel, the hand-off brief and the MCP tools) are in kernel/context_surfaces.py.

Building a pack writes nothing and asks no model. A pack that cannot be built yet (no request, no contract) says
why instead.
"""

from __future__ import annotations

from typing import Any

from kernel import context_parts as cp

HOLDOUTS_OUT = {"what": "the holdout scenarios", "why": "they stay in the holdout custody, outside the project "
                                                        "folder; no builder, verifier or assistant is given them"}
SECRETS_OUT = {"what": "secret values", "why": "a file that may hold secrets is never read, and a prompt names a "
                                               "secret's setting, never its value (FR-DF2-AC-2)"}
OTHERS_OUT = {"what": "other projects", "why": "a pack is built from this project's records only"}


class Unavailable(LookupError):
    """A pack that cannot be built yet, and why."""


def _intake(factory: Any, project: Any, target: str | None, **_: Any) -> dict[str, Any]:
    from kernel import input_intake as inputs
    from kernel import intake as k
    from kernel.canon import PERSPECTIVES, Canon
    from kernel.profiles import profile_of

    source = project.read("source.json")
    reading = project.read("inputs.json")
    if not isinstance(source, dict) or not source.get("text") or not isinstance(reading, dict):
        raise Unavailable("the panel has not read a request yet: intake runs first")
    perspective = target if target in PERSPECTIVES else PERSPECTIVES[0]
    text, kind = str(source["text"]), str(source.get("kind") or "idea")
    prompt = k.perspective_prompt(project, perspective, text, kind, profile_of(project), inputs.panel_note(reading),
                                  k.panel_given(project, Canon(project), None))
    parts = cp.split(prompt, [
        (None, "The task", "kernel/intake.py _panel_prefix", "static", "instructions"),
        ("The request, verbatim", "The request", "source.json", "project", "request"),
        ("The factory read the request by rule", "What the request states, read by rule", "inputs.json", "project",
         "records"),
        ("\nTarget maturity", "The maturity", "project.json", "project", "records"),
        ("\nAlready given by the person who chose", "What the chosen outputs settle", "outputs.json", "project",
         "records"),
        ("\nAlready asked and settled", "Questions settled before", "canon/questions.json", "project", "records"),
        ("\nThe project's own conventions", "The project's own conventions", "material.json, agent_context.json",
         "project", "conventions"),
        ("Read the request from your perspective only.", "Instructions and the answer's shape", "kernel/intake.py",
         "project", "instructions"),
        ("You are the **", f"The {perspective} perspective", "kernel/intake.py PERSPECTIVE_VOICES, the profile, "
                                                             "the posture", "call", "instructions")])
    compressed = []
    if source.get("cut_from"):
        compressed.append({"what": "the request", "how": f"cut at {k.MAX_SOURCE_CHARS:,} of {source['cut_from']:,} "
                                                         "characters; the prompt and the ledger (request_cut) say so",
                           "why": "MAX_SOURCE_CHARS, the panel's reading budget"})
    cut = (project.read("material.json", None) or {}).get("cut") or []
    if cut:
        compressed.append({"what": "the folder's material", "how": f"{len(cut)} file(s) summarised or listed, not "
                                                                    "read in full (material.json names each)",
                           "why": "the request's budget, the most telling files first (kernel/material.py)"})
    return cp.pack(project.pid, "intake", label="Intake panel", role="analyst", surface="intake panel",
                   where="kernel/intake.py perspective_prompt", text=prompt, parts=parts, target=perspective,
                   compressed=compressed, excluded=[OTHERS_OUT, SECRETS_OUT, HOLDOUTS_OUT],
                   note="What the panel reads if intake runs again now (going back to the questions): five "
                        "perspectives share everything before \"You are the\", word for word.")


def _spec(factory: Any, project: Any, target: str | None, **_: Any) -> dict[str, Any]:
    from kernel.canon import Canon
    from kernel.integration_decl import guidance
    from kernel.spec import spec_prompt

    if not Canon(project).brief.strip():
        raise Unavailable("there is no brief yet: intake writes it")
    prompt = spec_prompt(project, target or None)
    parts = cp.split(prompt, [
        (None, "The task", "kernel/spec.py spec_prompt", "static", "instructions"),
        ("The stack is fixed:", "The stack", "kernel/spec.py STACK", "static", "facts"),
        ("The paved road IT runs", "The paved road's platform facts", "kernel/roads.py ROAD_FACTS", "static", "facts"),
        (guidance()[:40], "How integrations are declared", "kernel/integration_decl.py guidance", "static", "facts"),
        ("If the request names its own requirement ids", "Instructions and the answer's shape", "kernel/spec.py",
         "static", "instructions"),
        ("The brief:", "The brief", "canon/brief.md", "project", "request"),
        ("\nA person reviewed your previous plan", "Why the last plan was not approved", "the person's reason",
         "call", "records"),
        ("\nTarget maturity", "The maturity, the profile and the posture", "project.json, kernel/profiles.py, "
                                                                          "kernel/posture_rules.py", "project",
         "records"),
        ("Write at most", "How many requirements", "kernel/spec.py MAX_REQUIREMENTS", "project", "instructions")])
    return cp.pack(project.pid, "spec", label="Spec", role="analyst", surface="spec", where="kernel/spec.py "
                   "spec_prompt", text=prompt, parts=parts, target=target or None,
                   excluded=[OTHERS_OUT, HOLDOUTS_OUT, {"what": "the questions' discussion",
                                                        "why": "the brief carries each answer and assumption, "
                                                               "with its provenance; the panel's opinions stay on "
                                                               "the questions"}])


def _holdout_author(factory: Any, project: Any, target: str | None, **_: Any) -> dict[str, Any]:
    from kernel.compile import holdout_prompt
    from kernel.holdouts import secret_names, signing_rules

    spec, plan = project.read("spec.json"), project.read("checkplan.json")
    if not isinstance(spec, dict) or not isinstance(plan, dict):
        raise Unavailable("the project is not compiled yet: the check plan names the holdout criteria")
    rows = [r for r in plan.get("checks") or [] if r.get("kind") in ("holdout", "probe")]
    if not rows:
        raise Unavailable("no criterion is checked by a holdout or a probe")
    names = secret_names(project)
    prompt = holdout_prompt(spec, rows, None, names)
    parts = cp.split(prompt, [
        (None, "The task", "kernel/compile.py holdout_prompt", "static", "instructions"),
        ("All scenarios run one after another", "Instructions and the answer's shape", "kernel/compile.py",
         "static", "instructions"),
        ("The product: ", "The product and its requirements", "spec.json", "project", "records"),
        ("The product's HTTP interface", "The interface", "spec.json interface", "project", "records"),
        (signing_rules(names)[:40], "How a step signs a request", "kernel/holdouts.py signing_rules, the road's "
                                                                  "secret names", "project", "facts"),
        ("Write one scenario for each of these criteria:", "The criteria to check", "checkplan.json", "project",
         "records")])
    return cp.pack(project.pid, "holdout_author", label="Holdout author", role="holdout_author",
                   surface="holdout author", where="kernel/compile.py holdout_prompt", text=prompt, parts=parts,
                   excluded=[{"what": "the holdout scenarios already written",
                              "why": "in the holdout custody: the author "
                                                                               "writes them afresh, nothing is read "
                                                                               "back"},
                             {"what": "a re-authoring ruling's reason", "why": "kept in the holdout custody; it "
                                                                                "reaches the author only when a "
                                                                                "person rules a scenario defective"},
                             SECRETS_OUT, {"what": "the code", "why": "the author works from the spec, never from "
                                                                     "what the builder wrote"}])


def _task(project: Any, target: str | None) -> tuple[dict[str, Any], str, str]:
    """The contract, the task (the one named, else the next ready, else the first) and the base revision."""
    from kernel.dispatch import ready_tasks
    from kernel.graph_build import main_revision

    contract = project.read("contract.json")
    if not isinstance(contract, dict) or not contract.get("tasks"):
        raise Unavailable("there is no contract yet: the plan is compiled first")
    ids = [t["id"] for t in contract["tasks"]]
    if target and target not in ids:
        raise Unavailable(f"no task {target}: the contract has {', '.join(ids)}")
    ready = ready_tasks(project)
    base = main_revision(project)
    if base is None:
        raise Unavailable("the product has no repository yet")
    return contract, target or (ready[0] if ready else ids[0]), base


def _builder(factory: Any, project: Any, target: str | None, **_: Any) -> dict[str, Any]:
    from kernel.agent_context_use import HEADING
    from kernel.dispatch import envelope

    contract, task, base = _task(project, target)
    prompt = envelope(project, contract, task, base=base)
    parts = cp.split(prompt, [
        (None, "The task and its base revision", "contract.json, project.json, the product's main", "call",
         "records"),
        ("\n## Goal", "The goal and its criteria", "contract.json", "project", "records"),
        ("\n## The product's HTTP interface", "The interface", "spec.json", "project", "records"),
        ("\n## Sign-in", "The paved road's sign-in", "kernel/outputs.py builder_notes", "project", "facts"),
        ("\n## Scope", "The scope", "contract.json tasks", "project", "records"),
        ("\n" + HEADING, "The project's own conventions", "repo.git at the base revision", "project", "conventions"),
        ("\n## How the product is built", "How the product is built", "kernel/dispatch.py STACK_NOTES", "static",
         "facts"),
        ("\n## The paved road's platform facts", "The paved road's platform facts", "kernel/roads.py", "static",
         "facts"),
        ("\n## Rules", "The rules", "kernel/dispatch.py envelope", "static", "instructions"),
        ("\n## Objections from the last round", "Objections from the last round", "the last gate", "call",
         "records"),
        ("\n## Report", "The report", "kernel/dispatch.py envelope", "static", "instructions")])
    return cp.pack(project.pid, "builder", label="Builder envelope", role="builder", surface="builder envelope",
                   where="kernel/dispatch.py envelope", text=prompt, parts=parts, target=task,
                   excluded=[HOLDOUTS_OUT, {"what": "the holdout and probe criteria", "why": "the envelope counts "
                                                                                             "them and never states "
                                                                                             "them (kernel/gate.py "
                                                                                             "visible_criteria)"},
                             {"what": "decision reasons and the canon", "why": "the contract carries what was "
                                                                              "decided; who argued what stays in "
                                                                              "the canon"}, OTHERS_OUT],
                   note="Round 0 of the task's next build; a repair round adds the last gate's objections.")


def _verifier(factory: Any, project: Any, target: str | None, **_: Any) -> dict[str, Any]:
    from kernel.gate import verifier_prompt

    contract, task, base = _task(project, target)
    prompt = verifier_prompt(contract, task, base)
    parts = cp.split(prompt, [
        (None, "Instructions and the answer's shape", "kernel/gate.py verifier_prompt", "static", "instructions"),
        ("The change is for task", "The task and its base revision", "contract.json, the product's main", "call",
         "records"),
        ("\nRequirements:", "The task's requirements", "contract.json", "project", "records"),
        ("\nAcceptance criteria the change must meet:", "The task's criteria", "contract.json", "project",
         "records")])
    return cp.pack(project.pid, "verifier", label="Verifier", role="verifier", surface="verifier",
                   where="kernel/gate.py verifier_prompt", text=prompt, parts=parts, target=task,
                   excluded=[HOLDOUTS_OUT, {"what": "the holdout and probe criteria", "why": "judged against the "
                                                                                             "running release, out "
                                                                                             "of the code's sight"},
                             {"what": "the builder's report", "why": "the verifier judges the change itself, not "
                                                                     "what the builder says of it"}, OTHERS_OUT])


ROLE_PACKS = {"intake": _intake, "spec": _spec, "holdout_author": _holdout_author, "builder": _builder,
              "verifier": _verifier}


def builders() -> dict[str, Any]:
    """Every pack's builder: the roles here, then the surfaces (kernel/context_surfaces.py)."""
    from kernel.context_surfaces import SURFACE_PACKS

    return {**ROLE_PACKS, **SURFACE_PACKS}


LABELS = {"intake": "Intake panel", "spec": "Spec", "holdout_author": "Holdout author", "builder": "Builder envelope",
          "verifier": "Verifier", "assistant": "Ask Rihma", "goal": "Goal help", "channel": "Agent channel answer",
          "handoff": "Hand-off brief", "mcp": "MCP tools"}
PACKS = tuple(LABELS)


def build(factory: Any, project: Any, pack_id: str, *, target: str | None = None, persona: str | None = None,
          question: str | None = None) -> dict[str, Any]:
    """One pack as it would be built now. Raises Unavailable with the reason when it cannot be, and KeyError for
    a pack that does not exist."""
    fn = builders().get(pack_id)
    if fn is None:
        raise KeyError(f"no context pack {pack_id!r}: one of {', '.join(PACKS)}")
    out: dict[str, Any] = fn(factory, project, target, persona=persona, question=question)
    return out


def every(factory: Any, project: Any, *, persona: str | None = None) -> list[dict[str, Any]]:
    """Every pack of the project, in the order the work reaches them, or why one cannot be built yet."""
    out = []
    for pack_id in PACKS:
        try:
            out.append(build(factory, project, pack_id, persona=persona))
        except Unavailable as exc:
            out.append({"id": pack_id, "label": LABELS[pack_id], "unavailable": str(exc)})
    return out
