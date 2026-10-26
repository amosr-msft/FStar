# Compiler encoding benchmarks

## Generated lemma context investigation

`tests/benchmarks/bv-context/` contains the focused investigation of the
historical exhaustive `BvModelAgreesWithZ3` source at `0e13baff38`.
`generate_simple.py` emits a direct non-BV squash/equality reproducer;
`run_simple_scaling.py` compares monolithic scaling with 64 balanced processes;
`run_simple_probes.py` runs admit/lax/no-ambient controls; and
`instrument_context.py` adds opt-in counters to ignored extracted OCaml.

```sh
git -C /path/to/FStar worktree add \
  /workspace/wt11/FStar-bv-context \
  0e13baff38309523a2074ef8fbc3745b4bc793ad

python tests/benchmarks/bv-context/run_simple_scaling.py \
  --fstar /workspace/wt11/FStar-bv-context/stage2/out/bin/fstar.exe \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/bv-simple-scaling"

python tests/benchmarks/bv-context/run_simple_probes.py \
  --fstar /workspace/wt11/FStar-bv-context/stage2/out/bin/fstar.exe \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/bv-simple-probes"
```

To build the diagnostic binary, restore these clean stage1 extracted files to
`stage2/fstarc.ml` before applying the instrumenter:

```text
FStarC_SMTEncoding_Pruning.ml
FStarC_SMTEncoding_SolverState.ml
FStarC_SMTEncoding_Z3.ml
FStarC_SMTEncoding_Solver.ml
FStarC_SMTEncoding_Encode.ml
FStarC_TypeChecker_Tc.ml
```

Then run `instrument_context.py`, build
`stage3/dune/fstarc-full/fstarc3_full.exe`, and use
`run_context_trace.py --worktree /workspace/wt11/FStar-bv-context` with and
without `--no-ambients`. `run_full_bv_probe.py --only no-ambients` checks the
exact historical BV source. Finally:

```sh
python tests/benchmarks/bv-context/summarize_context.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --worktree /workspace/wt11/FStar-bv-context \
  --output tests/benchmarks/bv-context/BV_CONTEXT_ANALYSIS.json
```

Forced context changes are diagnostics only. The preserved prior-session
report was unavailable here under content-exclusion policy; its supplied
headline results are labeled as such in the JSON and report.

The ambient-closure cache prototype is on
`users/amos/20261026-fstar-pruning-ambient-cache` (`734a73c518`). Reuse the
same simple sources and baseline evidence, then run candidate scaling with:

```sh
python tests/benchmarks/bv-context/run_simple_scaling.py \
  --fstar /workspace/wt11/FStar-bv-context/stage2/out/bin/fstar.exe \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/ambient-cache-simple-scaling" \
  --counts 256 512 1024 2048 4096 --no-split
```

`instrument_pruning_reference.py` builds an ignored diagnostic binary whose
`FSTAR_PRUNING_REFERENCE=1` mode forces the original fresh scan.
`PruningCacheScope.fst`, `SimpleAgreement64`, and the existing pruning test
produce byte-identical cached/reference query streams:

```sh
# Restore stage1/FStarC_SMTEncoding_Pruning.ml into stage2/fstarc.ml,
# instrument it, and rebuild fstarc3_full.exe.
python tests/benchmarks/bv-context/instrument_pruning_reference.py \
  /workspace/wt11/FStar-bv-context
python tests/benchmarks/bv-context/run_pruning_equivalence.py \
  --fstar /path/to/instrumented/fstarc3_full.exe \
  --z3 /path/to/z3-5.3.0 \
  --worktree /workspace/wt11/FStar-bv-context \
  --output "$EVIDENCE_ROOT/ambient-cache-correctness-v2"

python tests/benchmarks/bv-context/run_ambient_cache_validation.py \
  --fstar /workspace/wt11/FStar-bv-context/stage3/out/bin/fstar.exe \
  --z3 /path/to/z3-5.3.0 \
  --worktree /workspace/wt11/FStar-bv-context \
  --output "$EVIDENCE_ROOT/ambient-cache-validation"
```

Rebuild the context instrumentation from the candidate source and run
`run_context_trace.py` at 1,024 declarations for phase comparison. Run
`run_full_bv_probe.py --only baseline` for the full candidate, then summarize:

```sh
python tests/benchmarks/bv-context/summarize_ambient_cache.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --baseline-worktree /workspace/wt11/FStar-bv-context-baseline \
  --candidate-worktree /workspace/wt11/FStar-bv-context \
  --output tests/benchmarks/bv-context/AMBIENT_CACHE_EXPERIMENT.json
```

The cache branch is experimental; no runtime option is added and no PR is
created.

This benchmark generates deterministic transition functions that compare
concrete-width `FStar.BV` operations with corresponding `FStar.UInt`
operations. Both representations use seed `20261021`, the same record widths,
literals, child calls, dependency graph, and output selection.

Generator version 2 emits two shapes:

- `live` (the default) is the representative workload. Every generated
  binding is reachable from an output or next-state field, with one long
  dependency chain per width. Its 1,000-binding primary mix is 300
  conditionals, 150 extracts, 100 concatenations, 50 replications, five
  modular additions, five dynamic shifts, and 390 bitwise operations.
- `sparse` preserves generator version 1 byte-for-byte as a shallow,
  sparse-reachability control. Its initial measurements remain reproducible
  but are not representative of the requested live transition workload.

Matched operations are bitwise AND/OR/XOR/NOT, modular addition, dynamic left
shift, conditionals, low-bit extraction, concatenation, and two-fold
replication. UInt extraction/concatenation/replication use `to_uint_t` and
arithmetic. BV dynamic shifts convert the matched same-width BV operand with
`bv2int`; UInt shifts use the corresponding refined integer directly.

