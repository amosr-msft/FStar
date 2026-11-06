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

The broad representative campaign uses:

```sh
python run_broad_reproduction.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --head /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --artifact /workspace/wt11/pr4797-latest-artifact \
  --output /workspace/wt11/pr4797-broad-reproduction-final2 \
  --cpu 16 --repetitions 5

python run_dependency_rebuild_control.py \
  --original /workspace/wt11/FStar-pr4797-source-name-cache \
  --rebuild /workspace/wt11/FStar-pr4797-adbf-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-broad-dependency-rebuild-final2 \
  --cpu 16 --repetitions 5

# instrument_dependency_source_names.py modifies ignored stage3 extracted
# OCaml; rebuild fstarc-full and run the dependency command captured in the
# campaign JSON:
python instrument_dependency_source_names.py \
  /workspace/wt11/FStar-pr4797-source-name-cache
PATH=/workspace/wt11/benchmark-tools/bin:$PATH \
make -C /workspace/wt11/FStar-pr4797-source-name-cache/stage3 \
  -j8 fstarc-full FSTAR_DUNE_RELEASE=1
python run_dependency_diagnostic.py \
  --worktree /workspace/wt11/FStar-pr4797-source-name-cache \
  --fstar /path/to/instrumented/fstarc3_full.exe \
  --campaign /workspace/wt11/pr4797-broad-reproduction-final2 \
  --output /workspace/wt11/pr4797-broad-dependency-diagnostic-final3 \
  --cpu 16

python summarize_broad_reproduction.py \
  --campaign /workspace/wt11/pr4797-broad-reproduction-final2 \
  --dependency-rebuild /workspace/wt11/pr4797-broad-dependency-rebuild-final2 \
  --diagnostic /workspace/wt11/pr4797-broad-dependency-diagnostic-final3/result.json \
  --output BROAD_REPRODUCTION_RESULTS.json
```

The exact relative-source dependency follow-up uses:

```sh
python run_relative_dependency.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --head /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-relative-dependency \
  --cpu 16 --repetitions 20

# Instrument the pre-existing module-name path in both trees.
python instrument_module_name_path.py /workspace/wt11/FStar-pr4797-base
python instrument_module_name_path.py \
  /workspace/wt11/FStar-pr4797-source-name-cache

# Instrument the head's Find helpers.
python instrument_dependency_source_names.py \
  /workspace/wt11/FStar-pr4797-source-name-cache

PATH=/workspace/wt11/benchmark-tools/bin:$PATH \
make -C /workspace/wt11/FStar-pr4797-base/stage3 \
  -j8 fstarc-full FSTAR_DUNE_RELEASE=1
PATH=/workspace/wt11/benchmark-tools/bin:$PATH \
make -C /workspace/wt11/FStar-pr4797-source-name-cache/stage3 \
  -j8 fstarc-full FSTAR_DUNE_RELEASE=1

python run_relative_dependency_diagnostics.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --head /workspace/wt11/FStar-pr4797-source-name-cache \
  --campaign /workspace/wt11/pr4797-relative-dependency \
  --output /workspace/wt11/pr4797-relative-dependency-diagnostics \
  --cpu 16 --repetitions 3

python summarize_relative_dependency.py \
  --relative /workspace/wt11/pr4797-relative-dependency \
  --absolute /workspace/wt11/pr4797-broad-reproduction-final2 \
  --diagnostics /workspace/wt11/pr4797-relative-dependency-diagnostics \
  --output RELATIVE_DEPENDENCY_RESULTS.json
```

The shared ownership-cache experiment uses:

