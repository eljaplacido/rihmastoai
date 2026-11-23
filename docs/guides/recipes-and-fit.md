# Recipes, sandbox trials, measured fit and offline bundles

Four more pieces of the [agentic capability layer](../capability-layer.md):

- a **recipe** turns a proven capability into a starting point, so a new need is matched to what
  already works before anything new is built;
- a **sandbox trial** runs a candidate as a time-boxed local preview, and a named person decides
  what happens next;
- **measured fit** says how each model and endpoint performs on each kind of work, from the
  records only;
- a capability pack **declares** its workload classes, the site mode and its fallback ladder, and
  a release exports as an **offline bundle**.

None of them has a command or a cockpit screen yet. Each section shows how to call it from Python,
at the repository root.

## Recipes

A recipe is a delivered project whose latest [capability pack](packs-and-evidence.md) is valid
([kernel/recipes.py](../../kernel/recipes.py)). A product owner, a business owner or IT saves it.
The kernel refuses when:

- the project has no delivered release, or that release has no pack yet;
- the latest pack is for another release than the latest delivered one;
- the pack file no longer hashes to what `packs.json` recorded (it was edited after it was written);
- the pack is not valid: the refusal names each criterion that is not verified or held out.

A recipe keeps the spec, a summary of the contract (requirements and criteria), the profile, the
pack's version and hash, and its **parameters**: the questions every new use must answer.

```python
from kernel import recipes
from kernel.store import Factory

factory = Factory("var/demo")
project = factory.project("<project id>")
recipe = recipes.save(project, person="<your name>", persona="product_owner", parameters=[
    {"name": "approver", "question": "Who approves a loan?"},
    "Which kinds of items are lent?",                    # a plain question: its name is made from it
])
print(recipe["id"], recipe["pack"]["version"], recipe["keywords"])
```

### Matching a need to a recipe

`match(factory, text)` proposes recipes by rule, with no model. A recipe is proposed when it shares
**two keywords** with the need, or **one keyword and the profile** the need's own words name
([profiles](profiles.md)). The default profile, chosen when no word stands out, does not count.

```python
recipes.match(factory, "The lab needs to track equipment loans too")
recipes.match_signal(factory, "S-004")                   # a signal in the delivery square
```

Each proposal names the shared keywords, whether the profile matched, the pack version and the
parameters a new use would answer.

### A new project from a recipe

A business owner or product owner starts one:

```python
new = recipes.instantiate(factory, "RC-001", title="Lab equipment loans", person="<your name>",
                          persona="business_owner", parameters={"approver": "the lab manager"})
```

- The project starts at **explore** maturity, with the recipe's profile.
- Its spec starts from the recipe's spec. Every requirement is `vendor-proposed` until this
  project's owner confirms it: the recipe's owner confirmed it for another use.
- Each parameter becomes a question in the canon. A value given now is the person's answer. A
  parameter without a value stays open and goes to a person as a question card.
- The plan waits for a person's approval (`approve_plan`), so the pipeline compiles and builds
  nothing until someone has looked at the open parameters and approved the plan.

## Sandbox trials

`trial(project, ttl_minutes, person=..., persona=...)` tries a project before anyone commits to
it. It needs:

- explore maturity, and a compiled product;
- no blocking question open, and no other trial running;
- an autonomy cap of 3 (prepare) or more ([autonomy](autonomy.md));
- a business owner, product owner or developer to start it. That person is the one its outcome
  waits for.

What it does, with the existing delivery and operation code:

1. It delivers main's revision as a new explore release: build, deploy to the local preview,
   smoke check ([deploying](deploying.md)).
2. It runs the holdout scenarios against the preview and keeps the **scores only**: per criterion,
   passed or not. What a scenario expected stays in its custody.
3. It writes the result in plain words, for example: "Release 2 of Lab equipment loans (revision
   3f9c…) runs as a local preview at http://127.0.0.1:53121. Its holdout scenario passed. It stops
   by itself at 2026-11-22T12:30:00Z, after 30 minutes. Aino decides: promote it to a normal
   project, or discard it."
4. It opens an `approval` card for the named person: **approve promotes** the project to a normal
   one, **reject discards** it.
5. It starts a **watchdog**, a small detached process (`python -m kernel.recipes expire ...`) that
   stops the preview when the time limit passes, even when nothing else runs.

