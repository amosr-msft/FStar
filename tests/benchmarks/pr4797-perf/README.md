# PR #4797 performance controls

`ASYMPTOTIC_ANALYSIS.md` reviews the exact base/head source diff and traces the
changed path helpers through parser, dependency, diagnostic, checked-file, and
IDE call sites. It uses no timing probe.

Download artifact `bench-pr-4797` from Actions run `40991738766`, then:

```sh
python analyze_ci_artifact.py \
  --artifact /path/to/unpacked/bench-pr-4797 \
  --output CI_ARTIFACT_ANALYSIS.json

python run_startup_benchmark.py \
  --base /path/to/base-c68959fe \
  --head /path/to/head-e2c45ed0 \
  --cpu 16 --batches 5 --iterations 1000 \
  --output STARTUP_CPU16.json
```

The remote worker grants `/workspace/wt11`, but Copilot CLI's shell path
checker rejected the token `../../stage2/out/bin/fstar.exe` even after a shell
`cd`; the corresponding absolute path under `/workspace/wt11` was accepted.
This is observed heuristic behavior, not a claim about the checker's internal
implementation. All source runners therefore pass explicit absolute paths.

End-to-end verification and dependency checks require explicit absolute paths
under the CLI's granted worktree:

```sh
python run_source_workloads.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --head /workspace/wt11/FStar-pr4797-perf \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-source-workloads \
  --cpu 16 --repetitions 5

python run_rebuild_control.py \
  --original /workspace/wt11/FStar-pr4797-perf \
  --rebuild /workspace/wt11/FStar-pr4797-head-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-rebuild-control \
  --cpu 16 --repetitions 3

python run_dependency_focus.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --head /workspace/wt11/FStar-pr4797-perf \
  --rebuild /workspace/wt11/FStar-pr4797-head-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-dependency-focus \
  --cpu 16 --repetitions 20

python run_startup_rebuild_control.py \
  --original /workspace/wt11/FStar-pr4797-perf \
  --rebuild /workspace/wt11/FStar-pr4797-head-rebuild \
  --output STARTUP_REBUILD_CPU16.json \
  --cpu 16 --batches 5 --iterations 1000

python run_entry_counters.py \
  --worktree /workspace/wt11/FStar-pr4797-perf \
  --fstar /path/to/instrumented/fstarc3_full.exe \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output ENTRY_COUNTERS.json

python summarize_source_workloads.py \
  --source /workspace/wt11/pr4797-source-workloads \
  --rebuild /workspace/wt11/pr4797-rebuild-control \
  --dependency /workspace/wt11/pr4797-dependency-focus \
  --startup-rebuild STARTUP_REBUILD_CPU16.json \
  --entry-counters ENTRY_COUNTERS.json \
  --output SOURCE_WORKLOADS.json
```

The final source-name cache comparison uses:

```sh
# The candidate worktree may include later test-only commits; runners verify
# that production sources still match f4886d2dec and pin the benchmark binary.

python run_source_name_cache_three_way.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --pr /workspace/wt11/FStar-pr4797-perf \
  --cached /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-cache-source-three-way \
  --cpu 16 --repetitions 5

python run_source_name_cache_three_way.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --pr /workspace/wt11/FStar-pr4797-perf \
  --cached /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-cache-dependency-three-way \
  --cpu 16 --repetitions 20 --dependency-only

python run_source_name_root_scaling.py \
  --pr /workspace/wt11/FStar-pr4797-perf \
  --cached /workspace/wt11/FStar-pr4797-source-name-cache \
  --output /workspace/wt11/pr4797-cache-root-scaling \
  --cpu 16

python run_cache_rebuild_control.py \
  --original /workspace/wt11/FStar-pr4797-source-name-cache \
  --rebuild /workspace/wt11/FStar-pr4797-cache-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-cache-rebuild-control \
  --cpu 16 --repetitions 5

python instrument_source_name_cache.py \
  /workspace/wt11/FStar-pr4797-source-name-cache
# Rebuild stage3/fstarc-full as above, then:
python run_source_name_cache_counters.py \
  --worktree /workspace/wt11/FStar-pr4797-source-name-cache \
  --fstar /path/to/instrumented/fstarc3_full.exe \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output SOURCE_NAME_CACHE_COUNTERS.json \
  --cpu 16

python summarize_source_name_cache.py \
  --source /workspace/wt11/pr4797-cache-source-three-way \
  --dependency /workspace/wt11/pr4797-cache-dependency-three-way \
  --rebuild /workspace/wt11/pr4797-cache-rebuild-control \
  --scaling /workspace/wt11/pr4797-cache-root-scaling/result.json \
  --counters SOURCE_NAME_CACHE_COUNTERS.json \
  --output SOURCE_NAME_CACHE_RESULTS.json
```

The cache-miss follow-up compares `f4886d2dec` with `c939875498`:

