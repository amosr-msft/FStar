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

Total CPU increases by about 0.24 milliseconds per invocation. This locally
reproduces a small broad process cost without source parsing, filename
normalization, or Z3. It can explain a meaningful part of the 4-13 millisecond
shift in the thousands of short CI processes, but not the multi-second
individual outliers.

An extracted diagnostic counted calls during `--version`:

```text
PR4797_COUNTER source_file_name=0
PR4797_COUNTER mk_rng=0
```

The two executables make the same 90 startup syscalls in `strace -c`; syscall
counts do not explain the user-CPU difference. The head binary adds 985 bytes
of text and 448 bytes of data. The supported explanation for the startup
component is native executable/module-initialization or code-layout cost from
the changed compilation units, not execution of the new filename lookup.
Hardware instruction counters are unavailable on this host, so the evidence
does not distinguish those two lower-level effects.

## Helper controls

The hot-cache `source_file_name` microbenchmark takes 17.39 microseconds per
absolute call and 17.42 microseconds per relative call. Parser entry currently
calls it twice, so this is tens of microseconds per parsed source, not the
millisecond-scale broad shift.

The changed range constructor is faster in isolation: 10 million calls take a
0.052287-second median at the baseline and 0.026571 seconds at the head. The
patch removes basename processing from this high-frequency operation; it is not
an attributable regression mechanism.

## Conclusion

The CI's 1.022x broad result is real in its single sequential run, but it does
not identify a semantic filename-path regression:

1. Most of the relative shift is thousands of short F* processes.
2. A smaller startup shift reproduces locally when no changed helper executes.
3. The new helper's measured per-module cost is too small, and the hot range
   constructor became faster.
4. Child-process CPU is neutral in aggregate; solver-heavy outliers must be
   treated separately.

The strongest supported cause is a small native executable
startup/initialization or code-layout effect, amplified by the suite's
per-artifact process model. The long-test variation remains unattributed by
this single sequential run.
There is no evidence-based production fix to apply: removing hierarchical
filenames would break the PR's behavior, and avoiding the duplicate parser
lookup would save only tens of microseconds per source while leaving the
reproduced startup effect unchanged.

## Limitations

- The CI workflow ran all baseline tests, then all head tests, once each.
- Local execution of F* source workloads was denied by the environment's
  non-interactive permission policy. No workaround was attempted.
- Local controls therefore cover startup and directly callable compiler
  helpers, while representative verification/extraction evidence comes from
  the preserved raw CI artifact.
- No `perf` instruction/cycle counters are available on this host.
- No production source change or upstream comment/PR was made.
