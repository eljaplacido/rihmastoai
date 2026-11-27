"""The gate: whether a cell's change is warranted. The kernel runs the checks itself, apart from
the builder (FR-G6).

The signals for one task:
- **tests:** the product's whole suite, run by the kernel. Exit 0 is passed.
- **trace:** every visible criterion of the task is named by a test that the kernel saw run. A
  test that was skipped, marked as an expected failure or never collected names nothing.
- **fail-first:** each criterion's tests fail at the base revision. A test that passes, is
  skipped or never runs before the change proves nothing.
- **verifier:** a read-only role on another model family tries to break the change. An
  in-scope finding is an objection. An answer with no findings list is not measured.

A change that touches what a cell may not write (the surface, the contract, the factory's files)
is a violation, and the verifier does not run: it would run under the surface the change rewrote.
Each signal keeps its native value beside its named verdict. The combined verdict uses FR-G3's
precedence. *Warranted* means the combined verdict is passed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kernel import access_isolation as isolation
from kernel import integration_standins as standins
from kernel.gate_own import tests_or_own
from kernel.lanes import protected_paths
from kernel.model import ModelError, extract_json, run_gnomon_task
from kernel.verdicts import combine_verdicts

# The outcomes of a test that ran to its end; the others (skipped, expected failure, unexpected
# success) are a test that did not show its behaviour.
RAN = ("ok", "FAIL", "ERROR")
FAILING = ("FAIL", "ERROR")
SEVERITIES = ("high", "medium", "low")  # of a verifier's finding
_WORST = {"ok": 0, "skipped": 1, "expected failure": 2, "unexpected success": 3, "FAIL": 4, "ERROR": 4}

# The suite runs through unittest's own discovery and text runner, as `python -m unittest discover
# -s tests -v [-k pattern]` does, and every outcome is also written to a file by test id. A test
# with a docstring (two lines in -v output) or one that writes to stderr mid-line is seen as surely
# as any other. An error outside a test (a module that cannot be imported, a failing setUpClass)
# keeps its scope, the module or class it hit. Code under test can still lie about itself; fail-first
# and the verifier are there for that.
_RUNNER = r'''
import json, sys, unittest


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen = []

    def note(self, test, outcome):
        kind, scope = type(test).__name__, None
        if kind == "_FailedTest":
            scope = test._testMethodName
        elif kind == "_ErrorHolder":
            text = str(getattr(test, "description", ""))
            scope = text[text.find("(") + 1:text.rfind(")")] if "(" in text else text
        self.seen.append({"id": test.id(), "name": getattr(test, "_testMethodName", "") or "",
                          "outcome": outcome, "scope": scope})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.note(test, "FAIL" if issubclass(err[0], test.failureException) else "ERROR")


def noting(name, outcome):
    def add(self, test, *rest):
        getattr(unittest.TextTestResult, name)(self, test, *rest)
        self.note(test, outcome)
    return add


for name, outcome in (("addSuccess", "ok"), ("addFailure", "FAIL"), ("addError", "ERROR"), ("addSkip", "skipped"),
                      ("addExpectedFailure", "expected failure"), ("addUnexpectedSuccess", "unexpected success")):
    setattr(Result, name, noting(name, outcome))
out, pattern = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
loader = unittest.TestLoader()
if pattern:
    loader.testNamePatterns = [pattern if "*" in pattern else "*%s*" % pattern]
result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(loader.discover("tests"))
with open(out, "w", encoding="utf-8") as fh:
    json.dump({"ran": result.testsRun, "seen": result.seen}, fh)
sys.exit(5 if result.testsRun == 0 and not result.skipped else 0 if result.wasSuccessful() else 1)
'''


@dataclass
class Signal:
    name: str
    verdict: str
    native: dict = field(default_factory=dict)
    detail: str = ""


@dataclass
class GateResult:
    task: str
    base: str
    head: str
    signals: list
    verdict: str = "not measured"
    objections: list = field(default_factory=list)

    @property
    def warranted(self) -> bool:
        return self.verdict == "passed"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["warranted"] = self.warranted
        return d


def _python() -> str:
    return sys.executable or "python3"


def run_suite(repo_dir: Path, *, pattern: str | None = None, timeout: int = 600) -> dict:
    """Run the unittest suite in ``repo_dir``; return the exit code, each test's outcome by name
    (``tests``, the worst when two share a name) and every outcome the runner saw (``seen``)."""
    env = dict(os.environ, DATA_DIR=tempfile.mkdtemp(prefix="gate-data-"))
    env.pop("TRAFFIC_LOG", None)
    report = Path(env["DATA_DIR"] + "-outcomes.json")
    cmd = [_python(), "-c", _RUNNER, str(report), pattern or ""]
    try:  # integrations on stand-ins (FR-DS3); access enforced: IT's isolation runner, or refused (D-0016)
        with standins.running(repo_dir) as stand, \
                isolation.suite(cmd, repo_dir=Path(repo_dir), env=env | stand.env, report=report) as run:
            proc = subprocess.run(run.argv, cwd=repo_dir, capture_output=True, text=True, timeout=timeout,
                                  env=run.env, encoding="utf-8", errors="replace")
            seen, stood = _read_outcomes(run.report), stand.report()
    except subprocess.TimeoutExpired:
        return {"exit": None, "timeout": timeout, "tests": {}, "ran": 0, "seen": []}
    finally:
        shutil.rmtree(env["DATA_DIR"], ignore_errors=True)
        report.unlink(missing_ok=True)
    tests: dict[str, str] = {}
    for rec in seen["seen"]:
        name, outcome = rec["name"], rec["outcome"]
        if name and _WORST.get(outcome, 4) >= _WORST.get(tests.get(name, "ok"), 4):
            tests[name] = outcome
    return {"exit": proc.returncode, "tests": tests, "ran": seen["ran"], "seen": seen["seen"],
            "tail": proc.stderr.strip().splitlines()[-3:]} | stood


def _read_outcomes(path: Path) -> dict:
    """The runner's outcome file. A run that never wrote one (it crashed, or a test ended the
    process) saw nothing: no test ran as far as the kernel can tell."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    if not isinstance(doc, dict) or not isinstance(doc.get("seen"), list):
        return {"ran": 0, "seen": []}
    seen = [r | {"name": str(r.get("name") or ""), "outcome": str(r.get("outcome") or "ERROR")}
            for r in doc["seen"] if isinstance(r, dict) and isinstance(r.get("id"), str)]
    return {"ran": doc["ran"] if isinstance(doc.get("ran"), int) else 0, "seen": seen}


