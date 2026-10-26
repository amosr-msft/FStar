# Sparse controls and representative live workload

## Generated squash-lemma context growth

This investigation concerns the historical exhaustive
`BvModelAgreesWithZ3` source at
`0e13baff38309523a2074ef8fbc3745b4bc793ad`, not SMT interning and not the UInt
heap result. The preserved prior-session report was restricted by the
organization's content-exclusion policy, so its user-supplied headline results
remain the historical reference: 5,808 generated lemmas took 751-753 seconds
in one module, versus 152.7 seconds for the same 64 operation groups in
separate processes; generated declarations accounted for 704.1 seconds and
Z3 reported 74.2 seconds.

The historical source was rebuilt in an isolated worktree with OCaml 4.14.2
and Z3 5.3.0. Its source commit is exact, but the rebuilt stage2 binary hash is
`a9de01ce...`, not the report's `0ed8f974...`; rebuilt results below are
therefore not presented as binary-identical repetitions.

### Non-BV reproducer

The simple reproducer has no BV operators, sequences, tactics, or model
normalization. It emits distinct top-level declarations of this shape:

```fstar
irreducible
let opaque_param (i:int) : Tot (r:int{r == i}) = i

let agreement_0000 :
  squash (opaque_param 0 + 1 == 1) = ()
```

Every declaration submits a real SMT query: query count equals declaration
count, the opaque value is justified only by its refinement, and Z3's used
rlimit grows with accumulated context. Scaling is:

| Declarations | Wall | Sum declaration time | First / median / last declaration | Z3 reported | Last used rlimit |
|---:|---:|---:|---:|---:|---:|
| 256 | 3.36 s | 2.96 s | 3 / 11 / 22 ms | 0.97 s | 0.075 |
| 512 | 12.05 s | 11.35 s | 4 / 18 / 45 ms | 5.23 s | 0.148 |
| 1,024 | 48.30 s | 46.98 s | 4 / 45 / 100 ms | 21.74 s | 0.295 |
| 2,048 | 207.68 s | 205.03 s | 5 / 94 / 193 ms | 98.71 s | 0.599 |
| 4,096 | 1,052.14 s | 1,046.63 s | 4 / 249 / 476 ms | 525.34 s | 1.240 |
| 5,808 | >1,200 s | 1,194.91 s through declaration 4,607 | 4 / 244 / 579 ms in completed prefix | 597.30 s | 1.413 |

The 5,808-declaration run hit its 1,200-second harness timeout after a verified
contiguous prefix of 4,607 queries. The same 5,808 declarations split into 64
balanced 90/91-declaration modules/processes take **43.62 seconds summed wall
time**;
individual modules take 0.65-0.75 seconds and their last declaration is never
above 11 ms. The slowdown is therefore generic accumulating-declaration and
process-context behavior; BV is not required.

### Exact context and cost

Each checked declaration follows this path:

1. `TypeChecker.Tc` adds the checked sigelt through
   `TypeChecker.Env.push_sigelt`, consing it onto `env.gamma_sig`, then calls
   `env.solver.encode_sig`.
2. `SMTEncoding.Encode` represents the nullary squash-valued let with a symbol,
   its equation, and two typing assumptions (`typing_*` and
   `function_token_typing_*`).
3. `SMTEncoding.Pruning.maybe_add_ambient` recognizes each
   `HasType term (squash payload)` as `Sum_ambient true`.
   `add_assumption_summary` puts both assumptions in `ambients` and
   `extra_roots`.
4. For every following query, `Pruning.prune` scans the current query roots
   plus every accumulated extra root and includes all ambients. SolverState
   filters declarations already given to Z3, but in steady state still flushes
   eight newly reachable declarations for each new lemma. Those declarations
   remain in the persistent Z3 context.

At query/declaration 1,024, the measured state contains:

| Structure | Entries |
|---|---:|
| `env.gamma_sig` | 1,024 |
| `env.gamma_cache` | 0 |
| pruning definitions/declarations | 3,604 |
| trigger keys / edges | 3,119 / 8,095 |
| assumptions waiting on triggers | 7,066 |
| assumption-name map | 9,133 |
| ambients / extra roots | 2,044 / 2,044 |
| declarations retained by pruning | 8,213 |

The typechecker core memo table is cleared before every top-level declaration
and union-find is reset afterward. `gamma_sig` and all pruning maps do grow,
but the controlled probe distinguishes retention from the expensive
revisitation: with `context_pruning_no_ambients`, `gamma_sig`, the maps, and
2,044 extra roots still exist at declaration 1,024, while ambients move to the
diagnostic `pruned_ambients` list. Pruning then returns a constant 31
declarations in 0.39 ms instead of 8,213 in 31.96 ms, and per-declaration time
is 4.52 ms instead of 88.38 ms.

The instrumented phase split at declaration 512 is:

| Phase | Normal | No ambients |
|---|---:|---:|
| Query encoding before solver-state flush | 1.26 ms | 1.03 ms |
| Pruning graph scan/resolution | 15.38 ms | 0.40 ms |
| Already-given filtering and sorting | 1.92 ms | 0.88 ms |
| Newly flushed / total given declaration names | 8 / 4,117 | 0 / 31 |
| Serialization/communication outside measured Z3 | 0.52 ms | 1.00 ms |
| Z3 execution | 23 ms | <1 ms (counter resolution) |
| Post-query `encode_sig` | 0.46 ms | 0.57 ms |
| Other declaration checking | 1.11 ms | 0.89 ms |
| **Total declaration** | **43.67 ms** | **4.77 ms** |

Thus both sides grow:

- **F\*:** pruning repeatedly scans and resolves all prior ambient roots.
- **Z3:** eight newly reachable declarations per lemma accumulate in the
  persistent solver, increasing solver work even though each query root itself
  remains 16 declarations.

The simple 2,048-declaration control falls from 203.47 to 7.52 seconds under
the no-ambients diagnostic; last-declaration time falls from 191 to 5 ms.
Admit and lax controls check 4,096 declarations in 8.09 and 8.19 seconds,
respectively, confirming that parsing/environment retention alone is not the
inflation. The exact historical full BV source completes under the same
no-ambients diagnostic in 119.15 seconds with all 5,809 queries, 72.4 seconds
of profiled declarations, and 23.8 seconds reported by Z3. Because that run
uses the same-source rebuilt compiler rather than the preserved binary, it is
diagnostic evidence, not a matched speedup claim.

`context_pruning_no_ambients` changes proof-context selection and is **not** a
proposed production fix. Disabling context pruning entirely was not a valid
control on this historical compiler: it resent duplicate primitive
declarations to persistent Z3. No production fix is proposed here.

`BV_CONTEXT_ANALYSIS.json` records the scaling rows, partial timeout, balanced
split, phase counters, exact growing structures, commands, hashes, source
locations, diagnostics, and limitations. Reproduction scripts are under
`tests/benchmarks/bv-context/`.

## Primary result: current master versus main interning

The primary comparison pins upstream master
`9a10b2ccb1f17064ec496ee315acc6a5f99adf2a` and compares it with
`56e8ac31da`, the exact same tree plus only PR #4760's net two-file main
interning patch. This is the actual no-interning baseline; earlier references
to `b3f9782a6c` as a “baseline” were comparisons between interning
implementations, because that commit already includes unconditional
interning.

Both compilers use OCaml 4.14.2, Z3 5.3.0, identical non-patch sources and
flags, and compiler-specific dependency caches. Five shuffled uncached-target
runs per cell give:

