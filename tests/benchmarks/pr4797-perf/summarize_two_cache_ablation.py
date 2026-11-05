#!/usr/bin/env python3

import argparse
import hashlib
import json
import statistics
from pathlib import Path


METRICS = (
    "root_cpu_seconds",
    "child_cpu_seconds",
    "wall_seconds",
    "peak_group_rss_bytes",
    "fstar_heap_peak_bytes",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def campaign(path):
    root = path.resolve()
    provenance = json.loads((root / "provenance.json").read_text())
    rows = [
        json.loads(line)
        for line in (root / "measurements.jsonl").read_text().splitlines()
    ]
    summary = {}
    for workload in sorted({row["workload"] for row in rows}):
        selected = [row for row in rows if row["workload"] == workload]
        repetitions = (
            provenance["dependency_repetitions"]
            if workload == "dependency"
            else provenance["source_repetitions"]
        )
        paired = {}
        for metric in METRICS:
            deltas = []
            for repeat in range(1, repetitions + 1):
                pair = {
                    row["variant"]: row
                    for row in selected
                    if row["repeat"] == repeat
                }
                deltas.append(
                    pair["two"][metric] - pair["three"][metric]
                )
            paired[metric] = {
                "observations": deltas,
                "median": statistics.median(deltas),
                "mean": statistics.mean(deltas),
                "positive": sum(delta > 0 for delta in deltas),
            }
        summary[workload] = {
            "repetitions": repetitions,
            "paired_two_minus_three": paired,
        }
    return {
        "provenance": provenance,
        "measurements_sha256": sha256(root / "measurements.jsonl"),
        "rows": rows,
        "summary": summary,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--rebuilt", type=Path, required=True)
    parser.add_argument("--hot", type=Path, required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    hot = json.loads((args.hot.resolve() / "result.json").read_text())
    memory = json.loads(
        (args.memory.resolve() / "result.json").read_text()
    )
    output = {
        "original_two_cache_build": campaign(args.original),
        "rebuilt_two_cache_build": campaign(args.rebuilt),
        "hot_lookup": hot,
        "memory_diagnostic": memory,
        "evidence": {
            "hot_sha256": sha256(args.hot.resolve() / "result.json"),
            "memory_sha256":
                sha256(args.memory.resolve() / "result.json"),
            "script_sha256": sha256(Path(__file__)),
        },
        "limitations": [
            "The two-cache ablation intentionally does not preserve physical string identity.",
            "Memory snapshots use forced major GC and separate native builds.",
            "CPU sampling has approximately 10 ms resolution.",
            "CPU affinity does not reserve CPU 16.",
        ],
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
