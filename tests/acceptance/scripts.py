"""The scripted world the acceptance matrix runs in (docs/acceptance.md): offline, with no Gnomon.

- **AcceptanceModel** extends the demo's scripted model (kernel/demo.py ScriptedModel): it answers
  the panel, the analyst, the holdout author and the amendment for the needs in `needs.py`, and
  falls back to the demo's own scripts for anything else.
- **InterfaceCell** stands in for a Gnomon builder cell and the verifier: for each criterion its
  envelope lets it see, it routes the call the criterion names to the status its "then" names, and
  writes a test named by the criterion that fails before the route exists.
- **StockCell** builds the low-stock list on the adopted stock service (the brownfield row).
- **AcceptanceCase** is a fresh factory home per test, local paved roads on loopback, every
  process a road started stopped afterwards, and a guard that fails the test on any Gnomon call or
  any connection or name lookup beyond loopback.

The kernel is real everywhere else: the panel and the brief, the spec's ids and provenance, the
hashed contract, the gate (the product's own tests, the trace, fail-first, the verifier), holdouts
in custody, the paved road, the capability pack, the change loop, access and the ledger.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from kernel import demo
from kernel import roads as roadmod
from kernel.canon import Canon
from kernel.intake import intake
from kernel.lanes import ROUTING_FILE, Lanes
from kernel.pipeline import advance
from kernel.store import MATURITIES, Factory, FixedClock, read_json, write_json

from .needs import NEEDS, STOCK_AMENDMENT, TEXTS

# The test personas who decide in the acceptance runs: (name, persona). Neutral first names.
OWNER = ("Aino", "business_owner")
PRODUCT = ("Pekka", "product_owner")
IT = ("Jaana", "it")
DEVELOPER = ("Olli", "developer")
COMPLIANCE = ("Sanna", "compliance")

LOOPBACK = {"127.0.0.1", "::1", "localhost", None}
GNOMON_ENTRY_POINTS = ("kernel.model.run_gnomon_task", "kernel.gate.run_gnomon_task", "kernel.dispatch.run_gnomon_task",
                       "kernel.model.gnomon_cmd", "kernel.model.GnomonModel.ask", "kernel.dispatch.ingest_latest_run")
# One local road for every environment, on loopback (as tests/test_deliver.py configures it).
LOCAL_ROADS = {
    "schema": roadmod.SCHEMA,
    "roads": {"local": {"kind": "local-process", "configured": True, "environments": list(roadmod.ENVIRONMENTS),
                        "rules": {"tls": "none: loopback only", "egress": "none"}}},
    "maturity": {m: "local" for m in MATURITIES},
}
# How each card's owner decides it when a person says yes (the persona actions of docs/acceptance.md).
YES = {"approval": ("approve", OWNER), "validation": ("accept", OWNER), "deploy_gate": ("approve", IT),
       "change": ("accept", OWNER)}


def fence(obj: Any) -> str:
    return "```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```"


def need_of(prompt: str) -> str | None:
    """Which need of the matrix a prompt is about, by the phrases only that need's texts hold."""
    low = prompt.lower()
    return next((key for key, need in NEEDS.items() if any(m in low for m in need["markers"])), None)


class AcceptanceModel(demo.ScriptedModel):
    """The demo's scripted model, taught the matrix's needs. It is not a model: it tells which need
    and which kind of prompt it is, and answers from the script."""

    name = "acceptance-model"

    @staticmethod
    def _script(prompt: str) -> Any:
        if prompt.startswith("Amend a software specification") and "low-stock" in prompt:
            return STOCK_AMENDMENT
        key = need_of(prompt)
        if key is None:
            return demo.ScriptedModel._script(prompt)
        need = NEEDS[key]
        if "perspective on a panel" in prompt:
            for perspective, questions in need["panel"].items():
                if f"You are the **{perspective}** perspective" in prompt:
                    return {"reading": f"The {perspective.replace('_', ' ')} reading (scripted for the matrix).",
                            "questions": questions}
            return None
        if prompt.startswith("A panel of perspectives"):
            return {"opinions": need["opinions"]}
        if prompt.startswith("You turn a brief into a software specification"):
            return need["spec"]
        if prompt.startswith("You write acceptance scenarios"):
            return need["holdouts"]
        return None


# -- the scripted builder cells ----------------------------------------------------------------------

CRITERION = re.compile(r"^- \*\*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-AC-\d+)\*\*: given (.*?); when (.*?); then (.*)$",
                       re.MULTILINE)