def _naming(run: dict, criterion_id: str) -> dict[str, str]:
    """The tests in a run whose names name the criterion: test id to outcome (the worst one)."""
    pat = token(criterion_id)
    out: dict[str, str] = {}
    for rec in run.get("seen", []):
        if rec.get("scope") is None and pat.search(rec["name"]) \
                and _WORST.get(rec["outcome"], 4) >= _WORST.get(out.get(rec["id"], "ok"), 4):
            out[rec["id"]] = rec["outcome"]
    return out


def token(criterion_id: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(criterion_id.replace("-", "_")) + r"(?![0-9])")


def visible_criteria(contract: dict, task_id: str) -> list:
    task = next(t for t in contract["tasks"] if t["id"] == task_id)
    kinds = {c["id"]: c.get("check", {}).get("kind", "test")
             for r in contract["requirements"] for c in r["acceptance"]}
    return [cid for cid in task["criteria"] if kinds.get(cid, "test") == "test"]


def tests_naming(names, criterion_id: str) -> list:
    pat = token(criterion_id)
    return sorted(n for n in names if pat.search(n))


def collect_test_names(repo_dir: Path) -> set:
    names = set()
    for path in Path(repo_dir, "tests").rglob("test*.py"):
        for m in re.finditer(r"^\s*def (test\w+)\s*\(", path.read_text(encoding="utf-8", errors="replace"), re.MULTILINE):
            names.add(m.group(1))
    return names


