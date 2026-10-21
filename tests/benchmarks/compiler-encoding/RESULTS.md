# Sparse controls and representative live workload

Measured on 2026-10-21 at F* commit
`5275509e26b2e4c3df3ade7df1e01b3e38f9553a` with OCaml 5.2.1, Z3 5.3.0,
`--smtencoding.elim_box true`, prechecked dependencies, and an uncached target.
The host was an AMD EPYC 7763 VM with 32 logical CPUs and 125 GiB RAM.

Both generator versions use seed `20261021`, 50 input fields, 120 state fields,
25 output fields, ten child calls, and widths `{1,4,8,16,32,64,128}` with many
one-bit fields.

## Version 1 sparse-reachability control

Version 1 is preserved byte-for-byte. Graph analysis confirms it is a shallow
control, not the requested representative transition workload:

| Bindings | Reachable generated bindings | Maximum dependency depth |
|---:|---:|---:|
| 100 | 42 (42.0%) | 3 |
| 250 | 69 (27.6%) | 4 |
| 500 | 91 (18.2%) | 6 |
| 1,000 | 147 (14.7%) | 8 |

Its single write-mode sweep was:

| Bindings | BV wall | BV peak RSS | BV `.checked` | UInt wall | UInt peak RSS | UInt `.checked` |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 2.77 s | 278 MiB | 2.25 MiB | 2.99 s | 294 MiB | 2.06 MiB |
| 250 | 2.63 s | 315 MiB | 2.50 MiB | 8.22 s | 516 MiB | 2.21 MiB |
| 500 | 3.81 s | 544 MiB | 2.85 MiB | 39.52 s | 1,091 MiB | 2.44 MiB |
| 1,000 | 10.11 s | 1,438 MiB | 3.69 MiB | 364.06 s | 3,462 MiB | 2.91 MiB |

Three no-write repetitions at 500 bindings gave medians of 3.94 s and 523 MiB
for BV versus 40.54 s and 1,073 MiB for UInt. Diagnostic profiling attributed
the UInt cost to phase-2 VC simplification and primitive normalization; all
reported solver queries were below 0.01 s. This diagnosis applies to the
sparse-control expression shape.

The four 400-literal controls measured:

| Workload | Wall | Peak RSS | `.checked` |
|---|---:|---:|---:|
| Assertions only | 1.99 s | 262 MiB | 0.23 MiB |
| Refined bindings with assertions | 9.01 s | 654 MiB | 0.46 MiB |
| Refined bindings without assertions | 0.57 s | 185 MiB | 0.13 MiB |
| Direct BV constructions | 0.56 s | 186 MiB | 0.13 MiB |

The closed-size simplifier in
`src/typechecker/FStarC.TypeChecker.Primops.MachineInts.fst` decides literal
range predicates by bit length. Direct BV literals and explicit refinement
ascriptions have no demonstrated isolation penalty here. Repeated
`assert_norm` inside the nested sparse term was expensive: BV-1000 took 89.51
s and 3.33 GiB RSS with assertions versus 10.11 s and 1.40 GiB with direct
literals.

## Version 2 representative live workload

Version 2 adds one generated dependency chain per concrete width. Every
chain's latest binding is referenced by final outputs and reset/enable state
updates. The manifest computes reachability and depth from the actual graph:

| Bindings | Reachable generated bindings | Maximum dependency depth |
|---:|---:|---:|
| 100 | 100 (100%) | 28 |
| 250 | 250 (100%) | 79 |
| 500 | 500 (100%) | 129 |
| 1,000 | 1,000 (100%) | 268 |

The 1,000-binding primary schedule has exactly 300 conditionals, 150 extracts,
100 concatenations, 50 replications, five modular additions, five dynamic
shifts, and 390 bitwise operations. Extract/concat/repeat expressions also
have an auxiliary same-width XOR that keeps their result on the live chain.
Rising-edge, reset, and enable conditions come from previous/current one-bit
inputs and drive generated conditionals and synchronous state updates.

