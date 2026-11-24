"""Rihma over MCP: the factory's reads and proposals in a developer's own coding agent (FR-N3).

This is the headless form of the cockpit. A coding agent (Claude Code, Cursor, Codex or any other
MCP client) starts it as a child process and speaks MCP to it over stdio: JSON-RPC 2.0, one JSON
message per line. It wraps the same kernel read models as ``cockpit/server.py``.

    python -m mcp.server --home <factory home> --person "<name>" --persona developer

The person and the persona are fixed when the server starts. They sign every write and decide
what the reads show (the cards this persona may decide, what waits on it). The server refuses to
start for a name that is not a person (``kernel.people.is_person``) or an unknown persona. With
access enforced (``kernel.access``, D-0016) the operator who starts it is the local user the access
file names (``local:<os user>``): ``--person`` must be that user's name, ``--persona`` must be granted
to them, each proposal needs the persona granted on its project, and its records name the identity.

What the server keeps:
- **Proposals only.** Its writes are a change card (``kernel.change.submit``), a comment
  (``Canon.comment``) and a signal (``kernel.signals.receive``). Each is signed with the
  server's person and persona and noted in the ledger as ``mcp_write``. No tool decides a card,
  answers a question, approves, pauses, resumes or deploys: people do that in the cockpit.
- **No holdouts.** The holdout custody (``project.holdouts_dir``) is never served. Its content
  is read only to recognise it, and any output that carries it is redacted, as are the holdout
  failure details the ledger keeps. What the client itself sent is echoed as it came, never
  redacted, so no answer tells it which of its guesses are held out. Nothing outside the factory
  home is served, except the cockpit's own map of views and controls, and a running cell's last
  target is shown without the machine's own paths.
- **Clean stdout.** stdout carries only protocol messages. Logs and tracebacks go to stderr, and
  an error reaches the client as a JSON-RPC error or an ``isError`` result with a plain message.
  No line ends the server: one it cannot parse, or one that breaks it, gets an error answer.

The protocol is MCP's handshake revision (``initialize``), checked against the 2025-06-18 and
2025-11-25 specifications. A newer client that probes with ``server/discover`` gets "method not
found" and falls back to ``initialize``, as the 2026-07-28 revision's compatibility rules expect.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import traceback
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NotRequired, TypedDict

if __package__ in (None, ""):  # run as a file (python <repo>/mcp/server.py): find the kernel beside it
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel import access as kaccess  # noqa: E402
from kernel.canon import CARD_DECIDERS, Canon, DecisionRefused, deciders_of  # noqa: E402
from kernel.custody import held_strings, ledger_record, redact  # noqa: E402
from kernel.people import PERSONAS, Identity, is_person  # noqa: E402
from kernel.store import HOME_ENV, RIHMA_HOME_ENV, STAGES, Factory  # noqa: E402

SERVER_NAME = "rihma"
SERVER_TITLE = "Rihma"
SERVER_VERSION = "1.0.0"
# Handshake revisions this server speaks, newest first. An unknown request gets the newest.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
RESOURCE_NOT_FOUND = -32002

LEDGER_TAIL = 100
MAX_MESSAGE = 4 << 20
PID = re.compile(r"(?:_factory|[a-z0-9][a-z0-9-]{0,80})\Z")
PROJECT_URI = re.compile(r"rihma://projects/(?P<pid>[^/]+)/(?P<what>spec|contract|ledger)\Z")
MAP_URI = "rihma://cockpit/map"
DECIDE_IN_COCKPIT = ("Decisions (deciding a card, answering a question, approving, pausing, deploying) are made "
                     "by a person in the Rihma cockpit, not here.")

# -- the holdout guard: the one redaction module is kernel/custody.py -------------------------------


class Echo(str):
    """Text the client itself sent, served back as it came. Redaction passes it by: redacting the
    client's own words would tell it which of its guesses are held out. Only a value made from the
    client's input alone (its argument, or a fixed cut of it) is an Echo."""


def _redact(value, held: list):
    """Every string value with holdout content replaced (kernel.custody.redact). Keys are the kernel's
    field names and stay, and so does an ``Echo``: it is the client's own input."""
    return redact(value, held, keep=(Echo,))


class _Confined:
    """The factory as the server sees it: a project folder that leads out of the home (a link to
    somewhere else) is not a project. Everything else is the factory's own."""

    def __init__(self, factory, inside):
        self._factory, self._inside = factory, inside

    def __getattr__(self, name):
        return getattr(self._factory, name)

    def projects(self) -> list:
        return [p for p in self._factory.projects() if self._inside(p.dir)]

    def project(self, pid: str):
        project = self._factory.project(pid)
        if not self._inside(project.dir):
            raise KeyError(f"no project {pid!r} in this factory home")
        return project


# -- errors ---------------------------------------------------------------------------------------

