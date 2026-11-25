"""What every walkthrough (kernel/walkthrough.py, FR-WLK1) reads replies and folders with, and the steps the
walkthroughs that read a folder share (kernel/walkthrough_adopt.py, kernel/walkthrough_more.py).

A step's ``ask_<step>`` says the question in the chat, ``take_<step>`` reads the reply and returns the next
step (or None to stay), and ``done_<step>`` takes the result of the proposal the person confirmed. A folder is
checked against the folders the cockpit may read (kernel/source_guard.py) and scanned (kernel/material.py,
``preview``: nothing is kept); the scan's counts, the AI-tool setup found, the code's languages and what was
skipped as secret-looking are shown in the chat, and the full map opens from there.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kernel import walkthrough as wk

YES = {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "true", "kyllä", "kylla", "joo", "juu", "jep", "k", "on",
       "confidential", "luottamuksellinen"}
NO = {"no", "n", "nope", "not", "false", "ei", "e", "en", "nah"}
SSH = re.compile(r"^[\w.+-]+@[\w.-]+:")
# Files and folders by which an AI coding tool's setup is recognised in a project, and the tool's name.
AI_SETUP = (("CLAUDE.md", "Claude Code"), (".claude/", "Claude Code"), ("AGENTS.md", "AGENTS.md (Codex, OpenCode)"),
            (".cursorrules", "Cursor"), (".cursor/", "Cursor"), (".github/copilot-instructions.md", "GitHub Copilot"),
            (".windsurfrules", "Windsurf"), (".clinerules", "Cline"), ("GEMINI.md", "Gemini CLI"),
            (".aider.conf.yml", "Aider"), (".continue/", "Continue"), (".mcp.json", "MCP servers"),
            (".gnomon/", "Gnomon"))
INTENTS = (("monitor", "Monitor", "watch it as it runs today; nothing is built or changed"),
           ("maintain", "Maintain", "keep it working: changes come as people report them"),
           ("improve", "Improve", "develop it further through the factory"))


# -- reading a reply by rule (and by the model, if there is one) ---------------------------------------------

def yes_no(text: str | None) -> bool | None:
    said = re.findall(r"\w+", str(text or "").lower())
    if not said:
        return None
    return True if said[0] in YES else False if said[0] in NO else None


def pick(ctx: wk.Ctx, reply: dict[str, Any], options: list[dict[str, Any]]) -> str | None:
    """The option a reply names: the button pressed, its number, its id or label, or the only option whose words
    it shares. Failing that, the model's reading when there is a model, said in the chat."""
    if reply.get("choice"):
        return str(reply["choice"])
    text = str(reply.get("text") or "").strip()
    real = [o for o in options if o["id"] != "back"]
    if not text or not real:
        return None
    return by_rule(text, real) or by_model(ctx, text, real)


def by_rule(text: str, real: list[dict[str, Any]]) -> str | None:
    said = text.lower().strip(" .!?")
    if said.isdigit() and 1 <= int(said) <= len(real):
        return str(real[int(said) - 1]["id"])
    exact = next((o for o in real if said in (o["id"].lower(), o["label"].lower())), None)
    if exact is not None:
        return str(exact["id"])
    words = set(re.findall(r"\w+", said))
    hits = [o for o in real if words & set(re.findall(r"\w+", f"{o['id']} {o.get('keys', '')}".lower()))]
    return str(hits[0]["id"]) if len(hits) == 1 else None


def by_model(ctx: wk.Ctx, text: str, real: list[dict[str, Any]]) -> str | None:
    """The model's reading of a reply the rules could not place, said in the chat; never a choice of its own."""
    if ctx.reader is None:
        return None
    try:
        got = ctx.reader(text, [{k: o[k] for k in ("id", "label")} for o in real])
    except Exception:  # a model that fails leaves the rules' answer: none
        got = None
    chosen = next((o for o in real if o["id"] == got), None)
    if chosen is None:
        return None
    ctx.say(f"I read that as “{chosen['label']}” (the model's reading; press another button if not).",
            read_by="model")
    return str(chosen["id"])


def yes_or_no(ctx: wk.Ctx, reply: dict[str, Any]) -> bool | None:
    if reply.get("choice") in ("yes", "no"):
        return reply["choice"] == "yes"
    said = yes_no(reply.get("text"))
    if said is None:
        got = pick(ctx, reply, [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}])
        said = None if got is None else got == "yes"
    return said


def unquote(text: str | None) -> str:
    return str(text or "").strip().strip("\"'").strip()


# -- the scan, shown in the chat --------------------------------------------------------------------------------

def ai_setup(mp: dict[str, Any]) -> list[str]:
    paths = [r["path"] for r in mp.get("files") or []] + [d["path"] for d in mp.get("skipped_dirs") or []]
    found = []
    for mark, tool in AI_SETUP:
        hit = any(p == mark or p.startswith(mark) or p.endswith("/" + mark) for p in paths) if mark.endswith("/") \
            else any(p == mark or p.endswith("/" + mark) for p in paths)
        if hit and tool not in found:
            found.append(tool)
    return found