def signal_tests(repo_dir: Path, *, run: dict | None = None) -> Signal:
    """The whole suite, run by the kernel (``run``: a run already made at this revision)."""
    res = dict(run if run is not None else run_suite(repo_dir))
    res.pop("seen", None)  # every outcome stays in ``tests``; the runner's records stay out of the round
    if res["exit"] is None:
        return Signal("tests", "not measured", res, f"the suite did not finish in {res['timeout']}s")
    if res["ran"] == 0:
        return Signal("tests", "not measured", res, "no tests ran")
    failing = sorted(n for n, o in res["tests"].items() if o in FAILING)
    verdict = "passed" if res["exit"] == 0 else "failed"
    return Signal("tests", verdict, res, f"{res['ran']} ran" + (f"; failing: {', '.join(failing[:8])}" if failing else ""))


def signal_trace(repo_dir: Path, contract: dict, task_id: str, *, run: dict | None = None) -> Signal:
    """Every visible criterion is named by a test, and the kernel saw one of those tests run at
    this revision (``run``). A criterion whose tests were all skipped, marked as expected failures
    or never collected is not measured: nothing executed shows it."""
    run = run if run is not None else run_suite(repo_dir)
    crits = visible_criteria(contract, task_id)
    names = collect_test_names(repo_dir) | {r["name"] for r in run.get("seen", []) if r.get("scope") is None}
    missing = [cid for cid in crits if not tests_naming(names, cid)]
    unrun = _not_run(run, names, [cid for cid in crits if cid not in missing])
    native: dict[str, Any] = {"criteria": crits, "unnamed": missing} | ({"not_run": unrun} if unrun else {})
    if missing:
        return Signal("trace", "failed", native, "no test names " + ", ".join(missing))
    if unrun:
        return Signal("trace", "not measured", native, "no test naming it ran: " + "; ".join(
            f"{c}: " + ", ".join(f"{n} {o}" for n, o in sorted(v.items())[:3]) for c, v in unrun.items()))
    return Signal("trace", "passed", native, "every visible criterion is named by a test that ran")


def _not_run(run: dict, names: set, crits: list) -> dict[str, dict[str, str]]:
    """Per criterion that no naming test ran to its end in ``run``: its tests and what became of
    each (skipped, an expected failure, never ran)."""
    out = {}
    for cid in crits:
        outcomes = _naming(run, cid)
        if not any(o in RAN for o in outcomes.values()):
            out[cid] = {i.rsplit(".", 1)[-1]: o for i, o in outcomes.items()} or {
                n: "never ran" for n in tests_naming(names, cid)}
    return out


def signal_fail_first(repo_dir: Path, base: str, contract: dict, task_id: str, *, run: dict | None = None) -> Signal:
    """Copy the head's tests onto the base revision and run each criterion's tests there:
    they must fail. A test that passes, is skipped or never runs at base cannot show the change
    did anything; ``run`` is the suite's run at head, which says which tests to look for."""
    crits = visible_criteria(contract, task_id)
    if not crits:
        return Signal("fail_first", "not applicable", {}, "the task has no visible criteria")
    run = run if run is not None else run_suite(repo_dir)
    ids = {cid: sorted(_naming(run, cid)) for cid in crits}
    at_base = _passing_at(repo_dir, base, crits, ids)
    if at_base is None:
        return Signal("fail_first", "not measured", {"base": base}, "could not check out the base")
    passed_at_base, unseen = at_base
    for cid in crits:  # no test naming it ran at head: there is nothing to show failing at base
        if not ids[cid] and cid not in passed_at_base:
            unseen.setdefault(cid, ["no test naming it ran at head"])
    native: dict[str, Any] = {"base": base, "criteria": crits, "passed_at_base": passed_at_base}
    if unseen:
        native["unseen_at_base"] = unseen
    if passed_at_base:
        refused = _template_check(repo_dir, base, passed_at_base, ids, native, unseen)
        if refused is not None:
            return refused
    if unseen:
        return Signal("fail_first", "not measured", native, "tests that did not run before the change, so cannot "
                      "be shown to fail there: " + "; ".join(f"{c}: {', '.join(v[:3])}" for c, v in unseen.items()))
    if not passed_at_base:
        return Signal("fail_first", "passed", native, "every criterion's tests fail at base")
    native["already_met_at_base"] = sorted(passed_at_base)
    return Signal("fail_first", "passed", native,
                  "tests fail on the bare template; " + ", ".join(sorted(passed_at_base))
                  + " already held at base (built by earlier tasks)")


