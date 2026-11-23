---
id: D-0012
decided_by: operator session, under the owner's instruction to test the chain end to end with different inputs
decided_on: 2026-11-22
kind: paved road (test environment)
---

# A test paved road on the GPU box: Docker on loopback; Azure listed but not configured

A paved road is IT's to configure (FR-Q1, FR-Q5). The v1 tests need one, and no customer IT
exists here. So the operator configures a test road in `~/gf-home/paved_roads.json` on the
GPU box, marked as a test road:

- **Docker on the GPU box** (a road named after the host): the factory's products run as
  Docker containers there, published on 127.0.0.1 only, on free ports. That keeps clear of the
  llama-server on 18080 and the cockpit on 8787. It serves the demo, staging and production
  environments. "Production" here means the self-hosted production environment of a test
  product, not a real service.
- **azure-prod:** listed with `configured: false`, so the factory renders and validates the
  Azure package and opens a road card for IT, without deploying. No Azure identity or `az`
  CLI exists here (D-0010 notes, docs/paved-roads.md).

Every decision on a test product's Inbox cards is made by clearly named test personas
(`test-business`, `test-it`, `test-user`, and so on), never in the owner's name.
