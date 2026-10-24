#!/usr/bin/env python3

import argparse
import fcntl
import hashlib
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


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_time(path):
    text = path.read_text()
    elapsed = re.search(r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M)
    fields = elapsed.group(1).split(":")
    seconds = float(fields[-1])
    if len(fields) >= 2:
        seconds += 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[-3])
    rss = re.search(r"Maximum resident set size \(kbytes\): ([0-9]+)$", text, re.M)
    return seconds, int(rss.group(1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--interning", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    roots = {
        "master": args.master.resolve(),
        "interning": args.interning.resolve(),
        "candidate": args.candidate.resolve(),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    provenance = {
        "z3_sha256": sha256(args.z3.resolve()),
        "variants": {
            variant: {
                "commit": subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
                ).strip(),
                "binary_sha256": sha256(root / "stage3/out/bin/fstar.exe"),
            }
            for variant, root in roots.items()
        },
        "sources": {
            variant: {
                module: sha256(root / path)
                for module, path in MODULES.items()
            }
            for variant, root in roots.items()
        },
    }
    provenance_file = args.output / "provenance.json"
    if provenance_file.exists():
        if json.loads(provenance_file.read_text()) != provenance:
            raise RuntimeError("output directory contains incompatible provenance")
    else:
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    results = args.output / "measurements.jsonl"
    completed = set()
    if results.exists():
        for line in results.read_text().splitlines():
            row = json.loads(line)
            completed.add(
                (row["variant"], row["module"], row["mode"], row["repeat"])
            )
    jobs = [
        (variant, module, mode, repeat)
        for repeat in range(1, args.repetitions + 1)
        for variant in roots
        for module in MODULES
        for mode in ("write", "no-write")
        if (variant, module, mode, repeat) not in completed
    ]
    random.Random(4774).shuffle(jobs)
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
        environment = os.environ.copy()
        environment["FSTAR_MEM_REPORT"] = str(mem_file)
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            str(root / "stage3/out/bin/fstar.exe"),
            "--z3version", "5.3.0", "--smt", str(args.z3.resolve()),
            "--smtencoding.elim_box", "true",
            "--cache_dir", str(cache), "--odir", str(cache),
            "--already_cached", "Prims,FStar",
        ]
        if mode == "write":
            command.append("--cache_checked_modules")
        command.append(str(root / MODULES[module]))
        with log_file.open("w") as log:
            process = subprocess.run(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
        if process.returncode != 0:
            raise RuntimeError(f"{stem} failed; see {log_file}")
        wall, rss = parse_time(time_file)
        row = {
            "variant": variant,
            "module": module,
            "mode": mode,
            "repeat": repeat,
            "command": command,
            "wall_seconds": wall,
            "max_rss_kb": rss,
            "fstar_mempeak_bytes": int(mem_file.read_text().split()[1]),
            "checked_bytes": checked.stat().st_size if checked.exists() else 0,
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