| Live-500 | Master observations | Main interning observations | Median change | Checked size |
|---|---|---|---:|---:|
| BV write | 37.95, 38.17, 38.41, 38.37, 38.38 s | 37.75, 37.62, 38.45, 38.00, 38.34 s | -1.0% | 21,886,665 → 2,136,307 B (-90.2%) |
| BV no-write | 37.71, 37.89, 37.64, 37.76, 38.00 s | 37.67, 37.76, 37.95, 37.89, 38.32 s | +0.3% | — |
| UInt write | 27.56, 27.59, 27.62, 28.67, 28.79 s | 27.60, 27.96, 27.69, 28.35, 29.10 s | +1.2% | 4,619,278 → 1,862,553 B (-59.7%) |
| UInt no-write | 27.54, 27.80, 28.42, 28.32, 28.77 s | 27.74, 27.99, 27.87, 27.89, 28.52 s | -1.5% | — |

No consistent compilation slowdown reproduces. Write and no-write directions
reverse by representation and all changes are within the observed ranges.
These are descriptive five-run medians without significance testing.
Generic Marshal comparison verifies stage 1, the stored typechecking
result/index, and declarations are structurally equal across master and
interning artifacts while ignoring compiler-specific dependency digests.

Three intrusive profile repetitions per cell show the cost/offset directly:

- Final interning costs about 0.31 s BV and 0.10 s UInt.
- Whole-process OCaml allocation rises only 0.26-0.28% BV and 0.11-0.12%
  UInt.
- Pruning summary time falls from about 207 to 158 ms BV and 66 to 45 ms
  UInt because summaries traverse physically shared declarations.
- Checked serialization/write falls from about 555 to 42 ms BV and 114 to
  26 ms UInt.
- Typechecking/normalization still dominates (about 50 s BV / 40 s UInt);
  Z3 is only about 0.35/0.92 s, dependency loading about 20 ms, and solver
  registration about 3-20 ms.

Profile counters overlap and are intrusive, but explain the neutral total:
serialization and pruning savings offset much of the interning pass,
especially in write mode. GC counts and heap thresholds move slightly and are
not uniform. BV's lightweight F* peak heap is unchanged while write RSS falls
18%; UInt's F* peak heap rises 725.6 → 926.9 MB (+27.7%) and RSS rises about
20% write / 24% no-write. Intrusive UInt profiles likewise show major
collections increasing from 32 to 33-35 and top-heap thresholds rising about
4-8%. Main interning therefore improves cache/load memory strongly but has a
real workload-specific compile-memory regression on UInt. The historical CI
time slowdown is not reproduced under this matched current-master comparison.

### UInt heap mechanism

Three new matched production-binary repetitions reproduce the UInt peak
exactly in both modes: master remains at 725,590,016 bytes and main interning
at 926,916,608 bytes. The corresponding no-write RSS medians are 757,132 and
951,232 KiB. The normal OCaml 4.14.2 runtime controls are identical
(`minor_heap_size=262144` words, `major_heap_increment=15`,
`space_overhead=120`, `allocation_policy=2`) and `OCAMLRUNPARAM` is unset.
The latter was observed in the orchestrating environment before the campaign,
not embedded in each legacy measurement row.

The peak is not created by final declaration interning:

- File-boundary traces show all library and benchmark-child caches loaded
  while both processes still had a 6,812,672-word (54.5 MB) major heap.
- The large historical high-water divergence appears while typechecking the final
  generated `step` declaration, before final `encode_signature`. In the
  instrumented run, both variants enter that declaration after 382 minor
  collections and finish after 7,883. Master completes 21 major collections
  inside the declaration and grows from 23,589,888 to 94,893,056 words;
  interning completes 20 and grows from 19,395,584 to 99,087,360 words.
  Incremental `encode_sig`, final encoding, declaration/index interning,
  pruning, solver registration, and serialization all occur after that
  divergence.
- Absolute instrumented peaks differ from production because adding snapshots
  perturbs GC thresholds. The phase ordering and matched counter difference,
  not those absolute peaks, are the diagnostic evidence.

Forced full collections at phase boundaries show less reachable major-heap
data with interning, despite its higher historical capacity. Immediately
before final encoding, master has 10,298,678 live words (82.4 MB) versus
9,888,425 (79.1 MB) with interning. After pruning, master has 13,042,635 live
words (104.3 MB) versus 10,424,538 (83.4 MB). The UInt declaration graph
passed to the interner contains 2,672,432 reachable words; its canonical
output contains 464,588, with 175,947 shared between input and output. The
index falls from 100,792 to 67,312 reachable words. Thus temporary input/output
coexistence is real but small relative to the observed 201 MB capacity jump,
and the canonical graph retained after the pass is much smaller.

A five-run 2×2 compiler/dependency probe confirms threshold sensitivity but
does not cleanly isolate dependency shape. The interning executable with
master dependency artifacts stays at 725.6 MB in all five runs, although its
final interning code is unchanged; the normal interning/compiler-specific
pairing stays at 926.9 MB. The master executable with interning dependency
artifacts is bimodal (one 926.9 MB run, four 725.6 MB runs), and even the
master/master control shifts from the primary campaign's 725.6 MB to 759.1 MB
in all five probe runs. The probe therefore shows that the high-water result
is not a stable amount of extra live data, but cannot apportion the
perturbation among loaded graph shape, executable layout, and campaign
instrumentation. A controlled full major collection immediately after loading
the benchmark child does not eliminate the later divergence, so it is not
merely unreclaimed dependency-loading garbage; allocation, promotion, and
major-cycle pacing during the large `step` check matter.

The BV control remains at 725.6 MB for both production compilers. Its
pre-final-encoding live heaps are also close, while declaration interning
shrinks a much larger 9,575,912-word input graph to 608,927 words. BV therefore
does not cross the UInt-specific growth threshold in these runs.

**Conclusion:** the +27.7% UInt number is a real peak-capacity/RSS regression,
but not a 27.7% increase in reachable compiler objects and not retention by
canonical tables. During the allocation-heavy `step` typecheck, one fewer
completed major cycle coincides with the interning process landing in a larger
OCaml major-heap capacity bucket.
Loaded graph shape, executable layout, and diagnostic allocation can perturb
that schedule, but this experiment does not isolate their individual
contributions. Forced collections can change the bucket but are diagnostic
only; this evidence does not justify production GC calls or tuning.
`UINT_HEAP_ANALYSIS.json` contains the observations, boundary counters,
reachability measurements, crossed-dependency results, exact evidence hashes,
and stated limitations.

Dependent checks demonstrate the cache benefit:

| Dependency | Master median | Interning median | Time | Peak RSS |
|---|---:|---:|---:|---:|
| BV metadata only | 0.226 s | 0.189 s | -16.1% | -21.4% |
| BV rooted SMT payload | 1.426 s | 1.247 s | -12.6% | -23.1% |
| UInt metadata only | 0.151 s | 0.147 s | -2.5% | approximately unchanged |
| UInt rooted SMT payload | 1.209 s | 1.118 s | -7.5% | -8.3% |

The rooted mode references `step`, forces the exported SMT payload, and runs a
small query; metadata mode does not start Z3. These are warm-filesystem
measurements.

Ordinary controls also shrink without a timing penalty:
`Positivity` is 931,243 → 691,657 bytes with 0.99 → 0.98 s write medians;
`TestWellFoundedRecursion` is 681,964 → 516,176 bytes with 0.90 → 0.86 s.
No-write changes are similarly within 0.02 s.