CALL = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s,;)\"'`]*)")
STATUS = re.compile(r"^\s*([1-5]\d\d)\b")
CASES_FILE = "app/cases.json"
ROUTES = '''"""Routes written by the acceptance matrix's scripted builder cell (tests/acceptance/scripts.py).

Each route answers the criteria that name its call with the status their "then" names: the case
is the criterion id the caller sends, else the route's first criterion."""

import json
from pathlib import Path

from app.server import route

CASES = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))


def _answer(call, cases):
    first = next(iter(cases.values()))

    def answer(req):
        body = req.body if isinstance(req.body, dict) else {}
        case = str(body.get("criterion") or "")
        return cases.get(case, first), {"call": call, "criterion": case or None}

    return answer


for _call, _cases in CASES.items():
    _method, _path = _call.split(" ", 1)
    route(_method, _path)(_answer(_call, _cases))
'''
TEST_HEAD = '''import unittest

import app.routes  # noqa: F401
from app.server import handle


class {cls}(unittest.TestCase):
'''


def _record(task: str, steps: int, output: str) -> dict:
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": steps,
            "model": "acceptance-builder", "output": f"{task}: {output} (scripted for the acceptance matrix)"}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def call_of(cid: str, when: str, then: str) -> tuple[str, str, int]:
    """The call a criterion names in its "when" (else its "then"), and the status its "then" starts
    with (200 when it names none)."""
    m = CALL.search(when) or CALL.search(then)
    method, path = (m.group(1), m.group(2).rstrip(".,:")) if m else ("GET", f"/criteria/{cid}")
    status = STATUS.match(then)
    return method, path, int(status.group(1)) if status else 200


class InterfaceCell:
    """Stands in for a Gnomon builder cell and the verifier (read-only, no findings)."""

    def __init__(self) -> None:
        self.tasks: list[str] = []

    def __call__(self, lane_path: Any, prompt: str) -> dict:
        envelope = demo.ENVELOPE.search(prompt)
        if envelope is None:
            raise AssertionError("the scripted builder was given a prompt without a task envelope")
        task, lane = envelope.group(1), Path(lane_path)
        self.tasks.append(task)
        cases = read_json(lane / CASES_FILE) or {}
        tests = []
        for cid, _, when, then in CRITERION.findall(prompt):
            method, path, status = call_of(cid, when, then)
            cases.setdefault(f"{method} {path}", {})[cid] = status
            concrete = re.sub(r"\{\w+\}", "1", path)
            tests += [f"    def test_{cid.replace('-', '_')}_answers_as_its_criterion_says(self):",
                      f"        status, _, _ = handle({method!r}, {concrete!r}, {{'criterion': {cid!r}}})",
                      f"        self.assertEqual(status, {status})", ""]
        write_json(lane / CASES_FILE, cases)
        routes = ROUTES     # a small capability's routes keep its faces (kernel/capability_template.py)
        if (lane / "app" / "runtime.json").exists():
            routes = routes.replace("from app.server import route", "import factory.faces_http  # noqa: F401\n"
                                                                    "from app.server import route")
        _write(lane / "app" / "routes.py", routes)
        cls = task.replace("-", "") + "Test"
        _write(lane / "tests" / f"test_{task.lower().replace('-', '_')}.py",
               TEST_HEAD.format(cls=cls) + "\n".join(tests).rstrip() + "\n")
        return _record(task, 6, "routed each visible criterion's call and wrote its test first")

    @staticmethod
    def verify(prompt: str) -> str:
        return fence({"findings": []})


LOW_STOCK_CODE = '''"""The low-stock list (written by the acceptance matrix's scripted cell)."""


def low_stock(levels, threshold):
    """The items whose level is below ``threshold``, by name."""
    return sorted(sku for sku, level in levels.items() if level < threshold)
'''


ROOT_SUITE_FILES = {
    "README.md": "# Job scheduler\n\nRuns a job every n minutes. Its tests sit beside it at the root.\n",
    "scheduler.py": '"""Run a job every n minutes."""\n\n\ndef next_run(last, minutes):\n'
                    '    """The minute the job runs next."""\n    return last + minutes\n',
    "test_scheduler.py": "import unittest\n\nfrom scheduler import next_run\n\n\n"
                         "class NextRunTest(unittest.TestCase):\n"
                         "    def test_next_run_adds_the_interval(self):\n"
                         "        self.assertEqual(next_run(10, 5), 15)\n\n"
                         "    def test_an_interval_of_zero_runs_at_once(self):\n"
                         "        self.assertEqual(next_run(10, 0), 10)\n",
}


