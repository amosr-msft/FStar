#!/usr/bin/env python3

import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_output(path, expected):
    if path.is_symlink():
        raise RuntimeError("output must not be a symlink")
    if path.exists():
        marker = path / "provenance.json"
        if not path.is_dir() or not marker.is_file():
            raise RuntimeError("refusing to replace unmarked output")
        previous = json.loads(marker.read_text())
        if previous != expected:
            raise RuntimeError("existing output provenance differs")
        shutil.rmtree(path)
    path.mkdir(parents=True)


def elapsed(text):
    fields = re.search(
        r"Elapsed \(wall clock\) time.*: ([0-9:.]+)$", text, re.M
    ).group(1).split(":")
    seconds = float(fields[-1])
    if len(fields) >= 2:
        seconds += 60 * int(fields[-2])
    if len(fields) == 3:
        seconds += 3600 * int(fields[-3])
    return seconds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--stream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    z3_hash = sha256(args.z3.resolve())
    if z3_hash != (
        "4da6a0f78424098b600a9112ebb9d8ce45de248a4913c26dd7d472e6dabef6d3"
    ):
        raise RuntimeError("unexpected Z3 binary")
    provenance = {
        "runner_sha256": sha256(Path(__file__)),
        "z3_sha256": z3_hash,
        "z3_path": str(args.z3.resolve()),
        "stream_sha256": sha256(args.stream.resolve()),
        "stream_path": str(args.stream.resolve()),
        "stream_bytes": args.stream.stat().st_size,
        "repetitions": args.repetitions,
    }
    prepare_output(args.output, provenance)
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    results = []
    order = list(range(1, args.repetitions + 1))
    random.Random(4777).shuffle(order)
    for repeat in order:
        time_file = args.output / f"repeat-{repeat}.time"
        stdout_file = args.output / f"repeat-{repeat}.out"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            str(args.z3.resolve()), "-smt2", str(args.stream.resolve()),
        ]
        with stdout_file.open("w") as stream:
            process = subprocess.run(
                command, stdout=stream, stderr=subprocess.STDOUT
            )
        if process.returncode != 0:
            raise RuntimeError(f"replay {repeat} failed")
        timing = time_file.read_text()
        output = stdout_file.read_text()
        results.append({
            "repeat": repeat,
            "wall_seconds": elapsed(timing),
            "user_seconds": float(re.search(
                r"User time \(seconds\): ([0-9.]+)$", timing, re.M
            ).group(1)),
            "system_seconds": float(re.search(
                r"System time \(seconds\): ([0-9.]+)$", timing, re.M
            ).group(1)),
            "max_rss_kb": int(re.search(
                r"Maximum resident set size \(kbytes\): ([0-9]+)$",
                timing, re.M,
            ).group(1)),
            "unsat_count": len(re.findall(r"^unsat$", output, re.M)),
            "command": command,
        })
    (args.output / "measurements.json").write_text(
        json.dumps(sorted(results, key=lambda row: row["repeat"]), indent=2)
        + "\n"
    )


if __name__ == "__main__":
    main()