Generate sources and their SHA-256 manifests:

```sh
./generate.py --bindings 100 250 500 1000
```

Run the sweep with a compiler built from this checkout:

```sh
PATH=/path/to/z3/bin:$PATH ./run.py \
  --fstar /path/to/fstar.exe \
  --z3version 5.3.0 \
  --bindings 100 250 500 1000
```

Each measured target starts uncached. Child modules are prechecked, and F*
library dependencies remain cache-readable. `write` enables
`--cache_checked_modules`; `no-write` omits that flag without using
`--cache_off`. Generated sources, checked files, query logs, and raw results
stay under ignored `_generated`, `_cache`, and `_results` directories.
Measurements are written below `_results/<shape>/`.

The generator also emits the four 400-literal isolation workloads from the
benchmark specification and direct, refined-ascription, and normalized-
assertion BV variants at the largest requested binding count.

See [RESULTS.md](RESULTS.md) for the initial measurements and diagnosis.

## Primary master-versus-interning comparison

`MASTER_INTERNING_COMPARISON.json` is the primary comparison: pinned upstream
master `9a10b2ccb1` without interning versus
`users/amos/20261023-fstar-master-smt-sharing` (`56e8ac31da`), the exact same
tree plus only PR #4760's net two-file main interning patch.

```sh
export EVIDENCE_ROOT=/path/to/durable/session-files
git -C /path/to/FStar worktree add \
  -b users/amos/20261023-fstar-master-no-intern \
  /workspace/wt11/FStar-master-no-intern 9a10b2ccb1f
git -C /path/to/FStar worktree add \
  -b users/amos/20261023-fstar-master-smt-sharing \
  /workspace/wt11/FStar-master-interning \
  56e8ac31da209fc56899a225f9a9e6a4b5d37619
git -C /workspace/wt11/FStar-master-interning diff --name-status \
  9a10b2ccb1f17064ec496ee315acc6a5f99adf2a..HEAD
# Expected: only Encode.fst modified and Sharing.fst added.
for worktree in /workspace/wt11/FStar-master-{no-intern,interning}; do
  git -C "$worktree" submodule update --init --recursive
  (cd "$worktree" &&
    PATH=/path/containing/z3-5.3.0:$PATH make -j8 3)
done
./generate.py --out-dir _generated --bindings 500
```

Use `run_master_comparison.py` for five shuffled write/no-write repetitions,
`run_master_profiles.py` with binaries produced by
`instrument_extracted_analysis.py` for phase/GC analysis, and
`run_master_ordinary.py` for ordinary controls. Existing
`measure_dependent.py` measures metadata and rooted dependency loading.

`UINT_HEAP_ANALYSIS.json` is the focused follow-up for the UInt Live-500 peak.
It uses `run_uint_heap_diagnostics.py` for resumable lightweight,
phase-snapshot, forced-GC liveness, and crossed-dependency runs. Forced
collections and reachable-word scans are diagnostic only and are never
enabled in the production compiler.

`LOW_OVERHEAD_SHARING.json` compares no-interning master, the current main
interner, and the declarations-only candidate. The candidate keeps full
declaration interning but skips the separate pruning-index interner:

```sh
git -C /path/to/FStar worktree add \
  /workspace/wt11/FStar-master-decls-sharing \
  users/amos/20261024-fstar-master-decls-sharing

# Build all three compilers, then generate BenchBvChildren and
# BenchUIntChildren with each matching production compiler into:
#   $EVIDENCE_ROOT/low-overhead-caches-v2/cache-{master,interning,candidate}

# Build pass-profile binaries from clean extracted ML. For the two sharing
# variants, restore FStarC_SMTEncoding_Sharing.ml from stage1 before applying
# the ignored wrapper.
mkdir -p "$EVIDENCE_ROOT/low-overhead-instrumented-v2"
python instrument_extracted_analysis.py --sharing-only \
  /workspace/wt11/FStar-master-no-intern
cp /workspace/wt11/FStar-master-interning/stage1/fstarc.ml/\
FStarC_SMTEncoding_Sharing.ml \
  /workspace/wt11/FStar-master-interning/stage2/fstarc.ml/
python instrument_extracted_analysis.py --sharing-only \
  /workspace/wt11/FStar-master-interning
cp /workspace/wt11/FStar-master-decls-sharing/stage1/fstarc.ml/\
FStarC_SMTEncoding_Sharing.ml \
  /workspace/wt11/FStar-master-decls-sharing/stage2/fstarc.ml/
python instrument_extracted_analysis.py --sharing-only \
  /workspace/wt11/FStar-master-decls-sharing
# In each stage3/dune directory:
#   dune build fstarc-full/fstarc3_full.exe
# Copy the results as fstar-{master,interning,candidate}.exe.

python run_low_overhead_comparison.py \
  --master /workspace/wt11/FStar-master-no-intern \
  --interning /workspace/wt11/FStar-master-interning \
  --candidate /workspace/wt11/FStar-master-decls-sharing \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/low-overhead-caches-v2" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/low-overhead-comparison-v2" \
  --repetitions 5

python run_low_overhead_comparison.py \
  --master /workspace/wt11/FStar-master-no-intern \
  --interning /workspace/wt11/FStar-master-interning \
  --candidate /workspace/wt11/FStar-master-decls-sharing \
  --instrumented-dir "$EVIDENCE_ROOT/low-overhead-instrumented-v2" \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/low-overhead-caches-v2" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/low-overhead-profiles-v2" \
  --repetitions 3 --profile --modes no-write

python run_low_overhead_ordinary.py \
  --master /workspace/wt11/FStar-master-no-intern \
  --interning /workspace/wt11/FStar-master-interning \
  --candidate /workspace/wt11/FStar-master-decls-sharing \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/low-overhead-ordinary" \
  --repetitions 5

python summarize_low_overhead.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --master /workspace/wt11/FStar-master-no-intern \
  --interning /workspace/wt11/FStar-master-interning \
  --candidate /workspace/wt11/FStar-master-decls-sharing \
  --output LOW_OVERHEAD_SHARING.json
```