class StockCell(InterfaceCell):
    """Builds the low-stock list on the adopted stock service, inside the write scope the kernel's
    surface gives a cell there (app/** and tests/**)."""

    def __call__(self, lane_path: Any, prompt: str) -> dict:
        envelope = demo.ENVELOPE.search(prompt)
        if envelope is None:
            raise AssertionError("the scripted builder was given a prompt without a task envelope")
        task, lane = envelope.group(1), Path(lane_path)
        self.tasks.append(task)
        _write(lane / "app" / "__init__.py", '"""What the factory adds to the stock levels service."""\n')
        _write(lane / "app" / "low_stock.py", LOW_STOCK_CODE)
        lines = ["import unittest", "", "from app.low_stock import low_stock", "", "",
                 "class LowStockTest(unittest.TestCase):"]
        for cid, *_ in CRITERION.findall(prompt):
            lines += [f"    def test_{cid.replace('-', '_')}_only_items_below_the_threshold_are_listed(self):",
                      "        self.assertEqual(low_stock({'drill': 1, 'ladder': 9}, 3), ['drill'])", ""]
        _write(lane / "tests" / "test_low_stock.py", "\n".join(lines).rstrip() + "\n")
        return _record(task, 4, "added the low-stock list and its test")


# -- what the ledger says: D-0017's trace -------------------------------------------------------------

def payloads(project: Any, *kinds: str) -> list:
    return [r["event"]["payload"] for r in project.ledger().of_kind(*kinds)]


def trace(project: Any) -> dict:
    """D-0017's trace of one project as its hash-chained ledger holds it: who asked, who decided (or
    let the factory assume), what was assumed, and what proves the work."""
    asked = [p["requested_by"] for p in payloads(project, "intake_done") if p.get("requested_by")]
    asked += [p["person"] for p in payloads(project, "cockpit_write") if p.get("action") == "new_project"]
    return {
        "asked": asked,
        "decided": [(p["person"], p["persona"], p["kind"], p["verdict"]) for p in payloads(project, "decision")],
        "delegated": [p["chosen_by"] for p in payloads(project, "question_assumed") if p.get("chosen_by")],
        "assumed": [p["id"] for p in payloads(project, "assumption_added")],
        "gates": [(p["task"], p["verdict"]) for p in payloads(project, "gate")],
        "releases": [p.get("release") for p in payloads(project, "release_done")],
        "packs": [(p["version"], p["valid"]) for p in payloads(project, "pack_versioned")],
        "intact": project.ledger().verify().intact,
    }


# -- the test base ------------------------------------------------------------------------------------

