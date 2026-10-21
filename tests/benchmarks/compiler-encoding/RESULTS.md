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

The final BV and UInt source hashes are
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
