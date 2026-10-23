#!/usr/bin/env python3

import argparse
import fcntl
import json
import os
import random
import re
import subprocess
import time
from pathlib import Path


VARIANTS = ("original-a", "original-b", "fusion", "combined")
MODULES = ("BenchBvLive500", "BenchUIntLive500")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree-prefix", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--z3-bin-dir", type=Path, required=True)
    parser.add_argument("--instrumented-dir", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    results = args.output / "measurements.jsonl"
    done = set()
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            done.add((row["variant"], row["module"], row["repeat"]))
    env = os.environ.copy()
    env["PATH"] = f"{args.z3_bin_dir.resolve()}:{env['PATH']}"
    jobs = [
        (variant, module, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in VARIANTS for module in MODULES
        if (variant, module, repeat) not in done
    ]
    random.Random(4766).shuffle(jobs)
    for variant, module, repeat in jobs:
        compiler = (
            args.instrumented_dir / f"fstar-{variant}.exe"
            if args.instrumented_dir
            else Path(f"{args.worktree_prefix}-{variant}") / "stage3/out/bin/fstar.exe"
        )
        worktree = Path(f"{args.worktree_prefix}-{variant}")
        while any(
            "fstar.exe" in command and str(compiler) not in command
            for command in subprocess.run(
                ["ps", "-eo", "args="], text=True, capture_output=True, check=True
            ).stdout.splitlines()
        ):
            time.sleep(5)
        cache = args.cache_root / f"cache-{variant}"
        (cache / f"{module}.fst.checked").unlink(missing_ok=True)
        stem = f"{repeat:02d}-{module}-{variant}"
        log_file = args.output / f"{stem}.log"
        time_file = args.output / f"{stem}.time"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "env", "OCAMLRUNPARAM=v=0x400",
            str(compiler), "--z3version", "5.3.0",
            "--smt", str(args.z3_bin_dir.resolve() / "z3-5.3.0"),
            "--smtencoding.elim_box", "true", "--query_stats",
            "--include", str(worktree / "stage3/out/lib/fstar/ulib"),
            "--include", str(worktree / "stage3/out/lib/fstar/ulib.checked"),
            "--profile", module,
            "--profile_component", "FStarC.CheckedFiles",
            "--profile_component", "FStarC.TypeChecker",
            "--profile_component", "FStarC.SMTEncoding",
            "--include", str(args.generated),
            "--cache_dir", str(cache), "--odir", str(cache),
            "--already_cached", "Prims,FStar",
            str(args.generated / f"{module}.fst"),
        ]
        if args.instrumented_dir:
            env["FSTAR_SHARING_ANALYSIS"] = "1"
        print("RUN", stem, flush=True)
        with log_file.open("w") as log:
            completed = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_file}")
        text = log_file.read_text()
        value = lambda pattern: re.search(pattern, text, re.M).group(1)
        sharing = {}
        for phase, wall, cpu, allocated, promoted, major, minor_gc, major_gc, heap, peak in re.findall(
            r"SHARING_ANALYSIS,(decls|index),([0-9.]+),([0-9.]+),([0-9.]+),"
            r"([0-9.]+),([0-9.]+),(\d+),(\d+),(\d+),(\d+)", text
        ):
            sharing[f"{phase}_wall_ms"] = float(wall)
            sharing[f"{phase}_cpu_ms"] = float(cpu)
            sharing[f"{phase}_allocated_words"] = int(float(allocated))
            sharing[f"{phase}_promoted_words"] = int(float(promoted))
            sharing[f"{phase}_major_words"] = int(float(major))
            sharing[f"{phase}_minor_collections"] = int(minor_gc)
            sharing[f"{phase}_major_collections"] = int(major_gc)
            sharing[f"{phase}_heap_words_after"] = int(heap)
            sharing[f"{phase}_top_heap_words_after"] = int(peak)
        row = {
            "variant": variant, "module": module, "repeat": repeat,
            "command": command,
            "total_profile_ms": int(value(r"TOTAL TIME (\d+) ms")),
            "intern_decls_ms": int(value(r"Sharing\.intern_decls:\s+(\d+) ms")),
            "intern_index_ms": int(value(r"Sharing\.intern_index:\s+(\d+) ms")),
            "z3_aggregate_ms": sum(
                int(x) for x in re.findall(r"Z3 \(aggregate query time\):\s+(\d+) ms", text)
            ),
            "allocated_words": int(value(r"^allocated_words: (\d+)$")),
            "promoted_words": int(value(r"^promoted_words: (\d+)$")),
            "major_words": int(value(r"^major_words: (\d+)$")),
            "minor_collections": int(value(r"^minor_collections: (\d+)$")),
            "major_collections": int(value(r"^major_collections: (\d+)$")),
            "top_heap_words": int(value(r"^top_heap_words: (\d+)$")),
            **sharing,
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print("DONE", stem, row["total_profile_ms"], flush=True)


if __name__ == "__main__":
    main()