class AcceptanceCase(unittest.TestCase):
    """A fresh factory home per test: the scripted model, local roads on loopback, nothing left
    running, and no Gnomon or network beyond loopback (a call to either fails the test)."""

    roads = True

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rihmasto-acceptance-"))
        self.addCleanup(roadmod.rmtree, self.tmp)
        self.clock = FixedClock()
        self.factory = Factory(self.tmp / "home", clock=self.clock)
        self.lanes = Lanes(self.tmp / "lanes", size=1)
        self.model = AcceptanceModel()
        self.gnomon_calls: list = []
        self.network: list = []
        self._offline()
        if self.roads:
            write_json(self.factory.paved_roads_path, LOCAL_ROADS)
        self.addCleanup(roadmod.stop_started)
        self.addCleanup(self._stop_every_slot)

    def _offline(self) -> None:
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        real_connect, real_lookup = socket.socket.connect, socket.getaddrinfo

        def no_gnomon(*args: Any, **kwargs: Any) -> None:
            self.gnomon_calls.append(args[:1])
            raise AssertionError("an acceptance run called Gnomon")

        def connect(sock: socket.socket, address: Any) -> Any:
            host = address[0] if isinstance(address, tuple) else address
            if host not in LOOPBACK:
                self.network.append(("connect", host))
                raise OSError(f"the acceptance run refuses a connection to {host}")
            return real_connect(sock, address)

        def lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
            if host not in LOOPBACK:
                self.network.append(("lookup", host))
                raise socket.gaierror(f"the acceptance run refuses a lookup of {host}")
            return real_lookup(host, *args, **kwargs)

        keys = {ep["api_key_env"] for ep in (read_json(ROUTING_FILE) or {}).get("endpoints", {}).values()
                if isinstance(ep, dict) and ep.get("api_key_env")}
        stack.enter_context(mock.patch.dict(os.environ, {"GNOMON_CMD": "rihmasto-acceptance-no-such-gnomon"}))
        for key in keys | {k for k in os.environ if k.endswith("_API_KEY")}:
            os.environ.pop(key, None)
        for target in GNOMON_ENTRY_POINTS:
            stack.enter_context(mock.patch(target, side_effect=no_gnomon))
        stack.enter_context(mock.patch.object(socket.socket, "connect", connect))
        stack.enter_context(mock.patch.object(socket, "getaddrinfo", lookup))
        self.addCleanup(self._still_offline)

    def _still_offline(self) -> None:
        self.assertEqual(self.gnomon_calls, [], "an acceptance run called Gnomon")
        self.assertEqual(self.network, [], "an acceptance run reached beyond loopback")

    def _stop_every_slot(self) -> None:
        for p in self.factory.projects():
            with contextlib.suppress(Exception):  # a slot that is already gone
                roadmod.stop_all(p, LOCAL_ROADS)

    # -- what a persona does ----------------------------------------------------------------------

    def need(self, key: str, *, mode: str = "mixed", maturity: str = "explore", profile: str | None = None,
             requested_by: str = OWNER[0]) -> Any:
        """A person files one of the matrix's needs: a new project and its intake. The written spec
        is a markdown file, as a person hands one in; every other need is typed."""
        p = self.factory.new_project(NEEDS[key]["spec"]["title"], maturity=maturity, mode=mode, profile=profile)
        if key == "visitors":
            path = self.tmp / "visitor-sign-in.md"
            _write(path, TEXTS[key])
            intake(p, str(path), model=self.model, requested_by=requested_by)
        else:
            intake(p, TEXTS[key], model=self.model, requested_by=requested_by, literal=True)
        return p

    def run_chain(self, project: Any, cell: Any = None) -> dict:
        """Advance the project as far as it goes without a person: the real pipeline, with the
        scripted cell and verifier where Gnomon's would run."""
        cell = cell or InterfaceCell()
        return advance(project, model=self.model, lanes=self.lanes, cell_runner=cell, verifier_runner=cell.verify,
                       deliver_kwargs={})

    def answer_blocking(self, project: Any, who: tuple = OWNER) -> list:
        """A person answers every open blocking question with the first option offered (the panel's
        proposal; for the profile question, the first candidate)."""
        return self.answer_open(project, who, blocking_only=True)

    def answer_open(self, project: Any, who: tuple = OWNER, *, blocking_only: bool = False) -> list:
        """A person answers the open questions (every one, or the blocking ones) with the first option."""
        canon, answered = Canon(project), []
        for q in canon.questions("open"):
            if q["blocking"] or not blocking_only:
                with self.signed(who):
                    canon.answer(q["id"], q["options"][0], person=who[0], persona=who[1])
                answered.append(q["id"])
        return answered

    def ship(self, project: Any, cell: Any = None, *, rounds: int = 8) -> tuple[dict, list]:
        """Run the chain to its end, each time it waits deciding the waiting card as its owner says
        yes (YES): a blocking question is answered with its first option. Returns the last outcome
        and the cards decided, as (kind, persona)."""
        cell, decided = cell or InterfaceCell(), []
        for _ in range(rounds):
            out = self.run_chain(project, cell)
            if out["state"] != "waiting" or not out.get("waiting_on"):
                return out, decided
            for card_id in out["waiting_on"]:
                card = self.card(project, card_id)
                if card["kind"] == "question":
                    qid = card["refs"]["question"]
                    q = Canon(project).question(qid)
                    with self.signed(OWNER):
                        Canon(project).answer(qid, q["options"][0], person=OWNER[0], persona=OWNER[1])
                    decided.append(("question", OWNER[1]))
                    continue
                if card["kind"] not in YES:
                    return out, decided
                verdict, who = YES[card["kind"]]
                self.decide(project, card_id, verdict, who, f"{who[0]} says yes as the acceptance run's persona")
                decided.append((card["kind"], who[1]))
        raise AssertionError(f"the chain did not finish in {rounds} rounds: {out}")

    def signed(self, who: tuple) -> contextlib.AbstractContextManager:
        """The identity a decision by ``who`` is signed with: none in single-operator mode. The
        enforced-access cells sign as the verified identity (kernel.access.signing)."""
        return contextlib.nullcontext()

    def decide(self, project: Any, card_id: str, verdict: str, who: tuple, reason: str = "") -> dict:
        with self.signed(who):
            return Canon(project).decide(card_id, verdict, person=who[0], persona=who[1], reason=reason)

    def card(self, project: Any, card_id: str) -> dict:
        return Canon(project).get_card(card_id)

    def kinds(self, project: Any, kind: str) -> list:
        return payloads(project, kind)

    # -- what every cell checks -------------------------------------------------------------------

    def assertDelivered(self, project: Any, out: dict, env: str) -> dict:
        """The release landed in ``env``, every task merged through a passed gate, and the capability
        pack built from the release says what it lacks: valid where every criterion has evidence. On
        the preview (explore) no holdout runs, so a pack whose spec holds one is not valid, and says
        which criteria were not measured."""
        from kernel.packs import build_pack

        self.assertEqual((out["state"], out.get("env")), ("done", env), out)
        spec = project.read("spec.json")
        merged = {p["task"] for p in payloads(project, "merged")}
        self.assertEqual(merged, {t["id"] for t in project.read("contract.json")["tasks"]})
        pack = build_pack(project)
        acceptance = pack["acceptance"]
        held = {c["id"] for c in acceptance["criteria"] if c["kind"] in ("holdout", "probe")}
        self.assertEqual({c["state"] for c in acceptance["criteria"] if c["id"] not in held}, {"verified"})
        if env == "preview" and held:
            self.assertFalse(acceptance["valid"])
            self.assertEqual({(c["criterion"], c["state"]) for c in acceptance["not_valid_because"]},
                             {(cid, "not_measured") for cid in held})
        else:
            self.assertTrue(acceptance["valid"], acceptance)
        self.assertEqual(pack["provenance"]["signature"], None)    # "not signed", said plainly
        self.assertEqual(pack["pinned"]["contract_revision"], project.read("contract.json")["revision"])
        self.assertEqual(len(spec["requirements"]), len({r["id"] for r in spec["requirements"]}))
        return pack

    def assertTraced(self, project: Any, *, decided_by: set | None = None) -> dict:
        """D-0017: who decided (by name and persona), what was assumed, what proves it, in an intact
        hash-chained ledger. Who asked is checked on its own (test_trace.py): today it is not in the
        ledger on this path."""
        t = trace(project)
        self.assertTrue(t["intact"])
        self.assertTrue(t["gates"] and all(v in ("passed", "failed", "escalate") for _, v in t["gates"]))
        for person, persona, _, _ in t["decided"]:
            self.assertTrue(person and persona, t["decided"])
        if decided_by is not None:
            self.assertEqual({(p, r) for p, r, _, _ in t["decided"]}, decided_by)
        return t

    # -- brownfield ------------------------------------------------------------------------------

    def existing_service(self) -> Path:
        """The demo's existing stock levels service: a small git repository with its own tests."""
        repo = self.tmp / "existing" / "stock-levels"
        demo._existing_repo(repo, self.clock.stamp())
        return repo

    def root_suite_service(self) -> Path:
        """A small job scheduler shaped like the `schedule` candidate of the live brownfield run: one
        module and its unittest suite at the repository's root, no tests/ folder and no pytest marker."""
        repo = self.tmp / "existing" / "job-scheduler"
        with mock.patch.dict(demo.STOCK_FILES, ROOT_SUITE_FILES, clear=True), \
                mock.patch.object(demo, "STOCK_COMMIT", "The job scheduler and its tests"):
            demo._existing_repo(repo, self.clock.stamp())
        return repo

    # -- access ----------------------------------------------------------------------------------

    def enforce(self, bindings: list, people: dict) -> None:
        """IT writes an enforced access file: the proxy whose signed token the cockpit verifies (the
        provider's keys are the live identity test's), the people and their bindings."""
        from kernel import access as kaccess

        it_admin = "local:it-admin"
        doc = {"schema": kaccess.SCHEMA, "mode": "enforced", "changed_by": it_admin,
               "proxy": {"preset": "oauth2-proxy", "issuer": "https://login.example.org",
                         "origin": "https://rihmasto.example.org", "audience": "rihmasto-acceptance",
                         "groups_claim": "groups"},
               "people": [{"identity": k, "name": v} for k, v in {**people, it_admin: "Ilkka"}.items()],
               "bindings": [*bindings, {"subject": it_admin, "persona": "it", "scope": "*"}]}
        write_json(kaccess.access_path(self.factory), doc)
