# PR #4797 performance investigation

## Scope and provenance

This investigates the benchmarking report for hierarchical source filenames
without changing PR #4797 or combining it with ambient-pruning work.

- baseline: `c68959fe1f070cd66a5ed2e92965185505f109ce`
- PR head: `e2c45ed0c4099f8d27ef0d78641ca8b626f4cdcb`
- CI run: `40991738766`
- artifact: `bench-pr-4797` (`12953627090`)
- local compiler: OCaml 4.14.2, clean stage2 builds from each exact revision
- local affinity control: CPU 16, sanitized locale/runtime environment

The downloaded artifact contains the HTML report, 7,046 raw `.ramon` files,
and 5,774 `.fstarmem` files. `analyze_ci_artifact.py` pairs and validates the
raw records rather than
relying only on the report's outlier tables. The HTML has 3,477 matched rows;
3,411 have raw pairs. All 66 missing raw rows are hidden `.depend.ramon` files,
which the artifact upload omitted.

## What changed on common paths

The PR changes stored range filenames from basenames to include-relative paths.
The parser now calls `Find.source_file_name` at lexer and Pratt entry. That
function resolves relative names through the include path, normalizes absolute
names, and scans normalized include roots for the longest applicable root.
Dependency generation and a few warning/IDE entry points call it as well.

The central range constructor changed in the opposite performance direction:
`mk_rng` no longer calls `Filepath.basename` for every constructed range. Text
diagnostics also stopped resolving every issue range; only structured locations
need an absolute path.

## CI evidence

The report's "time" is `group.total`: process-group CPU time, not wall time.
The HTML's 3,424 rows with baseline CPU at least 0.1 seconds have a 1.0225x
geometric ratio, +2.19% median, and +71.54 seconds total. Of those, 3,367 have
raw records that separate root and child CPU:

| Metric | Geometric ratio | Median change | Total change |
|---|---:|---:|---:|
| process-group CPU | 1.0217x | +2.16% | +69.09 s |
| process-group user CPU | 1.0239x | +2.26% | +64.92 s |
| F* root user CPU | 1.0260x | +1.98% | +56.55 s |
| F* root system CPU | 1.0152x | 0.00% | +3.89 s |
| wall time | 1.0190x | +1.80% | +60.98 s |

For 711 rows with at least 0.05 seconds of inferred child CPU
(`group.total - root.utime - root.stime`), child CPU has a **0.9965x**
geometric ratio and 0.0% median. The broad shift is therefore in F* process
CPU, not Z3 or extraction children.

The relative headline is dominated by short processes:

| Baseline CPU band | Rows | Median absolute change | Median percent |
|---|---:|---:|---:|
| 0.1-0.2 s | 861 | +0.004 s | +2.53% |
| 0.2-0.5 s | 967 | +0.007 s | +2.23% |
| 0.5-1 s | 1,151 | +0.013 s | +2.06% |
| 1-2 s | 294 | +0.032 s | +2.25% |
| 2-5 s | 79 | +0.021 s | +0.70% |
| 5-20 s | 49 | +0.058 s | +0.64% |
| 20 s and above | 23 | +0.696 s | +0.61% |

Long outliers are not one phenomenon. `NormBudget.rejected` is entirely F*
CPU (229.96 to 243.05 seconds). `ExtIntDivRem.fst.checked` is almost entirely a
child process (F* root 0.55 to 0.59 seconds while group CPU moves 16.82 to
18.07 seconds). `BvModelAgreesWithZ3` moves 207.13 to 211.71 seconds, with F*
root user CPU 180.10 to 184.07 seconds and similar child CPU. A single
sequential base-then-head CI run cannot establish that these individual
long-tail changes are caused by the filename patch.

## Fixed-CPU startup control

`run_startup_benchmark.py` runs five randomized base/head batches, 1,000
fresh `fstar.exe --version` processes per batch, all inherited on CPU 16.
This path parses no source file and invokes no solver.

| Metric per 1,000 starts | Baseline median | Head median | Change |
|---|---:|---:|---:|
| user CPU | 17.422 s | 17.904 s | +2.77% |
| system CPU | 18.866 s | 18.621 s | -1.30% |
| wall | 36.567 s | 36.780 s | +0.58% |
| involuntary context switches | 1,371 | 1,375 | +4 |

Total CPU increases by about 0.24 milliseconds per invocation. This is much
smaller than the typical 4-13 millisecond CI difference and cannot explain the
headline shift by itself.

An extracted diagnostic counted calls during `--version`:

