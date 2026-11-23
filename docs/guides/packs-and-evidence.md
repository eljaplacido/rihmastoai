# Capability packs and evidence packs

Two documents describe what a release is and how it was checked. A **capability pack** says
exactly what was delivered. An **evidence pack** bundles the records a reviewer needs to judge it.
Neither claims more than was done.

## Capability packs

One manifest per release, pinned by hash ([kernel/packs.py](../../kernel/packs.py)). It holds:

- the contract revision and the product revision;
- the artifacts (the image, or the process reference on the local road);
- the models that built and judged the release, by role, and the harness surfaces they ran under;
- the autonomy cap the project had;
- its **acceptance**: every criterion with its evidence state, and the holdouts' results as scores
  only, never the scenarios;
- what it does not have: `runtime: not declared`, `sbom: not generated`, `signature: not signed`.

**Pack version equals behaviour version.** If any pinned hash changes, the version changes
(1.0.0, then 1.1.0, and so on). The same content keeps its version.

**A pack is valid only while its acceptance holds:** every criterion verified, or held out and
passing. Otherwise `not_valid_because` lists each criterion and its state.

Build or re-read one after a release:

```bash
rihma --home var/demo pack <project id>               # the latest release's pack, as JSON
rihma --home var/demo pack <project id> --release 2   # release 2
rihma --home var/demo pack <project id> --yaml        # a readable view; the JSON is the record
```

The JSON says the `version`, and under `acceptance` whether it is `valid` and, if not, each
criterion in `not_valid_because`. A project with no release yet is refused (exit 2). The pack is
written to `releases/<n>/capability-pack.json` in the project folder, and each new version is
listed in `packs.json` and the ledger (`pack_versioned`). The demo's shipment webhook has one:
version 1.0.0, valid, built by `demo-builder`. In the cockpit, a project's **Releases** view shows
each release's pack first. From Python, `kernel.packs.build_pack` and `render_yaml` do the same.

## Evidence packs

An exportable zip for compliance and audit: an AI Act, GDPR or NIS2 review, or an internal audit
([kernel/evidence_pack.py](../../kernel/evidence_pack.py)). It holds:

| File | What it is |
|---|---|
| `capability-pack.json` | the pack, as above |
| `contract.json`, `spec.md` | what was promised |
| `evidence.json` | each criterion's evidence state |
| `decisions.json` | every decision, with its person and persona |
| `gates.json` | every gate verdict, round by round |
| `holdout-scores.json` | holdout results as scores; the scenarios stay in custody |
| `gnomon-runs.json` | each Gnomon run: role, model, surface hash, audit-chain head and whether it was intact |
| `ledger.jsonl`, `ledger-check.json` | the full project ledger, and the result of verifying its hash chain at export |
| `attestation.json` | the verdict and the control table |
| `README.md`, `MANIFEST.json` | a summary, and the sha256 of every file |

**The attestation is never "compliant".** It is one of:
- **attestable:** the records are intact and complete enough for a reviewer to judge;
- **chain broken:** a hash chain did not verify, so what it covers cannot be trusted as recorded;
- **insufficient evidence:** intact, but too little was recorded (no release, or no human
  decision).

The control table names public control ids (for example `ai-act:art14`, human oversight) and says
for each one *evidenced*, *partial* or *no*, and why. It says plainly what the factory cannot
evidence, such as the transparency of a product's own screens. A reviewer judges conformity,
not the factory.

A compliance officer, IT, a business owner, a product owner or a developer may export; the export
is recorded in the ledger with their name:

```bash
rihma --home var/demo evidence <project id> --out exports --person "<your name>" --persona compliance
```

It prints the zip's path (`exports/<project id>-evidence-<...>.zip`) and the attestation's
verdict. In the cockpit, a project's **Evidence** view has **Export evidence pack**. From Python,
`kernel.evidence_pack.export` does the same.

## Security scans in both packs

Both packs carry the same security summary (`security` in the capability pack, `security.json` in
the evidence pack, from [kernel/security.py](../../kernel/security.py)): the latest scan of each
tool with its file's sha256 and counts by level, the gate's verdict, and each risk a named person
accepted until a date. With no scan it says "not measured: no security scan", never "passed". A
scan is evidence, not behaviour, so a new scan does not change the pack's version.

What the summary can be trusted to mean
([adapters/sarif.py](../../adapters/sarif.py) reads the SARIF 2.1.0 file):

- **A scanner that did not finish is not a clean scan.** A run with no `results` array, or with an
  invocation whose `executionSuccessful` is not true, is refused. So is a run that names no tool,
  a level other than `error`, `warning`, `note` or `none` (never lowered to a warning), a result
  whose level cannot be known, a start line or column that is not a whole number, text that cannot
  be stored as UTF-8 (a lone surrogate), and any malformed, too deep or too large file. The refusal
  is recorded as `security_scan_refused` with the file's sha256 and a reason cut to 500 characters,
  and the tool's last scan still counts.
- **Rules are read where the tool keeps them**, in the driver or in a tool extension (CodeQL's query
  packs), so a finding keeps its rule's level and CWE.
- **The latest scan is per tool and scope.** The scope is the run's category (`automationDetails.id`
  up to its last `/`, which CodeQL's `--sarif-category` sets) and its extensions' names. A clean
  JavaScript scan by CodeQL does not hide the open errors of its Python scan. A pipeline that scans
  several targets with one tool gives each its own category. The summary names the scope.
- **An acceptance covers one finding at the level accepted.** A finding's fingerprint includes its
  file, even when the tool gives a fingerprint of its own. A tool's full `fingerprints` decide
  before its `partialFingerprints`, so two results on one line with the same line hash stay two
  findings. Two findings of one scan never share a fingerprint. When a later scan reports the
  accepted finding at a more severe level, the acceptance no longer holds: the finding is open
  again, and the gate lists it under `reopened` with why.
- **An ended acceptance is recorded as what it means.** `risk_acceptance_expired` says the finding
  is open again only when that was its current acceptance and a scan still reports it; otherwise it
  says a later acceptance replaced it, or that no scan reports the finding now.
- **Who handed the file in.** A pipeline signs nothing; a person who hands in a scan is a named
  person with a persona, and the scan records both.

Scans stored before scopes existed give way to the tool's next scan, as before. For a tool that
gives fingerprints of its own (semgrep, CodeQL, gitleaks), the fingerprint now includes
the file, so an acceptance recorded against such a scan from before holds until the tool's next
scan, and is then given again if it still applies.

## What is not there yet

- Packs are not signed, and no SBOM is generated. Each pack says so.
- Product templates do not declare the runtime models an agentic product uses
  (`runtime: not declared`).
