# Getting started

Rihmasto sits as the governed middle layer between **your own development environments** (IDEs,
repositories, terminals, and coding agents) and **wherever your software and agentic capabilities are
deployed and monitored** (web, cloud, containers, local hosts, or MCP/HTTP faces). This guide takes you
from a fresh machine to a first real project. The demo needs only Python and git. Real projects also
need Gnomon and models from at least two model families.

## 1. What you need

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.11 or later | everything (standard library only, no packages) |
| git | any recent | the demo, lanes and product repositories |
| Gnomon | 0.6.5 or later; 0.6.7 recommended (the latest; `rihmasto doctor` says so) | real projects: every model call goes through it |
| Node | 22 or later | Gnomon |
| docker | any | optional: only the `docker` paved road |

Builder cells have run on Linux. On Windows the kernel, the tests, the demo and the cockpit run
natively; run cells in WSL2 or a container.

## 2. Install Rihmasto

```bash
git clone <repository URL> rihmasto && cd rihmasto
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e .
```

This installs the `rihmasto` command and `rihmasto-cockpit`, `rihmasto-embed` and `rihmasto-mcp`.
The earlier names (`rihma`, `rihma-cockpit` and so on) stay as aliases.

- Install it editable (`-e`), from a checkout. The kernel reads `.gnomon/`, `tools/` and
  `kernel/routing.json` from the checkout, so a copy outside it would not run.
- Use a virtual environment of its own. Rihmasto's `mcp` package would shadow the MCP Python SDK
  of the same name.
- `pip install -e .` may fetch the build tool, setuptools, once. Rihmasto itself has no package
  dependencies.
- You can also skip installing. Every command works from the repository root:
  `python -m kernel.cli <command>`, `python -m cockpit.server`, `python -m embed.server` and
  `python -m mcp.server`.

## 3. Check the machine

```bash
rihmasto doctor
```

It prints JSON:
- Python;
- Gnomon (found, version, supported, recommended);
- git and docker;
- whether the lanes root is writable;
- whether this machine's routing overlay, `kernel/routing.local.json`, is present (section 5);
- for each endpoint in the routing, whether its key variable is set. It never prints a key's
  value.

It exits 1 when Gnomon is missing, too old, or its version cannot be read. Everything else is a
warning. The demo below runs even when the doctor exits 1.

## 4. Try the demo

```bash
rihmasto demo
rihmasto-cockpit --home var/demo
```

`rihmasto demo` builds a demo factory home in `var/demo` in well under a minute. It uses no model
keys, no network and no Gnomon:
- a scripted model stands in for the analyst and the holdout author;
- a scripted builder cell and verifier stand in for Gnomon's cells;
- everything else is the real kernel: the panel, the spec rules, the compiled contract, the
  holdout custody, git lanes, the gate, the local preview road and the capability pack.

Every decision in it is made by a fake person named `demo-*`. Use `--home DIR` to build it
elsewhere. Running it again replaces an earlier demo home. It refuses any other folder that is
not empty, so it cannot overwrite a real factory home.

`rihmasto-cockpit` prints one link. Open it once, pick a persona, and look around.
[demo.md](demo.md) walks through what each persona sees.

The demo's scripted cell exists only inside `rihmasto demo`. **Advance** in the cockpit runs the
real pipeline, which needs Gnomon and models (section 5). The local preview was started, checked
and stopped again, so the release link in **Try it** does not answer.

## 5. Install Gnomon and configure models

### Install Gnomon

Install Gnomon with its own installer. These commands are from Gnomon's README at v0.6.6:

```bash
# Linux and macOS (needs Node 22 or later; the installer says how to get it if missing)
curl -fsSL https://raw.githubusercontent.com/eljaplacido/gnomonharness/master/scripts/install.sh | sh
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/eljaplacido/gnomonharness/master/scripts/install.ps1 | iex
```

- To pin a version, set `GNOMON_VERSION=0.6.7` before the install line
  (PowerShell: `$env:GNOMON_VERSION = '0.6.7'`). 0.6.7 is Gnomon's latest release at the time of
  writing; `rihmasto doctor` accepts 0.6.5 and later.
- `npm i -g gnomon-harness` also works. Check what it would install first with
  `npm view gnomon-harness version`.
- `gnomon update` upgrades it later.
- Rihmasto finds Gnomon as `$GNOMON_CMD` (split like a shell command line), or `gnomon` on your
  PATH. Run `rihmasto doctor` again: it should now exit 0.

### Verify what you install

Gnomon runs every model call and every builder cell, so check its bytes before you trust them.

