"""The assessment's rules for how a system is built and kept (kernel/assess.py): CI/CD governance and
maintenance. Each rule reads the files of one revision (kernel/assess_repo.py) and names its evidence: a
file and a line, or a measured fact. What the files cannot show (branch protection, the required checks
a hosting service enforces, the age of each package in a registry) is "not measured", with the reason.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import tomllib
from typing import Any

from kernel.assess_repo import Repo, at, base, fact, listed, result
from kernel.redteam.actionsrules import _USES, _unpinned_action

PIPELINES = {".gitlab-ci.yml": "GitLab CI", "azure-pipelines.yml": "Azure Pipelines", "Jenkinsfile": "Jenkins",
             ".circleci/config.yml": "CircleCI", "bitbucket-pipelines.yml": "Bitbucket Pipelines",
             ".travis.yml": "Travis CI", ".drone.yml": "Drone", ".buildkite/pipeline.yml": "Buildkite"}
TEST_STEP = re.compile(r"\b(pytest|unittest|tox|nox|(npm|yarn|pnpm)( run)? test|go test|cargo test"
                       r"|mvn\b.*\b(test|verify)|gradlew?\b.*\b(test|check|build)|make test|dotnet test|rspec|phpunit"
                       r"|jest|vitest)\b")
BEFORE_MERGE = {"GitHub Actions": re.compile(r"\bpull_request(_target)?\b|\bmerge_group\b"),
                "GitLab CI": re.compile(r"\bmerge_requests?\b|merge_request_event"),
                "Azure Pipelines": re.compile(r"^\s*pr\s*:"),
                "Bitbucket Pipelines": re.compile(r"^\s*pull-requests\s*:")}
RELEASE_STEP = re.compile(r"^\s*(release\s*:|tags\s*:|-\s*['\"]?v\*)|CI_COMMIT_TAG|\bgoreleaser\b|semantic-release")
RELEASE_FILES = ("CHANGELOG.md", "CHANGELOG", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md", "RELEASING.md",
                 ".releaserc", ".releaserc.json", ".releaserc.yml", "release-please-config.json", ".goreleaser.yml",
                 ".goreleaser.yaml", ".release-it.json")
COVERAGE_CONFIG = re.compile(r"\[(tool\.)?coverage[:.\]]|--cov\b|coverage run|collectCoverage|coverageThreshold|"
                             r"\bjacoco\b|-coverprofile|\bnyc\b|\bc8\b|codecov")
LOCKS = {"poetry.lock", "pipfile.lock", "uv.lock", "pdm.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
         "npm-shrinkwrap.json", "go.sum", "cargo.lock", "gemfile.lock", "composer.lock", "packages.lock.json",
         "gradle.lockfile"}
NEEDS_LOCK = {"package.json": ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json"),
              "go.mod": ("go.sum",), "cargo.toml": ("cargo.lock",), "gemfile": ("gemfile.lock",),
              "composer.json": ("composer.lock",), "pipfile": ("pipfile.lock",),
              "pyproject.toml": ("poetry.lock", "uv.lock", "pdm.lock")}
MAX_LOOSE = 8
UPDATERS = (".github/dependabot.yml", ".github/dependabot.yaml", "renovate.json", "renovate.json5", ".renovaterc",
            ".renovaterc.json", ".github/renovate.json", ".github/renovate.json5", ".gitlab/renovate.json")
OWNERS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS", ".gitlab/CODEOWNERS", "MAINTAINERS",
          "MAINTAINERS.md", "OWNERS")
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(?P<spec>[^#;]*)")
STALE_DAYS = 365


def workflows(repo: Repo) -> list[str]:
    return repo.named(lambda f: f.startswith(".github/workflows/") and f.count("/") == 2
                      and f.endswith((".yml", ".yaml")))


def pipelines(repo: Repo) -> list[tuple[str, str]]:
    found = [(f, "GitHub Actions") for f in workflows(repo)]
    return found + [(hit, system) for name, system in PIPELINES.items() if (hit := repo.first(name))]


def _cicd(key: str, title: str, verdict: str, **kw: Any) -> dict[str, Any]:
    return result(f"cicd.{key}", "cicd", title, verdict, **kw)


def pipeline(repo: Repo) -> dict[str, Any]:
    found = pipelines(repo)
    title = "A CI pipeline is defined"
    if found:
        return _cicd("pipeline", title, "passed", summary=f"{len(found)} pipeline definition(s)",
                     evidence=[{"file": f, "fact": system} for f, system in found])
    looked = "GitHub Actions workflows, " + ", ".join(PIPELINES)
    return _cicd("pipeline", title, "failed", severity="high", summary="no pipeline definition found",
                 evidence=[fact(f"none of {looked} among the {len(repo.files)} files of {repo.revision[:12]}")],
                 suggestion="Add a pipeline that runs the test suite on every push and pull request, so a change "
                            "is checked before it is merged.")


def tests_in_pipeline(repo: Repo) -> dict[str, Any]:
    title = "The pipeline runs the tests"
    found = pipelines(repo)
    if not found:
        return _cicd("tests_in_pipeline", title, "not applicable", reason="no pipeline is defined (cicd.pipeline)")
    steps = repo.find(TEST_STEP, [f for f, _ in found])
    if steps:
        return _cicd("tests_in_pipeline", title, "passed", summary=f"{len(steps)} test step(s) found", evidence=steps)
    return _cicd("tests_in_pipeline", title, "failed", severity="medium", summary="no step runs a test runner",
                 evidence=[fact(f"no test runner named in {listed([f for f, _ in found])}")],
                 suggestion="Run the test suite in the pipeline, so a failing test stops a change.")


def runs_before_merge(repo: Repo) -> dict[str, Any]:
    title = "Checks run on pull requests, before merge"
    found = pipelines(repo)
    if not found:
        return _cicd("runs_before_merge", title, "not applicable", reason="no pipeline is defined (cicd.pipeline)")
    readable = [(f, s) for f, s in found if s in BEFORE_MERGE]
    hits = [e for f, s in readable for e in repo.find(BEFORE_MERGE[s], [f], limit=2)]
    if hits:
        return _cicd("runs_before_merge", title, "passed", summary="a pull request trigger is declared", evidence=hits)
    if not readable:
        return _cicd("runs_before_merge", title, "not measured",
                     reason=f"the kernel reads the triggers of {', '.join(BEFORE_MERGE)} only; found "
                            f"{listed(sorted({s for _, s in found}))}")
    return _cicd("runs_before_merge", title, "failed", severity="medium", summary="no pull request trigger",
                 evidence=[fact(f"no pull request or merge request trigger in {listed([f for f, _ in readable])}")],
                 suggestion="Run the pipeline on pull requests (or merge requests), so checks pass before a merge.")


def _uses(repo: Repo) -> tuple[int, list[dict[str, Any]]]:
    total, loose = 0, []
    for rel in workflows(repo) + repo.named(lambda f: base(f) in ("action.yml", "action.yaml")):
        for n, line in enumerate(repo.text(rel).splitlines(), 1):
            for m in _USES.finditer(line):
                ref = m.group(1)
                if ref.startswith("./"):
                    continue
                total += 1
                if _unpinned_action(ref):
                    loose.append(at(rel, n, line))
    return total, loose


def pinned_actions(repo: Repo) -> dict[str, Any]:
    title = "Every action is pinned to a commit"
    total, loose = _uses(repo)
    if not total:
        return _cicd("pinned_actions", title, "not applicable", reason="no GitHub Actions workflow uses an action")
    if not loose:
        return _cicd("pinned_actions", title, "passed", summary=f"all {total} action reference(s) pinned to a full SHA",
                     evidence=[fact(f"{total} uses: references, each @<40-hex commit>")])
    return _cicd("pinned_actions", title, "failed", severity="medium",
                 summary=f"{len(loose)} of {total} action reference(s) by a mutable tag or branch (RT-GHA-UNPINNED, "
                         "CWE-829)", evidence=loose,
                 suggestion="Pin each action to the full commit SHA of the release you trust, with the tag in a "
                            "comment, and let an update bot move the pins.")


def token_permissions(repo: Repo) -> dict[str, Any]:
    title = "Workflows declare their token's permissions"
    flows = workflows(repo)
    if not flows:
        return _cicd("token_permissions", title, "not applicable", reason="no GitHub Actions workflow")
    declared = [(f, e) for f in flows for e in repo.find(re.compile(r"^permissions\s*:"), [f], limit=1)]
    missing = sorted(set(flows) - {f for f, _ in declared})
    if not missing:
        return _cicd("token_permissions", title, "passed", summary="each workflow declares permissions",
                     evidence=[e for _, e in declared])
    return _cicd("token_permissions", title, "failed", severity="low",
                 summary=f"{len(missing)} workflow(s) run with the repository's default token permissions",
                 evidence=[fact(f"no top-level permissions: in {listed(missing)}")],
                 suggestion="Declare `permissions:` at the top of each workflow, read-only unless a job must write.")


def required_checks(repo: Repo) -> dict[str, Any]:
    settings = repo.first(".github/settings.yml")
    declared = repo.find(re.compile(r"required_status_checks|required_pull_request_reviews"), [settings], limit=3) \
        if settings else []
    why = ("required checks are set in the hosting service's branch protection, not in the repository's files, "
           "and the kernel reads only the files")
    if declared:
        why += "; the settings file below declares some, but whether the service applies them is not visible"
    return _cicd("required_checks", "Checks are required before a merge", "not measured", reason=why,
                 evidence=declared)


def protected_main(repo: Repo) -> dict[str, Any]:
    owners = repo.first(*OWNERS[:4])
    return _cicd("protected_main", "The main branch is protected", "not measured",
                 reason="branch protection lives in the hosting service's settings, not in the files the kernel "
                        "reads: ask whoever administers the repository, and record the answer",
                 evidence=[{"file": owners, "fact": "names code owners; they bind only when protection requires "
                                                    "their review"}] if owners else [])


def release(repo: Repo) -> dict[str, Any]:
    title = "A release process is written down"
    files = [f for f in (repo.first(n) for n in RELEASE_FILES) if f]
    steps = repo.find(RELEASE_STEP, [f for f, _ in pipelines(repo)], limit=3)
    evidence = [{"file": f, "fact": "present"} for f in files] + steps
    if evidence:
        return _cicd("release", title, "passed", summary="a release step or release notes are kept", evidence=evidence)
    return _cicd("release", title, "failed", severity="low", summary="no release workflow and no changelog",
                 evidence=[fact(f"no tag or release trigger in a pipeline, and none of {listed(list(RELEASE_FILES))}; "
                                "tags are not read (the mirror fetches no tags)")],
                 suggestion="Write down how a release is made: a release workflow on tags, and a changelog.")


CICD = (pipeline, tests_in_pipeline, runs_before_merge, pinned_actions, token_permissions, required_checks,
        protected_main, release)


# -- maintenance -------------------------------------------------------------------------------------

def _care(key: str, title: str, verdict: str, **kw: Any) -> dict[str, Any]:
    return result(f"maintenance.{key}", "maintenance", title, verdict, **kw)


def tests(repo: Repo) -> dict[str, Any]:
    found = (repo.records.get("inventory") or {}).get("tests") or []
    title = "A test suite is found by rule"
    if found:
        return _care("tests", title, "passed", summary=", ".join(t["runner"] for t in found),
                     evidence=[fact(f"{t['runner']}: {t['basis']}") for t in found])
    return _care("tests", title, "failed", severity="high", summary="no test command found by rule",
                 evidence=[fact("no pytest or unittest suite, npm test script, go test, cargo test, Maven or Gradle "
                                "build among the files")],
                 suggestion="Add a test suite that pins today's behaviour before anything is changed.")


def _baseline_facts(base_line: dict[str, Any], revision: str) -> list[dict[str, Any]]:
    runs = [f"{r.get('runner')}: {r.get('verdict')}" + (f" {r['counts']}" if r.get("counts") else "")
            for r in base_line.get("runs") or []]
    out = [fact(f"at adoption, revision {str(base_line.get('revision'))[:12]}: " + ("; ".join(runs) or "no run"))]
    if base_line.get("revision") and base_line["revision"] != revision:
        out.append(fact(f"measured at the adoption revision, not at the assessed revision {revision[:12]}"))
    return out


def baseline(repo: Repo) -> dict[str, Any]:
    title = "The existing suite passes (the characterisation baseline)"
    base_line = repo.records.get("baseline")
    if not base_line:
        return _care("baseline", title, "not measured", reason="no characterisation baseline: the project was not "
                                                               "adopted, so its suite was never run by the kernel")
    verdict, evidence = base_line.get("verdict"), _baseline_facts(base_line, repo.revision)
    ran_at = str(base_line.get("revision") or "")
    if ran_at != repo.revision:   # a suite run at another revision says nothing measured about this one
        return _care("baseline", title, "not measured", evidence=evidence,
                     reason=f"the suite was run at adoption, at revision {ran_at[:12] or '(not recorded)'}, not at "
                            f"the assessed revision {repo.revision[:12]} (its result there: "
                            f"{verdict or 'not recorded'}); assess the adoption revision (--ref) to read that run")
    if verdict == "passed":
        return _care("baseline", title, "passed", summary="existing behaviour, not a spec", evidence=evidence)
    if verdict == "failed":
        return _care("baseline", title, "failed", severity="high", summary=str(base_line.get("reason") or "failing"),
                     evidence=evidence, suggestion="Make the existing suite pass, or record which failures are "
                                                   "known, before the system is changed.")
    return _care("baseline", title, "not measured", reason=str(base_line.get("reason") or "not measured"),
                 evidence=evidence)


def _coverage_report(repo: Repo) -> dict[str, Any] | None:
    rel = repo.first("coverage.xml")
    m = re.search(r'<coverage[^>]*\bline-rate="([0-9.]+)"', repo.text(rel)) if rel else None
    if not (rel and m):
        return None
    return {"file": rel, "fact": f"records a line rate of {float(m.group(1)):.0%} as committed; the kernel did not "
                                 "measure it"}


def coverage(repo: Repo) -> dict[str, Any]:
    title = "Test coverage is configured"
    names = [repo.first(n) for n in (".coveragerc", "codecov.yml", ".codecov.yml", ".nycrc", ".nycrc.json")]
    configs = repo.find(COVERAGE_CONFIG, [f for f in ("pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini",
                                                      "package.json", "pom.xml", "build.gradle", "Makefile")
                                         if f in repo.files] + [f for f, _ in pipelines(repo)], limit=4)
    evidence = [{"file": f, "fact": "present"} for f in names if f] + configs
    report = _coverage_report(repo)
    if report:
        evidence.append(report)
    if evidence:
        return _care("coverage", title, "passed", evidence=evidence,
                     summary="configured; its value is not measured by the kernel, which does not instrument the suite")
    return _care("coverage", title, "failed", severity="low", summary="no coverage configuration found by rule",
                 evidence=[fact("no .coveragerc, [tool.coverage], --cov, jest coverage, JaCoCo, nyc or codecov "
                                "configuration")],
                 suggestion="Measure coverage in the pipeline, so untested code is visible before it changes.")


def _requirement_lines(repo: Repo, rel: str) -> list[dict[str, Any]]:
    loose = []
    for n, line in enumerate(repo.text(rel).splitlines(), 1):
        s = line.strip()
        if not s or s.startswith(("#", "-", "git+", "http")):
            continue
        m = _REQUIREMENT.match(s)
        if m and "==" not in (m.group("spec") or ""):
            loose.append(at(rel, n, line))
    return loose


def _pyproject_deps(repo: Repo, rel: str) -> list[str]:
    """The dependencies a pyproject.toml declares: [project] dependencies, and Poetry's as `name spec`
    (an exact Poetry version, `1.2.3`, reads as `name==1.2.3`)."""
    try:
        data = tomllib.loads(repo.text(rel))
    except (tomllib.TOMLDecodeError, RecursionError):
        return []
    project: dict[str, Any] = data["project"] if isinstance(data.get("project"), dict) else {}
    deps = [d for d in project.get("dependencies") or [] if isinstance(d, str)]
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies")
    for name, spec in (poetry.items() if isinstance(poetry, dict) else []):
        if name.lower() != "python":
            exact = isinstance(spec, str) and re.fullmatch(r"\d[\w.]*", spec)
            deps.append(f"{name}=={spec}" if exact else f"{name} {spec}")
    return deps


def _declares(repo: Repo, rel: str) -> bool:
    """Whether a manifest declares any dependency: a package.json or a pyproject.toml may declare none."""
    name = base(rel)
    if name == "pyproject.toml":
        return bool(_pyproject_deps(repo, rel))
    if name != "package.json":
        return True
    try:
        data = json.loads(repo.text(rel) or "{}")
    except (ValueError, RecursionError):
        return True
    return not isinstance(data, dict) or any(data.get(k) for k in ("dependencies", "devDependencies",
                                                                   "optionalDependencies"))


def _unlocked(repo: Repo, rel: str, wanted: tuple[str, ...]) -> list[dict[str, Any]]:
    """The evidence of a manifest with no lock file beside it: each unpinned pyproject dependency at its
    line, or the manifest itself."""
    if base(rel) == "pyproject.toml":
        loose = [d for d in _pyproject_deps(repo, rel) if "==" not in d]
        return [(repo.find(re.compile(re.escape(d.split()[0])), [rel], 1) or [{"file": rel, "fact": d}])[0]
                for d in loose[:MAX_LOOSE]]
    return [{"file": rel, "fact": f"no {' or '.join(wanted)} beside it: versions resolve at install time"}]


def _manifests(repo: Repo) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """(dependency files, unpinned evidence, lock files) of the repository."""
    names = {f: base(f) for f in repo.files if not f.startswith(("vendor/", "node_modules/", "third_party/"))}
    lowered = {f.lower() for f in names}
    locks = [f for f, b in names.items() if b in LOCKS]
    requirements = [f for f, b in names.items() if b.startswith("requirements") and b.endswith(".txt")]
    loose = [e for f in requirements for e in _requirement_lines(repo, f)]
    declared = [f for f, b in names.items() if b in NEEDS_LOCK and _declares(repo, f)]
    for f in declared:
        folder = f.rsplit("/", 1)[0].lower() + "/" if "/" in f else ""
        wanted = NEEDS_LOCK[names[f]]
        if not any(folder + w in lowered for w in wanted):
            loose += _unlocked(repo, f, wanted)
    return requirements + declared, loose, locks


def pinning(repo: Repo) -> dict[str, Any]:
    title = "Dependencies are pinned"
    manifests, loose, locks = _manifests(repo)
    if not manifests and not locks:
        return _care("pinning", title, "not applicable", reason="no dependency manifest found by rule")
    if not loose:
        evidence = [{"file": f, "fact": "lock file"} for f in locks] or [fact(f"pinned: {listed(manifests)}")]
        return _care("pinning", title, "passed", summary="pinned versions or a lock file", evidence=evidence)
    return _care("pinning", title, "failed", severity="medium", summary=f"{len(loose)} unpinned declaration(s)",
                 evidence=loose, suggestion="Pin every dependency (== versions, or a committed lock file), so the "
                                            "build installs what was tested.")


def _days(older: str, newer: str) -> int:
    return (dt.datetime.fromisoformat(newer) - dt.datetime.fromisoformat(older)).days


def dependency_age(repo: Repo) -> dict[str, Any]:
    title = "Dependencies were updated in the last year"
    manifests, _, locks = _manifests(repo)
    files = locks or manifests
    if not files:
        return _care("dependency_age", title, "not applicable", reason="no dependency manifest found by rule")
    changed = sorted((d, f) for f in files if (d := repo.last_change(f)))
    if not changed or not repo.committed:
        return _care("dependency_age", title, "not measured", reason="the mirror's history does not date them")
    when, rel = changed[-1]
    days = _days(when, repo.committed)
    evidence = [{"file": rel, "fact": f"last changed {when[:10]}, {days} days before the assessed commit "
                                      f"({repo.committed[:10]})"},
                fact("the age of each package is not measured: package registries are not read offline")]
    if days <= STALE_DAYS:
        return _care("dependency_age", title, "passed", summary=f"updated {days} days before the commit",
                     evidence=evidence)
    return _care("dependency_age", title, "failed", severity="low", summary=f"not updated for {days} days",
                 evidence=evidence, suggestion="Update the dependencies and run the suite; then keep them moving "
                                               "with an update bot.")


def update_automation(repo: Repo) -> dict[str, Any]:
    title = "Dependency updates are automated"
    found = [f for f in (repo.first(n) for n in UPDATERS) if f]
    if found:
        return _care("update_automation", title, "passed", evidence=[{"file": f, "fact": "present"} for f in found])
    manifests, _, locks = _manifests(repo)
    if not (manifests or locks or workflows(repo)):
        return _care("update_automation", title, "not applicable", reason="no dependency or action to update")
    return _care("update_automation", title, "failed", severity="low", summary="no update bot configured",
                 evidence=[fact(f"none of {listed(list(UPDATERS), 3)}")],
                 suggestion="Configure Dependabot or Renovate for the dependencies and the pipeline's actions.")


def docs(repo: Repo) -> dict[str, Any]:
    title = "The README says what the system is"
    readme = (repo.records.get("inventory") or {}).get("readme") or {}
    more = [{"file": f, "fact": "present"} for f in (repo.first("CONTRIBUTING.md"), repo.first("docs/README.md")) if f]
    if readme.get("first_paragraph"):
        return _care("docs", title, "passed", evidence=[{"file": readme["file"], "fact": "a paragraph of text"}, *more])
    if readme.get("file"):
        return _care("docs", title, "failed", severity="low", summary="the README has no paragraph of text",
                     evidence=[{"file": readme["file"], "fact": "no paragraph of text"}],
                     suggestion="Say in the README's first paragraph what the system does and for whom.")
    return _care("docs", title, "failed", severity="medium", summary="no README",
                 evidence=[fact("no README at the repository's root")],
                 suggestion="Add a README: what the system does, how to run it and its tests, who owns it.")


def ownership(repo: Repo) -> dict[str, Any]:
    title = "Owners are named for review"
    found = repo.first(*OWNERS)
    if found:
        lines = repo.find(re.compile(r"^\s*[^#\s]"), [found], limit=2)
        return _care("ownership", title, "passed", evidence=lines or [{"file": found, "fact": "present"}])
    return _care("ownership", title, "failed", severity="low", summary="no CODEOWNERS or MAINTAINERS file",
                 evidence=[fact(f"none of {listed(list(OWNERS), 4)}")],
                 suggestion="Name the owners in CODEOWNERS, so each change is reviewed by someone who knows the code.")


MAINTENANCE = (tests, baseline, coverage, pinning, dependency_age, update_automation, docs, ownership)

__all__ = ["CICD", "MAINTENANCE", "pipelines", "workflows"]