Generate one write artifact for each variant/workload under
`$EVIDENCE_ROOT/low-overhead-artifacts/{master,interning,candidate}`.
Invoke `measure_dependent.py` for each variant, BV/UInt representation, and
metadata/rooted mode; preserve its JSONL under
`$EVIDENCE_ROOT/low-overhead-dependent`. Run
`compare_checked_structure.ml` for master versus both sharing variants.
The summarizer also requires the candidate build, `boot-diff`,
`BvBinaryOps`, `ClassicalSugar`, and structural-comparison logs named as in
`LOW_OVERHEAD_SHARING.json`; it validates their success markers, campaign
cell counts, commits, compiler/input/dependency/Z3 hashes, and artifact hashes
before emitting the report.

Build the detailed-phase binaries from ignored extracted ML:

```sh
mkdir -p "$EVIDENCE_ROOT/master-instrumented"
for variant in no-intern interning; do
  python instrument_extracted_analysis.py \
    /workspace/wt11/FStar-master-$variant
  (cd /workspace/wt11/FStar-master-$variant/stage3/dune &&
    dune build fstarc-full/fstarc3_full.exe)
  cp /workspace/wt11/FStar-master-$variant/stage3/dune/_build/default/\
fstarc-full/fstarc3_full.exe \
    "$EVIDENCE_ROOT/master-instrumented/fstar-$variant.exe"
done
```

Before `run_master_comparison.py`, build `BenchBvChildren.fst` and
`BenchUIntChildren.fst` once into each variant's
`$EVIDENCE_ROOT/master-comparison/cache-VARIANT` using that variant's compiler,
`--cache_checked_modules`, `--already_cached Prims,FStar`, and the shared
`_generated` include root.

```sh
python run_master_comparison.py \
  --master /workspace/wt11/FStar-master-no-intern \
  --interning /workspace/wt11/FStar-master-interning \
  --generated "$PWD/_generated" --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/master-comparison" --repetitions 5

python run_master_profiles.py \
  --master-worktree /workspace/wt11/FStar-master-no-intern \
  --interning-worktree /workspace/wt11/FStar-master-interning \
  --instrumented-dir "$EVIDENCE_ROOT/master-instrumented" \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/master-comparison" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/master-profiles" --repetitions 3

python run_master_ordinary.py \
  --master /workspace/wt11/FStar-master-no-intern \
  --interning /workspace/wt11/FStar-master-interning \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/master-ordinary" --repetitions 5

python summarize_master_comparison.py \
  --evidence-root /path/to/session/files \
  --master /workspace/wt11/FStar-master-no-intern \
  --interning /workspace/wt11/FStar-master-interning \
  --z3 /path/to/z3-5.3.0
```

For the heap investigation, first regenerate each compiler's child caches
after rebuilding its stage3 libraries; a stale child changes GC scheduling and
invalidates the matched workload. Build the ignored extracted-ML diagnostics
as above, then run:

```sh
python run_uint_heap_diagnostics.py \
  --master-worktree /workspace/wt11/FStar-master-no-intern \
  --interning-worktree /workspace/wt11/FStar-master-interning \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/master-comparison" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/uint-heap-diagnostics-valid" \
  --analysis-mode lightweight --modules BenchUIntLive500 \
  --modes write no-write --repetitions 3

python run_uint_heap_diagnostics.py \
  --master-worktree /workspace/wt11/FStar-master-no-intern \
  --interning-worktree /workspace/wt11/FStar-master-interning \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/master-comparison" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/uint-heap-diagnostics-valid" \
  --analysis-mode lightweight --modules BenchBvLive500 \
  --modes no-write --repetitions 2

python run_uint_heap_diagnostics.py \
  --master-worktree /workspace/wt11/FStar-master-no-intern \
  --interning-worktree /workspace/wt11/FStar-master-interning \
  --instrumented-dir "$EVIDENCE_ROOT/uint-heap-instrumented" \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/master-comparison" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/uint-decl-phases-v2" \
  --analysis-mode snapshot --modules BenchUIntLive500 \
  --modes no-write --repetitions 1

python run_uint_heap_diagnostics.py \
  --master-worktree /workspace/wt11/FStar-master-no-intern \
  --interning-worktree /workspace/wt11/FStar-master-interning \
  --instrumented-dir "$EVIDENCE_ROOT/uint-heap-instrumented" \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/master-comparison" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/uint-heap-liveness" \
  --analysis-mode forced --modules BenchUIntLive500 \
  --modes write no-write --repetitions 1

python run_uint_heap_diagnostics.py \
  --master-worktree /workspace/wt11/FStar-master-no-intern \
  --interning-worktree /workspace/wt11/FStar-master-interning \
  --instrumented-dir "$EVIDENCE_ROOT/uint-heap-instrumented" \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/master-comparison" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/bv-heap-liveness" \
  --analysis-mode forced --modules BenchBvLive500 \
  --modes no-write --repetitions 1

python run_uint_heap_diagnostics.py \
  --master-worktree /workspace/wt11/FStar-master-no-intern \
  --interning-worktree /workspace/wt11/FStar-master-interning \
  --instrumented-dir "$EVIDENCE_ROOT/uint-heap-instrumented" \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/master-comparison" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/uint-after-cache-gc" \
  --analysis-mode after-cache-gc --modules BenchUIntLive500 \
  --modes no-write --repetitions 3

python run_uint_heap_diagnostics.py \
  --master-worktree /workspace/wt11/FStar-master-no-intern \
  --interning-worktree /workspace/wt11/FStar-master-interning \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/master-comparison" \
  --z3 /path/to/z3-5.3.0 \
  --output "$EVIDENCE_ROOT/uint-heap-cross" \
  --analysis-mode lightweight --modules BenchUIntLive500 \
  --modes no-write --repetitions 5 --cross-dependencies

python summarize_uint_heap_diagnostics.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --master /workspace/wt11/FStar-master-no-intern \
  --interning /workspace/wt11/FStar-master-interning \
  --output UINT_HEAP_ANALYSIS.json
```

