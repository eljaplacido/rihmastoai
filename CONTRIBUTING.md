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

  Read the full text at the link above. Use a name and an email address that identify you.
- **Forgot to sign off?** `git commit --amend -s` fixes the last commit, and
  `git rebase --signoff main` fixes every commit on your branch.

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

## Run the checks

These are the commands CI runs ([.github/workflows/ci.yml](.github/workflows/ci.yml)), on Ubuntu
and Windows with Python 3.11 and 3.12. All three must pass.

```bash
python -m unittest discover -s tests              # the whole suite: about 13 minutes
python tools/contract_check.py contract/contract.json
python tools/contract_trace.py contract/contract.json
```

- Run the test modules you touch first, for example `python -m unittest tests.test_docs`, and
  the whole suite once before you open a pull request.
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

## Where decisions are recorded

[decisions/](decisions/) holds one file per decision: `D-0001-...md` and up. Each starts with
front matter (`id`, `decided_by`, `decided_on`, `kind`) and says what was decided, why, and on
what evidence. Contract amendments are in [decisions/amendments/](decisions/amendments/), and
proposals that wait for a decision in [decisions/proposed/](decisions/proposed/). A decision is
never rewritten; a later one supersedes it and says so. [GOVERNANCE.md](GOVERNANCE.md) says who
decides what.

## Conduct

Everyone who takes part follows the [code of conduct](CODE_OF_CONDUCT.md).
