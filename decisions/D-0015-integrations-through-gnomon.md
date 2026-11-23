---
id: D-0015
decided_by: owner
decided_on: 2026-11-23
kind: architecture
---

# Integrations run through Gnomon as governed tool calls

The owner (2026-11-23): "since we want to use Gnomon as engine and for governance layer, the Gnomon
approach would make sense".

**What this means:**
- Rihmasto reaches external systems (Jira, GitHub, Azure DevOps, Microsoft 365, Google Workspace,
  Slack, ServiceNow, cloud platforms, finance systems and the long tail) through Gnomon running those
  systems' MCP servers or API tools in a dedicated integration lane. Every external read and write is
  checked by Gnomon's policy, approved when it writes, and recorded in Gnomon's hash-chained audit trail,
  which Rihmasto ingests like any other Gnomon run.
- Rihmasto keeps only thin native pieces of its own: verified inbound webhooks that become signals or
  change proposals (never decisions), and outbound events from its ledgers (CloudEvents over Standard
  Webhooks). Long-tail systems come through any MCP server or the customer's iPaaS.
- Decisions stay with people in Rihmasto's Inbox. Chat and mail carry a deep link to the card; nothing
  external signs a decision.
- Credentials stay outside the repository, in Gnomon's credential store or the operating system's.
  Inbound content is untrusted data, never an instruction.
- What Gnomon does not yet support for this is fixed upstream in Gnomon, consistent with the
  independence rule (Gnomon is the single runtime dependency).