Generate compiler-specific child caches before the main campaign. For
dependent loading, generate one write artifact per compiler, then invoke
`measure_dependent.py` in both `metadata` and `rooted` modes with five
repetitions, using the matching child/target artifacts.

```sh
python measure_dependent.py \
  --fstar /workspace/wt11/FStar-master-interning/stage3/out/bin/fstar.exe \
  --smt /path/to/z3-5.3.0 \
  --dependency "$EVIDENCE_ROOT/master-artifacts/interning/BenchBvLive500.fst.checked" \
  --child "$EVIDENCE_ROOT/master-artifacts/interning/BenchBvChildren.fst.checked" \
  --target BenchDependentBv.fst --module BenchBvLive500 \
  --child-module BenchBvChildren --label interning-bv \
  --mode rooted --repeats 5
```

Structural comparison ignores only stage2's compiler-specific dependency
digests:

```sh
ocamlfind ocamlopt -linkpkg -package zarith \
  compare_checked_structure.ml -o "$EVIDENCE_ROOT/compare_checked_structure"
"$EVIDENCE_ROOT/compare_checked_structure" \
  "$EVIDENCE_ROOT/master-artifacts/master/BenchBvLive500.fst.checked" \
  "$EVIDENCE_ROOT/master-artifacts/interning/BenchBvLive500.fst.checked"
```

## Reproduction commands

The sparse-control results can be reproduced with the following separate
runs. `run.py` intentionally replaces `measurements.jsonl` for each run.

```sh
FSTAR=/path/to/fstar.exe
Z3VERSION=5.3.0

./run.py --fstar "$FSTAR" --z3version "$Z3VERSION" --shape sparse \
  --bindings 100 250 500 1000 --repeats 1
cp _results/sparse/measurements.jsonl _results/sparse/full-sweep.jsonl

./run.py --fstar "$FSTAR" --z3version "$Z3VERSION" --shape sparse \
  --bindings 500 --repeats 3 --modes no-write --only Direct500
cp _results/sparse/measurements.jsonl _results/sparse/direct500-repeats.jsonl

./run.py --fstar "$FSTAR" --z3version "$Z3VERSION" --shape sparse \
  --bindings 1000 --repeats 3 --modes write no-write --only BvDirect1000
cp _results/sparse/measurements.jsonl _results/sparse/bv1000-cache-repeats.jsonl
```

The final representative dynamic-shift measurements used:

```sh
./run.py --fstar "$FSTAR" --z3version "$Z3VERSION" --shape live \
  --bindings 100 250 500 --repeats 1 --modes write --timeout 1200
```

The type-checker profiles in the report used the generated 500-binding
targets, prechecked child modules, and these additional flags:

```sh
"$FSTAR" --z3version "$Z3VERSION" --smtencoding.elim_box true --force \
  --profile BenchUIntDirect500 --profile_component FStarC.TypeChecker \
  --include _generated --cache_dir _cache --odir _cache \
  --already_cached Prims,FStar _generated/BenchUIntDirect500.fst

"$FSTAR" --z3version "$Z3VERSION" --smtencoding.elim_box true --force \
  --profile BenchBvDirect500 --profile_component FStarC.TypeChecker \
  --include _generated --cache_dir _cache --odir _cache \
  --already_cached Prims,FStar _generated/BenchBvDirect500.fst
```

Query counts used the same command shape with `--query_stats` replacing the
two profiling flags, for UInt-500 and BV-1000 respectively. The printable
encoding measurements used:

```sh
"$FSTAR" --read_checked_file _cache/BenchBvDirect1000.fst.checked
```

## Experimental sharing recovery

`sharing_experiment.ml` is a bounded diagnostic prototype, not part of the F*
compiler. Build it with the same OCaml ABI and exact compiler library that wrote the
checked files. For example, enter the compiler's opam switch first (or prefix
the command with the corresponding `opam exec --switch=... --`):

```sh
FSTAR_ROOT=/path/to/FStar
BUILD=$FSTAR_ROOT/stage3/dune/_build/default/fstar-guts
eval "$(opam env --switch=/path/to/matching/switch --set-switch)"

ocamlfind ocamlopt -linkpkg \
  -package batteries,dynlink,mtime,mtime.clock,pprint,ppx_deriving.runtime \
  -package ppx_deriving_yojson.runtime,ppxlib,ppxlib.ast,process,stdint \
  -package yojson,zarith,unix \
  -I "$BUILD/.fstarcompiler.objs/byte" \
  -I "$BUILD/.fstarcompiler.objs/native" \
  "$BUILD/fstarcompiler.cmxa" sharing_experiment.ml \
  -o sharing_experiment.exe

./sharing_experiment.exe INPUT.checked OUTPUT.shared.checked
./sharing_experiment.exe --load OUTPUT.shared.checked
```

The pass recursively hash-conses structurally equal SMT terms, declarations,
declaration blocks, pruning summaries, and pruning-index entries. It preserves
every declaration and index entry in its original order. It does not remove
duplicate-key blocks, rename symbols, or use alpha-equivalence.

## Dependent-file load measurements