The final 1,000-binding BV and UInt source hashes are
`27df0287e51093829bb31f11d4de63535ca2930337b4336809e120693a795d49`
and `ad24b485152ca343a58c46c0a3305f80cab990219267c771abef79f19be5794d`.
Their common representation-neutral plan hash is
`8310efd1c5d3d05c7638c687414b3a1919aa58a60bf0b7b5e5401d5ff86ecc8f`.
The completed measurement rows were produced immediately after generating
these sources, but that runner version did not yet include source hashes in
JSONL, so the archived rows are not independently self-authenticating. The
runner now records `source_sha256` for subsequent measurements.

Completed final dynamic-shift write-mode measurements are:

| Bindings | BV wall | BV peak RSS | BV `.checked` | UInt wall | UInt peak RSS | UInt `.checked` |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 3.35 s | 335 MiB | 6.38 MiB | 3.34 s | 308 MiB | 2.62 MiB |
| 250 | 5.50 s | 589 MiB | 12.40 MiB | 5.13 s | 460 MiB | 3.37 MiB |
| 500 | 35.76 s | 1,466 MiB | 20.87 MiB | 27.02 s | 1,302 MiB | 4.41 MiB |

The final BV-1,000 write run did not complete. It was externally interrupted
after 19 minutes 28 seconds while `fstar.exe` still used one CPU and about 3.3
GiB RSS. The 1,200-second harness timeout had not fired, its timing file was
empty, no JSONL row was recorded, and no checked artifact was produced.
UInt-1,000 was therefore not started. This is not a measured full-run time.

An earlier version 2 prototype used constant rather than dynamic shifts. Its
BV/UInt 1,000-binding write medians were 20.14 s/40.32 MiB and 17.51 s/6.79
MiB. These values show that making all bindings live steepened exported-size
growth, but they do not measure the final sources and are excluded from the
final table.

The sparse control made UInt much slower, while completed live measurements
made BV slower and larger. Neither supports a general UInt-versus-BV winner:
operation mix, liveness, dependency depth, and shift representation materially
change the result.

## Encoding size and remaining gap

The sparse BV-1000 3.69 MiB checked file printed as 6.40 MB through
`--read_checked_file`; 6.23 MB was the exported SMT declaration AST. The
120-field `state_t` record accounted for 4.24 MB and the sparse `step` for 1.12
MB. Large records export constructor, typing, inversion, discriminator, and
projection facts for every field.

The largest completed final artifact is 20.87 MiB at BV-500, still far below
500 MB. The constant-shift live prototype reached 40.32 MiB at BV-1000, but
the final dynamic-shift BV-1000 run did not finish, so its size is unknown.
The final workload also remains well below the reported approximately
200-second real workload through 500 bindings.

Inspecting the 40.32 MiB prototype artifact with `--read_checked_file` did not
finish after 20 minutes 40 seconds at 100% of one CPU and roughly 1.3 GiB RSS;
it emitted only 177 KiB before its orphaned process was terminated. Checking
and cache generation had already completed in about 20 seconds, so the stall
is not module checking or cache writing. The partial output reached
`Checked module:` but never `SMT decls:` and ends within the checked-module
text. The available evidence therefore does not distinguish checked-module
output from subsequent loading or formatting of the third SMT payload.

`FStarC.Universal.tc_source_file` checks the module and then calls
`encode_modul`. `FStarC.CheckedFiles.store_module_to_cache` persists the
checked module and `module_encoding`, whose `me_decls` field is documented as
the bulk encoding. `FStarC.Util.save_3values_to_file` separately marshals,
hashes, and writes checked metadata and the SMT payload. Process RSS,
marshalled `.checked` size, printable exported AST, and dependency-expanded
SMT-LIB queries are therefore not interchangeable.

The original approximately 500 MB remains unexplained. A follow-up needs the
original artifact or an observation that identifies which of those quantities
was measured.

## Checked-file anatomy

The exact 40.32 MiB constant-shift prototype artifact no longer exists. The
later uncached final BV-1,000 attempt removed it before checking and did not
produce a replacement. The largest surviving matched artifacts are the final
dynamic-shift BV-500 and UInt-500 files. Their 55,437-byte and 56,991-byte
sources expand to 20.87 MiB and 4.41 MiB checked files: amplification factors
of 395 and 81 respectively.

Checked files contain a marshalled digest, a byte count, and three marshalled
values. Stage 1 contains the cache version, source digest, and parsing data.
Stage 2 contains dependency digests, the checked syntax module, inclusion
information, the eager SMT pruning index, and SMT fvar bindings. The third
value is the full exported SMT declaration list.

