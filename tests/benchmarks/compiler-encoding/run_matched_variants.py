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


def parse_time(path):
    text = path.read_text()
    elapsed = re.search(r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M)
    fields = elapsed.group(1).split(":")
    seconds = float(fields[-1])
    if len(fields) >= 2:
        seconds += 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[-3])
    value = lambda pattern: re.search(pattern, text, re.M).group(1)
    return {
        "wall_seconds": seconds,
        "user_seconds": float(value(r"User time \(seconds\): ([0-9.]+)$")),
        "system_seconds": float(value(r"System time \(seconds\): ([0-9.]+)$")),
        "max_rss_kb": int(value(r"Maximum resident set size \(kbytes\): (\d+)$")),
    }

def external_fstar_running(own_compiler):
    processes = subprocess.run(
        ["ps", "-eo", "args="], text=True, capture_output=True, check=True
    ).stdout.splitlines()
    return any(
        "fstar.exe" in command and str(own_compiler) not in command
        for command in processes
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree-prefix", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--z3-bin-dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=4765)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    results = args.output / "measurements.jsonl"
    done = set()
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            done.add((row["variant"], row["module"], row["mode"], row["repeat"]))
    env = os.environ.copy()
    env["PATH"] = f"{args.z3_bin_dir.resolve()}:{env['PATH']}"
    jobs = [
        (variant, module, mode, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in VARIANTS
        for module in MODULES
        for mode in ("write", "no-write")
        if (variant, module, mode, repeat) not in done
    ]
    random.Random(args.seed).shuffle(jobs)
    pending = list(jobs)
    while pending:
        variant, module, mode, repeat = pending.pop(0)
        worktree = Path(f"{args.worktree_prefix}-{variant}")
        compiler = worktree / "stage3/out/bin/fstar.exe"
        while external_fstar_running(compiler):
            time.sleep(5)
        cache = args.output / f"cache-{variant}"
        checked = cache / f"{module}.fst.checked"
        checked.unlink(missing_ok=True)
        stem = f"{repeat:02d}-{module}-{variant}-{mode}"
        time_file = args.output / f"{stem}.time"
        log_file = args.output / f"{stem}.log"
        mem_file = args.output / f"{stem}.fstarmem"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "env", f"FSTAR_MEM_REPORT={mem_file}",
            str(compiler), "--z3version", "5.3.0",
            "--smt", str(args.z3_bin_dir.resolve() / "z3-5.3.0"),
            "--smtencoding.elim_box", "true", "--timing",
            "--include", str(args.generated),
            "--cache_dir", str(cache), "--odir", str(cache),
            "--already_cached", "Prims,FStar",
        ]
        if mode == "write":
            command.append("--cache_checked_modules")
        command.append(str(args.generated / f"{module}.fst"))
        print("RUN", stem, flush=True)
        with log_file.open("w") as log:
            completed = subprocess.Popen(
                command, env=env, stdout=log, stderr=subprocess.STDOUT
            )
            overlapped = False
            while completed.poll() is None:
                time.sleep(1)
                overlapped = overlapped or external_fstar_running(compiler)
        if completed.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_file}")
        if overlapped:
            print("RETRY external overlap", stem, flush=True)
            pending.append((variant, module, mode, repeat))
            continue
        row = {
            "variant": variant, "module": module, "mode": mode, "repeat": repeat,
            "command": command, **parse_time(time_file),
            "fstar_mempeak_bytes": int(mem_file.read_text().split()[1]),
            "checked_bytes": checked.stat().st_size if checked.exists() else 0,
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print("DONE", stem, row["wall_seconds"], flush=True)


if __name__ == "__main__":
    main()
