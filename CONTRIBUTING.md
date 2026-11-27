# Contributing to Rihmasto

Rihmasto is built under its own rules. A change to the factory goes through the same steps it
asks of the products it builds: a criterion, a test named after it that fails first, the change,
and a recorded decision for anything that changes what is promised.

## Licence and sign-off

- **Inbound = outbound.** Rihmasto is licensed under the [Apache License 2.0](LICENSE). Your
  contribution is licensed under the same terms. There is no contributor licence agreement.
- **Sign off every commit** under the [Developer Certificate of Origin](https://developercertificate.org)
  (DCO). `git commit -s` adds the line for you:

  ```text
  Signed-off-by: Your Name <you@example.com>
  ```

  With that line you certify, in short, that:
  1. you created the contribution, in whole or in part, and have the right to submit it under the
     project's open-source licence;
  2. or it is based on earlier work under a suitable open-source licence, and you have the right
     to submit it, with your changes, under the same licence;
  3. or someone who certified 1, 2 or 3 gave it to you directly, and you did not change it;
  4. and you understand that the project and the contribution are public, and that a record of
     the contribution, your sign-off included, is kept indefinitely and may be redistributed.

  Read the full text at the link above. Use a name and an email address that identify you: the
  sign-off must name the commit's author, the same name and email.
- **Forgot to sign off?** `git commit --amend -s --no-edit` fixes the last commit. To fix every
  commit on your branch, run `git rebase --signoff <start>`, where `<start>` is the last commit
  your branch shares with `main`: the DCO check prints it, and it is in your clone, so the rebase
  moves nothing and only adds the lines. Then force-push the branch:
  `git push --force-with-lease origin HEAD`.
- **The DCO check.** Every pull request runs the **DCO sign-off** check
  ([tools/dco_check.py](tools/dco_check.py)). It lists each commit whose sign-off is missing or
  names someone other than its author, and says how to fix it.
- **Two authors need no sign-off, each only in a pull request its own account opened:** the
  project owner's GitHub noreply address (`40121627+eljaplacido@users.noreply.github.com`), in the
  owner's pull requests, because the owner holds the copyright of their own work; and
  `dependabot[bot]`, in Dependabot's pull requests, whose commits are the version bumps the owner
  set it up to make. git lets anyone write any author address, so the check goes by who opened the
  pull request, as GitHub records it. Everyone else signs off, maintainers included.

## Get set up

You need Python 3.11 or later and git.

```bash
git clone <repository URL> rihmasto && cd rihmasto
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e .
rihmasto demo                     # or: python -m kernel.cli demo
```

The tests need no Gnomon, no model and no network. They use scripted models and cells, and they
start product processes on loopback ports.

## Find your way around

| Folder | What is in it |
|---|---|
| `kernel/` | the rule engine: one module per job, each starting with a docstring that says what it owns ([architecture](docs/architecture.md)) |
| `cockpit/` | the web UI's server (`server.py`, `*_routes.py`) and its pages (`static/`, plain JavaScript; wording through `words.js`) |
| `mcp/`, `embed/`, `gateway/` | the MCP server, the website chat server and the capability gateway |
| `adapters/`, `connectors/` | reading Gnomon's results and SARIF; reference data connectors |
| `tools/` | the contract checker and tracer, the quality gate, the release export, sync and build |
| `contract/contract.json` | Rihmasto's own requirements, criteria and tasks |
| `decisions/` | every decision, amendment and proposal |
| `tests/` | `unittest` modules, named after the criteria they prove; `test_ui_*.py` drive the cockpit in headless Chrome |
| `docs/` | the guides ([index](docs/README.md)); `docs/scenarios/` walks each starting point |
| `.gnomon/` | the Gnomon surface Rihmasto ships; hashed byte for byte, so LF line endings only |

## Run the checks

These are the commands CI runs ([.github/workflows/ci.yml](.github/workflows/ci.yml)), on Ubuntu
and Windows with Python 3.11 and 3.12. All three must pass. On a pull request the DCO sign-off
check runs too ([How changes reach main](#how-changes-reach-main)).

```bash
python -m unittest discover -s tests              # the whole suite: about 13 minutes
python tools/contract_check.py contract/contract.json
python tools/contract_trace.py contract/contract.json
```

- Run the test modules you touch first, for example `python -m unittest tests.test_docs`, and
  the whole suite once before you open a pull request.
- **Browser tests.** The `tests/test_ui_*.py` modules drive the cockpit in headless Chrome over the
  DevTools protocol, at desktop and phone widths, in light and dark. They are skipped when Chrome is
  not installed (`RIHMA_CHROME` names another Chromium binary). A change to the cockpit's pages
  should pass them with no console errors and nothing scrolling sideways.
- **Docs.** `python -m unittest tests.test_docs` checks every relative link, that the docs index
  links every page, that every `rihmasto` subcommand the README and the getting-started guide name
  exists, and that no newcomer page names a home folder or a private address.
- CI also sets a git user name and email before the tests, in case a machine has none.
- Before a change to Python code, also run the quality gate: `python tools/quality.py --gate`.
  It fails on a hard rule (a file that does not parse, a third-party import in a runtime package,
  a bare `except`, a mutable default, CR line endings) or on a count that grew past
  [tools/quality_baseline.json](tools/quality_baseline.json). ruff and mypy are optional: without
  them their counts read "not measured".

## Spec first: criterion, test, change

Every change to what Rihmasto does starts from a criterion in the contract.

1. **The spec.** A requirement says what is needed, for whom. Each acceptance criterion says how
   you would know: given, when, then.
2. **The contract.** [contract/contract.json](contract/contract.json) is Rihmasto's own contract
   (`gnomonfactory.contract/1`). It holds the requirements (`FR-N4`), each with a provenance, the
   criteria under them (`FR-N4-AC-2`), each with the check that proves it, and the tasks, each
   naming the criteria it serves and the files it may write (`scope.write`).
3. **A test named after the criterion.** Its name contains the criterion's id, with hyphens as
   underscores:

   ```python
   def test_FR_N4_AC_1_the_demo_builds_a_home_with_no_keys_no_network_and_no_gnomon(self):
       ...
   ```

   `FR-N4-AC-1` is matched by `test_FR_N4_AC_1_...`, never by `test_FR_N4_AC_10_...`.
4. **Fail first.** Run the test before your change: it must fail. Then make the change, inside
   the task's scope, and run it again: it must pass. A test that passes before the change proves
   nothing. The factory's gate rejects such tests in products, and reviewers reject them here.

Two tools judge the contract, both standard library with no model:

- [tools/contract_check.py](tools/contract_check.py) checks the contract itself: unique ids,
  known keys, a check for every criterion, a task for every criterion and a criterion for every
  task, a named person behind every confirmed requirement, no dependency cycles. A failure names
  the rule, the path, what was expected and what was found.
- [tools/contract_trace.py](tools/contract_trace.py) lists each criterion with the tests that
  name it. A criterion no test names reads "not measured". It never says "verified": naming a
  criterion is a claim until a test is seen failing at base and passing at head.

**A new promise needs an amendment.** To change what Rihmasto promises, propose an amendment: the
requirement, its criteria and a task with its `scope.write`. It becomes a new contract revision
only when the lead maintainer approves it, and the approval is recorded in `decisions/`.

**A small fix needs none.** A bug, a typo or a clearer message inside an existing criterion needs
no amendment: add the regression test to the criterion it belongs to.

## The independence rule

- **Gnomon is the single runtime dependency.** The kernel reaches it only as a command. Every
  model call goes through Gnomon; the kernel never calls a model API itself.
- **Standard library only,** Python 3.11 or later ([D-0002](decisions/D-0002-kernel-language-python.md)).
  Add no package dependency, at runtime or in the tests.
- **No model family is assumed** ([D-0005](decisions/D-0005-no-model-family-dependency.md)). Roles
  are configuration in `kernel/routing.json`.
- **Other projects are inspiration only.** Rihmasto re-implements what it adopts, natively. What
  Gnomon does not yet support is fixed upstream in Gnomon
  ([D-0015](decisions/D-0015-integrations-through-gnomon.md)).

## Rules for the code

- **LF line endings.** [.gitattributes](.gitattributes) pins `eol=lf`. Gnomon hashes `.gnomon/`
  byte for byte, so a CRLF file changes a surface's identity between machines. Write files with
  `newline="\n"`; the kernel's own writers in `kernel/store.py` do.
- **Never commit secrets.** No keys, `.env` files, credential stores or tokens. Keys are read from
  the environment variable an endpoint's `api_key_env` names. Deploy packages carry secret
  references, never values. Check `git status` before every commit.
- **Neutral examples.** Demos, tests and docs use neutral examples, never real customers, people
  or machines.
- **Your machine stays out.** Put your own model endpoints in `kernel/routing.local.json`, which
  is gitignored and merged over the shipped `kernel/routing.json`. Tracked files name no host of
  yours, no home folder and no private address; `tests/test_docs.py` checks the newcomer pages for
  home folders and private addresses.
- **Honest states.** Use the named verdicts in `kernel/verdicts.py`. Something that could not be
  checked is "not measured", never a pass, a fail or a zero.
- **People decide.** Code may propose; only a named person with an allowed persona decides. Never
  let a model or "the factory" sign a decision.
- **One module, one job.** Each `kernel/` module starts with a docstring that says what it owns.
- **Trust is the owner's act.** Trusting a Gnomon surface (`gnomon trust grant`) is for the lead
  maintainer, never for a contributor or an agent.

## Issues

A good issue says:

- what is wrong or missing, and for whom (which persona, if it matters);
- how you would know it is fixed: a given / when / then is ideal;
- for a bug: the steps to reproduce, what you expected, what happened, and your Python and Gnomon
  versions (`rihmasto doctor` prints them; it never prints a key's value);
- the criterion it touches, if you know it.

Leave secrets, keys, private hosts and customer data out of issues and logs. Report a
vulnerability privately, as [SECURITY.md](SECURITY.md) explains, never in a public issue.

## Pull requests

A good pull request:

- names the criteria it serves, or the issue it fixes;
- names the tests that prove them, and says that they failed before the change;
- passes the three checks above;
- stays inside one task's scope, and is small enough to review in one sitting;
- has a `Signed-off-by` line on every commit;
- says what you could not check.

The [pull request template](.github/PULL_REQUEST_TEMPLATE.md) asks for these.

## How changes reach main

- **Pull requests only.** `main` is protected: nobody pushes to it, maintainers included. Fork the
  repository, work on a branch, and open a pull request against `main`.
- **The required checks.** A pull request merges only when the four CI jobs pass (Ubuntu and
  Windows, Python 3.11 and 3.12, in [ci.yml](.github/workflows/ci.yml)) and the **DCO sign-off**
  check passes ([dco.yml](.github/workflows/dco.yml)).
- **A code owner's review.** [CODEOWNERS](.github/CODEOWNERS) asks the lead maintainer to review
  every pull request ([GOVERNANCE.md](GOVERNANCE.md) says who decides what).
- **Squash merges.** A pull request becomes one commit on `main`, and the branch is deleted after
  the merge. A pull request of one commit merges with that commit's message, your `Signed-off-by`
  line included, so write it for the history. For several commits, the merge message is the pull
  request's title and your commits' messages, and the maintainer who merges keeps your
  `Signed-off-by` line at its end.
- **Sync pull requests.** The maintainers develop Rihmasto in a development repository of their
  own and publish it here as scrubbed snapshots. Each arrives as a pull request from a branch
  `sync/<sha>`, titled "Sync from the development repository at ...", whose description ends with
  a `Rihmasto-Export:` line; it passes the same checks. Before one is opened, every contribution
  merged on `main` is brought into the development repository with your name and the merged
  commit's message, your sign-off in it, kept, so a sync never reverts your work. A contribution
  must stay within the files this repository ships; one that adds a file the release leaves out,
  or a secret, cannot be brought in, and a maintainer will say so on the pull request. A change to
  `release/exclude.txt`, to the release tools (`tools/release_*.py`) or to a `.gitignore` gets a
  second, separate review before it is brought in.
- **Questions** go to [GitHub Discussions](https://github.com/eljaplacido/rihmastoai/discussions).
  Issues are for bugs and proposals.
- **A first contribution?** Look for issues labelled
  [good first issue](https://github.com/eljaplacido/rihmastoai/labels/good%20first%20issue): small,
  with a clear criterion, and a maintainer ready to help.

[docs/maintainers.md](docs/maintainers.md) gives the maintainers' side: releases and the sync.

## Versions and the changelog

- **Every notable change goes in [CHANGELOG.md](CHANGELOG.md)**, under `## [Unreleased]`, in the
  section that fits (Added, Changed, Fixed, Removed, Security). Name the criterion it serves and the
  guide that explains it. A pull request that changes what users see without a changelog line will be
  asked for one.
- **Versions follow [PEP 440](https://peps.python.org/pep-0440/):** `1.0.0a1` is an alpha,
  `1.0.0rc1` a release candidate, `1.0.0` a release. The version lives in `pyproject.toml`.
- **A maintainer cuts a version** by moving the Unreleased entries under `## [<version>] - <date>`,
  setting the same version in `pyproject.toml`, and, once that has merged, pushing the tag
  `v<version>`. The release workflow refuses a tag that does not match the declared version or has
  no changelog section ([maintainers](docs/maintainers.md)). Unreleased keeps its empty Added,
  Changed and Fixed headings after a cut, so a branch still open files its entry there and never
  under the version just dated; rebase an open branch onto them.
- **Which version you run:** `rihmasto --version`, `rihmasto doctor`, or **Settings > About and
  help** in the cockpit. The MCP server reports the same version to your IDE agent.

## Where decisions are recorded

[decisions/](decisions/) holds one file per decision: `D-0001-...md` and up. Each starts with
front matter (`id`, `decided_by`, `decided_on`, `kind`) and says what was decided, why, and on
what evidence. Contract amendments are in [decisions/amendments/](decisions/amendments/), and
proposals that wait for a decision in [decisions/proposed/](decisions/proposed/). A decision is
never rewritten; a later one supersedes it and says so. [GOVERNANCE.md](GOVERNANCE.md) says who
decides what.

## Conduct

Everyone who takes part follows the [code of conduct](CODE_OF_CONDUCT.md).
