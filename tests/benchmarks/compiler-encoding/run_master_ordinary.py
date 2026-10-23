#!/usr/bin/env python3

import argparse
import json
import os
import random
import re
import subprocess
from pathlib import Path


MODULES = {
    "Positivity": "tests/micro-benchmarks/Positivity.fst",
    "TestWellFoundedRecursion":
        "tests/micro-benchmarks/TestWellFoundedRecursion.fst",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--interning", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    roots = {"master": args.master.resolve(), "interning": args.interning.resolve()}
    args.output.mkdir(parents=True, exist_ok=True)
    jobs = [
        (variant, module, mode, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in roots for module in MODULES
        for mode in ("write", "no-write")
    ]
    random.Random(4771).shuffle(jobs)
    rows = []
    for variant, module, mode, repeat in jobs:
        root = roots[variant]
        cache = args.output / f"cache-{variant}-{module}"
        cache.mkdir(exist_ok=True)
        checked = cache / f"{module}.fst.checked"
        checked.unlink(missing_ok=True)
        stem = f"{repeat}-{module}-{variant}-{mode}"
        time_file = args.output / f"{stem}.time"
        mem_file = args.output / f"{stem}.fstarmem"
        log_file = args.output / f"{stem}.log"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "env", f"FSTAR_MEM_REPORT={mem_file}",
            str(root / "stage3/out/bin/fstar.exe"),
            "--z3version", "5.3.0", "--smt", str(args.z3.resolve()),
            "--smtencoding.elim_box", "true", "--cache_dir", str(cache),
            "--odir", str(cache), "--already_cached", "Prims,FStar",
        ]
        if mode == "write":
            command.append("--cache_checked_modules")
        command.append(str(root / MODULES[module]))
        with log_file.open("w") as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if completed.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_file}")
        timing = time_file.read_text()
        elapsed = re.search(r"Elapsed.*: (?:(\d+):)?(\d+):([0-9.]+)", timing)
        wall = (
            3600 * int(elapsed.group(1) or 0)
            + 60 * int(elapsed.group(2))
            + float(elapsed.group(3))
        )
        rows.append({
            "variant": variant, "module": module, "mode": mode, "repeat": repeat,
            "command": command, "wall_seconds": wall,
            "fstar_mempeak_bytes": int(mem_file.read_text().split()[1]),
            "checked_bytes": checked.stat().st_size if checked.exists() else 0,
        })
    (args.output / "measurements.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
