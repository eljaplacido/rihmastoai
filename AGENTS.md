# AGENTS.md — Working in Rihmasto

Rihmasto is a spec-first software governance and delivery platform written in standard-library Python with a browser cockpit and MCP server.

## Repository layout

- `kernel/` — Core state, ledger, contracts, alignment, assessment, teams, asks, reachability doctor, WIP tracking, Gnomon posture, and CLI (`python -m kernel.cli`).
- `cockpit/` — Loopback HTTP server (`cockpit/server.py`, `*_routes.py`) and static HTML/CSS/JS frontend (`cockpit/static/`).
- `mcp/` — Stdio MCP server (`mcp/server.py`, `mcp/bridge_tools.py`) exposing read-only and proposal-only tools to coding agents.
- `embed/` & `gateway/` — Embeddable widget server and HTTP gateway.
- `adapters/` — Harness and repository adapters.
- `contract/contract.json` & `spec.md` — Canonical specification and acceptance criteria (`FR-*`, `AC-*`).
- `tools/` — Contract validation, trace checking, quality gate, release export scrubber, and sharded CI runner.
- `docs/` — Architecture, cockpit, MCP, deployment, and workflow guides.
- `tests/` — Unit, integration, and headless-Chrome UI tests.

## Engineering rules

1. **Standard library only at runtime**: Do not introduce third-party runtime imports into `kernel/`, `cockpit/`, `mcp/`, `embed/`, `gateway/`, or `adapters/`.
2. **Spec-first & contract-traced**: Every behavior change maps to requirements and acceptance criteria in `contract/contract.json`. Do not modify `contract/contract.json` or `.gnomon/` without explicit owner approval.
3. **LF line endings and module limits**: Keep all files on LF (`\n`). Keep new Python modules at or under 500 lines, keep functions under 60 lines and complexity under 15, and annotate all new public functions.
4. **Never loosen baselines**: Do not weaken `tools/quality_baseline.json` to make the gate pass.
5. **Human-in-the-loop boundary**: Agents may read state and file proposals or answers to asks, never silently approve gates, change autonomy caps, or grant Gnomon trust.
6. **Public repository hygiene**: Never commit personal paths, local machine names, credentials, tokens, or private customer references.

## Verification commands

Run these before proposing a pull request:

```bash
# 1. Validate contract structure and test traceability
python tools/contract_check.py contract/contract.json
python tools/contract_trace.py contract/contract.json

# 2. Run the quality gate (set RIHMA_QA_PYTHON to a Python with ruff and mypy installed)
python tools/quality.py --gate

# 3. Check public release export hygiene
python tools/release_export.py --check --no-denylist

# 4. Run targeted tests while iterating
python -m unittest tests.<module> -v

# 5. Run the full suite (use the sharded runner on Windows; never run two Chrome suites at once)
python tools/ci_run.py --shards 3
```
