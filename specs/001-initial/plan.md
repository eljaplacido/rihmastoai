# Implementation Plan — Gnomon Factory

## Architecture Overview

Gnomon Factory is a self-hosted, deterministic orchestration layer that manages autonomous software development agents via the Gnomon harness. It operates as a state machine driven by a hash-chained, append-only ledger, ensuring that all phase transitions and verdicts are reproducible and auditable. The system is strictly kernel-based, meaning it contains no AI models itself; instead, it coordinates local (Qwen3.6-35B) and cloud (DeepSeek-v4-pro) models through isolated Gnomon tasks, enforcing strict boundaries between agent proposals and deterministic governance rules.

## Technology Stack

| Technology | Purpose | Justification |
|---|---|---|
| Gnomon (v0.6.5) | Agent Harness and Execution Environment | The sole runtime dependency. Provides the sandboxed worktrees, role-based surfaces, and ACP streaming interface required for FR-C2 and FR-C4. Ensures agents operate within defined leases and scopes. |
| TypeScript (Node 22) | Kernel Implementation Language | Matches Gnomon's runtime environment. Allows for precise control over event loops and async streams required for the live progress streaming (FR-C4) and ledger updates. Facilitates the import-graph checks to ensure the kernel remains model-free (NFR-1). |
| SQLite (WAL Mode) | Ledger and State Storage | Provides the ACID guarantees and append-only integrity required for the hash-chained ledger (FR-L1). Its embedded nature supports the self-hosted, single-machine constraint (GPU box/WSL2) while allowing efficient projection views for the Cockpit (FR-M1). |
| React + D3.js | Cockpit Visualization | Required to implement the complex visual grammar (FR-M2) with nine distinct views (FR-M3). D3.js allows for the precise rendering of shapes, colors, and line styles that denote decision authority and assurance levels, while React manages the reactive state updates from the SSE stream. |
| OpenTelemetry | Observability Export | Standardizes event metadata for external monitoring without exposing prompt content (NFR-4). Allows the factory to export structured traces of runs, artifacts, and phase transitions for auditing and debugging. |

## Components

### Ledger Kernel
**Type:** Service
**Depends on:** SQLite, Gnomon CLI

The core deterministic engine. It appends transitions to the hash-chained ledger, enforces import-graph constraints (no models), and manages phase transitions based on evidence (FR-E2).

### Intake Compiler
**Type:** Service
**Depends on:** Ledger Kernel, Policy Repository

Validates closed intake contracts (FR-A1) and vague explanations (FR-A2). Compiles requirements into machine-readable contracts with provenance and acceptance criteria (FR-O1).

### Task Orchestrator
**Type:** Service
**Depends on:** Gnomon CLI, Ledger Kernel, Cloud Model API

Manages Gnomon envelopes (FR-C1), handles write leases (FR-F5), and streams live progress via ACP (FR-C4). It routes work to local or cloud models based on capacity and window size (FR-F7).

### Verifier Agent
**Type:** Service
**Depends on:** Gnomon CLI, Holdout Scenario Store

A specialized Gnomon role that runs holdout scenarios (FR-B4) and verifies acceptance criteria using the 'test must fail first' rule (FR-G2). It operates on a pinned build separate from the one it judges (FR-G6).

### Cockpit UI
**Type:** Frontend
**Depends on:** Ledger Kernel (SSE), Policy Repository

The operator interface providing nine views (FR-M3). It consumes the SSE stream from the Ledger Kernel and renders the visual grammar (FR-M2) for Inbox, Floor, Colony, etc.

### MCP Server
**Type:** Service
**Depends on:** Ledger Kernel

Exposes read-only state and proposal filing capabilities to other agents (FR-N3). It strictly prohibits approval actions, enforcing the human-in-the-loop sovereignty principle.

### Reflex Engine
**Type:** Service
**Depends on:** Ledger Kernel, Task Orchestrator

A model-free component that handles apparatus failures (FR-C6) and safe stop states (FR-J3). It executes pre-approved repairs like retrying with backoff or recalling stalled cells (FR-J2).

### Policy Repository
**Type:** Storage

A version-controlled store for human-written policies, price tables (FR-L4), and gate rules. It accepts writes only from human operators or signed decisions.

## Environments

| Environment | Description | Resources |
|---|---|---|
| Local Development (GPU box/WSL2) | The primary runtime environment. Runs the full factory stack including the local Qwen3.6-35B model. Used for daily operations, fire drills (FR-J4), and development. | Local NVIDIA GPU (GPU box or RTX 5090), Linux Kernel, Node 22, SQLite |
| Staging | An isolated environment for running holdout scenarios (FR-H3) and canary releases (FR-H4). It mirrors production data but uses separate builds and verifiers. | Local NVIDIA GPU (GPU box or RTX 5090), Isolated Worktrees, Cloud Model Access |
| Production | The live environment where the reconciler (FR-H5) maintains the approved state. It is the only environment where real user feedback (FR-I1) is ingested. | Local NVIDIA GPU (GPU box or RTX 5090), Production Data, Cloud Model Access |

## Infrastructure Requirements

- Linux OS (a GPU box, WSL2, or Containerized) for sandbox compliance.
- NVIDIA GPU (a GPU box or an RTX 5090) for local Qwen3.6-35B inference.
- Local file system with high IOPS for hash-chained ledger and worktrees.
- Network access to Cloud Model API (DeepSeek-v4-pro) for escalation.
- No cloud hosting for the factory kernel; self-hosted only.
- OpenTelemetry collector for event export.

## Security Architecture

Security is enforced through deterministic governance and strict isolation. The kernel contains no models, verified by an import-graph check. Agents operate in sandboxed Gnomon worktrees with no network access unless explicitly allowed by their role. Production credentials are never held by agents; they are injected only at runtime via Gnomon's secure mechanisms. The ledger is append-only and hash-chained, ensuring immutability. Human operators sign all decisions via the Inbox, which are then appended to the ledger. Secrets are never logged or included in prompts. The MCP server allows read-only access and proposal filing but strictly prohibits approvals, maintaining human sovereignty over irreversible actions.

## Deployment Strategy

The factory is deployed as a self-hosted application on the owner's hardware. It uses a canary release strategy for its own updates, judged by anytime-valid confidence sequences against declared harm margins (FR-H4). The kernel is updated only after paired evaluations and human promotion (FR-K3). Staging runs holdout scenarios before production release. The system is designed to be rebuilt and rechecked from the ledger and pinned revisions with the kernel absent (FR-H6), ensuring reproducibility.