`BenchDependentBv.fst` and `BenchDependentUInt.fst` reference the benchmark
types and `step` definition. `measure_dependent.py` checks an uncached target
against a copied checked dependency in an isolated cache:

```sh
./measure_dependent.py \
  --fstar /path/to/fstar.exe \
  --smt /path/to/z3-5.3.0 \
  --dependency /path/to/BenchBvLive500.fst.checked \
  --child /path/to/BenchBvChildren.fst.checked \
  --target BenchDependentBv.fst \
  --module BenchBvLive500 \
  --child-module BenchBvChildren \
  --label bv-original \
  --mode rooted \
  --repeats 7
```

`metadata` admits the target query, so the dependency's stage-2 metadata is
loaded but the lazy SMT payload is not forced. `rooted` performs a small
excluded-middle query over `(B.step ...).state` with normal context pruning;
this forces the dependency payload without changing solver registration
semantics. Results are warm-filesystem measurements; the runner does not flush
the host page cache. Each invocation recreates its label/mode result directory
and cache, so artifact and tool inputs must live elsewhere. The runner is
Linux/GNU-specific: it requires `/usr/bin/time -v` and GNU `timeout`.

For the reported comparison, the artifact variants were:

| Label | Benchmark artifact | Child artifact |
|---|---|---|
| `bv-original` | Baseline `BenchBvLive500.fst.checked` built before construction reuse | Matching baseline `BenchBvChildren.fst.checked` |
| `bv-construction` | `BenchBvLive500.fst.checked` built by the modified compiler | Matching modified child |
| `bv-posthoc` | Baseline artifact rewritten by `sharing_experiment.exe` | Matching baseline child |
| `uint-original` | Baseline UInt artifact | Matching baseline child |
| `uint-posthoc` | Baseline UInt artifact rewritten by `sharing_experiment.exe` | Matching baseline child |

Run the example for both `--mode metadata` and `--mode rooted`, changing the
label and artifact paths according to the table. Original artifacts can be
regenerated by building commit `51e197e72a`; construction-reuse artifacts use
commit `a12303a4b7`. In either checkout:

```sh
./run.py --fstar /path/to/that/checkout/stage3/out/bin/fstar.exe \
  --z3version 5.3.0 --shape live --bindings 500 --repeats 1 \
  --modes write --only BvLive500
```

The post-hoc variants use the sharing-recovery command from the preceding
section. To isolate eager metadata loading, add
`--profile BenchDependentBv --profile_component FStarC.CheckedFiles` to an
otherwise equivalent direct F* invocation.

## Experimental general SMT sharing

The opt-in general prototype (`--ext smtencoding:share=true`) moves exact
interning to the common exported-encoding boundary: after `encode_signature`,
before `Pruning.summarize_elts`. It then interns the derived index separately.
This covers all SMT encoders without per-primitive caches and requires no
fresh-name replay.

`FStarC.SMTEncoding.Sharing` implements the interner in ordinary F*. Each
visited occurrence returns a bottom-up hash that its parent reuses, and
collision buckets use typed exact equality with physical equality for
already-canonical children. Opaque diagnostic messages compare only by
physical identity. Tables are local to one
module export and released afterward. The pass preserves list lengths and
ordering and does not use encoding keys, remove declarations, render opaque
fields, or perform alpha-equivalence. Abstract lidents compare only by physical
identity, conservatively preserving unexposed cached fields.

Build and test it with the standard compiler targets:

```sh
make -j8 3
make boot-diff
stage3/out/bin/fstar.exe --z3version 5.3.0 \
  --ext smtencoding:share=true \
  tests/micro-benchmarks/BvBinaryOps.fst
```

Pass cost can be isolated diagnostically with:

```sh
fstar.exe --profile ModuleName \
  --profile_component FStarC.SMTEncoding.Sharing \
  --ext smtencoding:share=true ModuleName.fst
```

`GENERAL_SHARING_MEASUREMENTS.json` records the compiler/solver/source hashes,
medians, artifact sizes, pass profiles, and validation outcomes used by the
report.

`TYPE_DIVERGE_VALIDATION.json` records the bounded Custard `TypeDiverge`
comparison, including the exact commands, compiler/input hashes, stack/runtime
settings, diagnostics, elapsed time, and peak RSS for `b1fe663037` and the
final compiler with the sharing option absent and present. The focused command
extracts a prechecked module, so it does not execute SMT interning.

## FunOS Co3 investigation

`FUNOS_CO3_INVESTIGATION.json` records the bounded attempt to compare current
FunOS stable `co3-verify` with upstream F* and unconditional sharing. It
includes the exact FunOS, FunSDK, FunFM, compiler, and solver revisions;
isolated-overlay setup; commands; partial checked-cache progress; and the
common `Libs.GuestMemRanges` assertion failure.

The benchmark requires `CO3_DISABLE_VERIFY=0`. FunOS pins Z3 4.13.3, so these
newer F* revisions also need `--z3version 4.13.3`. Supply `FSTAR_OPT` through
the environment so the Makefile still appends the configuration namespace:

```sh
FSTAR_OPT='--z3version 4.13.3' \
make MACHINE=s2-coco-qemu TARGET=guest-up CO3_DISABLE_VERIFY=0 \
  SDKDIR=/path/to/matched-sdk \
  -j4 co3-verify
```

Each SDK overlay used a dereferenced copy of its matching compiler's
`stage3/out/lib/fstar`, `fstar.exe`, and the project-pinned Z3. FunFM
`fd92b567` was built separately against each compiler/OCaml ABI and its Co3
plugin, sources, and checked library were installed into that overlay. Both
FunFM builds needed the same local, build-only compatibility patch: remove
the redundant `--include $(FSTAR_LIBDIR)/ulib.checked` from
`lang-co3/plugin/Makefile` while extracting the plugin. The patch was not
committed to FunFM.

