# Compiler encoding benchmarks

This benchmark generates deterministic transition functions that compare
concrete-width `FStar.BV` operations with corresponding `FStar.UInt`
operations. Both representations use seed `20261021`, the same record widths,
literals, child calls, dependency choices, and output selection.

The matched operations are bitwise AND/OR/XOR/NOT, modular addition, constant
left shift, conditionals, low-bit extraction, concatenation, and two-fold
replication. The UInt forms of the last three use `to_uint_t` and arithmetic.
Dynamic BV shifts are not included because their shift operand is itself a BV,
unlike `FStar.UInt.shift_left`.

Generate sources and their SHA-256 manifest:

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

The generator also emits the four 400-literal isolation workloads from the
benchmark specification and direct, refined-ascription, and normalized-
assertion BV variants at the largest requested binding count.

See [RESULTS.md](RESULTS.md) for the initial measurements and diagnosis.

## Initial-results commands

The initial report used the following separate runs. `run.py` intentionally
replaces `measurements.jsonl` for each run.

```sh
FSTAR=/path/to/fstar.exe
Z3VERSION=5.3.0

./run.py --fstar "$FSTAR" --z3version "$Z3VERSION" \
  --bindings 100 250 500 1000 --repeats 1
cp _results/measurements.jsonl _results/full-sweep.jsonl

./run.py --fstar "$FSTAR" --z3version "$Z3VERSION" \
  --bindings 500 --repeats 3 --modes no-write --only Direct500
cp _results/measurements.jsonl _results/direct500-repeats.jsonl

./run.py --fstar "$FSTAR" --z3version "$Z3VERSION" \
  --bindings 1000 --repeats 3 --modes write no-write --only BvDirect1000
cp _results/measurements.jsonl _results/bv1000-cache-repeats.jsonl
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
