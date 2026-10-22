# Compiler encoding benchmarks

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