To force the final measured target after a valid warm-up, remove only
`build/<machine>/co3/lang-co3/cache/Config.Main.co3.checked` and
`build/<machine>/co3/lang-co3/Config.Main.value.json.verify`; keep dependency
checked files. If namespace options were previously wrong, also remove
`Config.Main.deps.mk` and regenerate it before trusting the cache. This
procedure was prepared but not timed because dependency verification fails
first.

Do not use the apparent successful S2 run with an empty cache: that run lost
the namespace extension, generated an invalid dependency graph containing no
resolved `$CONFIG` modules, and did not exercise the intended dependency
verification. Current stable baseline, sharing, and canonical FunSDK runs all
reach the same `GuestMemRanges` VC: the `bounded 12` precondition lacks
usable length reasoning through four mapped lists and their nested appends.
Temporary map-length and exact-length-three refinements discharge themselves
but still do not close the final append/bounded VC. All eight
`u64_exn`-related field goals succeed. Rlimit 100 changes the reason from
timeout to `incomplete quantifiers` but does not prove it. No valid Co3 timing
comparison is reported because proving or changing this source obligation
would alter the requested benchmark.

`co3-verify` has not run in CI for some time because of performance
regressions. Recent CI therefore does not establish that it passes; the
isolated obligation may be a genuine stable proof gap.

The normal S3 `co3-extract` path succeeds on the same inputs. It concretely
evaluates `u64_exn`, emits 12 P ranges and 12 UP ranges, and reports all 16
Co3 export assertions as `PASS`. Verification fails later and differently:
`bounded`'s refined result is exposed through a `Pure` length precondition, so
F* emits an SMT/WP assertion for the call. Error 19 is
`Error_Z3SolverError`; “Assertion failed” is the SMT error reporter's generic
failed-goal message. It is not evidence that a concrete Co3 runtime exception
was thrown. Refinement subtyping can also produce an SMT assertion; the
printed VC, rather than the wording alone, identifies this one as
`bounded`'s `Pure` precondition.

## PR #4760 worst-offender reruns

`PR4760_WORST_OFFENDERS.json` records alternating local reruns of the three
largest absolute time regressions from the enabled PR comparison:
`NormBudget.rejected`, `BoolRefinement`, and `DPE.Messages.Spec`. The tests use
the actual `mk/test.mk` recipes with the existing baseline and sharing
compilers. `RAMON` was set to a GNU-time/F* memory wrapper; the commands inside
the recipes remain those recorded by the CI artifact.

The command shape for a checking target is:

```sh
PATH=/path/containing/z3-5.3.0:$PATH
rm -f _cache/BoolRefinement.fst.checked
make _cache/BoolRefinement.fst.checked \
  "RAMON=FSTAR_MEM_REPORT=$EVIDENCE_ROOT/bool.fstarmem /usr/bin/time -v -o $EVIDENCE_ROOT/bool.time"
```

The expected Custard rejection is forced similarly by removing only
`_output/NormBudget.rejected` and building that target. Do not invoke F*
directly and skip the make assertions: the target checks warning 373, its
required text, and diagnostic size.

Profiles add `OTHERFLAGS` without changing sources or expectations:

```sh
OTHERFLAGS='--profile BoolRefinement \
  --profile_component FStarC.TypeChecker \
  --profile_component FStarC.SMTEncoding \
  --profile_component FStarC.SMTEncoding.Sharing \
  --query_stats'
```

Use `--profile NormBudget --profile_component FStarC.Custard` for the
extraction rejection. DPE's command-line `OTHERFLAGS` must also repeat its
normal `--warn_error @247 --ext optimize_let_vc --ext fly_deps`; otherwise
Make command-line precedence suppresses them and the profile does not match
the measured recipe. Include `--warn_error -321` as well. Runtime GC
statistics use `OCAMLRUNPARAM=v=0x400`.
Profile and GC runs are diagnostic; do not combine their times with the
lightweight repetitions.

## Expanded PR #4760 repetitions

`run_pr4760_repeats.py` runs the actual Make targets for seven workloads,
deleting only the measured output before each invocation. It records GNU-time
process measurements, `FSTAR_MEM_REPORT`, output-artifact size, command, side, and
repetition in an append-only JSONL file. Completed
`(workload, side, repetition)` tuples are skipped on restart.

```sh
python run_pr4760_repeats.py \
  --baseline /path/to/baseline \
  --sharing /path/to/sharing \
  --z3-bin-dir /path/containing/z3-5.3.0 \
  --output /durable/results/directory \
  --repetitions 5
```

Order is deterministically shuffled within each repetition using seed
`4760 + repetition`. The selected workloads cover large absolute regressions
(`NormBudget`, `BoolRefinement`, and `DPE.Messages.Spec`) and high-percentage
regressions (`CBOR.Pulse`, `CborBoundarySlice`, `RBTreeIntrinsic`, and
`CBOR.Spec.Map`). The runner relies on each repository's existing
compiler-specific dependency cache and preserves Make's normal workload flags
and rejection checks.

`PR4760_EXPANDED_MEASUREMENTS.json` records every elapsed-time observation,
median/range, F* heap medians, artifact sizes, raw evidence hashes, and the
final conclusion.

## Fused sharing traversal optimization

`SHARING_OPTIMIZATION_MEASUREMENTS.json` compares unconditional-sharing
compiler `b3f9782a6c` with optimized commit `befb3db820`. The optimized
interner fuses child interning, canonical list construction, and list hashing,
and preserves original nodes/list cells when canonical children are
physically unchanged. Canonical-table lookup remains unconditional.

Synthetic total-time measurements use five deterministically shuffled
no-write repetitions per compiler and workload. Diagnostic pass/allocation
profiles use five separate runs. Two ordinary modules use five write and five
no-write repetitions per compiler. Raw measurements remain in session
storage; their hashes are recorded in the JSON.