def _template_check(repo_dir: Path, base: str, passed_at_base: dict, ids: dict, native: dict,
                    unseen: dict) -> Signal | None:
    """A criterion can already hold at the task's base because earlier tasks built it. What must
    be shown is that its tests can fail at all: they must fail on the bare paved-road template
    (the product's first commit). If they pass even there, they test nothing: the refusal. A test
    that does not run on the template is added to ``unseen``."""
    root = subprocess.run([*isolation.git(repo_dir), "rev-list", "--max-parents=0", "HEAD"], cwd=repo_dir,
                          capture_output=True, text=True).stdout.split()      # no replace ref, no graft
    template = root[0] if root else None
    on_template = _passing_at(repo_dir, template, list(passed_at_base), ids) if template and template != base else None
    vacuous = on_template[0] if on_template is not None else None
    native.update(template=template, passed_on_template=vacuous)
    if on_template is not None:
        for cid, names in on_template[1].items():
            unseen[cid] = sorted(set(unseen.get(cid, [])) | set(names))
            native["unseen_at_base"] = unseen
    if vacuous is None or vacuous:
        bad = vacuous if vacuous else passed_at_base
        return Signal("fail_first", "failed", native,
                      "tests that pass without the behaviour (" + ("on the bare template" if vacuous else "at base")
                      + "): " + "; ".join(f"{c}: {', '.join(v[:3])}" for c, v in bad.items()))
    return None


def _passing_at(repo_dir: Path, revision: str, crits: list, ids: dict) -> tuple[dict, dict] | None:
    """Copy the head's tests onto ``revision`` and return, per criterion, its tests that do not
    fail there (passed, skipped, or an expected failure), and its head tests (``ids``) that never
    ran there and were not stopped by an error in their own module or class. None if the revision
    cannot be checked out."""
    tmp = Path(tempfile.mkdtemp(prefix="gate-base-"))
    try:
        subprocess.run([*isolation.git(repo_dir), "worktree", "add", "-q", "--detach", str(tmp / "b"), revision],
                       cwd=repo_dir, capture_output=True, text=True, check=True)
        base_dir = tmp / "b"
        isolation.copy_tests(Path(repo_dir), base_dir)      # from git: a link a cell left is never followed
        passing_by, unseen_by = {}, {}
        for cid in crits:
            res = run_suite(base_dir, pattern=cid.replace("-", "_"))
            outcomes = _naming(res, cid)
            scopes = [r["scope"] for r in res.get("seen", []) if r.get("scope")]
            passing = sorted({i.rsplit(".", 1)[-1] for i, o in outcomes.items() if o not in FAILING})
            unseen = sorted({i.rsplit(".", 1)[-1] for i in ids.get(cid, []) if i not in outcomes
                             and not any(i == s or i.startswith(s + ".") for s in scopes)})  # its module or class
            if passing:
                passing_by[cid] = passing
            if unseen:
                unseen_by[cid] = unseen
        return passing_by, unseen_by
    except subprocess.CalledProcessError:
        return None
    finally:
        subprocess.run([*isolation.git(repo_dir), "worktree", "remove", "--force", str(tmp / "b")],
                       cwd=repo_dir, capture_output=True, text=True)
        shutil.rmtree(tmp, ignore_errors=True)


def signal_protected(repo_dir: Path, base: str, head: str) -> Signal | None:
    """A violation when the change touches a protected path; None when it does not."""
    touched = protected_paths(repo_dir, base, head)
    if not touched:
        return None
    return Signal("protected", "violation", {"paths": touched},
                  "the change touches what a cell may not: " + ", ".join(touched[:10]))