```sh
python run_source_name_cache_three_way.py \
  --cached /workspace/wt11/FStar-pr4797-cache-rebuild \
  --optimized /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-miss-source-pairs-final \
  --cpu 16 --repetitions 5

python run_source_name_cache_three_way.py \
  --cached /workspace/wt11/FStar-pr4797-cache-rebuild \
  --optimized /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-miss-dependency-pairs-final \
  --cpu 16 --repetitions 20 --dependency-only

python run_source_name_miss_scaling.py \
  --cached /workspace/wt11/FStar-pr4797-cache-rebuild \
  --optimized /workspace/wt11/FStar-pr4797-source-name-cache \
  --output /workspace/wt11/pr4797-miss-scaling \
  --cpu 16

python run_cache_rebuild_control.py \
  --original /workspace/wt11/FStar-pr4797-source-name-cache \
  --rebuild /workspace/wt11/FStar-pr4797-miss-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-miss-rebuild-control \
  --cpu 16 --repetitions 5 --optimized

python run_source_name_cache_three_way.py \
  --cached /workspace/wt11/FStar-pr4797-cache-rebuild \
  --optimized /workspace/wt11/FStar-pr4797-miss-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-miss-source-rebuild-pairs-final \
  --cpu 16 --repetitions 5

python summarize_source_name_miss.py \
  --source /workspace/wt11/pr4797-miss-source-pairs-final \
  --dependency /workspace/wt11/pr4797-miss-dependency-pairs-final \
  --rebuild /workspace/wt11/pr4797-miss-rebuild-control \
  --rebuilt-source /workspace/wt11/pr4797-miss-source-rebuild-pairs-final \
  --scaling /workspace/wt11/pr4797-miss-scaling/result.json \
  --output SOURCE_NAME_MISS_RESULTS.json
```

`source_name_fallback_probe.ml` is the focused cross-revision fixture for the
unresolved absolute `.`/`..` fallback corrected after benchmarking in
`adbf7292f2`.

Compile the probe against each revision's
`stage2/dune/_build/default/fstar-guts/fstarcompiler.cmxa`, then run:

```sh
/path/to/source_name_fallback_probe.exe \
  /workspace/wt11/pr4797-fallback-fixture/include \
  /workspace/wt11/pr4797-fallback-fixture/outside/absent
```

The existing cache (`f4886d2dec`) and corrected head (`adbf7292f2`) print:

```text
.=.
..=..
missing.fst=missing.fst
```

The benchmarked pre-correction `c939875498` printed `.=absent` and
`..=outside`.

Latest CI outliers from Actions run `41602245606` are reproduced with:

```sh
PATH=/workspace/wt11/benchmark-tools/bin:$PATH \
make -C /workspace/wt11/FStar-pr4797-base -j8 3
PATH=/workspace/wt11/benchmark-tools/bin:$PATH \
make -C /workspace/wt11/FStar-pr4797-source-name-cache -j8 3

# Preseed the complete Pulse dependency caches in each worktree. Repeat these
# two commands with the matching head paths/compiler.
PATH=/workspace/wt11/benchmark-tools/bin:$PATH \
make -C /workspace/wt11/FStar-pr4797-base/pulse/share/pulse/examples/protocol/calc \
  STAGE3=1 \
  FSTAR_EXE=/workspace/wt11/FStar-pr4797-base/stage3/out/bin/fstar.exe \
  _cache/Calc.Protocol.fst.checked _cache/Calc.Log.fst.checked
PATH=/workspace/wt11/benchmark-tools/bin:$PATH \
make -C /workspace/wt11/FStar-pr4797-base/pulse/share/pulse/examples/protocol/tftp \
  STAGE3=1 \
  FSTAR_EXE=/workspace/wt11/FStar-pr4797-base/stage3/out/bin/fstar.exe \
  _cache/TFTP.Impl.Client.Log.fst.checked

python run_latest_outliers.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --head /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-latest-nonpulse-loops-final \
  --cpu 16 \
  --workloads ext-uint-mask bv-model ext-uint-unsigned

# The final committed Pulse rows were rerun from the exact suite cwd after
# hardening that detail; they replace Pulse rows from the broad local campaign.
python run_latest_outliers.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --head /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-latest-pulse-loops-final \
  --cpu 16 \
  --workloads calc-protocol tftp-client-log calc-log

python summarize_latest_outliers.py \
  --campaign /workspace/wt11/pr4797-latest-nonpulse-loops-final \
  --pulse-campaign /workspace/wt11/pr4797-latest-pulse-loops-final \
  --artifact /workspace/wt11/pr4797-latest-artifact \
  --output LATEST_OUTLIER_RESULTS.json
```

`instrument_entry_counters.py` modifies ignored extracted OCaml in
`stage2/fstarc.ml`. Build the Pulse prerequisite and diagnostic compiler before
running the counter campaign:

```sh
python instrument_entry_counters.py /workspace/wt11/FStar-pr4797-perf

make -C /workspace/wt11/FStar-pr4797-perf/pulse plugin.extract \
  FSTAR_EXE=/workspace/wt11/FStar-pr4797-perf/stage2/out/bin/fstar.exe

PATH=/workspace/wt11/benchmark-tools/bin:$PATH \
make -C /workspace/wt11/FStar-pr4797-perf/stage3 -j8 fstarc-full \
  FSTAR_DUNE_RELEASE=1

/workspace/wt11/FStar-pr4797-perf/stage3/dune/_build/default/\
fstarc-full/fstarc3_full.exe --version
```

The final command confirms that startup does not execute the changed helpers.

The two OCaml harnesses link against each revision's
`stage2/dune/_build/default/fstar-guts/fstarcompiler.cmxa`. They isolate hot
`source_file_name` and `mk_rng` cost; they are controls, not end-to-end
benchmarks:

```sh
python run_internal_microbenchmarks.py \
  --base /path/to/base-c68959fe \
  --head /path/to/head-e2c45ed0 \
  --cpu 16 \
  --output INTERNAL_MICROBENCHMARKS.json
```
