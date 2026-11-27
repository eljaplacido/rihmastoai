"""Ask Rihma's practical answers about working on a project yourself (FR-RPJ1, docs/guides/ide-and-rihmasto.md):
"how do I work on this in my terminal (or my IDE)?", "how do I run its tests?", "where do I set up my IDE?" and
"where do I state its commands?".

A person working on an existing project wants the commands, with the project's real id and their own name, and
one button: not where a card is. The answers come from the project's records by rule, with no model, model or
not, and name only what this Rihmasto has: the Console and Open a terminal here, a workspace of one's own
(`rihmasto workspace open`, then `submit` through the gate), `rihmasto shell`, the IDE's MCP setup (`rihmasto
ide`), the test commands the adoption's baseline ran and the commands its own instructions state. An attached
repository is worked on in place and its commits judged by `rihmasto repo gate`; a project with no code yet says
so. Where `rihmasto` is not installed, or this factory's home is not the default one, the answer says how the
commands run as written (kernel/console_term.py ``run_note``).

The questions are matched narrowly: working on *the project itself* (it, this, the code, its title), never a
question that only names the command line ("how do I approve the plan from the cli?" stays the map's).
"""

from __future__ import annotations

import re
from typing import Any

# "work on / develop / hack on / edit / change ... it, this, the code, the project" ... or "work on it myself".
_SUBJECT = re.compile(
    r"\b(?:work(?:ing)? on|develop(?:ing)?|hack(?:ing)? on|cod(?:e|ing) on|edit(?:ing)?|chang(?:e|ing)|"
    r"modify(?:ing)?|contribut(?:e|ing) to|clon(?:e|ing))\s+(?:on\s+)?"
    r"(?:it|this|that|the (?:code|project|repo|repository|product|codebase|source|game|app)|its code|"
    r"the code of\b|my (?:code|project|repo|repository))\b"
    r"|\brun (?:it|this) locally\b|\b(?:työskentel\w*|kehit\w*|muokkaa\w*) (?:tätä|sitä|tämän|sen|koodia|projektia)")
_HOW = re.compile(r"\b(how (?:do|can|should|would) (?:i|we)|how to|where do i|can i\b|i want to work|miten|kuinka)")
_WHERE = re.compile(r"\b(terminal|shell|command[- ]line|cli\b|powershell|bash\b|ide\b|editor|vs ?code|locally|"
                    r"myself|my own|on my (?:own )?(?:machine|laptop|computer)|päätte|terminaali|komentorivi)")
_TESTS = re.compile(r"\b(?:run(?:ning)?|start) (?:its|the|my|our|these|those)? ?(?:own )?(?:tests?|test suite|suite|"
                    r"evaluation|evals?)\b|\btest command\b|\bhow (?:do|can) (?:i|we) test\b|"
                    r"\b(?:aja|ajaa|ajan) (?:sen )?test")
_IDE = re.compile(r"\b(ide\b|editor|vs ?code|cursor|mcp\b)")
_SETUP = re.compile(r"\b(set ?up|setup|connect|configure|hook up|where)\b")
_STATE_COMMANDS = re.compile(r"\b(state|set|name|add|configure|tell)\b.{0,40}\bcommands?\b")
NAME = "<your name>"


def asks_work(question: str) -> bool:
    """Whether a question asks how to work on the project itself, in one's own terminal, shell or IDE."""
    said = question.lower()
    return bool(_SUBJECT.search(said)) and bool(_HOW.search(said) or _WHERE.search(said))


def asks_tests(question: str) -> bool:
    """Whether a question asks how to run the project's own tests (or its evaluation)."""
    return bool(_TESTS.search(question.lower()))


def named_project(factory: Any, question: str) -> Any:
    """The one project a question names by its title or id when none is open, else None."""
    said = question.lower()
    found = []
    for p in factory.projects():
        title = str(p.meta.get("title") or "").lower().strip()
        if p.pid in said or (len(title) >= 3 and re.search(rf"(?<!\w){re.escape(title)}(?!\w)", said)):
            found.append(p)
    return found[0] if len(found) == 1 else None


def routed(factory: Any, project: Any, question: str, about: dict[str, Any] | None, *, person: str | None = None,
           hidden: Any = ()) -> dict[str, Any] | None:
    """Ask Rihma's hook (kernel/assistant.py): an answer already found stays; how to work on the project (the open
    one, or the one the question names) in one's own terminal or IDE gets its commands; how to run its tests, set
    up the IDE or state its commands gets its own answer."""
    from kernel.assistant_rules import FACTORY_PID

    if about is not None:
        return about
    if project is None:
        project = named_project(factory, question)
    if project is None or project.pid == FACTORY_PID:
        return None
    return own_answer(project, question, person=person, hidden=hidden)


