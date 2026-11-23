"""The gate: whether a cell's change is warranted. The kernel runs the checks itself, apart from
the builder (FR-G6).

The signals for one task:
- **tests:** the product's whole suite, run by the kernel. Exit 0 is passed.
- **trace:** every visible criterion of the task is named by a test.
- **fail-first:** each criterion's tests fail at the base revision. A test that passes
  before the change proves nothing.
- **verifier:** a read-only role on another model family tries to break the change. An
  in-scope finding is an objection.

Each signal keeps its native value beside its named verdict. The combined verdict uses
FR-G3's precedence. *Warranted* means the combined verdict is passed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kernel.model import ModelError, extract_json, run_gnomon_task
from kernel.verdicts import combine_verdicts

TEST_LINE = re.compile(r"^(test\w*) \(([\w.]+)\)\s*\.\.\.\s*(ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)$")


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
    """Run the unittest suite in ``repo_dir``; return exit code and each test's outcome."""
    env = dict(os.environ)
    env["DATA_DIR"] = tempfile.mkdtemp(prefix="gate-data-")
    env.pop("TRAFFIC_LOG", None)
    cmd = [_python(), "-m", "unittest", "discover", "-s", "tests", "-v"]
    if pattern:
        cmd += ["-k", pattern]
    try:
        proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=timeout,
                              env=env, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"exit": None, "timeout": timeout, "tests": {}, "ran": 0}
    finally:
        shutil.rmtree(env["DATA_DIR"], ignore_errors=True)
    tests = {}
    for line in proc.stderr.splitlines():
        m = TEST_LINE.match(line.strip())
        if m:
            tests[m.group(1)] = m.group(3).split()[0]
    ran = re.search(r"^Ran (\d+) tests?", proc.stderr, re.MULTILINE)
    return {"exit": proc.returncode, "tests": tests, "ran": int(ran.group(1)) if ran else 0,
            "tail": proc.stderr.strip().splitlines()[-3:]}


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


def signal_tests(repo_dir: Path) -> Signal:
    res = run_suite(repo_dir)
    if res["exit"] is None:
        return Signal("tests", "not measured", res, f"the suite did not finish in {res['timeout']}s")
    if res["ran"] == 0:
        return Signal("tests", "not measured", res, "no tests ran")
    failing = sorted(n for n, o in res["tests"].items() if o in ("FAIL", "ERROR"))
    verdict = "passed" if res["exit"] == 0 else "failed"
    return Signal("tests", verdict, res, f"{res['ran']} ran" + (f"; failing: {', '.join(failing[:8])}" if failing else ""))


def signal_trace(repo_dir: Path, contract: dict, task_id: str) -> Signal:
    names = collect_test_names(repo_dir)
    missing = [cid for cid in visible_criteria(contract, task_id) if not tests_naming(names, cid)]
    native = {"criteria": visible_criteria(contract, task_id), "unnamed": missing}
    if missing:
        return Signal("trace", "failed", native, "no test names " + ", ".join(missing))
    return Signal("trace", "passed", native, "every visible criterion is named by a test")


def signal_fail_first(repo_dir: Path, base: str, contract: dict, task_id: str) -> Signal:
    """Copy the head's tests onto the base revision and run each criterion's tests there:
    they must fail. A test that already passes at base cannot show the change did anything."""
    crits = visible_criteria(contract, task_id)
    if not crits:
        return Signal("fail_first", "not applicable", {}, "the task has no visible criteria")
    passed_at_base = _passing_at(repo_dir, base, crits)
    if passed_at_base is None:
        return Signal("fail_first", "not measured", {"base": base}, "could not check out the base")
    native: dict[str, Any] = {"base": base, "criteria": crits, "passed_at_base": passed_at_base}
    if not passed_at_base:
        return Signal("fail_first", "passed", native, "every criterion's tests fail at base")
    # A criterion can already hold at the task's base because earlier tasks built it. What must
    # be shown is that its tests can fail at all: they must fail on the bare paved-road template
    # (the product's first commit). If they pass even there, they test nothing.
    root = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=repo_dir, capture_output=True,
                          text=True).stdout.split()
    template = root[0] if root else None
    vacuous = _passing_at(repo_dir, template, list(passed_at_base)) if template and template != base else None
    native.update(template=template, passed_on_template=vacuous)
    if vacuous is None or vacuous:
        bad = vacuous if vacuous else passed_at_base
        return Signal("fail_first", "failed", native,
                      "tests that pass without the behaviour (" + ("on the bare template" if vacuous else "at base")
                      + "): " + "; ".join(f"{c}: {', '.join(v[:3])}" for c, v in bad.items()))
    native["already_met_at_base"] = sorted(passed_at_base)
    return Signal("fail_first", "passed", native,
                  "tests fail on the bare template; " + ", ".join(sorted(passed_at_base))
                  + " already held at base (built by earlier tasks)")