### Lower-overhead candidate

The lower-overhead experiment keeps the current PR's exact term, declaration,
and top-level-element interning, but does not intern the derived pruning index.
This removes a second traversal and its temporary hash tables, keys, hashed
summary records, and rebuilt lists. It introduces no option or runtime tuning.
The three pinned variants are:

1. Master without interning: `9a10b2ccb1`.
2. The same master plus the current main interning algorithm: `56e8ac31da`.
3. The same master plus declarations-only sharing:
   `973e5add74` (`users/amos/20261024-fstar-master-decls-sharing`).

An earlier terms-only probe was rejected before the full campaign: it reduced
BV sharing allocation more, but produced a 14.50 MB checked file, retaining
only about one third of the PR's BV size improvement. It is not one of the
three reported candidates.

Fresh production-graph profiles, three shuffled no-write repetitions, give:

| Live-500 | Master allocated words | Main PR overhead | Candidate overhead | Candidate vs PR overhead | Main PR pass | Candidate pass |
|---|---:|---:|---:|---:|---:|---:|
| BV | 16,746,448,040 | +48,391,117 | +41,789,999 | -13.6% | 272.3 + 39.0 ms | 271.2 ms |
| UInt | 10,010,142,353 | +12,167,375 | +12,153,579 | -0.1% | 89.1 + 1.2 ms | 92.9 ms |

The pass columns separate declaration and index interning. BV's removed index
pass allocates exactly 6,793,842 words and takes 38.4-40.2 ms. UInt's allocates
219,812 words and takes 1.1-1.2 ms. Candidate UInt declaration time is a few
milliseconds higher even though its code is unchanged; this is consistent
with binary-layout noise and is not evidence that removing the index pass made
declaration interning slower. Whole-process allocation is the relevant
no-interning comparison; peak heap is reported separately below.

Five shuffled lightweight production runs per cell give:

| Live-500 | Master median (range) | Main PR median (range) | Candidate median (range) | Candidate checked size |
|---|---:|---:|---:|---:|
| BV write | 38.69 s (38.58-38.80) | 37.47 s (37.39-37.52) | 37.96 s (37.78-38.13) | 4,873,026 B |
| BV no-write | 37.96 s (37.68-38.02) | 37.38 s (37.32-37.51) | 37.82 s (37.60-37.84) | — |
| UInt write | 27.67 s (27.58-27.76) | 27.77 s (27.77-27.94) | 27.91 s (27.71-28.07) | 1,926,883 B |
| UInt no-write | 27.53 s (27.40-27.62) | 27.62 s (27.55-27.83) | 27.84 s (27.78-27.87) | — |

The candidate's BV file is 77.7% smaller than master and retains 86.1% of the
main PR's byte reduction; UInt is 58.3% smaller and retains 97.7%. Compared
with the PR, the cost is 2.74 MB BV and 64 KB UInt. End-to-end time differences
are small relative to the work: candidate medians are 0.5-1.3% slower than the
PR and range from 1.9% faster to 1.1% slower than master.

BV production peak heap remains 725.6 MB for all three. UInt remains an OCaml
capacity-threshold result: candidate no-write is consistently 759.1 MB rather
than the PR's 926.9 MB, while candidate write is bimodal and has a 926.9 MB
median. This is not an allocation measurement and does not establish a stable
memory fix.

The larger candidate index preserves most rooted loading benefits:

| Dependent load | Master | Main PR | Candidate | Candidate RSS vs master |
|---|---:|---:|---:|---:|
| BV metadata | 0.217 s / 130.2 MiB | 0.187 s / 102.6 MiB | 0.212 s / 120.8 MiB | -7.2% |
| BV rooted | 1.428 s / 307.1 MiB | 1.243 s / 236.1 MiB | 1.279 s / 236.8 MiB | -22.9% |
| UInt metadata | 0.148 s / 101.7 MiB | 0.146 s / 100.0 MiB | 0.152 s / 102.3 MiB | +0.6% |
| UInt rooted | 1.191 s / 244.3 MiB | 1.107 s / 224.3 MiB | 1.119 s / 211.2 MiB | -13.6% |

Ordinary controls show the same tradeoff without a time penalty: candidate
`Positivity` is 719,773 bytes at 0.96 s write median (master 931,243/0.98,
PR 691,657/0.97); `TestWellFoundedRecursion` is 540,208 bytes at 0.88 s
(master 681,964/0.88, PR 516,176/0.86).

Build, exact bootstrap diff, `BvBinaryOps`, and `ClassicalSugar` pass. Generic
checked-file comparison verifies identical stage1, typechecking result/index
values, and declaration contents for BV and UInt against both master and the
main PR, ignoring only compiler-specific dependency digests.
`LOW_OVERHEAD_SHARING.json` contains every observation, exact revisions and
binary/artifact hashes, commands, dependent-load evidence hashes, and stated
limitations. PR #4760 remains unchanged at `debed4e7a9`.

`MASTER_INTERNING_COMPARISON.json` contains all observations, allocation/GC
profiles, dependent-load results, exact revisions/binary/build/solver
provenance, validation, commands, and evidence hashes. The current-master
experiment branch is `users/amos/20261023-fstar-master-smt-sharing`; no PR was
opened. PR #4760 remains open with main interning; only the later traversal
optimization remains reverted at `debed4e7a9`.

## Historical investigation

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
`ClassicalSugar` pass. A broader `make test-3` run stopped when the Custard
`TypeDiverge` rejection expected diagnostic 365 but encountered a stack
overflow. The focused comparison below did not reproduce that failure.

### Focused `TypeDiverge` comparison

The exact Makefile command uses the prechecked `TypeDiverge.fst.checked`,
OCaml code generation, `--custard_warn_any --warn_error @367`,
`--custard_entry TypeDiverge.f`, and `--custard_main TypeDiverge.main`. It has
no explicit stack or OCaml runtime override. The focused runs inherited an
8 MiB shell stack and had `OCAMLRUNPARAM` unset; each was bounded to 60
seconds.

| Compiler | Sharing option passed | Result | Wall | Max-process RSS |
|---|---:|---|---:|---:|
| `b1fe663037` | off | Error 365 | 18.02 s | 1,006 MiB |
| `b1fe663037` | on | Error 365 | 19.26 s | 1,006 MiB |
| `5b1137a9f1` | off | Error 365 | 15.90 s | 1,005 MiB |
| `5b1137a9f1` | on | Error 365 | 15.92 s | 1,006 MiB |

All four diagnostics are identical: Custard exceeds its 10,000,000-step
normalization budget on `t sq`, reached through `TypeDiverge.f`. The original
full-suite invocation did not pass `--ext smtencoding:share=true`, so the
opt-in interner was not enabled at the stack overflow. The failure is therefore
not a general-sharing regression. Moreover, the focused recipe extracts an
already-checked module, so even the option-present focused runs do not execute
SMT interning; they only confirm that both compiler revisions reproduce the
intended Custard diagnostic under the same extraction conditions. The
order-dependent/transient cause inside the earlier full-suite process remains
unexplained; no unrelated Custard fix was attempted.

The tracked `GENERAL_SHARING_MEASUREMENTS.json` records tool/source hashes,
medians, profiles, and validation outcomes.
`TYPE_DIVERGE_VALIDATION.json` records the exact focused commands, hashes,
settings, diagnostics, and measurements.

## Clean-branch matched benchmark

