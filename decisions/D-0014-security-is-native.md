---
id: D-0014
decided_by: owner
decided_on: 2026-11-23
kind: architecture
---

# Security scanning and red teaming are Rihmasto's own capability

The owner (2026-11-23): red teaming "cannot be dependent on that or any other repo, but it has to be a
capability of Rihmasto". The owner's other security project is separate and closed.

**What this means:**
- Rihmasto scans and red-teams with its own code: static checks of a product's source and
  configuration, secret scanning, dynamic tests against the factory's own running deployments, and
  agentic red teaming of LLM-facing surfaces (prompt injection, data exfiltration measured by canaries,
  tool abuse). Every check is proven by a seeded defect it must catch.
- Results are written as SARIF 2.1.0 and judged by the same security gate as any scan.
- Reading SARIF stays generic. Any scanner a team already uses can feed the gate, and none is required.
  External scanners found on PATH may be used as optional adapters, and say "not measured" when absent.
- The repository names no private project: no configuration files, fixtures, docs or code comments
  refer to one. Examples use well-known open-source scanners or a neutral example tool.
- Dynamic and agentic red teaming target only what the factory itself runs: its own environments and
  embeds, authorised per environment by IT or compliance, on addresses the factory deployed.

This is consistent with the independence rule (Gnomon is the single runtime dependency; earlier
projects are inspiration only).