```text
PR4797_COUNTER source_file_name=0
PR4797_COUNTER mk_rng=0
```

The two executables make the same 90 startup syscalls in `strace -c`; syscall
counts do not explain the user-CPU difference. More importantly, a clean second
build of the exact same `e2c45ed0c4` source produced a different binary hash.
Across five more 1,000-process pairs, that rebuild is **0.59 seconds user CPU**
and **0.75 seconds wall** faster per batch than the original head binary. This
same-source difference is larger than the original base/head startup gap.
Startup timing is therefore build-artifact/code-layout variability, not an
attributable source regression. Hardware instruction counters are unavailable
on this host, so its lower-level cause remains unresolved.

## Helper controls

The hot-cache `source_file_name` microbenchmark takes 17.39 microseconds per
absolute call and 17.42 microseconds per relative call. Parser entry currently
calls it twice, so this is tens of microseconds per parsed source, not the
millisecond-scale broad shift.

The changed range constructor is faster in isolation: 10 million calls take a
0.052287-second median at the baseline and 0.026571 seconds at the head. The
patch removes basename processing from this high-frequency operation; it is not
an attributable regression mechanism.

## End-to-end source workloads

The relative-path approval failure was a command-token path check: absolute
compiler, solver, include, output, and source paths under `/workspace/wt11`
were accepted. The end-to-end runner uses only those explicit paths. It forces
source checking, isolates cache/output directories, pins F* and inherited
children to CPU 16, randomizes adjacent base/head pairs, and samples root and
child process CPU separately.

Five-pair results do not reproduce the CI slowdown:

| Workload | Paired head-base root CPU | Paired child CPU | Paired wall |
|---|---:|---:|---:|
| `Normalization` | 0.00 s | 0.00 s | +0.002 s |
| `BvBinaryOps` | -0.01 s | -0.03 s | -0.069 s |
| `Bug3207` | -0.05 s | -0.01 s | -0.076 s |
| `tests/calc/Long` | -0.53 s | 0.00 s | -0.825 s |
| `ArrowUnfoldLimit` | -0.83 s | 0.00 s | -1.422 s |
| `Bug3207 --dep full` | +0.01 s | 0.00 s | +0.015 s |

Two independently built binaries from the same PR source differ by -0.27 and
-0.18 seconds median wall on Long and Arrow. Build/run variability contributes
to the observed direction, although it is smaller than the base/head
differences. Since the task is regression investigation, no performance benefit
is attributed to the filename change from these data.

Dependency generation is the one repeatable source effect. A focused 20-triple
base/original-head/rebuilt-head campaign gives paired median wall changes of:

| Comparison | Median | Mean |
|---|---:|---:|
| original head - base | +6.07 ms | +7.26 ms |
| rebuilt head - base | +3.78 ms | +2.99 ms |
| rebuild - original head | -5.58 ms | -4.27 ms |

Both independent PR builds are slower than base, but they also differ from each
other at this scale. An extracted counter on the same
`Bug3207 --dep full` command records 159 `source_file_name` calls taking
**4.493 ms total**, plus 8,814 range constructions. This matches the magnitude
of the 3-7 ms dependency difference and supports filename normalization as its
likely source, while build variability prevents a more precise attribution.
`Normalization` and `BvBinaryOps` spend 2.632 and 2.109 ms respectively in 101
and 90 filename calls, but do not regress end to end; they also construct 3,514
and 14,115 ranges, where the PR removed basename processing.

## Conclusion

The CI's 1.022x broad result is real in its single sequential run, but it does
not reproduce as a broad source regression:

1. Most of the relative shift is thousands of short F* processes.
2. The original startup shift is not stable across identical-source builds.
3. Representative verification workloads are neutral or faster at the PR head.
4. Child-process CPU is neutral in aggregate; solver-heavy outliers must be
   treated separately.
5. Dependency generation repeats a small 3-7 ms difference consistent with
   repeated `source_file_name` resolution.

The strongest supported conclusion is that the headline combines build/layout
and single-run variation with one narrow dependency-generation cost. The long
CI outliers remain unattributed. No production change is justified in this
round: preserving hierarchical filenames is required, and dependency
generation's few milliseconds do not explain the broad or long-test headline.

The separate `ASYMPTOTIC_ANALYSIS.md` finds one avoidable scaling risk:
`source_file_name` scans all expanded include roots even after its internal
`find_file` lookup is cached, and ordinary parsing invokes it twice per file
(three times per incremental IDE chunk). A final-result cache cleared by
`Find.clear` would preserve semantics and remove repeated scans. This finding
does not establish that the CI headline came from the path change.

