# Generated squash-lemma context benchmark

This directory reproduces the order-dependent slowdown from the historical
exhaustive `BvModelAgreesWithZ3` benchmark without BV operators or sequence
evaluation. Each generated declaration proves an opaque refined integer
equality through a real SMT query.

- `generate_simple.py` writes monolithic or balanced split modules.
- `run_simple_scaling.py` measures counts 256 through 5,808 and a 64-process
  split.
- `run_simple_probes.py` compares normal, no-ambient, admitted, and lax runs.
- `instrument_context.py` instruments ignored extracted OCaml to count the
  retained typechecker, pruning, solver-state, and query costs.
- `run_context_trace.py` runs an instrumented module.
- `run_full_bv_probe.py` runs a focused diagnostic on the historical full BV
  source.
- `summarize_context.py` validates and combines durable evidence into
  `BV_CONTEXT_ANALYSIS.json`.

Generated sources remain under evidence/output directories. The no-ambient
mode changes context selection and is diagnostic only.
