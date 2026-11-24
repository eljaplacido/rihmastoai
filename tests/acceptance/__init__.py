"""The acceptance matrix the owner tests Rihmasto against (docs/acceptance.md), offline.

Each test is one or more cells of the matrix: a use case (a row) in a mode, a maturity or an access
mode (a column). It runs the real kernel with the scripted model and builder of `scripts.py`, which
extend the demo's (kernel/demo.py), with no Gnomon, no model keys and no network beyond loopback, so
CI runs it as part of `python -m unittest discover -s tests`. On its own:
`python -m unittest discover -s tests/acceptance -t tests`.
"""