## Final source-name cache experiment

The production experiment at `f4886d2dec` adds only a final
`source_file_name` hash cache beside `find_file_cache` and clears it from
`Find.clear`. A focused internal regression checks repeated hierarchical
lookups and invalidation through both include-path and file-list changes.
Follow-up commits wire that regression into `tests/ide all` and isolate its
build artifacts; the branch head is `25e2ae0571`. The compiler build, bootstrap
diff, and regression pass.

A structural CPU-16 probe performs 20,000 hot identical lookups after warming
the caches:

| Expanded roots | Unchanged PR | Cached PR |
|---:|---:|---:|
| 1 | 0.365 s | 0.00111 s |
| 16 | 0.371 s | 0.00111 s |
| 64 | 0.399 s | 0.00113 s |
| 256 | 0.495 s | 0.00098 s |

This establishes the intended scaling change for repeated identical inputs. It
is not an end-to-end speedup claim.

The source suite was repeated as five randomized CPU-16 triples: exact base,
unchanged PR, and cached PR. Paired cached-minus-PR medians are:

| Workload | F* root CPU | Child CPU | Wall | Peak RSS |
|---|---:|---:|---:|---:|
| `Normalization` | 0.00 s | 0.00 s | +0.001 s | +0.62 MiB |
| `BvBinaryOps` | 0.00 s | -0.03 s | -0.035 s | +0.23 MiB |
| `Bug3207` | +0.01 s | +0.02 s | +0.070 s | -0.16 MiB |
| `tests/calc/Long` | +0.40 s | 0.00 s | +0.645 s | +5.34 MiB |
| `ArrowUnfoldLimit` | +0.13 s | 0.00 s | +0.256 s | -1.31 MiB |

The Long/Arrow direction is not attributable to the cache. A second clean
build of the exact `f4886d2dec` source is 1.24 seconds median wall and
0.81 seconds F* CPU faster than the original candidate on Long. On Arrow its
paired wall differences span -1.53 to +3.05 seconds, with a +0.46-second
median; that same-source spread exceeds the +0.26-second cached-versus-PR
median. Normalization is neutral; BV is slightly faster; the Bug3207 difference
is small relative to observed variability. No ordinary or long workload has a
demonstrated cache regression.

The focused dependency campaign used 20 randomized triples. Paired wall
medians are:

| Comparison | Wall |
|---|---:|
| unchanged PR - base | +6.9 ms |
| cached PR - base | +14.5 ms |
| cached PR - unchanged PR | +3.5 ms |

The cache does **not** reduce the narrow dependency cost. An extracted
diagnostic explains why: `Bug3207 --dep full` makes 159
`source_file_name` calls but only four cache hits. `Normalization` makes 101
calls with 26 hits. Dependency generation mostly converts distinct filenames,
so final-result memoization cannot remove its first ownership scan. The
cached-versus-PR dependency difference is only a few milliseconds, below
precise attribution with the current CPU sampling and comparable to
same-source build variation.

Peak-memory differences are small and inconsistent. Cached-minus-PR median RSS
ranges from -1.31 to +5.34 MiB in source workloads and is -0.10 MiB in the
dependency campaign. There is no measured systematic retention increase.

The cache is therefore useful as a bounded asymptotic improvement for repeated
parser/IDE inputs, but it does not fix the previously measured dependency gap
and provides no evidence that it explains the original 1.022x CI result.

## Cache-miss path follow-up

The follow-up implementation at `c939875498` keeps the final-result cache and
reduces first/distinct-input work without changing public path contracts:

- resolved paths are normalized once before the normalized-path helper;
- the filename dirname is computed at most once when any flat root exists;
- normalized root boundary prefixes are prepared in the existing include-root
  cache instead of allocated for every distinct filename.

The focused regression now also covers overlapping roots, longest-root
selection, flat roots, and path boundaries. Build, bootstrap diff, and the
wired regression pass.

A structural control converts 5,000 distinct nonexistent absolute filenames,
so every call is a final-result cache miss:

| Expanded roots | Existing cache | Miss-optimized | Change |
|---:|---:|---:|---:|
| 1 | 0.0820 s | 0.0806 s | -1.6% |
| 16 | 0.0872 s | 0.0854 s | -2.0% |
| 64 | 0.1157 s | 0.1092 s | -5.7% |
| 256 | 0.2302 s | 0.2057 s | -10.7% |