The delivery branch `users/amos/20261022-fstar-smt-sharing` is based on
upstream `5275509e26`. Commit `f4decbb8c2` changes exactly two compiler files:
it adds `FStarC.SMTEncoding.Sharing.fst` and adds the opt-in call in
`FStarC.SMTEncoding.Encode.fst`. It contains no benchmark files, reports,
standalone experiments, handwritten runtime, or BV-only cache/fresh replay.

The following medians compare that clean compiler with untouched upstream.
Both use identical sources and common flags, Z3 5.3.0, prechecked
dependencies, and an uncached measured target; sharing runs additionally pass
`--ext smtencoding:share=true`. Three repetitions alternate write/no-write
order.

| Live-500 | Baseline write | Shared write | Baseline no-write | Shared no-write |
|---|---:|---:|---:|---:|
| BV wall | 35.348 s | 35.179 s | 34.873 s | 34.932 s |
| BV max-process RSS | 1,496 MiB | 1,295 MiB | 1,270 MiB | 1,271 MiB |
| BV `.checked` | 21,886,665 B | 2,136,307 B | — | — |
| UInt wall | 27.077 s | 26.931 s | 26.819 s | 26.886 s |
| UInt max-process RSS | 1,302 MiB | 1,253 MiB | 1,254 MiB | 1,233 MiB |
| UInt `.checked` | 4,619,278 B | 1,862,553 B | — | — |

Sharing reduces checked size by 90.2% for BV and 59.7% for UInt. Total write
wall medians change -0.5% for both BV and UInt; no-write medians change +0.2%
and +0.3%, respectively. These are only three runs per cell and do not isolate
causation, but they show that persistence savings can offset the instrumented
240/30 ms BV and 72/<1 ms UInt declaration/index pass costs.

Write-minus-no-write is not treated as isolated persistence time: each run is
a separate process and includes noise and heap behavior. A five-run diagnostic
over already constructed values separates the persistence operations:

| Diagnostic median | BV baseline | BV shared | UInt baseline | UInt shared |
|---|---:|---:|---:|---:|
| Serialize stage 1/2 | 148.1 ms | 24.5 ms | 39.7 ms | 23.3 ms |
| Serialize SMT payload | 336.4 ms | 13.2 ms | 58.3 ms | 12.5 ms |
| Merkle hash | 35.8 ms | 3.6 ms | 8.4 ms | 3.1 ms |
| Buffered write | 4.0 ms | 0.5 ms | 0.9 ms | 0.5 ms |
| Sum of medians | 524.3 ms | 41.8 ms | 107.3 ms | 39.3 ms |

Thus diagnostic persistence work falls about 92.0% for BV and 63.4% for UInt.
The dominant BV saving is SMT serialization (336.4 to 13.2 ms), followed by
combined stage-1/stage-2 serialization. Hashing also scales with payload size. Actual
`save_3values_to_file` additionally performs atomic replacement; the
diagnostic also uses atomic replacement but does not measure `fsync` or
cold-storage latency.

Ordinary non-BV controls also shrink; with three runs per cell, observed total
write changes range from -0.7% to +3.7%:

| Module | Baseline/shared write | Baseline/shared size | Size reduction |
|---|---:|---:|---:|
| `Positivity` | 1.013 / 1.006 s | 931,243 / 691,657 B | 25.7% |
| `ClassicalSugar` | 1.082 / 1.082 s | 605,436 / 502,130 B | 17.1% |
| `TestWellFoundedRecursion` | 0.930 / 0.964 s | 681,964 / 516,176 B | 24.3% |

Their sharing declaration/index profiles are 12/1, 2/0, and 6/1 ms.

Dependent-file loading improves as well. With identical uncached dependent
sources, five warm-filesystem repetitions give BV metadata/rooted medians of
0.227/1.527 s baseline versus 0.178/1.322 s shared; maximum-process RSS falls
from 130/337 MiB to 104/248 MiB. UInt metadata/rooted changes from
0.166/1.146 s to 0.166/1.087 s, with rooted RSS falling from 245 to 227 MiB.

Direct warm-cache read/unmarshal probes explain part of that end-to-end
improvement. Internal timings measure only `load_2values_from_file3` (stage
1/2 metadata) or `load_3rd_value_from_file3` (the lazy SMT payload);
whole-process wall additionally includes startup.

| Artifact/read | Internal baseline → shared | Process wall baseline → shared | RSS baseline → shared |
|---|---:|---:|---:|
| BV stage 1/2 metadata | 36.9 → 6.5 ms | 54.3 → 21.3 ms | 62.6 → 30.5 MiB |
| BV SMT payload | 107.1 → 6.9 ms | 128.3 → 21.8 ms | 134.3 → 30.5 MiB |
| UInt stage 1/2 metadata | 6.5 → 6.1 ms | 21.0 → 20.5 ms | 30.5 → 29.9 MiB |
| UInt SMT payload | 29.7 → 5.1 ms | 46.3 → 19.7 ms | 54.2 → 28.8 MiB |

BV metadata/payload unmarshalling falls 82%/94%; UInt payload unmarshalling
falls 83%, while its already-small metadata changes little. The speedups are
not proportional to byte reduction because startup, allocation, GC, target
checking, pruning/registration, and Z3 remain. The rooted dependent benchmark
is the end-to-end measure: it issues a query over `B.step` under normal
pruning, thereby forcing the exported payload; metadata mode admits the query
and starts no Z3 process.

The exact clean commit was rebuilt after commit: BV/UInt confirmation runs
produced the same 2,136,307/1,862,553-byte artifacts in 35.58/26.92 s. UInt is
within the repeated-run range; BV is 0.27 s (0.8%) above its largest repeated
observation. Default (flag-off) artifacts generated with matched flags are
byte-identical to upstream for both synthetic targets. Structural comparisons of shared versus
baseline artifacts preserve checked module, inclusion information, index,
fvar bindings, and declaration contents/order. Standard build, exact
`boot-diff`, opt-in `BvBinaryOps`, and opt-in `ClassicalSugar` pass.

`CLEAN_SHARING_MEASUREMENTS.json` records branch/base/commit, exact diff scope,
compiler/solver/source/artifact hashes, commands, medians, diagnostics, and
validation outcomes. Raw logs and generated artifacts remain ignored.

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

## FunOS Co3 investigation

A matched `make co3-verify` benchmark was prepared but could not produce a
valid timing comparison because verification fails before either
configuration reaches its final `Config.Main` target. `co3-verify` has been
absent from CI for some time because of performance regressions, so recent CI
does not establish that it passes. The failure may therefore be a genuine
stable proof gap; it is not a measured performance result.

The exact revisions were:

- FunOS stable `3b35ffd1bd2f3e15273cd2ecb06721a648b9ab3b`.
- FunSDK stable `95f4497cb63823806536c56a072a2d002eb45e59`
  (`FunSDK-2961`).
- FunFM stable `fd92b567b1753ac577ee66712b41fa11fb5cf689`.
- Baseline F* `5275509e26b2e4c3df3ade7df1e01b3e38f9553a`.
- Unconditional-sharing F* `b3f9782a6c3c02f2a91705aa00ee936361b5df27`.

Separate FunOS worktrees, FunSDK overlays, compiler libraries, Co3 plugins,
and checked caches were used for the two compilers. The Co3 plugins were built
with the matching OCaml 5.2.1 compiler ABI. FunOS pins Z3 4.13.3; both
compilers require an explicit `--z3version 4.13.3` acknowledgement when using
that project solver. `CO3_DISABLE_VERIFY=0` was required because stable
otherwise disables this target.

