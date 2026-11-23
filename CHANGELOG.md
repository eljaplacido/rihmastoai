# Changelog

Every notable change to Rihmasto is recorded here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[PEP 440](https://peps.python.org/pep-0440/): `1.0.0.dev0` is a development release before 1.0.0.

## [Unreleased]

### Added

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