This demonstrates the intended miss-path reduction as include-root count
grows. The lookup remains linear in root count, as required by the unchanged
longest-root scan.

The focused 20-pair dependency campaign, where the previous counter found
155 misses among 159 calls, changes by:

| Metric, optimized - existing cache | Median | Mean |
|---|---:|---:|
| F* root CPU | 0.00 s | -0.004 s |
| child CPU | 0.00 s | 0.00 s |
| wall | -1.7 ms | -2.6 ms |
| peak RSS | +0.24 MiB | +0.20 MiB |

The miss-path changes slightly reduce dependency wall time, but the result is
small relative to run-to-run variation and 10 ms CPU accounting granularity.
They do not eliminate the earlier base-to-PR dependency difference.

Five-pair source controls against the original cached build show Normalization
neutral, BV -0.03 seconds wall, Arrow -0.85 seconds, and Long apparently
+0.65 seconds F* CPU/+1.08 seconds wall. A clean rebuild of the exact optimized
source is 0.27 seconds F* CPU faster than the original optimized binary on
Long. Pairing that rebuilt binary against the existing cache removes the Long
signal: -0.20 seconds F* CPU and -0.11 seconds wall median. Normalization is
-0.01/-0.008 seconds. BV shifts from -0.03 to +0.02 seconds wall across builds.
No Long, Normalization, or BV regression is attributable to the miss
optimization.

Bug3207 remains a small adverse signal: optimized-minus-cached wall medians are
+0.027 seconds for the original optimized build and +0.056 seconds for the
rebuild. F* CPU is 0.00/+0.02 seconds, while child CPU is +0.01/0.00 seconds.
This is retained as a small repeatable wall signal, but is too close to
build/run variation to assign to one miss-path operation.

Arrow is faster with both optimized builds (-0.85 and -0.32 seconds wall), but
the magnitude remains build-dependent; no source speedup is claimed.

Peak RSS is likewise build-sensitive. The rebuilt optimized comparison changes
median RSS by -1.80 MiB on Long, +0.28 MiB on Normalization, +0.58 MiB on BV,
+0.20 MiB on Bug3207, and -31.75 MiB on Arrow. There is no consistent
miss-cache retention increase.

The miss optimization improves the targeted structural cost and provides a
small dependency-wall improvement. It still does not explain the original
1.022x CI result.

An independent review identified an off-benchmark fallback edge in
`c939875498`: for an unresolved absolute input ending in `.` or `..` outside
all include roots, ownership matching correctly used the normalized path, but
fallback basename also used that normalized path. The earlier cached
implementation returned basename of the original input. A direct fixture
confirmed `.`/`..` became `absent`/`outside`.

Correction `adbf7292f2` keeps the normalized ownership operand but supplies a
lazy basename fallback over the original unresolved input. The direct
cross-revision probe now matches the previous `.`/`..` output; build, bootstrap
diff, and the focused regression pass. The `.`/`..` edge inputs were not used
by the benchmark sources or structural probe, so the long benchmark campaign
was not repeated. The performance results above are labeled as `c939875498`;
the corrected branch head is `adbf7292f2`.

## Latest CI outlier loops

Actions run `41602245606` compares exact base `c68959fe1f` with corrected head
`adbf7292f2`. Its 3,477 matched tests have a 1.008x time geometric mean. The
full artifact identifies six meaningful loop candidates:

- the three largest absolute regressions: `ExtUIntMask`,
  `BvModelAgreesWithZ3`, and `ExtUIntUnsigned`;
- the two requested Pulse cases with complete recovered paths:
  `pulse/share/pulse/examples/protocol/calc/spec/Calc.Protocol.fst` and
  `pulse/share/pulse/examples/protocol/tftp/impl/TFTP.Impl.Client.Log.fst`;
- `Calc.Log`, the next-largest absolute Pulse increase (+1.30 seconds).

Raw `.ramon` data shows the CI mechanisms differ. ExtUIntMask and
ExtUIntUnsigned are almost entirely child CPU; BvModel is F* CPU;
Calc.Protocol is mainly F* CPU; TFTP Client Log and Calc.Log are mainly child
CPU.

The exact stage3 compilers and compiler-specific F*/Pulse dependency trees were
rebuilt locally. Each target used the raw CI flags and source, explicit
absolute paths, CPU 16 inherited by children, and adjacent randomized pairs.
Pulse dependencies were preseeded through their Makefile graph, then only the
current target checked file was removed before each raw invocation. Five pairs
were run for substantial workloads and ten for Calc.Protocol.

