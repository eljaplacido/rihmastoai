"""Plug in an existing project, and start from documents: the walkthroughs that read what a person has
(kernel/walkthrough.py, FR-WLK1).

Plug in: the folder or git address, checked and scanned (nothing kept), the title, whether it is confidential
(a hosted role is named, with Set up a model as a detour), the intent and the posture, then "Adopt <title>":
the cockpit's own adoption, run as a job the chat waits on, and the result: the baseline, the kind of work
proposed (or the which-kind question as buttons), What's next and Open the project. A folder with no code
is offered as documents for a new project instead.

Start from documents: a folder of material or one file, scanned, then "Create <title>": the cockpit's own New
project, its intake a job the chat waits on, and the first questions as buttons.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel import walkthrough as wk
from kernel import walkthrough_flows as wf


class PlugIn(wf.Flow):
    name, label, control = "plug_in", "Plug in an existing project", "walk_plug_in"
    about = "a folder or a git address: checked, scanned, adopted as a job, and what comes next"
    intro = ("Let's plug in your project. I check the folder, scan it and show you what I found; you choose how "
             "Rihmasto works with it, and nothing is adopted until you press Adopt.")
    first = "source"
    steps = ("source", "title", "confidential", "intent", "posture", "confirm", "adopting", "kind", "done")
    roles = ("analyst", "holdout_author", "builder", "verifier")
    after_confidential = "intent"
    hosted_means = ("It is adopted all the same, but every model call for it is refused until those roles are on a "
                    "local model.")

    def ask_source(self, ctx: wk.Ctx) -> dict[str, Any]:
        before = wk.recent(ctx.factory, ctx.person)
        return ctx.say("Which project? Type the path of its folder on this machine, or a git address (https://...)."
                       + (" Or pick one you gave before." if before else ""),
                       options=[{"id": f"recent:{i}", "label": p} for i, p in enumerate(before)],
                       input={"kind": "path", "placeholder": "a folder path, or https://host/repo.git"})

    def take_source(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        from kernel.adopt import AdoptionRefused, check_source

        choice = str(reply.get("choice") or "")
        before = wk.recent(ctx.factory, ctx.person)
        text = before[int(choice[7:])] if choice.startswith("recent:") and choice[7:].isdigit() \
            and int(choice[7:]) < len(before) else wf.unquote(reply.get("text"))
        if not text:
            return None
        ctx.data.pop("scan", None)
        if "://" in text or wf.SSH.match(text):
            try:
                check_source(text)
            except AdoptionRefused as exc:
                ctx.say(f"I cannot adopt from that address: {exc}.")
                return None
            ctx.data.update(source=text, kind="url", title=wf.title_from(text))
            wk.remember(ctx.factory, ctx.person, text)
            ctx.say("A git address: Rihmasto clones it without credentials when you adopt it, so there is nothing to "
                    "scan here first.")
            return "title"
        path = wf.scan_folder(ctx, text)
        if path is None:
            return None
        ctx.data.update(kind="git" if ctx.data["scan"]["git"] else "folder", title=wf.title_from(str(path)))
        if not ctx.data["scan"]["code"] and not ctx.data["scan"]["git"]:   # a repository is adopted as it is
            return "nocode"
        return "title"

    def ask_nocode(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("This folder holds no code, only documents: there is nothing to adopt. You can start a new "
                       "project from it instead, with its documents as the material.",
                       options=[{"id": "documents", "label": "Start a new project from it"},
                                {"id": "another", "label": "Give another folder"}])

    def take_nocode(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        got = wf.pick(ctx, reply, wk.offered(ctx.w))
        if got == "documents":
            ctx.w["switch"] = {"name": "documents", "said": ctx.data["source"]}
            ctx.w["outcome"] = "switched"
            return "done"
        return "source" if got == "another" else None

    def ask_intent(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("What should Rihmasto do with it?",
                       options=[{"id": i, "label": label, "hint": hint} for i, label, hint in wf.INTENTS])

    def take_intent(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        got = wf.pick(ctx, reply, [{"id": i, "label": label, "keys": hint} for i, label, hint in wf.INTENTS])
        if got is None:
            return None
        ctx.data["intent"] = got
        return "posture"

    def ask_confirm(self, ctx: wk.Ctx) -> dict[str, Any]:
        d = ctx.data
        s = d.get("scan") or {}
        lines = [f"From {d['source']}" + (" (a git repository)" if d.get("kind") == "git" else
                                         " (a git address)" if d.get("kind") == "url" else
                                         " (not a git repository: its files are copied into a baseline repository; "
                                         "your folder is never changed)"),
                 "Intent: " + dict((i, label) for i, label, _ in wf.INTENTS)[d["intent"]],
                 "Posture: " + wf.posture_label(d.get("posture")),
                 "Confidential: " + ("yes, local models only" if d.get("confidential") else "no")]
        if s.get("excluded"):
            lines.append(f"{s['excluded']} files left out as you unticked them")
        args = {"title": d["title"], "source": d["source"], "intent": d["intent"], "posture": d.get("posture"),
                "exclude": list(d.get("exclude") or []), "confidential": bool(d.get("confidential"))}
        return ctx.say("Ready. Nothing has been done yet. Adopting runs as a job: Rihmasto reads the code, runs "
                       "its own tests once for a baseline and records what it found.",
                       proposal={"action": "adopt", "label": f"Adopt {d['title']}", "lines": lines, "args": args})

    def done_confirm(self, ctx: wk.Ctx, prop: dict[str, Any], result: dict[str, Any]) -> str:
        job = result.get("job") or {}
        ctx.data["job"] = job.get("id")
        if job.get("state") == "done" and job.get("made"):      # the command line adopts at once
            return self.finished(ctx, job)
        return "adopting"

    def ask_adopting(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Adopting. I show the progress here and say when it is done; you may close the chat and "
                       "come back.", progress={"job": ctx.data.get("job"), "kind": "adopt"})

    def take_adopting(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        job = self.wait_for(reply, ctx, "adopting")
        if job is None:
            return None
        if job.get("state") != "done" or not job.get("made"):
            ctx.say(f"The adoption did not finish: {wf.job_error(job)}. Nothing was adopted. You can try again.")
            return "confirm"
        return self.finished(ctx, job)

    def finished(self, ctx: wk.Ctx, job: dict[str, Any]) -> str:
        project = ctx.factory.project(job["made"])
        ctx.data["project"] = project.pid
        base = project.read("baseline.json") or {}
        kind = (project.read("adopted.json") or {}).get("profile") or {}
        from kernel.profiles import PROFILES

        label = PROFILES.get(str(kind.get("profile")), {}).get("label", kind.get("profile"))
        line, links = wf.next_links(project)
        unsure = kind.get("by") == "rule" and kind.get("confidence") != "clear" and kind.get("candidates")
        on_way, way_links = journey_next(ctx.factory, project, ctx.persona)
        ctx.say(f"{project.meta.get('title')} is adopted. Its baseline: {base.get('verdict', 'not measured')}"
                + (f" ({base['reason']})" if base.get("reason") else "") + ". "
                + (f"The kind of work: {label}, as I read the README and the title." if not unsure else
                   "I could not tell the kind of work for sure.") + f" {line}.{on_way}",
                result={"project": project.pid, "baseline": {k: base.get(k) for k in ("verdict", "reason")},
                        "kind": kind},
                links=[wf.open_project(project.pid), *way_links, *wf.adopted_links(project.pid), *links])
        ctx.data["kind"] = kind
        return "kind" if unsure else "done"

    def _kinds(self, ctx: wk.Ctx) -> list[dict[str, Any]]:
        from kernel.profiles import PROFILES

        kind = ctx.data.get("kind") or {}
        ids = [str(kind.get("profile")), *[str(c) for c in kind.get("candidates") or []]]
        return [{"id": k, "label": PROFILES[k]["label"]} for k in dict.fromkeys(ids) if k in PROFILES]

    def ask_kind(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Which kind of work is it? The kind decides what the factory asks and checks.",
                       options=self._kinds(ctx), final=True)

    def take_kind(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        got = wf.pick(ctx, reply, self._kinds(ctx))
        if got is None:
            return None
        if got == (ctx.data.get("kind") or {}).get("profile"):
            ctx.say("It stays as it is.")
            return "done"
        ctx.data["chosen_kind"] = got
        return "setkind"

    def ask_setkind(self, ctx: wk.Ctx) -> dict[str, Any]:
        from kernel.profiles import PROFILES

        k = ctx.data["chosen_kind"]
        return ctx.say("I propose to change the kind of work in Project settings.", proposal={
            "action": "set_kind", "label": f"Set the kind to {PROFILES[k]['label']}",
            "lines": [f"Project {ctx.data['project']}", f"Kind of work: {PROFILES[k]['label']}"],
            "args": {"project": ctx.data["project"], "kind": k}}, final=True)

    def done_setkind(self, ctx: wk.Ctx, prop: dict[str, Any], result: dict[str, Any]) -> str:
        return "done"

    def ask_done(self, ctx: wk.Ctx) -> dict[str, Any]:
        if ctx.w.get("outcome") == "switched":
            return ctx.say("Starting from documents with that folder.", final=True)
        pid = ctx.data.get("project")
        if not pid:
            return ctx.say("Done.", final=True)
        on_way, way_links = journey_next(ctx.factory, ctx.factory.project(pid), ctx.persona)
        return ctx.say("Done. The project is in the factory now." + (on_way or " Next, align it with its "
                       "repository's own specs and tests, and see the AI tools it uses."), final=True,
                       links=[wf.open_project(pid), *way_links, *wf.adopted_links(pid)])


class Documents(wf.Flow):
    name, label, control = "documents", "Start from documents", "walk_documents"
    about = "a spec or a folder of material: scanned, made a new project, and its first questions"
    intro = ("Let's start a new project from your documents. I scan them and show what I would read; nothing is "
             "created until you press Create.")
    first = "source"
    steps = ("source", "title", "confidential", "posture", "confirm", "intake", "done")
    roles = ("analyst",)
    hosted_means = "A confidential project is refused while the analyst's model is hosted."
    hosted_go = "Go on without confidential"

    def ask_source(self, ctx: wk.Ctx) -> dict[str, Any]:
        before = wk.recent(ctx.factory, ctx.person)
        return ctx.say("Which documents? Type the path of a folder of material (a spec, notes, slides) or of one "
                       "file on this machine.", options=[{"id": f"recent:{i}", "label": p}
                                                         for i, p in enumerate(before)],
                       input={"kind": "path", "placeholder": "a folder or a file path"})

    def take_source(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        choice = str(reply.get("choice") or "")
        before = wk.recent(ctx.factory, ctx.person)
        text = before[int(choice[7:])] if choice.startswith("recent:") and choice[7:].isdigit() \
            and int(choice[7:]) < len(before) else wf.unquote(reply.get("text"))
        if not text:
            return None
        ctx.data.pop("scan", None)
        path = Path(text).expanduser()
        if path.is_file():
            return self._file(ctx, path)
        folder = wf.scan_folder(ctx, text)
        if folder is None:
            return None
        if not ctx.data["scan"]["chars"]:
            ctx.say("There is nothing in it Rihmasto can read: every file is listed or skipped. Give another folder.")
            return None
        ctx.data.update(folder=True, title=wf.title_from(str(folder)))
        return "title"

    def _file(self, ctx: wk.Ctx, path: Path) -> str | None:
        from kernel.shape import ShapeRefused, read_material
        from kernel.source_guard import SourceRefused, check_folder

        try:
            check_folder(str(path.resolve().parent), ctx.persona)
            text = read_material(path.name, path.read_bytes())
        except SourceRefused as exc:
            ctx.say(wf.refused_folder(exc))
            return None
        except (ShapeRefused, OSError) as exc:
            ctx.say(f"{exc}.")
            return None
        ctx.data.update(source=str(path.resolve()), text=text[:200_000], folder=False, title=wf.title_from(path.stem))
        wk.remember(ctx.factory, ctx.person, str(path.resolve()))
        ctx.say(f"I read {path.name}: {len(text):,} characters. Nothing has been sent or recorded.")
        return "title"

    def take_hosted(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        if wf.pick(ctx, reply, wk.offered(ctx.w)) != "go":
            return None
        ctx.data["confidential"] = bool(ctx.data.get("confidential")) and not wf.hosted_roles(self.roles)
        return self.after_confidential

    def ask_confirm(self, ctx: wk.Ctx) -> dict[str, Any]:
        d = ctx.data
        lines = [f"From {d['source']}" + (" (a folder, as scanned)" if d.get("folder") else " (one file)"),
                 "Posture: " + wf.posture_label(d.get("posture")),
                 "Confidential: " + ("yes, local models only" if d.get("confidential") else "no")]
        args = {"title": d["title"], "source": d["source"] if d.get("folder") else d.get("text", ""),
                "folder": bool(d.get("folder")), "exclude": list(d.get("exclude") or []),
                "confidential": bool(d.get("confidential")), "posture": d.get("posture")}
        return ctx.say("Ready. Nothing has been done yet. Creating the project starts its intake as a job: the "
                       "analyst reads the material and asks only what it does not say.",
                       proposal={"action": "new_project", "label": f"Create {d['title']}", "lines": lines,
                                 "args": args})

    def done_confirm(self, ctx: wk.Ctx, prop: dict[str, Any], result: dict[str, Any]) -> str:
        ctx.data["project"] = (result.get("project") or {}).get("id")
        ctx.data["job"] = (result.get("job") or {}).get("id")
        return intake_done(ctx, result["job"]) if (result.get("job") or {}).get("state") == "done" else "intake"

    def ask_intake(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ask_intake(ctx)

    def take_intake(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        job = self.wait_for(reply, ctx, "reading the material")
        return None if job is None else intake_done(ctx, job)

    def ask_done(self, ctx: wk.Ctx) -> dict[str, Any]:
        pid = ctx.data.get("project")
        return ctx.say("Done. Answer the questions in the project, or let Rihma assume what is not blocking.",
                       final=True, links=[wf.open_project(pid)] if pid else None)


def journey_next(factory: Any, project: Any, persona: str) -> tuple[str, list[dict[str, Any]]]:
    """After an adoption, the next step of feeding in a project (FR-JRN1: the assessment), and its button with
    Guide me through the rest; nothing when the journey has no step left."""
    from kernel import journey_state as js

    prog = js.progress(factory, "brownfield", project=project, persona=persona)
    step = next((s for s in prog["steps"] if s["id"] == prog["next"]), None)
    if step is None:
        return "", []
    act = step["action"]
    first = {"label": step["button"], "route": act.get("route"), "control": act.get("control"), "do": act.get("do"),
             "project": project.pid, "step": step["id"]}
    guide = {"label": "Guide me through the rest", "route": f"#/p/{project.pid}/overview", "guide": "brownfield",
             "project": project.pid}
    said = step.get("not_yet") or step["title"]
    return (f" {said[:1].upper()}{said[1:]}: that is next, because {step['why'][:1].lower()}{step['why'][1:]}",
            [first, guide])


def ask_intake(ctx: wk.Ctx) -> dict[str, Any]:
    return ctx.say(f"Created {ctx.data.get('project')}. The intake is running: I say when its questions are ready.",
                   progress={"job": ctx.data.get("job"), "kind": "intake"})


def intake_done(ctx: wk.Ctx, job: dict[str, Any]) -> str:
    """The intake job ended: its first questions as buttons, or why it did not finish and What's next."""
    project = ctx.factory.project(ctx.data["project"])
    if job.get("state") != "done":
        line, links = wf.next_links(project)
        ctx.say(f"The intake did not finish: {wf.job_error(job)}. {line}.",
                links=[wf.open_project(project.pid), *links])
        return "done"
    links = wf.questions_links(project)
    ctx.say((f"The intake is done: {len(links)} question{'s' if len(links) != 1 else ''} wait on a person. Press one "
             "to answer it." if links else "The intake is done, and it asks nothing: the material said enough."),
            links=[*links, wf.open_project(project.pid)])
    return "done"


FLOWS = {"plug_in": PlugIn(), "documents": Documents()}
