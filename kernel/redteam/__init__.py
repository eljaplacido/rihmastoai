"""Rihmasto's own security scanning and red teaming (D-0014, FR-H10).

Rihmasto checks what it builds with its own code. It depends on no other project: the kernel's
standard library is all it needs, and external scanners found on PATH are optional extras that
say "not measured" when absent.

- `rules.py`: the rule catalogue. Every rule has a CWE id and an OWASP Top 10 2025 id, and a
  seeded defect in `tests/fixtures/redteam/vulnerable_app` that it must catch, with a clean twin
  in `tests/fixtures/redteam/clean_app` it must stay quiet on.
- `static.py`: the static layer. It reads a product's source and configuration (which files, and
  how: `collect.py`) and says per layer what it measured. The rules live beside it: `pyrules.py`
  (Python, through the standard library's `ast`: names and bindings in `pyast.py`, `pybind.py` and
  `pycheck.py`, SQL in `pysql.py`, set-up rules in `pysettings.py`, the path dataflow heuristic in
  `taint.py`), `webrules.py` and `htmlrules.py` (JavaScript and HTML, read by `jslex.py`),
  `dockerrules.py` and `actionsrules.py` (through `configrules.py`) and `secretscan.py` (secrets,
  with the patterns and the mask in `masking.py`). Nothing is imported, executed or downloaded.
- `report.py`: findings, per-layer coverage, SARIF 2.1.0 for the security gate, and a summary.
- `scope.py`: who authorised which targets until when. Dynamic and agentic tests only ever reach
  what the factory itself deployed, on loopback, inside a scope a person with the `it` or
  `compliance` persona authorised. A surface counts only through the handle `started.py` issued
  for a server or process the factory started.
- `agentic.py`: the agentic layer, against the embed chat and the cockpit assistant, scored by
  canaries (`canary.py`, with the encodings undone in `decoders.py`) and judged by `judge.py`.
- `dynamic.py`: the dynamic layer. It probes a running deployment the scope allows: security
  headers, error pages that leak, path traversal, reflected injection, method tampering, malformed
  and oversized bodies, CORS and rate limiting, on the routes of the project's fixed interface.
  Every request goes through `client.py`, which checks the scope before each one and keeps the
  run's request budget. The probes live in `contentprobes.py` and `protocolprobes.py`, with what
  they share in `probing.py`; their rules are `rules.DYNAMIC_RULES`, each proven by the seeded
  server in `tests/fixtures/redteam/dynamic/vulnerable` and quiet on its clean twin.

    python -m kernel.redteam static <path> [--sarif out.sarif] [--markdown out.md]
    python -m kernel.redteam dynamic <project> --env <environment> [--sarif out.sarif]
"""

from __future__ import annotations

TOOL_NAME = "Rihmasto red team"
TOOL_VERSION = "0.1.0"

__all__ = ["TOOL_NAME", "TOOL_VERSION"]
