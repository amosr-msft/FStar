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
- `instrument_pruning_reference.py` adds an extracted-only switch between the
  cached and original fresh pruning paths.
- `run_pruning_equivalence.py` records byte-identical cached/reference query
  streams with compiler, solver, cache, and source provenance.
- `run_ambient_cache_validation.py` records focused fallback and full-source
  checks with exact commands and hashes.
- `PruningCacheScope.fst` checks alternating symbols for query-local leakage.
- `PruningEmptyPattern.fst` covers an encoded explicit empty pattern
  alternative.
- `pruning_cache_regression.ml` and `run_pruning_state_regression.py` compare
  retained cached/reference declarations for empty and ordinary trigger
  alternatives.
- `summarize_ambient_cache.py` validates the prototype evidence into
  `AMBIENT_CACHE_EXPERIMENT.json`.
- `run_ambient_cache_suite.py` runs the pinned, adjacent-pair broad suite.
- `run_matched_fstar_workload.py` adds focused successful regression controls.
- `run_matched_query_stream.py` verifies cross-compiler SMT stream identity.
- `summarize_ambient_cache_suite.py` validates and reports broad-suite evidence
  in `AMBIENT_CACHE_BROAD_SUITE.json`.

Generated sources remain under evidence/output directories. The no-ambient
mode changes context selection and is diagnostic only.
