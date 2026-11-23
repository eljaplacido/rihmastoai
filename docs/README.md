# Rihmasto documentation

Every guide and reference page that ships with Rihmasto, grouped by who reads it. A page can sit
in more than one group. Pages marked *design* describe something planned; they say inside what is
built and what is not.

## Start here

- [The README](../README.md): what Rihmasto is, the quick start, and the project's status.
- [Getting started](getting-started.md): install, the demo, models and Gnomon, a first real
  project, the cockpit, where things are kept.
- [The demo](demo.md): what the demo factory holds, and what each persona sees in it.
- [How it works](how-it-works.md): the chain step by step, the delivery square, personas and
  lenses, and what Gnomon does beside the kernel.

## Business owners and product owners

- [Signals, concepts and updates](guides/signals-and-concepts.md): how needs and outside events
  arrive, and how a person decides what becomes work.
- [The autonomy ladder](guides/autonomy.md): how far the factory may go on its own, and who sets
  the cap.
- [Work profiles](guides/profiles.md): the kinds of work, and what each one asks.
- [The capability layer](capability-layer.md): what Rihmasto delivers, besides software, and who
  sees what.
- [The whole delivery](factory-overview.md) (*design*): the seven stages, the delivery square and
  the canon, from a business need to measured benefit.

## Developers

- [Existing solutions, your own terminal, security findings](brownfield.md): adopting a
  repository, workspaces for your own agent, and SARIF findings.
- [Security: Rihmasto checks what it builds](guides/security.md): its own static scan, dynamic
  probes and agentic red team, the scope a person authorises, and what they do not catch.
- [MCP](mcp.md): the MCP server for your own coding agent, with its tools, resources and safety
  boundary.
- [The cockpit](cockpit.md): every view, the lenses, the assistant and the JSON API.
- [Running fully local](guides/local-models.md): every role on your own hardware.
- [Recipes, sandbox trials, measured fit and offline bundles](guides/recipes-and-fit.md): reuse of
  proven capabilities, from Python.
- [Spec to verify](spec-to-verify.md) (*design*): how a requirement becomes something Gnomon
  enforces.
- [The v1 chain](v1-design.md) (*design*): the end-to-end chain as it was designed for v1.
- [Code quality](code-quality.md): the quality gate, its numbers, and what to fix.
- [Rihmasto against Gnomon v0.6.6](gnomon-0.6.6-audit.md): what changed in Gnomon 0.6.6 and how
  Rihmasto follows it.
- [Contributing](../CONTRIBUTING.md): set up, run the checks, and the spec-first way of working.

## IT and operations

- [Access](guides/access.md): who may decide as which persona. Single-operator and enforced modes,
  the access file, and setting up an identity-aware proxy (oauth2-proxy with Entra ID, Okta, Google
  or Keycloak; Google IAP; an AWS load balancer).
- [Deploying on paved roads](guides/deploying.md): the short version of how a product lands.
- [Paved roads](paved-roads.md): the full reference: configuring a road, what each maturity does,
  and what is real and what is not.
- [The capability gateway](guides/gateway.md): one OpenAI-compatible endpoint for a site's
  workloads, with fallbacks, quotas and an audit.
- [Embeds](guides/embeds.md): a website chat that files feedback or a need, and how it is
  protected.
- [Integrations](integrations.md) (*design*): connecting other systems through Gnomon as governed
  tool calls.
- [Events, doorbells and connectors](guides/integrations.md): signed events and notices out,
  verified webhooks in, and the connector model, as far as they are built.
- [Portability](portability.md) (*design, phase 1 built*): running a release anywhere, with its pins
  and evidence.
- [Security](../SECURITY.md): how to report a vulnerability, and the threat model in short.

## Compliance

- [Capability packs and evidence packs](guides/packs-and-evidence.md): what a release is, and the
  bundle a reviewer checks.
- [The autonomy ladder](guides/autonomy.md): the cap, who may set it, and how it is recorded.
- [Access](guides/access.md): how a decision is bound to a verified identity, and how each change
  to who may decide is recorded.
- [Security findings from any scanner](brownfield.md#security-findings-from-any-scanner): the
  security gate and accepted risks.
- [Decisions](../decisions/): every decision, who made it and why.

## Background and research

- [Knowledge graphs and ontologies](knowledge-graph.md) (*phase 1 built*): a read model over Rihmasto's
  own records, and the read-only `rihmasto graph` command.
- [Ideas for the road ahead](roadmap-ideas.md): ideas from research, and which are done.
- [Gnomon upstream issues](../upstream/gnomon-issues.md): what Rihmasto asked of Gnomon.
- [The first working spec](../specs/001-initial/spec.md): an early draft of the factory's own
  spec, kept as history; the contract is the current one.

## The project

- [Contributing](../CONTRIBUTING.md), [code of conduct](../CODE_OF_CONDUCT.md),
  [governance](../GOVERNANCE.md) and [security](../SECURITY.md).
- [The changelog](../CHANGELOG.md): what changed in each release.
- [Maintainers: releases and the two-way sync](maintainers.md): how a snapshot of the maintainers'
  development repository reaches `main`, and how merged contributions are brought back.
- [Licence](../LICENSE) (Apache-2.0) and [notice](../NOTICE).
- [The contract](../contract/contract.json): Rihmasto's own requirements, criteria and tasks.
- [Decisions](../decisions/), [amendments](../decisions/amendments/) and
  [proposals](../decisions/proposed/).