| Container value | BV-500 bytes | BV share | UInt-500 bytes | UInt share |
|---|---:|---:|---:|---:|
| Stage 1: cache/source/parsing data | 18,533 | 0.08% | 18,330 | 0.40% |
| Stage 2: dependencies and checked result | 6,378,921 | 29.15% | 1,207,394 | 26.14% |
| Exported SMT declarations | 15,489,153 | 70.77% | 3,393,496 | 73.46% |

The OCaml Marshal headers report the number of serialized heap objects and the
64-bit heap words required to unmarshal each value. These are format-provided
in-memory estimates, not measured RSS. BV's metadata and SMT values report
1,019,398 and 3,016,725 objects, with about 25.10 MiB and 73.06 MiB of
64-bit heap words. UInt reports 163,783 and 915,425 objects, with about 4.35
MiB and 20.39 MiB of heap words.

Re-marshalling the second value's fields separately shows what makes BV
metadata large. The values are not additive because separately marshalling
them changes cross-field sharing.

| Metadata field | BV-500 | UInt-500 |
|---|---:|---:|
| Checked syntax module | 873,066 bytes | 954,671 bytes |
| Inclusion information | 20,055 bytes | 20,055 bytes |
| SMT pruning index | 23,761 entries / 5,481,833 bytes | 2,128 entries / 229,606 bytes |
| SMT fvar bindings | 233 / 50,907 bytes | 233 / 52,729 bytes |

The checked syntax module is therefore not the BV/UInt size difference. The
dominant difference is exported SMT declarations and their eager index. A
bounded traversal of the third value found:

| Exported structure | BV-500 | UInt-500 |
|---|---:|---:|
| Declaration blocks | 23,761 | 2,128 |
| Flattened declarations | 154,840 | 3,409 |
| `Assume` declarations | 45,075 | 1,809 |
| `DeclFun` declarations | 44,149 | 883 |
| `DefineFun` declarations | 21,645 | 12 |
| Term occurrences | 939,508 | 365,413 |
| Maximum term depth | 261 | 197 |

The same live expression is present in both artifacts: for example, the
bounded traversal counted 3,704 BV XOR applications and 3,704 UInt
`logxor` applications. The main step equation is also comparable in size
(173,330 BV versus 183,326 UInt term occurrences). BV is larger because every
native BV primitive encoding calls `bv_size_decls` for its input/result
widths. Those blocks declare the width-specific `BoxBitVecN` constructor and
projection and add typing-inversion facts. In BV-500, width-one alone appears
in 12,163 such keyed blocks; the other common widths appear thousands of
times.

This repetition is directly visible in the hash-consing keys: 21,854 BV
declaration blocks are keyed, but they contain only 40 unique keys, leaving
21,814 duplicate keyed blocks. UInt has 221 keyed blocks, 33 unique keys, and
188 duplicates. During module registration, `give_index_to_z3_and_set_env`
uses the index keys to drop duplicates before declarations are handed to Z3.
However, `encode_modul_aux` builds the post-check exported encoding with
`encode_top_level_facts`, summarizes every block, and retains the full
declaration list for the checked file. Thus the artifact stores both the
repeated declarations and one eager summary per block even though the solver
registration path deduplicates them before sending declarations to Z3.

`Marshal.to_string value []` preserves existing physical sharing with
backreferences. It does not structurally hash-cons separately allocated but
equal blocks and does not compress the payload. Consequently sharing within a
constructed term survives serialization, while the thousands of independently
constructed equal `bv_size_decls` blocks remain distinct. This explains both
the 14.77 MiB third value and the otherwise surprising 5.48 MiB pruning index
for a 55 KiB source.

## Experimental exact-sharing recovery

`sharing_experiment.ml` tests the narrow hypothesis that recovering physical
sharing before serialization shrinks checked files. It recursively rebuilds
SMT terms, declarations, declaration blocks, pruning summaries, and index
entries, replacing structurally equal values with a canonical physical
object. It preserves list lengths, declaration/index ordering, names, ranges,
and every declaration. It does not remove duplicate-key blocks or attempt
alpha-equivalence, so key equality alone never authorizes sharing.