def summary(mp: dict[str, Any], *, git: bool, code: bool) -> dict[str, Any]:
    from kernel.material import SECRET_WHY

    t = mp["totals"]
    inv = mp.get("inventory") or {}
    return {"folder": mp["folder"], "read": t["read"], "summarised": t["summarised"], "listed": t["listed"],
            "skipped": t["skipped"], "files": t["files"], "chars": t["chars"], "budget": t["budget"],
            "excluded": t["excluded"], "git": git, "code": code, "ai_setup": ai_setup(mp),
            "languages": [f"{x['language']} ({x['files']})" for x in inv.get("languages") or []][:8],
            "secret_files": [r["path"] for r in mp["files"] if r["why"].startswith(SECRET_WHY)][:20],
            "exclude": list(mp.get("exclude") or [])}


def summary_text(s: dict[str, Any]) -> str:
    out = [f"I scanned it: {s['read']} read, {s['summarised']} summarised, {s['listed']} listed, "
           f"{s['skipped']} skipped, of {s['files']} files."]
    if s["languages"]:
        out.append("Code: " + ", ".join(s["languages"]) + ".")
    out.append(("AI-tool setup found: " + ", ".join(s["ai_setup"]) + ".") if s["ai_setup"] else
               "No AI-tool setup found.")
    if s["secret_files"]:
        out.append("Skipped as secret-looking, never opened or sent: " + ", ".join(s["secret_files"]) + ".")
    if s["excluded"]:
        out.append(f"{s['excluded']} files left out as you unticked them.")
    out.append("Nothing has been sent or recorded.")
    return " ".join(out)


def refused_folder(exc: Exception) -> str:
    from kernel.source_guard import ROOTS_ENV

    sep = ";" if Path.cwd().drive else ":"
    return (f"I may not read that folder: {str(exc).removeprefix('refused: ')}. The cockpit reads folders under "
            f"your home folder, or under the roots the operator lists in {ROOTS_ENV} (folders separated by "
            f"“{sep}”, then start the cockpit again). Give another folder, or ask the operator to add it.")


def scan_folder(ctx: wk.Ctx, text: str) -> Path | None:
    """Check a folder the person named and scan it, saying the result; the folder, or None when it may not be
    read (said plainly, with how to allow it)."""
    from kernel.source_guard import SourceRefused, check_folder

    try:
        path = check_folder(text, ctx.persona)
    except SourceRefused as exc:
        ctx.say(refused_folder(exc))
        return None
    except ValueError as exc:
        ctx.say(f"{exc}. Type the folder's full path.")
        return None
    rescan(ctx, path)
    wk.remember(ctx.factory, ctx.person, str(path))
    return path


def rescan(ctx: wk.Ctx, path: Path) -> dict[str, Any]:
    from kernel import material
    from kernel.material_adopt import is_git

    mp = material.preview(path, ctx.data.get("exclude") or [])
    s = summary(mp, git=is_git(path), code=material.has_code(mp))
    ctx.data.update(source=str(path), scan=s)
    ctx.say(summary_text(s), scan=s, links=[{"label": "See the full map", "map": str(path)}])
    return s


def untick(ctx: wk.Ctx, exclude: list[str]) -> None:
    """The files the person unticked in the full map: scanned again without them."""
    if not (ctx.data.get("scan") or {}).get("folder"):
        ctx.say("There is no folder scanned in this walkthrough yet.")
        return
    ctx.data["exclude"] = [str(x) for x in exclude][:5000]
    rescan(ctx, Path(ctx.data["source"]))


def title_from(source: str) -> str:
    name = re.split(r"[\\/]", source.rstrip("/\\"))[-1].removesuffix(".git")
    return re.sub(r"[-_]+", " ", name).strip().capitalize() or "My project"


def hosted_roles(roles: tuple[str, ...]) -> list[dict[str, Any]]:
    from kernel import confidential

    return [r for r in confidential.routes(roles) if not r["local"]]


def hosted_line(rows: list[dict[str, Any]]) -> str:
    return "; ".join(f"the {r['role']} role{' (its fallback)' if r['which'] == 'fallback' else ''} goes to "
                     f"{r['endpoint']} ({str(r['url'] or '').split('/')[2] if '://' in str(r['url'] or '') else '?'})"
                     for r in rows)


def posture_options() -> list[dict[str, Any]]:
    from kernel.posture import POSTURES

    out = [{"id": "none", "label": "No posture (the default)",
            "hint": "the project runs as before: blocking questions to people, the rest by its mode"}]
    return out + [{"id": k, "label": p["label"], "hint": p["summary"]} for k, p in POSTURES.items()]


def posture_label(name: str | None) -> str:
    return next((o["label"] for o in posture_options() if o["id"] == (name or "none")), str(name))