```python
t = recipes.trial(new, 30, person="<your name>", persona="product_owner")
print(t["result"])
recipes.decide(new, t["trial"], "promote", person="<your name>", persona="product_owner",
               reason="it does what the lab needs")                  # or "discard"
```

- **Promote** stops the preview and raises the maturity (demo by default; pass `maturity=` for
  pilot or production). The next pipeline run delivers it on that maturity's road.
- **Discard** stops the preview and stops the project (`halted`), keeping all its records.
- Only the named person decides. `decide` refuses anyone else. A card decided in the Inbox by
  someone else is not applied: `settle(project)` records why and asks the named person again.
- A trial that cannot start (no road, a failed smoke check) says so in plain words and still opens
  the card, so a person decides what to do with it.

`sweep(factory)` is one round over every project: it stops each trial past its limit (when its
watchdog did not, for example after a restart) and carries out trial cards decided in the Inbox.
Run it on a schedule, or before reading the trials.

## Measured fit

[kernel/fit.py](../../kernel/fit.py) says how each model and endpoint fits each **workload
class**:

| Class | Meaning | Roles, by rule |
|---|---|---|
| interactive | a person waits for the answer | assistant, embed |
| batch | nobody waits on each call | analyst, builder, verifier, holdout author |
| specialist | a narrow job a person names as such | none by rule: map a role with `roles={"<role>": "specialist"}` |

A role no rule maps is reported as not mapped, never guessed.

### Where the rows come from

Every row is one role, model, endpoint and workload class, from records only:

- **Gnomon runs** in every project ledger (`gnomon_run`): runs, the pass rate over measured runs
  (apparatus failures and not-measured runs are counted beside it, never in it), and tokens.
- **Gate rounds** (`cell_ran` and `gate`): the first-round pass rate of each builder model's work,
  as the kernel's gate judged it. A builder cell in a grant-free lane has no verify of its own, so
  this is the measure of a builder. A person's own workspace submission is left out. These rows
  have no endpoint: the cell record does not name it.