The intended commands were:

```sh
FSTAR_OPT='--z3version 4.13.3' \
make MACHINE=s3-qemu TARGET=guest-up CO3_DISABLE_VERIFY=0 \
  SDKDIR=/path/to/matched-sdk \
  -j4 co3-verify

FSTAR_OPT='--z3version 4.13.3' \
make MACHINE=s2-coco-qemu TARGET=guest-up CO3_DISABLE_VERIFY=0 \
  SDKDIR=/path/to/matched-sdk \
  -j4 co3-verify
```

`FSTAR_OPT` is an environment variable here, not a Make command-line
assignment. Environment origin allows `co3-langco3.mk` to append the resolved
namespace; a command-line assignment suppresses its `+=` and must spell the
namespace manually. `co3-debug` confirms the supported S3 resolution:
`Config.Main`, include roots `configs/co3/{common,funos}`, target name
`S3.QEMU`, and namespace
`Machines.S3_QEMU+Chips.S3+Defaults+Stubs`.

Both configurations and both compared compilers stop on the same
configuration-independent obligation in
`configs/co3/common/Libs/GuestMemRanges.co3:24-64`. S3 reaches 57 checked
dependencies and S2 reaches 62 before it. At source level, the failing VC is
equivalent to the precondition to `bounded 12`:

```text
List.length
  (xkphys ... @ xkphys ... @
   guarded ... @ guarded ...) <= 12
```

This is a refinement-precondition failure, not a runtime-exception failure.
`u64_exn` has no logical precondition: it tests the concrete integer and calls
`Co3.Base.Error.error` when it does not fit. Standalone `lang_co3` extraction
evaluates those paths. In contrast, `bounded` returns a refined bounded-array
type through a `Pure` function whose `requires` clause is
`normalize (List.length l <= n)`. Applying it causes F*'s WP to emit the
length condition as an assertion.

The canonical S3 `co3-extract` command succeeds over the same namespace,
generated config, and source. It emits 12 UP-memory ranges for each of the P
and UP domains; every numeric field is within `u64`, with the largest value
exactly `2^64-1`. Its `Config.Main.asserts.json` contains 16 assertions and
all 16 are `PASS`. Those are Co3 export/value/type assertions and are distinct
from the F* WP assertion generated while checking `bounded`.

The diagnostic wording is also expected. Numeric Error 19 is
`Error_Z3SolverError` in `FStarC.Errors.Codes`; SMT error reporting labels a
failed proof goal “Assertion failed.” Refinement subtyping can also generate
an SMT guard and eventually use this generic message, so the wording alone
does not distinguish the source. Here, the printed VC and `bounded` signature
show specifically that the failed goal is its `Pure` precondition.

`physical` is a three-element list and each helper is `List.map ... physical`,
but the original VC carries no usable length facts through those maps and
nested appends. A temporary proof probe attached
`FStar.List.Tot.Properties.map_lemma` refinements to both helper results;
those refinement subgoals succeeded. Even strengthening each helper result
to length exactly three succeeded at fuel 4, but the final appended-list
obligation still exhausted rlimit 5. The gap is therefore broader than a
missing map lemma alone: normalization/SMT does not bridge the helper
refinements through the nested appends into `bounded`'s precondition. The
diagnostic has eight preceding `up_memory_range_t` field goals; all succeed
immediately, so this is not an unclassified `u64_exn` conversion or a
machine-specific address bound.

At the default rlimit 5, the length query exhausts all four fuel/ifuel retry
configurations. At rlimit 100 it stops earlier with `incomplete quantifiers`
after using rlimit 7-22, showing that simply increasing the timeout does not
close the proof. The unconditional-sharing compiler reaches the same VC
before module export, so the sharing pass has not executed.

The canonical stable FunSDK combination also produces the identical VC:
packaged F* `fb6ea91eb4` (OCaml 5.4.1), FunFM `888c614f`, and Z3 4.13.3.
The benchmark overlays use ABI-matched FunFM `fd92b567`; this was a setup
difference, but `Co3.Pervasives.fst` is byte-identical and the canonical
result excludes it as the cause. The failing source SHA-256 is
`8c8e35ee801c84afeba870da336b996465d80c851cd930765f7987f2c831d415`.

There is also a build/docs inconsistency: stable sets
`CO3_DISABLE_VERIFY ?= 1`, so the documented `make ... co3-verify` commands
without `CO3_DISABLE_VERIFY=0` print `CO3 VERIFY DISABLED`. Explicitly
enabling verification exposes this proof gap. This default is intentional in
the current source; separately, `co3-verify` has not run in CI for some time
because of performance regressions. The documentation still reads as though
the commands verify.

The proof probes were diagnostic only and fully reverted. Direct calls to the
F* list lemma also produce Co3 “no shape attribute” warnings, so they are not
being proposed as a production fix. Making the concatenated length computation
explicit in Co3-compatible proof structure is one possible direction, not a
demonstrated required fix; no source change is included in these compiler
benchmarks.

An apparent successful S2 attempt was rejected as benchmark evidence: a
command-line Make variable accidentally suppressed the namespace extension,
so dependency discovery resolved literal `$CONFIG` to no modules and the run
only invoked the final exporter/verifier over an invalid empty dependency
graph. Regenerating dependencies with the full namespace option exposes the
same `GuestMemRanges` failure. No failed proof was admitted, no test was
disabled or modified, and no partial-cache timings are presented as
`co3-verify` results.

No matched performance result is possible without changing/proving the FunOS
source obligation, which would no longer be the requested unchanged-source
benchmark. This investigation therefore stops at the verified blocker rather
than adding an admit, disabling assertions, or benchmarking a proof-patched
source.

### Sharing implementation opportunities

Inspection of `FStarC.SMTEncoding.Sharing` found several concrete allocation
and traversal costs. They are optimization candidates, not demonstrated
causes of the large single-run regressions in PR-wide benchmarking:

- `intern_term` allocates one `hashed_term` record per visited occurrence.
  Recursive constructors then allocate an intermediate list of those records
  and a second list produced by `List.map term_value`; quantifier patterns
  repeat this at two list levels. `intern_decl`, `intern_elt`, and the pruning
  summary path use the same intermediate-record/list pattern. A private
  accumulator returning canonical value and hash together could avoid some
  allocations, but it must preserve order and collision-checked equality.
- Every table lookup allocates a key record (`term_key`, `decl_key`,
  `elt_key`, or summary variants), including hits. A table API that accepts a
  precomputed hash plus an equality predicate, or a purpose-built local
  bucket table, could remove these short-lived keys. This requires measured
  benefit before replacing the compiler's standard hash-table abstraction.
- `intern_index` creates fresh term and declaration tables, so `Sum_other`
  declarations can be traversed and hashed again rather than reusing
  canonical identities from `intern_decls`. Sharing one module-local
  interning context across declarations and the derived index would avoid
  that work and could improve cross-field Marshal sharing. The index profile
  was only about 27 ms on BV-500 and below 1 ms on UInt-500, so the expected
  gain is bounded.
- Initial table capacities are multiples of declaration-block count
  (`4 * blocks` for terms, `2 * blocks` for declarations), although term
  occurrences can exceed block count by orders of magnitude. Resizing and
  collision statistics should be instrumented before choosing a larger
  capacity, because over-allocation would work against the memory benefit on
  ordinary modules.