```sh
python run_ownership_cache_dependency.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --pr /workspace/wt11/FStar-pr4797-adbf-rebuild \
  --fixed /workspace/wt11/FStar-pr4797-source-name-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-ownership-dependency-final \
  --cpu 16 --repetitions 20

python run_ownership_cache_dependency.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --pr /workspace/wt11/FStar-pr4797-adbf-rebuild \
  --fixed /workspace/wt11/FStar-pr4797-owner-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-ownership-dependency-rebuilt \
  --cpu 16 --repetitions 20

python run_dependency_rebuild_control.py \
  --original /workspace/wt11/FStar-pr4797-source-name-cache \
  --rebuild /workspace/wt11/FStar-pr4797-owner-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-owner-rebuild-control \
  --cpu 16 --repetitions 20 --ownership

python run_ownership_source_controls.py \
  --base /workspace/wt11/FStar-pr4797-base \
  --pr /workspace/wt11/FStar-pr4797-adbf-rebuild \
  --fixed /workspace/wt11/FStar-pr4797-owner-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-owner-source-controls \
  --cpu 16 --repetitions 5

# Apply instrument_ownership_cache.py and instrument_module_name_path.py to
# the fixed stage3 extraction, rebuild fstarc-full, then:
python run_ownership_diagnostic.py \
  --worktree /workspace/wt11/FStar-pr4797-source-name-cache \
  --fstar /path/to/instrumented/fstarc3_full.exe \
  --campaign /workspace/wt11/pr4797-relative-dependency \
  --output /workspace/wt11/pr4797-owner-diagnostic-final2 \
  --cpu 16 --repetitions 3

python summarize_ownership_cache.py \
  --original /workspace/wt11/pr4797-ownership-dependency-final \
  --rebuilt /workspace/wt11/pr4797-ownership-dependency-rebuilt \
  --rebuild-control /workspace/wt11/pr4797-owner-rebuild-control \
  --source-controls /workspace/wt11/pr4797-owner-source-controls \
  --diagnostic /workspace/wt11/pr4797-owner-diagnostic-final2 \
  --output OWNERSHIP_CACHE_RESULTS.json
```

Pre-CI memory and broad controls use:

```sh
python run_ownership_cache_memory.py \
  --worktree /workspace/wt11/FStar-pr4797-source-name-cache \
  --output /workspace/wt11/pr4797-owner-memory-final2 \
  --cpu 16

python run_pr_fixed_broad.py \
  --pr /workspace/wt11/FStar-pr4797-adbf-rebuild \
  --fixed /workspace/wt11/FStar-pr4797-owner-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --artifact /workspace/wt11/pr4797-latest-artifact \
  --output /workspace/wt11/pr4797-owner-broad-confidence \
  --cpu 16 --repetitions 10

python summarize_pre_ci_confidence.py \
  --broad /workspace/wt11/pr4797-owner-broad-confidence \
  --memory OWNERSHIP_CACHE_MEMORY.json \
  --ownership OWNERSHIP_CACHE_RESULTS.json \
  --output PRE_CI_CONFIDENCE_RESULTS.json
```

The final source-name cache ablation uses:

```sh
python run_two_cache_ablation.py \
  --three /workspace/wt11/FStar-pr4797-owner-rebuild \
  --two /workspace/wt11/FStar-pr4797-two-cache \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-two-cache-ablation-final \
  --cpu 16 --dependency-repetitions 20 --source-repetitions 5

python run_two_cache_ablation.py \
  --three /workspace/wt11/FStar-pr4797-owner-rebuild \
  --two /workspace/wt11/FStar-pr4797-two-cache-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-two-cache-ablation-rebuilt \
  --cpu 16 --dependency-repetitions 20 --source-repetitions 5

python run_two_cache_hot.py \
  --three /workspace/wt11/FStar-pr4797-owner-rebuild \
  --two /workspace/wt11/FStar-pr4797-two-cache-rebuild \
  --output /workspace/wt11/pr4797-two-cache-hot \
  --cpu 16

python run_two_cache_memory.py \
  --three /workspace/wt11/FStar-pr4797-owner-rebuild \
  --two /workspace/wt11/FStar-pr4797-two-cache-rebuild \
  --output /workspace/wt11/pr4797-two-cache-memory \
  --cpu 16

python summarize_two_cache_ablation.py \
  --original /workspace/wt11/pr4797-two-cache-ablation-final \
  --rebuilt /workspace/wt11/pr4797-two-cache-ablation-rebuilt \
  --hot /workspace/wt11/pr4797-two-cache-hot \
  --memory /workspace/wt11/pr4797-two-cache-memory \
  --output TWO_CACHE_ABLATION_RESULTS.json
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

## Current-master root-trie comparison

`run_root_trie_comparison.py` verifies exact source and native artifact hashes
before running. Phase-one comparisons require `current-pr` and `no-flat`;
final comparisons require `master`, `no-flat`, and `trie`. For example:

```sh
python run_root_trie_comparison.py \
  --kind dependency --comparison trie \
  --variant master=/workspace/wt11/FStar-pr4797-master-current \
  --variant no-flat=/workspace/wt11/FStar-pr4797-no-flat \
  --variant trie=/workspace/wt11/FStar-pr4797-root-trie \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-root-trie-results/trie-dependency \
  --repetitions 20 --cpu 16 --timeout 180

