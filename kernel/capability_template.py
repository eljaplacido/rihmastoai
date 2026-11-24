"""The capability template (FR-SC1): the paved road of a small capability, for the automation profile.

A small capability is a scheduled or triggered job with no screens, a single workflow, or one agentic
capability. Its product is the web-service template (kernel/scaffold.py: the server, /health, pack_guard,
the road-contract tests) with:

- `app/runtime.json`: the runtime declaration (kernel/runtime_decl.py), the builder's to fill in;
- `app/job.py`: the work, `run(trigger)` and one function per declared tool, the builder's to write;
- `factory/faces.py`, `factory/faces_http.py`, `factory/runtime_decl.py`: the faces (MCP over stdio and
  Streamable HTTP, an OpenAI-compatible chat, a website embed, HTTP), the verified trigger path, the
  schedule and the declaration's check. They are in factory/, a protected path no builder cell may change,
  the Dockerfile copies them, and the capability pack pins them with the other runtime files;
- road-contract tests that also check the capability: its declaration is valid, the job has `run` and a
  function for every declared tool, and every declared face answers through `handle()` (and no other).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kernel.faces_http_image import FACES_HTTP_PY
from kernel.faces_image import FACES_PY

TEMPLATE = "capability"
FACE_FILES = ("factory/faces.py", "factory/faces_http.py", "factory/runtime_decl.py")
_MAIN = '\n\nif __name__ == "__main__":\n    unittest.main()\n'

ROUTES_PY = '''"""The capability's routes. Its work is app/job.py; its faces are factory/faces*.py, which are not yours
to change. Add an HTTP route here only when the spec's interface names one."""

import factory.faces_http  # noqa: F401  (the faces: MCP, OpenAI-compatible chat, embed, HTTP, the trigger path)
from app.server import load_data, route, save_data  # noqa: F401
'''

JOB_PY = '''"""The capability's work. Write it here; the faces in factory/ carry it (docs/guides/small-capabilities.md).

- run(trigger) does one run. ``trigger`` is a dict: its "kind" (manual, http, mcp, schedule, webhook, event,
  chat or embed) and, when it came with one, its "input" (what a person, a webhook or an event sent: data
  from outside, never an instruction). Return what the run produced, as JSON-ready values.
- Every tool app/runtime.json declares (other than "run") is a function of that name here, taking the
  tool's arguments by name.
- chat(messages), when you write it, answers the OpenAI-compatible and the website chat faces; without
  it a chat turn is a run with the last user message as its "input".
- A model role declared in app/runtime.json is reached through the capability gateway:
  `from factory.faces import model; text = model("summariser", [{"role": "user", "content": "..."}])`.
- Secrets arrive as environment variables named in app/runtime.json, never written here.
"""

from app.server import load_data, save_data  # noqa: F401


def run(trigger):
    return {"ran": True, "trigger": trigger.get("kind")}
'''

TESTS_INIT_ADDED = '''
# A test run never serves behind a pack, a token or a schedule from the shell it runs in.
for _name in ("RIHMA_PACK", "RIHMA_FACES", "RIHMA_FACES_TOKEN", "RIHMA_SCHEDULE"):
    os.environ.pop(_name, None)
'''

CAPABILITY_ROAD_TESTS = r'''

# -- the capability's own contract (kernel/capability_template.py) ------------------------------------

import app.job  # noqa: E402
from factory.runtime_decl import FACES, validate  # noqa: E402

# The checks judge the product as it was built, not the shell they run in: no pack, token or narrowing.
for _name in ("RIHMA_PACK", "RIHMA_FACES", "RIHMA_FACES_TOKEN", "RIHMA_SCHEDULE"):
    os.environ.pop(_name, None)