- Abstract lidents and opaque `Labeled` diagnostic messages intentionally use
  constant hashes with physical-only equality. This is correctness-preserving
  but can create long collision buckets when many distinct values occur.
  Identity hashing would improve distribution if the runtime exposes a
  stable non-retaining physical hash; structural rendering or equality is not
  a safe substitute.
- Equality compares canonical children physically but does not first test
  physical equality of the complete candidate node. Adding that fast path is
  small and safe, though it only helps repeated references to an already
  canonical complete node and needs profiling to establish impact.

Earlier profiles put the sharing work at roughly 228 ms declarations plus
27 ms index for BV-500, 82 ms plus 1 ms for UInt-500, and 2-10 ms plus
0-1 ms for ordinary controls. Those pass costs cannot directly explain
10-20 second PR-wide outliers. GC/heap-layout changes, solver variability, and
single-run noise remain plausible; component timing and allocation/collision
counts on a reproducing module are needed before changing the implementation.

`FUNOS_CO3_INVESTIGATION.json` records the exact revisions, commands, tool
hashes, cache progress, failures, and rejected run.

## PR #4760 worst-offender reruns

The three largest absolute regressions in the enabled PR comparison were
rerun locally using the workflow's exact test recipes, existing matched
compiler builds, Z3 5.3.0, compiler-specific caches, and alternating
baseline/sharing order. Each unprofiled cell has two warm-filesystem runs.
The baseline is `5275509e26`; sharing is unconditional at `b3f9782a6c`.

| Workload | CI baseline → sharing | Local baseline runs | Local sharing runs | Local median change |
|---|---:|---:|---:|---:|
| `NormBudget.rejected` | 139.38 → 157.39 s | 147.49, 159.90 s | 152.11, 144.09 s | -3.6% |
| `BoolRefinement` | 83.10 → 94.64 s | 58.94, 58.52 s | 59.10, 58.65 s | +0.2% |
| `DPE.Messages.Spec` | 92.33 → 104.97 s | 61.64, 62.04 s | 60.92, 60.83 s | -1.6% |

None of the three time regressions reproduced. Two repetitions are not enough
to claim a speedup, especially for `NormBudget`, whose local range is nearly
16 seconds. These local runs do not provide evidence for a direct 11-18
second sharing-pass cost; they do not rule out runner-specific interaction,
GC effects, or a regression that needs more repetitions to detect.

`NormBudget` remained the expected rejection in every run: warning 373,
including “the argument as written,” with a diagnostic below 100 KB. It loads
an already checked module and runs Custard extraction, so it never calls SMT
encoding or the sharing pass. A diagnostic Custard profile attributes
essentially all time to `split_mono_args`: 160.8 seconds baseline and 148.3
seconds sharing in one archived run, again within the wide run-to-run spread.

The verification profiles are diagnostic and slower than the lightweight
runs. They show:

| Workload | Baseline profile | Sharing profile | Sharing declarations/index | Dominant work |
|---|---:|---:|---:|---|
| `BoolRefinement` | 70.65 s | 73.52 s | 18/2 ms | phase-2 checking, Z3, normalization |
| `DPE.Messages.Spec` | 62.42 s | 63.63 s | 4/0 ms | Z3: 60.05/60.97 s aggregate |

`BoolRefinement` issued the same 1,128 profiled query attempts on both sides.
F*'s aggregate Z3 counters, including the profiled `FStar.Preorder`
dependency, were 49.99 versus 49.46 seconds. Its largest type-checker counters
were phase-2 checking and solver calls. The remaining profile delta is spread
through normalization, phase 1, and relationship checking rather than the 20
ms interner. `DPE.Messages.Spec` issued the same 86 query attempts; F*'s
aggregate Z3 counters were 60.05 versus 60.97 seconds. Its 4 ms interner is
four orders of magnitude smaller than total time; essentially all of this
diagnostic run's 1.22-second delta is inside solver time.

One additional run per side used OCaml's exit statistics
(`OCAMLRUNPARAM=v=0x400`). The Bool and DPE GC runs were concurrent pairs, so
their timing is discarded; allocation and collection counters are retained.
All allocation values are OCaml words. Peak values below are the separate
`FSTAR_MEM_REPORT` byte measurements, shown in decimal MB/GB.

| Workload | Allocated words, baseline → sharing | Major words | Major collections | Peak OCaml heap |
|---|---:|---:|---:|---:|
| `NormBudget` | 5.867B → 5.865B (-0.02%) | 918.7M → 917.3M | 24 → 23 | 5.781 → 6.238 GB (+7.9%) |
| `BoolRefinement` | 3.129B → 3.128B (-0.02%) | 89.3M → 85.7M | 16 → 16 | 455.9 → 410.9 MB (-9.9%) |
| `DPE.Messages.Spec` | 232.5M → 230.4M (-0.9%) | 28.0M → 25.4M | 12 → 11 | 205.5 → 187.6 MB (-8.7%) |

The reproducible `NormBudget` memory increase is not caused by extra
allocation: total allocation and promotion are essentially unchanged, while
the OCaml runtime grows the sharing binary's heap to a larger high-water mark.
Because this path does not invoke sharing, the likely mechanism is binary
layout changing GC growth/collection timing. The two workloads that do invoke
sharing retain the PR's expected memory reduction.

The measured evidence does not support changing the interner for these CI
outliers. A useful next performance experiment would repeat the full PR
workflow several times or rerun selected tests in randomized alternating
order on the same runner class. `PR4760_WORST_OFFENDERS.json` records the raw
local values, reproduction templates, profile counters, GC counters, and
limitations. The 58 retained raw local files remain in session storage; their
sorted checksum-manifest digest is
`e20c64d5b2d02a00d1c24f6f09ba0d580401ea5b462cbbe6069561003925c2dc`.

## Expanded PR #4760 repetitions

Seven workloads from the enabled CI comparison were rerun five times per
compiler using their actual Make targets. The selection covers the three
largest absolute time deltas and four high-percentage regressions. Each
compiler has its own dependency cache; only the measured output is deleted.
Order is deterministically shuffled within each repetition, and all 70
observations are ordinary warm-filesystem runs.

| Workload | CI base → sharing | Local baseline observations | Local sharing observations | Median change | F* heap change |
|---|---:|---|---|---:|---:|
| `NormBudget.rejected` | 139.38 → 157.39 s | 143.77, 150.92, 144.24, 146.97, 143.89 | 154.57, 143.53, 141.08, 141.35, 153.12 | -0.5% | +7.9% |
| `BoolRefinement` | 83.10 → 94.64 s | 58.83, 58.52, 58.73, 59.38, 59.09 | 59.13, 58.23, 58.57, 58.78, 59.26 | -0.1% | -9.9% |
| `DPE.Messages.Spec` | 92.33 → 104.97 s | 61.51, 61.26, 61.30, 61.36, 61.34 | 61.39, 60.92, 61.15, 61.45, 61.48 | +0.1% | -8.7% |
| `CBOR.Pulse` | 20.65 → 24.72 s | 19.73, 19.61, 19.43, 19.57, 19.59 | 19.46, 19.12, 19.10, 19.43, 19.56 | -0.8% | -15.4% |
| `CborBoundarySlice` | 30.57 → 35.81 s | 29.05, 28.70, 28.74, 28.81, 29.08 | 28.65, 29.14, 28.62, 28.63, 28.93 | -0.6% | -10.2% |
| `RBTreeIntrinsic` | 24.28 → 28.46 s | 22.25, 22.03, 22.04, 22.09, 22.18 | 22.03, 22.28, 22.02, 22.06, 21.99 | -0.3% | -17.1% |
| `CBOR.Spec.Map` | 7.26 → 9.02 s | 6.51, 6.45, 6.45, 6.48, 6.48 | 6.47, 6.46, 6.47, 6.51, 6.48 | -0.2% | -3.5% |

