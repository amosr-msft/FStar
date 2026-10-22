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
  'RAMON=FSTAR_MEM_REPORT=/tmp/bool.fstarmem /usr/bin/time -v -o /tmp/bool.time'
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
