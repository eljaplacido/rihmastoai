## What and why

<!-- What this changes, and the need behind it. Link the issue if there is one. -->

## Criteria

<!-- The contract criteria this serves, for example FR-N4-AC-2. A new promise needs an amendment
in contract/contract.json and a record in decisions/. -->

-

## Tests

<!-- The tests that prove each criterion. Their names contain the criterion id
(test_FR_N4_AC_2_...). -->

-

- [ ] Each new test failed before the change, and passes after it.

## Checks

- [ ] `python -m unittest discover -s tests`
- [ ] `python tools/contract_check.py contract/contract.json`
- [ ] `python tools/contract_trace.py contract/contract.json`
- [ ] `python tools/quality.py --gate` (for a change to Python code)

## Sign-off

- [ ] Every commit has a `Signed-off-by` line (`git commit -s`), under the
  [Developer Certificate of Origin](https://developercertificate.org).
- [ ] The change adds no package dependency, and no secret, key or private host.

## What I could not check

<!-- Anything you could not run or verify, and why. -->