No CI time regression reproduces in the expanded local campaign. The largest
local median increase is 0.08% for `DPE.Messages.Spec`, well inside its
0.56-second sharing range. This does not prove that the CI observations were
noise or rule out runner-specific interactions; it shows that none is stable
under five repetitions on this host.

No new intrusive profile was run because there is no reproducible time
regression to profile. The separate profiles above already cover the three
largest CI outliers: sharing itself costs 20 ms for `BoolRefinement`, 4 ms for
`DPE.Messages.Spec`, and does not execute in `NormBudget`. The reproducible
`NormBudget` heap increase remains +7.9%, with prior GC statistics showing
essentially unchanged allocation; all six verification workloads reduce F*
peak heap by 3.5-17.1%.

`PR4760_EXPANDED_MEASUREMENTS.json` contains the individual observations,
medians, ranges, heap values, artifact sizes, and hashes of the retained raw
JSONL and campaign log.

## Fused traversal and unchanged-node reuse

Compiler-only commit `befb3db820` implements the two approved interner
optimizations relative to `b3f9782a6c`:

- one recursive traversal interns children, constructs the canonical list,
  and computes the existing bottom-up list hash;
- original list cells and enclosing term/declaration/summary nodes are reused
  when every canonical child remains physically unchanged.

Collision-checked canonical lookup still runs for every node. No table,
index, equality, range, ordering, or declaration-cardinality semantics
changed. The compiler diff is one file:
`src/smtencoding/FStarC.SMTEncoding.Sharing.fst` (121 insertions, 45
deletions).

Five deterministically shuffled no-write repetitions give:

| Live-500 | Preopt observations | Optimized observations | Median change | F* heap change |
|---|---|---|---:|---:|
| BV | 35.31, 37.53, 36.24, 35.70, 34.68 s | 38.59, 37.49, 38.22, 37.97, 40.90 s | +7.1% | -41.2% |
| UInt | 29.06, 26.80, 28.46, 27.07, 26.96 s | 29.78, 29.32, 27.97, 29.39, 28.06 s | +8.3% | -28.1% |

Thus the changes are not a total-time optimization in this build. They do
reduce whole-process allocation: BV allocated words fall 0.19%, UInt 0.29%,
and minor collection counts fall by 23 and 27. However, major collections
rise from 43 to 59 for BV and 28 to 32 for UInt. The instrumented declaration
pass median changes 225 → 229 ms for BV and 83 → 102 ms for UInt; index
medians remain 31 and 1 ms. These diagnostic timings include profiler noise,
but provide no evidence of a pass-time gain.

Ordinary modules remain at startup/noise scale:

| Module | Write median preopt → optimized | No-write median | Checked size |
|---|---:|---:|---:|
| `Positivity` | 1.02 → 0.99 s | 1.01 → 1.02 s | 691,657 B |
| `TestWellFoundedRecursion` | 0.91 → 0.90 s | 0.90 → 0.92 s | 516,176 B |

Their optimized F* heap high-water marks increase, from 99.1 to 121.6 MB and
65.8 to 88.1 MB respectively. As with the earlier extraction-only
`NormBudget` result, binary/GC layout can move peak heap independently of
interner-local allocation.

BV/UInt checked sizes are exactly unchanged at 2,136,307 and 1,862,553 bytes.
Exact-sharing recovery verifies each complete input structurally; recovered
preopt/optimized pairs are byte-identical (BV
`bc400558...`, UInt `41ed0673...`). Optimized artifacts also load normally,
and a rooted BV dependent query completes in 1.261 seconds.

Stage3 build, exact `boot-diff`, `BvBinaryOps`, and `ClassicalSugar` pass.
`SHARING_OPTIMIZATION_MEASUREMENTS.json` records individual runs, allocation
counters, artifact evidence, commands/hashes, and limitations.

### Fusion versus unchanged-node reuse

The combined change was reverted from PR #4760 by `debed4e7a9`, restoring
the compiler source exactly to `b3f9782a6c`. Fusion-only experiment
`206126a6dd` starts from that original and contains no physical-equality tests
or unchanged-list/node reuse.

Five shuffled no-write repetitions compare original and fusion-only:

| Live-500 | Original observations | Fusion-only observations | Median change | F* heap change |
|---|---|---|---:|---:|
| BV | 38.32, 38.30, 38.28, 38.02, 38.55 s | 38.83, 39.02, 38.60, 38.59, 38.61 s | +0.8% | -4.4% |
| UInt | 28.69, 28.75, 27.80, 28.24, 28.13 s | 29.42, 29.79, 29.13, 28.79, 29.29 s | +3.7% | -18.1% |

The no-write path does execute interning: its separate profile commands omit
`--cache_checked_modules` and report both sharing counters. Those five-run
profiles show no fusion pass slowdown for BV (declarations 243 → 243 ms,
index 36 → 30 ms) and a modest UInt reduction (82 → 78 ms, index unchanged at
1 ms). Nevertheless, lightweight total medians rise. The total-time change is
therefore not time spent directly in the measured sharing counters.

Fusion-only barely changes whole-process allocation: -0.0097% BV and -0.0026%
UInt. The reason is visible in the implementation. The original creates an
intermediate list cons cell that retains each hashed-result record. Fusion
removes that cons, but each callback now allocates a
`(canonical_child, hash)` tuple of similar size. The hashed-result record and
canonical output cons still exist.

Existing combined profiles have only another -0.0004% BV/-0.0007% UInt
allocation difference relative to fusion-only. Their declaration median is
lower for BV (229 versus 243 ms) but higher for UInt (102 versus 78 ms).
However, these values come from different compiler builds with materially
different baselines. They cannot isolate an incremental reuse cost or benefit;
they only show no consistent cross-build pass-time pattern.

The absolute combined and fusion-only synthetic times are also similar, but
their original baselines differ materially across compiler rebuilds. The
earlier +7-8% combined result cannot be assigned to reuse. The controlled
fusion-only comparison instead shows that fusion itself can coexist with a
small total-time increase even while its measured pass time is unchanged or
lower. Binary/GC layout, solver/runtime noise, and downstream phase
perturbation remain possible explanations for the gap between pass counters
and total time; this experiment does not distinguish them.

Five-run ordinary controls move only 10-20 ms and retain identical heap/size
within each original/fusion comparison. BV/UInt checked sizes remain
2,136,307/1,862,553 bytes. After ignoring compiler-specific dependency
digests, generic Marshal comparison finds stage 1, the complete stored
typechecking result/index, and declarations structurally equal; the durable
comparison log SHA-256 is `bfd850ef...`. Stage3,
`boot-diff`, `BvBinaryOps`, and `ClassicalSugar` pass for fusion-only.

`FUSION_REUSE_ISOLATION.json` records all observations, pass/GC counters,
artifact validation, exact code distinctions, and evidence hashes.

#### Same-process pass isolation

A final standalone harness links renamed extracted copies of all three exact
implementations into one executable. It loads one checked artifact once,
checks all variant outputs structurally equal, forces a full major GC before
each measurement, and runs 30 repetitions with shuffled variant order.
`Gc.allocated_bytes` deltas cover the selected pass plus the identical
clock/statistics epilogue in the driver.

