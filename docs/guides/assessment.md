# Assessing an existing system, and watching it run

An assessment reads what Rihmasto holds of an adopted system's repository (main, from git's objects, never a
checkout) and judges it by rule from five perspectives: CI/CD governance, maintenance, security (with the red
team's static scan), compliance, and architecture and operations. Each finding names a file and a line, or a
measured fact, with a severity and a suggested change; what the files cannot show reads "not measured". With
**Ask the panel too**, the intake panel's perspectives (business, end user, IT and security, operations,
delivery) read the inventory and the rules' results through a model and propose more, kept apart as opinions.
The details, the record and the change loop are in [brownfield](../brownfield.md#assessing-an-adopted-system).

## Run one

In the cockpit, open an adopted project's **Assessment** tab and press **Assess now** (tick **Ask the panel
too** for the panel). On the command line:

```
rihmasto assess <pid> --person Aino --persona developer [--with-model]
```

By rule an assessment usually ends in seconds; with the panel, each perspective waits on a model, which can
take minutes. Either way the tab shows it live.

## Live progress

While it runs, the Assessment tab shows the assessment's plan as rows of tiles, one row per group:

| Group | Its steps |
|---|---|
| Reading the code | the revision (read from the mirror's objects), the inventory (languages, tests, routes) |
| Rule checks | one per area the rules cover (CI/CD governance, maintenance, security, compliance, architecture and operations), and the security scan |
| The panel | one per perspective that answers, each with the model named (only with the panel) |
| The record | the version written and its sha256 put in the ledger |

Each tile fills as its step runs and ends, and says its state in a glyph and a word, never in colour alone: a
dashed ring waits, a turning arrow runs, a tick is done, a cross failed (and says why: a perspective whose model
gave no answer is "not measured"), an arrow was skipped. A done area carries its count as it lands (5
findings; 1 proposal), with what else it measured (1 passed, 2 not measured). Above the tiles: the steps done
of all, a thin meter with one segment per step, the time it has taken, and the step running now in words ("The
IT and security perspective is reading the inventory and the rules' results with qwen3.6-35b"). Below them, the
findings so far, newest first; press a tile to list only that area's.

**The estimate is honest.** It comes from the step times of the earlier assessments of the same project (the
median of the last five, kept in the cockpit's own folder, `_cockpit/progress/<pid>.json`). The first one says
"First assessment here: no estimate yet"; a step never timed before is counted as unknown and said; a step
that runs well past its usual time says so.

**Cancel** stops the assessment after the step that runs now, signed with your name and noted in the ledger
(`cockpit_write`, `assess_cancel`); nothing it did so far is recorded. When it ends, the view waits a moment on
the filled tiles, then hands over to the result.

The same progress, small, is on the project's **Overview** while it runs, and in **Ask Rihma**: ask "how is the
assessment going?" (or "miten arviointi etenee?") and Rihma answers from the progress itself, no model needed:
"The assessment is 8 of 14 steps in (2 of 4 groups done), running for under a minute. Now: the business
perspective is reading ... Found so far: CI/CD governance 5, Maintenance 6, ...", with the tiles and Take me
there.

## Other long jobs

Every long job shows the same view. An **adoption** (in Plug in an existing project and on the Jobs page) maps
the steps its job prints (copying the folder, fetching the code, reading the code and the documents, running
its own tests once, recording the baseline) onto its plan; a step it did not need is skipped. A **folder scan**
shows looking through the folder, opening what matters and the material map, with its counts. Gate rounds,
deliveries and Gnomon audits that print their steps use the same adapter (`kernel/progress_jobs.py`
`from_lines`); jobs that report in lines carry no times, so their view says it has no estimate.

For a developer: a job reports through `kernel/progress.py` (`Reporter.plan`, `start`, `say`, `found`, `done`,
`failed`, `skip`, `finish`), and a route reads `Reporter.since(cursor)`: only the events after the cursor, and
the whole plan from cursor 0. The cockpit's routes are `GET /api/projects/<pid>/assessment/progress?since=<n>`
and `POST /api/projects/<pid>/assessment/cancel`; the view is `cockpit/static/progress.js`.