Structural validation runs the existing exact-sharing experiment on each
pre-optimization and optimized checked artifact. That tool verifies the
complete metadata/index/declaration values before and after recovery. The
recovered BV pair and UInt pair are byte-identical, which establishes
structural equivalence while allowing physical sharing and the outer digest
to differ.

The combined compiler optimization was subsequently reverted from PR #4760.
`FUSION_REUSE_ISOLATION.json` compares the original implementation, a
fusion-only experiment, and the existing combined fusion+reuse evidence. The
fusion-only compiler is on
`users/amos/20261022-fstar-smt-sharing-fusion`; it is not a PR branch.

The decisive isolation uses one executable containing renamed extracted
copies of all three implementations. It measures pass-local wall/CPU and GC
allocation deltas on the same already-loaded declarations/index, with 30
shuffled repetitions per artifact. This avoids compiler-binary, solver, and
input-construction differences while measuring the algorithm itself.

`sharing_pass_bench.ml` is the driver. Build it in the compiler's Dune
workspace with three extracted modules named `Sharing_original`,
`Sharing_fusion`, and `Sharing_combined`, copied respectively from
`b3f9782a6c`, `206126a6dd`, and `befb3db820`. The evidence JSON records their
extracted-module and executable hashes. The generated files are:

```text
stage3/dune/_build/default/fstar-guts/fstarc.ml/FStarC_SMTEncoding_Sharing.ml
```

Copy that path from each built worktree as
`sharing_original.ml`, `sharing_fusion.ml`, and `sharing_combined.ml` into a
temporary directory under `stage3/dune`, copy `sharing_pass_bench.ml` there,
and use this stanza:

```lisp
(executable
 (name sharing_pass_bench)
 (libraries fstarcompiler unix))
```

Build and run from `stage3/dune`:

```sh
dune build sharing-bench/sharing_pass_bench.exe
_build/default/sharing-bench/sharing_pass_bench.exe \
  /path/to/BenchBvLive500.fst.checked 30 > bv.csv
_build/default/sharing-bench/sharing_pass_bench.exe \
  /path/to/BenchUIntLive500.fst.checked 30 > uint.csv
```

The measured checked-input SHA-256 values are `bc400558...ad6d` for BV and
`41ed0673...87bd` for UInt.

## Matched whole-program analysis

`run_matched_variants.py` runs shuffled write/no-write measurements for two
identical-source original rebuilds, fusion-only, and fusion+reuse. It rejects
and retries observations when one-second command-line polling flags another
F* executable on the shared host; false positives and short missed overlaps
remain possible.

`run_matched_profiles.py` collects intrusive typechecker/SMT/query/GC profiles.
For its audited `matched-instrumented` binaries,
`instrument_extracted_analysis.py --sharing-only` added just the production
interning timing/allocation wrappers. Restore clean extracted ML, then run the
script without that flag to build the distinct `matched-instrumented-phases`
binaries used by `run_matched_detailed_phases.py`; those also time final fresh
encoding, pruning summary/index, solver registration, and checked-file
storage. Both modes modify ignored extracted compiler ML only.

```sh
mkdir -p "$EVIDENCE_ROOT/matched-instrumented" \
         "$EVIDENCE_ROOT/matched-instrumented-phases"
python instrument_extracted_analysis.py --sharing-only \
  /workspace/wt11/FStar-sharing-VARIANT
(cd /workspace/wt11/FStar-sharing-VARIANT/stage3/dune &&
  dune build fstarc-full/fstarc3_full.exe)
cp /workspace/wt11/FStar-sharing-VARIANT/stage3/dune/_build/default/\
fstarc-full/fstarc3_full.exe \
  "$EVIDENCE_ROOT/matched-instrumented/fstar-VARIANT.exe"

# Restore the three generated ML files from the clean stage1 extraction:
for file in FStarC_SMTEncoding_Sharing.ml FStarC_SMTEncoding_Encode.ml \
            FStarC_CheckedFiles.ml; do
  cp /workspace/wt11/FStar-sharing-VARIANT/stage1/fstarc.ml/$file \
     /workspace/wt11/FStar-sharing-VARIANT/stage2/fstarc.ml/$file
done
# Then build the detailed-phase binary:
python instrument_extracted_analysis.py \
  /workspace/wt11/FStar-sharing-VARIANT
(cd /workspace/wt11/FStar-sharing-VARIANT/stage3/dune &&
  dune build fstarc-full/fstarc3_full.exe)
cp /workspace/wt11/FStar-sharing-VARIANT/stage3/dune/_build/default/\
fstarc-full/fstarc3_full.exe \
  "$EVIDENCE_ROOT/matched-instrumented-phases/fstar-VARIANT.exe"
```

`run_matched_ordinary.py` measures the two ordinary controls. After all raw
runs complete, regenerate and validate the structured report:

```sh
python summarize_matched_analysis.py \
  --evidence-root /home/amosrobinson/.copilot/session-state/\
7081de44-8211-4e82-806b-f466934ac8a6/files \
  --worktree-prefix /workspace/wt11/FStar-sharing \
  --z3 /home/amosrobinson/.copilot/session-state/\
7081de44-8211-4e82-806b-f466934ac8a6/files/bin/z3-5.3.0
python -m json.tool MATCHED_END_TO_END_ANALYSIS.json >/dev/null
```

`MATCHED_END_TO_END_ANALYSIS.json` contains the complete five-run
write/no-write observations, three-run broad profiles, two-run detailed phase
measurements, ordinary controls, provenance, and evidence hashes.