| Workload | CI group CPU Δ | Local F* CPU Δ | Local child CPU Δ | Local wall Δ | Head slower |
|---|---:|---:|---:|---:|---:|
| `ExtUIntMask` | +10.85 s | +0.01 s | +1.20 s | +2.21 s | 3/5 |
| `BvModelAgreesWithZ3` | +3.20 s | -3.58 s | -0.02 s | -5.30 s | 0/5 |
| `ExtUIntUnsigned` | +2.72 s | 0.00 s | +0.59 s | +0.89 s | 3/5 |
| `Calc.Protocol` | +0.44 s | +0.005 s | 0.00 s | +0.009 s | 5/10 |
| `TFTP.Impl.Client.Log` | +1.19 s | -0.02 s | -0.03 s | -0.097 s | 1/5 |
| `Calc.Log` | +1.30 s | -0.01 s | -0.12 s | -0.21 s | 2/5 |

Values are paired medians; “head slower” counts positive wall deltas. None of
the clear regressions repeats at its CI magnitude. BvModel and Pulse directions
do not repeat their CI mechanisms; the extraction cases remain child-dominated
but are sign-variable.

The two extraction cases retain weak same-direction medians, but not stable
regressions. ExtUIntMask child-CPU deltas range from -3.76 to +7.94 seconds and
wall deltas from -6.05 to +13.03 seconds; its +2.21-second wall median is much
smaller than CI's +11.94 seconds. ExtUIntUnsigned child CPU ranges from -2.98
to +3.00 seconds and wall from -5.07 to +4.86 seconds; its +0.89-second median
is smaller than CI's +2.21 seconds. Both have only three positive wall pairs.
Their child-dominated direction is compatible with the CI mechanism, but the
sign-changing observations do not establish a repeatable regression.

The CI BvModel F* heap rises by 34.28 MiB. Locally, every base and head run
reports the same 412.82 MiB F* heap; paired group RSS instead has a
-2.25 MiB median. The absolute local heap regime is lower than CI
(CI baseline 674.74 MiB), so only the local relative non-reproduction is
claimed. Other local F* heap comparisons are also byte-identical by workload.

TFTP Client Log has a +1.29 MiB paired median sampled group RSS, but deltas
range from -4.14 to +7.42 MiB and F* heap is byte-identical. No stable memory
regression is established.

The first local campaign stopped on a setup failure: all selected Pulse targets
had been removed before provenance, inadvertently removing Calc.Log, a
Calc.Protocol dependency. That directory is retained and none of its rows are
used. The corrected campaign restored full compiler-specific dependency caches
and completed all 70 rows with no failures or timeouts.

These loops do not reproduce the latest report's worst outliers. They do not
prove the 1.008x aggregate is noise; they show that its largest individual
contributors are not stable under matched repeated CPU-affinity controls.

## Broad representative reproduction

Repeating only worst outliers cannot test the report's +0.7% median/1.008x
geometric shift. A broader direction-balanced block therefore selected 15
checked-file targets across five duration bands (0.1 seconds through 40
seconds), with improved, neutral, and regressed CI rows in each band where
available. It covers ordinary verification and child-heavy extraction. The
full `tests/bug-reports/closed` dependency target is a sixteenth workload.

A repeated full suite was not practical: the hosted workflow takes about two
hours for one sequential base/head pair, so five interleaved pairs would take
roughly ten hours before controls. The representative selection and its limits
are recorded in `BROAD_REPRODUCTION_RESULTS.json`.

All 160 rows complete under CPU 16 using exact stage3 revisions, raw checked
target flags, source hashes, and compiler-specific dependency trees. The
selected checked targets themselves have a 1.0011x geometric ratio in the
single CI run; they are deliberately balanced rather than sampled to reproduce
the full report's 1.008x.

Local process-group CPU aggregates are:

| Set | Cell geometric ratio | Median change |
|---|---:|---:|
| 15 checked-file workloads | **1.0029x** | 0.0% |
| checked files plus dependency generation | **1.0108x** | 0.0% |

Across the five blocks, checked-file geometric ratios are 0.9909x, 0.9832x,
1.0066x, 1.0301x, and 1.0044x. A positive shift appears in three blocks and
reverses in two. The aggregate is positive but smaller than the full report's
1.008x and highly block-sensitive; this is evidence for a possible small broad
effect, not a stable 0.8% estimate.

Most individual CI directions also fail to persist. Examples:

| Workload | CI change | Local paired group CPU |
|---|---:|---:|
| `MergeSort2` | -5.9% | -0.5% |
| `TestMBQI` | +0.0% | +0.8% |
| `ExtUIntDivRem` | +5.9% | -0.4% |
| `BvBinaryOps` | +1.7% | +0.2% |
| `CanonCommSemiring` | +2.4% | -1.4% |
| `Long` | -0.2% | -2.0% |
| `ExtUIntRotate` | +2.3% | +0.4% |
| `RBTreeIntrinsic` | -1.6% | +0.4% |

Dependency generation amplifies the combined result from 1.0029x to 1.0108x.
The dependency target is slower in all five pairs: +0.43 seconds F* CPU and
+0.67 seconds wall median. An
independent build of the exact same `adbf7292f2` source is 0.08 seconds F* CPU
and 0.11 seconds wall faster than the original head binary, much smaller than
the base/head gap.

Path instrumentation on the exact absolute-input dependency command records:

- 1,716 `source_file_name` calls taking 0.128 seconds in total;
- 1,320 normalized ownership scans taking 0.280 seconds in total.

The latter includes calls made through `source_file_name` and direct dependency
module-name resolution, so these times must not be added. It accounts for most,
but not all, of the source-sensitive +0.43-second F* CPU gap. This localization
is consistent with the path-handling change.

There is an important invocation limitation. The hosted Makefile dependency
command uses relative source arguments, while this remote CLI requires explicit
authorized-root absolute paths. Absolute inputs exercise the same ownership
logic more directly and may amplify its cost. Accordingly, the dependency
result is evidence of a real absolute-path scaling cost, not a precise
reproduction of CI's +0.078-second `.depend` result.

The strongest supported result is a variable small checked-file shift
(1.0029x across all cells), plus a repeatable absolute-path dependency cost
that raises the combined representative block to 1.0108x. The checked result is
compatible with but smaller than the CI headline, and its block spread prevents
a precise estimate. This campaign neither cleanly reproduces nor rules out the
full 1.008x aggregate.

## Relative dependency-path control

The remote permission diagnosis had only established that relative executable
tokens were rejected. A direct execution-tool invocation confirmed that the
raw CI source manifest (`Bug016.fst ... RemoveUnusedTyparsIFace.A.fsti`) is
allowed from `tests/bug-reports/closed` when executable, solver, include, and
output paths remain absolute.

Twenty randomized CPU-16 pairs using that exact relative source list reproduce
the dependency gap unchanged:

| Metric, head - base | Median | Mean | Positive |
|---|---:|---:|---:|
| F* root CPU | +0.440 s | +0.443 s | 20/20 |
| child CPU | 0.000 s | 0.000 s | 0/20 |
| wall | +0.667 s | +0.675 s | 20/20 |
| sampled group RSS | -0.94 MiB | -0.93 MiB | 0/20 |

The prior absolute-input control was +0.43 seconds F* CPU/+0.67 seconds wall.
Absolute arguments did **not** create or materially amplify the regression.

Both baseline and head were instrumented on the exact relative command:

| Path | Base | Head |
|---|---:|---:|
| `module_name_from_include_path` | 562 calls, 0.131 s | 562 calls, 0.138 s |
| `source_file_name` | absent | 1,716 calls, 0.139 s |
| normalized ownership matcher | inlined in module-name timing | 1,124 calls, 0.260 s |
| instrumented F* root CPU | 1.85 s | 2.16 s |

The head ownership count is exactly two scans per dependency source: 562 from
the pre-existing module-name path and 562 from the new diagnostic-range
`source_file_name` conversion. `source_file_name` has 1,716 total calls, but
only the absolute/resolved subset enters ownership matching. The normalized
ownership timing is nested in both top-level timings and must not be added.

The pre-existing module-name work changes by only about 0.008 seconds. The
new diagnostic filename path contributes about 0.139 seconds total, including
roughly 0.122 seconds of the additional ownership scans. Instrumented root CPU
still differs by about 0.31 seconds, so the counters localize a substantial but
not complete part of the uninstrumented +0.44-second gap.

The smallest semantics-preserving next optimization is to memoize normalized
ownership results in `Find` and share that cache between
`relative_source_path` and `source_file_name`. Both APIs currently receive the
same normalized filename in this loop but scan roots independently. The cache
can use the existing `Find.clear` invalidation lifecycle. Removing the
diagnostic conversion or weakening hierarchical filenames is not justified.
No production change is made in this round.

## Shared ownership cache experiment

