# Changelog

Every notable change to Rihmasto is recorded here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[PEP 440](https://peps.python.org/pep-0440/): `1.0.0.dev0` is a development release before 1.0.0.

## [Unreleased]

### Added

- **Change anything, go back a step, never get stuck** (FR-CHG1): a project's kind of work, mode,
  maturity and title change after it was made, with a preview of what the change means for the
  questions, spec and plan already done (`project_changed` in the ledger, before and after); a project
  goes back to its material, questions, spec or plan so that step runs again, with what it sets aside
  kept under `superseded/` and open questions withdrawn with the reason (never past a release); material
  is added later, and re-intake asks only about what is new; What's next on the overview, and
  `rihmasto next`, say what a project waits for, who can act, and the actions that move it on. Commands
  `rihmasto settings`, `rewind`, `material add` and `next`; the cockpit's Project settings dialog
  ([guide](docs/guides/change-anything.md)). An intake run again never asks a settled question again.
- **Shape it in chat** (D-0022, FR-SHP1): open a conversation with Rihma (the analyst role) with
  nothing, a sentence, a file (text, Markdown or Word) or a folder, and work out the need: Rihma asks
  one or two questions at a time and keeps a draft brief beside the chat that you can edit (a field you
  edited stays yours), and says when it is good enough. **Create the project from this** asks for the
  work profile, mode and maturity with Rihma's suggestion; the draft becomes the project's request, so
  intake never asks again what it says. Conversations are kept under `_shape/`, signed in the factory's
  ledger, and resume later. With no model set up, the chat says so and links to Models setup. In the
  cockpit from Home and New project, and as `rihmasto shape` (interactive, or
  `start|say|attach|edit|show|create`) ([guide](docs/guides/shape-in-chat.md)).
- **Models setup** (FR-MDL1): Settings > Models and `rihmasto models list|presets|test|set|remove`
  show each role's model, endpoint host, local or hosted, key state and readiness, and set a role to
  any OpenAI-compatible endpoint (presets for llama.cpp, Ollama, vLLM, OpenCode Go and hosted
  providers) in this machine's `kernel/routing.local.json`. A key is given as an environment
  variable's name or stored outside the repository, handed to Gnomon in its variable, and never shown,
  logged or put in the ledger. **Test** sends a tiny prompt and says the latency or the error. Home
  shows a **Set up a model** card while no model answers ([guide](docs/guides/models-setup.md)).
- **Releases** (FR-REL1): pushing a version tag such as `v1.0.0` runs the suite and the contract again,
  then builds the source archives, a CycloneDX SBOM and `SHA256SUMS`, signs a build provenance
  attestation and publishes a GitHub Release whose notes are the version's changelog section. A tag
  that is not `pyproject.toml`'s version, or a version with no changelog section, publishes nothing.
  "Run workflow" rehearses without publishing ([docs/maintainers.md](docs/maintainers.md)). CI uses
  `actions/checkout` and `actions/setup-python` v7.
- **Any folder as material** (FR-MAT1): intake scans whatever a folder holds instead of expecting
  certain file names. Word, PowerPoint, Excel, OpenDocument, HTML, CSV, JSON, YAML, TOML, PDF (partly
  read), logs (first and last lines) and code (an inventory, never its text) are read by rule; every file
  is read, summarised, listed or skipped with why, secret-looking files are never read, and a budget
  reads the most telling first and says what it cut. `rihmasto scan <folder>` and the cockpit's **Scan
  the folder** step show the map before anything is sent; `new` with a folder needs `--yes`. A
  **confidential** project keeps every model call on loopback or private endpoints and refuses a hosted
  one, naming the role. **An existing project** may be any folder: one that is not a git repository is
  snapshotted into a baseline repository (the folder is never changed), and one with no code is offered
  as material for a new project ([inputs](docs/guides/inputs.md), [brownfield](docs/brownfield.md)).

- **Autopilot, delegation and staying on track** (D-0017): a person delegates named card kinds on a
  project, for at most seven days, to the factory's deterministic rules, and the pipeline decides those
  cards in their name with "by delegation" on record; an autopilot run lets Rihmasto run on its own,
  bound to a sandbox (local preview or roads marked sandbox, sandbox relay receivers, no connector
  writes), until a person stops it; Track says whether a project stays on track against its approved
  plan, with every figure's basis, human checkpoints that can hold the run, and a daily digest through
  the relay. Commands `rihmasto autopilot`, `delegation`, `track` and `tracking`; the cockpit's Track
  view, pill and Home widget; the MCP reads `rihma_track` and `rihma_autopilot`
  ([guide](docs/guides/autopilot-and-tracking.md)). A pass under way when a person stops the autopilot
  stays in the sandbox (it delivers nothing and ends at its next safe point), the daily digest leaves a
  held project out for receivers outside the sandbox, and a project header shows one on-track answer.
- **Outputs per audience** ([docs/guides/outputs.md](docs/guides/outputs.md)): a person chooses what
  a project delivers, at intake or later, and the kernel builds each output from the records and the
  release, the same records giving the same bytes: a web app with the paved road's sign-in, a
  container with compose, an OpenAPI 3.1 description, a plain delivery report, the evidence pack and
  the source as a git bundle. `rihmasto output`, and the cockpit's **Outputs** view. The MCP server
  output is planned, through a hook to the small-capability faces. Outputs chosen with the request
  are told to intake and never asked again; the source's README runs as written outside any
  repository; the sign-in's checks catch session fixation; a sign-in added later runs unprivileged;
  and a factory check the sign-in turns away is recorded as not measured, never failed or passed.
- **Use only what you need.** Rihmasto is a catalogue of modules with presets (spec only, gate my code,
  assess only, security only, evidence only, capability only, the full factory), chosen per factory
  and per project by a named person and recorded in the ledger: `rihmasto modules show|set|presets`,
  Settings, Modules in the cockpit, and a first-run choice on a new factory home. A module that is off
  is refused where it acts, on the command line, in the cockpit, in the MCP server's write tools, in
  a website's chat and at the webhook server, is hidden where it shows and is not proposed by the
  assistant; a safety switch (revoking a chat, removing a webhook source, ending a subscription,
  disabling a connector) stays open whatever is on. An attached repository's tests run only through IT's isolation runner while
  access is enforced. A repository of your own is attached with
  `rihmasto repo attach` and judged by the gate (`repo gate`), scanned (`repo scan`) and its releases
  recorded for evidence (`repo releases`); `rihmasto contract export` ends spec only in files
  ([docs/guides/use-only-what-you-need.md](docs/guides/use-only-what-you-need.md)).

- **Small capabilities** ([docs/guides/small-capabilities.md](docs/guides/small-capabilities.md)): the
  `automation` profile and its capability template, a runtime declaration (`app/runtime.json`) judged
  at the gate and carried in the pack with secrets by name, one image whose faces (MCP over stdio and
  Streamable HTTP, an OpenAI-compatible chat also routed by the gateway, a website embed, HTTP) answer
  only after the pack guard has checked the pack, verified webhook and relay triggers, a schedule,
  results out as signed events, `rihmasto capability check` and `serve`, and the faces in
  `compose.yaml`. A face the declaration does not name stays shut on every transport, MCP's stdio
  included, and the openai face reports its token usage as not measured (the gateway's audit too),
  never as zeros.
- **Postures and priority weights** ([docs/guides/postures.md](docs/guides/postures.md)): prototype,
  balanced, production or regulated, tuned by ux, security, compliance, speed and cost, previewed
  before anyone chooses, recorded with who chose it, and changed during the run with what it changes
  now and later (`rihmasto posture`, New project's **How it runs**, where *No posture* is chosen
  until a person picks one, for a need and for an adopted project, and the **Posture** chip in the
  header and in Project settings, whose maturity and mode changes keep to the posture).
- **Brownfield assessment** ([docs/brownfield.md](docs/brownfield.md#assessing-an-adopted-system)):
  `rihmasto assess` and the cockpit's **Assessment** view judge an adopted system from every
  perspective by rule, versioned, with the panel's review apart, and file chosen findings as changes.
- **Access with the identity provider's signed token** ([docs/guides/access.md](docs/guides/access.md)):
  the cockpit verifies the provider's token (RS256 or ES256) and holds no shared secret; with access
  enforced, untrusted code (a suite, an adopted suite, a product, a Gnomon cell) runs only through
  IT's isolation runner, and the cockpit refuses to start a job that would need one it lacks.
- **Data integrations** ([docs/guides/data-integrations.md](docs/guides/data-integrations.md)): a
  product declares the databases, warehouses, cloud storage and business APIs it reaches, IT approves
  each binding, delivery wires it in by name, and the gate tests it on stand-ins.
- **The acceptance matrix** ([docs/acceptance.md](docs/acceptance.md)): every need, mode, maturity and
  access column with its offline cells in `tests/acceptance`, and the live acid-test plan.
- **Pull requests only.** `main` changes only through pull requests that pass the four CI jobs and
  the new DCO sign-off check, with a code owner's review, squash-merged
  ([CONTRIBUTING.md](CONTRIBUTING.md#how-changes-reach-main)).
- **The DCO sign-off check:** [tools/dco_check.py](tools/dco_check.py), run on every pull request by
  [.github/workflows/dco.yml](.github/workflows/dco.yml). It lists each commit without its author's
  sign-off and says how to fix it from the commit the branch starts from. The owner's and
  Dependabot's exemptions hold only in pull requests their own accounts opened, and a commit whose
  text holds a control character is still checked.
- **CODEOWNERS** and **Dependabot** for the GitHub Actions the workflows use (Rihmasto has no package
  dependencies).
- **The two-way sync:** [tools/release_sync.py](tools/release_sync.py) sends each snapshot of the
  maintainers' development repository here as a pull request, and brings merged contributions back
  with their authors and merged messages. A contribution comes in as the three-way merge of its
  change, so a change that is there already is never applied twice. The import refuses a path the
  release leaves out (in any case), a path that differs only in case, a merge commit, and a change
  to the exclude list, the release tools or a `.gitignore` that a maintainer has not read, or that
  would let a private or ignored file out. A copied export trailer never skips an import, and an
  export never reverts one. [docs/maintainers.md](docs/maintainers.md) gives the procedure and the
  repository's settings.
- This changelog.

### Changed

- Questions go to GitHub Discussions; security reports go to private vulnerability reporting, at
  the repository's security advisories ([SECURITY.md](SECURITY.md)).
- The release export's exclude list matches paths in any case, so a left-out folder spelled
  otherwise on a disk that ignores case stays out too.

### Fixed

Found by walking the owner's journeys in a real cockpit with a local model:

- New project no longer assumes a web app: **Let Rihma choose** is the default, and the intake proposes
  the kind of work by rule from the need or the folder.
- A project made from a folder, or adopted, opens its Project settings again (they read "unreadable"), and
  material added to it is kept beside the folder's map instead of failing.
- Material read with re-intake no longer goes on to build on the spec written before it; nothing is built
  past an open blocking question (FR-CHG1-AC-10).
- What's next drops a run's result from before a person went back a step, changed a setting or added
  material; says when the autonomy cap stops the build, on the command line too; opens Models setup for
  any persona when a model did not answer; names the command for every action; and offers an improved
  adopted project's next steps.
- The Jobs page opens the project an adoption made; the first-run name shows at once in the person menu;
  Ask Rihma no longer flags a cockpit view or control it cites as "not found"; a confidential refusal and
  Models setup say how to drop a hosted fallback; `rihmasto settings` and `rewind` previews need no signer.

## [1.0.0.dev0] - 2026-11-23

The first public release: a development snapshot. Commands, file formats and the cockpit's API may
still change before 1.0.0. It covers the first public snapshot and what was published the same day:
the fixes below and Rihmasto's own red team.

### Added

- **The chain from a need to a running service:** an intake panel whose perspectives ask the
  questions that change what gets built; specs with given / when / then criteria and their
  provenance; a contract compiled with no model and pinned by its hash; Gnomon builder cells; a gate
  that runs the tests itself, checks that they fail first, keeps holdout scenarios in custody and
  asks an independent verifier; delivery on paved roads; and a change loop.
- **The cockpit:** one Inbox for the decisions that are people's, lenses per persona, and Rihma
  agents ("Ask Rihma"), behind a one-use sign-in on 127.0.0.1.
- **The capability layer:** capability packs, evidence packs with a chain check, and the autonomy
  ladder with its cap.
- **Signals and concepts, website chats (embeds), the security gate** for SARIF findings with
  accepted risks that expire, and **the MCP server** for a developer's own coding agent (reads and
  proposals, never decisions).
- **Seven work profiles:** `web_service` and `integration` ready, five in preview.
- **`rihmasto demo`**, a demo factory with no keys, no network and no Gnomon, and a 15-minute tour
  by role ([docs/demo.md](docs/demo.md)): a website feedback chat, a stakeholder comment, a
  security scan with an accepted risk, an exported evidence pack, an autonomy cap and an adopted
  existing service.
- **Rihmasto's own red team** (`python -m kernel.redteam`, [docs/guides/security.md](docs/guides/security.md)):
  static checks of Python, JavaScript and HTML, Dockerfiles, GitHub Actions and secrets, each rule
  with a CWE and an OWASP Top 10 2025 id, a seeded example it must catch and a clean twin it must
  stay silent on, and SARIF into the security gate; dynamic probes only of a service the factory
  deployed itself, on loopback, under a written scope an IT or compliance person grants for at most
  31 days; and agentic checks of Rihma agents and website chats against injection and leaks, scored
  by canaries. A layer that could not run is not measured, never passed. The bypasses independent
  attacks found are seeded cases it now catches, or limits the guide documents.
- **The Rihmasto logo:** the README banner, the cockpit's corner mark and its tab icon.
- **The project's rules:** the contributing guide, the code of conduct (Contributor Covenant 2.1),
  governance, the security policy, issue and pull request templates, and CI on Ubuntu and Windows
  with Python 3.11 and 3.12. Apache License 2.0.

### Fixed

- The tests hold on Python 3.11 and 3.12: deep JSON is refused at parsing, and a run with no test
  exits 0.
- A decision made before a workspace merged a task never undoes the merge.
- A capability pack keeps the criteria its release had; a malformed ledger line no longer stops an
  evidence export.
- A developer's label on a change, on an adopted solution too, waits for the business decision it
  needs; withdrawn holdouts never run.
- Cockpit Home: Customize keeps one lens and the keyboard focus, the pipeline reads at every size,
  nothing unmeasured shows as zero, and a read error shows as an error. The square, the catalogue,
  the Inbox and the settings have the fixes from a UI audit, each checked in a real browser.
- The routing overlay, the home variables, the install docs and the release export's checks; the
  release scan reads a private key as a header with key material after it.
- The browser driver waits through a page that is still navigating, so a slow machine is not a
  failure.
- The Gnomon surface's comments and the contract's prose say Rihmasto, not the project's working
  name.