| Live-500 declarations | Original | Fusion only | Fusion + reuse |
|---|---:|---:|---:|
| BV median wall | 225.78 ms | 217.91 ms | 215.48 ms |
| BV allocated words | 42,038,651 | 40,129,011 | 34,096,313 |
| UInt median wall | 81.25 ms | 78.78 ms | 75.14 ms |
| UInt allocated words | 12,528,960 | 12,270,709 | 10,373,307 |

Fusion improves declaration time by 3.5% BV / 3.0% UInt and allocation by
4.5% / 2.1%. Adding unchanged-node/list reuse improves time another 1.1% /
4.6% and allocation another 15.0% / 15.5%. Reachable output words are
identical across variants. **Node reuse is therefore not the slowdown
cause inside the measured pass; it is the larger pass-local allocation
improvement.** This does not rule out reuse-induced downstream GC/layout
effects after the pass returns.

Index effects are smaller. BV median time is 24.83 / 24.01 / 23.98 ms for
original/fusion/combined, with 6.79M / 7.08M / 6.52M allocated words. UInt is
0.790 / 0.764 / 0.766 ms and 219.8K / 220.5K / 201.8K words. Fusion's callback
and recursive-result tuples can outweigh the removed intermediate list for
these small index lists; reuse recovers the allocation.

Both tuple layers are explicit in extracted OCaml: the callback returns
`(canonical_child, hash)` and every recursive `intern_list` returns
`(canonical_tail, tail_hash)`. They are not removed at extraction. They
partially offset fusion's eliminated intermediate-list allocation, but the
measured declaration pass still allocates 2-5% less. Native allocation-site
attribution was not instrumented, so this is a structural explanation rather
than a per-constructor allocation count.

This resolves the algorithm question but not the earlier whole-program timing:
both algorithms are faster in-process, while separately built compilers showed
small-to-large total-time increases. Those increases happen outside the
measured pass or reflect process-level perturbation; this experiment does not
distinguish downstream phases, GC/binary layout, solver/runtime noise, or
their interactions. The PR remains reverted.

## Matched end-to-end and phase analysis

The earlier whole-program comparison mixed compiler builds from different
toolchains/build rounds. A new four-way comparison rebuilds original A,
original B, fusion-only, and fusion+reuse from the same OCaml 4.14.2
bootstrap, options, non-sharing sources, solver, and host; only the sharing
module differs between algorithm variants. Original A/B have identical full
source and extracted sharing code but different executable hashes, giving an
identical-source build/layout control. The fusion binary was built from its
uncommitted diff immediately before commit `206126a6dd`, so it reports
`b3f9782a6c-dirty`; the recorded extracted-module hash identifies the exact
implementation. Nine attempts were flagged by the
overlap detector and excluded before recording. No overlap was
observed by one-second `ps` command-line polling for the 80 accepted
observations; this is a guard, not a proof, because a short process, command
text false positive, or another invocation containing the same executable
path can be missed.

Five shuffled repetitions per cell give:

| Live-500 | Original A | Original B | Fusion only | Fusion + reuse |
|---|---:|---:|---:|---:|
| BV write | 37.43 s | 37.88 s | 38.27 s | 38.23 s |
| BV no-write | 37.33 s | 37.79 s | 37.96 s | 38.29 s |
| UInt write | 28.08 s | 28.14 s | 28.38 s | 28.19 s |
| UInt no-write | 27.92 s | 28.07 s | 28.34 s | 28.08 s |

The 7-8% slowdown is gone. Relative to original A, fusion/combined are
1.7-2.6% slower on BV and 0.4-1.5% on UInt. But original B is itself 1.2%
slower than original A on BV despite identical source/extracted sharing code.
Fusion and combined differ by -0.1/+0.9% BV (write/no-write) and
-0.7/-0.9% UInt. This leaves no evidence that node reuse causes an end-to-end
slowdown; residual differences are at or near the identical-source build
control.

All matched variants have the same checked sizes and, for BV, identical
725,590,016-byte median F* peak heaps. UInt heap medians are also generally
identical; a single GC-threshold difference moves original B's no-write
median. Two ordinary controls are indistinguishable: all write/no-write
medians are within 0.01-0.03 seconds, with identical artifact sizes and peak
heaps.

### Where the time goes

Three intrusive profiles per variant/module and two separately instrumented
write/no-write runs locate the work. Representative medians are:

| Phase | BV | UInt |
|---|---:|---:|
| Typechecking declarations | 49-50 s | 40-41 s |
| VC simplification (nested in checking) | 29.8-30.5 s | 12.9-13.3 s |
| Incremental `encode_sig` (nested in checking) | 4.5-4.7 s | 3.8-4.0 s |
| Final fresh `encode_signature` | 2.0 s | 1.6-1.7 s |
| Final `intern_decls` | 0.27-0.29 s | 0.087-0.094 s |
| Pruning `summarize_elts` | 0.15-0.16 s | 0.044-0.048 s |
| Final `intern_index` | 0.029-0.032 s | about 0.001 s |
| Solver registration | about 0.015 s | about 0.003 s |
| Z3 aggregate query time | about 0.35 s | about 0.91 s |
| Dependency checked-file loading | about 0.018 s | about 0.018 s |
| Checked-file serialization/write | 0.038-0.039 s | 0.035-0.037 s |

Counters overlap (for example, simplification is inside declaration checking),
so they are not additive. They establish the scale: normalization/typechecking
dominates; final interning is below 1% of total; solver, dependency loading,
index interning, and persistence are too small to explain multi-second
changes. Write-minus-no-write medians are 0.04-0.31 seconds and sometimes
negative, while direct storage timing is only 35-39 ms. Persistence is not the
slowdown source.

The production wrappers also measure the pass on the fresh graph from
`encode_signature`. Fusion reduces declaration-pass allocation by 4.5% BV /
2.1% UInt. Reuse then reduces only another 0.12% / 0.40%, because most fresh
parents change when children are canonicalized. Whole-process allocation
changes by only about 0.01% BV / 0.003% UInt; minor/major collection counts
and peak heap are essentially unchanged across matched variants.

### Why the isolated pass looked different

Production runs `encode_signature → intern_decls → summarize_elts →
intern_index`, then stores those post-intern values in `.checked`. The
same-process harness instead loads that serialized post-intern graph, warms
all variants with structural comparisons, and forces a full major GC before
each timed pass. It has no parsing, checking, normalization, solver,
dependency loading, or serialization.

Exact-sharing recovery confirms the loaded artifact is already at the same
size after another sharing pass; recovery changes representative/digest once,
then reaches a digest fixed point. On this post-intern graph, reuse saves about
15% declaration allocation. On the actual fresh production input it saves
only 0.1-0.4%. Thus the isolated harness correctly measures algorithm behavior
on its input, but substantially overstates production reuse opportunities.

The remaining 1-2% end-to-end differences are unresolved. Identical-source
binary rebuilds demonstrate up to 1.2% BV variability; profiling perturbation can move
another similar amount. No measured phase consistently assigns the remainder
to fusion or reuse. Build/link layout, downstream normalization/GC
perturbation, and ordinary runtime noise remain plausible, but none is proven.
The PR remains reverted.

`MATCHED_END_TO_END_ANALYSIS.json` records all individual observations,
phase/GC values, build hashes, excluded overlaps, artifact sizes, and raw
evidence hashes. The matched end-to-end, profile, detailed-phase, and ordinary
runners, extracted-code instrumentation script, and aggregator provide
reproduction details.
