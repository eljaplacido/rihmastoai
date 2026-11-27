# Capability packs and evidence packs

Two documents describe what a release is and how it was checked. A **capability pack** says
exactly what was delivered. An **evidence pack** bundles the records a reviewer needs to judge it.
Neither claims more than was done.

## Capability packs

One manifest per release, pinned by hash ([kernel/packs.py](../../kernel/packs.py)). It holds:

- the contract revision and the product revision;
- the artifacts: an image by the digest the registry gave it (`repository@sha256:...`) once it was
  pushed and pinned, never by its tag; otherwise by its local image id, with
  `pinned.not_by_digest` saying a site cannot pull it; or the process reference on the local road;
- the product's file trees, `app_files_sha256` and `runtime_files_sha256`, which pack_guard
  recomputes inside the container, and the public smoke set it runs (`smoke`);
- the models that built and judged the release, by role, and the harness surfaces they ran under;
- the autonomy cap the project had;
- its **acceptance**: every criterion with its evidence state, and the holdouts' results as scores
  only, never the scenarios;
- what it does not have: `sbom: not generated`, `signature: not signed`, and for a product with no
  runtime declaration, `runtime: not declared` (a small capability's pack carries its declaration).

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
| `people-in-the-loop.json` | every ask, every signed answer from people in the loop (inside, or outside through a one-use link) and every enforcement change; the summary's decisions by people counts the answers |
| `gates.json` | every gate verdict, round by round |
| `holdout-scores.json` | holdout results as scores; the scenarios stay in custody |
| `gnomon-runs.json` | each Gnomon run: role, model, surface hash, audit-chain head and whether it was intact |
| `ledger.jsonl`, `ledger-check.json` | the full project ledger, and the result of verifying its hash chain at export |
| `attestation.json` | the verdict and the control table |
| `governance-map.json` | each of the five guarantees held, partial or lost where the latest release runs, the same map as its deploy gate card |
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

## Taking a release to a site

Phase 1 of [portability](../portability.md) is built: a delivered release travels as its image,
pinned by digest, with its pack beside it, never inside it (the pack pins the image).

**Pinned by digest once IT pushed it.** Name a registry on a docker road in `paved_roads.json`
(`"registry": "registry.example:5000/team"`). At build, the kernel tags the image for that registry
on the deploying host (`image_tagged` in the ledger) and pushes nothing: every write to an external
system goes through Gnomon's integration lane
([D-0015](../../decisions/D-0015-integrations-through-gnomon.md)), which is planned. IT pushes the
tag with its own tools (`docker push <tag>`; the release records the tag), then pins the release:

```bash
rihmasto --home var/demo pack pin <project id> --person "<your name>" --persona it
```

It reads the digest the registry gave the image from the deploying host's docker (`RepoDigests`),
records `image_pinned` with the person, and from then on the release, its pack and the site's
deploy package name the image by that digest. A tag not pushed yet is said, not pinned; only the
it persona may pin. Until then, or without a registry, the pack pins the local image id and says
why a site cannot pull it.

**The offline bundle** ([kernel/bundle.py](../../kernel/bundle.py), from Python for now) is the
deploy kit. Besides the pack, the contract and the source it holds:

| File | What it is |
|---|---|
| `deploy-package.json` | the site's deploy package (`gnomonfactory.deploy_package/2`): the image by digest, the pack by version and hash, secrets by name only |
| `compose.yaml` | for any Docker or Podman host, only when the image is pinned by digest: `/data` on a named volume, the bundle's folder (the pack and its status) mounted read-only at `/pack`, each secret as the environment variable of its name, its value from the deployer's environment |
| `evidence.zip` | an evidence pack, exported and recorded as any other |
| `rihmasto_verify.py` | the offline verifier |
| `BUNDLE.json`, `README.md` | what is in it and what is not, and its governance map |
| `SHA256SUMS` | the sha256 of every file above |
| `signature.json`, `SHA256SUMS.sigstore.json`, `trusted_root.json` | how SHA256SUMS is signed: a Sigstore bundle, only when cosign really signed |
| `cosign.pub` | the key that signed, for reference only: verify against the key the factory published |
| `pack-status.json` (and its `.sigstore.json`) | the pack's status (`rihma.pack-status/1`): valid, suspended or withdrawn, and when it expires; signed whenever the bundle is |

**Signing.** cosign 3.1 and later sign a blob only into a Sigstore bundle. When cosign is on PATH
and `RIHMA_COSIGN_KEY` names a key (a file or a KMS reference; Rihmasto never reads the key), the
bundle and its status are signed offline, with no transparency-log upload, and carry what an
offline check needs. Without cosign it says "not signed: cosign not installed". Never a placeholder
signature. The factory's owner publishes the public key apart from any bundle, for example
`cosign public-key --key "$RIHMA_COSIGN_KEY" --outfile factory-cosign.pub`, and hands it to each
site's IT once: the `cosign.pub` inside a bundle proves nothing, since whoever changes a bundle can
sign it again and replace that file.

**Checking a bundle where it lands**, with nothing installed but Python, against the key the factory
published:

```bash
python tools/rihmasto_verify.py <bundle folder or zip> --key factory-cosign.pub
cosign verify-blob --key factory-cosign.pub --bundle SHA256SUMS.sigstore.json --trusted-root trusted_root.json --insecure-ignore-tlog=true SHA256SUMS
```

The verifier ([tools/rihmasto_verify.py](../../tools/rihmasto_verify.py)) imports nothing from
Rihmasto. It checks SHA256SUMS (a changed byte is named by its file), the pack's hash, that the
bundle, the deploy package and the status name that pack, the status's expiry, the app files against
the source, the evidence pack's manifest and ledger chain, and the published
[schemas](../../schemas/). With cosign on PATH it verifies the signatures against `--key` only
("verified"). In a signed bundle the status must be signed and present too, and with `--key` a
bundle without a signature fails. The verdict:

| Verdict | Exit | When |
|---|---|---|
| passed | 0 | every check passed and every signature was verified against `--key` |
| failed | 2 | a check failed, or a signature did not verify or is missing where one is required |
| not verified: no verifier | 3 | every other check passed; cosign is not installed |
| not verified: no trusted key | 3 | every other check passed; no `--key` was given |
| not signed | 3 | every other check passed; nothing is signed (an evidence pack never is) |
| not measured | 4 | nothing readable was given |

**pack_guard.** Every product built on the paved road carries `factory/pack_guard.py`, and its image
starts through it (the Dockerfile's CMD), so a change to `app/` cannot take the guard out. Where a
site sets `RIHMA_PACK` (the compose file does), `/health` answers 503, with the reasons, until the
pack's hash, the app and runtime files, the status (valid, unexpired, this pack) and the smoke set
pass. An edited file keeps the product from ever becoming ready. The guard keeps the newest status
it has seen in `DATA_DIR`: an older status is not taken, a withdrawal is final, and a missing or
half-written status file falls back to the newest seen, also after a restart. Replace
`pack-status.json` in the bundle's folder however you like (the folder is mounted, not the file).
It cooperates with the operator: it is not DRM. Without `RIHMA_PACK` it hands over to the product's
server, and the factory's own roads start the product directly.

**Withdrawing a pack version.** A person with the it, compliance or product owner persona:

```bash
rihmasto --home var/demo pack withdraw <project id> "why" --person "<your name>" --persona it
```

It is recorded in the ledger (`pack_withdrawn`) and issues a withdrawn status document in the
project's `pack-status/` folder, signed when cosign can sign. Placed beside the pack at a site, it
turns that site's `/health` to 503 at the guard's next read, naming the reason and the person.

**The governance map.** Every gate card (the demo's acceptance, staging's validation, production's
deploy gate), the evidence pack and the bundle mark each of the five guarantees (pinning, evals,
revocation, evidence, telemetry) *held*, *partial* or *lost* where the release runs, and why. A guarantee resting on a platform feature nobody has verified (the Azure
road, never deployed) is never held.

## What is not there yet

- Packs are not signed on their own, and no SBOM is generated. Each pack says so; a bundle's
  SHA256SUMS is signed when cosign can sign it.
- The web-service template declares no runtime (`runtime: not declared`). A small capability's
  template does: its pack's `runtime` carries its trigger, tools, model roles, integrations, secrets
  by name and faces, and the image serves MCP and an OpenAI-compatible model behind the pack guard
  ([small capabilities](small-capabilities.md)).
- No command or cockpit screen exports a bundle; Rihmasto does not push to a registry (IT does,
  until Gnomon's integration lane can); pack_guard reads the status from a file only; the base image
  is a tag, not a digest. See [portability](../portability.md) for the rest of the plan.
