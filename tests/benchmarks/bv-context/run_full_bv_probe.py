#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


PROBES = (
    ("baseline", ()),
    ("no-ambients", ("--ext", "context_pruning_no_ambients")),
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elapsed_seconds(text):
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
    parser.add_argument("--fstar", type=Path, required=True)
    parser.add_argument("--z3", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument(
        "--only", choices=tuple(probe for probe, _ in PROBES),
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent
    selected = [
        (probe, options)
        for probe, options in PROBES
        if args.only is None or probe == args.only
    ]
    provenance = {
        "fstar_sha256": sha256(args.fstar),
        "z3_sha256": sha256(args.z3),
        "source_sha256": sha256(args.source),
        "runner_sha256": sha256(Path(__file__)),
        "probe_plan": [
            {"probe": probe, "options": list(options)}
            for probe, options in selected
        ],
    }
    provenance_file = args.output / "provenance.json"
    if provenance_file.exists():
        if json.loads(provenance_file.read_text()) != provenance:
            raise RuntimeError("incompatible provenance")
    else:
        provenance_file.write_text(json.dumps(provenance, indent=2) + "\n")
    results = args.output / "measurements.jsonl"
    completed = set()
    if results.exists():
        for line in results.read_text().splitlines():
            completed.add(json.loads(line)["probe"])
    for probe, options in selected:
        if probe in completed:
            continue
        log_file = args.output / f"{probe}.log"
        time_file = args.output / f"{probe}.time"
        command = [
            "/usr/bin/time", "-v", "-o", str(time_file),
            "timeout", "--kill-after=5s", f"{args.timeout}s",
            str(args.fstar), "--z3version", "5.3.0", "--smt", str(args.z3),
            "--timing", "--query_stats", *options, str(args.source),
        ]
        with log_file.open("w") as log:
            process = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT
            )
        if process.returncode != 0:
            raise RuntimeError(f"{probe} failed; see {log_file}")
        text = log_file.read_text()
        declarations = [
            int(value)
            for value in re.findall(
                r"BvModelAgreesWithZ3\.[^,]+, profiled "
                r"FStarC\.TypeChecker\.Tc\.process_one_decl:\s+([0-9]+) ms",
                text,
            )
        ]
        queries = [
            (float(seconds), float(rlimit))
            for seconds, rlimit in re.findall(
                r"Query-stats \(BvModelAgreesWithZ3\.[^,]+, 1\).*?"
                r"succeeded in ([0-9.]+) seconds.*?used rlimit ([0-9.]+)",
                text,
            )
        ]
        time_text = time_file.read_text()
        row = {
            "probe": probe,
            "options": list(options),
            "wall_seconds": elapsed_seconds(time_text),
            "max_rss_kb": int(re.search(
                r"Maximum resident set size \(kbytes\): ([0-9]+)$",
                time_text, re.M,
            ).group(1)),
            "profiled_declaration_count": len(declarations),
            "profiled_declaration_ms": sum(declarations),
            "query_count": len(queries),
            "z3_reported_seconds": sum(seconds for seconds, _ in queries),
            "last_rlimit": queries[-1][1],
            "command": command,
        }
        with results.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
