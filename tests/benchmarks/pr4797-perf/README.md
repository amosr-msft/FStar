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
