"""The faces of a capability image (FR-SC3): the text of `factory/faces.py`.

kernel/capability_template.py writes FACES_PY into every capability product (the `capability` template
of the automation profile), in factory/, a protected path: no builder cell may change it, and the pack
pins it among the runtime files. Its HTTP routes are in `factory/faces_http.py`
(kernel/faces_http_image.py), which the product's routes import, so the faces are served wherever the
product runs: on the factory's own roads, in the image (started through pack_guard), and by
`rihmasto capability serve`. It is the standard library only, and it imports nothing from the kernel.
"""

from __future__ import annotations

FACES_PY = r'''"""faces: one capability image, reached several ways (docs/guides/small-capabilities.md).

Written by Rihmasto into every capability product; not the builder's to change (factory/ is protected,
and the capability pack pins this file). The product's work is app/job.py: run(trigger), optionally
chat(messages), and one function per tool app/runtime.json declares. The faces, each only when the
declaration names it:

- mcp: MCP over stdio (`python3 factory/faces.py --face mcp --stdio`) and Streamable HTTP (POST /mcp):
  initialize, ping, tools/list and tools/call. The tools are two reads (capability_describe,
  capability_runs) and the capability's own declared tools, in a fixed order, with the pack's version.
- openai: an OpenAI-compatible chat (GET /v1/models, POST /v1/chat/completions) whose model is the
  capability's name; the capability gateway routes to it as a workload of that name.
- embed: a website's chat (GET /embed/widget.js, POST /embed/messages), only from the declared origins.
- http: POST /capability/run runs the job once; GET /capability/runs lists the recent runs.

The trigger path is POST /capability/trigger (a webhook or a relay event, verified with Standard
Webhooks), and with RIHMA_SCHEDULE=on a scheduled capability runs on its schedule (factory/faces_http.py).

Before a face answers, the declaration must be valid (factory/runtime_decl.py) and, when the pack is
mounted beside the image (RIHMA_PACK), pack_guard's checks must pass: the pack's hash, the file trees,
its status and the smoke set. Otherwise a face answers 503 (a JSON-RPC error on stdio) with the reasons.
RIHMA_FACES (and --face) narrows the faces that answer. A face the declaration does not name, or that is
narrowed away, answers 404, and MCP over stdio answers each request with error -32001.
RIHMA_FACES_TOKEN, when set, is the bearer token the mcp, openai and http faces require. A request whose Origin is not a declared origin is refused.

Each run is kept in DATA_DIR/capability-runs.jsonl. With RIHMA_RESULT_URL and RIHMA_RESULT_SECRET set, each
run also goes out as a CloudEvent (rihma.capability.ran) signed with Standard Webhooks: the result as an
outbound event. A model role reaches the gateway workload the declaration gives it: model(role, messages),
at RIHMA_GATEWAY_URL (its /v1 base), with RIHMA_GATEWAY_TOKEN as the bearer token when one is set.

    python3 factory/faces.py --face mcp --stdio
    python3 factory/faces.py --port 8080 [--face openai] [--schedule]
    python3 factory/faces.py --run '{"kind": "manual"}'      one run, printed as JSON
"""

import argparse
import base64
import contextlib
import datetime
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if __name__ == "__main__":  # run as a file: hand over to the copy app.routes imports, whose routes are served
    from factory.faces import main as _main

    sys.exit(_main())

from app.server import Handler, data_dir, handle  # noqa: E402
from factory.runtime_decl import FACES, canonical, validate  # noqa: E402

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26")
RUNS = "capability-runs.jsonl"
MAX_RESULT = 16 * 1024
LOOPBACK = ("127.0.0.1", "localhost", "::1")
KEPT = ("kind", "source", "ref", "event", "tool", "delivery")   # what a run keeps of its trigger
_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
_LOCK = threading.Lock()
STATE = {"only": None}


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def declaration():
    """The runtime declaration and its problems (empty when it is valid)."""
    try:
        with open(os.path.join(ROOT, "app", "runtime.json"), encoding="utf-8") as fh:
            decl = json.load(fh)
    except (OSError, ValueError) as exc:
        return {}, ["app/runtime.json cannot be read: " + type(exc).__name__]
    return (decl if isinstance(decl, dict) else {}), validate(decl)


def guard():
    """pack_guard's one guard of this process; None when no pack is mounted beside the image (it is off)."""
    if not os.environ.get("RIHMA_PACK"):
        return None
    from factory import pack_guard

    return pack_guard.shared(handle, ROOT)


def not_ready():
    """Why no face may answer now; empty when every check passes."""
    problems = declaration()[1]
    if problems:
        return ["the runtime declaration is not valid: " + "; ".join(problems[:5])]
    g = guard()
    return [] if g is None or g.ready else list(g.reasons)


def pack_version():
    g = guard()
    if g is None:
        return "no pack mounted"
    return g.version or "not checked yet"


def header(headers, name):
    return next((v for k, v in (headers or {}).items() if k.lower() == name), None)


def origins(decl):
    embed = decl.get("embed")
    return list(embed.get("origins") or []) if isinstance(embed, dict) else []


def enabled(face, decl, problems):
    """Whether this face answers at all: declared and narrowed away by neither --face nor RIHMA_FACES. With a
    declaration that is not valid every face answers, with 503 and the reasons."""
    if any(only and face not in only.split(",") for only in (STATE["only"], os.environ.get("RIHMA_FACES"))):
        return False
    return bool(problems) or face in (decl.get("faces") or [])


def refusal(face, headers):
    """(status, body) when this face may not answer the request; None when it may."""
    decl, problems = declaration()
    if not enabled(face, decl, problems):
        return 404, {"error": "not found"}
    origin = header(headers, "origin")
    if (origin or face == "embed") and origin not in origins(decl):
        return 403, {"error": "this origin may not use the capability"}
    token = os.environ.get("RIHMA_FACES_TOKEN")
    given = (header(headers, "authorization") or "").encode("utf-8")
    if token and face != "embed" and not hmac.compare_digest(given, ("Bearer " + token).encode("utf-8")):
        return 401, {"error": "a bearer token is required"}
    why = not_ready()
    return (503, {"error": "not ready", "guard": why}) if why else None


# -- runs ------------------------------------------------------------------------------------------

def now_stamp():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runs(limit=20):
    """The newest runs kept in DATA_DIR, oldest first."""
    try:
        with open(os.path.join(data_dir(), RUNS), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-max(1, min(int(limit), 200)):]:
        with contextlib.suppress(ValueError):
            out.append(json.loads(line))
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect is an answer, never followed


def opener(url):
    """https, or http on this machine only; no proxy on loopback; redirects never followed."""
    parts = urllib.parse.urlsplit(url)
    local = (parts.hostname or "") in LOOPBACK
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("the receiver must be https (http only on this machine)")
    handlers = [urllib.request.ProxyHandler({})] if local else []
    return urllib.request.build_opener(*handlers, _NoRedirect())


def send(rec):
    """The run as a CloudEvent signed with Standard Webhooks, to RIHMA_RESULT_URL; None when none is set."""
    url, secret = os.environ.get("RIHMA_RESULT_URL"), os.environ.get("RIHMA_RESULT_SECRET")
    if not url or not secret:
        return None
    name = declaration()[0].get("name")
    event = {"specversion": "1.0", "id": rec["id"], "source": "/rihmasto/capabilities/%s" % name,
             "type": "rihma.capability.ran", "subject": rec["id"], "time": rec["at"],
             "datacontenttype": "application/json",
             "data": {k: rec[k] for k in ("id", "at", "trigger", "state", "result_sha256")}}
    body, stamp = canonical(event).encode("utf-8"), int(time.time())
    try:
        key = base64.b64decode(secret[6:]) if secret.startswith("whsec_") else secret.encode("utf-8")
        mac = hmac.new(key, ("%s.%d." % (rec["id"], stamp)).encode("utf-8") + body, hashlib.sha256).digest()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/cloudevents+json", "webhook-id": rec["id"], "webhook-timestamp": str(stamp),
            "webhook-signature": "v1," + base64.b64encode(mac).decode("ascii")})
        with opener(url).open(req, timeout=10) as resp:
            return "sent: http %d" % resp.status
    except Exception as exc:  # the receiver's trouble is noted on the run, never the run's failure
        return "not sent: " + type(exc).__name__


def _bounded(work, timeout):
    """work() in a thread, at most ``timeout`` seconds: (result, None), or (None, the error's description)."""
    box = {}

    def target():
        try:
            box["result"] = work()
        except Exception as exc:  # the job's failure is the run's outcome, never a crash of the face
            box["error"] = {"error": type(exc).__name__, "detail": str(exc)[:300]}

    worker = threading.Thread(target=target, name="capability-run", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return None, {"error": "TimedOut", "detail": "the run took longer than %s seconds" % timeout}
    return box.get("result"), box.get("error")


def record(trigger, work):
    """One run of work(): its outcome kept in DATA_DIR, and sent out when a receiver is set."""
    rec = {"id": "run-" + uuid.uuid4().hex[:16], "at": now_stamp(),
           "trigger": {k: v for k, v in trigger.items() if k in KEPT and isinstance(v, str)}}
    timeout = declaration()[0].get("timeout_seconds", 60)
    result, error = _bounded(work, timeout if isinstance(timeout, int) else 60)
    state = "succeeded" if error is None else ("timed_out" if error["error"] == "TimedOut" else "failed")
    result = result if error is None else error
    try:
        text = canonical(result)
    except (TypeError, ValueError):
        result, state = {"error": "the job returned something that is not JSON"}, "failed"
        text = canonical(result)
    rec.update(state=state, result_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
               result=result if len(text) <= MAX_RESULT else {"truncated": True, "bytes": len(text)})
    rec["sent"] = send(rec)
    os.makedirs(data_dir(), exist_ok=True)
    with _LOCK, open(os.path.join(data_dir(), RUNS), "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def run_job(trigger):
    import app.job

    return record(trigger, lambda: app.job.run(dict(trigger)))


def _last_user(turns):
    for turn in reversed(turns):
        if turn.get("role") == "user":
            content = turn.get("content")
            if isinstance(content, list):
                content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
            return str(content or "")[:8000]
    return ""


def chat(messages, kind="chat"):
    """A chat turn as one run: app.job.chat(turns) when the product has it, else a run with the last user text."""
    import app.job

    turns = [m for m in messages if isinstance(m, dict)][-20:]
    own = getattr(app.job, "chat", None)
    if callable(own):
        return record({"kind": kind}, lambda: own(turns))
    return record({"kind": kind}, lambda: app.job.run({"kind": kind, "input": _last_user(turns)}))


def reply_text(rec):
    result = rec.get("result")
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def model(role, messages, **extra):
    """The reply of the gateway workload app/runtime.json gives this model role (RIHMA_GATEWAY_URL)."""
    workload = next((r.get("workload") for r in declaration()[0].get("model_roles") or [] if r.get("role") == role),
                    None)
    base = os.environ.get("RIHMA_GATEWAY_URL")
    if workload is None or not base:
        raise LookupError("no model role %r is declared, or RIHMA_GATEWAY_URL is not set" % role)
    headers = {"Content-Type": "application/json"}
    if os.environ.get("RIHMA_GATEWAY_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["RIHMA_GATEWAY_TOKEN"]
    url = base.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, method="POST", headers=headers, data=json.dumps(
        dict(extra, model=workload, messages=messages, stream=False)).encode("utf-8"))
    with opener(url).open(req, timeout=120) as resp:
        return json.loads(resp.read(4 << 20))["choices"][0]["message"]["content"]


# -- MCP -------------------------------------------------------------------------------------------

def tools(decl):
    """The two reads, then the capability's own tools in the order the declaration gives them."""
    empty = {"type": "object", "properties": {}}
    reads = [{"name": "capability_describe", "inputSchema": empty, "annotations": {"readOnlyHint": True},
              "description": "What this capability is, what starts it and what it needs; secrets by name only."},
             {"name": "capability_runs", "annotations": {"readOnlyHint": True},
              "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
              "description": "The recent runs: when, what started each, its state and its result."}]
    return reads + [{"name": t["name"], "description": t["description"], "inputSchema": t.get("input") or empty,
                     "annotations": {"readOnlyHint": t["effect"] == "read"}} for t in decl.get("tools") or []]


def _arguments(tool, args):
    schema = tool.get("input") or {}
    props = schema.get("properties") or {}
    missing = [k for k in schema.get("required") or [] if k not in args]
    unknown = [k for k in args if k not in props]
    wrong = [k for k, v in args.items() if k in props and (not isinstance(v, _TYPES[props[k]["type"]])
                                                          or isinstance(v, bool) != (props[k]["type"] == "boolean"))]
    if missing or unknown or wrong:
        raise ValueError("arguments: missing %s, unknown %s, wrong type %s" % (missing, unknown, wrong))


def call_tool(decl, name, args):
    if name == "capability_describe":
        return dict(decl, secrets=[s.get("name") for s in decl.get("secrets") or []], pack=pack_version())
    if name == "capability_runs":
        return {"runs": runs(args.get("limit") if isinstance(args.get("limit"), int) else 20)}
    tool = next(t for t in decl.get("tools") or [] if t["name"] == name)
    _arguments(tool, args)
    if name == "run":
        return run_job({"kind": "mcp", "tool": name, "input": args})
    import app.job

    fn = getattr(app.job, name, None)
    if not callable(fn):
        raise LookupError("the tool %s is declared, but app/job.py has no function of that name" % name)
    return record({"kind": "mcp", "tool": name}, lambda: fn(**args))


def _tools_call(decl, params):
    name, args = params.get("name"), params.get("arguments") or {}
    if name not in [t["name"] for t in tools(decl)] or not isinstance(args, dict):
        raise RpcError(-32602, "Unknown tool, or arguments that are not an object: %s" % name)
    try:
        out = call_tool(decl, name, args)
    except (LookupError, ValueError, TypeError) as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}], "structuredContent": out,
            "isError": out.get("state") in ("failed", "timed_out")}


def _initialize(decl, params):
    asked = params.get("protocolVersion")
    return {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": decl["name"], "version": pack_version()},
            "instructions": decl["summary"] + " Its reads and its own tools only: nothing here decides or approves."}


_METHODS = {"initialize": _initialize, "ping": lambda decl, params: {}, "tools/call": _tools_call,
            "tools/list": lambda decl, params: {"tools": tools(decl), "_meta": {
                "rihmasto/capability": decl["name"], "rihmasto/pack": pack_version()}}}


def rpc_error(mid, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": err}


NOT_OFFERED = -32001   # the JSON-RPC error of a face the declaration does not name, or RIHMA_FACES narrowed away


def offered():
    """Whether the mcp face may answer here at all (stdio included): the same rule as every HTTP face."""
    decl, problems = declaration()
    return enabled("mcp", decl, problems)


def mcp(msg):
    """Answer one JSON-RPC message; None for a notification. Every request needs the mcp face offered (declared
    and not narrowed away), then waits on not_ready()."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return rpc_error(None, -32600, "not a JSON-RPC 2.0 message")
    if "id" not in msg:
        return None
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if not offered():
        return rpc_error(mid, NOT_OFFERED, "not found: this capability does not offer the mcp face here",
                         {"face": "mcp", "offered": False})
    if not isinstance(method, str) or not isinstance(params, dict):
        return rpc_error(mid, -32600, "a request needs a method, and params as an object")
    if method not in _METHODS:  # server/discover included: a newer client falls back to initialize
        return rpc_error(mid, -32601, "method not found: %s" % method)
    why = not_ready()
    if why:
        return rpc_error(mid, -32000, "not ready: " + "; ".join(why), {"guard": why})
    try:
        return {"jsonrpc": "2.0", "id": mid, "result": _METHODS[method](declaration()[0], params)}
    except RpcError as exc:
        return rpc_error(mid, exc.code, str(exc))
    except Exception as exc:  # a bug, never a verdict: answer it and keep serving
        return rpc_error(mid, -32603, "internal error: " + type(exc).__name__)


def mcp_batch(msg):
    if isinstance(msg, list):
        return [a for a in (mcp(m) for m in msg) if a is not None] or None
    return mcp(msg)


# -- serving -----------------------------------------------------------------------------------------

def serve_stdio(stdin=None, stdout=None):
    """MCP over stdio: one JSON-RPC message per line; stdout carries protocol messages only."""
    stdin, stdout = stdin or sys.stdin.buffer, stdout or sys.stdout.buffer
    sys.stdout = sys.stderr   # a stray print, even from a run that outlived its timeout, never reaches the protocol
    if not offered():
        print("the mcp face is not offered: app/runtime.json does not name it, or RIHMA_FACES or --face leaves it "
              "out; every request is answered with error %d" % NOT_OFFERED, file=sys.stderr, flush=True)
    for line in iter(stdin.readline, b""):
        if not line.strip():
            continue
        try:
            answer = mcp_batch(json.loads(line.decode("utf-8")))
        except ValueError:
            answer = rpc_error(None, -32700, "Parse error: a message is one line of UTF-8 JSON")
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            stdout.flush()
    return 0


def serve_http(host, port):
    handler = Handler
    if guard() is not None:  # a pack beside it: /health answers through the guard, as in the image
        from factory import pack_guard

        handler = pack_guard.guarded(Handler, guard(), handle)
    server = ThreadingHTTPServer((host, port), handler)
    print(json.dumps({"listening": "http://%s:%d" % (host, server.server_address[1]),
                      "faces": STATE["only"] or "declared"}), flush=True)
    server.serve_forever()


def run_once(text):
    """One run with the trigger given as JSON, printed as JSON; refused while a check does not pass."""
    try:
        trigger = json.loads(text)
    except ValueError:
        trigger = None
    if not isinstance(trigger, dict) or not isinstance(trigger.get("kind"), str):
        print(json.dumps({"state": "refused", "reasons": ["the trigger is a JSON object with a kind"]}))
        return 2
    why = not_ready()
    if why:
        print(json.dumps({"state": "refused", "reasons": why}))
        return 3
    rec = run_job(trigger)
    print(json.dumps(rec, ensure_ascii=False))
    return 0 if rec["state"] == "succeeded" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="factory/faces.py", description="The capability's faces.")
    ap.add_argument("--face", choices=FACES, help="answer on this face only")
    ap.add_argument("--stdio", action="store_true", help="MCP over stdio")
    ap.add_argument("--port", type=int, help="serve HTTP on this port (0: a free one)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--run", metavar="TRIGGER", help="run once with this JSON trigger (- reads it from stdin)")
    ap.add_argument("--schedule", action="store_true", help="also run on the declared schedule")
    args = ap.parse_args(argv)
    import app.routes  # noqa: F401  (the product's routes, which import the HTTP faces)

    STATE["only"] = args.face
    if args.run is not None:
        return run_once(sys.stdin.read() if args.run == "-" else args.run)
    if args.schedule:
        from factory import faces_http

        faces_http.start_schedule()
    if args.stdio or (args.port is None and args.face in (None, "mcp")):
        return serve_stdio()
    if args.port is None:
        ap.error("the %s face is served over HTTP: give --port" % args.face)
    serve_http(args.host, args.port)
    return 0
'''