The follow-up implementation at `7da01c0b4a` adds one canonical
normalized-path-to-relative-ownership cache in `Find`. Both
`relative_source_path` and `source_file_name` use it, and `Find.clear`
invalidates it with the existing resolution caches. The final source-name cache
remains separate because it additionally memoizes file resolution and fallback
formatting. Positive and negative ownership results are cached.

The focused regression now exercises an ownership lookup followed by a source
name lookup, positive/negative results, include/file-list invalidation,
overlapping roots, flat roots, boundaries, and unresolved fallback names.
Build, bootstrap diff, and the wired test pass.

Twenty relative-manifest triples compare exact base, unchanged PR, and the
fixed compiler:

| Comparison | F* CPU median | Wall median | Positive |
|---|---:|---:|---:|
| unchanged PR - base | +0.405 s | +0.612 s | 19/20, 19/20 |
| original fixed build - base | +0.315 s | +0.488 s | 19/20, 19/20 |
| fixed - unchanged PR | -0.085 s | -0.126 s | 1/20, 1/20 |

The cache consistently recovers about 0.09 seconds F* CPU and 0.13 seconds
wall from the unchanged PR.

Native build identity remains material. A second build of the exact fixed
source is 0.24 seconds F* CPU and 0.39 seconds wall faster than the original
fixed binary in all 20 pairs. Substituting that rebuild into the same
base/PR/fixed triples yields:

| Comparison | F* CPU median | Wall median | Positive |
|---|---:|---:|---:|
| unchanged PR - base | +0.400 s | +0.618 s | 20/20, 20/20 |
| rebuilt fixed - base | +0.080 s | +0.116 s | 20/20, 20/20 |
| rebuilt fixed - unchanged PR | -0.320 s | -0.500 s | 0/20, 0/20 |

Thus the source-level residual is not measured precisely by one binary. Across
the two fixed builds, the base gap ranges from +0.08 to +0.315 seconds F* CPU.
The optimization clearly removes the duplicated ownership work, but build
variation dominates the remaining estimate.

The ownership cache retains one result per distinct normalized path until
`Find.clear`. Sampled group RSS increases consistently: fixed-minus-PR medians
are +2.75 MiB for the original fixed build and +2.02 MiB for the rebuild,
positive in all 20 pairs. This is the measured space cost of sharing ownership
results; no claim is made about OCaml heap capacity from sampled RSS.

Fixed-path diagnostics show:

- 1,124 ownership requests, 562 misses and 562 hits;
- 1,716 source-name requests, 562 misses;
- total `source_file_name` time about 0.008 seconds;
- 562 module-name conversions taking about 0.122-0.125 seconds.

This confirms the second ownership scan is gone. The measured path helpers no
longer expose another concrete hotspot, so no additional production
optimization is justified.

Representative source controls (rebuilt fixed versus unchanged PR) are neutral:

| Workload | F* CPU median | Child CPU median | Wall median |
|---|---:|---:|---:|
| `Normalization` | -0.01 s | 0.00 s | -0.020 s |
| `BvBinaryOps` | -0.01 s | +0.03 s | +0.026 s |
| `Long` | 0.00 s | +0.01 s | +0.047 s |

All are within observed pair variation; no shifted verification overhead is
established.

The ownership cache fixes a real, reproduced dependency inefficiency and
substantially reduces the gap. It does not by itself establish or fix the
full-suite 1.008x aggregate.

## Pre-CI memory and broader confidence

The consistent +2-3 MiB sampled RSS in dependency triples prompted a same-binary
retention diagnostic. The harness first allocates and retains the exact 562
filename inputs, forces major GC, populates only the ownership cache, forces
major GC, clears through `Find.clear`, and forces GC again.

The populated cache contains:

- 562 entries;
- 47,103 key characters;
- 6,639 relative-value characters;
- no negative entries for this manifest.

After forced major GC, cache population adds 30,882 live OCaml words
(approximately 241 KiB at 8 bytes/word). After `Find.clear` and another major
GC, live heap returns to within 389 words of the same-process input baseline.
The OCaml heap capacity remains exactly 126,976 words throughout.

RSS rises from 13,544 to 15,640 KiB (+2,096 KiB) on population and remains at
15,640 KiB after clear, despite
the live-word recovery and unchanged heap capacity. The obvious cache objects
therefore explain only a few hundred KiB of live data. The measured 2 MiB RSS
shape is consistent with page commitment or allocator/runtime behavior, not
2-3 MiB of persistently live ownership entries. Forced-GC snapshots are
diagnostic and are not normal-run timings.

