---
id: D-0016
decided_by: owner
decided_on: 2026-11-23
kind: architecture
---

# Access goes through the organisation's own identity

The owner (2026-11-23), approving access control phase A: "Yes sounds good".

Until now a signer was a typed name: the cockpit had one operator session, the person and the persona
came from the request, the command line took `--person` and `--persona`, and anyone holding the session
could sign as any persona. The card-kind rules (`kernel/canon.py` `CARD_DECIDERS`) said which personas
may decide which card, but not who may act as a persona.

**What this means:**
- Rihmasto never stores passwords. People sign in through the organisation's identity provider (OIDC) at
  an identity-aware proxy that IT runs in front of the cockpit. The cockpit stays on 127.0.0.1, with the
  proxy beside it.
- The signer is the verified identity: the issuer and subject the proxy vouches for, or
  `local:<os user>` for the command line and the MCP server on the operator's own machine. The person
  recorded with a decision is that identity's display name, and the identity is recorded beside it.
- An access map that IT owns binds identities and groups to personas per scope: all projects, or named
  projects. It lives in the factory home, in a folder of its own that only IT writes
  (`projects/_factory/access/access.json`, schema `rihmasto.access/1`).
  Without it Rihmasto runs as a single operator's tool, as before, and says so plainly.
- The kernel refuses a decision whose persona is not granted to the signing identity on that project.
  An access file that cannot be read or checked refuses every decision (fail closed). Each change to the
  file is recorded in the factory ledger with its sha256 and who changed it: what the file claims, and
  its owner as the file system records it.
- The card-kind rules stay: a persona granted on a project still decides only the cards its kind allows.
- Machine identity for roads and lanes stays with Gnomon (D-0015).

**Next phases:**
- SCIM 2.0 provisioning, so joiners get their personas and leavers lose them, and a leaver's open
  cards are re-routed.
- Separation of duties: for example, the person who asked for a change may not also accept it.

How it works and how IT sets it up: [docs/guides/access.md](../docs/guides/access.md).