def by_rule(factory: Any, project: Any, question: str, about: dict[str, Any] | None, *, person: str | None = None,
            hidden: Any = ()) -> dict[str, Any] | None:
    """Ask Rihma's answers by rule, model or not (kernel/assistant.py ``ask``): how to work on the project
    yourself (its terminal, its tests, its IDE), then how a part of its work is doing, from its own records."""
    from kernel import assistant_status as status_q
    from kernel.assistant_rules import asks_for_action

    about = routed(factory, project, question, about, person=person, hidden=hidden)
    if about is None and project is not None and not asks_for_action(question):
        about = status_q.areas_answer(project, question)
    return about


def before_map(question: str, project: Any, act: bool, hidden: Any, person: str | None = None
               ) -> dict[str, Any] | None:
    """What the cockpit map answers before it is searched (kernel/assistant.py ``from_map``): how to work on this
    project yourself, and how this project, or a part of it, is doing."""
    from kernel import assistant_status as status_q
    from kernel.assistant_rules import FACTORY_PID

    if project is None or act:
        return None
    if project.pid != FACTORY_PID:
        own = own_answer(project, question, person=person, hidden=hidden)
        if own is not None:
            return own
    return status_q.project_answer(project, question)


def for_project(answer: str, project: Any) -> str:
    """A command the map gives (``<pid>``), for the project asked about."""
    from kernel.assistant_rules import FACTORY_PID

    return answer.replace("<pid>", project.pid) if project is not None and project.pid != FACTORY_PID else answer


def about_this(project: Any, question: str) -> str:
    """The question with the project's own title or id said as "this" ("how do I work on Toolbox in my
    terminal?" asks how to work on this)."""
    said = question.lower()
    for name in {str(project.meta.get("title") or "").lower().strip(), project.pid.lower()}:
        if len(name) >= 3:
            said = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "this", said)
    return said


def own_answer(project: Any, question: str, *, person: str | None = None, hidden: Any = ()) -> dict[str, Any] | None:
    """The practical answer about working on ``project`` the question asks for, or None."""
    from kernel.ide import kind_of

    said = about_this(project, question)
    if asks_work(said):
        return work_answer(project, person=person, hidden=hidden)
    if kind_of(project) is None:
        return None
    if asks_tests(said):
        return tests_answer(project, hidden=hidden)
    if _STATE_COMMANDS.search(said) and "console" not in hidden:
        return _shape(f"State {_title(project)}'s commands in Console, Console settings: each one you name there "
                      "becomes a button, and runs in the project's working copy. A test command can also be a Health "
                      "Test suite check, run on demand or on a schedule.",
                      {"route": f"#/p/{project.pid}/console", "control": "console_settings"}, project.pid,
                      ["console_settings", "health_enable"])
    if _IDE.search(said) and _SETUP.search(said):
        return ide_answer(project)
    return None


def _title(project: Any) -> str:
    return f"{project.meta.get('title') or project.pid} ({project.pid})"


def _who(person: str | None) -> str:
    return f'--person "{(person or "").strip() or NAME}" --persona developer'


def _baseline_runs(project: Any) -> list[str]:
    base = project.read("baseline.json", {}) or {}
    runs = [" ".join(str(w) for w in r.get("command") or []) for r in base.get("runs") or [] if isinstance(r, dict)]
    runs = [r for r in runs if r]
    return runs or ([str(base["command"])] if base.get("command") else [])


def _stated(project: Any, kinds: tuple[str, ...] = ("test", "run", "build")) -> list[str]:
    """The commands the project's own instructions state (agent_context.json), its tests first."""
    ctx = project.read("agent_context.json", None)
    ctx = ctx if isinstance(ctx, dict) else {}
    return [s["command"] for kind in kinds for s in ctx.get("stated") or []
            if isinstance(s, dict) and s.get("kind") == kind and s.get("command")]


def _run_note(project: Any) -> str:
    from kernel.console_term import run_note

    return run_note(project.factory.home)


def work_answer(project: Any, *, person: str | None = None, hidden: Any = ()) -> dict[str, Any]:
    """The steps to work on ``project`` in one's own terminal or IDE, with its real id and the person's name, and
    Take me there to its Console (Open a terminal here)."""
    from kernel.ide import kind_of

    pid, title = project.pid, project.meta.get("title") or project.pid
    kind = kind_of(project)
    if kind is None and not project.path("repo.git").is_dir():
        return _shape(f"{title} ({pid}) has no code yet, so there is nothing to open in a terminal: its code comes "
                      "from the factory's build, or adopt or attach your repository first (New project, An existing "
                      "project).", {"route": f"#/p/{pid}/overview", "control": None}, pid)
    who = _who(person)
    steps = _attached_steps(project, who) if kind == "attached" else _workspace_steps(pid, who)
    if "console" not in hidden:
        steps.insert(0, "In the cockpit: the Console runs this project's commands in a working copy, and Open a "
                        f"terminal here opens your own terminal in it (Take me there); `rihmasto shell {pid} {who}` "
                        "does the same from a terminal on this machine.")
    steps.append(f"Your IDE's agent: `rihmasto ide {pid}` (or Work on it from your IDE on the Overview) gives the MCP "
                 "setup for Claude Code, Cursor and Codex.")
    extra = [*_tests_lines(project), _run_note(project)]
    text = (f"To work on {title} ({pid}) in your terminal or IDE: "
            + " ".join(f"{n}. {s}" for n, s in enumerate(steps, 1))
            + "".join(f" {e}" for e in extra if e) + " Your own folder is never changed.")
    nav = ({"route": f"#/p/{pid}/console", "control": "console_terminal"} if "console" not in hidden
           else {"route": f"#/p/{pid}/overview", "control": "ide_setup"})
    return _shape(text, nav, pid)


