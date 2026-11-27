"""Each project's Gnomon governance posture, computed by Rihmasto from the project's own Gnomon files (FR-GNP1).

The owner (2026-11-27) asked for Gnomon insights per project and their suggestions, then: "we don't want
dependencies from these projects to this ... I am giving this as an inspiration for Rihmasto's capabilities". So
Rihmasto computes the posture itself, from nothing but the project's own `.gnomon/config.toml` and
`.gnomon/policy.toml` (and the names of the folders beside them), read-only:

- ``read``: where the files are (the project's local working copy, else the main branch of Rihmasto's copy of its
  repository) and what they declare, parsed as TOML; no other file of the repository is opened;
- ``score``: the checks, each one of Gnomon's documented settings, grouped into six dimensions (verification and
  change, containment and sandbox, governance and guards, audit and provenance, loop/edit/context, freshness), and
  a suggestion for each check that does not hold: its severity, why, and the exact setting in the project's own
  file;
- ``view``: the posture as the cockpit, the command line and Ask Rihma show it, and ``propose``: one suggestion
  filed as a change card a person decides;
- ``ask``: Ask Rihma's answers; ``cli``: ``rihmasto gnomon-posture``.

Nothing here writes into the repository, applies a suggestion or grants Gnomon any trust or approval: a
suggestion becomes a change card at most, and trusting Gnomon stays the owner's act.
"""

from __future__ import annotations

VIEW = "gnomon_posture"
SEES = ("developer", "it")                    # the personas the view is for
FILERS = ("developer", "it")                  # who files a suggestion as a change card
FILE = "gnomon_posture.json"                  # a project's suggestions filed as change cards

__all__ = ["FILE", "FILERS", "SEES", "VIEW"]
