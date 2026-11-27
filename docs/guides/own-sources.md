# A project's own sources

An adopted or attached project often keeps its real requirements, tests and plan in its own shape: a folder
of rule files, each with the test that checks it; a gate run on another machine; an issues log; a round's
README whose table says what is done. Guessing them from old documents misleads ("0 of 772 tests trace",
"the suite could not run"). Here the project says where they are, Rihmasto finds and proposes them by rule,
and from then on reads them as the truth.

## Where it is

- **Project settings** of an adopted or attached project: *Project's own sources*.
- **What Rihmasto understood**, on an adopted project's Overview: one line on what is mapped, its own
  tasks and findings, and the panel folded below.
- **Ask Rihma**: "where does this project keep its requirements?", "use the rule files as requirements".
- **A terminal**: `rihmasto sources show <pid>` and the signed `rihmasto sources map|change|stop|read|use-anyway|import|run`.

The panel starts with **What to do next**, from the real state, as buttons: map what was found, run a test
root that has not run, import results from elsewhere, use an old plan anyway, read again after a new commit.

## What is found, by rule

Read from the repository's committed revision; nothing found is run.

| Kind | Found as | Read with |
|------|----------|-----------|
| Requirements and criteria | a folder of JSON or YAML records sharing an id, a title and criteria or the test that checks each | a field mapping: `id`, `title`, `statement`, `criteria`, `test`, `status` |
| Findings | a JSONL file (an issues or findings log) | one finding per line: id, title, severity, status, where |
| Tasks | markdown tables with a status column, and checklists, in a round's or sprint's README, a handoff note, a to-do list | each row a task with its status; sibling folders (`rounds/*/README.md`) are one source |
| Test results | JUnit XML, TAP or JSON files a run committed | the cases and their verdicts, or bare counts |
| Test roots | each Python package with its own `pyproject.toml`, `setup.cfg`, `pytest.ini` or `tox.ini` above its tests | a command per root, any command, not only pytest |

Each record keeps its path and line, so whatever is shown from it says where it came from.

## Old plans

A planning document (a spec, a requirements document, a task list, a plan) whose last commit is at least
14 days older than the code's newest commit, with at least 8 commits to the code since, **may be an old
plan**. It is not imported into alignment by default and the panel says so; **Use it anyway** keeps it,
signed. These two numbers are the platform's, the same for every project; which files are a project's own
sources is the project's.

## Mapping, changing, stopping

**Map** takes a found source as it was proposed, or files you name with a glob and a field mapping.
**Change** edits the files, the field mapping or how often it is read again: on every new commit (the watch
of an adopted project), daily or weekly (an automation in your name), or by hand. **Stop** keeps it,
stopped, with your reason. Each is signed by a developer, product owner, IT or operations, and in the
project's ledger. Nothing is ever written to the repository.

## What then comes from them

- **Alignment** (the Alignment tab) proposes the requirements and criteria from the mapped source instead
  of documents, and its tasks from the mapped task rows. A test a requirement's own record names traces to
  it "by the project's own source", with full confidence.
- **What Rihmasto understood** says its tests from its own runs, its contract from its own requirements and
  its open findings from its own file. A run from the repository's root that could not run no longer
  shows as a health problem once each of its own test roots passes.
- **The trace**: each requirement, the test it names, and that test's latest result (a run here, results
  imported or committed), with where and when it ran.

## Test runs

- **Run its tests** runs a mapped root's command in a temporary checkout, offline, with a time limit, through
  IT's isolation runner when access is enforced, after a developer, IT, operations or product owner says
  yes: it runs the project's own code on this machine. It is a job you follow live in Running now. A
  command is a program and its arguments; shell syntax is refused. The verdict comes from the exit code and
  the counts its output gives, or from the results file the mapping names.
- **Import results** keeps a results file produced elsewhere (a nightly gate on a build host) with the
  time it was produced and the machine's name, signed. Nothing runs here.

## Said truly

- **Old plans by real commits.** The commits to the code since a planning document last changed are counted
  from the history over every code path, so code that changed twenty times in two files has twenty commits
  since, not two. A handoff note, a to-do list or a roadmap at the repository's root is found as tasks; a
  run report in a `gates/` folder as test results.
- **Each test its own verdict.** A requirement's test matches a result by its whole name or whole segments
  of it (`tests/test_a.py::test_b`), never by a part of a word: `gate_law_01` is not `gate_law_010`. A file
  named as the test takes its cases' worst verdict. With no match it says *not run*.
- **Every root.** A root-level baseline that could not run stops counting as a health problem only once
  every mapped test root has a passing latest run. Then the header, *Its state*, Ask Rihma and the suggested
  automation say its own tests instead of the root's suite, and an automation that runs its tests runs each
  mapped root.
- **The latest revision.** *Read again* (and a daily or weekly read) fetches an adopted project's upstream
  first and says whether it moved, or why it could not fetch. A source read on every new commit says so only
  when the watch is set up; until then it says *not watched yet* and *What to do next* offers *Set up the
  watch*.
- **Review in Alignment.** Mapped requirements and tasks reach the contract and the Board when you accept
  them in Alignment: *What to do next* says how many wait (*Review 4 requirements and 6 tasks to import*) and
  opens it. The panel stays open while next steps remain.
- **Findings in Health.** The open findings of the project's own findings file show on its Health tab, each
  with its severity and its place in the code. Keys such as `issue_id`, `sev` and `loc` are mapped by rule;
  a line that is not a JSON object is said, never dropped silently.
- **Stopped sources** are listed with who stopped them and why, with *Resume*; what they read is not offered
  again as found. Ask Rihma: "resume SRC-2". Asking to use a source that is mapped already says which one it
  is; "use <path> anyway" for a document that is not an old plan says so.