class RpcError(Exception):
    """A protocol error: it answers the request with a JSON-RPC error object."""

    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


class ToolError(Exception):
    """A tool that ran and could not do what was asked: an ``isError`` result with a plain message."""


class InputRefused(ToolError):
    """A refusal of what the client sent, in fixed words and the client's own input. It is served as
    it is, never redacted, for the reason an ``Echo`` is not: nothing in it comes from the factory."""


# -- the tools --------------------------------------------------------------------------------------

class Param(TypedDict):
    """One text argument of a tool, as its input schema states it."""

    description: str
    required: bool
    maxLength: int
    enum: NotRequired[list[str]]


class Tool(TypedDict):
    """One tool: its title, whether it only reads, its arguments and what it does."""

    title: str
    read: bool
    params: dict[str, Param]
    description: str


def _p(description: str, *, required: bool = True, limit: int = 200, enum: Iterable[str] | None = None) -> Param:
    param: Param = {"description": description, "required": required, "maxLength": limit}
    if enum:
        param["enum"] = list(enum)
    return param


PID_ARG = _p("The project id, as rihma_projects lists it.", limit=81)
COMMENT_TARGETS = Canon.COMMENT_TARGETS
# A write tool is the cockpit's write by another door: refused, as that route is, where its module is not
# enabled (kernel/modules.py, FR-MOD5). Every tool that writes names its route here.
WRITE_ROUTES = {"rihma_report_change": "post_change", "rihma_comment": "post_comment", "rihma_signal": "post_signal"}

TOOLS: dict[str, Tool] = {
    "rihma_projects": {
        "title": "Projects", "read": True, "params": {},
        "description": "Every project in the factory: id, title, work profile, maturity, stage, what it is doing "
                       "now (state and one line) and its health (on track, at risk or off track, with reasons)."},
    "rihma_project": {
        "title": "One project", "read": True, "params": {"pid": PID_ARG},
        "description": "One project: now, health, evidence counts per state, open questions, the open cards your "
                       "persona may decide (ids and titles only), what its running cell is doing and its posture "
                       "(what it does and what holds the project now). Decisions are made in the cockpit."},
    "rihma_waiting": {
        "title": "What waits on you", "read": True, "params": {},
        "description": "The decisions waiting on your persona across projects, oldest first, with their age in "
                       "hours. You decide them in the cockpit."},
    "rihma_floor": {
        "title": "Floor", "read": True, "params": {},
        "description": "The factory's Floor: the gate's judgement of the work (first-round pass rate, merged, "
                       "escalated, rounds) and the harness outcomes of each Gnomon run, with spend."},
    "rihma_timeline": {
        "title": "Task timeline", "read": True, "params": {"pid": PID_ARG},
        "description": "How each task of a project went: its rounds with start, end, model and gate verdict, "
                       "and when it merged or escalated."},
    "rihma_evidence": {
        "title": "Evidence", "read": True, "params": {"pid": PID_ARG},
        "description": "Each acceptance criterion of a project with its evidence state: verified, claimed, held "
                       "out, failing or not measured, and what the state rests on."},
    "rihma_assessment": {
        "title": "Assessment", "read": True,
        "params": {"pid": PID_ARG,
                   "version": _p("Optional: which assessment, such as AS-2 (default: the latest).", required=False,
                                 limit=16)},
        "description": "An adopted system's assessment (the latest, or the one named): its findings from five "
                       "perspectives (CI/CD governance, maintenance, security, compliance, architecture and "
                       "operations), each with its evidence, severity and suggested change; the panel's "
                       "model_proposed findings, kept apart and never facts; what was not measured and why; and "
                       "what changed since the version before. A person files findings as changes in the cockpit."},
    "rihma_square": {
        "title": "Delivery square", "read": True, "params": {},
        "description": "The delivery square at a glance: signals waiting, concepts to validate, projects per "
                       "stage band, end-user feedback waiting for triage and what runs in production."},
    "rihma_track": {
        "title": "Staying on track", "read": True,
        "params": {"pid": _p("Optional project id; without it, every project's line.", required=False, limit=81)},
        "description": "How a project is doing against its approved plan: on track, at risk, off track or not "
                       "measured, with each reason and every figure's basis (tasks, gate first round, assumption "
                       "debt, scope changes, blocking cards, time and cost against a budget, posture), and the "
                       "human checkpoints due."},
    "rihma_autopilot": {
        "title": "Autopilot and delegations", "read": True, "params": {"pid": PID_ARG},
        "description": "A project's autopilot run (running, expired or stopped), the sandbox it is bound to, its "
                       "delegations, the cards they decided and the ones they left to a person. Starting or "
                       "stopping one is a person's act, in the cockpit or the command line."},
    "rihma_ask": {
        "title": "Ask where", "read": True,
        "params": {"question": _p("A question such as 'where do I approve the plan?'", limit=2000),
                   "pid": _p("Optional project id, for answers about one project.", required=False, limit=81)},
        "description": "Ask where something is or how a project is going. Answers come from the cockpit's own map "
                       "of views and controls, with no model. Decisions are made in the cockpit."},
    "rihma_report_change": {
        "title": "Report a change", "read": False,
        "params": {"pid": PID_ARG, "text": _p("What you saw or what should change, in plain words.", limit=20000)},
        "description": "Propose a change or report feedback on a project. It opens a change card signed with this "
                       "server's person and persona, classified by rule; a person decides it in the cockpit."},
    "rihma_comment": {
        "title": "Comment", "read": False,
        "params": {"pid": PID_ARG,
                   "target_kind": _p("What the comment is about.", limit=32, enum=COMMENT_TARGETS),
                   "target_id": _p("Its id, for example R-2, R-2-AC-1, T-003, 1 or C-0004.", limit=200),
                   "text": _p("The comment.", limit=20000)},
        "description": "Comment on a requirement, criterion, task, release, card or the project. A comment "
                       "decides nothing; a product or business owner may promote it into a change."},
    "rihma_signal": {
        "title": "Raise a signal", "read": False,
        "params": {"text": _p("The need, in plain words.", limit=8000),
                   "source": _p("Where it came from, for example 'team chat' or 'code review'.", limit=200)},
        "description": "Raise a business need as a signal in the delivery square (channel 'manual'), signed with "
                       "this server's person and persona. A person triages it into a change or a concept."},
}