The pass requires distinct input and output paths, so it cannot overwrite the
input artifact. Before saving and after reloading, it checks structural equality of
the full SMT declaration list, full pruning index, and both metadata stages.
F* successfully loaded both shared artifacts as cached dependencies and
verified a dependent module with an SMT query (`excluded_middle`, reported by
`--query_stats`). The prototype's `--load` mode separately forced and loaded
both shared SMT payloads.

| Artifact | Original | Shared | Reduction | Pass wall | Peak RSS |
|---|---:|---:|---:|---:|---:|
| BV-500 | 21,886,665 B | 2,150,246 B | 90.2% | 4.74 s | 160 MiB |
| UInt-500 | 4,619,278 B | 1,876,955 B | 59.4% | 1.67 s | 83 MiB |

For BV, structural canonicalization found reuse for 915,764 of 939,508 visited
term occurrences, 150,978 of 154,840 declarations, 21,554 of 23,761
declaration blocks, 152,852 of 154,840 pruning summaries, and 23,012 of
23,761 index entries. These are hash-cons hits during a bottom-up pass, not
counts of declarations removed.

| Container value | BV original | BV shared | UInt original | UInt shared |
|---|---:|---:|---:|---:|
| Stage 1 | 18,533 B | 18,533 B | 18,330 B | 18,330 B |
| Stage 2 | 6,378,921 B | 1,144,512 B | 1,207,394 B | 1,142,640 B |
| SMT declarations | 15,489,153 B | 987,143 B | 3,393,496 B | 715,927 B |

The experiment confirms that exact sharing, without changing logical
contents, recovers most of the BV artifact's redundancy. It also shrinks UInt,
showing substantial repeated term structure beyond BV's width declarations.
After sharing, the BV/UInt files are 2.15/1.88 MB; the large representation
gap nearly disappears, though BV still has all 23,761 declaration and index
entries.

Loading both metadata and the forced SMT payload also improved:

| Artifact | Load wall | Peak RSS |
|---|---:|---:|
| BV original | 0.177 s | 160 MiB |
| BV shared | 0.029 s | 35 MiB |
| UInt original | 0.053 s | 59 MiB |
| UInt shared | 0.027 s | 33 MiB |

These are standalone process measurements and include startup. The pass itself
uses structural hashing/equality and temporarily holds original and recovered
graphs, so its bounded memory/time cost should not be interpreted as a
production implementation result. The remaining ~2 MB includes all list
spines, names, stage-1 data, checked syntax, and structurally distinct terms;
this experiment intentionally does not test key-based declaration removal.

Re-serialization recomputes the checked file's outer Merkle digest. Although
the values are structurally equal, the different physical sharing changes the
marshalled bytes and therefore the digest. Existing downstream checked files
that recorded the original digest will be invalidated and must be rebuilt. BV
changed from `f20e9c5031f035597f4d7dffad808b5b` to
`935e7f796bbd89839ee94ad09a7e7e04`; UInt changed from
`423d1ac2ce9ac5255d73d1a7e16e7f38` to
`32912d2b5dd9fbae4ada93ac263a90f0`.

## Construction-time BV support reuse

The focused compiler experiment memoizes `bv_size_decls` results while
encoding a module. Its key is `(current_module_name, width)`: width determines
the `BoxBitVecN` constructor, while the module name scopes generated symbols.
The mutable table belongs to the SMT encoding environment, is copied by
environment snapshots, and is cleared together with the module fresh-name
counter before whole-module export. Cache hits consume the skipped fresh name
so later generated names retain their sequence. Every declaration-list
occurrence remains in its original position; only the referenced immutable
block is physically reused.

The unchanged baseline is the final dynamic-shift BV-500 run above. The
modified compiler used the identical source and flags. The source SHA-256 was
`18cdc6ee13d09da41f99b773151fadae607bd3f899e6e39f3085565471c3ecb1`;
the exact command and uncommitted compiler-diff hash are retained with the raw
results. The baseline artifact's stored source digest is
`bb5eeaca1cd04d52f64300ffc91d1464`, equal to the current BV-500 source MD5,
and the modified artifact records the same digest. This authenticates the
source used by both artifacts even though the older measurement JSON row did
not record SHA-256 directly.