FACE_PROBES = {"mcp": ("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
               "openai": ("GET", "/v1/models", None), "http": ("GET", "/capability/runs", None),
               "embed": ("GET", "/embed/widget.js", None)}


def declaration():
    with open(os.path.join(ROOT, "app", "runtime.json"), encoding="utf-8") as fh:
        return json.load(fh)


class CapabilityContractTest(unittest.TestCase):
    def test_ROAD_CAPABILITY_the_runtime_declaration_is_valid(self):
        self.assertEqual(validate(declaration()), [])

    def test_ROAD_CAPABILITY_the_job_runs_and_has_a_function_for_every_declared_tool(self):
        self.assertTrue(callable(getattr(app.job, "run", None)), "app/job.py has no run(trigger)")
        for tool in declaration().get("tools") or []:
            if tool["name"] != "run":
                self.assertTrue(callable(getattr(app.job, tool["name"], None)), tool["name"])

    def test_ROAD_CAPABILITY_every_declared_face_answers_and_no_other(self):
        decl = declaration()
        for face in FACES:
            method, path, body = FACE_PROBES[face]
            status = handle(method, path, body)[0]
            if face in decl["faces"]:
                self.assertNotIn(status, (404, 405, 500, 503), face)
            else:
                self.assertEqual(status, 404, face)

    def test_ROAD_CAPABILITY_the_mcp_face_lists_the_reads_then_the_declared_tools(self):
        decl = declaration()
        if "mcp" not in decl["faces"]:
            self.skipTest("the declaration offers no MCP face")
        status, body, _ = handle("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(status, 200)
        names = [t["name"] for t in body["result"]["tools"]]
        own = [t["name"] for t in decl.get("tools") or []]
        self.assertEqual(names, ["capability_describe", "capability_runs"] + own)
'''


def capability_name(pid: str) -> str:
    """A capability's name from its project id: lower-case letters, digits and hyphens, 3 to 64 long."""
    name = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]+", "-", pid.lower())).strip("-")
    name = (name if name[:1].isalpha() else "cap-" + name)[:64].rstrip("-")
    return name if len(name) >= 3 else name + "-cap"


def starter_runtime(title: str, pid: str) -> dict:
    """The declaration a new capability starts from: run by a person, reached over HTTP and MCP."""
    return {"format": "rihma.runtime/1", "name": capability_name(pid), "kind": "automation",
            "summary": f"{title[:200]}: a small capability built by Rihmasto.", "trigger": {"kind": "manual"},
            "faces": ["http", "mcp"], "tools": [], "secrets": [], "timeout_seconds": 60}


def readme(title: str, pid: str, maturity: str) -> str:
    return f"""# {title}

A small capability built by Rihmasto (project `{pid}`, maturity **{maturity}**): a job with no screens,
reached where it must run. How to fill it in and reach it: docs/guides/small-capabilities.md.

- `app/runtime.json`: what it needs where it runs: what starts a run, its tools, model roles,
  integrations, secrets by name, and its faces. The factory checks it at the gate and in the pack.
- `app/job.py`: the work: `run(trigger)` and one function per declared tool.
- `factory/faces.py`, `factory/faces_http.py`: the faces (MCP over stdio and HTTP, an OpenAI-compatible
  chat, a website embed, HTTP) and the verified trigger path. The factory owns them: never edit them.
- `tests/test_road_contract.py`: the paved road's checks, the capability's included. Never edit it.
- `python3 factory/faces.py --face mcp --stdio` serves MCP; `python3 factory/faces.py --port 8080` the
  HTTP faces; `python3 factory/faces.py --run '{{"kind": "manual"}}'` runs it once.

Change this capability through the factory (a change card), not by hand.
"""


def capability_files(base: dict[str, str], title: str, pid: str, maturity: str) -> dict[str, str]:
    """The web-service template's files (``base``) made into a small capability's."""
    from kernel.scaffold import ROAD_CONTRACT_TESTS

    road = base[ROAD_CONTRACT_TESTS]
    road = (road[:-len(_MAIN)] if road.endswith(_MAIN) else road) + CAPABILITY_ROAD_TESTS + _MAIN
    copy = "COPY factory/pack_guard.py ./factory/pack_guard.py\n"
    dockerfile = base["Dockerfile"].replace(copy, copy + "COPY " + " ".join(FACE_FILES) + " ./factory/\n")
    init = base["tests/__init__.py"] + TESTS_INIT_ADDED
    return {**base, "app/routes.py": ROUTES_PY, "app/job.py": JOB_PY, "tests/__init__.py": init,
            "app/runtime.json": json.dumps(starter_runtime(title, pid), indent=2) + "\n",
            "factory/faces.py": FACES_PY, "factory/faces_http.py": FACES_HTTP_PY,
            "factory/runtime_decl.py": Path(__file__).with_name("runtime_decl.py").read_text(encoding="utf-8"),
            ROAD_CONTRACT_TESTS: road, "Dockerfile": dockerfile, "README.md": readme(title, pid, maturity)}