def verifier_prompt(contract: dict, task_id: str, base: str) -> str:
    """Open, P8 in docs/code-quality.md (here and in change_verifier_prompt): a `git diff` the read-only
    verifier cannot run. The instructions come first, word for word in every review, the task last (FR-CTX1)."""
    task = next(t for t in contract["tasks"] if t["id"] == task_id)
    crit = {c["id"]: c for r in contract["requirements"] for c in r["acceptance"]}
    reqs = sorted({cid.rsplit("-AC-", 1)[0] for cid in task["criteria"]})
    statements = {r["id"]: r["statement"] for r in contract["requirements"]}
    listing = "\n".join(f"- {cid}: given {crit[cid]['given']}; when {crit[cid]['when']}; then {crit[cid]['then']}"
                        for cid in visible_criteria(contract, task_id))
    return f"""You review a change against the task named at the end. You may read files and run nothing else.

Try to break it. Look for:
- a criterion that is not really met;
- a test that cannot fail, or that checks something other than its name says;
- a crash on ordinary input;
- data that is lost or leaks between requests.

Do not report style. Answer with this JSON in a ```json block:
{{"findings": [{{"criterion": "R-1-AC-1 or null", "in_scope": true, "severity": "high|medium|low",
   "finding": "what breaks", "repro": "how to see it"}}]}}
An empty list means you found nothing.
The change is for task {task_id}. Compare it with the base revision {base} (`git diff {base} -- app tests`).

Requirements:
{chr(10).join(f"- {r}: {statements[r]}" for r in reqs)}

Acceptance criteria the change must meet:
{listing}
"""


def signal_verifier(repo_dir: Path, contract: dict, task_id: str, base: str, *, runner=None) -> Signal:
    """A read-only review by the verifier role. ``runner`` replaces the gnomon call in tests."""
    return _verifier_signal(repo_dir, verifier_prompt(contract, task_id, base), runner=runner)


def read_findings(text: str) -> tuple[list | None, str]:
    """The verifier's findings from its answer, read strictly: one JSON object whose `findings` is
    a list of objects, each with a severity of high, medium or low. Anything else (prose, findings
    as an object or under another key, an item that is not an object, an unknown severity) is
    (None, why): the verifier gave no usable verdict, and its signal is not measured."""
    try:
        doc = extract_json(text)
    except ModelError as exc:
        return None, str(exc)
    findings = doc.get("findings") if isinstance(doc, dict) else None
    if not isinstance(findings, list):
        return None, "the answer holds no findings list"
    out = []
    for f in findings:
        if not isinstance(f, dict):
            return None, f"a finding is not an object: {str(f)[:80]}"
        severity = str(f.get("severity", "")).strip().lower()
        if severity not in SEVERITIES:
            return None, f"a finding has no severity of {', '.join(SEVERITIES)}: {f.get('severity')!r}"
        out.append(f | {"severity": severity})
    return out, ""


def _verifier_signal(repo_dir: Path, prompt: str, *, runner=None) -> Signal:
    try:
        if runner is not None:
            text = runner(prompt)
            record = {"output": text}
        else:
            record = run_gnomon_task(repo_dir, prompt, role="verifier", timeout=1200)
            text = record.get("output") or ""
    except ModelError as exc:
        return Signal("verifier", "not measured", {"error": str(exc)}, "the verifier gave no usable answer")
    findings, why = read_findings(text if isinstance(text, str) else "")
    if findings is None:
        return Signal("verifier", "not measured", {"error": why, "model": record.get("model"),
                                                   "bucket": record.get("bucket")},
                      f"the verifier gave no usable answer: {why}")
    blocking = [f for f in findings if f.get("in_scope", True) and f["severity"] == "high"]
    native = {"findings": findings, "model": record.get("model"), "bucket": record.get("bucket")}
    if blocking:
        return Signal("verifier", "failed", native, f"{len(blocking)} high in-scope finding(s)")
    return Signal("verifier", "passed", native, f"{len(findings)} finding(s), none high and in scope")