| BV-500 | Baseline | Construction reuse | Change |
|---|---:|---:|---:|
| Write wall | 35.76 s | 35.44 s median (3 runs) | -0.9% |
| `step` timer | 31.76 s | 31.93 s median | +0.5% |
| Peak RSS | 1,466 MiB | 1,304 MiB | -11.1% |
| `.checked` | 21,886,665 B | 9,165,709 B | -58.1% |

Modified no-write runs had a 35.22 s median, 0.22 s below the write median.
The difference includes timing noise as well as serialization/hash/write, and
the baseline had no matching no-write repetition.

| Container value | Baseline | Construction reuse | Reduction |
|---|---:|---:|---:|
| Stage 1 | 18,533 B | 18,533 B | 0% |
| Stage 2 | 6,378,921 B | 3,794,656 B | 40.5% |
| SMT declarations | 15,489,153 B | 5,352,462 B | 65.4% |
| Re-marshalled pruning index | 5,481,833 B | 2,897,568 B | 47.1% |

Applying the general post-hoc sharing pass after construction reuse reduces
9,165,709 B further to 1,974,932 B. Relative to that result, targeted
construction reuse captures 63.9% of the recoverable byte reduction. Residual
redundancy includes equal terms and summaries outside `bv_size_decls`, plus
list spines and other independently allocated structures; the focused change
intentionally does not intern them.

The UInt-500 control is byte-identical at 4,619,278 B. Its single modified run
was 28.11 s / 1,302 MiB versus the earlier 27.02 s / 1,302 MiB baseline, which
is consistent with no size or memory effect and normal single-run timing
variation.

The baseline and modified BV pruning indexes are structurally equal, as are
SMT fvar bindings and inclusion information. The first physically reused
support block has the same hash-consing key and renders to identical SMT. The
checked syntax module and raw declaration AST are not structurally byte-stable
because reuse changes range/fresh metadata, but solver-visible support blocks
retain their names, keys, and order. The focused `BvBinaryOps` test, exact-tree
compiler `boot-diff`, and a dependent SMT query loaded from the modified
checked file all pass.

## Experimental general SMT interning

The opt-in general prototype (`--ext smtencoding:share=true`) replaces the
BV-specific cache with one exact structural interning pass over the completed
exported `decls_t`, immediately before pruning-index construction. A second
pass interns the derived index. Per-module tables cover terms, declarations,
declaration blocks, declaration summaries, and index entries; they are
discarded after export. This boundary is independent of encoding environments,
snapshots, solver resets, modules, and fresh-name scopes.

The pass preserves every list entry and its order. It uses ordinary structural
equality, including names, ranges, and labels—not encoding keys, SMT semantic
hashes, or alpha-equivalence. Equality first checks physical identity and
treats opaque/function-containing values that reject structural comparison as
non-shareable. Checked modules, inclusion data, fvar bindings,
indexes, and declaration ASTs are structurally equal to the original
pre-optimization artifacts on BV-500, UInt-500, and all three ordinary
controls. Synthetic dependency digests differ because their child artifacts
were rebuilt; ordinary controls have equal dependency digests.

Compared with three fresh runs of the BV-only compiler on identical sources:

| Live-500 | BV-only median | General median | Change |
|---|---:|---:|---:|
| BV write wall | 34.79 s | 39.81 s | +14.4% |
| BV max-process RSS | 1,302 MiB | 1,277 MiB | -1.9% |
| BV `.checked` | 9,165,709 B | 2,136,307 B | -76.7% |
| UInt write wall | 27.82 s | 29.20 s | +5.0% |
| UInt max-process RSS | 1,300 MiB | 1,254 MiB | -3.5% |
| UInt `.checked` | 4,619,278 B | 1,862,553 B | -59.7% |

The standalone post-hoc sharing pass makes no further byte or digest change to
either general artifact. General construction-time interning therefore
recovers all exact sharing found post hoc and subsumes the BV-specific cache
without fresh-name replay. It also closes the synthetic BV/UInt artifact gap.
With the option absent, final BV and UInt artifacts are byte-identical to
those produced by the BV-only compiler.

Profiling attributes 4.55 s / 24 ms of BV-500 and 1.42 s / 1 ms of UInt-500
to declaration/index interning. This accounts for the total-time regression.
On ordinary
non-BV modules, declaration/index passes cost only 3–20 ms / 0–1 ms:

