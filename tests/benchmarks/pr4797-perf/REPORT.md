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

## Limitations

- The CI workflow ran all baseline tests, then all head tests, once each.
- Local root/child CPU sampling has approximately 10 ms resolution; wall time
  is higher resolution.
- Fixed affinity does not reserve CPU 16 from other host workloads.
- Local extraction-child coverage comes from the preserved CI artifact; the
  local suite focuses on F* verification and dependency generation.
- No `perf` instruction/cycle counters are available on this host.
- No production source change or upstream comment/PR was made.
