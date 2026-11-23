---
id: D-0013
decided_by: owner
decided_on: 2026-11-23
kind: name
supersedes: D-0010
---

# The factory is called Rihmasto

The owner named the AI factory **Rihmasto**, Finnish for a mycelium: the whole network of hyphae
(D-0010 named a single one, *rihma*). The factory is the network, not one thread. It connects
needs from the operation, concepts, builds, users' feedback and running capabilities, and keeps
them alive and growing.

**Rihmasto and Rihma.** The two words follow the biology (the owner, 2026-11-23):
- **Rihmasto** is the whole system: the platform, the factory, the network.
- **Rihma** is one thread in it: a single agent. The cockpit's chat assistant is *Rihma* ("Ask Rihma"),
  and the factory's agent roles (analyst, builder, verifier, holdout author, ops agents) are *Rihma
  agents*.

**What changes, and when.** The rename is carried out as one step after the open parallel work has
merged, so it does not collide with it:
- the product name becomes Rihmasto in the README, the docs, the cockpit and the CLI's help;
- the command becomes `rihmasto`, and `rihma` stays as an alias;
- the factory home variable becomes `RIHMASTO_HOME`, and `RIHMA_HOME` and `GNOMONFACTORY_HOME` are
  still honoured;
- file formats keep their ids (`gnomonfactory.*`, `rihma.capability-pack.v1`, `rihma.event/1`), and
  decision records keep the names they were written with, because they are history.

**Name check.** It is still to be done before public use, exactly as D-0010 asked for Rihma: the
exact word in the PRH trade register and the EUIPO database, and the GitHub organisation or
repository name.

**Carried out in the command line (2026-11-23).** The distribution is `rihmasto`, and its commands are
`rihmasto`, `rihmasto-cockpit`, `rihmasto-embed` and `rihmasto-mcp`; `rihma`, `rihma-cockpit`,
`rihma-embed` and `rihma-mcp` are aliases of the same entry points. The factory home is read from
`RIHMASTO_HOME`, then `RIHMA_HOME`, then `GNOMONFACTORY_HOME`. Two things keep their names on
purpose, because they are wire formats rather than product names: the Python packages (`kernel`,
`adapters`, `cockpit`, `embed`, `mcp`), which other code imports, and the schema ids (`rihma.*`,
`gnomonfactory.*`), which files and other tools already carry. Renaming either would break what
was written before, for no gain to anyone using Rihmasto.
