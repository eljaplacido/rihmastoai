# Governance

This page says who maintains Rihmasto, how decisions are made and recorded, and how someone becomes
a maintainer.

## Maintainers

| Maintainer | GitHub | Role |
|---|---|---|
| The project owner | [@eljaplacido](https://github.com/eljaplacido) | Lead maintainer |

Maintainers review and merge pull requests, triage issues, handle security and conduct reports,
cut releases, and keep the decision records. [docs/maintainers.md](docs/maintainers.md) gives the
release and sync procedure.

The lead maintainer also decides what the project promises and how it is built: the contract, the
architecture, the name, the licence and the dependencies. Trusting a Gnomon surface
(`gnomon trust grant`) for this repository is the lead maintainer's act, never a contributor's or
an agent's.

## How decisions are made

- **Everyday changes.** A bug fix, a clearer message or a new test inside an existing criterion
  merges when a maintainer has reviewed it and the checks pass ([CONTRIBUTING.md](CONTRIBUTING.md)).
- **Changes to what Rihmasto promises.** A new or changed requirement is a contract amendment. It
  is proposed in an issue or a pull request, and becomes a new contract revision only when the lead
  maintainer approves it.
- **Architecture, naming, licence and dependencies.** These are discussed in an issue and decided
  by the lead maintainer.
- **Disagreement.** Maintainers look for agreement in the issue or pull request. When they cannot
  agree, the lead maintainer decides and records why.

## How decisions are recorded

Every decision that changes what the project promises or how it is built is written down in
[decisions/](decisions/):

- `D-0001-...md` and up: one file per decision. Each starts with front matter (`id`, `decided_by`,
  `decided_on`, `kind`) and says what was decided, why, and on what evidence.
- [decisions/amendments/](decisions/amendments/): contract amendments (`A-0001` and up).
- [decisions/proposed/](decisions/proposed/): proposals that wait for a decision (`P-0001` and up).

A record is never rewritten. A later decision supersedes it and says so, as
[D-0013](decisions/D-0013-name-rihmasto.md) supersedes D-0010.

## Becoming a maintainer

A contributor becomes a maintainer after a sustained record of good work: merged pull requests that
follow the spec-first way of working, careful reviews of other people's changes, and conduct in line
with the [code of conduct](CODE_OF_CONDUCT.md).

1. A maintainer nominates the contributor in an issue, or the contributor asks there.
2. The maintainers discuss it in the open.
3. The lead maintainer decides, records it in `decisions/`, and adds the new maintainer to the
   table above.

A maintainer who steps away is thanked and removed from the table. A maintainer may also be removed
for breaking the code of conduct; that too is recorded.

## Changing this page

Changes to this page go through a pull request that the lead maintainer approves, and are recorded
as a decision.