class Flow:
    """What every walkthrough has; the steps are its own ``ask_``, ``take_`` and ``done_`` methods."""

    name = label = about = control = intro = first = ""
    steps: tuple[str, ...] = ()

    def untick(self, ctx: wk.Ctx, exclude: list[str]) -> None:
        untick(ctx, exclude)

    def ask_done(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Done.", final=True)

    def take_confirm(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        """Typed words at a proposal: only its button carries it out."""
        ctx.say("Nothing is done until you press the button of the proposal above, signed with your name. Or go "
                "Back to change something.")
        return None

    take_setkind = take_handover = take_confirm

    # the shared steps of the walkthroughs that read a folder

    def ask_title(self, ctx: wk.Ctx) -> dict[str, Any]:
        default = ctx.data.get("title") or title_from(ctx.data.get("source") or "")
        ctx.data["title"] = default
        return ctx.say("What should the project be called?", options=[{"id": "default", "label": default}],
                       input={"kind": "text", "placeholder": "A short title"})

    def take_title(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        title = ctx.data["title"] if reply.get("choice") == "default" else unquote(reply.get("text"))[:200]
        if not title:
            return None
        ctx.data["title"] = title
        return "confidential"

    def ask_confidential(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Is the material confidential? Then every model call for the project stays on a model on "
                       "this machine or your own network, and nothing goes to a hosted model.",
                       options=[{"id": "yes", "label": "Yes, keep it on local models"}, {"id": "no", "label": "No"}])

    def take_confidential(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        said = yes_or_no(ctx, reply)
        if said is None:
            return None
        ctx.data["confidential"] = said
        return ("hosted" if hosted_roles(self.roles) else self.after_confidential) if said else self.after_confidential

    roles: tuple[str, ...] = ()
    after_confidential = "posture"

    def ask_hosted(self, ctx: wk.Ctx) -> dict[str, Any]:
        rows = hosted_roles(self.roles)
        if not rows:
            return ctx.say("Every role it needs is on a local model now.", options=[{"id": "go", "label": "Go on"}])
        return ctx.say(f"Confidential is noted, but {hosted_line(rows)}. {self.hosted_means} You can set up a "
                       "local model now and come back here.",
                       options=[{"id": "walk:model", "label": "Set up a model now"},
                                {"id": "go", "label": self.hosted_go}])

    hosted_means = ""
    hosted_go = "Go on; I will set it up later"

    def take_hosted(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        return self.after_confidential if pick(ctx, reply, wk.offered(ctx.w)) == "go" else None

    def ask_posture(self, ctx: wk.Ctx) -> dict[str, Any]:
        return ctx.say("Which posture? A posture sets how carefully it runs; No posture keeps the defaults. You can "
                       "change it later in Project settings.", options=posture_options())

    def take_posture(self, ctx: wk.Ctx, reply: dict[str, Any]) -> str | None:
        got = pick(ctx, reply, posture_options())
        if got is None:
            return None
        ctx.data["posture"] = None if got == "none" else got
        return "confirm"

    def wait_for(self, reply: dict[str, Any], ctx: wk.Ctx, what: str) -> dict[str, Any] | None:
        """A job that ended, or None while it runs (a typed reply then hears that it still runs)."""
        job = reply.get("job")
        if not isinstance(job, dict) or job.get("state") in (None, "running", "unknown"):
            ctx.say(f"Still {what}: I show the progress here and say when it is done.")
            return None
        return job


def job_error(job: dict[str, Any]) -> str:
    lines = [x for x in job.get("log_tail") or [] if x.strip() and not x.startswith(("adopt: ", "{", "}", " "))]
    return lines[-1][:400] if lines else f"the job ended as {job.get('state')}"


def progress_of(job: dict[str, Any] | None) -> list[str]:
    """The progress lines an adoption printed, in plain words (kernel/material_cli.py)."""
    return [x.removeprefix("adopt: ") for x in (job or {}).get("log_tail") or [] if x.startswith("adopt: ")]


def questions_links(project: Any) -> list[dict[str, Any]]:
    from kernel.canon import Canon

    qs = Canon(project).questions("open")
    return [{"label": f"{q['id']}: {q['text'][:90]}", "route": f"#/p/{project.pid}/questions/{q['id']}"}
            for q in qs[:6]]


def open_project(pid: str) -> dict[str, Any]:
    return {"label": "Open the project", "route": f"#/p/{pid}/overview"}


def adopted_links(pid: str) -> list[dict[str, Any]]:
    """After an adoption: align the repository's own specs and tests (FR-ALN1), and its AI tools (FR-AGC1)."""
    return [{"label": "Open Alignment", "route": f"#/p/{pid}/align", "control": "align_scan"},
            {"label": "AI tools in this project", "route": f"#/p/{pid}/overview", "control": "ai_tools"}]


def next_links(project: Any) -> tuple[str, list[dict[str, Any]]]:
    from kernel.next_step import next_step

    nx = next_step(project)
    links = [{"label": a["label"], "route": f"#/p/{project.pid}/{a.get('view') or 'overview'}",
              "control": a.get("control")} for a in nx["actions"][:4]]
    return f"What's next: {nx['waits_for']}", links