| Ordinary module | BV-only size | General size | Size change | Wall medians |
|---|---:|---:|---:|---:|
| `Positivity` | 931,243 B | 691,714 B | -25.7% | 1.05 / 1.07 s |
| `ClassicalSugar` | 605,436 B | 502,130 B | -17.1% | 1.30 / 2.10 s |
| `TestWellFoundedRecursion` | 681,964 B | 516,209 B | -24.3% | 0.96 / 0.93 s |

`ClassicalSugar` timings were highly variable (general 1.36–2.40 s) despite a
3 ms measured sharing pass, so that median difference is not attributable to
interning. These controls show useful size reductions beyond BV/UInt without
meaningful pass cost at their scale.

Dependent loading of general artifacts is essentially the same as post-hoc
sharing: BV metadata/rooted medians are 0.184 s / 1.242 s at 104.9 / 242.1 MiB
maximum-process RSS; UInt is 0.172 s / 1.096 s at 102.3 / 228.1 MiB.

This prototype remains opt-in because its current cost is too high for a
default optimization. OCaml polymorphic structural hashing/equality revisits
large subtrees and temporarily holds the original and rebuilt graphs. Equality
uses a physical fast path and treats opaque/function-containing values that
reject structural comparison as non-shareable, avoiding a new error-reporting
failure mode. A production design should retain this common boundary but use
typed cached hashes, or a bottom-up hash-cons representation that computes
each node's hash once. Thresholding the pass by declaration count is another
option, but the ordinary-module reductions show that a BV-only policy would
leave general benefits behind. List spines, checked syntax modules, fvar
bindings, and stage-1 data remain outside this prototype's coverage.
Final validation includes exact-tree `boot-diff`, opt-in `BvBinaryOps` and
`ClassicalSugar`, structural artifact comparisons for all measured modules,
and dependent rooted queries loaded from both general synthetic artifacts.

### Efficient F* reimplementation

The initial common-boundary prototype at commit `b1fe663037` used recursive
OCaml polymorphic hashing/equality. The replacement is an ordinary F*
implementation using `FStarC.Hash`, `FStarC.HashTable`, and
`FStarC.Util.physical_equality`. Recursive workers return each rebuilt node
with a cached bottom-up hash; parent hashes combine child hashes once, and
collision buckets use explicit typed equality over canonical child pointers.
Hash collisions therefore never authorize merging unequal values.

Ranges compare and hash both definition and use locations. Abstract lidents
compare only by physical identity, conservatively preserving unexposed cached
fields. All SMT constructors and pruning-summary variants are handled
explicitly. Opaque
diagnostic messages in `Labeled` terms are neither traversed, rendered, nor
structurally compared: they share only when physically identical and use a
constant hash contribution. The superseded handwritten OCaml runtime was
removed.

Compared with three identical runs of `b1fe663037`:

| Live-500 opt-in | OCaml prototype | F* interner | Change |
|---|---:|---:|---:|
| BV write wall | 39.81 s | 34.76 s | -12.7% |
| BV max-process RSS | 1,277 MiB | 1,277 MiB | -0.02% |
| BV declaration/index pass | 4.55 s / 24 ms | 0.228 s / 27 ms | -95.0% declarations |
| BV `.checked` | 2,136,307 B | 2,136,307 B | unchanged |
| UInt write wall | 29.20 s | 27.14 s | -7.1% |
| UInt max-process RSS | 1,254 MiB | 1,254 MiB | +0.05% |
| UInt declaration/index pass | 1.42 s / 1 ms | 0.082 s / 1 ms | -94.2% declarations |
| UInt `.checked` | 1,862,553 B | 1,862,553 B | unchanged |

Against the default BV-only path in the exact same final compiler, F* general
interning adds 1.3% wall time for BV-500 (34.32 to 34.76 s) and 0.7% for
UInt-500 (26.95 to 27.14 s). Artifact reductions remain 76.7% and 59.7%.

The F* and OCaml implementations produce structurally equal checked modules,
indexes, fvar bindings, and declaration ASTs on both synthetic workloads and
all ordinary controls. Applying the standalone sharing pass to the F*
artifacts produces no further byte reduction, although Marshal digests differ
because the exact physical-sharing topology is not identical.