python run_root_trie_comparison.py \
  --kind checked --comparison trie \
  --variant master=/workspace/wt11/FStar-pr4797-master-current \
  --variant no-flat=/workspace/wt11/FStar-pr4797-no-flat \
  --variant trie=/workspace/wt11/FStar-pr4797-root-trie \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --artifact /workspace/wt11/pr4797-latest-artifact \
  --output /workspace/wt11/pr4797-root-trie-results/trie-checked \
  --repetitions 5 --cpu 16

python run_root_trie_comparison.py \
  --kind structural --comparison trie \
  --variant master=/workspace/wt11/FStar-pr4797-master-current \
  --variant no-flat=/workspace/wt11/FStar-pr4797-no-flat \
  --variant trie=/workspace/wt11/FStar-pr4797-root-trie \
  --output /workspace/wt11/pr4797-root-trie-results/trie-structural \
  --repetitions 10 --cpu 16

python summarize_root_trie.py \
  --input /workspace/wt11/pr4797-root-trie-results \
  --output ROOT_TRIE_RESULTS.json
```

The structural process uses the public module-name API common to exact master
and the PR. Its cold metric includes `set_include_path`, root expansion, root
index construction, and one distinct ownership lookup.

## Cache-state grouping control

The cache-state driver extends the exact-artifact checks without changing the
root-trie campaign runner (whose hash is retained by the earlier evidence):

```sh
python run_cache_state_comparison.py \
  --kind dependency --comparison cache-state \
  --variant reviewed-trie=/workspace/wt11/FStar-pr4797-trie-reviewed \
  --variant cache-state=/workspace/wt11/FStar-pr4797-root-trie \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-cache-state-final/dependency \
  --repetitions 10 --cpu 16 --timeout 180

python run_cache_state_comparison.py \
  --kind checked --comparison cache-state \
  --variant reviewed-trie=/workspace/wt11/FStar-pr4797-trie-reviewed \
  --variant cache-state=/workspace/wt11/FStar-pr4797-root-trie \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --artifact /workspace/wt11/pr4797-latest-artifact \
  --output /workspace/wt11/pr4797-cache-state-final/checked \
  --repetitions 5 --workload test03 --workload bv-binary-ops \
  --workload long --cpu 16

python run_cache_state_rebuild_control.py \
  --kind checked --comparison cache-state-rebuild \
  --variant reviewed-trie=/workspace/wt11/FStar-pr4797-trie-reviewed \
  --variant cache-state=/workspace/wt11/FStar-pr4797-root-trie \
  --variant cache-state-rebuild=\
/workspace/wt11/FStar-pr4797-cache-state-final-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --artifact /workspace/wt11/pr4797-latest-artifact \
  --output /workspace/wt11/pr4797-cache-state-final/rebuild-control \
  --repetitions 5 --workload test03 --workload bv-binary-ops \
  --workload long --cpu 16

python summarize_cache_state.py \
  --input /workspace/wt11/pr4797-cache-state-final \
  --output CACHE_STATE_RESULTS.json