def _schema(params: dict[str, Param]) -> dict[str, Any]:
    props: dict[str, dict[str, Any]] = {}
    for name, p in params.items():
        props[name] = {"type": "string", "description": p["description"], "maxLength": p["maxLength"]}
        if "enum" in p:
            props[name]["enum"] = p["enum"]
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    required = [n for n, p in params.items() if p["required"]]
    if required:
        schema["required"] = required
    return schema


def tool_list() -> list:
    out = []
    for name, t in TOOLS.items():
        hints = {"readOnlyHint": True, "openWorldHint": False} if t["read"] else \
            {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
        out.append({"name": name, "title": t["title"], "description": t["description"],
                    "inputSchema": _schema(t["params"]), "annotations": {"title": t["title"], **hints}})
    return out


# -- the machine's own paths ------------------------------------------------------------------------

# Where an absolute path starts: a drive, a separator that is not inside a relative path or a web
# address (a file:// address is a path), a home directory (~ or ~user), or the "..." one of the
# machine's folders was cut down to.
_PATH_START = (r"(?:(?<!\w)[A-Za-z]:[\\/]|(?<![\w.:/\\])[\\/]|(?<=file://)/|(?<![\w.])~[\w.-]*[\\/]"
               r"|(?<![\w.])\.\.\.[\\/])")
_START = re.compile(_PATH_START)
# A path in quotes runs to its closing quote (or the end of a cut target), spaces and all; a bare one
# runs to the next space, quote or shell operator.
_PATH = re.compile(rf"(?P<q>[\"'])(?P<quoted>{_PATH_START}[^\"'\r\n]*)(?P<end>(?P=q)|\Z)"
                   rf"|(?P<bare>{_PATH_START}[^\s\"'`;|&<>]*)")


def _machine_roots(home: str | Path, lanes: str | Path | None) -> list[str]:
    """The machine's own folders a lane target may name: the factory home, the lanes and the user's
    home, as given and as resolved, longest first."""
    from kernel.lanes import lanes_root

    roots: set[str] = set()
    for where in (lambda: Path(home), lambda: Path(lanes or lanes_root()), Path.home):
        with contextlib.suppress(RuntimeError, KeyError, OSError):   # no home directory to name
            path = where()
            roots |= {str(path), str(path.resolve())}
    return sorted(roots, key=len, reverse=True)


def _norm(path: str) -> str:
    return re.sub(r"[\\/]+", "/", path).casefold()


def _root_out(text: str, root: str) -> str:
    """``text`` with ``root`` (either separator, any case) cut down to "...". A drive or a one-part
    path ("/srv") names no one and stays."""
    parts = re.split(r"[\\/]+", root.rstrip("\\/"))
    if sum(1 for p in parts if p) < 2:
        return text
    body = r"[\\/]+".join(re.escape(p) for p in parts)
    return re.sub(rf"(?<![\w.]){body}(?![\w.-])", "...", text, flags=re.IGNORECASE)


def _short(match: re.Match[str]) -> str:
    """One absolute path as its last part, ".../name", inside its quotes when it had them."""
    path = match["bare"] if match["bare"] is not None else match["quoted"]
    name = re.split(r"[\\/]", path.rstrip("\\/"))[-1]
    short = "..." if name in ("", "...") or name.endswith(":") else ".../" + name
    return short if match["bare"] is not None else match["q"] + short + match["end"]


def _local(target: str, roots: Iterable[str] = ()) -> str:
    """A tool target from a lane, without the machine's own paths. A shell command names paths
    anywhere, so every absolute path in it keeps only its last part, quoted or not. The machine's
    known folders go first: a target the kernel cut short inside one of them loses its unfinished
    tail, and one named whole goes whole, even with a space in its name."""
    text, roots = str(target), list(roots)
    starts = list(_START.finditer(text))
    if starts and any(_norm(root).startswith(_norm(text[starts[-1].start():])) for root in roots):
        text = text[:starts[-1].start()] + "..."
    for root in roots:
        text = _root_out(text, root)
    return _PATH.sub(_short, text)


class RihmaMCP:
    """The server's logic, apart from the transport: one call to ``handle`` per JSON-RPC message."""

    def __init__(self, factory: Factory, *, person: str, persona: str, lanes_root=None):
        if not is_person(person):
            raise ValueError(f"{person!r} is not a person; the server signs writes with a named person")
        if persona not in PERSONAS:
            raise ValueError(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")
        # With access enforced (D-0016) the operator who starts the server is the local user the access
        # file names: the person is that user's name, and the persona must be granted on some project.
        access = kaccess.load(factory, record=True, by="the MCP server")
        self.identity: Identity | None = None
        if access.enforced:
            self.identity = kaccess.local_identity(access)
            person, persona = kaccess.sign(access, self.identity, person, persona, None)
        self.person, self.persona = person.strip(), persona
        self.lanes_root = lanes_root
        self.roots = _machine_roots(factory.home, lanes_root)
        self.home = Path(factory.home).resolve()
        self.holdouts = Path(factory.holdouts_dir).resolve()
        self.factory = _Confined(factory, self._inside_home)
        self.kernel_factory = factory              # the access rules are read from the home itself
        self.protocol: str | None = None

    @property
    def instructions(self) -> str:
        verified = f", verified as {self.identity.id}" if self.identity is not None else ""
        return (f"Rihma is a governed AI factory. This server gives you its reads and lets you make proposals, "
                f"signed as {self.person} ({self.persona}{verified}). Every write is a proposal: a change card, a "
                f"comment or a signal. No tool here decides a card, answers a question, approves, pauses, resumes or "
                f"deploys; people make those decisions in the Rihma cockpit. Holdout scenarios are never shown. "
                f"Resources: rihma://projects/<pid>/spec, /contract and /ledger, and {MAP_URI}.")

    # -- JSON-RPC ---------------------------------------------------------------------------------

    def handle(self, msg) -> dict | None:
        """Answer one parsed message. A notification (no id) gets no answer."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _error(_request_id(msg), INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        is_request = "id" in msg
        mid = msg.get("id")
        method = msg.get("method")
        if not isinstance(method, str):
            if "result" in msg or "error" in msg:   # a response to nothing we asked: ignore it
                return None
            return _error(_request_id(msg), INVALID_REQUEST, "a request needs a method") if is_request else None
        if not is_request:
            return None                              # notifications/initialized, cancelled, ...: nothing to say
        if mid is None or isinstance(mid, bool) or not isinstance(mid, (str, int, float)):
            return _error(None, INVALID_REQUEST, "a request id is a string or a number")
        params = msg.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(mid, INVALID_PARAMS, "params must be an object")
        handler = {
            "initialize": self.initialize, "ping": lambda _: {},
            "tools/list": self.tools_list, "tools/call": self.tools_call,
            "resources/list": self.resources_list, "resources/templates/list": self.resource_templates,
            "resources/read": self.resources_read,
        }.get(method)
        if handler is None:
            return _error(mid, METHOD_NOT_FOUND, f"method not found: {method}")
        try:
            return {"jsonrpc": "2.0", "id": mid, "result": handler(params)}
        except RpcError as exc:
            return _error(mid, exc.code, exc.message, exc.data)
        except Exception as exc:  # a bug, never a verdict: log it on stderr and keep serving
            traceback.print_exc(file=sys.stderr)
            return _error(mid, INTERNAL_ERROR, f"internal error: {type(exc).__name__}")

    def initialize(self, params: dict) -> dict:
        asked = params.get("protocolVersion")
        self.protocol = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {"protocolVersion": self.protocol, "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": SERVER_NAME, "title": SERVER_TITLE, "version": SERVER_VERSION},
                "instructions": self.instructions}

    def tools_list(self, params: dict) -> dict:
        return {"tools": tool_list()}

    def tools_call(self, params: dict) -> dict:
        name, args = params.get("name"), params.get("arguments")
        if not isinstance(name, str) or name not in TOOLS:
            raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        if args is not None and not isinstance(args, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object")
        held = self._held()
        try:
            values = self._arguments(TOOLS[name]["params"], args or {})
            with kaccess.signing(self.identity):    # a proposal's records name the operator's identity
                result = getattr(self, "tool_" + name[len("rihma_"):])(**values)
        except ToolError as exc:   # a refusal of the client's own input is its own words, never redacted
            text = str(exc) if isinstance(exc, InputRefused) else _redact(str(exc), held)
            return {"content": [{"type": "text", "text": text}], "isError": True}
        result = _redact(result, held)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2, default=str)}],
                "structuredContent": result, "isError": False}

    @staticmethod
    def _arguments(spec: dict[str, Param], args: dict[str, Any]) -> dict[str, str]:
        """The tool's arguments, checked. A refusal names what the client sent and the tool's own
        fixed words, nothing else, so it is served unredacted (``InputRefused``)."""
        unknown = sorted(set(args) - set(spec))
        if unknown:
            takes = ", ".join(spec) or "no arguments"
            raise InputRefused(f"unknown argument(s): {', '.join(unknown)}; this tool takes {takes}")
        out: dict[str, str] = {}
        for name, p in spec.items():
            value = args.get(name)
            if value is None or (isinstance(value, str) and not value.strip() and not p["required"]):
                if p["required"]:
                    raise InputRefused(f"{name} is required")
                continue
            if not isinstance(value, str):
                raise InputRefused(f"{name} must be text")
            value = value.strip()
            if not value:
                raise InputRefused(f"{name} is required")
            if len(value) > p["maxLength"]:
                raise InputRefused(f"{name} is longer than {p['maxLength']} characters")
            if "enum" in p and value not in p["enum"]:
                raise InputRefused(f"{name} must be one of {', '.join(p['enum'])}")
            out[name] = value
        return out

    # -- where things are ------------------------------------------------------------------------

    def _inside_home(self, path: Path) -> bool:
        real = Path(path).resolve()
        return real.is_relative_to(self.home) and not real.is_relative_to(self.holdouts)

    def _project(self, pid: str):
        """A project of this factory home, or a plain refusal that echoes the id as the client sent it."""
        if not PID.match(pid or ""):
            raise InputRefused(f"no project {pid!r}: a project id is lower-case letters, digits and hyphens")
        try:
            return self.factory.project(pid)
        except KeyError:
            raise InputRefused(f"no project {pid}; rihma_projects lists them") from None

    def _held(self) -> list:
        """The strings of every scenario in the holdout custody that a builder could not already see in
        its project's spec or contract, longest first. They are used only to redact output."""
        return held_strings(Path(self.factory.holdouts_dir), Path(self.factory.projects_dir), inside=self._inside_home)

    @staticmethod
    def _safe(fn, *args, **kwargs):
        """A read model that cannot read a broken project says so instead of failing the whole answer."""
        try:
            return fn(*args, **kwargs)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            print(f"rihma mcp: {getattr(fn, '__name__', fn)} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return {"unreadable": type(exc).__name__}

    def _live(self, project) -> dict:
        from kernel.status import live

        out = live(project, lanes_root=self.lanes_root)
        if isinstance(out.get("last"), dict) and out["last"].get("target"):
            out["last"]["target"] = _local(out["last"]["target"], self.roots)
        return out

    # -- read tools ------------------------------------------------------------------------------

    def tool_projects(self) -> dict:
        from kernel.profiles import profile_of
        from kernel.status import health, now

        rows = []
        for p in self.factory.projects():
            if p.pid.startswith("_"):
                continue
            meta = p.meta
            stage = meta.get("stage", 1)
            rows.append({"id": p.pid, "title": meta.get("title"), "profile": profile_of(p)["id"],
                         "maturity": meta.get("maturity"), "stage": stage, "stage_name": STAGES.get(stage),
                         "now": self._safe(now, p), "health": self._safe(health, p)})
        return {"persona": self.persona, "projects": rows}

    def tool_project(self, pid: str) -> dict:
        from kernel.lenses import LENSES, lens_for
        from kernel.profiles import profile_of
        from kernel.status import evidence, health, now

        project = self._project(pid)
        canon, meta = Canon(project), project.meta
        stage = meta.get("stage", 1)
        counts = None
        if project.path("contract.json").exists():
            rows = self._safe(evidence, project)
            counts = dict(Counter(e["state"] for e in rows)) if isinstance(rows, list) else rows
        lens = lens_for(self.persona)
        return {
            "id": project.pid, "title": meta.get("title"), "profile": profile_of(project)["id"],
            "maturity": meta.get("maturity"), "mode": meta.get("mode"), "stage": stage,
            "stage_name": STAGES.get(stage), "now": self._safe(now, project), "health": self._safe(health, project),
            "evidence": counts if counts is not None else {"not_measured": "no contract yet"},
            "open_questions": [{"id": q["id"], "text": q["text"], "perspective": q["perspective"],
                                "blocking": q["blocking"]} for q in canon.questions("open")],
            "cards_you_may_decide": [{"id": c["id"], "title": c["title"]}
                                     for c in canon.cards(state="open", persona=self.persona)],
            "live": self._safe(self._live, project),
            "posture": self._safe(_posture, project),
            "lens": {"name": lens, "question": LENSES[lens]["question"]},
            "persona": self.persona, "note": DECIDE_IN_COCKPIT,
        }

    def tool_waiting(self) -> dict:
        from kernel.dashboard import queue

        q = queue(self.factory)
        items = [{k: i[k] for k in ("project", "card", "kind", "title", "age_hours")} for i in q["items"]
                 if i["kind"] in CARD_DECIDERS and self.persona in deciders_of(i)]   # a card may narrow them
        ages = [i["age_hours"] for i in items if i["age_hours"] is not None]
        return {"persona": self.persona, "count": len(items), "items": items,
                "oldest_hours": max(ages) if ages else None, "note": DECIDE_IN_COCKPIT}

    def tool_floor(self) -> dict:
        from kernel.projections import floor

        f = floor(self.factory)
        return {"gates": f["gates"], "harness": {"overall": f["overall"], "note": f["harness_note"]},
                "by_phase": f["by_phase"], "spend": f["spend"]}

    def tool_timeline(self, pid: str) -> dict:
        from kernel.dashboard import timeline

        return {"project": pid, **timeline(self._project(pid))}

    def tool_evidence(self, pid: str) -> dict:
        from kernel.status import evidence

        project = self._project(pid)
        contract = project.read("contract.json")
        if not contract:
            return {"project": pid, "criteria": [], "counts": {},
                    "note": "no contract yet: criteria come with the contract, at stage 4"}
        text = {c["id"]: c.get("then") for r in contract.get("requirements", []) for c in r.get("acceptance", [])}
        rows = [{**e, "then": text.get(e["criterion"])} for e in evidence(project)]
        return {"project": pid, "criteria": rows, "counts": dict(Counter(e["state"] for e in rows))}

    def tool_assessment(self, pid: str, version: str | None = None) -> dict:
        from kernel.assess import history, load, summary

        project = self._project(pid)
        versions = [e.get("id") for e in history(project)]
        if not versions:
            return {"project": pid, "assessment": None,
                    "note": "no assessment yet: a person runs it (rihmasto assess, or Assess now in the cockpit)"}
        try:
            record = load(project, version)
        except LookupError as exc:
            raise ToolError(str(exc.args[0] if exc.args else exc)) from None
        return {"project": pid, "assessment": summary(record), "versions": versions}

    def tool_square(self) -> dict:
        from kernel.signals import square

        return square(self.factory)

    def tool_track(self, pid: str | None = None) -> dict:
        from kernel.track import summary, track

        if pid is not None:
            return self._safe(track, self._project(pid))
        return {"projects": [self._safe(summary, p) for p in self.factory.projects() if not p.pid.startswith("_")],
                "note": DECIDE_IN_COCKPIT}

    def tool_autopilot(self, pid: str) -> dict:
        from kernel.autopilot import status

        return {**self._safe(status, self._project(pid)), "note": DECIDE_IN_COCKPIT}

    def tool_ask(self, question: str, pid: str | None = None) -> dict:
        from kernel.assistant import ask

        if pid is not None:
            self._project(pid)
        try:
            out = ask(self.factory, question, persona=self.persona, project_id=pid, model=None)
        except (OSError, ValueError, KeyError) as exc:
            raise ToolError(f"could not answer from the records: {type(exc).__name__}") from None
        out["note"] = ("This answer comes from the cockpit's map, with no model. The routes are cockpit links. "
                       + DECIDE_IN_COCKPIT)
        return out

    # -- write tools: proposals, signed ----------------------------------------------------------

    def _signed(self, project, action: str, target: str) -> dict:
        project.log("mcp_write", {"action": action, "target": target, "person": self.person,
                                  "persona": self.persona})
        signer = {"identity": self.identity.id} if self.identity is not None else {}
        return {"person": self.person, "persona": self.persona, **signer}

    def _module_on(self, tool: str, pid: str | None) -> None:
        """A write tool of a module that is not enabled where it acts is refused, saying how to enable it."""
        from kernel import modules

        if tool in WRITE_ROUTES:
            try:
                modules.require_route(self.kernel_factory, WRITE_ROUTES[tool], pid)
            except modules.ModuleOff as exc:
                raise ToolError(f"refused: {exc}") from None

    def _granted(self, pid: str) -> None:
        """With access enforced (D-0016), a proposal on ``pid`` needs the operator's persona granted there;
        a server started before access was enforced proposes nothing until it is started again."""
        access = kaccess.load(self.kernel_factory, record=True, by="the MCP server")
        if not access.enforced:
            return
        try:
            kaccess.sign(access, self.identity, self.person, self.persona, pid)
        except kaccess.AccessRefused as exc:
            raise ToolError(f"refused: {exc}") from None

    def tool_report_change(self, pid: str, text: str) -> dict:
        from kernel.change import submit, triage

        project = self._project(pid)
        self._module_on("rihma_report_change", pid)
        self._granted(pid)
        try:
            card = submit(project, persona=self.persona, person=self.person, text=text)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        tri = triage(project, card["id"], model=None)
        # the title is the first line of the client's text, so it comes back as the client wrote it
        return {"project": pid, "card": card["id"], "kind": "change", "title": Echo(card["title"]),
                "triage": {k: tri.get(k) for k in ("class", "way_back", "needs_decision")},
                "signed": self._signed(project, "report_change", card["id"]),
                "note": "A proposal: the change card waits in the Inbox. " + DECIDE_IN_COCKPIT}

    def tool_comment(self, pid: str, target_kind: str, target_id: str, text: str) -> dict:
        project = self._project(pid)
        self._module_on("rihma_comment", pid)
        self._granted(pid)
        try:
            c = Canon(project).comment({"kind": target_kind, "id": target_id}, text, person=self.person,
                                       persona=self.persona)
        except (DecisionRefused, ValueError) as exc:
            raise ToolError(str(exc)) from None
        target = {"kind": Echo(c["target"]["kind"]), "id": Echo(c["target"]["id"])}   # as the client named it
        return {"project": pid, "comment": c["id"], "target": target,
                "signed": self._signed(project, "comment", c["id"]),
                "note": "A comment decides nothing; a product or business owner may promote it into a change."}

    def tool_signal(self, text: str, source: str) -> dict:
        from kernel.learn import FACTORY_PID, factory_project
        from kernel.signals import receive

        self._module_on("rihma_signal", None)
        self._granted(FACTORY_PID)
        try:
            s = receive(self.factory, text, channel="manual", source=source, person=self.person,
                        persona=self.persona)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        return {"signal": s["id"], "channel": s["channel"], "source": Echo(s["source"]), "state": s["state"],
                "signed": self._signed(factory_project(self.factory), "signal", s["id"]),  # type: ignore[call-overload]
                "note": "A proposal: a person triages the signal into a change or a concept in the cockpit."}

    # -- resources --------------------------------------------------------------------------------

    def resources_list(self, params: dict) -> dict:
        out = [{"uri": MAP_URI, "name": "cockpit-map", "title": "The cockpit's map of views and controls",
                "mimeType": "application/json"}]
        for p in self.factory.projects():
            if p.pid.startswith("_"):
                continue
            title = p.meta.get("title") or p.pid
            for what, name, mime in (("spec", "spec.md", "text/markdown"), ("contract", "contract.json",
                                     "application/json"), ("ledger", "ledger.jsonl", "application/json")):
                if p.path(name).is_file():
                    out.append({"uri": f"rihma://projects/{p.pid}/{what}", "name": f"{p.pid}-{what}",
                                "title": f"{title}: {what}", "mimeType": mime})
        return {"resources": _redact(out, self._held())}

    def resource_templates(self, params: dict) -> dict:
        return {"resourceTemplates": [
            {"uriTemplate": "rihma://projects/{pid}/spec", "name": "project-spec", "title": "A project's spec",
             "mimeType": "text/markdown"},
            {"uriTemplate": "rihma://projects/{pid}/contract", "name": "project-contract",
             "title": "A project's contract", "mimeType": "application/json"},
            {"uriTemplate": "rihma://projects/{pid}/ledger", "name": "project-ledger",
             "title": f"A project's ledger, the last {LEDGER_TAIL} records", "mimeType": "application/json"}]}

    def resources_read(self, params: dict) -> dict:
        from kernel.assistant import ui_map

        uri = params.get("uri")
        if not isinstance(uri, str):
            raise RpcError(INVALID_PARAMS, "uri is required")
        held = self._held()
        if uri == MAP_URI:
            return _contents(uri, "application/json", json.dumps(_redact(ui_map(), held), ensure_ascii=False, indent=2))
        m = PROJECT_URI.match(uri)
        if not m:
            raise RpcError(RESOURCE_NOT_FOUND, "Resource not found", {"uri": uri})
        try:
            project = self._project(m["pid"])
        except ToolError as exc:
            raise RpcError(RESOURCE_NOT_FOUND, f"Resource not found: {exc}", {"uri": uri}) from None
        what = m["what"]
        path = project.path({"spec": "spec.md", "contract": "contract.json", "ledger": "ledger.jsonl"}[what])
        if not path.is_file() or not self._inside_home(path):
            raise RpcError(RESOURCE_NOT_FOUND, f"Resource not found: {m['pid']} has no {what} yet", {"uri": uri})
        if what == "spec":
            return _contents(uri, "text/markdown", _redact(path.read_text(encoding="utf-8", errors="replace"), held))
        if what == "contract":
            try:
                contract = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                raise RpcError(INTERNAL_ERROR, f"the contract of {m['pid']} is not readable JSON") from None
            return _contents(uri, "application/json", json.dumps(_redact(contract, held), ensure_ascii=False, indent=2))
        records = project.ledger().records()
        tail = [ledger_record(r) for r in records[-LEDGER_TAIL:]]   # without holdout details (kernel/custody.py)
        body = {"project": project.pid, "total": len(records), "shown": len(tail), "records": tail,
                "note": "Holdout scenarios and what they met stay in the holdout custody; such fields are "
                        "redacted, so a redacted record no longer matches its hash."}
        return _contents(uri, "application/json", json.dumps(_redact(body, held), ensure_ascii=False, indent=2))


def _posture(project) -> dict:
    """A project's posture as the cockpit's Posture dialog shows it: what it does and what holds the
    project now, without the full rule set (kernel/posture_rules.py)."""
    from kernel.posture_rules import view

    return {k: v for k, v in view(project).items() if k != "effects"}


def _contents(uri: str, mime: str, text: str) -> dict:
    return {"contents": [{"uri": uri, "mimeType": mime, "text": text}]}


def _request_id(msg: Any) -> str | int | float | None:
    """The id of a message when it is one JSON-RPC allows, a string or a number; otherwise null. An
    id the client nested is never echoed, so no answer is deeper than the server can write."""
    mid = msg.get("id") if isinstance(msg, dict) else None
    return mid if isinstance(mid, (str, int, float)) and not isinstance(mid, bool) else None


def _error(mid, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": err}


# -- the stdio transport ----------------------------------------------------------------------------

def handle_line(server: RihmaMCP, line: bytes) -> bytes | None:
    """One line in, at most one line out. A batch (a JSON array) is answered as an array."""
    if len(line) > MAX_MESSAGE:
        return _dump(_error(None, INVALID_REQUEST, f"a message is at most {MAX_MESSAGE} bytes"))
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _dump(_error(None, PARSE_ERROR, "Parse error: a message is one line of UTF-8 JSON"))
    except RecursionError:          # well-formed, but nested deeper than the parser's stack
        return _dump(_error(None, PARSE_ERROR, "Parse error: the message is nested too deeply"))
    if isinstance(msg, list):
        if not msg:
            return _dump(_error(None, INVALID_REQUEST, "an empty batch"))
        answers = [a for a in (server.handle(m) for m in msg) if a is not None]
        return _dump(answers) if answers else None
    answer = server.handle(msg)
    return _dump(answer) if answer is not None else None


def _dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8") + b"\n"


def serve(server: RihmaMCP, stdin=None, stdout=None) -> None:
    """Read messages from stdin until it closes; write only protocol messages to stdout."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    while True:
        line = stdin.readline()
        if not line:
            return
        if not line.strip():
            continue
        with contextlib.redirect_stdout(sys.stderr):  # a stray print never corrupts the protocol stream
            try:
                out = handle_line(server, line.rstrip(b"\r\n"))
            except Exception as exc:  # a bug, never a verdict: log it, answer it and keep serving
                traceback.print_exc(file=sys.stderr)
                out = _dump(_error(None, INTERNAL_ERROR, f"internal error: {type(exc).__name__}"))
        if out is not None:
            stdout.write(out)
            stdout.flush()


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mcp.server",
                                     description="Rihma over MCP (stdio): reads and proposals, never decisions.")
    parser.add_argument("--home", help=f"the factory home (default: ${RIHMA_HOME_ENV}, ${HOME_ENV}, or var/)")
    parser.add_argument("--person", required=True, help="the named person who signs every write")
    parser.add_argument("--persona", required=True, help=f"the persona the reads and writes are for: {', '.join(PERSONAS)}")
    parser.add_argument("--lanes", help="where the product lanes are, for the live cell (default: $GF_LANES or ~/gf-lanes)")
    args = parser.parse_args(argv)
    factory = Factory(args.home)
    if not Path(factory.home).is_dir():
        print(f"refused: the factory home {factory.home} does not exist", file=sys.stderr)
        return 2
    try:
        server = RihmaMCP(factory, person=args.person, persona=args.persona, lanes_root=args.lanes)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"rihma mcp: serving {factory.home} on stdio as {server.person} ({server.persona})", file=sys.stderr)
    with contextlib.suppress(KeyboardInterrupt):
        serve(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
