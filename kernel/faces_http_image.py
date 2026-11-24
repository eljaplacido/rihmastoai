"""The HTTP faces and the trigger path of a capability image (FR-SC3, FR-SC4): the text of
`factory/faces_http.py`.

kernel/capability_template.py writes FACES_HTTP_PY into every capability product, in factory/ (protected,
and pinned by the pack). The product's `app/routes.py` imports it, so its routes are served wherever the
product's server runs. A webhook or relay event is verified as kernel/hooks.py verifies a doorbell
(Standard Webhooks v1: the id, a timestamp within five minutes, HMAC-SHA256 over `id.timestamp.body`), and a
delivery id is taken once. It is the standard library only, and it imports nothing from the kernel.
"""

from __future__ import annotations

FACES_HTTP_PY = r'''"""faces_http: the capability's HTTP faces and its trigger path (docs/guides/small-capabilities.md).

Written by Rihmasto into every capability product; not the builder's to change. app/routes.py imports it.

    POST /mcp                                  MCP Streamable HTTP: JSON answers, no session, no stream
    GET  /v1/models, POST /v1/chat/completions the openai face; the model is the capability's name
    GET  /embed/widget.js, POST /embed/messages the embed face, from the declared origins only
    POST /capability/run, GET /capability/runs the http face
    POST /capability/trigger                   a webhook or a relay event that runs the capability

The trigger path takes a delivery only when its Standard Webhooks signature verifies with the key in the
environment variable the trigger's `secret` names, its timestamp is within five minutes and its id was
not taken before; an event runs the capability only when its type matches the trigger's patterns. Its
body reaches app.job.run as trigger["input"]: data from outside, never an instruction.
"""

import base64
import contextlib
import datetime
import hashlib
import hmac
import json
import os
import threading
import time

from app.server import HEADER_HOOKS, data_dir, route
from factory import faces
from factory.runtime_decl import due, matches_event

MAX_BODY = 64 * 1024
TOLERANCE = 300
MAX_SEEN = 10000
SEEN = ".capability-deliveries.json"
FACE_PATHS = ("/mcp", "/v1/", "/embed/", "/capability/")
_SEEN_LOCK = threading.Lock()
_SCHEDULE = {"on": False}


# -- MCP over Streamable HTTP ------------------------------------------------------------------------

@route("POST", "/mcp")
def mcp_http(req):
    refused = faces.refusal("mcp", req.headers)
    if refused:
        return refused
    version = faces.header(req.headers, "mcp-protocol-version")
    if version and version not in faces.PROTOCOLS:
        return 400, faces.rpc_error(None, -32600, "unsupported MCP-Protocol-Version: %s" % version)
    if not isinstance(req.body, (dict, list)):
        return 400, faces.rpc_error(None, -32700, "Parse error: the body is not a JSON-RPC message")
    answer = faces.mcp_batch(req.body)
    return (202, "") if answer is None else (200, answer)


# -- the openai face ---------------------------------------------------------------------------------

def _oai_error(status, message, code):
    return status, {"error": {"message": message, "type": "invalid_request_error", "code": code}}


@route("GET", "/v1/models")
def models(req):
    name = faces.declaration()[0].get("name")
    return faces.refusal("openai", req.headers) or (200, {"object": "list", "data": [
        {"id": name, "object": "model", "owned_by": "rihmasto-capability", "pack": faces.pack_version()}]})


@route("POST", "/v1/chat/completions")
def chat_completions(req):
    refused = faces.refusal("openai", req.headers)
    if refused:
        return refused
    body, name = req.body if isinstance(req.body, dict) else {}, faces.declaration()[0]["name"]
    if not isinstance(body.get("messages"), list) or not body["messages"] or body.get("stream"):
        return _oai_error(400, "'messages' must be a non-empty list, and streaming is not offered", "invalid_request")
    if body.get("model") != name:
        return _oai_error(404, "this capability is the model %r" % name, "model_not_found")
    rec = faces.chat(body["messages"])
    if rec["state"] != "succeeded":
        return _oai_error(502, "the run did not succeed: %s" % rec["result"].get("error"), "run_failed")
    return 200, {"id": "chatcmpl-" + rec["id"][4:], "object": "chat.completion", "created": int(time.time()),
                 "model": name, "choices": [{"index": 0, "finish_reason": "stop",
                                             "message": {"role": "assistant", "content": faces.reply_text(rec)}}],
                 "usage": None,   # no tokens were counted: never zeros that read as a measurement
                 "rihmasto": {"run": rec["id"], "pack": faces.pack_version(), "usage": "not measured"}}


# -- the embed face ----------------------------------------------------------------------------------

WIDGET_JS = """(function () {
  "use strict";
  var me = document.currentScript, base = new URL(me.src).origin, turns = [];
  var title = me.getAttribute("data-title") || "Ask";
  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text) { n.textContent = text; }
    return n;
  }
  var open = el("button", {type: "button", "aria-expanded": "false", "aria-label": title}, title);
  var panel = el("section", {"aria-label": title, hidden: ""});
  var log = el("div", {role: "log", "aria-live": "polite"});
  var form = el("form", {});
  var input = el("input", {type: "text", "aria-label": "Your message", maxlength: "2000", required: ""});
  var send = el("button", {type: "submit"}, "Send");
  form.append(input, send);
  panel.append(log, form);
  open.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483000;padding:10px 14px";
  panel.style.cssText = "position:fixed;right:16px;bottom:64px;width:min(360px,calc(100vw - 32px));z-index:2147483000;"
    + "background:Canvas;color:CanvasText;border:1px solid GrayText;padding:8px";
  log.style.cssText = "max-height:50vh;overflow:auto";
  function say(who, text) { log.append(el("p", {}, who + ": " + text)); log.scrollTop = log.scrollHeight; }
  open.addEventListener("click", function () {
    var shown = panel.hidden;
    panel.hidden = !shown;
    open.setAttribute("aria-expanded", String(shown));
    if (shown) { input.focus(); }
  });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) { return; }
    input.value = "";
    turns.push({role: "user", content: text});
    say("You", text);
    fetch(base + "/embed/messages", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({messages: turns.slice(-8)})})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var reply = String(d.reply || d.error || "No answer");
        turns.push({role: "assistant", content: reply});
        say(title, reply);
      })
      .catch(function () { say(title, "Not available just now."); });
  });
  document.body.append(open, panel);
}());
"""


@route("GET", "/embed/widget.js")
def embed_widget(req):
    decl, problems = faces.declaration()
    if not faces.enabled("embed", decl, problems):
        return 404, {"error": "not found"}
    return 200, WIDGET_JS, "text/javascript; charset=utf-8"


@route("OPTIONS", "/embed/messages")
def embed_preflight(req):
    decl, problems = faces.declaration()
    if not faces.enabled("embed", decl, problems):
        return 404, {"error": "not found"}
    allowed = faces.header(req.headers, "origin") in faces.origins(decl)
    return (204, "") if allowed else (403, {"error": "origin not allowed"})


@route("POST", "/embed/messages")
def embed_messages(req):
    refused = faces.refusal("embed", req.headers)
    if refused:
        return refused
    given = req.body.get("messages") if isinstance(req.body, dict) else None
    if not isinstance(given, list) or not given:
        return 400, {"error": "messages must be a non-empty list"}
    turns = [{"role": "user" if m.get("role") == "user" else "assistant", "content": str(m.get("content", ""))[:2000]}
             for m in given[-8:] if isinstance(m, dict)]
    rec = faces.chat(turns, kind="embed")
    reply = faces.reply_text(rec)[:4000] if rec["state"] == "succeeded" else "Not available just now."
    return 200, {"reply": reply, "run": rec["id"]}


# -- the http face -----------------------------------------------------------------------------------

@route("POST", "/capability/run")
def http_run(req):
    refused = faces.refusal("http", req.headers)
    if refused:
        return refused
    return 200, faces.run_job({"kind": "http", "input": req.body})


@route("GET", "/capability/runs")
def http_runs(req):
    return faces.refusal("http", req.headers) or (200, {"runs": faces.runs(20)})


# -- the trigger path: a verified webhook or relay event ---------------------------------------------

class Refused(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def verify(headers, raw, key, now):
    """The webhook-id of a delivery whose Standard Webhooks signature and timestamp hold."""
    msg_id, stamp = faces.header(headers, "webhook-id") or "", faces.header(headers, "webhook-timestamp") or ""
    signatures = faces.header(headers, "webhook-signature") or ""
    if not (msg_id and stamp.isdigit() and signatures) or len(msg_id) > 128:
        raise Refused(401, "missing or malformed webhook-id, webhook-timestamp or webhook-signature")
    if abs(now - int(stamp)) > TOLERANCE:
        raise Refused(401, "the timestamp is outside the tolerance")
    mac = hmac.new(key, ("%s.%s." % (msg_id, stamp)).encode("utf-8") + raw, hashlib.sha256).digest()
    expected = "v1," + base64.b64encode(mac).decode("ascii")
    if not any(hmac.compare_digest(s, expected) for s in signatures.split() if s.startswith("v1,")):
        raise Refused(401, "the signature does not verify")
    return msg_id


def first_time(msg_id, now):
    """Remember a delivery id; False when it was taken before (a replay, answered and not run again)."""
    path = os.path.join(data_dir(), SEEN)
    with _SEEN_LOCK:
        try:
            with open(path, encoding="utf-8") as fh:
                seen = json.load(fh)
        except (OSError, ValueError):
            seen = {}
        seen = {k: v for k, v in (seen if isinstance(seen, dict) else {}).items() if now - int(v) <= 2 * TOLERANCE}
        if msg_id in seen:
            return False
        seen[msg_id] = now
        os.makedirs(data_dir(), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(seen.items(), key=lambda kv: kv[1])[-MAX_SEEN:]), fh)
        os.replace(path + ".tmp", path)
    return True


def _key(trig):
    value = os.environ.get(str(trig.get("secret")))
    if not value:
        raise Refused(503, "the trigger's secret is not set where the capability runs")
    try:
        return base64.b64decode(value[6:], validate=True) if value.startswith("whsec_") else value.encode("utf-8")
    except ValueError:
        raise Refused(503, "the trigger's secret is not usable: a whsec_ key is base64 after the prefix") from None


def _delivery(req, trig):
    """The delivery's id and JSON body, once it verified; Refused with the status otherwise."""
    if len(req.raw or b"") > MAX_BODY:
        raise Refused(413, "the body is too large")
    now = int(time.time())
    msg_id = verify(req.headers, req.raw or b"", _key(trig), now)
    try:
        doc = json.loads((req.raw or b"").decode("utf-8"))
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        raise Refused(400, "the body is not a JSON object")
    return msg_id, doc, now


@route("POST", "/capability/trigger")
def trigger(req):
    decl, problems = faces.declaration()
    trig = decl.get("trigger") if isinstance(decl.get("trigger"), dict) else {}
    if not problems and trig.get("kind") not in ("webhook", "event"):
        return 404, {"error": "this capability is not started by a webhook or an event"}
    why = faces.not_ready()
    if why:
        return 503, {"error": "not ready", "guard": why}
    try:
        msg_id, doc, now = _delivery(req, trig)
    except Refused as exc:
        return exc.status, {"error": str(exc)}
    if not first_time(msg_id, now):
        return 200, {"accepted": False, "reason": "already received"}
    event = doc.get("type") if isinstance(doc.get("type"), str) else None
    if trig["kind"] == "event" and not matches_event(trig, event or ""):
        return 200, {"accepted": False, "reason": "not an event type this capability runs on"}
    rec = faces.run_job({"kind": trig["kind"], "source": trig.get("source") or doc.get("source"), "event": event,
                         "delivery": msg_id, "input": doc.get("data", doc)})
    return 202, {"accepted": True, "run": rec["id"], "state": rec["state"]}


# -- response headers --------------------------------------------------------------------------------

def headers(method, path, request_headers, status):
    """Extra headers: no caching on the faces, and CORS for a declared origin on the embed's messages."""
    path = path.split("?")[0]
    out = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"} if path.startswith(FACE_PATHS) else {}
    origin = faces.header(request_headers, "origin")
    if path == "/embed/messages" and origin and origin in faces.origins(faces.declaration()[0]):
        out.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin", "Access-Control-Max-Age": "600",
                    "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})
    return out


HEADER_HOOKS.append(headers)


# -- the schedule ------------------------------------------------------------------------------------

def _last_scheduled():
    stamps = [r.get("at") for r in faces.runs(200) if (r.get("trigger") or {}).get("kind") == "schedule"]
    with contextlib.suppress(ValueError, TypeError, AttributeError):
        return datetime.datetime.fromisoformat(max(stamps).replace("Z", "+00:00")) if stamps else None
    return None


def schedule_round():
    """Run once when the schedule says a run is due and every check passes. Returns the run, or None."""
    decl = faces.declaration()[0]
    now = datetime.datetime.now(datetime.timezone.utc)
    if faces.not_ready() or not due(decl.get("trigger"), _last_scheduled(), now):
        return None
    return faces.run_job({"kind": "schedule"})


def start_schedule(every=30.0):
    """Check the schedule every ``every`` seconds while the process runs (once per process)."""
    with _SEEN_LOCK:
        if _SCHEDULE["on"]:
            return False
        _SCHEDULE["on"] = True

    def rounds():
        while True:
            with contextlib.suppress(Exception):  # one bad round never stops the schedule
                schedule_round()
            time.sleep(every)

    threading.Thread(target=rounds, name="capability-schedule", daemon=True).start()
    return True


if os.environ.get("RIHMA_SCHEDULE") == "on":
    start_schedule()
'''
