# PR #4797 performance controls

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

`instrument_entry_counters.py` modifies ignored extracted OCaml in
`stage2/fstarc.ml`. Build `stage3/dune/fstarc-full/fstarc3_full.exe` afterward
and run it with `--version` to confirm that startup does not execute the changed
helpers.

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