- **The installer checks for you.** It downloads the release's `SHA256SUMS` and refuses any file whose
  SHA-256 does not match, or that has no published digest.
- **Read the installer before you run it.** Instead of piping it into a shell, download it, read it,
  then run it:

  ```bash
  curl -fsSLo install-gnomon.sh https://raw.githubusercontent.com/eljaplacido/gnomonharness/master/scripts/install.sh
  less install-gnomon.sh
  GNOMON_VERSION=0.6.7 sh install-gnomon.sh
  ```

- **Check a release by hand.** Every Gnomon release publishes `SHA256SUMS`, a `.sha256` file per
  archive, an SPDX SBOM and signed SLSA build provenance. With the GitHub CLI:

  ```bash
  V=0.6.7
  gh release download v$V -R eljaplacido/gnomonharness -p "gnomon-$V-linux-x64.tar.gz" -p SHA256SUMS
  sha256sum --check --ignore-missing SHA256SUMS        # macOS: shasum -a 256 --check --ignore-missing SHA256SUMS
  gh attestation verify gnomon-$V-linux-x64.tar.gz --repo eljaplacido/gnomonharness \
    --cert-identity https://github.com/eljaplacido/gnomonharness/.github/workflows/build-release.yml@refs/tags/v$V
  ```

  On Windows, `Get-FileHash gnomon-0.6.7-windows-x64.tar.gz -Algorithm SHA256` prints the hash to
  compare with its line in `SHA256SUMS`. From a checkout of Gnomon, `scripts/verify-release.sh 0.6.7`
  checks every file of a release and its attestations at once.
- **Trust is yours to give.** A Gnomon surface that grants more than Gnomon's defaults runs clamped
  until its owner trusts it (`gnomon trust grant`). Rihmasto's product lanes grant nothing extra, so
  they need no trust; never let an agent grant it for you.

Rihmasto's own releases carry the same kind of evidence: source archives, a CycloneDX SBOM,
`SHA256SUMS` and a signed build provenance attestation (`sha256sum --check SHA256SUMS`, then
`gh attestation verify <file> -R eljaplacido/rihmastoai`).

### Choose the models

**The quick way.** In the cockpit, **Settings > Models setup** sets each role and tests it. On the
command line:

```bash
rihmasto models presets                                   # the common choices, local and hosted
rihmasto models set analyst --base-url http://127.0.0.1:8080/v1 --model qwen3-32b \
    --person "<your name>" --persona it                   # a local OpenAI-compatible server
rihmasto models set verifier --base-url https://llm-provider.example/v1 --model glm-4.6 \
    --key-env HOSTED_API_KEY --person "<your name>" --persona it   # a hosted one; the key stays in the variable
rihmasto models use claude-code --person "<your name>" --persona it  # or: your coding agent, on your own login
rihmasto models test analyst
```

[Models setup](guides/models-setup.md) and [your coding agent as the model](guides/harness-models.md)
say more. The rest of this section is the routing file those commands write, for when you want every
detail.

Rihmasto is model-agnostic. Each role (each Rihma agent) uses any OpenAI-compatible endpoint, local
or hosted, set per role. Every call goes through Gnomon, which gives it governance, an audit trail
and security, whatever model answers.

The shipped [kernel/routing.json](../kernel/routing.json) points at a local OpenAI-compatible
server on 127.0.0.1 and one hosted endpoint. Put your own routing in `kernel/routing.local.json`,
beside it. That file is gitignored, so your hosts and choices never reach a commit, and the kernel
merges it over the shipped file each time it loads the routing:

- each role, model and endpoint it names replaces the shipped one whole (a role's `fallback` too);
- any other key it sets, such as `max_context_tokens`, replaces the shipped value;
- nothing is removed. A shipped endpoint that no role uses is never compiled into a lane, but
  `rihmasto doctor` still warns when its key variable is not set.

This `kernel/routing.local.json` uses a GPU host on your network for the analyst and the builder,
and a hosted provider for the verifier and the holdout author:

```json
{
  "max_context_tokens": 98304,
  "roles": {
    "analyst":        {"model": "qwen3-32b", "endpoint": "local"},
    "holdout_author": {"model": "glm-4.6",   "endpoint": "hosted"},
    "builder":        {"model": "qwen3-32b", "endpoint": "local",
                       "fallback": {"model": "deepseek-v3", "endpoint": "hosted"}},
    "verifier":       {"model": "glm-4.6",   "endpoint": "hosted"},
    "assistant":      {"model": "qwen3-32b", "endpoint": "local"}
  },
  "models": {
    "qwen3-32b":   {"family": "qwen"},
    "glm-4.6":     {"family": "glm"},
    "deepseek-v3": {"family": "deepseek"}
  },
  "endpoints": {
    "local":  {"kind": "openai", "url": "http://gpu-box.local:8080/v1/chat/completions"},
    "hosted": {"kind": "openai", "url": "https://llm-provider.example/v1/chat/completions",
               "api_key_env": "HOSTED_API_KEY"}
  }
}
```

- **Roles.** `analyst` runs intake and the spec. `holdout_author` writes the end-to-end
  scenarios. `builder` writes code in a cell. `verifier` reviews it read-only. `assistant`
  answers "Ask Rihma" in the cockpit; without it, the analyst's model is used.
- **The verifier is always another family.** The kernel refuses a routing where the verifier
  shares a family with the builder or the builder's fallback. The verifier has no fallback: a
  judge from the builder's family is no judge, so an unavailable verifier makes the verdict
  "not measured". Give the holdout author another family than the builder too.
- **Families** come from `models.<name>.family`, or else from the model name up to its first
  hyphen.
- **Keys** are read from the environment variable that `api_key_env` names. Set it in the shell
  that runs Rihmasto. `rihmasto doctor` tells you whether it is set. A key never goes in a file in
  the repository.
- **Local models** work through any OpenAI-compatible server, such as llama.cpp's `llama-server`
  or vLLM. Use `"kind": "openai"` and its `/v1/chat/completions` URL; on the same machine that is
  `http://127.0.0.1:<port>/v1/chat/completions`. See
  [guides/local-models.md](guides/local-models.md) for a fully local setup with no hosted model.
- **Fallbacks** are what Gnomon switches to when the primary endpoint fails, for example on a
  rate limit.
- **Context window.** Gnomon 0.6.6 asks an endpoint for its own window. To cap one, set
  `max_context_tokens` on that endpoint. The top-level value is the fallback when nothing
  answers.

After a change, `rihmasto lanes` checks the routing, recompiles the analyst lane and shows the
pool. Products compiled earlier keep the surface they were built with: `rihmasto resurface
<project>` recompiles one, recorded as a kernel commit.

## 6. A first real project

Start at the `explore` maturity. It lands on the built-in local preview road, so no paved road
needs configuring.

```bash
rihmasto new "Equipment loans" --profile auto --mode mixed --maturity explore \
    --requested-by "<your name>" \
    --source "Our team keeps losing track of who borrowed the drills and laptops."
```

- **`--profile auto`** proposes the kind of work from the request, by rule (here a web service).
  Name one to choose it yourself: see [guides/profiles.md](guides/profiles.md).
- **`--mode`**: `socratic` sends every question to a person, `assume` lets the factory assume
  each answer with a due date, `mixed` asks only the blocking ones.
- **`--maturity`**: `explore`, `demo`, `pilot` or `production` decides which stages run, which
  gates apply and where the result lands.
- **`--source`** also takes a path: a markdown file, or a folder. From a folder the panel reads
  its `specs/*/spec.md` and `plan.md` files when it has them, and otherwise its README, spec and
  brief files and up to six `docs/*.md` files. `--source-file` reads the request's text from a
  file.

The panel runs at once (this needs Gnomon and the analyst's model). The command prints the
project id and the questions it asked. Answer them in the cockpit (section 7) or on the command
line:

```bash
rihmasto status
rihmasto answer <project> Q-001 "the team lead approves" --person "<your name>" --persona business_owner
rihmasto assume <project> Q-002 --person "<your name>" --persona business_owner
```

Then let it run until a person is needed:

```bash
rihmasto run <project>
```

`run` writes the spec, compiles the contract, authors the holdouts, builds each task in a cell,
judges it at the gate, and delivers. It stops at each card a person must decide and says which.
Decide it in the cockpit's **Inbox**, or on the command line, then run again:

```bash
rihmasto decide <project> <card> <verdict> --person "<your name>" --persona <persona> --reason "<why>"
```

`rihmasto status <project>` lists each open card with its id. `--reason` is optional, and it is
recorded with the decision. At `pilot` and `production`, nothing is built until a person approves
the plan.

Feedback goes back through the change loop:

```bash
rihmasto change <project> "Adding an item with an empty name crashes" --person "<your name>" --persona end_user
rihmasto apply <project> <card>   # after triage, and after a business decision where one is needed
```

## 7. The cockpit

```bash
rihmasto-cockpit
```

Without `--home`, the cockpit and the command line use the same factory home: `$RIHMASTO_HOME`,
else `$RIHMA_HOME` or `$GNOMONFACTORY_HOME` (earlier names, still honoured), else `var/` in the
checkout. The server listens on 127.0.0.1 only and prints one link:

```text
Open this link once to sign in: http://127.0.0.1:8787/#k=<one-use code>
```

- **Sign in.** Open the link once. The page exchanges the code for a session token and keeps it
  in that tab. **Open in another browser tab**, in the person menu, makes a new one-use link.
- **Pick a persona.** The persona decides which cards you may decide; the kernel checks it on every
  decision. It is not a login: the cockpit is for one operator.
- **Questions.** Pick an option or write your own, then **Answer**. Or press **Let Rihma assume**
  to turn the panel's proposal into an assumption with a due date.
- **Inbox.** Every card that waits on your persona: approvals, escalations, deploy gates, concepts,
  updates.
- **Ask Rihma** (or the `/` key) opens the assistant. It answers from the records and proposes
  actions; you confirm each one, and it writes nothing itself.
- **From another machine,** open an SSH tunnel to the same port
  (`ssh -L 8787:127.0.0.1:8787 <host>`), then open the link. Use `127.0.0.1`, not `localhost`.

Options: `--home DIR`, `--port N` (default 8787), `--assistant map|gnomon`, `--embed-base URL`.
[cockpit.md](cockpit.md) describes every view, the lenses and the JSON API.

## 8. An existing solution, or your own terminal

Not every project starts from a need. To bring a solution that already exists, adopt its
repository with what you mean to do with it:

```bash
rihmasto adopt "Legacy loans" --source ../legacy-loans --intent maintain \
    --person "<your name>" --persona developer
rihmasto sync <project>           # fetch the upstream again and record what changed since adoption
```

- `--intent` is `monitor` (probe where it runs: add `--base-url`), `maintain` or `improve`.
- `--source` is a local path, or a URL git can clone without credentials. Clone a private
  repository yourself and adopt the local path.
- Rihmasto records an inventory by rule and runs a detected Python suite once. Its results are
  the **existing behaviour, not a spec**: a suite that already fails is recorded as failing. A
  toolchain the kernel does not run is "not measured".
- The upstream is fetch-only. `sync` never moves the project's main: it opens a change card when
  the upstream moved, and a person decides.

To work by hand, open a workspace: a branch of your own with the project's context and Rihmasto's
MCP server set up for your agent (Gnomon, Claude Code, OpenCode or a plain shell):

```bash
rihmasto workspace open <project> --person "<your name>" --persona developer --agent claude
rihmasto workspace submit <project> <workspace path> --person "<your name>" --persona developer --task T-003
rihmasto workspace list <project>
```

`open` prints the command that opens your terminal there; it launches nothing itself. `submit`
makes you a cell: your commits meet the same gate (tests, trace, fail-first for the task, the
verifier), then merge or escalate. [brownfield.md](brownfield.md) has the details, the security
gate for SARIF findings, and the limits.

## 9. The capability layer from the command line

Every capability feature has a command. Each one prints JSON, and each write is signed with
`--person` and `--persona`. When the kernel refuses (a persona that may not, a reason left empty,
an unknown id), the command prints why and exits 2.

```bash
rihmasto security ingest <project> scan.sarif --person "<your name>" --persona it
rihmasto security status <project>
rihmasto security accept <project> SEC-1-1 --reason "a fixed command, no user input" --expires 2027-06-30 \
    --person "<your name>" --persona it
rihmasto pack <project> --yaml                    # the latest release's capability pack, readable
rihmasto evidence <project> --out exports --person "<your name>" --persona compliance
rihmasto autonomy show
rihmasto signal log --text "The loans page should show overdue items first" --channel chat \
    --source "team chat" --person "<your name>" --persona operations
rihmasto signal triage S-001
rihmasto square
rihmasto catalogue
```

| Feature | Commands | Guide |
|---|---|---|
| Security findings | `security ingest`, `security status`, `security accept` | [brownfield.md](brownfield.md#security-findings-from-any-scanner) |
| Capability and evidence packs | `pack`, `evidence` | [guides/packs-and-evidence.md](guides/packs-and-evidence.md) |
| Embeds | `embed create`, `embed list`, `embed revoke` | [guides/embeds.md](guides/embeds.md) |
| The autonomy cap | `autonomy show`, `autonomy set` | [guides/autonomy.md](guides/autonomy.md) |
| Signals and concepts | `signal log`, `signal list`, `signal triage`, `concept edit`, `concept apply` | [guides/signals-and-concepts.md](guides/signals-and-concepts.md) |
| Observations and updates | `observe`, `updates apply` | [guides/signals-and-concepts.md](guides/signals-and-concepts.md#observations-and-the-updates-inbox) |
| The square and the catalogue | `square`, `catalogue` | [cockpit.md](cockpit.md#the-delivery-square) |

`rihmasto <command> --help` lists each command's options.

## 10. Where things are kept

| What | Where |
|---|---|
| The factory home | `--home`, else `$RIHMASTO_HOME`, else `$RIHMA_HOME`, else `$GNOMONFACTORY_HOME`, else `var/` in the checkout. Not committed. |
| A project | `<home>/projects/<id>/`: `project.json`, `canon/` (brief, questions, assumptions, decisions, Inbox cards), `spec.json`, `contract.json`, `checkplan.json`, `tasks.json`, `repo.git` (the product), `releases/`, `ops/`, `ledger.jsonl` |
| The factory's own canon | `<home>/projects/_factory/`: concepts, signals, observations, the autonomy policy, embeds |
| Holdouts | `<home>/holdouts/<id>/`: outside the project folder and every lane. Builders never see them. |
| Paved roads | `<home>/paved_roads.json`, written by IT ([guides/deploying.md](guides/deploying.md)) |
| Lanes | `$GF_LANES`, else `<home>/lanes` for a demo home (or one with a `.lanes-here` file), else `~/gf-lanes` (the cockpit warns when two homes share it): `analyst/` for intake and spec, `lane-1` to `lane-3` for cells (`GF_LANES_SIZE` sets the pool) |
| Workspaces | `<lanes root>/workspaces/<id>/<person>-<n>`, on the branch `work/<person>/<n>` |
| Security findings | `<home>/projects/<id>/security/<n>.json`, one per ingested SARIF scan |
| Cockpit state | `<home>/cockpit/heads.json` (the last ledger head it verified), `<home>/_cockpit/` (layouts and evidence exports), `<home>/jobs/` (logs of Advance and New project) |
| Model routing and prices | [kernel/routing.json](../kernel/routing.json) with your `kernel/routing.local.json` merged over it (gitignored), [kernel/prices.json](../kernel/prices.json) |

Secrets are never kept in any of these. Keys stay in environment variables, and deploy packages
carry references to secrets, never their values.

## 11. Troubleshooting

**`rihmasto doctor` exits 1.** Gnomon is missing, older than 0.6.5, or printed a version Rihmasto
cannot read. Install or upgrade it, or set `GNOMON_CMD` to the command that runs it.

**"apparatus failure".** The harness or the provider failed, not the work: an endpoint error, a
rate limit, a context overflow, or Gnomon not starting. Gnomon reports these as exit codes 10 to
13. A cell is retried with growing pauses before anyone is asked. An apparatus failure never
counts against a task or a model. A pipeline stopped by one keeps what it recorded; run it again
when the endpoint answers.

**"not measured".** A check that could not run, or a number with nothing behind it. It is an
honest state, not a pass and not a fail. You will see it when:
- the verifier gave no usable answer;
- a suite ran no tests;
- a criterion has no evidence yet;
- a model is missing from [kernel/prices.json](../kernel/prices.json), so its cost is unknown;
- a forecast has no merged task to rest on.

Fix the cause. Do not read it as zero.

**The spec stops with a send-back list.** Blocking questions are still open. Answer them, or let
Rihma assume them, then run again.

**A task escalated.** It did not pass its gate after two repair rounds. The card keeps every
objection. Decide **retry**, **accept as is** (it merges with you as the permission, marked not
warranted) or **stop**.

**A `road` card for IT.** The maturity needs an environment with no configured paved road. IT
configures it in `paved_roads.json`, then decides the card `configured`.

**The cockpit refuses the page.** Use `127.0.0.1`, not `localhost`. Through an SSH tunnel, use
the same local port as the server's. A sign-in link works once; **Open in another browser tab** makes
another.

**A Gnomon cell is clamped.** An untrusted surface that grants more than Gnomon's defaults runs
clamped. Product lanes grant nothing extra, so they need no trust. Trusting a surface
(`gnomon trust grant`) is the owner's act, never an agent's.

**`rihmasto demo` refuses a folder.** It only writes into an empty folder or an earlier demo home.
Choose another `--home`.

**"Filename too long" on Windows.** A project's repository lives at
`<home>/projects/<id>/repo.git`, and git writes files up to about 140 characters below the home.
Windows limits a path to 260 characters, so a factory home in a deep folder fails with this
error. Keep the home's path under about 120 characters, for example by cloning near the root of a
drive or by passing a short `--home`.
