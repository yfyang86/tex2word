"""Synthetic-LaTeX probe harness: generate -> verify -> fix -> update.

Small synthetic documents ("probes") exercise one construct in one setting.
Generic oracles (dropped/duplicated content, leaked LaTeX, unresolved
references, raw citation keys, warnings, math fallbacks, empty n-ary bodies,
math round-trip) plus per-probe expectations flag defects; a baseline of known
failures turns the run into a regression gate. See ``tools/synth/README.md``.
"""

SENTINEL = "Qx7k"
