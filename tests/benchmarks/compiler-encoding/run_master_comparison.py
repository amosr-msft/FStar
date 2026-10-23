#!/usr/bin/env python3

import argparse
import fcntl
import json
import os
import random
import re
import subprocess
from pathlib import Path


VARIANTS = ("master", "interning")
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--interning", type=Path, required=True)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    roots = {"master": args.master.resolve(), "interning": args.interning.resolve()}
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    results = args.output / "measurements.jsonl"
    completed_keys = set()
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            completed_keys.add(
                (row["variant"], row["module"], row["mode"], row["repeat"])
            )
    environment = os.environ.copy()
    jobs = [
        (variant, module, mode, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in VARIANTS for module in MODULES
        for mode in ("write", "no-write")
        if (variant, module, mode, repeat) not in completed_keys
    ]
    random.Random(4769).shuffle(jobs)
    for variant, module, mode, repeat in jobs:
        root = roots[variant]
        cache = args.output / f"cache-{variant}"
        checked = cache / f"{module}.fst.checked"
        checked.unlink(missing_ok=True)
        stem = f"{repeat:02d}-{module}-{variant}-{mode}"
        time_file = args.output / f"{stem}.time"
        mem_file = args.output / f"{stem}.fstarmem"
        log_file = args.output / f"{stem}.log"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "env", f"FSTAR_MEM_REPORT={mem_file}",
            str(root / "stage3/out/bin/fstar.exe"),
            "--z3version", "5.3.0", "--smt", str(args.z3.resolve()),
            "--smtencoding.elim_box", "true", "--timing",
            "--include", str(args.generated), "--cache_dir", str(cache),
            "--odir", str(cache), "--already_cached", "Prims,FStar",
        ]
        if mode == "write":
            command.append("--cache_checked_modules")
        command.append(str(args.generated / f"{module}.fst"))
        with log_file.open("w") as log:
            completed = subprocess.run(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
        if completed.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_file}")
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


if __name__ == "__main__":
    main()