Final same-compiler ordinary-module default/general medians are 0.983/0.997 s
(`Positivity`), 1.057/1.062 s (`ClassicalSugar`), and 0.875/0.885 s
(`TestWellFoundedRecursion`). Declaration pass costs are 10, 2, and 4 ms;
index costs are 1, 0, and 1 ms. Their checked sizes remain approximately
17–26% below the default compiler.

With the exact final compiler and artifacts, BV dependent metadata/rooted
medians are 0.179/1.229 s at 104.1/240.2 MiB; UInt medians are 0.164/1.085 s
at 101.7/227.5 MiB.

The efficient implementation substantially reduces the earlier cost without
sacrificing sharing or exact collision checks. It remains opt-in because
BV-500 still has measurable overhead and broader error-reporting/plugin
coverage is warranted before changing the default.

The standard build, exact `boot-diff`, opt-in `BvBinaryOps`, and opt-in
`ClassicalSugar` pass. A broader `make test-3` run did not complete: the
Custard `TypeDiverge` rejection expected diagnostic 365 but encountered a
stack overflow. No baseline full-suite run was made, so this failure is
unclassified rather than claimed as pre-existing. The tracked
`GENERAL_SHARING_MEASUREMENTS.json` records tool/source hashes, medians,
profiles, and this validation outcome.

## Dependent-file loading

The same modified compiler and Z3 5.3.0 checked one identical uncached
dependent source against each BV artifact. Each isolated cache contained the
matching child checked file and exactly one `BenchBvLive500.fst.checked`; logs
confirm that dependency was loaded successfully rather than rechecked. Seven
sequential repetitions used warm filesystem caches.

Two modes separate eager metadata loading from lazy payload use:

- **Metadata:** the target query is admitted. F* reads stage 2 and installs the
  deferred encoding, but starts no Z3 process and does not force `me_decls`.
- **Rooted:** an excluded-middle query mentions `(B.step ...).state`. With
  normal context pruning enabled, this resolves the exported `step`, forces
  the full third value, registers relevant declarations, and runs a
  negligible (<0.01 s reported) solver query.

| BV dependency | Metadata wall | Metadata max-process RSS | Rooted wall | Rooted max-process RSS |
|---|---:|---:|---:|---:|
| Original, 21.89 MB | 0.229 s | 130.9 MiB | 1.466 s | 327.7 MiB |
| Construction reuse, 9.17 MB | 0.218 s | 120.3 MiB | 1.330 s | 274.3 MiB |
| Post-hoc exact sharing, 2.15 MB | 0.188 s | 103.9 MiB | 1.256 s | 240.3 MiB |

Construction reuse therefore reduces end-to-end rooted dependent checking by
9.3% and maximum-process RSS by 16.3% relative to the original artifact. Full
sharing reduces them by 14.3% and 26.7%. The construction result captures most
of the load-memory benefit without a general interning pass.

`FStarC.CheckedFiles` profiling on diagnostic (not baseline) runs reports 38
ms, 29 ms, and 6 ms for loading the original, construction-reuse, and post-hoc
BV metadata respectively. The difference between rooted and metadata medians
is not a pure payload timer: it also includes deferred registration/pruning,
Z3 startup, target VC encoding, and process noise.

The matched UInt control shows the smaller artifact has less room to improve:

| UInt dependency | Metadata wall | Metadata max-process RSS | Rooted wall | Rooted max-process RSS |
|---|---:|---:|---:|---:|
| Original, 4.62 MB | 0.168 s | 101.8 MiB | 1.155 s | 245.8 MiB |
| Post-hoc sharing, 1.88 MB | 0.168 s | 101.5 MiB | 1.112 s | 227.6 MiB |

These are ordinary warm-filesystem runs. No attempt was made to flush the
shared host page cache, so they measure practical repeated invocation rather
than controlled cold-I/O behavior. GNU time reports the maximum RSS of one
process in the `timeout`/F*/Z3 tree, not the sum of concurrently resident F*
and Z3 processes. Every row records the modified F* executable SHA-256, F*
version output, Z3 executable SHA-256/version, target hash, dependency hash,
child hash, and command. The BV and UInt target hashes were respectively
`ff6e3f9ba1aae4c9881b4961a019fc70c4cfdb483688d9d5b33f8e7a3aa5e039`
and `62bca877c9afdb999ed62bfb683efbc5dcea7f7f83c1f6e9adec03661b7495c6`.