def _passing_at(repo_dir: Path, revision: str, crits: list) -> dict | None:
    """Copy the head's tests onto ``revision`` and return, per criterion, its tests that pass
    there. None if the revision cannot be checked out."""
    tmp = Path(tempfile.mkdtemp(prefix="gate-base-"))
    try:
        subprocess.run(["git", "worktree", "add", "-q", "--detach", str(tmp / "b"), revision], cwd=repo_dir,
                       capture_output=True, text=True, check=True)
        base_dir = tmp / "b"
        shutil.rmtree(base_dir / "tests", ignore_errors=True)
        shutil.copytree(Path(repo_dir) / "tests", base_dir / "tests")
        passing_by = {}
        for cid in crits:
            res = run_suite(base_dir, pattern=cid.replace("-", "_"))
            named = {n: o for n, o in res["tests"].items() if token(cid).search(n)}
            passing = sorted(n for n, o in named.items() if o == "ok")
            if passing:
                passing_by[cid] = passing
        return passing_by
    except subprocess.CalledProcessError:
        return None
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tmp / "b")], cwd=repo_dir,
                       capture_output=True, text=True)
        shutil.rmtree(tmp, ignore_errors=True)


def verifier_prompt(contract: dict, task_id: str, base: str) -> str:
    task = next(t for t in contract["tasks"] if t["id"] == task_id)
    crit = {c["id"]: c for r in contract["requirements"] for c in r["acceptance"]}
    reqs = sorted({cid.rsplit("-AC-", 1)[0] for cid in task["criteria"]})
    statements = {r["id"]: r["statement"] for r in contract["requirements"]}
    listing = "\n".join(f"- {cid}: given {crit[cid]['given']}; when {crit[cid]['when']}; then {crit[cid]['then']}"
                        for cid in visible_criteria(contract, task_id))
    return f"""You review a change in this repository for task {task_id}. Compare it with the base
revision {base} (`git diff {base} -- app tests`). You may read files and run nothing else.

Requirements:
{chr(10).join(f"- {r}: {statements[r]}" for r in reqs)}

Acceptance criteria the change must meet:
{listing}

Try to break it. Look for:
- a criterion that is not really met;
- a test that cannot fail, or that checks something other than its name says;
- a crash on ordinary input;
- data that is lost or leaks between requests.

Do not report style. Answer with this JSON in a ```json block:
{{"findings": [{{"criterion": "R-1-AC-1 or null", "in_scope": true, "severity": "high|medium|low",
   "finding": "what breaks", "repro": "how to see it"}}]}}
An empty list means you found nothing.
"""


def signal_verifier(repo_dir: Path, contract: dict, task_id: str, base: str, *, runner=None) -> Signal:
    """A read-only review by the verifier role. ``runner`` replaces the gnomon call in tests."""
    return _verifier_signal(repo_dir, verifier_prompt(contract, task_id, base), runner=runner)


def _verifier_signal(repo_dir: Path, prompt: str, *, runner=None) -> Signal:
    try:
        if runner is not None:
            text = runner(prompt)
            record = {"output": text}
        else:
            record = run_gnomon_task(repo_dir, prompt, role="verifier", timeout=1200)
            text = record.get("output") or ""
        findings = extract_json(text).get("findings") or []
    except (ModelError, AttributeError) as exc:
        return Signal("verifier", "not measured", {"error": str(exc)}, "the verifier gave no usable answer")
    findings = [f for f in findings if isinstance(f, dict)]
    blocking = [f for f in findings if f.get("in_scope", True) and f.get("severity") == "high"]
    native = {"findings": findings, "model": record.get("model"), "bucket": record.get("bucket")}
    if blocking:
        return Signal("verifier", "failed", native, f"{len(blocking)} high in-scope finding(s)")
    return Signal("verifier", "passed", native, f"{len(findings)} finding(s), none high and in scope")


def judge(repo_dir: Path, contract: dict, task_id: str, base: str, head: str, *,
          verifier: bool = True, verifier_runner=None) -> GateResult:
    signals = [signal_tests(repo_dir), signal_trace(repo_dir, contract, task_id),
               signal_fail_first(repo_dir, base, contract, task_id)]
    if verifier:
        signals.append(signal_verifier(repo_dir, contract, task_id, base, runner=verifier_runner))
    return _conclude(GateResult(task=task_id, base=base, head=head, signals=signals))


def _conclude(result: GateResult) -> GateResult:
    """The combined verdict (FR-G3) and every objection, from the signals."""
    result.verdict = combine_verdicts([s.verdict for s in result.signals])
    for s in result.signals:
        if s.verdict in ("failed", "violation"):
            result.objections.append(f"{s.name}: {s.detail}")
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
                 task_id: str | None = None, verifier_runner=None) -> GateResult:
    """The gate for commits a person made in a workspace. With a contract task named, it is the
    very same `judge` a builder cell meets. Without one, the suite and the independent verifier
    still run, and trace and fail-first are not applicable: no criterion is claimed."""
    if task_id is not None:
        return judge(repo_dir, contract, task_id, base, head, verifier_runner=verifier_runner)
    signals = [signal_tests(repo_dir),
               Signal("trace", "not applicable", {"criteria": []}, "the change names no criterion"),
               Signal("fail_first", "not applicable", {}, "the change names no criterion"),
               _verifier_signal(repo_dir, change_verifier_prompt(contract, base, author), runner=verifier_runner)]
    return _conclude(GateResult(task=label, base=base, head=head, signals=signals))