- **Gnomon eval reports**, imported read-only: the `report.json` that `gnomon eval` writes under
  `.gnomon-trials/_eval/` (schema `gnomon.eval/3`, section 47 of Gnomon's CONTRACTS). Each arm
  gives a row: passes over valid cells, output tokens, and wall-clock time, so a mean latency and a
  throughput. A command arm (another harness) is not metered by Gnomon, and its row says so. Any
  other file is not imported, and the report says why. Gnomon's other benchmark result files have
  no documented format, so they are not read.

Nothing is estimated. Gnomon's task record carries the run's duration (`volatile.duration_ms`), but
Rihma's ingest does not keep it in the ledger yet, so a ledger row says latency is **not measured**.
A ledger run that carries `duration_ms` is used as soon as the ingest keeps it.

### The rule

A candidate needs at least 5 measured runs (`min_runs`). Then:

- **batch** and **specialist**: the best pass rate wins; then more measured runs; then fewer output
  tokens per run;
- **interactive**: the best pass rate decides, but among candidates within 0.05 of it, the lowest
  measured mean latency wins.

```python
from kernel.fit import fit_report

text = fit_report(factory, ["Answer customers' questions in the website chat",
                            "Nightly report of overdue loans",
                            {"name": "Tag photos", "workload": "specialist"}],
                  eval_reports=["<path to>/report.json"])
open("fit.md", "w", encoding="utf-8").write(text)
```

A use case is mapped by the class a person names, by its role, or by keywords (chat, answer,
website, nightly, report, classify, extract, and so on). One that matches no rule, or two classes
equally, is listed as not mapped. The report then has:

- the use cases and their classes;
- the measured candidates per class;
- one recommendation per class, with its rule, and **what would change it**: the next candidate and
  the pass rate or latency it would need, candidates short of the minimum runs, unmeasured latency;
- everything **not measured**: per row, per class, per use case, and per import.

`assess(...)` returns the same as data. Rihma never re-routes on it: a person changes
[kernel/routing.json](../../kernel/routing.json), or this machine's `kernel/routing.local.json`
([Local models](local-models.md#2-route-the-roles)).

## What a pack declares

Each [capability pack](packs-and-evidence.md) now declares, apart from what was measured:

- the **workload classes** it uses, by the roles that built and judged it. The product's own
  runtime roles are not declared by the template yet, and the pack says so;
- the **site mode**: `connected` (the default), `restricted` or `air-gapped`;
- the **fallback ladder**, filtered by the site mode:

| Level | What | connected | restricted | air-gapped |
|---|---|---|---|---|
| L1 | the same pack elsewhere | yes | inside the site only | inside the site only |
| L2 | a smaller model, degraded | yes | yes | yes |
| L3 | the cloud, only for allowed data classes | the classes the policy allows (public by default) | public data only, when the policy allows it | never |
| L4 | queue and defer | yes | yes | yes |

IT or compliance sets the site mode in the factory's policy, with a reason, recorded in the
factory's ledger:

```python
from kernel.packs import set_site_mode

set_site_mode(factory, "air-gapped", person="<your name>", persona="it", reason="the plant network is isolated")
set_site_mode(factory, "connected", person="<your name>", persona="it", reason="the link is back",
              cloud_data_classes=["public", "internal"])
```

The declarations decide where the capability may run when something fails, so they are behaviour:
they are hashed with the pack's content, and **a change to them changes the version**. Where the
mode came from (the default or a person's policy) is not behaviour and is not hashed. A pack built
before declarations existed gets a new minor version the first time it is built again, because its
content now declares them.

`latest_pack(project)` reads the newest pack as it was written, and builds, versions and logs
nothing. `pack_problems(project, pack)` says when a pack no longer matches its record.

## Offline bundles

`export_bundle` exports one release as a folder, or a zip with `as_zip=True`
([kernel/bundle.py](../../kernel/bundle.py)). A compliance officer, IT, a business owner, a
product owner or a developer may export; the export is recorded in the ledger with their name.

```python
from kernel.bundle import export_bundle

path = export_bundle(project, "exports", person="<your name>", persona="it")   # the latest release
```

| File | What it is |
|---|---|
| `capability-pack.json`, `capability-pack.yaml` | the release's pack (the JSON is the record) |
| `contract.json` | the contract as the product carried it at the pinned revision |
| `source/product-<rev12>.zip` | the product's source at the pinned revision (`git archive`) |
| `image.json` | each artifact's reference; `images/<name>.tar` only when docker is on PATH and the image is present on this host |
| `BUNDLE.json`, `README.md` | what is in the bundle and what is not |
| `deploy-package.json`, `compose.yaml`, `evidence.zip`, `rihmasto_verify.py` | the deploy kit; see [taking a release to a site](packs-and-evidence.md#taking-a-release-to-a-site) |
| `SHA256SUMS` | the sha256 of every file above |
| `signature.json`, `SHA256SUMS.sigstore.json` | whether SHA256SUMS is signed; the Sigstore bundle only when it is |
| `pack-status.json` | the pack's status, which expires; outside SHA256SUMS, since a fresh copy replaces it |

**A signature only when cosign really signed.** When cosign is on PATH and the `RIHMA_COSIGN_KEY`
environment variable names a key (a file or a KMS reference; Rihma never reads the key), cosign
signs SHA256SUMS offline into a Sigstore bundle, with no transparency-log upload. Otherwise
`signature.json` says why not: "not signed: cosign not installed", no key named, or cosign failed
with its exit code. There is never a placeholder signature.

To check a bundle on the receiving side, against the key the factory published (never the
`cosign.pub` inside the bundle; see [taking a release to a site](packs-and-evidence.md#taking-a-release-to-a-site)):

```bash
python tools/rihmasto_verify.py <bundle> --key factory-cosign.pub
cosign verify-blob --key factory-cosign.pub --bundle SHA256SUMS.sigstore.json --trusted-root trusted_root.json --insecure-ignore-tlog=true SHA256SUMS
```

## What is not there yet

- No command or cockpit screen for recipes, trials, fit, site mode or bundles: Python only.
- The cockpit's Inbox does not call `recipes.settle`, so a trial card decided there is carried out
  by the next `sweep(factory)` or `settle(project)`. A dedicated trial card kind (promote, discard)
  would need a change to the canon; trials use the `approval` kind.
- Rihma's Gnomon ingest does not keep the run's duration, so ledger fit rows have no latency or
  throughput; only imported eval reports have them. Gate rows have no endpoint.
- The fallback ladder is declared, not enforced: nothing routes a call down the ladder yet, and the
  site mode does not yet restrict the endpoints in the routing file.
- No SBOM is generated for a bundle or a pack.