def _tests_lines(project: Any) -> list[str]:
    from kernel.native_guide import own_tests

    runs, stated = _baseline_runs(project), _stated(project)
    own = own_tests(project)          # its own test roots ran: they say its tests, not the root's suite (FR-SRC2)
    said = f" ({', '.join(f'`{c}`' for c in own['commands'])})" if own and own["commands"] else ""
    out = [f"{own['line'][0].upper()}{own['line'][1:]}{said}."] if own else []
    if runs and not own:
        verdict = (project.read("baseline.json", {}) or {}).get("verdict")
        out.append(f"Its tests, as the adoption's baseline ran them{f' ({verdict})' if verdict else ''}: "
                   + ", ".join(f"`{r}`" for r in runs) + ".")
    more = [c for c in stated if c not in runs]
    if more:
        out.append("Its own instructions state: " + ", ".join(f"`{c}`" for c in more[:3])
                   + " (buttons in the Console).")
    return out


def _attached_steps(project: Any, who: str) -> list[str]:
    repo = (project.meta.get("attached") or {}).get("repo")
    own = "Work in your own repository as you always do" + (f": {repo}" if repo else "")
    return [own + ". Rihmasto never writes to it, pushes to it or merges into it.",
            f"`rihmasto repo gate {project.pid} --head <commit> {who}` judges a commit against the contract."]


def _workspace_steps(pid: str, who: str) -> list[str]:
    return [(f"Your own branch: `rihmasto workspace open {pid} {who} --agent shell` clones main onto a branch "
             "of your own and prints its folder; work and commit there as you always do."),
            (f"From that folder when it is ready: `rihmasto workspace submit {pid} . {who}` sends your commits "
             "through the gate (its tests, the criteria, the verifier); warranted, they merge into main.")]


def tests_answer(project: Any, *, hidden: Any = ()) -> dict[str, Any]:
    """How to run the project's own tests: the commands its baseline ran and its instructions state, as Console
    buttons; when none is known, that none was found by rule and where a person names one."""
    pid = project.pid
    lines = _tests_lines(project)
    console = {"route": f"#/p/{pid}/console", "control": "console_run"}
    if lines:
        where = ("Run them in the Console (Take me there), where they are buttons, or from your own terminal in a "
                 "workspace of your own; a Health Test suite check runs them on demand or on a schedule.")
        return _shape(f"{_title(project)}: " + " ".join(lines) + " " + where, console, pid,
                      ["console_run", "health_enable"])
    base = project.read("baseline.json", {}) or {}
    why = base.get("reason") or "the baseline is not measured"
    nav = {"route": f"#/p/{pid}/checks", "control": "health_enable"} if "checks" not in hidden else console
    return _shape(f"{_title(project)}: no test command was found by rule ({why}), so there is nothing to run yet. "
                  "Name the command that checks it once: as a Health Test suite check (Take me there), which runs on "
                  "demand or on a schedule, or in Console, Console settings, where it becomes a button. Agents are "
                  "told the same and never invent one.", nav, pid, ["health_enable", "console_settings"])


def ide_answer(project: Any) -> dict[str, Any]:
    """Where the IDE is set up for this project: the Overview's Work on it from your IDE, and `rihmasto ide`."""
    pid = project.pid
    note = _run_note(project)
    return _shape(f"Set up your IDE for {_title(project)} on its Overview, Work on it from your IDE (Take me there): "
                  f"it gives the MCP setup for Claude Code, Cursor and Codex. From a terminal, `rihmasto ide {pid}` "
                  "prints the same." + (f" {note}" if note else ""),
                  {"route": f"#/p/{pid}/overview", "control": "ide_setup"}, pid, ["ide_setup"])


def _shape(answer: str, nav: dict[str, Any], pid: str, matches: list[str] | None = None) -> dict[str, Any]:
    return {"answer": answer, "navigate": nav, "propose": [], "dropped": [], "sources": [pid], "by": "map",
            "matches": matches or ["console_terminal", "ide_setup"]}