For broader pre-CI confidence, the same 15 checked-file workloads were repeated
as ten randomized CPU-16 PR/fixed pairs (300 rows), with F* heap reports and
root/child CPU, wall, root RSS, and group RSS:

| Aggregate | Result |
|---|---:|
| process-group CPU geometric ratio | **0.9930x** |
| median cell change | **-0.18%** |
| blocks with fixed slower | 2/10 |

Block ratios range from 0.9756x to 1.0045x. No meaningful F* CPU regression is
visible in any selected workload. Representative paired medians:

| Workload | F* CPU | Child CPU | Wall | Group RSS | F* heap |
|---|---:|---:|---:|---:|---:|
| `BvBinaryOps` | -0.01 s | +0.03 s | +0.073 s | -0.22 MiB | 0 |
| `CanonCommSemiring` | -0.04 s | -0.01 s | -0.073 s | -0.33 MiB | 0 |
| `Long` | -0.185 s | 0.00 s | -0.280 s | +2.68 MiB | 0 |

Every paired F* heap delta across all 15 workloads is zero. Sampled RSS moves
in both directions by workload; Long's +2.68 MiB median is consistent with the
same page-commit signal seen in the retention diagnostic, not increased live
F* heap.

The broad selected set is not equivalent to the full CI suite, but these
additional 300 rows provide no evidence that the ownership cache shifts
ordinary verification overhead or OCaml peak heap. The measured tradeoff is a
small retained live cache (about 241 KiB for 562 paths) plus roughly 2 MiB of
process RSS/page commitment in the dependency-shaped process.

## Final source-name cache ablation

The compiler currently has three related caches: file resolution, normalized
ownership, and final source-name formatting. Experimental branch
`users/amos/20261105-fstar-pr4797-two-cache` removes only the outer final
source-name cache while retaining the other two and all structural filename
behavior. Physical string identity is intentionally not treated as an API
contract; no caller relies on it. Build, bootstrap diff, and the focused
structural regression pass.

Twenty dependency pairs show that the third cache earns its cost. Two
independent two-cache builds both regress versus the preserved three-cache
build:

| Two-cache build | F* CPU | Wall | Slower |
|---|---:|---:|---:|
| original | +0.155 s | +0.226 s | 20/20 |
| rebuild | +0.155 s | +0.218 s | 20/20 |

F* heap peaks are byte-identical. Sampled group RSS is +0.98 MiB for the
original two-cache build and -0.07 MiB for its rebuild, demonstrating native
layout/RSS variability rather than a reliable memory saving.

Representative source controls are mostly neutral and build-sensitive:

- Normalization is effectively neutral: original-build F* CPU/wall is
  +0.01/+0.010 seconds; rebuild is 0.00/-0.001 seconds.
- BvBinaryOps changes by about +0.01 seconds F* CPU; wall is +0.045/+0.089
  seconds across the two builds.
- Long changes from +0.67/+1.02 seconds to -0.25/-0.31 seconds across two-cache
  builds, so no source-level direction is assigned.

Hot repeated lookups show the main benefit. For 20,000 warmed identical calls:

| Expanded roots | Three caches | Two caches |
|---:|---:|---:|
| 1 | 0.00167 s | 0.11654 s |
| 16 | 0.00166 s | 0.11526 s |
| 64 | 0.00167 s | 0.11502 s |
| 256 | 0.00150 s | 0.11539 s |

The final cache is roughly 70 times faster on this repeated-input path.

Its incremental live storage is small. After the ownership stage is already
populated, the source-name stage adds 13,699 live words with three caches and
11,067 with two caches. The difference is 2,632 words, about 20.6 KiB at
8 bytes/word. The final table has 562 entries; key/value character payloads
are shared with existing strings where possible. Source-stage RSS increments
are 56 KiB versus 28 KiB in the two separate native builds, below meaningful
attribution.

Removing the final cache therefore saves only tens of KiB of live OCaml data,
does not reliably reduce RSS or F* heap, and costs about 0.16 seconds F* CPU on
the full dependency workload while severely degrading hot repeated lookups.
The third cache earns its cost and should be retained. The ablation remains on
its separate experimental branch.

## Limitations

- The CI workflow ran all baseline tests, then all head tests, once each.
- Local root/child CPU sampling has approximately 10 ms resolution; wall time
  is higher resolution.
- Fixed affinity does not reserve CPU 16 from other host workloads.
- Local extraction-child coverage comes from the preserved CI artifact; the
  local suite focuses on F* verification and dependency generation.
- No `perf` instruction/cycle counters are available on this host.
- No production source change or upstream comment/PR was made.
