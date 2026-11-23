---
id: P-0014
status: proposed (the owner decides; the surface change and its trust are the owner's act)
proposed_on: 2026-11-23
kind: surface
---

# Widen the builder's write scope beyond M0, and accept pyproject.toml as a test configuration

## What Gnomon found

`gnomon check --base fff079c --role builder` judged everything built in the session of 22–23 November
by this repository's own surface (`.gnomon/`), on a clean checkout on the GPU box:

| Check | Verdict | Why |
|---|---|---|
| surface | pass | `.gnomon/` was not edited |
| must_fail_first | pass | 31 new test files fail on the old sources |
| verify | passed_unverified | the suite passed (exit 0), but `pyproject.toml`, a detected test configuration (`protects = ["@detected", ...]`), changed |
| write_allow | fail | 73 of 145 changed paths are outside the builder's M0 scope `tools/**, tests/**, kernel/**, adapters/**` |
| audit | pass | the verdict is in Gnomon's hash-chained trail |

The work is outside the scope because the factory grew past M0: the cockpit, the embed server, the MCP
server, the gateway, the docs and the release files did not exist when the scope was set.

## The proposal

1. Widen the builder's `write_allow` in `.gnomon/roles.toml` to the packages the factory now has:

   ```diff
   -write_allow = ["tools/**", "tests/**", "kernel/**", "adapters/**"]
   +write_allow = ["tools/**", "tests/**", "kernel/**", "adapters/**", "cockpit/**", "embed/**",
   +               "mcp/**", "gateway/**", "docs/**", "README.md", "CONTRIBUTING.md", "SECURITY.md",
   +               "pyproject.toml", ".gitignore"]
   ```

   Still never: `.gnomon/**` (the surface protects itself), `contract/**` (the operator amends the
   contract, and the contract checker forbids a task that writes it), and `decisions/**` (the
   owner's record).
2. Accept `pyproject.toml` once as a legitimate test configuration. It holds the package definition
   and no test settings. A later change to it is again `passed_unverified` until a person looks, which
   is what the `protects` rule is for.

## Commands for the owner

These are not run by any agent: the surface hash changes and trust is yours.

```bash
# 1. edit .gnomon/roles.toml as above (or apply the diff by hand), then commit it yourself
# 2. trust the new surface on each machine that runs cells
gnomon trust            # in the repository, on the GPU box and on this workstation
# 3. judge the session's work again under the new surface
gnomon check --base fff079c --role builder --json
```

The expected result after the change: write_allow passes. verify stays `passed_unverified` for this one
check, because `pyproject.toml` changed in the range; a check from a base after that commit passes as
`passed`.