For the audited run, `/workspace/wt11/FStar-sharing` was the worktree prefix,
`/workspace/wt11/FStar/tests/benchmarks/compiler-encoding/_generated` held the
sources, the evidence root was
`/home/amosrobinson/.copilot/session-state/7081de44-8211-4e82-806b-f466934ac8a6/files`,
and Z3 was that root's `bin/z3-5.3.0`. The output subdirectories were
`matched-e2e-isolated`, `matched-profiles`, `matched-detailed-phases`, and
`matched-ordinary`; broad/detailed instrumented binaries were respectively in
`matched-instrumented` and `matched-instrumented-phases`.

Run the campaigns from this directory (all paths are examples):

```sh
python run_matched_variants.py \
  --worktree-prefix /workspace/wt11/FStar-sharing \
  --generated "$PWD/_generated" --output "$EVIDENCE_ROOT/matched-e2e" \
  --z3-bin-dir /path/to/z3/bin --repetitions 5

python run_matched_profiles.py \
  --worktree-prefix /workspace/wt11/FStar-sharing \
  --instrumented-dir "$EVIDENCE_ROOT/matched-instrumented" \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/matched-e2e" \
  --output "$EVIDENCE_ROOT/matched-profiles" \
  --z3-bin-dir /path/to/z3/bin --repetitions 3

python run_matched_detailed_phases.py \
  --worktree-prefix /workspace/wt11/FStar-sharing \
  --instrumented-dir "$EVIDENCE_ROOT/matched-instrumented-phases" \
  --generated "$PWD/_generated" \
  --cache-root "$EVIDENCE_ROOT/matched-e2e" \
  --output "$EVIDENCE_ROOT/matched-phases" \
  --z3-bin-dir /path/to/z3/bin --repetitions 2

python run_matched_ordinary.py \
  --worktree-prefix /workspace/wt11/FStar-sharing \
  --output "$EVIDENCE_ROOT/matched-ordinary" \
  --z3-bin-dir /path/to/z3/bin \
  --repetitions 5
```

Original A/B and combined were made as detached worktrees at their commits;
original A and B both use `b3f9782a6c`. Fusion uses the existing compiler
built from the fusion-only diff immediately before it was committed unchanged
as `206126a6dd`; its embedded version therefore reports
`b3f9782a6c-dirty`. The extracted-module hash audits the exact measured
implementation. Each matched rebuild copied the completed
OCaml-4.14.2 `stage0` through `stage3` trees from the fusion worktree using
`cp -a --reflink=auto`, touched only
`src/smtencoding/FStarC.SMTEncoding.Sharing.fst`, and resumed:

```sh
git -C /path/to/FStar worktree add --detach /workspace/wt11/FStar-sharing-VARIANT COMMIT
git -C /workspace/wt11/FStar-sharing-VARIANT submodule update --init --recursive
for stage in stage0 stage1 stage2 stage3; do
  cp -a --reflink=auto \
    /workspace/wt11/FStar-sharing-fusion/$stage \
    /workspace/wt11/FStar-sharing-VARIANT/$stage
done
touch /workspace/wt11/FStar-sharing-VARIANT/src/smtencoding/\
FStarC.SMTEncoding.Sharing.fst
cd /workspace/wt11/FStar-sharing-VARIANT
PATH=/path/containing/z3-5.3.0:$PATH make -j8 3
```

The build-log, executable, solver, and extracted-module hashes in the JSON
audit this setup. Original A/B's extracted sharing modules are byte-identical
while their final executables differ, providing the build-noise control.

To audit the isolated-pass input, run `sharing_experiment.exe INPUT OUTPUT`
twice: first on the production checked artifact, then on `OUTPUT`. The first
pass verifies structural equality and the second establishes the recovered
digest fixed point. Production ordering is visible in
`FStarC.SMTEncoding.Encode.encode_modul_aux`; checked storage is in
`FStarC.CheckedFiles.store_module_to_cache`.

```sh
sharing_experiment.exe INPUT.checked RECOVERED.checked > recovery.log
sharing_experiment.exe RECOVERED.checked RECOVERED2.checked > fixed-point.log
```

The `input_audit_*` hashes in the JSON identify these logs, not the recovered
checked artifacts.

## Clean sharing branch benchmarks

`CLEAN_SHARING_MEASUREMENTS.json` compares untouched upstream
`5275509e26` with clean commit `f4decbb8c2` on
`users/amos/20261022-fstar-smt-sharing`. That clean branch contains only
`FStarC.SMTEncoding.Sharing` and its opt-in `Encode.encode_modul_aux`
integration.

Synthetic and ordinary baseline runs use the same generated/source files,
flags, explicit Z3 5.3.0 binary, uncached measured target, and prechecked
dependencies. Each configuration alternates three `write` and `no-write`
runs. Sharing runs add only:

```sh
--ext smtencoding:share=true
```

Persistence subphases are diagnostic rather than baseline timings:

```sh
sharing_experiment.exe --persistence-profile \
  INPUT.checked OUTPUT.checked
```

This mode loads an existing artifact, then separately times Marshal
serialization of stage 1/2 and SMT declarations, Merkle hashing, and a
buffered file write. It verifies structural round-trip equality. The write is
atomically renamed into place but does not call `fsync`, so it estimates CPU
serialization/hash and page-cache write cost rather than durable-storage
latency.

Checked-file read/unmarshal cost can be isolated with the same executable:

```sh
sharing_experiment.exe --load-metadata INPUT.checked
sharing_experiment.exe --load-smt INPUT.checked
```

`--load-metadata` reads stage 1/2, including the checked module and pruning
index. `--load-smt` seeks past stage 1/2 and unmarshals the lazy third-value
SMT declaration payload. Run under `/usr/bin/time -v` to capture whole-process
wall/RSS; the program's internal timer isolates the load function. Reported
runs use warm filesystem caches and do not flush the host page cache.
