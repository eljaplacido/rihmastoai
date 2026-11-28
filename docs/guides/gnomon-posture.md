# Gnomon posture: how well Gnomon governs each project, and what to tighten

Each project has a **Gnomon safety** view (the Govern capsule, for developers and IT). Rihmasto computes it itself,
read-only, from the project's own Gnomon files: `.gnomon/config.toml` and `.gnomon/policy.toml` in its local
working copy (or, without one, on the main branch of Rihmasto's copy of its repository). No other file is opened,
nothing runs in the repository, nothing is kept, and no outside service is asked.

## What it scores

Six dimensions, 100 points in all, each from settings Gnomon documents:

| Dimension | Points | What holds |
|---|---|---|
| Verification and change | 20 | `[verify] command` (a check after a turn), `after = "change"` or `"always"`, `protects`, `exit_on_fail = true` |
| Containment and sandbox | 20 | `[sandbox] exec = "os"` or `"docker"` (not `"off"`), `network = false`, `reads = "scoped"` |
| Governance and guards | 20 | `[governance]` at `prevent` or `enforce` (`observe` and `advise` hold in part), `[approval]` declared |
| Audit and provenance | 15 | `[audit] enabled = true`, `chain = true`, `[audit.anchor]` |
| Loop, edit and context | 15 | `[defaults] edit_format = "hashline"`, `[context]`, `[resilience]` |
| Freshness | 10 | `.gnomon/skills/`, `.gnomon/trials/` or `.gnomon/loops/`, and no key Gnomon no longer reads (`[sandbox] level`) |

The view shows the total, the dimensions with their checks (the weakest first) and where it read. A file that is
not TOML Rihmasto can read is named. A project with no `.gnomon` folder is **not measured**: Gnomon is not set up
there yet, and the first step is `gnomon init` in its folder. A project with no working copy and no repository is
not measured either, with why. Neither is ever shown as a score of zero.

## Suggestions become change cards, never changes

For each check that does not hold the view suggests the exact setting and the file it goes in, with its full path in
the working copy, a severity and why. **File as a change** files one as a change card in the project's Inbox, signed
with your name, once per suggestion; a person decides it there and makes the change in the project's own files.
Rihmasto applies nothing, writes no `.gnomon` file and grants Gnomon no trust or approval: trusting or approving
Gnomon stays the owner's act.

## On the command line

```bash
rihmasto gnomon-posture show <pid>                         # the posture, as JSON
rihmasto gnomon-posture propose <pid> GP-sandbox-exec --person "<your name>" --persona developer
```

## Ask Rihma

"How well is Gnomon governing this project?" and "What should I tighten first?" are answered by rule from the
project's own Gnomon files, read now, with **Take me there** to the view.