```

## Direct final trie versus current master

The direct comparison reuses the 15-workload raw-artifact harness. The broad
driver randomizes workload/repetition cells while assigning exactly ten
master-first and ten final-first pairs per workload:

```sh
python run_final_master_broad.py \
  --pr /workspace/wt11/FStar-pr4797-master-current \
  --fixed /workspace/wt11/FStar-pr4797-root-trie \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --artifact /workspace/wt11/pr4797-latest-artifact \
  --output /workspace/wt11/pr4797-final-master/broad \
  --repetitions 20 --cpu 16

python run_final_master_dependency.py \
  --kind dependency --comparison final-master \
  --variant master=/workspace/wt11/FStar-pr4797-master-current \
  --variant final=/workspace/wt11/FStar-pr4797-root-trie \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-final-master/dependency \
  --repetitions 20 --cpu 16 --timeout 180
```

The independently rebuilt BV/Long control uses exact rebuild hashes:

```sh
python run_final_master_rebuild.py \
  --kind checked --comparison final-master-rebuild \
  --variant master-rebuild=/workspace/wt11/FStar-pr4797-master-rebuild \
  --variant final-rebuild=\
/workspace/wt11/FStar-pr4797-cache-state-final-rebuild \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --artifact /workspace/wt11/pr4797-latest-artifact \
  --output /workspace/wt11/pr4797-final-master/rebuild-control \
  --repetitions 10 --workload bv-binary-ops --workload long \
  --cpu 16 --timeout 600

python summarize_final_master.py \
  --broad /workspace/wt11/pr4797-final-master/broad \
  --dependency /workspace/wt11/pr4797-final-master/dependency \
  --order-control \
    /workspace/wt11/pr4797-final-master/broad-aggregate-balanced \
  --rebuild-control \
    /workspace/wt11/pr4797-final-master/rebuild-control \
  --output FINAL_MASTER_RESULTS.json
```

`pr` and `fixed` in the inherited broad rows are explicitly aliased to master
and final grouped trie in provenance. The second broad block is retained as a
run-variation control but is not primary because only its aggregate direction
count, not every workload's count, is exactly balanced. Its exact historical
driver is preserved as `run_final_master_broad_aggregate_control.py`.

## Alternative root-index representations

The primary incumbent/forest/flat campaigns use:

```sh
python run_root_index_differential.py \
  --variant incumbent=/workspace/wt11/FStar-pr4797-root-trie \
  --variant forest=/workspace/wt11/FStar-pr4797-root-forest \
  --variant flat=/workspace/wt11/FStar-pr4797-flat-root-map \
  --output ROOT_INDEX_DIFFERENTIAL.json --cpu 16

python run_root_index_variants.py \
  --kind dependency --comparison trie \
  --variant incumbent=/workspace/wt11/FStar-pr4797-root-trie \
  --variant forest=/workspace/wt11/FStar-pr4797-root-forest \
  --variant flat=/workspace/wt11/FStar-pr4797-flat-root-map \
  --z3 /workspace/wt11/benchmark-tools/bin/z3-5.3.0 \
  --output /workspace/wt11/pr4797-root-index-variants/dependency \
  --repetitions 20 --cpu 16 --timeout 180
```

Run the same driver with `--kind checked`, the preserved raw artifact, and ten
repetitions; run `--kind structural` with ten repetitions. The driver balances
forward/reverse order for every variant pair within each workload or root
count. Independent dependency and BV/Long rebuild controls use
`run_root_index_rebuild_control.py`.

```sh
python summarize_root_index_variants.py \
  --input /workspace/wt11/pr4797-root-index-variants \
  --rebuild /workspace/wt11/pr4797-root-index-rebuild \
  --differential ROOT_INDEX_DIFFERENTIAL.json \
  --output ROOT_INDEX_VARIANT_RESULTS.json
```

The differential harness is evidence-only. No bespoke test was added back to
the production branches.

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
