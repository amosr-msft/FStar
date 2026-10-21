# Initial results

Measured on 2026-10-21 at F* commit
`5275509e26b2e4c3df3ade7df1e01b3e38f9553a` (the then-current upstream
`master`). The contextual commit
`6db6b296ad57c9caf7395661a691e52dca37ba0f` is an ancestor of this baseline.
The compiler was built from the baseline with OCaml 5.2.1 and run with Z3
5.3.0, `--smtencoding.elim_box true`, prechecked dependencies, and an uncached
target. The host was an AMD EPYC 7763 VM with 32 logical CPUs and 125 GiB RAM.

Generator version 1 uses seed `20261021`, 50 input fields, 120 state fields, 25
output fields, ten child calls, and widths `{1,4,8,16,32,64,128}` with 40% of
field choices at width one. At 1,000 bindings the BV source contains 100
conditionals, 43 extracts, 52 concatenations, 58 replications, 100 additions,
100 shifts, and several hundred bitwise operations. Representative hashes are:

- BV direct: `5062d3cbc59af27d22fdb39eb48e75bf7d5bdd8235a41a5778082ef84f52c4bb`
- UInt direct: `e33aeb1f3e6ce8971d22077463a0f3badb3e81bb281885d22411882ac04f4266`
- BV with normalization assertions:
  `58c77d5ab9c69973fed1fe1edc65b5b27fb869c2cb9fa474a2a15b3aa25028fe`

## Baseline sweep

These are single write-mode runs; the large representation differences were
confirmed separately below.

| Bindings | BV wall | BV peak RSS | BV `.checked` | UInt wall | UInt peak RSS | UInt `.checked` |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 2.77 s | 278 MiB | 2.25 MiB | 2.99 s | 294 MiB | 2.06 MiB |
| 250 | 2.63 s | 315 MiB | 2.50 MiB | 8.22 s | 516 MiB | 2.21 MiB |
| 500 | 3.81 s | 544 MiB | 2.85 MiB | 39.52 s | 1,091 MiB | 2.44 MiB |
| 1,000 | 10.11 s | 1,438 MiB | 3.69 MiB | 364.06 s | 3,462 MiB | 2.91 MiB |

Three repeated no-write runs at 500 bindings gave medians of 3.94 s and 523
MiB for BV versus 40.54 s and 1,073 MiB for UInt: UInt was 10.3 times slower
and used 2.05 times the memory. This is despite the UInt checked artifact being
smaller.

The matched operation semantics are equal under unsigned interpretation, but
their F* representations are intentionally not: concrete-width `FStar.BV`
operations receive native SMT bitvector encoding, while `FStar.UInt` values
are refined integers and their bitwise operations are specified through the
UInt/bit-vector library. The arithmetic `to_uint_t` implementations of
extract/concat/repeat also introduce refinement normalization work.

Diagnostic profiling materially slowed both runs, so its counters are not
baseline timings. At 500 bindings, UInt phase-2 checking took 38.9 s, including
15.4 s in `simplify_vc` and 16.4 s in primitive-step normalization. The BV
profile reported 1.8 s in phase 2, 0.29 s in `simplify_vc`, and 1.28 s in
primitive-step normalization. Query statistics showed 252 UInt-500 queries
and 204 BV-1000 queries, all reported below 0.01 s. The dominant UInt cost is
therefore VC construction/simplification and normalization, not Z3 solving.

## Literals and cache writing

| 400-literal isolation workload | Wall | Peak RSS | `.checked` |
|---|---:|---:|---:|
| Assertions only | 1.99 s | 262 MiB | 0.23 MiB |
| Refined bindings with assertions | 9.01 s | 654 MiB | 0.46 MiB |
| Refined bindings without assertions | 0.57 s | 185 MiB | 0.13 MiB |
| Direct BV constructions | 0.56 s | 186 MiB | 0.13 MiB |

The closed-size simplifier in
`src/typechecker/FStarC.TypeChecker.Primops.MachineInts.fst` decides literal
range predicates by bit length. Direct BV literals and explicit refinement
ascriptions therefore have no demonstrated isolation penalty here. Repeated
`assert_norm` inside a large nested term is expensive: the 1,000-binding BV
variant took 89.51 s and 3.33 GiB RSS, versus 10.11 s and 1.40 GiB for direct
literals. Assertions alone are much cheaper than assertions embedded in
nested refined bindings.

Three BV-1000 repetitions measured 8.69 s median with cache writing disabled
and 8.71 s with it enabled. Writing increased median peak RSS from 1,422 to
1,437 MiB and produced a 3.69 MiB file, but did not produce a meaningful wall
time increase on this host.

## What the encoding size is

The synthetic workload does **not** reproduce a 500 MB file or SMT-LIB query.
Its largest checked artifact is 3.90 MiB. For BV-1000, the 3.69 MiB marshalled
checked file prints as 6.40 MB through `--read_checked_file`; 6.23 MB of that
text is the exported SMT declaration AST, while the checked module and SMT
fvar table account for about 72 KB and 59 KB respectively. The printable SMT
section contains 3,325 `declare-fun`, 4,251 `assert`, and 1,233 `define-fun`
forms.

The largest concrete exported blocks are:

| Declaration block | Printable SMT encoding |
|---|---:|
| 120-field `state_t` record and projections | 4.24 MB |
| 1,000-binding `step` | 1.12 MB |
| 50-field `input_t` record and projections | 0.61 MB |
| 25-field `output_t` record and projections | 0.20 MB |

Large records dominate because F* exports constructor declarations, typing and
inversion axioms, discriminator/projection declarations, projection typing,
and projection equations for every field. The large `step` is exported as one
definition retaining its nested body. A real 500 MB report should therefore
first identify whether it refers to this in-memory/exported declaration AST,
its printable form, a complete solver query including dependencies, or the
marshalled `.checked` container; these measurements show they are not
interchangeable.

`FStarC.Universal.tc_source_file` checks declarations and then calls
`encode_modul`, after which `store_module_to_cache` persists the checked module
and exported SMT encoding. `FStarC.SMTEncoding.Env.module_encoding` documents
that `me_decls` is the bulk encoding. `FStarC.CheckedFiles` stores its pruning
index and fvars alongside those declarations, and
`FStarC.Util.save_3values_to_file` separately marshals, hashes, and writes the
checked metadata and SMT payload. Peak RSS is consequently transient compiler
state, not the size of emitted SMT-LIB or the checked file.