def judge(repo_dir: Path, contract: dict, task_id: str, base: str, head: str, *,
          verifier: bool = True, verifier_runner=None) -> GateResult:
    guard = signal_protected(repo_dir, base, head)
    run = run_suite(repo_dir)
    signals = [signal_tests(repo_dir, run=run), signal_trace(repo_dir, contract, task_id, run=run),
               signal_fail_first(repo_dir, base, contract, task_id, run=run), *standins.signal(contract, run, task_id)]
    if guard is not None:  # the verifier would run under the surface the change rewrote: it does not run
        signals.append(guard)
    elif verifier:
        signals.append(signal_verifier(repo_dir, contract, task_id, base, runner=verifier_runner))
    return _conclude(GateResult(task=task_id, base=base, head=head, signals=signals))


def _conclude(result: GateResult) -> GateResult:
    """The combined verdict (FR-G3) and every objection, from the signals. Evidence that could not
    be read is an objection too, so the next round and the person deciding see what was missing."""
    result.verdict = combine_verdicts([s.verdict for s in result.signals])
    for s in result.signals:
        if s.verdict in ("failed", "violation"):
            result.objections.append(f"{s.name}: {s.detail}")
        elif s.verdict == "not measured":
            result.objections.append(f"{s.name} (not measured): {s.detail}")
        if s.name == "verifier":
            for f in s.native.get("findings", []):
                if f.get("in_scope", True) and f.get("severity") == "high":
                    result.objections.append(f"verifier ({f.get('criterion') or 'general'}): {f.get('finding')} "
                                             f"(repro: {f.get('repro', '-')})")
    return result


# -- a person as a cell: the same gate for a workspace's commits ------------------------------------

def change_verifier_prompt(contract: dict, base: str, author: str) -> str:
    """The verifier's task for a change that names no contract task: every live criterion is in
    view, and the reviewer looks for what the change breaks."""
    lines = []
    for r in contract["requirements"]:
        if r.get("provenance") == "withdrawn":
            continue
        lines.append(f"- {r['id']}: {r['statement']}")
        lines += [f"    - {c['id']}: given {c.get('given', '-')}; when {c.get('when', '-')}; then {c['then']}"
                  for c in r["acceptance"] if (c.get("check") or {}).get("kind", "test") == "test"]
    return f"""You review a change {author} made in this repository. Compare it with the base revision
{base} (`git diff {base}`). You may read files and run nothing else.

The product's requirements and the criteria its tests check:
{chr(10).join(lines)}

Try to break it. Look for:
- a criterion the change stops meeting;
- a test that cannot fail, or that checks something other than its name says;
- a crash on ordinary input;
- data that is lost or leaks between requests.

Do not report style. Answer with this JSON in a ```json block:
{{"findings": [{{"criterion": "R-1-AC-1 or null", "in_scope": true, "severity": "high|medium|low",
   "finding": "what breaks", "repro": "how to see it"}}]}}
An empty list means you found nothing.
"""


def judge_change(repo_dir: Path, contract: dict, base: str, head: str, *, label: str, author: str,
                 task_id: str | None = None, verifier_runner=None, own_suites: list | None = None) -> GateResult:
    """The gate for a person's workspace commits: with a contract task, the very `judge` a builder cell meets;
    without, the suite (or an adopted project's ``own_suites``: gate_own) and the verifier, no criterion claimed."""
    if task_id is not None:
        return judge(repo_dir, contract, task_id, base, head, verifier_runner=verifier_runner)
    prompt, run = change_verifier_prompt(contract, base, author), run_suite(repo_dir)
    signals = [*standins.signal(contract, run), tests_or_own(repo_dir, signal_tests(repo_dir, run=run), own_suites),
               Signal("trace", "not applicable", {"criteria": []}, "the change names no criterion"),
               Signal("fail_first", "not applicable", {}, "the change names no criterion"),
               signal_protected(repo_dir, base, head) or _verifier_signal(repo_dir, prompt, runner=verifier_runner)]
    return _conclude(GateResult(task=label, base=base, head=head, signals=signals))
